from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pilot_core.config import load_settings


VALID_CONFIG = """
[server]
listen_host = "127.0.0.1"
listen_port = 8770

[[rooms]]
id = "office"
name = "Office"
response_player_id = "office-assistant"
default_music_player_id = "office-music"
default_device_id = "pilot-office"

[[players]]
id = "office-assistant"
room_id = "office"
name = "Office Assistant"
protocol = "pipewire"
kind = "response"

[[players]]
id = "office-music"
room_id = "office"
name = "Pilot Office Music"
protocol = "sendspin"
kind = "music"
"""


class ConfigTests(unittest.TestCase):
    def _load(self, contents: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.toml"
            path.write_text(contents, encoding="utf-8")
            return load_settings(path)

    def test_loads_valid_registry(self) -> None:
        settings = self._load(VALID_CONFIG)
        self.assertEqual(settings.server.listen_port, 8770)
        self.assertEqual(settings.rooms[0].id, "office")
        self.assertEqual(settings.rooms[0].default_device_id, "pilot-office")
        self.assertEqual(settings.players[1].protocol, "sendspin")
        self.assertTrue(settings.players[1].control_enabled)

    def test_can_disable_player_control_without_hiding_state(self) -> None:
        configured = VALID_CONFIG.replace(
            'kind = "music"',
            'kind = "music"\ncontrol_enabled = false',
        )
        settings = self._load(configured)
        self.assertTrue(settings.players[1].enabled)
        self.assertFalse(settings.players[1].control_enabled)

    def test_can_disable_legacy_bootstrap(self) -> None:
        configured = VALID_CONFIG.replace(
            "listen_port = 8770",
            "listen_port = 8770\nlegacy_bootstrap_enabled = false",
        )
        self.assertFalse(self._load(configured).server.legacy_bootstrap_enabled)

    def test_rejects_unknown_default_player(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown player"):
            self._load(
                VALID_CONFIG.replace(
                    'default_music_player_id = "office-music"',
                    'default_music_player_id = "missing"',
                )
            )

    def test_rejects_disabled_default_player(self) -> None:
        configured = VALID_CONFIG.replace(
            'kind = "music"',
            'kind = "music"\nenabled = false',
        )
        with self.assertRaisesRegex(ValueError, "disabled player"):
            self._load(configured)

    def test_rejects_duplicate_player_id(self) -> None:
        duplicate = (
            VALID_CONFIG
            + """
[[players]]
id = "office-music"
room_id = "office"
name = "Duplicate"
protocol = "sendspin"
kind = "music"
"""
        )
        with self.assertRaisesRegex(ValueError, "duplicate player id"):
            self._load(duplicate)

    def test_validates_local_tts_provider_configuration(self) -> None:
        home_assistant = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
home_assistant_url = "http://homeassistant.local:8123"
tts_provider = "home_assistant"
tts_engine_id = "tts.piper"
tts_format = "wav"

[[rooms]]""",
            1,
        )
        settings = self._load(home_assistant)
        self.assertEqual(settings.integrations.tts_engine_id, "tts.piper")

        invalid = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
tts_provider = "home_assistant"

[[rooms]]""",
            1,
        )
        with self.assertRaisesRegex(ValueError, "home_assistant_url"):
            self._load(invalid)

    def test_validates_display_temperature_sensors(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
outdoor_temperature_entity_id = "sensor.outdoor_temperature"
indoor_temperature_entity_id = "sensor.bedroom_temperature"
temperature_history_hours = 24

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(
            settings.integrations.outdoor_temperature_entity_id,
            "sensor.outdoor_temperature",
        )
        self.assertEqual(settings.integrations.temperature_history_hours, 24)

        invalid = configured.replace(
            'outdoor_temperature_entity_id = "sensor.outdoor_temperature"',
            'outdoor_temperature_entity_id = "weather.home"',
        )
        with self.assertRaisesRegex(ValueError, "must be a sensor entity"):
            self._load(invalid)


if __name__ == "__main__":
    unittest.main()
