from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.storage import Store


def watch_settings(root: Path) -> Settings:
    return Settings(
        server=ServerSettings(
            database_path=":memory:",
            meeting_asset_path=str(root / "meetings"),
        ),
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


class WatchMeetingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.settings = watch_settings(Path(self.root.name))
        self.store = Store(":memory:", self.settings)
        self.token = self.store.register_device(
            "pilot-ios",
            "office",
            "Pilot iPhone",
            ["meetings", "portable-client"],
        )
        self.client = TestClient(create_app(self.settings, self.store))
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Pilot-Device-ID": "pilot-ios",
        }

    def tearDown(self) -> None:
        self.client.close()
        self.store.close()
        self.root.cleanup()

    def test_watch_capture_id_makes_device_create_idempotent(self) -> None:
        payload = {
            "title": "Watch meeting",
            "language": "en-AU",
            "started_at": "2026-08-11T09:30:00+10:00",
            "source_capture_id": "a1817c57-6cd6-4b52-a86d-284ecbdbf1ae",
        }

        first = self.client.post(
            "/v1/devices/pilot-ios/meetings",
            headers=self.headers,
            json=payload,
        )
        replay = self.client.post(
            "/v1/devices/pilot-ios/meetings",
            headers=self.headers,
            json={**payload, "title": "A replay must not replace the original"},
        )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json()["id"], first.json()["id"])
        self.assertEqual(replay.json()["title"], "Watch meeting")
        self.assertEqual(
            replay.json()["source_capture_id"], payload["source_capture_id"]
        )
        listing = self.client.get(
            "/v1/devices/pilot-ios/meetings", headers=self.headers
        )
        self.assertEqual(len(listing.json()["meetings"]), 1)

    def test_capture_id_is_scoped_to_authenticated_device(self) -> None:
        other_token = self.store.register_device(
            "pilot-ios-peer",
            "office",
            "Second Pilot iPhone",
            ["meetings", "portable-client"],
        )
        capture_id = "d51ab205-bb18-4396-b593-d8451cc57f86"
        first = self.client.post(
            "/v1/devices/pilot-ios/meetings",
            headers=self.headers,
            json={"title": "First", "source_capture_id": capture_id},
        )
        second = self.client.post(
            "/v1/devices/pilot-ios-peer/meetings",
            headers={
                "Authorization": f"Bearer {other_token}",
                "X-Pilot-Device-ID": "pilot-ios-peer",
            },
            json={"title": "Second", "source_capture_id": capture_id},
        )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(first.json()["id"], second.json()["id"])

    def test_existing_meeting_database_gains_capture_id_without_data_loss(self) -> None:
        database_path = Path(self.root.name) / "legacy.sqlite3"
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                """CREATE TABLE meetings (
                       id TEXT PRIMARY KEY,
                       title TEXT NOT NULL,
                       language TEXT NOT NULL,
                       source_device_id TEXT,
                       started_at TEXT NOT NULL,
                       ended_at TEXT,
                       status TEXT NOT NULL,
                       summary TEXT,
                       created_at TEXT NOT NULL,
                       updated_at TEXT NOT NULL
                   )"""
            )
            connection.execute(
                """INSERT INTO meetings
                   (id, title, language, source_device_id, started_at, status,
                    created_at, updated_at)
                   VALUES ('legacy', 'Legacy meeting', 'en-AU', NULL,
                           '2026-01-01T00:00:00+00:00', 'created',
                           '2026-01-01T00:00:00+00:00',
                           '2026-01-01T00:00:00+00:00')"""
            )

        migrated = Store(str(database_path), self.settings)
        try:
            meeting = migrated.get_meeting("legacy")
            self.assertIsNotNone(meeting)
            assert meeting is not None
            self.assertIsNone(meeting["source_capture_id"])
            with sqlite3.connect(database_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(meetings)")
                }
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(meetings)")
                }
            self.assertIn("source_capture_id", columns)
            self.assertIn("meetings_source_capture", indexes)
        finally:
            migrated.close()


if __name__ == "__main__":
    unittest.main()
