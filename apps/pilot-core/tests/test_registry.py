from __future__ import annotations

import unittest

from pilot_core.config import IntegrationSettings, Player, Room, ServerSettings, Settings
from pilot_core.registry import Registry


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            server=ServerSettings(),
            integrations=IntegrationSettings(),
            rooms=(
                Room(
                    id="office",
                    name="Office",
                    response_player_id="office-response",
                    default_music_player_id="office-music",
                ),
            ),
            players=(
                Player(
                    id="office-response",
                    room_id="office",
                    name="Office Assistant",
                    protocol="pipewire",
                    kind="response",
                ),
                Player(
                    id="office-music",
                    room_id="office",
                    name="Pilot Office Music",
                    protocol="sendspin",
                    kind="music",
                ),
            ),
        )

    def test_room_view_contains_players(self) -> None:
        registry = Registry.from_settings(self.settings)
        view = registry.room_view("office")
        self.assertEqual(view["default_music_player_id"], "office-music")
        self.assertEqual(len(view["players"]), 2)
        self.assertTrue(view["players"][1]["control_enabled"])

    def test_revision_is_deterministic(self) -> None:
        first = Registry.from_settings(self.settings)
        second = Registry.from_settings(self.settings)
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(len(first.revision), 12)


if __name__ == "__main__":
    unittest.main()
