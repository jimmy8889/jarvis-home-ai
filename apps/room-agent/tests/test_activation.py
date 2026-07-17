from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile
import unittest

from pilot_room_agent.activation import ActivationGate, configuration_fingerprint
from pilot_room_agent.config import Settings


class ActivationGateTests(unittest.TestCase):
    def test_requires_matching_supervised_acceptance_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activation.json"
            settings = Settings(
                room_id="office",
                speaker_node="k3",
                playback_alsa_device="pipewire",
                audio_activation_state_path=str(path),
            )
            self.assertFalse(ActivationGate(settings).status()["allowed"])
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "armed": True,
                        "room_id": "office",
                        "accepted_at": datetime.now(UTC).isoformat(),
                        "configuration_fingerprint": configuration_fingerprint(
                            settings
                        ),
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o640)
            self.assertTrue(ActivationGate(settings).status()["allowed"])

            changed = Settings(
                room_id="office",
                speaker_node="different-output",
                playback_alsa_device="pipewire",
                audio_activation_state_path=str(path),
            )
            status = ActivationGate(changed).status()
            self.assertFalse(status["allowed"])
            self.assertEqual(status["reason"], "configuration_changed")

    def test_can_be_explicitly_disabled_for_development(self) -> None:
        settings = Settings(audio_activation_required=False)
        status = ActivationGate(settings).status()
        self.assertTrue(status["allowed"])
        self.assertEqual(status["reason"], "not_required")


if __name__ == "__main__":
    unittest.main()
