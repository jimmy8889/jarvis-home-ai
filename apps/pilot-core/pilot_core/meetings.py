from __future__ import annotations

from collections.abc import AsyncIterator
from hashlib import sha256
import os
from pathlib import Path
import secrets
from typing import Any

from .storage import Store


ALLOWED_RECORDING_TYPES = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
}


class MeetingRecordingError(ValueError):
    pass


class MeetingRecordings:
    def __init__(self, store: Store, path: str, max_bytes: int) -> None:
        self.store = store
        self.root = Path(path)
        self.max_bytes = max_bytes

    async def save(
        self,
        meeting_id: str,
        filename: str,
        content_type: str,
        chunks: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        if self.store.get_meeting(meeting_id) is None:
            raise KeyError(meeting_id)
        normalized_type = content_type.partition(";")[0].strip().lower()
        extension = ALLOWED_RECORDING_TYPES.get(normalized_type)
        if extension is None:
            raise MeetingRecordingError("unsupported meeting recording type")
        safe_name = Path(filename).name.strip() or f"recording{extension}"
        if not safe_name.lower().endswith(extension):
            safe_name += extension

        meeting_directory = self.root / meeting_id
        meeting_directory.mkdir(parents=True, exist_ok=True)
        destination = meeting_directory / f"recording{extension}"
        temporary = meeting_directory / f".upload-{secrets.token_hex(8)}"
        digest = sha256()
        size = 0
        try:
            with temporary.open("xb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise MeetingRecordingError(
                            "meeting recording exceeds configured size limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise MeetingRecordingError("meeting recording is empty")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        return self.store.set_meeting_recording(
            meeting_id,
            safe_name,
            normalized_type,
            digest.hexdigest(),
            size,
            str(destination),
        )
