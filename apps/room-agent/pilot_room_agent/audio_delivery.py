from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import tempfile
from threading import Lock, Thread
import time
from typing import Any, Callable
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from .config import Settings
from .controls import ControlError, ControlState


CONTENT_TYPE_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
}
ASSET_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class AudioFetcher:
    """Fetches room-bound audio only from the configured Pilot Core."""

    def __init__(
        self,
        settings: Settings,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self.opener = opener or urlopen
        self.cache = Path(settings.audio_cache_path)

    def fetch(self, payload: dict[str, Any]) -> Path:
        asset_id = payload.get("audio_asset_id")
        digest = payload.get("sha256")
        size_bytes = payload.get("size_bytes")
        content_type = payload.get("content_type")
        if not isinstance(asset_id, str) or not ASSET_ID_PATTERN.fullmatch(asset_id):
            raise ControlError("invalid audio_asset_id")
        if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
            raise ControlError("invalid audio asset digest")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or not 1 <= size_bytes <= self.settings.audio_max_bytes
        ):
            raise ControlError("invalid audio asset size")
        if not isinstance(content_type, str):
            raise ControlError("invalid audio content type")
        normalized_type = content_type.partition(";")[0].strip().lower()
        extension = CONTENT_TYPE_EXTENSIONS.get(normalized_type)
        if extension is None:
            raise ControlError("unsupported audio content type")

        self._cleanup_cache()
        path = self.cache / f"{asset_id}{extension}"
        if path.is_file() and self._matches(path, digest, size_bytes):
            return path

        token = Path(self.settings.core_device_token_file).read_text(
            encoding="utf-8"
        ).strip()
        if not token:
            raise ControlError("Pilot Core device token is empty")
        base = self.settings.core_url.rstrip("/") + "/"
        url = urljoin(base, f"v1/audio-assets/{quote(asset_id, safe='')}")
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Pilot-Device-ID": self.settings.core_device_id,
                "Accept": normalized_type,
            },
        )

        temporary_name = ""
        try:
            with self.opener(
                request, timeout=self.settings.audio_download_timeout_seconds
            ) as response:
                returned_type = response.headers.get_content_type().lower()
                if returned_type != normalized_type:
                    raise ControlError("Pilot Core returned an unexpected content type")
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=self.cache, prefix=f".{asset_id}.", delete=False
                ) as temporary:
                    temporary_name = temporary.name
                    hasher = sha256()
                    received = 0
                    while True:
                        chunk = response.read(65_536)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > self.settings.audio_max_bytes:
                            raise ControlError("downloaded audio exceeds the size limit")
                        temporary.write(chunk)
                        hasher.update(chunk)
            if received != size_bytes:
                raise ControlError("downloaded audio size does not match its manifest")
            if hasher.hexdigest() != digest:
                raise ControlError("downloaded audio digest does not match its manifest")
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
            return path
        except ControlError:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as error:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise ControlError(f"audio download failed: {error}") from error

    @staticmethod
    def _matches(path: Path, digest: str, size_bytes: int) -> bool:
        if path.stat().st_size != size_bytes:
            return False
        hasher = sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65_536):
                hasher.update(chunk)
        return hasher.hexdigest() == digest

    def _cleanup_cache(self) -> None:
        self.cache.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - self.settings.audio_cache_retention_seconds
        for path in self.cache.iterdir():
            if not path.is_file() or path.stat().st_mtime > cutoff:
                continue
            if ASSET_ID_PATTERN.fullmatch(path.stem) or path.name.startswith("."):
                path.unlink(missing_ok=True)


class AudioPlayback:
    """Owns the single transient assistant/announcement playback slot."""

    def __init__(
        self,
        state: ControlState,
        fetcher: AudioFetcher,
        popen: Callable[..., Any] | None = None,
    ) -> None:
        self.state = state
        self.fetcher = fetcher
        self.popen = popen or subprocess.Popen
        self.lock = Lock()
        self.process: Any | None = None
        self.generation = 0
        self.asset_id = ""
        self.kind = ""
        self.started_at: str | None = None

    def play(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = payload.get("kind")
        if kind not in {"assistant", "announcement"}:
            raise ControlError("audio kind must be assistant or announcement")
        critical = payload.get("critical", False)
        if not isinstance(critical, bool):
            raise ControlError("critical must be a boolean")
        if critical and kind != "announcement":
            raise ControlError("only announcements may be critical")
        volume = payload.get("volume", 1.0)
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not 0 <= volume <= 1
        ):
            raise ControlError("volume must be between 0 and 1")
        path = self.fetcher.fetch(payload)

        with self.lock:
            self._stop_locked()
            try:
                process = self.popen(
                    ["pw-play", "--volume", f"{float(volume):.4f}", str(path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as error:
                raise ControlError(f"audio playback failed: {error}") from error
            self.process = process
            self.generation += 1
            generation = self.generation
            self.asset_id = str(payload["audio_asset_id"])
            self.kind = str(kind)
            self.started_at = datetime.now(UTC).isoformat()
            self._set_state(kind, critical, True)
        Thread(
            target=self._watch,
            args=(process, generation, kind),
            name="pilot-audio-playback",
            daemon=True,
        ).start()
        return {
            "audio_asset_id": self.asset_id,
            "kind": kind,
            "critical": critical,
            "volume": float(volume),
            "started": True,
        }

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            stopped = self.process is not None
            self._stop_locked()
            self.state.set("assistant_speaking", False)
            self.state.set("announcement_active", False)
            self.state.set("critical_announcement", False)
        return {"audio_playback_stopped": stopped}

    def close(self) -> None:
        self.cancel()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "enabled": True,
                "active": self.process is not None,
                "audio_asset_id": self.asset_id or None,
                "kind": self.kind or None,
                "started_at": self.started_at,
            }

    def _stop_locked(self) -> None:
        process = self.process
        previous_kind = self.kind
        self.process = None
        self.generation += 1
        self.asset_id = ""
        self.kind = ""
        self.started_at = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        if previous_kind:
            self._set_state(previous_kind, False, False)

    def _watch(self, process: Any, generation: int, kind: str) -> None:
        try:
            process.wait()
        except OSError:
            pass
        with self.lock:
            if self.process is not process or self.generation != generation:
                return
            self.process = None
            self.asset_id = ""
            self.kind = ""
            self.started_at = None
            self._set_state(kind, False, False)

    def _set_state(self, kind: str, critical: bool, active: bool) -> None:
        if kind == "assistant":
            self.state.set("assistant_speaking", active, 300 if active else None)
            return
        self.state.set("announcement_active", active, 300 if active else None)
        self.state.set(
            "critical_announcement", active and critical, 300 if active else None
        )
