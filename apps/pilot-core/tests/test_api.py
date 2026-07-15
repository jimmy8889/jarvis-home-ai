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
