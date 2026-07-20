from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import IntegrationSettings
from .conversation import AssistantUnavailable, LLMRequestFailed, OpenAICompatibleLLM
from .secret_values import read_secret
from .storage import Store


ALLOWED_RECORDING_TYPES = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/m4a": ".m4a",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
}


class MeetingRecordingError(ValueError):
    pass


class MeetingProcessingError(RuntimeError):
    pass


class MeetingRecordings:
    def __init__(self, store: Store, path: str, max_bytes: int) -> None:
        self.store = store
        self.root = Path(path)
        self.max_bytes = max_bytes

    async def save(
        self,
        meeting_id: str,
        filename: str,
        content_type: str,
        chunks: AsyncIterator[bytes],
    ) -> dict[str, Any]:
        if self.store.get_meeting(meeting_id) is None:
            raise KeyError(meeting_id)
        normalized_type = content_type.partition(";")[0].strip().lower()
        extension = ALLOWED_RECORDING_TYPES.get(normalized_type)
        if extension is None:
            raise MeetingRecordingError("unsupported meeting recording type")
        safe_name = Path(filename).name.strip() or f"recording{extension}"
        if not safe_name.lower().endswith(extension):
            safe_name += extension

        meeting_directory = self.root / meeting_id
        meeting_directory.mkdir(parents=True, exist_ok=True)
        destination = meeting_directory / f"recording{extension}"
        temporary = meeting_directory / f".upload-{secrets.token_hex(8)}"
        digest = sha256()
        size = 0
        try:
            with temporary.open("xb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise MeetingRecordingError(
                            "meeting recording exceeds configured size limit"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise MeetingRecordingError("meeting recording is empty")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

        return self.store.set_meeting_recording(
            meeting_id,
            safe_name,
            normalized_type,
            digest.hexdigest(),
            size,
            str(destination),
        )


class MeetingProcessor:
    """Local-first transcription and evidence-linked meeting analysis."""

    def __init__(
        self,
        store: Store,
        settings: IntegrationSettings,
        *,
        llm: OpenAICompatibleLLM | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.llm = llm or OpenAICompatibleLLM(settings, transport=transport)
        self.transport = transport

    def status(self) -> dict[str, Any]:
        return {
            "stt_configured": bool(
                self.settings.meeting_stt_url and self.settings.meeting_stt_model
            ),
            "stt_model": self.settings.meeting_stt_model or None,
            "analysis_configured": bool(self.llm.status()["configured"]),
            "analysis_model": self.llm.status()["model"],
        }

    async def process(self, meeting_id: str) -> dict[str, Any]:
        meeting = self.store.get_meeting(meeting_id)
        if meeting is None:
            raise KeyError(meeting_id)
        recording = self.store.get_meeting_recording(meeting_id)
        if recording is None:
            raise MeetingProcessingError("meeting recording is missing")
        try:
            segments = await self.transcribe(recording, meeting["language"])
            transcribed = self.store.replace_transcript(meeting_id, segments)
            analysis = await self.analyze(transcribed)
            return self.store.replace_meeting_analysis(
                meeting_id,
                analysis["summary"],
                analysis["decisions"],
                analysis["action_items"],
            )
        except (MeetingProcessingError, AssistantUnavailable, LLMRequestFailed) as error:
            self.store.fail_meeting(meeting_id, str(error))
            raise MeetingProcessingError(str(error)) from None

    async def transcribe(
        self,
        recording: dict[str, Any],
        language: str,
    ) -> list[dict[str, Any]]:
        endpoint = self._local_endpoint(
            self.settings.meeting_stt_url,
            "/audio/transcriptions",
        )
        if not self.settings.meeting_stt_model:
            raise MeetingProcessingError("meeting STT model is not configured")
        headers: dict[str, str] = {}
        token = read_secret(self.settings.meeting_stt_token_env)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with Path(recording["path"]).open("rb") as audio:
                async with httpx.AsyncClient(
                    timeout=self.settings.meeting_stt_timeout_seconds,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        endpoint,
                        headers=headers,
                        data={
                            "model": self.settings.meeting_stt_model,
                            "language": language.split("-", 1)[0],
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "segment",
                        },
                        files={
                            "file": (
                                recording["filename"],
                                audio,
                                recording["content_type"],
                            )
                        },
                    )
                    response.raise_for_status()
                    if len(response.content) > 10_000_000:
                        raise MeetingProcessingError("STT response is too large")
                    body = response.json()
        except MeetingProcessingError:
            raise
        except (OSError, httpx.HTTPError, ValueError) as error:
            raise MeetingProcessingError(f"local transcription failed: {error}") from error
        raw_segments = body.get("segments") if isinstance(body, dict) else None
        if not isinstance(raw_segments, list) or not raw_segments:
            raise MeetingProcessingError("local STT returned no timestamped segments")
        output: list[dict[str, Any]] = []
        characters = 0
        for raw in raw_segments[:20_000]:
            if not isinstance(raw, dict):
                continue
            text = " ".join(str(raw.get("text", "")).split())[:20_000]
            if not text:
                continue
            try:
                start_ms = max(0, round(float(raw.get("start", 0)) * 1000))
                end_ms = round(float(raw.get("end", 0)) * 1000)
            except (TypeError, ValueError):
                continue
            if end_ms <= start_ms:
                continue
            characters += len(text)
            if characters > self.settings.meeting_transcript_max_characters:
                raise MeetingProcessingError("transcript exceeds configured character limit")
            speaker = str(
                raw.get("speaker")
                or raw.get("speaker_label")
                or "Speaker 1"
            ).strip()[:100]
            average_log_probability = raw.get("avg_logprob")
            confidence = None
            if isinstance(average_log_probability, (int, float)) and math.isfinite(
                average_log_probability
            ):
                confidence = round(min(max(math.exp(average_log_probability), 0), 1), 4)
            output.append(
                {
                    "speaker_label": speaker,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": text,
                    "confidence": confidence,
                }
            )
        if not output:
            raise MeetingProcessingError("local STT returned no valid segments")
        return output

    async def analyze(self, meeting: dict[str, Any]) -> dict[str, Any]:
        valid_ids = {segment["id"] for segment in meeting["transcript"]}
        transcript_lines: list[str] = []
        size = 0
        for segment in meeting["transcript"]:
            line = (
                f"[{segment['id']} {self._timestamp(segment['start_ms'])} "
                f"{segment.get('speaker_label') or 'Speaker'}] {segment['text']}"
            )
            size += len(line)
            if size > self.settings.meeting_transcript_max_characters:
                raise MeetingProcessingError("analysis transcript exceeds configured limit")
            transcript_lines.append(line)
        prompt = "\n".join(transcript_lines)
        message = await self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Analyze the meeting transcript. Return only a JSON object with "
                        "summary (string), decisions (array of {summary, segment_ids}), "
                        "and action_items (array of {task, owner, due_at, confidence, "
                        "segment_ids}). Every conclusion must cite existing segment IDs. "
                        "Do not invent owners, dates, decisions, or actions. Use null when "
                        "an owner or ISO-8601 due_at is not explicit."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Meeting title: {meeting['title']}\n"
                        f"Started: {meeting['started_at']}\n\n{prompt}"
                    ),
                },
            ],
            [],
            tool_choice="none",
        )
        content = message.get("content")
        if not isinstance(content, str):
            raise MeetingProcessingError("local analysis returned no JSON content")
        try:
            body = json.loads(self._json_text(content))
        except (json.JSONDecodeError, TypeError) as error:
            raise MeetingProcessingError("local analysis returned invalid JSON") from error
        if not isinstance(body, dict):
            raise MeetingProcessingError("local analysis must return an object")
        summary = " ".join(str(body.get("summary", "")).split())[:20_000]
        if not summary:
            raise MeetingProcessingError("local analysis returned an empty summary")
        decisions = self._evidence_items(
            body.get("decisions"),
            valid_ids,
            text_key="summary",
            limit=1_000,
        )
        actions = self._evidence_items(
            body.get("action_items"),
            valid_ids,
            text_key="task",
            limit=2_000,
            actions=True,
        )
        return {"summary": summary, "decisions": decisions, "action_items": actions}

    @staticmethod
    def _local_endpoint(base: str, suffix: str) -> str:
        parsed = urlsplit(base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MeetingProcessingError("meeting STT URL is not configured")
        host = parsed.hostname
        local = (
            host in {"localhost", "::1"}
            or "." not in host
            or host.endswith((".local", ".internal"))
        )
        try:
            local = local or ipaddress.ip_address(host).is_private
        except ValueError:
            pass
        if not local:
            raise MeetingProcessingError("meeting STT URL must use local infrastructure")
        endpoint = base
        if not endpoint.endswith(suffix):
            endpoint = f"{endpoint}{suffix}"
        return endpoint

    @staticmethod
    def _timestamp(milliseconds: int) -> str:
        seconds = milliseconds // 1000
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _json_text(content: str) -> str:
        value = content.strip()
        if value.startswith("```"):
            lines = value.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            value = "\n".join(lines)
        return value

    @staticmethod
    def _evidence_items(
        value: Any,
        valid_ids: set[str],
        *,
        text_key: str,
        limit: int,
        actions: bool = False,
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        output: list[dict[str, Any]] = []
        for raw in value[:limit]:
            if not isinstance(raw, dict):
                continue
            text = " ".join(str(raw.get(text_key, "")).split())[:4_000]
            if not text:
                continue
            evidence = raw.get("segment_ids")
            segment_ids = [
                item
                for item in evidence[:500]
                if isinstance(evidence, list) and isinstance(item, str) and item in valid_ids
            ] if isinstance(evidence, list) else []
            if not segment_ids:
                continue
            item: dict[str, Any] = {text_key: text, "segment_ids": segment_ids}
            if actions:
                owner = raw.get("owner")
                due_at = raw.get("due_at")
                confidence = raw.get("confidence")
                item.update(
                    {
                        "owner": (
                            " ".join(str(owner).split())[:300]
                            if owner is not None
                            else None
                        ),
                        "due_at": str(due_at)[:64] if due_at else None,
                        "confidence": (
                            min(max(float(confidence), 0), 1)
                            if isinstance(confidence, (int, float))
                            and not isinstance(confidence, bool)
                            and math.isfinite(float(confidence))
                            else None
                        ),
                    }
                )
                item["due_at"] = MeetingProcessor._due_at(item["due_at"])
            output.append(item)
        return output

    @staticmethod
    def _due_at(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
