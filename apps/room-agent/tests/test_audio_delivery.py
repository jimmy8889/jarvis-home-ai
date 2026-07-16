from __future__ import annotations

from email.message import Message
from hashlib import sha256
from pathlib import Path
from threading import Event
import tempfile
import time
import unittest

from pilot_room_agent.audio_delivery import AudioFetcher, AudioPlayback
from pilot_room_agent.config import Settings
from pilot_room_agent.controls import ControlError, ControlState


class FakeResponse:
    def __init__(self, content: bytes, content_type: str = "audio/wav") -> None:
        self.content = content
        self.offset = 0
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def read(self, size: int) -> bytes:
        chunk = self.content[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class FakeProcess:
    def __init__(self) -> None:
        self.finished = Event()
        self.terminated = False

    def poll(self) -> int | None:
        return 0 if self.finished.is_set() else None

    def terminate(self) -> None:
        self.terminated = True
        self.finished.set()

    def wait(self) -> int:
        self.finished.wait(2)
        return 0

    def finish(self) -> None:
        self.finished.set()


class AudioFetcherTests(unittest.TestCase):
    def test_fetch_authenticates_and_verifies_download(self) -> None:
        content = b"RIFF-secure-pilot-audio"
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("device-secret\n", encoding="utf-8")
            captured: dict[str, object] = {}

            def opener(request, **kwargs):
                captured["request"] = request
                captured.update(kwargs)
                return FakeResponse(content)

            settings = Settings(
                core_url="https://pilot.example/base",
                core_device_id="pilot-office",
                core_device_token_file=str(token_path),
                audio_cache_path=str(Path(directory) / "audio"),
            )
            fetcher = AudioFetcher(settings, opener=opener)
            asset_id = "a" * 32
            path = fetcher.fetch(
                {
                    "audio_asset_id": asset_id,
                    "sha256": sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "content_type": "audio/wav",
                }
            )
            request = captured["request"]
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(
                request.full_url,
                f"https://pilot.example/base/v1/audio-assets/{asset_id}",
            )
            self.assertEqual(
                request.get_header("Authorization"), "Bearer device-secret"
            )
            self.assertEqual(
                request.get_header("X-pilot-device-id"), "pilot-office"
            )
            self.assertEqual(captured["timeout"], 15)

    def test_fetch_rejects_digest_mismatch_without_caching_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token"
            token_path.write_text("device-secret", encoding="utf-8")
            settings = Settings(
                core_url="http://pilot-core:8770",
                core_device_id="pilot-office",
                core_device_token_file=str(token_path),
                audio_cache_path=str(Path(directory) / "audio"),
            )
            fetcher = AudioFetcher(
                settings, opener=lambda *args, **kwargs: FakeResponse(b"wrong")
            )
            with self.assertRaisesRegex(ControlError, "digest"):
                fetcher.fetch(
                    {
                        "audio_asset_id": "b" * 32,
                        "sha256": "0" * 64,
                        "size_bytes": 5,
                        "content_type": "audio/wav",
                    }
                )
            self.assertEqual(list((Path(directory) / "audio").iterdir()), [])


class AudioPlaybackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.audio_path = Path(self.directory.name) / "reply.wav"
        self.audio_path.write_bytes(b"RIFF")
        self.processes: list[FakeProcess] = []
        self.commands: list[list[str]] = []

        class Fetcher:
            def __init__(inner_self, path: Path) -> None:
                inner_self.path = path

            def fetch(inner_self, payload):
                return inner_self.path

        def popen(command, **kwargs):
            self.commands.append(command)
            process = FakeProcess()
            self.processes.append(process)
            return process

        self.state = ControlState()
        self.playback = AudioPlayback(
            self.state, Fetcher(self.audio_path), popen=popen
        )

    def tearDown(self) -> None:
        self.playback.close()
        self.directory.cleanup()

    def payload(self, kind: str = "assistant") -> dict[str, object]:
        return {
            "audio_asset_id": "c" * 32,
            "sha256": "0" * 64,
            "size_bytes": 4,
            "content_type": "audio/wav",
            "kind": kind,
            "volume": 0.6,
            "critical": kind == "announcement",
        }

    def test_playback_sets_and_clears_assistant_state(self) -> None:
        result = self.playback.play(self.payload())
        self.assertTrue(result["started"])
        self.assertTrue(self.state.snapshot()["assistant_speaking"])
        self.assertEqual(self.commands[0][:3], ["pw-play", "--volume", "0.6000"])
        self.processes[0].finish()
        for _ in range(50):
            if not self.state.snapshot()["assistant_speaking"]:
                break
            time.sleep(0.01)
        self.assertFalse(self.state.snapshot()["assistant_speaking"])
        self.assertFalse(self.playback.status()["active"])

    def test_cancel_terminates_audio_and_clears_announcement_state(self) -> None:
        self.playback.play(self.payload("announcement"))
        self.assertTrue(self.state.snapshot()["critical_announcement"])
        result = self.playback.cancel()
        self.assertTrue(result["audio_playback_stopped"])
        self.assertTrue(self.processes[0].terminated)
        self.assertFalse(self.state.snapshot()["announcement_active"])

    def test_critical_assistant_audio_is_rejected(self) -> None:
        payload = self.payload()
        payload["critical"] = True
        with self.assertRaisesRegex(ControlError, "only announcements"):
            self.playback.play(payload)
