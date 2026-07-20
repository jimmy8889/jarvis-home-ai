from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess
from threading import Lock
import time
from typing import Any, Callable

from .config import Settings
from .controls import ControlError


_MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _./()'&,+-]{0,500}$")
_EXTENSIONS = frozenset(
    {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"}
)


class MpvPlayback:
    """Supervised, local-library-only mpv JSON IPC adapter."""

    def __init__(
        self,
        settings: Settings,
        *,
        process_factory: Callable[..., Any] | None = None,
        socket_factory: Callable[..., socket.socket] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.process_factory = process_factory or subprocess.Popen
        self.socket_factory = socket_factory or socket.socket
        self.clock = clock or time.monotonic
        self.lock = Lock()
        self.process: Any | None = None

    def status(self) -> dict[str, Any]:
        if not self.settings.video_enabled:
            return {"enabled": False, "available": False}
        available = self._ping()
        state: dict[str, Any] = {
            "enabled": True,
            "available": available,
            "library_roots": len(self.settings.video_media_roots),
        }
        if available:
            for key in ("pause", "time-pos", "duration", "filename", "media-title"):
                try:
                    state[key.replace("-", "_")] = self._property(key)
                except ControlError:
                    state[key.replace("-", "_")] = None
        return state

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.video_enabled:
            raise ControlError("local video playback is disabled")
        with self.lock:
            if action == "video_play":
                media_id = payload.get("media_id")
                path = self._resolve_media(media_id)
                self._ensure_started()
                self._command(["loadfile", str(path), "replace"])
                return {"media_id": str(media_id), "state": "loading"}
            self._ensure_started()
            if action == "video_pause":
                self._command(["set_property", "pause", True])
            elif action == "video_resume":
                self._command(["set_property", "pause", False])
            elif action == "video_stop":
                self._command(["stop"])
            elif action == "video_seek":
                seconds = self._bounded_number(payload.get("seconds"), -3600, 3600)
                self._command(["seek", seconds, "relative+exact"])
            elif action in {"video_audio_track", "video_subtitle_track"}:
                track = payload.get("track")
                if isinstance(track, bool) or not isinstance(track, int) or not 0 <= track <= 128:
                    raise ControlError("track must be an integer between 0 and 128")
                prop = "aid" if action == "video_audio_track" else "sid"
                self._command(["set_property", prop, "no" if track == 0 else track])
            else:
                raise ControlError(f"unsupported video action: {action}")
            return {"state": self.status()}

    def close(self) -> None:
        with self.lock:
            if self._ping():
                try:
                    self._command(["quit"])
                except ControlError:
                    pass
            process = self.process
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.process = None

    def cancel(self) -> dict[str, bool]:
        with self.lock:
            if not self._ping():
                return {"video_playback_stopped": False}
            self._command(["stop"])
            return {"video_playback_stopped": True}

    def _resolve_media(self, media_id: Any) -> Path:
        if not isinstance(media_id, str) or not _MEDIA_ID.fullmatch(media_id):
            raise ControlError("media_id is invalid")
        relative = Path(media_id)
        if relative.is_absolute() or ".." in relative.parts or "\\" in media_id:
            raise ControlError("media_id must be a safe relative library path")
        if relative.suffix.casefold() not in _EXTENSIONS:
            raise ControlError("media type is not allowed")
        for root_value in self.settings.video_media_roots:
            root = Path(root_value).expanduser().resolve()
            candidate = (root / relative).resolve()
            if root not in candidate.parents:
                continue
            if candidate.is_file():
                return candidate
        raise ControlError("media item was not found in an allowed library")

    def _ensure_started(self) -> None:
        if self._ping():
            return
        ipc = Path(self.settings.video_ipc_path)
        ipc.parent.mkdir(parents=True, exist_ok=True)
        ipc.unlink(missing_ok=True)
        command = [
            "mpv",
            "--idle=yes",
            "--force-window=yes",
            "--no-terminal",
            f"--input-ipc-server={ipc}",
            f"--hwdec={self.settings.video_hwdec}",
            f"--audio-device={self.settings.video_audio_device}",
            "--save-position-on-quit=no",
            "--watch-later-options=start",
        ]
        if self.settings.video_display:
            command.append(f"--screen={self.settings.video_display}")
        try:
            self.process = self.process_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as error:
            raise ControlError(f"unable to start mpv: {error}") from error
        deadline = self.clock() + float(self.settings.video_start_timeout_seconds)
        while self.clock() < deadline:
            if self.process.poll() is not None:
                raise ControlError("mpv exited before its control socket became ready")
            if self._ping():
                return
            time.sleep(0.05)
        raise ControlError("mpv control socket did not become ready")

    def _ping(self) -> bool:
        try:
            self._request({"command": ["get_property", "idle-active"]})
            return True
        except ControlError:
            return False

    def _property(self, name: str) -> Any:
        return self._request({"command": ["get_property", name]}).get("data")

    def _command(self, command: list[Any]) -> dict[str, Any]:
        return self._request({"command": command})

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(request, separators=(",", ":")).encode() + b"\n"
        client = self.socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(2)
            client.connect(self.settings.video_ipc_path)
            client.sendall(payload)
            response = b""
            while b"\n" not in response and len(response) < 1_000_000:
                chunk = client.recv(65_536)
                if not chunk:
                    break
                response += chunk
        except (OSError, TimeoutError) as error:
            raise ControlError(f"mpv IPC unavailable: {error}") from error
        finally:
            client.close()
        try:
            result = json.loads(response.split(b"\n", 1)[0])
        except (json.JSONDecodeError, UnicodeDecodeError, IndexError) as error:
            raise ControlError("mpv returned an invalid response") from error
        if not isinstance(result, dict) or result.get("error") != "success":
            raise ControlError(str(result.get("error", "mpv command failed")))
        return result

    @staticmethod
    def _bounded_number(value: Any, minimum: float, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ControlError("seconds must be a number")
        selected = float(value)
        if not minimum <= selected <= maximum:
            raise ControlError(f"seconds must be between {minimum:g} and {maximum:g}")
        return selected
