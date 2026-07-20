from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
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

    def test_device_capabilities_can_change_without_rotating_token(self) -> None:
        updated = self.store.update_device_capabilities(
            "office-n150", ["audio", "media-control", "voice", "audio"]
        )

        self.assertEqual(
            updated["capabilities"], ["audio", "media-control", "voice"]
        )
        self.assertTrue(self.store.authenticate_device("office-n150", self.token))
        with self.assertRaises(KeyError):
            self.store.update_device_capabilities("missing", ["display"])

    def test_bootstrap_grant_is_bound_and_single_use(self) -> None:
        grant = self.store.create_bootstrap_grant(
            "new-office", "office", "New Office", ["voice", "audio"], 600
        )
        registration = self.store.redeem_bootstrap_grant(grant["bootstrap_token"])
        self.assertEqual(registration["device_id"], "new-office")
        self.assertTrue(
            self.store.authenticate_device("new-office", registration["device_token"])
        )
        with self.assertRaises(PermissionError):
            self.store.redeem_bootstrap_grant(grant["bootstrap_token"])

    def test_new_grant_revokes_older_unused_grant_for_device(self) -> None:
        first = self.store.create_bootstrap_grant(
            "new-office", "office", "New Office", ["audio"], 600
        )
        second = self.store.create_bootstrap_grant(
            "new-office", "office", "New Office", ["audio"], 600
        )
        with self.assertRaises(PermissionError):
            self.store.redeem_bootstrap_grant(first["bootstrap_token"])
        self.assertEqual(
            self.store.redeem_bootstrap_grant(second["bootstrap_token"])["device_id"],
            "new-office",
        )

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

    def test_conversation_session_is_room_and_device_scoped(self) -> None:
        session = self.store.resolve_conversation_session(
            "office",
            device_id="office-n150",
        )
        self.store.append_conversation_turn(
            session["id"],
            "user",
            "Turn on the light",
        )
        self.store.append_conversation_turn(
            session["id"],
            "assistant",
            "The light is on.",
            {"provider": "home_assistant"},
        )
        continued = self.store.resolve_conversation_session(
            "office",
            session["id"],
            device_id="office-n150",
        )
        self.assertEqual(continued["id"], session["id"])
        turns = self.store.conversation_turns(session["id"])
        self.assertEqual([turn["role"] for turn in turns], ["user", "assistant"])

        other_device = self.store.resolve_conversation_session(
            "office",
            session["id"],
            device_id="another-device",
        )
        self.assertNotEqual(other_device["id"], session["id"])

    def test_conversation_provider_id_and_end_are_persisted(self) -> None:
        session = self.store.resolve_conversation_session("office")
        self.store.update_conversation_provider_id(session["id"], "ha-session")
        stored = self.store.get_conversation_session(session["id"])
        assert stored is not None
        self.assertEqual(stored["provider_conversation_id"], "ha-session")
        self.assertTrue(self.store.end_conversation_session(session["id"]))
        ended = self.store.get_conversation_session(session["id"])
        assert ended is not None
        self.assertEqual(ended["status"], "ended")

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

        self.assertTrue(self.store.mark_command_delivered(command["id"], "office-n150"))
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

    def test_legacy_room_table_is_migrated_for_default_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.db"
            connection = sqlite3.connect(path)
            connection.execute(
                """CREATE TABLE rooms (
                       id TEXT PRIMARY KEY,
                       name TEXT NOT NULL,
                       response_player_id TEXT NOT NULL,
                       default_music_player_id TEXT NOT NULL,
                       agent_url TEXT NOT NULL DEFAULT ''
                   )"""
            )
            connection.commit()
            connection.close()

            migrated = Store(str(path), settings())
            migrated.close()
            connection = sqlite3.connect(path)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(rooms)")}
            connection.close()
        self.assertIn("default_device_id", columns)

    def test_legacy_player_table_is_migrated_for_control_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """CREATE TABLE rooms (
                       id TEXT PRIMARY KEY,
                       name TEXT NOT NULL,
                       response_player_id TEXT NOT NULL,
                       default_music_player_id TEXT NOT NULL,
                       default_device_id TEXT NOT NULL DEFAULT '',
                       agent_url TEXT NOT NULL DEFAULT ''
                   );
                   CREATE TABLE players (
                       id TEXT PRIMARY KEY,
                       room_id TEXT NOT NULL REFERENCES rooms(id),
                       name TEXT NOT NULL,
                       protocol TEXT NOT NULL,
                       kind TEXT NOT NULL,
                       endpoint TEXT NOT NULL DEFAULT '',
                       external_id TEXT NOT NULL DEFAULT '',
                       enabled INTEGER NOT NULL DEFAULT 1
                   );"""
            )
            connection.commit()
            connection.close()

            migrated = Store(str(path), settings())
            migrated.close()
            connection = sqlite3.connect(path)
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(players)")
            }
            policies = {
                row[0]: row[1]
                for row in connection.execute("SELECT id, control_enabled FROM players")
            }
            connection.close()
        self.assertIn("control_enabled", columns)
        self.assertIn("control_endpoint", columns)
        self.assertEqual(policies["office-music"], 1)


if __name__ == "__main__":
    unittest.main()
