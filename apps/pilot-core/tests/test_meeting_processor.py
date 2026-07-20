from __future__ import annotations

from datetime import UTC, datetime
import json
import re
from pathlib import Path
import tempfile
import unittest

import httpx

from pilot_core.config import IntegrationSettings, ServerSettings, Settings
from pilot_core.meetings import MeetingProcessingError, MeetingProcessor
from pilot_core.storage import Store


class EvidenceLLM:
    def status(self) -> dict:
        return {"configured": True, "model": "local-analysis"}

    async def chat(self, messages, tools, *, tool_choice="auto") -> dict:
        transcript = messages[-1]["content"]
        segment_ids = re.findall(r"\[([a-f0-9]{32}) ", transcript)
        return {
            "content": json.dumps(
                {
                    "summary": "The team agreed on the release plan.",
                    "decisions": [
                        {
                            "summary": "Ship the release.",
                            "segment_ids": [segment_ids[0]],
                        },
                        {
                            "summary": "Unsupported conclusion.",
                            "segment_ids": ["not-a-segment"],
                        },
                    ],
                    "action_items": [
                        {
                            "task": "Prepare release notes.",
                            "owner": "James",
                            "due_at": "2026-07-24T09:00:00+10:00",
                            "confidence": 0.92,
                            "segment_ids": [segment_ids[-1]],
                        }
                    ],
                }
            )
        }


class MeetingProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.store = Store(
            ":memory:",
            Settings(
                server=ServerSettings(database_path=":memory:"),
                integrations=IntegrationSettings(),
                rooms=(),
                players=(),
            ),
        )
        self.meeting = self.store.create_meeting(
            "Release planning",
            "en-AU",
            datetime.now(UTC).isoformat(),
            None,
        )
        recording = Path(self.root.name) / "meeting.wav"
        recording.write_bytes(b"RIFFtest")
        self.store.set_meeting_recording(
            self.meeting["id"],
            "meeting.wav",
            "audio/wav",
            "0" * 64,
            recording.stat().st_size,
            str(recording),
        )

    async def asyncTearDown(self) -> None:
        self.store.close()
        self.root.cleanup()

    async def test_local_stt_and_llm_produce_timestamped_evidence_linked_output(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/audio/transcriptions")
            self.assertIn("multipart/form-data", request.headers["content-type"])
            return httpx.Response(
                200,
                json={
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 2.5,
                            "text": "We will ship the release.",
                            "speaker": "James",
                            "avg_logprob": -0.1,
                        },
                        {
                            "start": 2.5,
                            "end": 5.0,
                            "text": "I will prepare the release notes.",
                            "avg_logprob": -0.2,
                        },
                    ]
                },
            )

        processor = MeetingProcessor(
            self.store,
            IntegrationSettings(
                meeting_stt_url="http://whisper.internal:8000/v1",
                meeting_stt_model="whisper-large-v3",
                llm_provider="openai",
                llm_url="http://ollama.internal:11434/v1",
                llm_model="local-analysis",
            ),
            llm=EvidenceLLM(),
            transport=httpx.MockTransport(handler),
        )
        result = await processor.process(self.meeting["id"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["transcript"]), 2)
        self.assertEqual(result["transcript"][0]["speaker_label"], "James")
        self.assertEqual(result["transcript"][1]["speaker_label"], "Speaker 1")
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(len(result["action_items"]), 1)
        self.assertEqual(
            result["action_items"][0]["due_at"],
            "2026-07-23T23:00:00+00:00",
        )
        valid_ids = {segment["id"] for segment in result["transcript"]}
        self.assertTrue(set(result["decisions"][0]["segment_ids"]) <= valid_ids)
        self.assertTrue(set(result["action_items"][0]["segment_ids"]) <= valid_ids)

    async def test_public_stt_url_fails_closed_and_marks_meeting_failed(self) -> None:
        processor = MeetingProcessor(
            self.store,
            IntegrationSettings(
                meeting_stt_url="https://api.example.com/v1",
                llm_provider="openai",
                llm_url="http://ollama.internal:11434/v1",
                llm_model="local-analysis",
            ),
            llm=EvidenceLLM(),
        )
        with self.assertRaisesRegex(MeetingProcessingError, "local infrastructure"):
            await processor.process(self.meeting["id"])
        self.assertEqual(self.store.get_meeting(self.meeting["id"])["status"], "failed")

    async def test_empty_or_untimestamped_stt_is_rejected(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"text": "No segments"})

        processor = MeetingProcessor(
            self.store,
            IntegrationSettings(
                meeting_stt_url="http://whisper.internal:8000/v1",
                meeting_stt_model="whisper-1",
            ),
            llm=EvidenceLLM(),
            transport=httpx.MockTransport(handler),
        )
        recording = self.store.get_meeting_recording(self.meeting["id"])
        assert recording is not None
        with self.assertRaisesRegex(MeetingProcessingError, "timestamped segments"):
            await processor.transcribe(recording, "en")


if __name__ == "__main__":
    unittest.main()
