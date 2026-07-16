from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import IntegrationSettings, Player, Room, ServerSettings, Settings
from pilot_core.storage import Store


def settings() -> Settings:
    return Settings(
        server=ServerSettings(database_path=":memory:"),
        integrations=IntegrationSettings(),
        rooms=(
            Room(
                id="office",
                name="Office",
                response_player_id="office-assistant",
                default_music_player_id="office-music",
            ),
        ),
        players=(
            Player(
                id="office-assistant",
                room_id="office",
                name="Office Assistant",
                protocol="pipewire",
                kind="response",
            ),
            Player(
                id="office-music",
                room_id="office",
                name="Office Music",
                protocol="sendspin",
                kind="music",
                external_id="pilot-office",
            ),
        ),
    )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PILOT_CORE_ADMIN_TOKEN"] = "admin-test"
        os.environ["PILOT_CORE_BOOTSTRAP_TOKEN"] = "bootstrap-test"
        config = settings()
        self.store = Store(":memory:", config)
        self.client = TestClient(create_app(config, self.store))

    def tearDown(self) -> None:
        os.environ.pop("PILOT_CORE_ADMIN_TOKEN", None)
        os.environ.pop("PILOT_CORE_BOOTSTRAP_TOKEN", None)
        self.client.close()
        self.store.close()

    def test_admin_api_requires_token(self) -> None:
        self.assertEqual(self.client.get("/v1/rooms").status_code, 401)
        response = self.client.get(
            "/v1/rooms", headers={"Authorization": "Bearer admin-test"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rooms"][0]["id"], "office")

    def test_register_and_publish_source_event(self) -> None:
        registration = self.client.post(
            "/v1/devices/register",
            headers={"Authorization": "Bearer bootstrap-test"},
            json={
                "device_id": "office-n150",
                "room_id": "office",
                "name": "Office N150",
                "capabilities": ["audio", "voice"],
            },
        )
        self.assertEqual(registration.status_code, 200)
        token = registration.json()["device_token"]
        event = self.client.post(
            "/v1/events",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Pilot-Device-ID": "office-n150",
            },
            json={
                "room_id": "office",
                "type": "source_state",
                "payload": {"source": "music", "active": True},
            },
        )
        self.assertEqual(event.status_code, 200)
        self.assertEqual(event.json()["focus"]["foreground"], "music")

    def test_websocket_requires_admin_token(self) -> None:
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/v1/events/ws"):
                pass

    def register_device(self) -> str:
        registration = self.client.post(
            "/v1/devices/register",
            headers={"Authorization": "Bearer bootstrap-test"},
            json={
                "device_id": "office-n150",
                "room_id": "office",
                "name": "Office N150",
                "capabilities": ["audio", "voice"],
            },
        )
        self.assertEqual(registration.status_code, 200)
        return registration.json()["device_token"]

    def test_queued_command_is_delivered_and_acknowledged(self) -> None:
        token = self.register_device()
        queued = self.client.post(
            "/v1/devices/office-n150/commands",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "pause", "source": "music"},
        )
        self.assertEqual(queued.status_code, 201)
        command_id = queued.json()["id"]

        with self.client.websocket_connect(
            "/v1/devices/ws?device_id=office-n150",
            headers={"Authorization": f"Bearer {token}"},
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "hello")
            message = socket.receive_json()
            self.assertEqual(message["type"], "command")
            self.assertEqual(message["command"]["id"], command_id)
            socket.send_json(
                {
                    "type": "command_result",
                    "command_id": command_id,
                    "status": "succeeded",
                    "result": {"ok": True},
                }
            )
            self.assertEqual(socket.receive_json()["type"], "command_ack")

        result = self.client.get(
            f"/v1/commands/{command_id}",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "succeeded")

    def test_device_websocket_rejects_invalid_token(self) -> None:
        self.register_device()
        with self.assertRaises(Exception):
            with self.client.websocket_connect(
                "/v1/devices/ws?device_id=office-n150",
                headers={"Authorization": "Bearer wrong"},
            ):
                pass

    def test_online_device_receives_new_command_immediately(self) -> None:
        token = self.register_device()
        with self.client.websocket_connect(
            "/v1/devices/ws?device_id=office-n150",
            headers={"Authorization": f"Bearer {token}"},
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "hello")
            devices = self.client.get(
                "/v1/devices",
                headers={"Authorization": "Bearer admin-test"},
            )
            self.assertTrue(devices.json()["devices"][0]["connected"])
            created = self.client.post(
                "/v1/devices/office-n150/commands",
                headers={"Authorization": "Bearer admin-test"},
                json={"action": "cancel"},
            )
            self.assertEqual(created.status_code, 201)
            message = socket.receive_json()
            self.assertEqual(message["command"]["id"], created.json()["id"])
            self.assertEqual(created.json()["status"], "delivered")

    def test_command_schema_rejects_missing_volume(self) -> None:
        self.register_device()
        response = self.client.post(
            "/v1/devices/office-n150/commands",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "set_volume", "source": "room"},
        )
        self.assertEqual(response.status_code, 422)

    @patch("pilot_core.api.Integrations.music_assistant", new_callable=AsyncMock)
    def test_media_uses_provider_player_id(self, music_assistant) -> None:
        music_assistant.return_value = {"ok": True}
        response = self.client.post(
            "/v1/media",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "play", "player_id": "office-music"},
        )
        self.assertEqual(response.status_code, 200)
        music_assistant.assert_awaited_once_with(
            "players/cmd/play", {"player_id": "pilot-office"}
        )


if __name__ == "__main__":
    unittest.main()
