from __future__ import annotations

import json
import os
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.tts import LocalTTS, TTSRequestFailed


WAV = b"RIFF\x04\x00\x00\x00WAVEpilot"


class HomeAssistantTTSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-secret"

    async def asyncTearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    async def test_synthesizes_with_piper_and_fetches_only_proxy_path(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/tts_get_url":
                payload = json.loads(request.content)
                self.assertEqual(payload["engine_id"], "tts.piper")
                self.assertEqual(payload["message"], "Hello office")
                self.assertEqual(payload["language"], "en-AU")
                self.assertFalse(payload["cache"])
                self.assertEqual(payload["options"]["preferred_format"], "wav")
                return httpx.Response(
                    200,
                    json={"path": "/api/tts_proxy/generated.wav"},
                )
            if request.url.path == "/api/tts_proxy/generated.wav":
                return httpx.Response(
                    200, content=WAV, headers={"Content-Type": "audio/wav"}
                )
            return httpx.Response(404)

        settings = IntegrationSettings(
            home_assistant_url="http://homeassistant.local:8123",
            tts_provider="home_assistant",
            tts_engine_id="tts.piper",
            tts_voice="default",
            tts_format="wav",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        result = await tts.synthesize("Hello office", "en-AU")

        self.assertEqual(result.content, WAV)
        self.assertEqual(result.content_type, "audio/wav")
        self.assertEqual(result.provider, "home_assistant")
        self.assertEqual(result.model, "tts.piper")
        self.assertEqual(len(requests), 2)
        self.assertTrue(
            all(
                request.headers["authorization"] == "Bearer ha-secret"
                for request in requests
            )
        )

    async def test_rejects_provider_controlled_absolute_download_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "path": "http://attacker.invalid/api/tts_proxy/speech.wav"
                },
            )

        settings = IntegrationSettings(
            home_assistant_url="http://homeassistant.local:8123",
            tts_provider="home_assistant",
            tts_engine_id="tts.piper",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        with self.assertRaisesRegex(TTSRequestFailed, "unsafe"):
            await tts.synthesize("Do not fetch arbitrary URLs")

    async def test_rejects_encoded_proxy_path_traversal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"path": "/api/tts_proxy/%2e%2e/states"},
            )

        settings = IntegrationSettings(
            home_assistant_url="http://homeassistant.local:8123",
            tts_provider="home_assistant",
            tts_engine_id="tts.piper",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        with self.assertRaisesRegex(TTSRequestFailed, "unsafe"):
            await tts.synthesize("Do not traverse paths")


class OpenAITTSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["PILOT_TTS_TOKEN"] = "tts-secret"

    async def asyncTearDown(self) -> None:
        os.environ.pop("PILOT_TTS_TOKEN", None)

    async def test_synthesizes_with_openai_compatible_local_server(self) -> None:
        observed: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            observed["url"] = str(request.url)
            observed["payload"] = json.loads(request.content)
            observed["authorization"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                content=WAV,
                headers={"Content-Type": "application/octet-stream"},
            )

        settings = IntegrationSettings(
            tts_provider="openai",
            tts_url="http://tts.local:8000/v1/audio/speech",
            tts_model="kokoro",
            tts_voice="af_heart",
            tts_format="wav",
            tts_language="en",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        result = await tts.synthesize("Local speech", voice="af_sky")

        self.assertEqual(
            observed["url"], "http://tts.local:8000/v1/audio/speech"
        )
        self.assertEqual(
            observed["payload"],
            {
                "model": "kokoro",
                "voice": "af_sky",
                "input": "Local speech",
                "response_format": "wav",
            },
        )
        self.assertEqual(observed["authorization"], "Bearer tts-secret")
        self.assertEqual(result.content_type, "audio/wav")
        self.assertEqual(result.voice, "af_sky")

    async def test_rejects_oversized_or_invalid_audio(self) -> None:
        settings = IntegrationSettings(
            tts_provider="openai",
            tts_url="http://tts.local:8000/v1/audio/speech",
            tts_format="wav",
        )
        oversized = LocalTTS(
            settings,
            4,
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200, content=WAV, headers={"Content-Type": "audio/wav"}
                )
            ),
        )
        with self.assertRaisesRegex(TTSRequestFailed, "size limit"):
            await oversized.synthesize("Too large")

        invalid = LocalTTS(
            settings,
            1_000_000,
            httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=b"not a wave file",
                    headers={"Content-Type": "audio/wav"},
                )
            ),
        )
        with self.assertRaisesRegex(TTSRequestFailed, "invalid wav"):
            await invalid.synthesize("Invalid")


if __name__ == "__main__":
    unittest.main()
