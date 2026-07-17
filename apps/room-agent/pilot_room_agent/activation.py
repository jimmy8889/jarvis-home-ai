from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import stat
from typing import Any

from . import __version__
from .config import Settings


MAX_STATE_BYTES = 16_384


class ActivationError(RuntimeError):
    """Room audio has not passed the supervised activation gate."""


def configuration_fingerprint(settings: Settings) -> str:
    values = {
        "room_id": settings.room_id,
        "capture_alsa_device": settings.capture_alsa_device,
        "playback_alsa_device": settings.playback_alsa_device,
        "speaker_node": settings.speaker_node,
        "room_agent_version": __version__,
    }
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


class ActivationGate:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings.audio_activation_state_path)

    def status(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "required": self.settings.audio_activation_required,
            "allowed": False,
            "reason": "not_armed",
            "accepted_at": None,
        }
        if not self.settings.audio_activation_required:
            return {**base, "allowed": True, "reason": "not_required"}
        try:
            details = self.path.lstat()
            if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o022:
                return {**base, "reason": "unsafe_state_file"}
            if details.st_size > MAX_STATE_BYTES:
                return {**base, "reason": "invalid_state"}
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return base
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {**base, "reason": "invalid_state"}
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            return {**base, "reason": "invalid_state"}
        if state.get("armed") is not True:
            return {**base, "reason": "disarmed"}
        if state.get("room_id") != self.settings.room_id:
            return {**base, "reason": "room_changed"}
        if state.get("configuration_fingerprint") != configuration_fingerprint(
            self.settings
        ):
            return {**base, "reason": "configuration_changed"}
        return {
            **base,
            "allowed": True,
            "reason": "supervised_acceptance_recorded",
            "accepted_at": state.get("accepted_at"),
        }

    def require(self) -> dict[str, Any]:
        status = self.status()
        if not status["allowed"]:
            raise ActivationError(
                f"room audio activation denied: {status['reason']}"
            )
        return status
