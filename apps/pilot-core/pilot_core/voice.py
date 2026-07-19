from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect

from .config import IntegrationSettings
from .secret_values import read_secret


class VoicePipelineUnavailable(RuntimeError):
    """Home Assistant's local Assist pipeline has not been configured."""


class VoicePipelineFailed(RuntimeError):
    """Home Assistant rejected or failed a streamed Assist pipeline run."""


@dataclass(frozen=True)
class VoicePipelineResult:
    transcript: str
    response_text: str
    conversation_id: str | None
    raw_response: dict[str, Any]


def _websocket_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise VoicePipelineUnavailable("Home Assistant URL is invalid")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, "/api/websocket", "", ""))


def _speech_text(intent_output: dict[str, Any]) -> str:
    try:
        value = intent_output["response"]["speech"]["plain"]["speech"]
    except (KeyError, TypeError):
        return ""
    return value.strip() if isinstance(value, str) else ""


class HomeAssistantVoicePipeline:
    """Streams raw PCM to Home Assistant's documented Assist WebSocket API."""

    def __init__(
        self,
        settings: IntegrationSettings,
        connector: Callable[..., Any] = connect,
    ) -> None:
        self.settings = settings
        self.connector = connector

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(
                self.settings.home_assistant_url
                and read_secret(self.settings.home_assistant_token_env)
            ),
            "provider": "home_assistant",
            "pipeline_id": self.settings.home_assistant_assist_pipeline_id or None,
            "language": self.settings.home_assistant_assist_language,
        }

    async def run(
        self,
        audio: AsyncIterable[bytes],
        *,
        sample_rate: int,
        language: str | None = None,
        home_assistant_device_id: str | None = None,
        conversation_id: str | None = None,
    ) -> VoicePipelineResult:
        token = read_secret(self.settings.home_assistant_token_env)
        if not self.settings.home_assistant_url or not token:
            raise VoicePipelineUnavailable(
                "Home Assistant URL and token are required for voice"
            )
        if sample_rate not in {8000, 16000, 24000, 32000, 48000}:
            raise VoicePipelineFailed("unsupported input sample rate")

        command: dict[str, Any] = {
            "id": 1,
            "type": "assist_pipeline/run",
            "start_stage": "stt",
            "end_stage": "intent",
            "input": {"sample_rate": sample_rate},
            "timeout": self.settings.home_assistant_assist_timeout_seconds,
        }
        # Home Assistant selects language from the configured Assist pipeline.
        # `language` is retained in this API for the TTS stage and future
        # pipeline routing, but it is not an `assist_pipeline/run` input field.
        _ = language
        if self.settings.home_assistant_assist_pipeline_id:
            command["pipeline"] = self.settings.home_assistant_assist_pipeline_id
        if home_assistant_device_id:
            command["device_id"] = home_assistant_device_id
        if conversation_id:
            command["conversation_id"] = conversation_id

        websocket_url = _websocket_url(self.settings.home_assistant_url)
        try:
            async with self.connector(
                websocket_url,
                open_timeout=10,
                close_timeout=5,
                max_size=2_000_000,
            ) as socket:
                await self._authenticate(socket, token)
                await socket.send(json.dumps(command))
                handler_id = await self._wait_for_stt(socket)

                async for chunk in audio:
                    if chunk:
                        await socket.send(bytes((handler_id,)) + chunk)
                await socket.send(bytes((handler_id,)))
                return await self._collect_result(socket)
        except (VoicePipelineUnavailable, VoicePipelineFailed):
            raise
        except Exception as error:
            raise VoicePipelineFailed(
                f"Home Assistant voice pipeline failed: {error}"
            ) from error

    async def transcribe(
        self,
        audio: AsyncIterable[bytes],
        *,
        sample_rate: int,
        language: str | None = None,
    ) -> str:
        """Run only STT so Pilot Core can own intent routing and conversation."""
        token = read_secret(self.settings.home_assistant_token_env)
        if not self.settings.home_assistant_url or not token:
            raise VoicePipelineUnavailable(
                "Home Assistant URL and token are required for voice"
            )
        if sample_rate not in {8000, 16000, 24000, 32000, 48000}:
            raise VoicePipelineFailed("unsupported input sample rate")
        command: dict[str, Any] = {
            "id": 1,
            "type": "assist_pipeline/run",
            "start_stage": "stt",
            "end_stage": "stt",
            "input": {"sample_rate": sample_rate},
            "timeout": self.settings.home_assistant_assist_timeout_seconds,
        }
        _ = language
        if self.settings.home_assistant_assist_pipeline_id:
            command["pipeline"] = self.settings.home_assistant_assist_pipeline_id

        websocket_url = _websocket_url(self.settings.home_assistant_url)
        try:
            async with self.connector(
                websocket_url,
                open_timeout=10,
                close_timeout=5,
                max_size=2_000_000,
            ) as socket:
                await self._authenticate(socket, token)
                await socket.send(json.dumps(command))
                handler_id = await self._wait_for_stt(socket)
                async for chunk in audio:
                    if chunk:
                        await socket.send(bytes((handler_id,)) + chunk)
                await socket.send(bytes((handler_id,)))
                return await self._collect_transcript(socket)
        except (VoicePipelineUnavailable, VoicePipelineFailed):
            raise
        except Exception as error:
            raise VoicePipelineFailed(
                f"Home Assistant transcription failed: {error}"
            ) from error

    async def _authenticate(self, socket: Any, token: str) -> None:
        message = self._json(await socket.recv())
        if message.get("type") != "auth_required":
            raise VoicePipelineFailed("Home Assistant did not request authentication")
        await socket.send(json.dumps({"type": "auth", "access_token": token}))
        message = self._json(await socket.recv())
        if message.get("type") != "auth_ok":
            raise VoicePipelineFailed("Home Assistant authentication failed")

    async def _wait_for_stt(self, socket: Any) -> int:
        handler_id: int | None = None
        stt_started = False
        while not stt_started:
            message = self._json(await socket.recv())
            if message.get("type") == "result":
                if not message.get("success"):
                    raise VoicePipelineFailed(
                        self._error_message(message, "Assist pipeline was rejected")
                    )
                continue
            event = self._event(message)
            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "run-start":
                raw_handler = (data.get("runner_data") or {}).get(
                    "stt_binary_handler_id"
                )
                if isinstance(raw_handler, int) and 0 <= raw_handler <= 255:
                    handler_id = raw_handler
            elif event_type == "stt-start":
                stt_started = True
            elif event_type == "error":
                raise VoicePipelineFailed(
                    str(data.get("message") or data.get("code") or "STT failed")
                )
        if handler_id is None:
            raise VoicePipelineFailed("Home Assistant returned no STT audio handler")
        return handler_id

    async def _collect_result(self, socket: Any) -> VoicePipelineResult:
        transcript = ""
        response_text = ""
        conversation_id: str | None = None
        intent_output: dict[str, Any] = {}
        while True:
            event = self._event(self._json(await socket.recv()))
            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "stt-end":
                value = (data.get("stt_output") or {}).get("text")
                if isinstance(value, str):
                    transcript = value.strip()
            elif event_type == "intent-end":
                raw_output = data.get("intent_output")
                if isinstance(raw_output, dict):
                    intent_output = raw_output
                    response_text = _speech_text(raw_output)
                    raw_conversation = raw_output.get("conversation_id")
                    if isinstance(raw_conversation, str):
                        conversation_id = raw_conversation
            elif event_type == "error":
                raise VoicePipelineFailed(
                    str(
                        data.get("message")
                        or data.get("code")
                        or "Assist pipeline failed"
                    )
                )
            elif event_type == "run-end":
                break
        if not transcript:
            raise VoicePipelineFailed("Home Assistant returned no transcript")
        if not response_text:
            raise VoicePipelineFailed("Home Assistant returned no spoken response")
        return VoicePipelineResult(
            transcript=transcript,
            response_text=response_text,
            conversation_id=conversation_id,
            raw_response=intent_output,
        )

    async def _collect_transcript(self, socket: Any) -> str:
        transcript = ""
        while True:
            event = self._event(self._json(await socket.recv()))
            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "stt-end":
                value = (data.get("stt_output") or {}).get("text")
                if isinstance(value, str):
                    transcript = value.strip()
            elif event_type == "error":
                raise VoicePipelineFailed(
                    str(data.get("message") or data.get("code") or "STT failed")
                )
            elif event_type == "run-end":
                break
        if not transcript:
            raise VoicePipelineFailed("Home Assistant returned no transcript")
        return transcript

    @staticmethod
    def _json(message: Any) -> dict[str, Any]:
        if not isinstance(message, str):
            raise VoicePipelineFailed("Home Assistant returned unexpected binary data")
        try:
            value = json.loads(message)
        except (TypeError, ValueError) as error:
            raise VoicePipelineFailed("Home Assistant returned invalid JSON") from error
        if not isinstance(value, dict):
            raise VoicePipelineFailed("Home Assistant returned an invalid message")
        return value

    @staticmethod
    def _event(message: dict[str, Any]) -> dict[str, Any]:
        if message.get("type") != "event":
            return {}
        event = message.get("event")
        return event if isinstance(event, dict) else {}

    @staticmethod
    def _error_message(message: dict[str, Any], fallback: str) -> str:
        error = message.get("error")
        if isinstance(error, dict):
            value = error.get("message") or error.get("code")
            if isinstance(value, str):
                return value
        return fallback
