from __future__ import annotations

import json
import os
import unittest

from pilot_core.config import IntegrationSettings
from pilot_core.voice import HomeAssistantVoicePipeline


class FakeSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = [json.dumps(message) for message in messages]
        self.sent: list[str | bytes] = []

    async def recv(self):
        return self.messages.pop(0)

    async def send(self, value):
        self.sent.append(value)


class FakeConnection:
    def __init__(self, socket: FakeSocket) -> None:
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_):
        return False


class VoicePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["HOME_ASSISTANT_TOKEN"] = "ha-token"

    async def asyncTearDown(self) -> None:
        os.environ.pop("HOME_ASSISTANT_TOKEN", None)

    async def test_streams_prefixed_pcm_and_collects_assist_result(self) -> None:
        socket = FakeSocket(
            [
                {"type": "auth_required"},
                {"type": "auth_ok"},
                {"id": 1, "type": "result", "success": True},
                {
                    "type": "event",
                    "event": {
                        "type": "run-start",
                        "data": {"runner_data": {"stt_binary_handler_id": 7}},
                    },
                },
                {"type": "event", "event": {"type": "stt-start", "data": {}}},
                {
                    "type": "event",
                    "event": {
                        "type": "stt-end",
                        "data": {"stt_output": {"text": "turn off the light"}},
                    },
                },
                {
                    "type": "event",
                    "event": {
                        "type": "intent-end",
                        "data": {
                            "intent_output": {
                                "conversation_id": "conversation-1",
                                "response": {
                                    "speech": {
                                        "plain": {"speech": "The light is off."}
                                    }
                                },
                            }
                        },
                    },
                },
                {"type": "event", "event": {"type": "run-end", "data": {}}},
            ]
        )

        def connector(*_, **__):
            return FakeConnection(socket)

        async def audio():
            yield b"\x01\x02"
            yield b"\x03\x04"

        pipeline = HomeAssistantVoicePipeline(
            IntegrationSettings(home_assistant_url="http://ha.local:8123"),
            connector=connector,
        )
        result = await pipeline.run(audio(), sample_rate=16000)
        self.assertEqual(result.transcript, "turn off the light")
        self.assertEqual(result.response_text, "The light is off.")
        self.assertEqual(result.conversation_id, "conversation-1")
        binary_messages = [
            message for message in socket.sent if isinstance(message, bytes)
        ]
        self.assertEqual(binary_messages, [b"\x07\x01\x02", b"\x07\x03\x04", b"\x07"])


if __name__ == "__main__":
    unittest.main()
