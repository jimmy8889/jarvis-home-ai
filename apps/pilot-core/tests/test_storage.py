from __future__ import annotations

import unittest

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
            ),
        ),
    )


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:", settings())
        self.token = self.store.register_device(
            "office-n150", "office", "Office N150", ["audio", "voice"]
        )

    def tearDown(self) -> None:
        self.store.close()

    def test_device_token_is_required(self) -> None:
        self.assertTrue(self.store.authenticate_device("office-n150", self.token))
        self.assertFalse(self.store.authenticate_device("office-n150", "wrong"))
        self.assertNotIn("token", self.store.list_devices()[0])

    def test_source_events_update_focus(self) -> None:
        self.store.record_event(
            "office-n150",
            "office",
            "source_state",
            {"source": "music", "active": True},
        )
        event = self.store.record_event(
            "office-n150",
            "office",
            "source_state",
            {"source": "assistant", "active": True},
        )
        self.assertEqual(event["focus"]["foreground"], "assistant")
        self.assertEqual(event["focus"]["gains"]["music"], 0.2)

    def test_device_cannot_write_another_room(self) -> None:
        with self.assertRaises(PermissionError):
            self.store.record_event(
                "office-n150", "media-room", "health", {"ready": True}
            )

    def test_command_lifecycle_is_persisted(self) -> None:
        command = self.store.create_command(
            "office-n150", {"action": "pause", "source": "music"}, 30
        )
        self.assertEqual(command["status"], "queued")
        self.assertEqual(
            self.store.pending_commands("office-n150")[0]["id"], command["id"]
        )

        self.assertTrue(
            self.store.mark_command_delivered(command["id"], "office-n150")
        )
        completed = self.store.complete_command(
            command["id"],
            "office-n150",
            "succeeded",
            {"ok": True},
        )
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], {"ok": True})
        self.assertEqual(self.store.pending_commands("office-n150"), [])
        replayed = self.store.complete_command(
            command["id"],
            "office-n150",
            "failed",
            {"ok": False},
        )
        self.assertEqual(replayed["status"], "succeeded")
        self.assertEqual(replayed["result"], {"ok": True})

    def test_command_cannot_be_completed_by_another_device(self) -> None:
        command = self.store.create_command(
            "office-n150", {"action": "stop", "source": "music"}, 30
        )
        with self.assertRaises(KeyError):
            self.store.complete_command(
                command["id"], "other-device", "succeeded", {"ok": True}
            )


if __name__ == "__main__":
    unittest.main()
