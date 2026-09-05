from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import (
    IntegrationSettings,
    Player,
    Room,
    ServerSettings,
    Settings,
)
from pilot_core.meetings import (
    MeetingRecordingConflict,
    MeetingRecordingError,
    MeetingRecordings,
)
from pilot_core.storage import Store


def ticket_settings(root: Path, database_path: str = ":memory:") -> Settings:
    return Settings(
        server=ServerSettings(
            database_path=database_path,
            meeting_asset_path=str(root / "meetings"),
            public_upload_base_url="https://pilot-upload.example.com",
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


class MeetingUploadTicketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.settings = ticket_settings(Path(self.root.name))
        self.store = Store(":memory:", self.settings)
        self.token = self.store.register_device(
            "pilot-ios",
            "office",
            "Pilot iPhone",
            ["meetings", "portable-client"],
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "X-Pilot-Device-ID": "pilot-ios",
        }
        self.client = TestClient(create_app(self.settings, self.store))

    def tearDown(self) -> None:
        self.client.close()
        self.store.close()
        self.root.cleanup()

    def create_meeting(self, title: str = "Watch meeting") -> str:
        response = self.client.post(
            "/v1/devices/pilot-ios/meetings",
            headers=self.headers,
            json={"title": title},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["id"])

    def issue_ticket(self, meeting_id: str, recording: bytes) -> dict[str, object]:
        response = self.client.post(
            f"/v1/devices/pilot-ios/meetings/{meeting_id}/recording-upload-ticket",
            headers=self.headers,
            json={
                "filename": "watch-meeting.m4a",
                "content_type": "audio/m4a",
                "sha256": sha256(recording).hexdigest(),
                "size_bytes": len(recording),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    def upload(self, ticket: dict[str, object], recording: bytes):
        return self.client.put(
            str(ticket["upload_url"]),
            headers={
                "Authorization": f"Bearer {ticket['upload_token']}",
                "Content-Type": "audio/m4a",
                "X-Pilot-Filename": "watch-meeting.m4a",
            },
            content=recording,
        )

    def test_off_origin_ticket_upload_never_requires_device_credential(self) -> None:
        recording = b"durable watch meeting audio"
        meeting_id = self.create_meeting()
        manifest = self.client.get(
            "/v1/devices/pilot-ios/manifest", headers=self.headers
        ).json()
        self.assertEqual(
            manifest["endpoints"]["meeting_recording_upload"],
            "/v1/devices/pilot-ios/meetings/{meeting_id}/recording",
        )
        self.assertEqual(
            manifest["endpoints"]["meeting_recording_upload_ticket"],
            "/v1/devices/pilot-ios/meetings/{meeting_id}/recording-upload-ticket",
        )

        ticket = self.issue_ticket(meeting_id, recording)
        self.assertEqual(
            ticket["schema_version"],
            "pilot.meeting-recording-upload-ticket.v1",
        )
        self.assertEqual(
            ticket["upload_url"],
            f"https://pilot-upload.example.com/v1/meeting-recording-uploads/{ticket['ticket_id']}",
        )
        self.assertEqual(ticket["recording"]["sha256"], sha256(recording).hexdigest())
        expires_at = datetime.fromisoformat(str(ticket["expires_at"]))
        self.assertGreater(expires_at, datetime.now(UTC) + timedelta(hours=23))
        self.assertLessEqual(expires_at, datetime.now(UTC) + timedelta(hours=24, seconds=5))

        with self.store._lock:
            stored = self.store._connection.execute(
                "SELECT token_hash FROM meeting_recording_upload_tickets WHERE id = ?",
                (ticket["ticket_id"],),
            ).fetchone()
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertNotEqual(stored["token_hash"], ticket["upload_token"])

        rejected_device_token = self.client.put(
            str(ticket["upload_url"]),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "audio/m4a",
            },
            content=recording,
        )
        self.assertEqual(rejected_device_token.status_code, 401)

        accepted = self.upload(ticket, recording)
        self.assertEqual(accepted.status_code, 201, accepted.text)
        self.assertEqual(accepted.headers["cache-control"], "no-store")
        self.assertEqual(accepted.json()["meeting_id"], meeting_id)
        self.assertEqual(accepted.json()["sha256"], sha256(recording).hexdigest())
        self.assertEqual(self.store.get_meeting(meeting_id)["status"], "recorded")

        replay = self.upload(ticket, recording)
        self.assertEqual(replay.status_code, 401, replay.text)

    def test_ticket_binds_hash_and_size_before_recording_replace(self) -> None:
        expected = b"expected recording bytes"
        meeting_id = self.create_meeting()
        ticket = self.issue_ticket(meeting_id, expected)

        mismatch = self.upload(ticket, b"substituted recording")
        self.assertEqual(mismatch.status_code, 422, mismatch.text)
        self.assertIn("size does not match", mismatch.json()["detail"])
        self.assertIsNone(self.store.get_meeting_recording(meeting_id))
        self.assertFalse(
            (Path(self.root.name) / "meetings" / meeting_id / "recording.m4a").exists()
        )
        consumed = self.upload(ticket, expected)
        self.assertEqual(consumed.status_code, 401, consumed.text)

        fresh = self.issue_ticket(meeting_id, expected)
        accepted = self.upload(fresh, expected)
        self.assertEqual(accepted.status_code, 201, accepted.text)

    def test_ticket_size_bound_stops_stream_and_removes_partial_file(self) -> None:
        meeting_id = self.create_meeting("Early size bound")
        requested_chunks: list[str] = []

        async def chunks():
            requested_chunks.append("within-ticket")
            yield b"1234"
            requested_chunks.append("over-ticket")
            yield b"x" * 65_536
            requested_chunks.append("must-not-be-requested")
            yield b"y" * 65_536

        recordings = MeetingRecordings(
            self.store,
            str(Path(self.root.name) / "bounded-meetings"),
            max_bytes=1_000_000,
        )

        async def save() -> None:
            await recordings.save(
                meeting_id,
                "bounded.m4a",
                "audio/m4a",
                chunks(),
                expected_sha256=sha256(b"12345").hexdigest(),
                expected_size_bytes=5,
                replace_existing=False,
            )

        with self.assertRaisesRegex(
            MeetingRecordingError,
            "size does not match upload ticket",
        ):
            asyncio.run(save())

        self.assertEqual(requested_chunks, ["within-ticket", "over-ticket"])
        meeting_directory = (
            Path(self.root.name) / "bounded-meetings" / meeting_id
        )
        self.assertFalse((meeting_directory / "recording.m4a").exists())
        self.assertEqual(list(meeting_directory.glob(".upload-*")), [])
        self.assertIsNone(self.store.get_meeting_recording(meeting_id))

    def test_rotation_revocation_expiry_and_ownership_invalidate_ticket(self) -> None:
        recording = b"credential-bound recording"

        rotated_meeting = self.create_meeting("Rotated")
        rotated_ticket = self.issue_ticket(rotated_meeting, recording)
        self.store.rotate_device_credentials("pilot-ios")
        self.assertEqual(self.upload(rotated_ticket, recording).status_code, 401)

        # Re-register restores an active credential for independent checks.
        self.token = self.store.register_device(
            "pilot-ios",
            "office",
            "Pilot iPhone",
            ["meetings", "portable-client"],
        )
        self.headers["Authorization"] = f"Bearer {self.token}"
        expired_meeting = self.create_meeting("Expired")
        expired_ticket = self.issue_ticket(expired_meeting, recording)
        with self.store._lock, self.store._connection:
            self.store._connection.execute(
                """UPDATE meeting_recording_upload_tickets
                   SET expires_at = ? WHERE id = ?""",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    expired_ticket["ticket_id"],
                ),
            )
        self.assertEqual(self.upload(expired_ticket, recording).status_code, 401)

        ownership_meeting = self.create_meeting("Ownership")
        ownership_ticket = self.issue_ticket(ownership_meeting, recording)
        other_token = self.store.register_device(
            "pilot-ios-peer",
            "office",
            "Peer iPhone",
            ["meetings"],
        )
        self.assertTrue(other_token)
        with self.store._lock, self.store._connection:
            self.store._connection.execute(
                "UPDATE meetings SET source_device_id = ? WHERE id = ?",
                ("pilot-ios-peer", ownership_meeting),
            )
        self.assertEqual(self.upload(ownership_ticket, recording).status_code, 401)

        revoked_meeting = self.create_meeting("Revoked")
        revoked_ticket = self.issue_ticket(revoked_meeting, recording)
        self.store.revoke_device("pilot-ios")
        self.assertEqual(self.upload(revoked_ticket, recording).status_code, 401)

    def test_ticket_claim_is_atomic_and_legacy_device_upload_remains(self) -> None:
        recording = b"atomic ticket recording"
        meeting_id = self.create_meeting()
        ticket = self.issue_ticket(meeting_id, recording)
        first = self.store.claim_meeting_recording_upload_ticket(
            str(ticket["ticket_id"]), str(ticket["upload_token"])
        )
        self.assertEqual(first["meeting_id"], meeting_id)
        with self.assertRaises(PermissionError):
            self.store.claim_meeting_recording_upload_ticket(
                str(ticket["ticket_id"]), str(ticket["upload_token"])
            )

        legacy_meeting = self.create_meeting("Legacy same-origin")
        legacy = self.client.put(
            f"/v1/devices/pilot-ios/meetings/{legacy_meeting}/recording",
            headers={
                **self.headers,
                "Content-Type": "audio/m4a",
                "X-Pilot-Filename": "legacy.m4a",
            },
            content=recording,
        )
        self.assertEqual(legacy.status_code, 201, legacy.text)

    def test_claim_is_atomic_against_authority_changes_in_other_store(self) -> None:
        root = Path(self.root.name) / "claim-authority"
        database_path = root / "pilot.sqlite3"
        settings = ticket_settings(root, str(database_path))
        store_a = Store(str(database_path), settings)
        store_b = Store(str(database_path), settings)
        try:
            for suffix in ("revision", "revoked", "capability", "ownership"):
                device_id = f"pilot-{suffix}"
                store_a.register_device(
                    device_id,
                    "office",
                    f"Pilot {suffix}",
                    ["meetings", "portable-client"],
                )
                meeting = store_a.create_meeting(
                    f"Meeting {suffix}",
                    "en-AU",
                    datetime.now(UTC).isoformat(),
                    device_id,
                )
                ticket = store_a.create_meeting_recording_upload_ticket(
                    meeting["id"],
                    device_id,
                    "recording.m4a",
                    "audio/m4a",
                    sha256(suffix.encode()).hexdigest(),
                    len(suffix),
                )
                if suffix == "revision":
                    store_b.rotate_device_credentials(device_id)
                elif suffix == "revoked":
                    store_b.revoke_device(device_id)
                elif suffix == "capability":
                    store_b.update_device_capabilities(
                        device_id, ["portable-client"]
                    )
                else:
                    peer_id = "pilot-ownership-peer"
                    store_b.register_device(
                        peer_id,
                        "office",
                        "Ownership peer",
                        ["meetings"],
                    )
                    with store_b._lock, store_b._connection:
                        store_b._connection.execute(
                            """UPDATE meetings SET source_device_id = ?
                               WHERE id = ?""",
                            (peer_id, meeting["id"]),
                        )
                with self.subTest(suffix=suffix), self.assertRaises(
                    PermissionError
                ):
                    store_a.claim_meeting_recording_upload_ticket(
                        ticket["id"], ticket["upload_token"]
                    )

            # Hold an uncommitted credential change in Store B. Store A's
            # single UPDATE waits for it, then evaluates the new revision.
            device_id = "pilot-concurrent-revision"
            store_a.register_device(
                device_id,
                "office",
                "Concurrent Pilot",
                ["meetings"],
            )
            meeting = store_a.create_meeting(
                "Concurrent authority",
                "en-AU",
                datetime.now(UTC).isoformat(),
                device_id,
            )
            ticket = store_a.create_meeting_recording_upload_ticket(
                meeting["id"],
                device_id,
                "recording.m4a",
                "audio/m4a",
                sha256(b"concurrent").hexdigest(),
                len(b"concurrent"),
            )
            with store_b._lock:
                store_b._connection.execute("BEGIN IMMEDIATE")
                store_b._connection.execute(
                    """UPDATE devices
                       SET credential_revision = credential_revision + 1
                       WHERE id = ?""",
                    (device_id,),
                )

            update_started = threading.Event()
            outcome: list[BaseException | str] = []

            def trace(statement: str) -> None:
                if statement.startswith(
                    "UPDATE meeting_recording_upload_tickets AS ticket"
                ):
                    update_started.set()

            store_a._connection.set_trace_callback(trace)

            def claim() -> None:
                try:
                    store_a.claim_meeting_recording_upload_ticket(
                        ticket["id"], ticket["upload_token"]
                    )
                    outcome.append("claimed")
                except BaseException as error:
                    outcome.append(error)

            thread = threading.Thread(target=claim)
            thread.start()
            self.assertTrue(update_started.wait(timeout=2))
            with store_b._lock:
                store_b._connection.commit()
            thread.join(timeout=5)
            store_a._connection.set_trace_callback(None)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], PermissionError)
        finally:
            store_a.close()
            store_b.close()

    def test_two_stores_and_claimed_tickets_have_one_durable_winner(self) -> None:
        root = Path(self.root.name) / "recording-race"
        database_path = root / "pilot.sqlite3"
        settings = ticket_settings(root, str(database_path))
        store_a = Store(str(database_path), settings)
        store_b = Store(str(database_path), settings)
        try:
            device_id = "pilot-race"
            store_a.register_device(
                device_id,
                "office",
                "Racing Pilot",
                ["meetings"],
            )
            meeting = store_a.create_meeting(
                "One recording winner",
                "en-AU",
                datetime.now(UTC).isoformat(),
                device_id,
            )
            first_bytes = b"first distinct claimed ticket"
            second_bytes = b"second distinct claimed ticket"
            first_ticket = store_a.create_meeting_recording_upload_ticket(
                meeting["id"],
                device_id,
                "first.m4a",
                "audio/m4a",
                sha256(first_bytes).hexdigest(),
                len(first_bytes),
            )
            store_a.claim_meeting_recording_upload_ticket(
                first_ticket["id"], first_ticket["upload_token"]
            )
            second_ticket = store_b.create_meeting_recording_upload_ticket(
                meeting["id"],
                device_id,
                "second.m4a",
                "audio/m4a",
                sha256(second_bytes).hexdigest(),
                len(second_bytes),
            )
            store_b.claim_meeting_recording_upload_ticket(
                second_ticket["id"], second_ticket["upload_token"]
            )

            recordings_a = MeetingRecordings(
                store_a,
                settings.server.meeting_asset_path,
                settings.server.meeting_asset_max_bytes,
            )
            recordings_b = MeetingRecordings(
                store_b,
                settings.server.meeting_asset_path,
                settings.server.meeting_asset_max_bytes,
            )
            streams_ready = threading.Barrier(2)
            outcomes: list[dict[str, object] | BaseException] = []
            outcomes_lock = threading.Lock()

            async def chunks(payload: bytes):
                yield payload
                streams_ready.wait(timeout=5)

            def save(
                recordings: MeetingRecordings,
                payload: bytes,
                filename: str,
            ) -> None:
                try:
                    result = asyncio.run(
                        recordings.save(
                            meeting["id"],
                            filename,
                            "audio/m4a",
                            chunks(payload),
                            expected_sha256=sha256(payload).hexdigest(),
                            expected_size_bytes=len(payload),
                            replace_existing=False,
                        )
                    )
                except BaseException as error:
                    result = error
                with outcomes_lock:
                    outcomes.append(result)

            threads = [
                threading.Thread(
                    target=save,
                    args=(recordings_a, first_bytes, "first.m4a"),
                ),
                threading.Thread(
                    target=save,
                    args=(recordings_b, second_bytes, "second.m4a"),
                ),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())

            winners = [item for item in outcomes if isinstance(item, dict)]
            conflicts = [
                item
                for item in outcomes
                if isinstance(item, MeetingRecordingConflict)
            ]
            self.assertEqual(len(winners), 1, outcomes)
            self.assertEqual(len(conflicts), 1, outcomes)
            durable = store_a.get_meeting_recording(meeting["id"])
            self.assertIsNotNone(durable)
            assert durable is not None
            destination = Path(durable["path"])
            durable_bytes = destination.read_bytes()
            self.assertIn(durable_bytes, (first_bytes, second_bytes))
            self.assertEqual(durable["sha256"], sha256(durable_bytes).hexdigest())
            self.assertEqual(
                list(destination.parent.glob(".upload-*")),
                [],
            )
        finally:
            store_a.close()
            store_b.close()

    def test_final_file_and_directory_are_synced_before_database_commit(self) -> None:
        meeting_id = self.create_meeting("Durable ordering")
        payload = b"fsync before database commit"
        root = Path(self.root.name) / "fsync-order"
        recordings = MeetingRecordings(self.store, str(root), 1_000_000)
        events: list[str] = []
        real_fsync = os.fsync
        real_set_recording = self.store.set_meeting_recording

        def observed_fsync(descriptor: int) -> None:
            kind = "directory" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file"
            events.append(kind)
            real_fsync(descriptor)

        def observed_set_recording(*args, **kwargs):
            events.append("database")
            return real_set_recording(*args, **kwargs)

        async def chunks():
            yield payload

        with (
            patch("pilot_core.meetings.os.fsync", side_effect=observed_fsync),
            patch.object(
                self.store,
                "set_meeting_recording",
                side_effect=observed_set_recording,
            ),
        ):
            asyncio.run(
                recordings.save(
                    meeting_id,
                    "durable.m4a",
                    "audio/m4a",
                    chunks(),
                    expected_sha256=sha256(payload).hexdigest(),
                    expected_size_bytes=len(payload),
                    replace_existing=False,
                )
            )

        self.assertEqual(events[-3:], ["file", "directory", "database"])

    def test_startup_cleanup_is_bounded_and_skips_active_or_recent_uploads(
        self,
    ) -> None:
        now = datetime.now(UTC)
        root = Path(self.root.name) / "stale-cleanup"
        meeting_directory = root / "meeting-one"
        meeting_directory.mkdir(parents=True)
        stale = meeting_directory / ".upload-stale"
        recent = meeting_directory / ".upload-recent"
        active = meeting_directory / ".upload-active"
        for path in (stale, recent, active):
            path.write_bytes(b"partial")
        old_timestamp = (now - timedelta(hours=7)).timestamp()
        os.utime(stale, (old_timestamp, old_timestamp))
        os.utime(active, (old_timestamp, old_timestamp))

        with active.open("r+b") as active_handle:
            fcntl.flock(active_handle.fileno(), fcntl.LOCK_EX)
            MeetingRecordings(self.store, str(root), 1_000_000)
            self.assertFalse(stale.exists())
            self.assertTrue(active.exists())
            self.assertTrue(recent.exists())

        bounded_root = Path(self.root.name) / "bounded-cleanup"
        bounded = MeetingRecordings(self.store, str(bounded_root), 1_000_000)
        bounded_directory = bounded_root / "meeting-two"
        bounded_directory.mkdir(parents=True)
        leftovers = [
            bounded_directory / f".upload-{index}" for index in range(5)
        ]
        for path in leftovers:
            path.write_bytes(b"crash leftover")
            os.utime(path, (old_timestamp, old_timestamp))
        removed = bounded.cleanup_stale_uploads(
            now=now,
            stale_after_seconds=6 * 60 * 60,
            max_entries=3,
        )
        self.assertEqual(removed, 2)
        self.assertEqual(sum(path.exists() for path in leftovers), 3)

    def test_existing_database_creates_upload_ticket_table(self) -> None:
        database_path = Path(self.root.name) / "pilot.sqlite3"
        settings = ticket_settings(Path(self.root.name), str(database_path))
        original = Store(str(database_path), settings)
        try:
            original.create_meeting(
                "Existing meeting",
                "en-AU",
                datetime.now(UTC).isoformat(),
                None,
            )
            with original._lock, original._connection:
                original._connection.execute(
                    "DROP TABLE meeting_recording_upload_tickets"
                )
        finally:
            original.close()

        migrated = Store(str(database_path), settings)
        try:
            with sqlite3.connect(database_path) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(meeting_recording_upload_tickets)"
                    )
                }
            self.assertIn("token_hash", columns)
            self.assertIn("claimed_at", columns)
            self.assertEqual(len(migrated.list_meetings()), 1)
        finally:
            migrated.close()


if __name__ == "__main__":
    unittest.main()
