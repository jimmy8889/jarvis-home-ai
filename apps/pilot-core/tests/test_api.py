from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pilot_core.api import create_app
from pilot_core.config import IntegrationSettings, Player, Room, ServerSettings, Settings
from pilot_core.storage import Store
from pilot_core.tts import SynthesizedAudio


def settings(audio_asset_path: str = "/tmp/pilot-core-test-audio") -> Settings:
    return Settings(
        server=ServerSettings(
            database_path=":memory:", audio_asset_path=audio_asset_path
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
        self.assertIn(
            "office", {room["id"] for room in response.json()["rooms"]}
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
            headers={
                "Authorization": f"Bearer {grant['bootstrap_token']}"
            },
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.headers["cache-control"], "no-store")
        self.assertEqual(registered.json()["device_id"], "grant-office")
        replay = self.client.post(
            "/v1/devices/bootstrap",
            headers={
                "Authorization": f"Bearer {grant['bootstrap_token']}"
            },
        )
        self.assertEqual(replay.status_code, 401)

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
        synthesize.assert_awaited_once_with(
            "Hello office", "en-AU", "default"
        )

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
                "speech": {
                    "plain": {"speech": "The office light is now on."}
                }
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
        synthesize.assert_awaited_once_with(
            "The office light is now on.", "en", None
        )

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
        self.assertEqual(
            state["targets"]["default_music_player"]["id"], "office-music"
        )
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
        self.assertEqual(
            response.json()["target_player"]["id"], "media-music"
        )
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


if __name__ == "__main__":
    unittest.main()
