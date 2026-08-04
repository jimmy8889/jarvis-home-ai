from __future__ import annotations

import json
import os
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.tts import LocalTTS, TTSRequestFailed, TTSUnavailable


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
                self.assertEqual(payload["options"]["preferred_sample_rate"], 16000)
                self.assertEqual(payload["options"]["preferred_sample_channels"], 1)
                self.assertEqual(payload["options"]["preferred_sample_bytes"], 2)
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
                json={"path": "http://attacker.invalid/api/tts_proxy/speech.wav"},
            )

        settings = IntegrationSettings(
            home_assistant_url="http://homeassistant.local:8123",
            tts_provider="home_assistant",
            tts_engine_id="tts.piper",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        with self.assertRaisesRegex(TTSRequestFailed, "unsafe"):
            await tts.synthesize("Do not fetch arbitrary URLs")

    async def test_retries_with_configured_piper_locale(self) -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tts_get_url":
                payload = json.loads(request.content)
                requests.append(payload)
                if payload["language"] == "en-AU":
                    return httpx.Response(500, text="unsupported locale")
                return httpx.Response(
                    200,
                    json={"path": "/api/tts_proxy/fallback.wav"},
                )
            if request.url.path == "/api/tts_proxy/fallback.wav":
                return httpx.Response(
                    200, content=WAV, headers={"Content-Type": "audio/wav"}
                )
            return httpx.Response(404)

        settings = IntegrationSettings(
            home_assistant_url="http://homeassistant.local:8123",
            tts_provider="home_assistant",
            tts_engine_id="tts.piper",
            tts_language="en_US",
            tts_format="wav",
        )
        tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
        result = await tts.synthesize("Fallback locale", "en-AU")

        self.assertEqual([item["language"] for item in requests], ["en-AU", "en_US"])
        self.assertEqual(result.language, "en-AU")
        self.assertEqual(result.content_type, "audio/wav")

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

        self.assertEqual(observed["url"], "http://tts.local:8000/v1/audio/speech")
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

    async def test_qwen_voice_picker_exposes_and_validates_3080_voices(self) -> None:
        settings = IntegrationSettings(
            tts_provider="openai",
            tts_url="http://tts.local:8030/v1/audio/speech",
            tts_model="tts",
            tts_voice="serena",
        )
        tts = LocalTTS(settings, 1_000_000)
        self.assertIn("serena", tts.available_voices())
        self.assertIn("vivian", tts.status()["available_voices"])
        with self.assertRaisesRegex(TTSUnavailable, "voice is not available"):
            await tts.synthesize("Invalid voice", voice="not-a-qwen-voice")

    async def test_kokoro_voice_routes_to_the_optional_sidecar(self) -> None:
        observed: dict[str, object] = {}
        os.environ["PILOT_KOKORO_TOKEN"] = "kokoro-secret"

        def handler(request: httpx.Request) -> httpx.Response:
            observed["url"] = str(request.url)
            observed["payload"] = json.loads(request.content)
            observed["authorization"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                content=WAV,
                headers={"Content-Type": "audio/wav"},
            )

        try:
            settings = IntegrationSettings(
                tts_provider="openai",
                tts_url="http://tts.local:8030/v1/audio/speech",
                tts_model="tts",
                tts_voice="serena",
                tts_kokoro_url="http://tts.local:8032/v1/audio/speech",
                tts_kokoro_token_env="PILOT_KOKORO_TOKEN",
                tts_format="wav",
            )
            tts = LocalTTS(settings, 1_000_000, httpx.MockTransport(handler))
            result = await tts.synthesize("G'day from Pilot", voice="bm_george")
        finally:
            os.environ.pop("PILOT_KOKORO_TOKEN", None)

        self.assertEqual(observed["url"], "http://tts.local:8032/v1/audio/speech")
        self.assertEqual(
            observed["payload"],
            {
                "model": "Kokoro-82M",
                "voice": "bm_george",
                "input": "G'day from Pilot",
                "response_format": "wav",
            },
        )
        self.assertEqual(observed["authorization"], "Bearer kokoro-secret")
        self.assertEqual(result.provider, "kokoro")
        self.assertEqual(result.model, "Kokoro-82M")
        self.assertIn("bm_george", tts.available_voices())
        self.assertEqual(tts.voice_groups()[1]["provider"], "kokoro")

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
