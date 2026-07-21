from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import IntegrationSettings, Player, Room, ServerSettings, Settings
from pilot_core.conversation import AssistantResponse
from pilot_core.home_intelligence import HomeIntelligence
from pilot_core.integrations import Integrations
from pilot_core.storage import Store


FIXTURES = Path(__file__).with_name("fixtures")


class ProductContractTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PILOT_CORE_ADMIN_TOKEN"] = "admin-test"
        self.root = tempfile.TemporaryDirectory()
        root = Path(self.root.name)
        self.settings = Settings(
            server=ServerSettings(
                database_path=":memory:",
                admin_token_env="PILOT_CORE_ADMIN_TOKEN",
                audio_asset_path=str(root / "audio"),
                meeting_asset_path=str(root / "meetings"),
                firmware_asset_path=str(root / "firmware"),
            ),
            integrations=IntegrationSettings(
                energy_solar_power_entity_id="sensor.solar",
                energy_grid_power_entity_id="sensor.grid",
                energy_battery_power_entity_id="sensor.battery",
                energy_battery_soc_entity_id="sensor.battery_soc",
                energy_home_load_entity_id="sensor.home_load",
            ),
            rooms=(
                Room(
                    id="office",
                    name="Office",
                    response_player_id="office-music",
                    default_music_player_id="office-music",
                    home_area_ids=("james_office",),
                ),
                Room(
                    id="bedroom",
                    name="Bedroom",
                    response_player_id="bedroom-music",
                    default_music_player_id="bedroom-music",
                ),
            ),
            players=(
                Player(
                    id="office-music",
                    room_id="office",
                    name="Office Music",
                    protocol="sendspin",
                    kind="music",
                ),
                Player(
                    id="bedroom-music",
                    room_id="bedroom",
                    name="Bedroom Music",
                    protocol="sendspin",
                    kind="music",
                ),
            ),
        )
        self.store = Store(":memory:", self.settings)
        self.token = self.store.register_device(
            "pilot-phone",
            "office",
            "Pilot Phone",
            [
                "home-control",
                "home-read",
                "media-control",
                "portable-client",
                "voice",
            ],
        )
        intelligence = HomeIntelligence(
            self.store,
            Integrations(self.settings.integrations),
            self.settings.integrations,
            self.settings.rooms,
        )
        now = datetime.now(UTC).isoformat()
        records = intelligence.normalize_snapshot(
            [
                {
                    "entity_id": "light.office_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Office Lamp"},
                    "last_updated": now,
                },
                {
                    "entity_id": "light.office_mystery",
                    "state": "off",
                    "attributes": {"friendly_name": "Office Mystery"},
                    "last_updated": now,
                },
                *[
                    {
                        "entity_id": f"sensor.{entity}",
                        "state": value,
                        "attributes": {
                            "friendly_name": entity.replace("_", " ").title(),
                            "device_class": (
                                "battery" if entity == "battery_soc" else "power"
                            ),
                            "unit_of_measurement": (
                                "%" if entity == "battery_soc" else "W"
                            ),
                        },
                        "last_updated": now,
                    }
                    for entity, value in (
                        ("solar", "5000"),
                        ("grid", "-1200"),
                        ("battery", "1800"),
                        ("battery_soc", "76"),
                        ("home_load", "2000"),
                    )
                ],
            ],
            synced_at=now,
            registry_metadata={
                "light.office_lamp": {"area_id": "james_office"},
            },
        )
        sync_id = self.store.begin_home_catalog_sync()
        self.store.replace_home_catalog(sync_id, records)
        self.client = TestClient(create_app(self.settings, self.store))

    def tearDown(self) -> None:
        self.client.close()
        self.store.close()
        self.root.cleanup()
        os.environ.pop("PILOT_CORE_ADMIN_TOKEN", None)

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token or self.token}",
            "X-Pilot-Device-ID": "pilot-phone",
        }

    @staticmethod
    def admin_headers() -> dict[str, str]:
        return {"Authorization": "Bearer admin-test"}

    def test_manifest_snapshot_and_energy_are_device_scoped(self) -> None:
        manifest = self.client.get(
            "/v1/devices/pilot-phone/manifest", headers=self.headers()
        )
        self.assertEqual(manifest.status_code, 200, manifest.text)
        self.assertEqual(manifest.json()["schema_version"], "pilot.client.v1")
        self.assertTrue(manifest.json()["features"]["energy"])
        self.assertTrue(manifest.json()["features"]["realtime"])
        self.assertNotIn("token", json.dumps(manifest.json()).casefold())

        snapshot = self.client.get(
            "/v1/devices/pilot-phone/events/snapshot", headers=self.headers()
        )
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        self.assertEqual(snapshot.json()["schema_version"], "pilot.snapshot.v1")
        self.assertEqual(snapshot.json()["energy"]["solar"]["value"], 5000)
        self.assertEqual(
            set(snapshot.json()["home"]["rooms"]), {"office", "bedroom"}
        )

        energy = self.client.get(
            "/v1/devices/pilot-phone/energy", headers=self.headers()
        )
        self.assertEqual(energy.status_code, 200, energy.text)
        self.assertEqual(energy.json()["schema_version"], "pilot.energy.v1")

    def test_presentation_is_explainable_persistent_and_safety_bounded(self) -> None:
        home = self.client.get(
            "/v1/devices/pilot-phone/home?room_id=office", headers=self.headers()
        )
        entities = {item["entity_id"]: item for item in home.json()["entities"]}
        trusted = entities["light.office_lamp"]["presentation"]
        inferred = entities["light.office_mystery"]["presentation"]
        self.assertTrue(trusted["room"]["authoritative"])
        self.assertEqual(trusted["room"]["trust"], "registry")
        self.assertFalse(inferred["room"]["authoritative"])
        self.assertEqual(inferred["room"]["trust"], "inferred")

        rejected = self.client.post(
            "/v1/devices/pilot-phone/home/actions",
            headers=self.headers(),
            json={
                "room_id": "office",
                "entity_id": "light.office_mystery",
                "action": "turn_on",
            },
        )
        self.assertEqual(rejected.status_code, 403, rejected.text)

        updated = self.client.patch(
            "/v1/home/presentation/light.office_mystery",
            headers=self.admin_headers(),
            json={
                "exposure_policy": "include",
                "room_id": "office",
                "priority": 99,
                "section": "Favourites",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["presentation"]["room"]["trust"], "explicit")
        self.assertTrue(
            updated.json()["presentation"]["room"]["authoritative"]
        )

        with (
            patch.object(
                Integrations,
                "home_assistant_typed_action",
                new=AsyncMock(return_value={"changed_state_count": 1}),
            ),
            patch.object(
                Integrations,
                "home_assistant_state",
                new=AsyncMock(
                    return_value={
                        "entity_id": "light.office_mystery",
                        "state": "on",
                        "attributes": {},
                    }
                ),
            ),
            patch("pilot_core.home_actions.asyncio.sleep", new=AsyncMock()),
        ):
            accepted = self.client.post(
                "/v1/devices/pilot-phone/home/actions",
                headers=self.headers(),
                json={
                    "room_id": "office",
                    "entity_id": "light.office_mystery",
                    "action": "turn_on",
                },
            )
        self.assertEqual(accepted.status_code, 200, accepted.text)

    def test_resumable_events_credentials_rotation_and_revocation(self) -> None:
        published = self.client.post(
            "/v1/events",
            headers=self.headers(),
            json={
                "room_id": "office",
                "type": "source_state",
                "payload": {"source": "music", "active": True},
            },
        )
        self.assertEqual(published.status_code, 200, published.text)
        events = self.client.get(
            "/v1/devices/pilot-phone/events?cursor=0", headers=self.headers()
        )
        self.assertEqual(events.status_code, 200, events.text)
        self.assertEqual(events.json()["events"][0]["revision"], 1)
        self.assertEqual(
            events.json()["events"][0]["type"],
            "pilot.audio.source.changed.v1",
        )
        cursor = events.json()["cursor"]
        empty = self.client.get(
            f"/v1/devices/pilot-phone/events?cursor={cursor}",
            headers=self.headers(),
        )
        self.assertEqual(empty.json()["events"], [])

        rotated = self.client.post(
            "/v1/devices/pilot-phone/credentials/rotate-self",
            headers=self.headers(),
        )
        self.assertEqual(rotated.status_code, 200, rotated.text)
        new_token = rotated.json()["device_token"]
        self.assertEqual(
            self.client.get(
                "/v1/devices/pilot-phone/manifest", headers=self.headers()
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.get(
                "/v1/devices/pilot-phone/manifest", headers=self.headers(new_token)
            ).status_code,
            200,
        )
        revoked = self.client.post(
            "/v1/devices/pilot-phone/revoke", headers=self.admin_headers()
        )
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(
            self.client.get(
                "/v1/devices/pilot-phone/manifest", headers=self.headers(new_token)
            ).status_code,
            401,
        )

    def test_typed_seek_command_reaches_music_assistant_contract(self) -> None:
        with patch.object(
            Integrations,
            "music_assistant",
            new=AsyncMock(return_value={"ok": True}),
        ) as music_assistant:
            response = self.client.post(
                "/v1/devices/pilot-phone/media",
                headers=self.headers(),
                json={
                    "action": "seek",
                    "player_id": "office-music",
                    "position_seconds": 91.5,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        music_assistant.assert_awaited_once_with(
            "players/cmd/seek",
            {"player_id": "office-music", "position": 91.5},
        )

    def test_assistant_response_has_typed_cards_actions_and_fixture_shape(self) -> None:
        response = AssistantResponse(
            session_id="conversation-1",
            room_id="office",
            response_text="The office is 22 degrees.",
            provider="pilot_llm",
            continue_conversation=False,
            result={},
            tool_calls=(
                {
                    "id": "call-1",
                    "name": "get_temperature",
                    "arguments": {"location": "inside"},
                    "output": {"state": "22", "unit": "°C"},
                },
            ),
        ).as_dict()
        self.assertEqual(response["schema_version"], "pilot.assistant.v1")
        self.assertEqual(response["cards"][0]["kind"], "weather")
        self.assertEqual(response["actions"][0]["status"], "succeeded")

        for name in (
            "device_manifest.v1.json",
            "home_entity_presentation.v1.json",
            "client_events.v1.json",
            "media_snapshot.v1.json",
            "assistant_response.v1.json",
        ):
            with (FIXTURES / name).open(encoding="utf-8") as handle:
                self.assertIsInstance(json.load(handle), dict)


if __name__ == "__main__":
    unittest.main()
