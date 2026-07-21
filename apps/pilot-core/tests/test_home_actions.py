from __future__ import annotations

from datetime import UTC, datetime
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import IntegrationSettings, Player, Room, ServerSettings, Settings
from pilot_core.home_intelligence import HomeIntelligence
from pilot_core.integrations import Integrations
from pilot_core.storage import Store


class HomeActionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-test"
        self.root = tempfile.TemporaryDirectory()
        self.settings = Settings(
            server=ServerSettings(
                database_path=":memory:",
                audio_asset_path=f"{self.root.name}/audio",
                meeting_asset_path=f"{self.root.name}/meetings",
                firmware_asset_path=f"{self.root.name}/firmware",
            ),
            integrations=IntegrationSettings(
                home_assistant_url="http://ha.test:8123",
            ),
            rooms=(
                Room(
                    id="office",
                    name="Office",
                    response_player_id="office-response",
                    default_music_player_id="office-music",
                    home_area_ids=("office", "james_office"),
                ),
                Room(
                    id="bedroom",
                    name="Bedroom",
                    response_player_id="bedroom-response",
                    default_music_player_id="bedroom-music",
                    home_area_ids=("bedroom",),
                ),
            ),
            players=(
                Player(
                    id="office-response",
                    room_id="office",
                    name="Office response",
                    protocol="pipewire",
                    kind="response",
                ),
                Player(
                    id="office-music",
                    room_id="office",
                    name="Office music",
                    protocol="sendspin",
                    kind="music",
                ),
                Player(
                    id="bedroom-response",
                    room_id="bedroom",
                    name="Bedroom response",
                    protocol="pipewire",
                    kind="response",
                ),
                Player(
                    id="bedroom-music",
                    room_id="bedroom",
                    name="Bedroom music",
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
            ["home-control", "home-read", "portable-client"],
        )
        self.fixed_token = self.store.register_device(
            "pilot-office",
            "office",
            "Office",
            ["home-control", "home-read"],
        )
        intelligence = HomeIntelligence(
            self.store,
            Integrations(self.settings.integrations),
            self.settings.integrations,
            self.settings.rooms,
        )
        sync_id = self.store.begin_home_catalog_sync()
        records = intelligence.normalize_snapshot(
            [
                {
                    "entity_id": "light.office_lamp",
                    "state": "off",
                    "attributes": {"friendly_name": "Office Lamp", "brightness": 0},
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
                {
                    "entity_id": "lock.bedroom_door",
                    "state": "locked",
                    "attributes": {
                        "friendly_name": "Bedroom Door",
                        "device_class": "lock",
                    },
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
                {
                    "entity_id": "switch.unassigned",
                    "state": "off",
                    "attributes": {"friendly_name": "Unassigned"},
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
                {
                    "entity_id": "sensor.office_temperature",
                    "state": "23.4",
                    "attributes": {
                        "friendly_name": "Office Temperature",
                        "device_class": "temperature",
                        "unit_of_measurement": "°C",
                    },
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
                {
                    "entity_id": "sensor.office_linkquality",
                    "state": "91",
                    "attributes": {"friendly_name": "Office Linkquality"},
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
                {
                    "entity_id": "light.office_internal",
                    "state": "off",
                    "attributes": {"friendly_name": "Office Internal Light"},
                    "last_updated": "2026-07-21T00:00:00+00:00",
                },
            ],
            synced_at=datetime.now(UTC).isoformat(),
            registry_metadata={
                "light.office_lamp": {"area_id": "james_office"},
                "lock.bedroom_door": {"area_id": "bedroom"},
                "switch.unassigned": {"area_id": None},
                "sensor.office_temperature": {"area_id": "james_office"},
                "sensor.office_linkquality": {"area_id": "james_office"},
                "light.office_internal": {
                    "area_id": "james_office",
                    "hidden_by": "integration",
                },
            },
        )
        self.store.replace_home_catalog(sync_id, records)
        self.client = TestClient(create_app(self.settings, self.store))

    def tearDown(self) -> None:
        self.client.close()
        self.store.close()
        self.root.cleanup()
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    def headers(self, device_id: str = "pilot-phone", token: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token or self.token}",
            "X-Pilot-Device-ID": device_id,
        }

    def test_room_projection_is_device_authenticated_and_area_bounded(self) -> None:
        response = self.client.get(
            "/v1/devices/pilot-phone/home?room_id=office",
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json()["entity_count"], 2)
        entity = next(
            item for item in response.json()["entities"]
            if item["entity_id"] == "light.office_lamp"
        )
        self.assertEqual(entity["entity_id"], "light.office_lamp")
        self.assertIn("set_brightness", entity["actions"])
        self.assertNotIn("lock.bedroom_door", response.text)
        self.assertNotIn("sensor.office_linkquality", response.text)
        self.assertNotIn("light.office_internal", response.text)

    def test_fixed_room_device_cannot_project_another_room(self) -> None:
        response = self.client.get(
            "/v1/devices/pilot-office/home?room_id=bedroom",
            headers=self.headers("pilot-office", self.fixed_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_shared_home_model_is_stable_and_marks_geometry_as_pending(self) -> None:
        first = self.client.get(
            "/v1/devices/pilot-phone/home/model",
            headers=self.headers(),
        )
        second = self.client.get(
            "/v1/devices/pilot-phone/home/model",
            headers=self.headers(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["model_version"], second.json()["model_version"])
        self.assertEqual(first.json()["presentation"], "semantic-2d")
        self.assertFalse(first.json()["capabilities"]["glb_geometry"])
        self.assertEqual(
            {room["id"] for room in first.json()["rooms"]},
            {"office", "bedroom"},
        )

    def test_low_risk_action_executes_and_is_reconciled_and_audited(self) -> None:
        with (
            patch.object(
                Integrations,
                "home_assistant_typed_action",
                new=AsyncMock(return_value={"changed_state_count": 1}),
            ) as execute,
            patch.object(
                Integrations,
                "home_assistant_state",
                new=AsyncMock(
                    return_value={
                        "entity_id": "light.office_lamp",
                        "state": "on",
                        "attributes": {"brightness": 255},
                    }
                ),
            ),
            patch("pilot_core.home_actions.asyncio.sleep", new=AsyncMock()),
        ):
            response = self.client.post(
                "/v1/devices/pilot-phone/home/actions",
                headers=self.headers(),
                json={
                    "room_id": "office",
                    "entity_id": "light.office_lamp",
                    "action": "turn_on",
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        action = response.json()["action"]
        self.assertEqual(action["status"], "succeeded")
        execute.assert_awaited_once_with(
            "light",
            "turn_on",
            "light.office_lamp",
            {},
        )
        audit = self.store.home_action_audit(action["id"])
        self.assertEqual(
            [event["event_type"] for event in audit],
            ["requested", "approved", "succeeded"],
        )

    def test_high_risk_action_requires_same_device_confirmation_once(self) -> None:
        with patch.object(
            Integrations,
            "home_assistant_typed_action",
            new=AsyncMock(return_value={"changed_state_count": 1}),
        ) as execute:
            prepared = self.client.post(
                "/v1/devices/pilot-phone/home/actions",
                headers=self.headers(),
                json={
                    "room_id": "bedroom",
                    "entity_id": "lock.bedroom_door",
                    "action": "unlock",
                },
            )
            self.assertEqual(prepared.status_code, 202, prepared.text)
            action_id = prepared.json()["action"]["id"]
            execute.assert_not_awaited()
            with (
                patch.object(
                    Integrations,
                    "home_assistant_state",
                    new=AsyncMock(
                        return_value={
                            "entity_id": "lock.bedroom_door",
                            "state": "unlocked",
                            "attributes": {},
                        }
                    ),
                ),
                patch("pilot_core.home_actions.asyncio.sleep", new=AsyncMock()),
            ):
                confirmed = self.client.post(
                    f"/v1/devices/pilot-phone/home/actions/{action_id}/confirm",
                    headers=self.headers(),
                )
            replay = self.client.post(
                f"/v1/devices/pilot-phone/home/actions/{action_id}/confirm",
                headers=self.headers(),
            )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["action"]["status"], "succeeded")
        self.assertEqual(replay.status_code, 409)
        execute.assert_awaited_once()

    def test_unassigned_entity_cannot_be_controlled(self) -> None:
        response = self.client.post(
            "/v1/devices/pilot-phone/home/actions",
            headers=self.headers(),
            json={
                "room_id": "office",
                "entity_id": "switch.unassigned",
                "action": "turn_on",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_audit_api_requires_admin_token(self) -> None:
        self.assertEqual(self.client.get("/v1/home/actions").status_code, 401)
