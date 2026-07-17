from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from pilot_room_agent.activation_cli import _load_receipt
from pilot_room_agent.config import Settings


class ActivationReceiptTests(unittest.TestCase):
    def receipt(self, created_at: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "room_id": "office",
            "created_at": created_at,
            "capture_device": "pipewire",
            "playback_device": "pipewire",
            "speaker_node": "k3",
            "checks": [
                "silent_validation",
                "microphone_capture",
                "speaker_playback",
                "simultaneous_input_output",
            ],
        }

    def test_accepts_recent_matching_receipt(self) -> None:
        settings = Settings(
            room_id="office",
            capture_alsa_device="pipewire",
            playback_alsa_device="pipewire",
            speaker_node="k3",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(
                json.dumps(self.receipt(datetime.now(UTC).isoformat())),
                encoding="utf-8",
            )
            loaded = _load_receipt(path, settings, 3600)
        self.assertEqual(len(loaded["sha256"]), 64)

    def test_rejects_stale_receipt(self) -> None:
        settings = Settings(
            room_id="office",
            capture_alsa_device="pipewire",
            playback_alsa_device="pipewire",
            speaker_node="k3",
        )
        stale = datetime.now(UTC) - timedelta(hours=2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            path.write_text(
                json.dumps(self.receipt(stale.isoformat())), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "stale"):
                _load_receipt(path, settings, 3600)


if __name__ == "__main__":
    unittest.main()
