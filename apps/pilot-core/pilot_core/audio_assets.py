from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import secrets
from typing import Any

from .storage import Store


CONTENT_TYPE_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
}


class AudioAssetError(ValueError):
    """An invalid or unavailable room audio asset."""


class AudioAssets:
    def __init__(
        self,
        store: Store,
        root: str,
        max_bytes: int,
        default_retention_seconds: int,
    ) -> None:
        self.store = store
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.default_retention_seconds = default_retention_seconds

    def create(
        self,
        room_id: str,
        kind: str,
        filename: str,
        content_type: str,
        content: bytes,
        retention_seconds: int | None = None,
    ) -> dict[str, Any]:
        self.cleanup()
        if kind not in {"assistant", "announcement"}:
            raise AudioAssetError("kind must be assistant or announcement")
        normalized_type = content_type.partition(";")[0].strip().lower()
        extension = CONTENT_TYPE_EXTENSIONS.get(normalized_type)
        if extension is None:
            raise AudioAssetError("unsupported audio content type")
        if not content:
            raise AudioAssetError("audio asset is empty")
        if len(content) > self.max_bytes:
            raise AudioAssetError(
                f"audio asset exceeds the {self.max_bytes}-byte limit"
            )
        retention = retention_seconds or self.default_retention_seconds
        if not 60 <= retention <= 86_400:
            raise AudioAssetError("retention_seconds must be between 60 and 86400")

        self.root.mkdir(parents=True, exist_ok=True)
        asset_id = secrets.token_hex(16)
        path = self.root / f"{asset_id}{extension}"
        temporary = self.root / f".{asset_id}.tmp"
        temporary.write_bytes(content)
        temporary.chmod(0o600)
        temporary.replace(path)
        safe_filename = Path(filename or f"speech{extension}").name[:200]
        expires_at = (datetime.now(UTC) + timedelta(seconds=retention)).isoformat()
        try:
            return self.store.create_audio_asset(
                asset_id,
                room_id,
                kind,
                safe_filename,
                normalized_type,
                sha256(content).hexdigest(),
                len(content),
                str(path),
                expires_at,
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def get(self, asset_id: str) -> dict[str, Any] | None:
        self.cleanup()
        asset = self.store.get_audio_asset(asset_id)
        if asset is None:
            return None
        if not Path(asset["path"]).is_file():
            self.store.delete_audio_asset(asset_id)
            return None
        return asset

    def list(self, room_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.cleanup()
        return self.store.list_audio_assets(room_id, limit)

    def delete(self, asset_id: str) -> bool:
        path = self.store.delete_audio_asset(asset_id)
        if path is None:
            return False
        Path(path).unlink(missing_ok=True)
        return True

    def cleanup(self) -> int:
        paths = self.store.purge_expired_audio_assets()
        for path in paths:
            Path(path).unlink(missing_ok=True)
        return len(paths)

    @staticmethod
    def public_view(asset: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in asset.items() if key != "path"}
