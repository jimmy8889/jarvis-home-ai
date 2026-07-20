from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.integrations import Integrations
from pilot_core.storage import Store
from pilot_core.tts import LocalTTS, SynthesizedAudio
from pilot_core.voice import HomeAssistantVoicePipeline


WAV = b"RIFF\x04\x00\x00\x00WAVEpilot"


class DisplayNodeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-test"
        self.root = tempfile.TemporaryDirectory()
        root = Path(self.root.name)
        self.settings = Settings(
            server=ServerSettings(
                database_path=":memory:",
                audio_asset_path=str(root / "audio"),
                meeting_asset_path=str(root / "meetings"),
                firmware_asset_path=str(root / "firmware"),
            ),
            integrations=IntegrationSettings(
                home_assistant_url="http://homeassistant.test:8123",
                home_assistant_assist_pipeline_id="local-pipeline",
                weather_entity_id="weather.home",
                outdoor_temperature_entity_id="sensor.outdoor_temperature",
                indoor_temperature_entity_id="sensor.bedroom_temperature",
                energy_solar_power_entity_id="sensor.solar_power",
                energy_grid_power_entity_id="sensor.grid_power",
                energy_battery_power_entity_id="sensor.battery_power",
                energy_battery_soc_entity_id="sensor.battery_soc",
                energy_home_load_entity_id="sensor.home_load",
                tts_provider="home_assistant",
                tts_engine_id="tts.piper",
            ),
            rooms=(
                Room(
                    id="bedroom",
                    name="Bedroom",
                    response_player_id="bedroom-speaker",
                    default_music_player_id="bedroom-music",
                    default_device_id="pilot-bedroom-display",
                ),
                Room(
                    id="office",
                    name="Office",
                    response_player_id="office-music",
                    default_music_player_id="office-music",
                    default_device_id="pilot-office",
                ),
            ),
            players=(
                Player(
                    id="bedroom-speaker",
                    room_id="bedroom",
                    name="Bedroom Display Speaker",
                    protocol="pilot-device",
                    kind="response",
                    control_enabled=False,
                ),
                Player(
                    id="bedroom-music",
                    room_id="bedroom",
                    name="Bedroom Music",
                    protocol="sendspin",
                    kind="music",
                    external_id="bedroom-player",
                ),
                Player(
                    id="office-music",
                    room_id="office",
                    name="Office Music",
                    protocol="sendspin",
                    kind="music",
                    external_id="office-player",
                ),
            ),
        )
        self.store = Store(":memory:", self.settings)
        self.token = self.store.register_device(
            "pilot-bedroom-display",
            "bedroom",
            "Bedroom Display",
            ["audio", "display", "media-control", "ota", "voice"],
        )
        self.client = TestClient(create_app(self.settings, self.store))
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Pilot-Device-ID": "pilot-bedroom-display",
        }

    def tearDown(self) -> None:
        self.client.close()
        self.store.close()
        self.root.cleanup()
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    def test_snapshot_is_authenticated_and_weather_is_bounded(self) -> None:
        raw_weather = {
            "entity_id": "weather.home",
            "current": {
                "state": "sunny",
                "last_updated": "2026-07-18T05:00:00+00:00",
                "attributes": {
                    "temperature": 22.5,
                    "apparent_temperature": 21.8,
                    "temperature_unit": "°C",
                    "humidity": 61,
                    "wind_speed": 18,
                    "wind_speed_unit": "km/h",
                    "wind_bearing": "S",
                    "precipitation_unit": "mm",
                    "private_attribute": "must not leak",
                },
            },
            "forecast_response": {
                "service_response": {
                    "weather.home": {
                        "forecast": [
                            {
                                "condition": "partlycloudy",
                                "temperature": 26,
                                "templow": 15,
                                "precipitation": 2.4,
                                "precipitation_probability": 20,
                                "private_forecast": "must not leak",
                            },
                            {
                                "condition": "rainy",
                                "temperature": 24,
                                "templow": 16,
                                "precipitation_probability": 70,
                            },
                        ]
                    }
                }
            },
        }

        def temperature_history(entity_id: str) -> dict:
            is_outside = entity_id == "sensor.outdoor_temperature"
            return {
                "entity_id": entity_id,
                "period_hours": 24,
                "current": {
                    "state": "24.5" if is_outside else "21.5",
                    "last_updated": "2026-07-19T02:00:00+00:00",
                    "attributes": {"unit_of_measurement": "°C"},
                },
                "history": [
                    [
                        {
                            "state": "16.5" if is_outside else "20.0",
                            "last_changed": "2026-07-18T02:00:00+00:00",
                        },
                        {
                            "state": "27.0" if is_outside else "23.0",
                            "last_changed": "2026-07-19T01:00:00+00:00",
                        },
                    ]
                ],
            }

        with (
            patch.object(
                Integrations,
                "home_assistant_weather",
                new=AsyncMock(return_value=raw_weather),
            ),
            patch.object(
                Integrations,
                "home_assistant_temperature_history",
                new=AsyncMock(side_effect=temperature_history),
            ),
        ):
            response = self.client.get(
                "/v1/devices/pilot-bedroom-display/snapshot",
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["room_id"], "bedroom")
        self.assertEqual(payload["weather"]["temperature"], 22.5)
        self.assertEqual(payload["weather"]["high_temperature"], 26)
        self.assertEqual(payload["weather"]["wind_speed"], 18)
        self.assertEqual(payload["weather"]["precipitation"], 2.4)
        self.assertEqual(payload["weather"]["tomorrow_condition"], "rainy")
        self.assertEqual(
            payload["temperature_extremes"]["outside"]["minimum"],
            16.5,
        )
        self.assertEqual(
            payload["temperature_extremes"]["inside"]["maximum"],
            23.0,
        )
        self.assertEqual(
            len(payload["temperature_extremes"]["outside"]["samples"]),
            24,
        )
        self.assertNotIn("private_attribute", json.dumps(payload))
        self.assertTrue(payload["voice"]["configured"])
        self.assertTrue(payload["tts"]["configured"])
        self.assertEqual(
            self.client.get("/v1/devices/pilot-bedroom-display/snapshot").status_code,
            422,
        )

    def test_text_assistant_is_device_authenticated_and_room_scoped(self) -> None:
        with patch.object(
            Integrations,
            "home_assistant_conversation",
            new=AsyncMock(
                return_value={
                    "conversation_id": "ha-conversation-1",
                    "response": {
                        "response_type": "query_answer",
                        "speech": {
                            "plain": {
                                "speech": "The bedroom is 22 degrees.",
                            }
                        },
                    },
                }
            ),
        ):
            response = self.client.post(
                "/v1/devices/pilot-bedroom-display/assistant",
                headers=self.headers,
                json={
                    "text": "What is the bedroom temperature?",
                    "language": "en-AU",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["room_id"], "bedroom")
        self.assertEqual(payload["device_id"], "pilot-bedroom-display")
        self.assertEqual(payload["response_text"], "The bedroom is 22 degrees.")
        self.assertTrue(payload["conversation_id"])

        moved = self.client.post(
            "/v1/devices/pilot-bedroom-display/assistant",
            headers=self.headers,
            json={
                "text": "What is happening in the office?",
                "room_id": "office",
            },
        )
        self.assertEqual(moved.status_code, 403)

    def test_media_control_uses_the_configured_room_player(self) -> None:
        with patch.object(
            Integrations,
            "music_assistant",
            new=AsyncMock(return_value={"ok": True}),
        ) as music_assistant:
            response = self.client.post(
                "/v1/devices/pilot-bedroom-display/media",
                headers=self.headers,
                json={"action": "pause"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["player"]["id"], "bedroom-music")
        music_assistant.assert_awaited_once_with(
            "players/cmd/pause",
            {"player_id": "bedroom-player"},
        )

    def test_fixed_room_media_control_cannot_name_another_room_player(self) -> None:
        response = self.client.post(
            "/v1/devices/pilot-bedroom-display/media",
            headers=self.headers,
            json={"action": "pause", "player_id": "office-music"},
        )

        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()["detail"],
            "fixed-room device cannot control another room",
        )

    def test_portable_client_can_control_another_room_player(self) -> None:
        token = self.store.register_device(
            "pilot-ios-test",
            "bedroom",
            "Pilot iOS Test",
            ["media-control", "portable-client", "voice"],
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Pilot-Device-ID": "pilot-ios-test",
        }
        with patch.object(
            Integrations,
            "music_assistant",
            new=AsyncMock(return_value={"ok": True}),
        ) as music_assistant:
            response = self.client.post(
                "/v1/devices/pilot-ios-test/media",
                headers=headers,
                json={"action": "pause", "player_id": "office-music"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["room_id"], "office")
        music_assistant.assert_awaited_once_with(
            "players/cmd/pause",
            {"player_id": "office-player"},
        )

    def test_media_search_uses_device_credentials(self) -> None:
        with patch.object(
            Integrations,
            "music_assistant",
            new=AsyncMock(return_value={"tracks": []}),
        ) as music_assistant:
            response = self.client.post(
                "/v1/devices/pilot-bedroom-display/media/search",
                headers=self.headers,
                json={"query": "Massive Attack", "limit": 8},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"tracks": []})
        music_assistant.assert_awaited_once_with(
            "music/search",
            {
                "search_query": "Massive Attack",
                "limit": 8,
                "library_only": False,
            },
        )

    def test_surface_is_authenticated_and_bounded(self) -> None:
        raw_energy = {
            "solar": {
                "state": "4.2",
                "last_updated": "2026-07-19T02:00:00+00:00",
                "attributes": {"unit_of_measurement": "kW", "private": "discard"},
            },
            "grid": {
                "state": "-1200",
                "attributes": {"unit_of_measurement": "W"},
            },
            "battery": {
                "state": "-2500",
                "attributes": {"unit_of_measurement": "W"},
            },
            "battery_soc": {
                "state": "74.5",
                "attributes": {"unit_of_measurement": "%"},
            },
            "home_load": {
                "state": "1500",
                "attributes": {"unit_of_measurement": "W"},
            },
        }
        now_playing = {
            "status": "ok",
            "observed_at": "2026-07-19T02:00:00+00:00",
            "items": [
                {
                    "player_id": "office",
                    "player_name": "Office",
                    "state": "playing",
                    "title": "Track",
                    "artist": "Artist",
                }
            ],
        }
        with (
            patch.object(
                Integrations,
                "home_assistant_energy",
                new=AsyncMock(return_value=raw_energy),
            ),
            patch(
                "pilot_core.api.MediaStateReader.now_playing",
                new=AsyncMock(return_value=now_playing),
            ),
        ):
            response = self.client.get(
                "/v1/devices/pilot-bedroom-display/surface",
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["energy"]["solar"]["value"], 4200)
        self.assertEqual(payload["energy"]["grid"]["direction"], "exporting")
        self.assertEqual(payload["energy"]["battery"]["direction"], "charging")
        self.assertEqual(payload["energy"]["battery_soc"]["value"], 74.5)
        self.assertEqual(payload["now_playing"]["items"][0]["title"], "Track")
        self.assertNotIn("private", json.dumps(payload))
        self.assertEqual(
            self.client.get(
                "/v1/devices/pilot-bedroom-display/surface"
            ).status_code,
            422,
        )

    def test_voice_stream_returns_private_tts_asset(self) -> None:
        synthesized = SynthesizedAudio(
            content=WAV,
            content_type="audio/wav",
            filename="speech.wav",
            provider="home_assistant",
            voice="en_US-amy-low",
            model="tts.piper",
            language="en",
        )

        async def consume_voice(_pipeline, audio, **_kwargs):
            received = bytearray()
            async for chunk in audio:
                received.extend(chunk)
            self.assertEqual(len(received), 16000)
            return "What is the weather?"

        with (
            patch.object(
                HomeAssistantVoicePipeline,
                "transcribe",
                new=consume_voice,
            ),
            patch.object(
                Integrations,
                "home_assistant_conversation",
                new=AsyncMock(
                    return_value={
                        "conversation_id": "ha-conversation-1",
                        "response": {
                            "response_type": "query_answer",
                            "speech": {
                                "plain": {
                                    "speech": "It is sunny and 22 degrees.",
                                }
                            },
                        },
                    }
                ),
            ),
            patch.object(
                LocalTTS,
                "synthesize",
                new=AsyncMock(return_value=synthesized),
            ),
        ):
            response = self.client.post(
                "/v1/devices/pilot-bedroom-display/voice",
                headers={
                    **self.headers,
                    "Content-Type": "application/octet-stream",
                    "X-Pilot-Sample-Rate": "16000",
                },
                content=b"\x00\x00" * 8000,
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["transcript"], "What is the weather?")
        self.assertEqual(payload["response_text"], "It is sunny and 22 degrees.")
        self.assertTrue(
            payload["audio"]["download_url"].startswith("/v1/audio-assets/")
        )
        self.assertNotIn("path", payload["audio"])

    def test_firmware_manifest_and_image_require_device_credentials(self) -> None:
        release_dir = Path(self.root.name) / "firmware" / "esp32-c6-touch-amoled-2.16"
        release_dir.mkdir(parents=True)
        image = b"pilot-firmware-image"
        filename = "pilot-display-node-0.2.0.bin"
        (release_dir / filename).write_bytes(image)
        digest = hashlib.sha256(image).hexdigest()
        (release_dir / "latest.json").write_text(
            json.dumps(
                {
                    "version": "0.2.0",
                    "filename": filename,
                    "sha256": digest,
                    "mandatory": False,
                }
            ),
            encoding="utf-8",
        )

        manifest = self.client.get(
            "/v1/devices/pilot-bedroom-display/firmware",
            headers=self.headers,
            params={
                "target": "esp32-c6-touch-amoled-2.16",
                "current_version": "0.1.0",
            },
        )
        self.assertEqual(manifest.status_code, 200)
        self.assertTrue(manifest.json()["update_available"])
        self.assertEqual(manifest.json()["release"]["sha256"], digest)

        newer_device = self.client.get(
            "/v1/devices/pilot-bedroom-display/firmware",
            headers=self.headers,
            params={
                "target": "esp32-c6-touch-amoled-2.16",
                "current_version": "0.3.0",
            },
        )
        self.assertEqual(newer_device.status_code, 200)
        self.assertFalse(newer_device.json()["update_available"])

        download = self.client.get(
            "/v1/devices/pilot-bedroom-display/firmware/image",
            headers=self.headers,
            params={"target": "esp32-c6-touch-amoled-2.16"},
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, image)
        self.assertEqual(download.headers["x-pilot-firmware-sha256"], digest)

        denied = self.client.get(
            "/v1/devices/pilot-bedroom-display/firmware/image",
            headers={
                "Authorization": "Bearer wrong",
                "X-Pilot-Device-ID": "pilot-bedroom-display",
            },
            params={"target": "esp32-c6-touch-amoled-2.16"},
        )
        self.assertEqual(denied.status_code, 401)


if __name__ == "__main__":
    unittest.main()
