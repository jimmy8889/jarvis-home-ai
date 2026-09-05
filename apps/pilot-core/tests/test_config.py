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

    def test_music_disabled_room_does_not_require_placeholder_player(self) -> None:
        configured = VALID_CONFIG + """

[[rooms]]
id = "bedroom"
name = "Bedroom"
response_player_id = "bedroom-response"
default_music_player_id = ""
music_enabled = false

[[players]]
id = "bedroom-response"
room_id = "bedroom"
name = "Bedroom Response"
protocol = "pilot-device"
kind = "response"
"""
        settings = self._load(configured)
        bedroom = next(room for room in settings.rooms if room.id == "bedroom")
        self.assertFalse(bedroom.music_enabled)
        self.assertEqual(bedroom.default_music_player_id, "")

    def test_loads_separate_player_control_endpoint(self) -> None:
        configured = VALID_CONFIG.replace(
            'kind = "music"',
            'kind = "music"\ncontrol_endpoint = "http://10.0.1.150:8080"',
        )
        settings = self._load(configured)
        self.assertEqual(
            settings.players[1].control_endpoint,
            "http://10.0.1.150:8080",
        )

    def test_can_disable_legacy_bootstrap(self) -> None:
        configured = VALID_CONFIG.replace(
            "listen_port = 8770",
            "listen_port = 8770\nlegacy_bootstrap_enabled = false",
        )
        self.assertFalse(self._load(configured).server.legacy_bootstrap_enabled)

    def test_validates_public_upload_base_url(self) -> None:
        configured = VALID_CONFIG.replace(
            "listen_port = 8770",
            'listen_port = 8770\npublic_upload_base_url = "https://pilot-upload.example.com/"',
        )
        self.assertEqual(
            self._load(configured).server.public_upload_base_url,
            "https://pilot-upload.example.com",
        )
        for invalid in (
            "http://pilot-upload.example.com",
            "https://pilot-upload.example.com/private",
            "https://user:secret@pilot-upload.example.com",
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "public_upload_base_url"
            ):
                self._load(
                    VALID_CONFIG.replace(
                        "listen_port = 8770",
                        f'listen_port = 8770\npublic_upload_base_url = "{invalid}"',
                    )
                )

    def test_validates_public_client_base_url(self) -> None:
        configured = VALID_CONFIG.replace(
            "listen_port = 8770",
            'listen_port = 8770\npublic_client_base_url = "https://pilot.example.com/"',
        )
        self.assertEqual(
            self._load(configured).server.public_client_base_url,
            "https://pilot.example.com",
        )
        for invalid in (
            "http://pilot.example.com",
            "https://pilot.example.com/private",
            "https://user:secret@pilot.example.com",
        ):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "public_client_base_url"
            ):
                self._load(
                    VALID_CONFIG.replace(
                        "listen_port = 8770",
                        f'listen_port = 8770\npublic_client_base_url = "{invalid}"',
                    )
                )

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

    def test_validates_standalone_energy_manager_polling_contract(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
energy_manager_url = "http://10.0.1.205:8787"
energy_manager_timeout_seconds = 1.5
energy_manager_snapshot_interval_seconds = 2
energy_manager_plan_interval_seconds = 20
energy_manager_stale_after_seconds = 10

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(
            settings.integrations.energy_manager_url,
            "http://10.0.1.205:8787",
        )
        self.assertEqual(settings.integrations.energy_manager_timeout_seconds, 1.5)
        self.assertEqual(
            settings.integrations.energy_manager_snapshot_interval_seconds,
            2,
        )
        self.assertEqual(settings.integrations.energy_manager_plan_interval_seconds, 20)
        self.assertEqual(settings.integrations.energy_manager_stale_after_seconds, 10)

        for invalid_url in (
            "ftp://10.0.1.205:8787",
            "http://user:secret@10.0.1.205:8787",
            "http://10.0.1.205:8787/api/v1",
        ):
            with self.subTest(invalid_url=invalid_url), self.assertRaisesRegex(
                ValueError, "energy_manager_url"
            ):
                self._load(configured.replace("http://10.0.1.205:8787", invalid_url))

        with self.assertRaisesRegex(ValueError, "stale_after_seconds"):
            self._load(configured.replace("energy_manager_stale_after_seconds = 10", "energy_manager_stale_after_seconds = 1"))

    def test_validates_local_llm_provider_configuration(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
llm_provider = "openai"
llm_url = "http://rtx.local:11434/v1"
llm_model = "qwen3:8b"
meeting_analysis_model = "gemma4:12b"
llm_max_tool_rounds = 3

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(settings.integrations.llm_model, "qwen3:8b")
        self.assertEqual(settings.integrations.meeting_analysis_model, "gemma4:12b")
        self.assertEqual(settings.integrations.llm_max_tool_rounds, 3)

        invalid = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
llm_provider = "openai"
llm_model = "qwen3:8b"

[[rooms]]""",
            1,
        )
        with self.assertRaisesRegex(ValueError, "llm_url"):
            self._load(invalid)

    def test_loads_vllm_backend_pool(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
llm_provider = "vllm"

[[integrations.llm_backends]]
id = "ai3090-primary"
url = "http://ai3090:8000/v1"
model = "primary"
token_env = "PILOT_LLM_3090_TOKEN"
roles = ["assistant", "reasoning", "meeting"]
priority = 10
max_output_tokens = 1536
timeout_seconds = 90

[[integrations.llm_backends]]
id = "ai3080-verifier"
url = "http://ai3080:8000/v1"
model = "verifier"
token_env = "PILOT_LLM_3080_TOKEN"
roles = ["assistant", "verification"]
priority = 100

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(len(settings.integrations.llm_backends), 2)
        self.assertEqual(settings.integrations.llm_backends[0].id, "ai3090-primary")
        self.assertEqual(settings.integrations.llm_backends[0].max_output_tokens, 1536)

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

    def test_validates_optional_sun_scene_entity(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
sun_entity_id = "sun.sun"

[[rooms]]""",
            1,
        )
        self.assertEqual(self._load(configured).integrations.sun_entity_id, "sun.sun")

        with self.assertRaisesRegex(ValueError, "must be a sun entity"):
            self._load(
                configured.replace(
                    'sun_entity_id = "sun.sun"',
                    'sun_entity_id = "sensor.sun"',
                )
            )

    def test_validates_display_energy_sensors(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
energy_solar_power_entity_id = "sensor.solar_power"
energy_grid_power_entity_id = "sensor.grid_power"
energy_battery_power_entity_id = "sensor.battery_power"
energy_battery_soc_entity_id = "sensor.battery_soc"
energy_home_load_entity_id = "sensor.home_load"

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(
            settings.integrations.energy_battery_soc_entity_id,
            "sensor.battery_soc",
        )

        invalid = configured.replace(
            'energy_home_load_entity_id = "sensor.home_load"',
            'energy_home_load_entity_id = "weather.home"',
        )
        with self.assertRaisesRegex(ValueError, "must be a sensor entity"):
            self._load(invalid)

    def test_validates_home_catalogue_limits(self) -> None:
        configured = VALID_CONFIG.replace(
            "[[rooms]]",
            """[integrations]
home_catalog_sync_interval_seconds = 120
home_catalog_stale_after_seconds = 600
home_catalog_max_entities = 25000

[[rooms]]""",
            1,
        )
        settings = self._load(configured)
        self.assertEqual(
            settings.integrations.home_catalog_sync_interval_seconds,
            120,
        )
        self.assertEqual(settings.integrations.home_catalog_max_entities, 25_000)

        invalid = configured.replace(
            "home_catalog_max_entities = 25000",
            "home_catalog_max_entities = 50",
        )
        with self.assertRaisesRegex(ValueError, "home_catalog_max_entities"):
            self._load(invalid)


if __name__ == "__main__":
    unittest.main()
