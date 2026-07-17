from __future__ import annotations

import json
import os
import unittest

import httpx

from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.integrations import Integrations
from pilot_core.media_state import MediaStateReader
from pilot_core.registry import Registry


class MediaStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-token"
        os.environ["MUSIC_ASSISTANT_TOKEN"] = "ma-token"

    async def asyncTearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)
        os.environ.pop("MUSIC_ASSISTANT_TOKEN", None)

    def settings(self) -> Settings:
        return Settings(
            server=ServerSettings(),
            integrations=IntegrationSettings(
                home_assistant_url="http://ha.local:8123",
                music_assistant_url="http://ma.local:8095",
            ),
            rooms=(
                Room(
                    id="media-room",
                    name="Media Room",
                    response_player_id="media-response",
                    default_music_player_id="media-heos",
                ),
            ),
            players=(
                Player(
                    id="media-response",
                    room_id="media-room",
                    name="Media Room Assistant",
                    protocol="heos",
                    kind="response",
                    endpoint="media_player.media_room",
                    external_id="1174905188",
                    control_enabled=False,
                ),
                Player(
                    id="media-heos",
                    room_id="media-room",
                    name="Media Room",
                    protocol="heos",
                    kind="music",
                    endpoint="media_player.media_room",
                    external_id="1174905188",
                    control_enabled=False,
                ),
            ),
        )

    async def test_builds_safe_provider_neutral_player_state(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.host == "ma.local":
                payload = json.loads(request.content)
                self.assertEqual(payload["command"], "players/all")
                return httpx.Response(
                    200,
                    json=[
                        {
                            "player_id": "1174905188",
                            "name": "Media Room",
                            "provider": "heos",
                            "available": True,
                            "powered": True,
                            "state": "idle",
                            "volume_level": 35,
                            "active_source": "1174905188",
                            "group_childs": [],
                            "device_info": {
                                "manufacturer": "Denon",
                                "model": "AVC-X8500H",
                                "software_version": "3.88.614",
                                "ip_address": "10.0.1.150",
                                "mac_address": "not-returned",
                                "identifiers": {"secret": "not-returned"},
                            },
                        }
                    ],
                )
            self.assertEqual(request.url.path, "/api/states/media_player.media_room")
            return httpx.Response(
                200,
                json={
                    "entity_id": "media_player.media_room",
                    "state": "idle",
                    "last_changed": "2026-07-17T00:00:00+00:00",
                    "attributes": {
                        "friendly_name": "Media Room",
                        "volume_level": 0.35,
                        "is_volume_muted": False,
                        "media_title": "Dance into the Light",
                        "media_artist": "Phil Collins",
                        "supported_features": 3079741,
                    },
                },
            )

        config = self.settings()
        reader = MediaStateReader(
            Registry.from_settings(config),
            Integrations(config.integrations, httpx.MockTransport(handler)),
        )
        snapshot = await reader.snapshot("media-room")
        state = snapshot["players"]["media-heos"]
        self.assertEqual(snapshot["providers"]["music_assistant"]["status"], "ok")
        self.assertEqual(snapshot["providers"]["home_assistant"]["status"], "ok")
        self.assertEqual(state["status"], "ok")
        self.assertTrue(state["effective"]["available"])
        self.assertEqual(state["effective"]["volume_percent"], 35)
        self.assertEqual(state["effective"]["media"]["title"], "Dance into the Light")
        self.assertEqual(state["music_assistant"]["device"]["model"], "AVC-X8500H")
        self.assertNotIn("identifiers", state["music_assistant"]["device"])
        self.assertFalse(state["player"]["control_enabled"])
        self.assertEqual(sum(request.url.host == "ha.local" for request in requests), 1)

    async def test_missing_provider_credentials_fail_closed_without_network(
        self,
    ) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN")
        os.environ.pop("MUSIC_ASSISTANT_TOKEN")
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(500)

        config = self.settings()
        reader = MediaStateReader(
            Registry.from_settings(config),
            Integrations(config.integrations, httpx.MockTransport(handler)),
        )
        snapshot = await reader.snapshot()
        self.assertEqual(
            snapshot["providers"]["music_assistant"]["status"],
            "not_configured",
        )
        self.assertEqual(snapshot["providers"]["home_assistant"]["status"], "partial")
        self.assertEqual(snapshot["players"]["media-heos"]["status"], "unresolved")
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
