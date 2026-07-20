from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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
from pilot_core.tts import SynthesizedAudio


def settings(audio_asset_path: str = "/tmp/pilot-core-test-audio") -> Settings:
    return Settings(
        server=ServerSettings(
            database_path=":memory:",
            audio_asset_path=audio_asset_path,
            meeting_asset_path=str(Path(audio_asset_path) / "meetings"),
        ),
        integrations=IntegrationSettings(),
        rooms=(
            Room(
                id="office",
                name="Office",
                response_player_id="office-assistant",
                default_music_player_id="office-music",
                default_device_id="office-n150",
            ),
            Room(
                id="media-room",
                name="Media Room",
                response_player_id="media-assistant",
                default_music_player_id="media-music",
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
            Player(
                id="media-assistant",
                room_id="media-room",
                name="Media Assistant",
                protocol="pipewire",
                kind="response",
            ),
            Player(
                id="media-music",
                room_id="media-room",
                name="Media Music",
                protocol="heos",
                kind="music",
                endpoint="media_player.media_room",
                external_id="denon-media-room",
            ),
        ),
    )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["PILOT_CORE_ADMIN_TOKEN"] = "admin-test"
        os.environ["PILOT_CORE_BOOTSTRAP_TOKEN"] = "bootstrap-test"
        self.audio_directory = tempfile.TemporaryDirectory()
        config = settings(self.audio_directory.name)
        self.store = Store(":memory:", config)
        self.client = TestClient(create_app(config, self.store))

    def tearDown(self) -> None:
        os.environ.pop("PILOT_CORE_ADMIN_TOKEN", None)
        os.environ.pop("PILOT_CORE_BOOTSTRAP_TOKEN", None)
        self.client.close()
        self.store.close()
        self.audio_directory.cleanup()

    def test_admin_api_requires_token(self) -> None:
        self.assertEqual(self.client.get("/v1/rooms").status_code, 401)
        response = self.client.get(
            "/v1/rooms", headers={"Authorization": "Bearer admin-test"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("office", {room["id"] for room in response.json()["rooms"]})

    def test_meeting_ingestion_transcript_and_analysis_are_local_and_reviewable(
        self,
    ) -> None:
        headers = {"Authorization": "Bearer admin-test"}
        created = self.client.post(
            "/v1/meetings",
            headers=headers,
            json={
                "title": "Office planning",
                "language": "en-AU",
                "started_at": "2026-07-17T09:00:00+10:00",
            },
        )
        self.assertEqual(created.status_code, 201)
        meeting_id = created.json()["id"]
        self.assertEqual(created.json()["status"], "created")

        recording_bytes = b"RIFF\x10\x00\x00\x00WAVEfmt "
        uploaded = self.client.put(
            f"/v1/meetings/{meeting_id}/recording",
            headers={
                **headers,
                "Content-Type": "audio/wav",
                "X-Pilot-Filename": "../../planning.wav",
            },
            content=recording_bytes,
        )
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(uploaded.json()["filename"], "planning.wav")
        self.assertNotIn("path", uploaded.json())
        self.assertEqual(uploaded.json()["size_bytes"], len(recording_bytes))

        transcript = self.client.put(
            f"/v1/meetings/{meeting_id}/transcript",
            headers=headers,
            json={
                "segments": [
                    {
                        "speaker_label": "Speaker 1",
                        "start_ms": 0,
                        "end_ms": 2400,
                        "text": "Rachael will prepare pricing by Friday.",
                        "confidence": 0.94,
                    }
                ]
            },
        )
        self.assertEqual(transcript.status_code, 200)
        self.assertEqual(transcript.json()["status"], "transcribed")
        segment_id = transcript.json()["transcript"][0]["id"]

        analysis = self.client.put(
            f"/v1/meetings/{meeting_id}/analysis",
            headers=headers,
            json={
                "summary": "The team assigned the pricing work.",
                "decisions": [
                    {
                        "summary": "Pricing is due Friday.",
                        "segment_ids": [segment_id],
                    }
                ],
                "action_items": [
                    {
                        "task": "Prepare pricing",
                        "owner": "Rachael",
                        "due_at": "2026-07-18T17:00:00+10:00",
                        "confidence": 0.91,
                        "segment_ids": [segment_id],
                    }
                ],
            },
        )
        self.assertEqual(analysis.status_code, 200)
        payload = analysis.json()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["action_items"][0]["owner"], "Rachael")
        self.assertEqual(payload["decisions"][0]["segment_ids"], [segment_id])
        self.assertNotIn("path", payload["recording"])

        listing = self.client.get("/v1/meetings", headers=headers)
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(listing.json()["meetings"][0]["has_recording"])
        self.assertEqual(listing.json()["meetings"][0]["transcript_segment_count"], 1)
        self.assertEqual(listing.json()["meetings"][0]["action_item_count"], 1)

        downloaded = self.client.get(
            f"/v1/meetings/{meeting_id}/recording", headers=headers
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, recording_bytes)

    def test_meeting_recording_rejects_unsupported_content(self) -> None:
        headers = {"Authorization": "Bearer admin-test"}
        meeting_id = self.client.post(
            "/v1/meetings",
            headers=headers,
            json={"title": "Unsafe upload"},
        ).json()["id"]
        response = self.client.put(
            f"/v1/meetings/{meeting_id}/recording",
            headers={**headers, "Content-Type": "application/octet-stream"},
            content=b"not audio",
        )
        self.assertEqual(response.status_code, 422)

    @patch("pilot_core.api.MeetingProcessor.process", new_callable=AsyncMock)
    def test_device_meetings_are_capability_scoped_owned_and_queued(
        self, process
    ) -> None:
        registration = self.client.post(
            "/v1/devices/register",
            headers={"Authorization": "Bearer bootstrap-test"},
            json={
                "device_id": "pilot-ios",
                "room_id": "office",
                "name": "Pilot iPhone",
                "capabilities": ["meetings", "portable-client"],
            },
        )
        token = registration.json()["device_token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Pilot-Device-ID": "pilot-ios",
        }
        created = self.client.post(
            "/v1/devices/pilot-ios/meetings",
            headers=headers,
            json={
                "title": "Client planning",
                "source_device_id": "pilot-ios",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        meeting_id = created.json()["id"]
        self.assertEqual(created.json()["source_device_id"], "pilot-ios")

        upload = self.client.put(
            f"/v1/devices/pilot-ios/meetings/{meeting_id}/recording",
            headers={
                **headers,
                "Content-Type": "audio/wav",
                "X-Pilot-Filename": "planning.wav",
            },
            content=b"RIFF\x10\x00\x00\x00WAVEfmt ",
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        process.return_value = {
            **self.store.get_meeting(meeting_id),
            "status": "ready",
        }
        queued = self.client.post(
            f"/v1/devices/pilot-ios/meetings/{meeting_id}/process",
            headers=headers,
        )
        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(queued.json()["meeting"]["status"], "processing")
        process.assert_awaited_once_with(meeting_id)

        listing = self.client.get(
            "/v1/devices/pilot-ios/meetings",
            headers=headers,
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([item["id"] for item in listing.json()["meetings"]], [meeting_id])

        other_id = self.store.create_meeting(
            "Another device",
            "en",
            "2026-07-21T00:00:00+00:00",
            "another-device",
        )["id"]
        forbidden = self.client.get(
            f"/v1/devices/pilot-ios/meetings/{other_id}",
            headers=headers,
        )
        self.assertEqual(forbidden.status_code, 404)

        no_capability_token = self.register_device()
        no_capability = self.client.get(
            "/v1/devices/office-n150/meetings",
            headers={
                "Authorization": f"Bearer {no_capability_token}",
                "X-Pilot-Device-ID": "office-n150",
            },
        )
        self.assertEqual(no_capability.status_code, 403)

    @patch("pilot_core.api.MeetingProcessor.process", new_callable=AsyncMock)
    def test_meeting_processing_endpoint_is_admin_only(self, process) -> None:
        headers = {"Authorization": "Bearer admin-test"}
        meeting_id = self.client.post(
            "/v1/meetings",
            headers=headers,
            json={"title": "Local processing"},
        ).json()["id"]
        process.return_value = {
            **self.store.get_meeting(meeting_id),
            "status": "ready",
            "summary": "Processed locally.",
        }
        unauthorized = self.client.post(f"/v1/meetings/{meeting_id}/process")
        self.assertEqual(unauthorized.status_code, 401)
        response = self.client.post(
            f"/v1/meetings/{meeting_id}/process",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ready")
        process.assert_awaited_once_with(meeting_id)

    def test_dashboard_shell_and_assets_have_security_headers(self) -> None:
        root = self.client.get("/", follow_redirects=False)
        self.assertEqual(root.status_code, 307)
        self.assertEqual(root.headers["location"], "/dashboard")

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Pilot Core", dashboard.text)
        self.assertIn("Assistant engine", dashboard.text)
        self.assertIn("Semantic catalogue", dashboard.text)
        self.assertIn("Find any entity", dashboard.text)
        self.assertEqual(dashboard.headers["cache-control"], "no-store")
        self.assertIn(
            "frame-ancestors 'none'",
            dashboard.headers["content-security-policy"],
        )
        self.assertEqual(dashboard.headers["x-frame-options"], "DENY")

        script = self.client.get("/dashboard/assets/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("sessionStorage", script.text)
        self.assertEqual(
            self.client.get("/dashboard/assets/not-allowed.js").status_code,
            404,
        )

    def test_operations_requires_admin_and_handles_unenrolled_rooms(self) -> None:
        self.assertEqual(self.client.get("/v1/operations").status_code, 401)
        response = self.client.get(
            "/v1/operations",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertEqual(payload["deployment"]["version"], "0.23.1")
        self.assertEqual(payload["summary"]["room_count"], 2)
        self.assertEqual(payload["summary"]["device_count"], 0)
        self.assertEqual(payload["summary"]["armed_room_count"], 0)
        self.assertEqual(payload["summary"]["unarmed_room_count"], 2)
        self.assertTrue(payload["safety"]["audible_actions_gated"])
        self.assertEqual(
            set(payload["safety"]["unarmed_rooms"]),
            {"office", "media-room"},
        )
        self.assertIn("home_assistant", payload["integrations"])
        self.assertIn("music_assistant", payload["integrations"])
        self.assertIn("tts", payload["integrations"])
        self.assertIn("players", payload["media"])
        self.assertEqual(payload["assistant"]["session_owner"], "pilot_core")
        self.assertFalse(payload["assistant"]["llm"]["configured"])
        self.assertEqual(payload["integrations"]["tts"]["status"], "not_configured")
        self.assertIn(payload["observability"]["status"], {"guarded", "degraded"})

        self.assertEqual(self.client.get("/v1/observability").status_code, 401)
        observability = self.client.get(
            "/v1/observability",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(observability.status_code, 200)
        self.assertEqual(observability.headers["cache-control"], "no-store")
        self.assertIn("alerts", observability.json())

        self.assertEqual(self.client.get("/v1/metrics").status_code, 401)
        metrics = self.client.get(
            "/v1/metrics",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.headers["cache-control"], "no-store")
        self.assertIn("pilot_core_up 1", metrics.text)
        self.assertNotIn("admin-test", metrics.text)

    def test_configured_tts_is_not_reported_as_unhealthy(self) -> None:
        config = settings(self.audio_directory.name)
        config = replace(
            config,
            integrations=replace(
                config.integrations,
                tts_url="http://tts.internal:8000",
                tts_provider="piper",
            ),
        )
        store = Store(":memory:", config)
        client = TestClient(create_app(config, store))
        try:
            response = client.get(
                "/v1/operations",
                headers={"Authorization": "Bearer admin-test"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["integrations"]["tts"]["status"], "ok")
            self.assertNotIn(
                "tts",
                {
                    alert.get("integration_id")
                    for alert in payload["observability"]["alerts"]
                },
            )
        finally:
            client.close()
            store.close()

    def test_operations_aggregates_health_commands_and_events(self) -> None:
        token = self.register_device()
        health = self.client.post(
            "/v1/events",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Pilot-Device-ID": "office-n150",
            },
            json={
                "room_id": "office",
                "type": "health",
                "payload": {
                    "ready": True,
                    "uptime_seconds": 123,
                    "audio_activation": {"allowed": False},
                },
            },
        )
        self.assertEqual(health.status_code, 200)
        command = self.client.post(
            "/v1/rooms/office/control",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "cancel"},
        )
        self.assertEqual(command.status_code, 201)

        response = self.client.get(
            "/v1/operations",
            headers={"Authorization": "Bearer admin-test"},
        )
        payload = response.json()
        self.assertEqual(payload["summary"]["device_count"], 1)
        self.assertEqual(payload["summary"]["connected_device_count"], 0)
        self.assertEqual(payload["summary"]["pending_command_count"], 1)
        self.assertEqual(payload["rooms"]["office"]["devices"][0]["id"], "office-n150")
        self.assertFalse(
            payload["rooms"]["office"]["devices"][0]["health"]["payload"][
                "audio_activation"
            ]["allowed"]
        )
        self.assertEqual(payload["commands"][0]["payload"]["action"], "cancel")
        self.assertEqual(payload["events"][0]["type"], "health")

        commands = self.client.get(
            "/v1/commands?limit=1",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(commands.status_code, 200)
        self.assertEqual(len(commands.json()["commands"]), 1)
        self.assertEqual(
            commands.json()["commands"][0]["id"],
            command.json()["command"]["id"],
        )

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

    def test_one_time_bootstrap_grant_registers_device_once(self) -> None:
        grant_response = self.client.post(
            "/v1/bootstrap-grants",
            headers={"Authorization": "Bearer admin-test"},
            json={
                "device_id": "grant-office",
                "room_id": "office",
                "name": "Grant Office",
                "capabilities": ["audio", "voice"],
                "expires_in_seconds": 600,
            },
        )
        self.assertEqual(grant_response.status_code, 201)
        self.assertEqual(grant_response.headers["cache-control"], "no-store")
        grant = grant_response.json()
        self.assertEqual(grant["device_id"], "grant-office")

        registered = self.client.post(
            "/v1/devices/bootstrap",
            headers={"Authorization": f"Bearer {grant['bootstrap_token']}"},
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.headers["cache-control"], "no-store")
        self.assertEqual(registered.json()["device_id"], "grant-office")
        replay = self.client.post(
            "/v1/devices/bootstrap",
            headers={"Authorization": f"Bearer {grant['bootstrap_token']}"},
        )
        self.assertEqual(replay.status_code, 401)

    def test_admin_can_update_device_capabilities_without_reenrollment(self) -> None:
        token = self.register_device()

        response = self.client.patch(
            "/v1/devices/office-n150/capabilities",
            headers={"Authorization": "Bearer admin-test"},
            json={"capabilities": ["audio", "media-control", "voice", "voice"]},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["device"]["capabilities"],
            ["audio", "media-control", "voice"],
        )
        self.assertTrue(self.store.authenticate_device("office-n150", token))

    def test_legacy_bootstrap_endpoint_can_be_disabled(self) -> None:
        config = settings(self.audio_directory.name)
        config = replace(
            config,
            server=replace(config.server, legacy_bootstrap_enabled=False),
        )
        store = Store(":memory:", config)
        with TestClient(create_app(config, store)) as client:
            response = client.post(
                "/v1/devices/register",
                headers={"Authorization": "Bearer bootstrap-test"},
                json={
                    "device_id": "legacy-office",
                    "room_id": "office",
                    "name": "Legacy Office",
                    "capabilities": ["audio"],
                },
            )
        store.close()
        self.assertEqual(response.status_code, 403)

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

    def test_room_audio_asset_is_private_and_queues_verified_playback(self) -> None:
        office_token = self.register_device()
        upload = self.client.post(
            "/v1/rooms/office/audio-assets",
            params={"kind": "assistant", "filename": "reply.wav"},
            headers={
                "Authorization": "Bearer admin-test",
                "Content-Type": "audio/wav",
            },
            content=b"RIFF-pilot-test",
        )
        self.assertEqual(upload.status_code, 201)
        asset = upload.json()
        self.assertNotIn("path", asset)

        download = self.client.get(
            f"/v1/audio-assets/{asset['id']}",
            headers={
                "Authorization": f"Bearer {office_token}",
                "X-Pilot-Device-ID": "office-n150",
            },
        )
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"RIFF-pilot-test")
        self.assertEqual(download.headers["x-pilot-sha256"], asset["sha256"])

        queued = self.client.post(
            "/v1/rooms/office/audio",
            headers={"Authorization": "Bearer admin-test"},
            json={"asset_id": asset["id"], "volume": 0.7},
        )
        self.assertEqual(queued.status_code, 201)
        payload = queued.json()["command"]["payload"]
        self.assertEqual(payload["action"], "play_audio")
        self.assertEqual(payload["audio_asset_id"], asset["id"])
        self.assertEqual(payload["sha256"], asset["sha256"])
        self.assertEqual(payload["size_bytes"], len(b"RIFF-pilot-test"))
        self.assertEqual(queued.json()["target"]["id"], "office-n150")

    def test_audio_asset_cannot_cross_room_boundary(self) -> None:
        office_token = self.register_device()
        media_registration = self.client.post(
            "/v1/devices/register",
            headers={"Authorization": "Bearer bootstrap-test"},
            json={
                "device_id": "media-n150",
                "room_id": "media-room",
                "name": "Media N150",
                "capabilities": ["audio"],
            },
        )
        media_token = media_registration.json()["device_token"]
        upload = self.client.post(
            "/v1/rooms/office/audio-assets?kind=announcement",
            headers={
                "Authorization": "Bearer admin-test",
                "Content-Type": "audio/flac",
            },
            content=b"fLaC-pilot-test",
        )
        asset_id = upload.json()["id"]

        denied_download = self.client.get(
            f"/v1/audio-assets/{asset_id}",
            headers={
                "Authorization": f"Bearer {media_token}",
                "X-Pilot-Device-ID": "media-n150",
            },
        )
        self.assertEqual(denied_download.status_code, 403)
        denied_queue = self.client.post(
            "/v1/rooms/media-room/audio",
            headers={"Authorization": "Bearer admin-test"},
            json={"asset_id": asset_id},
        )
        self.assertEqual(denied_queue.status_code, 409)

        allowed_download = self.client.get(
            f"/v1/audio-assets/{asset_id}",
            headers={
                "Authorization": f"Bearer {office_token}",
                "X-Pilot-Device-ID": "office-n150",
            },
        )
        self.assertEqual(allowed_download.status_code, 200)

    def test_audio_upload_rejects_unsupported_content(self) -> None:
        response = self.client.post(
            "/v1/rooms/office/audio-assets?kind=assistant",
            headers={
                "Authorization": "Bearer admin-test",
                "Content-Type": "application/octet-stream",
            },
            content=b"not-audio",
        )
        self.assertEqual(response.status_code, 422)

    def test_assistant_asset_cannot_be_marked_critical(self) -> None:
        self.register_device()
        upload = self.client.post(
            "/v1/rooms/office/audio-assets?kind=assistant",
            headers={
                "Authorization": "Bearer admin-test",
                "Content-Type": "audio/wav",
            },
            content=b"RIFF-assistant",
        )
        response = self.client.post(
            "/v1/rooms/office/audio",
            headers={"Authorization": "Bearer admin-test"},
            json={"asset_id": upload.json()["id"], "critical": True},
        )
        self.assertEqual(response.status_code, 422)

    def test_deleted_audio_asset_is_no_longer_listed(self) -> None:
        upload = self.client.post(
            "/v1/rooms/office/audio-assets?kind=assistant",
            headers={
                "Authorization": "Bearer admin-test",
                "Content-Type": "audio/wav",
            },
            content=b"RIFF-delete-test",
        )
        asset_id = upload.json()["id"]
        deleted = self.client.delete(
            f"/v1/audio-assets/{asset_id}",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(deleted.status_code, 204)
        listing = self.client.get(
            "/v1/rooms/office/audio-assets",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(listing.json()["assets"], [])
        self.assertFalse(any(Path(self.audio_directory.name).iterdir()))

    @patch("pilot_core.api.LocalTTS.synthesize", new_callable=AsyncMock)
    def test_room_speak_synthesizes_and_queues_to_resolved_device(
        self, synthesize
    ) -> None:
        self.register_device()
        synthesize.return_value = SynthesizedAudio(
            content=b"RIFF\x04\x00\x00\x00WAVEpilot",
            content_type="audio/wav",
            filename="speech.wav",
            provider="home_assistant",
            voice="default",
            model="tts.piper",
            language="en-AU",
        )
        response = self.client.post(
            "/v1/rooms/office/speak",
            headers={"Authorization": "Bearer admin-test"},
            json={
                "text": "Hello office",
                "language": "en-AU",
                "voice": "default",
                "volume": 0.75,
            },
        )
        self.assertEqual(response.status_code, 201)
        result = response.json()
        self.assertEqual(result["target"]["id"], "office-n150")
        self.assertEqual(result["command"]["payload"]["action"], "play_audio")
        self.assertEqual(result["command"]["payload"]["volume"], 0.75)
        self.assertEqual(result["synthesis"]["provider"], "home_assistant")
        synthesize.assert_awaited_once_with("Hello office", "en-AU", "default")

    def test_room_speak_requires_configured_tts(self) -> None:
        self.register_device()
        response = self.client.post(
            "/v1/rooms/office/speak",
            headers={"Authorization": "Bearer admin-test"},
            json={"text": "This should remain silent"},
        )
        self.assertEqual(response.status_code, 503)

    def test_room_speak_rejects_critical_assistant(self) -> None:
        response = self.client.post(
            "/v1/rooms/office/speak",
            headers={"Authorization": "Bearer admin-test"},
            json={"text": "No", "critical": True},
        )
        self.assertEqual(response.status_code, 422)

    @patch("pilot_core.api.LocalTTS.synthesize", new_callable=AsyncMock)
    @patch(
        "pilot_core.api.Integrations.home_assistant_conversation",
        new_callable=AsyncMock,
    )
    def test_assistant_can_speak_home_assistant_response(
        self, conversation, synthesize
    ) -> None:
        self.register_device()
        conversation.return_value = {
            "response": {
                "speech": {"plain": {"speech": "The office light is now on."}}
            },
            "conversation_id": "conversation-1",
        }
        synthesize.return_value = SynthesizedAudio(
            content=b"RIFF\x04\x00\x00\x00WAVEpilot",
            content_type="audio/wav",
            filename="speech.wav",
            provider="home_assistant",
            voice="default",
            model="tts.piper",
            language="en",
        )
        response = self.client.post(
            "/v1/assistant",
            headers={"Authorization": "Bearer admin-test"},
            json={
                "text": "Turn on the office light",
                "room_id": "office",
                "speak": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["speech_delivery"]["target"]["id"],
            "office-n150",
        )
        conversation_id = response.json()["conversation_id"]
        detail = self.client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [turn["role"] for turn in detail.json()["turns"]],
            ["user", "assistant"],
        )
        listed = self.client.get(
            "/v1/conversations",
            headers={"Authorization": "Bearer admin-test"},
            params={"room_id": "office"},
        )
        self.assertEqual(listed.json()["conversations"][0]["id"], conversation_id)
        status = self.client.get(
            "/v1/assistant/status",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(status.json()["session_owner"], "pilot_core")
        synthesize.assert_awaited_once_with("The office light is now on.", "en", None)

    def test_room_state_combines_registered_device_and_default_targets(self) -> None:
        token = self.register_device()
        self.client.post(
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
        response = self.client.get(
            "/v1/rooms/office/state",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()
        self.assertEqual(state["focus"]["foreground"], "music")
        self.assertEqual(state["targets"]["default_music_player"]["id"], "office-music")
        self.assertEqual(state["devices"][0]["id"], "office-n150")
        whole_home = self.client.get(
            "/v1/state", headers={"Authorization": "Bearer admin-test"}
        )
        self.assertEqual(whole_home.status_code, 200)
        self.assertEqual(
            whole_home.json()["rooms"]["office"]["focus"]["foreground"],
            "music",
        )

    def test_room_control_resolves_device_without_caller_supplying_id(self) -> None:
        self.register_device()
        response = self.client.post(
            "/v1/rooms/office/control",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "cancel"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["target"]["id"], "office-n150")
        self.assertEqual(response.json()["command"]["status"], "queued")

    @patch("pilot_core.api.Integrations.music_assistant", new_callable=AsyncMock)
    def test_room_media_resolves_default_music_player(self, music_assistant) -> None:
        music_assistant.return_value = {"ok": True}
        response = self.client.post(
            "/v1/rooms/office/media",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "play"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["player"]["id"], "office-music")
        music_assistant.assert_awaited_once_with(
            "players/cmd/play", {"player_id": "pilot-office"}
        )

    @patch("pilot_core.api.Integrations.music_assistant", new_callable=AsyncMock)
    def test_room_media_transfer_resolves_both_room_defaults(
        self, music_assistant
    ) -> None:
        music_assistant.return_value = {"ok": True}
        response = self.client.post(
            "/v1/rooms/office/media",
            headers={"Authorization": "Bearer admin-test"},
            json={"action": "transfer", "target_room_id": "media-room"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["player"]["id"], "office-music")
        self.assertEqual(response.json()["target_player"]["id"], "media-music")
        music_assistant.assert_awaited_once_with(
            "player_queues/transfer",
            {
                "source_queue_id": "pilot-office",
                "target_queue_id": "denon-media-room",
                "auto_play": True,
            },
        )

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

    @patch(
        "pilot_core.api.Integrations.home_assistant_media_player_command",
        new_callable=AsyncMock,
    )
    def test_media_room_source_selection_uses_bounded_ha_endpoint(
        self, media_command
    ) -> None:
        media_command.return_value = {"changed_states": []}
        response = self.client.post(
            "/v1/rooms/media-room/media",
            headers={"Authorization": "Bearer admin-test"},
            json={
                "action": "select_source",
                "source": "Media Room - Media Player",
            },
        )
        self.assertEqual(response.status_code, 200)
        media_command.assert_awaited_once_with(
            "media_player.media_room",
            "select_source",
            source="Media Room - Media Player",
        )

    @patch(
        "pilot_core.api.Integrations.denon_avr_command",
        new_callable=AsyncMock,
    )
    def test_media_room_can_use_separate_denon_control_endpoint(
        self, denon_command
    ) -> None:
        denon_command.return_value = {"accepted": True}
        config = settings(self.audio_directory.name)
        config = replace(
            config,
            players=tuple(
                replace(
                    player,
                    control_endpoint="http://10.0.1.150:8080",
                )
                if player.id == "media-music"
                else player
                for player in config.players
            ),
        )
        store = Store(":memory:", config)
        with TestClient(create_app(config, store)) as client:
            response = client.post(
                "/v1/rooms/media-room/media",
                headers={"Authorization": "Bearer admin-test"},
                json={"action": "select_source", "source": "HEOS Music"},
            )
        store.close()
        self.assertEqual(response.status_code, 200)
        denon_command.assert_awaited_once_with(
            "http://10.0.1.150:8080",
            "select_source",
            source="HEOS Music",
        )

    @patch("pilot_core.api.Integrations.music_assistant", new_callable=AsyncMock)
    def test_control_disabled_player_is_read_only(self, music_assistant) -> None:
        config = settings(self.audio_directory.name)
        config = replace(
            config,
            players=tuple(
                replace(player, control_enabled=False)
                if player.id == "media-music"
                else player
                for player in config.players
            ),
        )
        store = Store(":memory:", config)
        with TestClient(create_app(config, store)) as client:
            response = client.post(
                "/v1/rooms/media-room/media",
                headers={"Authorization": "Bearer admin-test"},
                json={"action": "play"},
            )
        store.close()
        self.assertEqual(response.status_code, 409)
        self.assertIn("controls are disabled", response.json()["detail"])
        music_assistant.assert_not_awaited()

    @patch("pilot_core.api.Integrations.music_assistant", new_callable=AsyncMock)
    def test_transfer_to_control_disabled_player_is_rejected(
        self, music_assistant
    ) -> None:
        config = settings(self.audio_directory.name)
        config = replace(
            config,
            players=tuple(
                replace(player, control_enabled=False)
                if player.id == "media-music"
                else player
                for player in config.players
            ),
        )
        store = Store(":memory:", config)
        with TestClient(create_app(config, store)) as client:
            response = client.post(
                "/v1/rooms/office/media",
                headers={"Authorization": "Bearer admin-test"},
                json={
                    "action": "transfer",
                    "target_room_id": "media-room",
                },
            )
        store.close()
        self.assertEqual(response.status_code, 409)
        self.assertIn("controls are disabled", response.json()["detail"])
        music_assistant.assert_not_awaited()

    @patch(
        "pilot_core.api.MediaStateReader.snapshot",
        new_callable=AsyncMock,
    )
    def test_read_only_media_state_routes(self, snapshot) -> None:
        player_state = {
            "player": {"id": "media-music", "room_id": "media-room"},
            "status": "ok",
            "effective": {
                "available": True,
                "powered": True,
                "playback_state": "idle",
                "volume_percent": 35,
            },
        }
        snapshot.return_value = {
            "observed_at": "2026-07-17T00:00:00+00:00",
            "room_id": "media-room",
            "providers": {},
            "players": {"media-music": player_state},
        }
        room_response = self.client.get(
            "/v1/rooms/media-room/media-state",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(room_response.status_code, 200)
        self.assertEqual(room_response.headers["cache-control"], "no-store")
        self.assertEqual(room_response.json()["players"]["media-music"]["status"], "ok")

        player_response = self.client.get(
            "/v1/players/media-music/state",
            headers={"Authorization": "Bearer admin-test"},
        )
        self.assertEqual(player_response.status_code, 200)
        self.assertEqual(player_response.headers["cache-control"], "no-store")
        self.assertEqual(player_response.json()["effective"]["volume_percent"], 35)
        self.assertEqual(self.client.get("/v1/media/state").status_code, 401)


if __name__ == "__main__":
    unittest.main()
