from __future__ import annotations

import unittest

from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.orchestration import ResolutionError, RoomOrchestrator
from pilot_core.registry import Registry
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
                default_device_id="office-primary",
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


class OrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        config = settings()
        self.store = Store(":memory:", config)
        self.store.register_device(
            "office-backup", "office", "Office Backup", ["audio"]
        )
        self.store.register_device(
            "office-primary", "office", "Office Primary", ["audio", "voice"]
        )
        self.orchestrator = RoomOrchestrator(Registry.from_settings(config), self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_default_music_player_is_resolved_from_room(self) -> None:
        player = self.orchestrator.music_player("office")
        self.assertEqual(player.id, "office-music")
        self.assertEqual(player.external_id, "pilot-office")

    def test_room_music_policy_fails_closed(self) -> None:
        config = settings()
        room = config.rooms[0]
        disabled = Settings(
            server=config.server,
            integrations=config.integrations,
            rooms=(
                Room(
                    id=room.id,
                    name=room.name,
                    response_player_id=room.response_player_id,
                    default_music_player_id=room.default_music_player_id,
                    default_device_id=room.default_device_id,
                    music_enabled=False,
                ),
            ),
            players=config.players,
        )
        store = Store(":memory:", disabled)
        try:
            orchestrator = RoomOrchestrator(Registry.from_settings(disabled), store)
            with self.assertRaisesRegex(ResolutionError, "music is disabled"):
                orchestrator.music_player("office")
        finally:
            store.close()

    def test_connected_capable_device_is_preferred_deterministically(self) -> None:
        selected = self.orchestrator.device(
            "office", {"office-primary"}, capability="audio"
        )
        self.assertEqual(selected.id, "office-primary")
        self.assertTrue(selected.connected)

    def test_default_device_is_used_when_all_candidates_are_offline(self) -> None:
        selected = self.orchestrator.device("office", set(), capability="audio")
        self.assertEqual(selected.id, "office-primary")

    def test_explicit_device_must_belong_to_room_and_have_capability(self) -> None:
        with self.assertRaisesRegex(ResolutionError, "capability voice"):
            self.orchestrator.device(
                "office",
                set(),
                capability="voice",
                device_id="office-backup",
            )

    def test_response_player_cannot_be_used_as_music_output(self) -> None:
        with self.assertRaisesRegex(ResolutionError, "not a music output"):
            self.orchestrator.music_player("office", "office-assistant")

    def test_room_state_combines_sources_health_and_targets(self) -> None:
        self.store.record_event("office-primary", "office", "health", {"ready": True})
        self.store.record_event(
            "office-primary",
            "office",
            "source_state",
            {"source": "music", "active": True},
        )
        state = self.orchestrator.room_state("office", {"office-primary"})
        self.assertEqual(state["focus"]["foreground"], "music")
        self.assertTrue(state["sources"]["music"]["active"])
        primary = next(
            item for item in state["devices"] if item["id"] == "office-primary"
        )
        self.assertTrue(primary["connected"])
        self.assertTrue(primary["health"]["payload"]["ready"])


if __name__ == "__main__":
    unittest.main()
