from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import math
import os
from pathlib import Path
import secrets
import time
from typing import Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator

from . import __version__
from .assist_focus import AssistFocusBridge
from .audio_assets import AudioAssetError, AudioAssets
from .config import Settings
from .conversation import (
    AssistantTools,
    AssistantUnavailable,
    ConversationEngine,
    OpenAICompatibleLLM,
)
from .firmware import FirmwareReleaseError, FirmwareReleases, is_newer_version
from .integrations import IntegrationRequestFailed, IntegrationUnavailable, Integrations
from .media_state import MediaStateReader
from .meetings import MeetingRecordingError, MeetingRecordings
from .observability import evaluate_observability, prometheus_metrics
from .orchestration import ResolutionError, RoomOrchestrator
from .registry import Registry
from .secret_values import read_secret
from .storage import Store
from .tts import LocalTTS, TTSRequestFailed, TTSUnavailable
from .voice import (
    HomeAssistantVoicePipeline,
    VoicePipelineFailed,
    VoicePipelineUnavailable,
)
from .voice_acceptance import VoiceAcceptanceFailed, validate_voice_round_trip


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    room_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=100)


class BootstrapGrantRequest(DeviceRegistration):
    expires_in_seconds: int = Field(default=600, ge=60, le=3600)


class DeviceCapabilitiesUpdate(BaseModel):
    capabilities: list[str] = Field(max_length=100)


class EventInput(BaseModel):
    room_id: str
    type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)


class MediaCommand(BaseModel):
    action: str
    player_id: str
    media_uri: str | None = None
    target_player_id: str | None = None
    volume: int | None = Field(default=None, ge=0, le=100)
    source: str | None = Field(default=None, min_length=1, max_length=200)


class AssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    room_id: str
    language: str = Field(default="en", min_length=2, max_length=35)
    conversation_id: str | None = None
    speak: bool = False
    voice: str | None = Field(default=None, min_length=1, max_length=128)
    volume: float = Field(default=1.0, ge=0, le=1)
    device_id: str | None = None
    expires_in_seconds: int = Field(default=30, ge=1, le=300)
    retention_seconds: int | None = Field(default=None, ge=60, le=86_400)


class DeviceAssistantRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="en", min_length=2, max_length=35)
    conversation_id: str | None = None
    room_id: str | None = Field(default=None, min_length=1, max_length=128)


class MediaSearch(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    media_types: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)
    library_only: bool = False


class DeviceCommandInput(BaseModel):
    action: Literal[
        "play",
        "pause",
        "stop",
        "set_volume",
        "start_listening",
        "stop_listening",
        "assistant_start",
        "assistant_end",
        "announcement_start",
        "announcement_end",
        "cancel",
    ]
    source: Literal["room", "music", "airplay", "all"] | None = None
    volume: float | None = Field(default=None, ge=0, le=1)
    critical: bool | None = None
    ttl_seconds: int | None = Field(default=None, ge=1, le=300)
    expires_in_seconds: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "DeviceCommandInput":
        if self.action in {"play", "pause", "stop"} and self.source == "room":
            raise ValueError("transport source must be music, airplay, or all")
        if self.action == "set_volume":
            if self.volume is None:
                raise ValueError("volume is required for set_volume")
            if self.source == "all":
                raise ValueError("volume source must be room, music, or airplay")
        return self

    def control_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"expires_in_seconds"}, exclude_none=True)


class RoomControlInput(DeviceCommandInput):
    device_id: str | None = None
    capability: Literal["audio", "voice"] | None = None

    def control_payload(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={"expires_in_seconds", "device_id", "capability"},
            exclude_none=True,
        )


class RoomMediaCommand(BaseModel):
    action: Literal[
        "play",
        "pause",
        "stop",
        "set_volume",
        "play_media",
        "transfer",
        "power_on",
        "power_off",
        "select_source",
    ]
    player_id: str | None = None
    media_uri: str | None = None
    target_room_id: str | None = None
    target_player_id: str | None = None
    volume: int | None = Field(default=None, ge=0, le=100)
    source: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "RoomMediaCommand":
        if self.action == "set_volume" and self.volume is None:
            raise ValueError("volume is required for set_volume")
        if self.action == "play_media" and not self.media_uri:
            raise ValueError("media_uri is required for play_media")
        if self.action == "transfer" and not self.target_room_id:
            raise ValueError("target_room_id is required for transfer")
        if self.action == "select_source" and not self.source:
            raise ValueError("source is required for select_source")
        return self


class RoomAudioCommand(BaseModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    device_id: str | None = None
    volume: float = Field(default=1.0, ge=0, le=1)
    critical: bool = False
    expires_in_seconds: int = Field(default=30, ge=1, le=300)


class RoomSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    voice: str | None = Field(default=None, min_length=1, max_length=128)
    kind: Literal["assistant", "announcement"] = "assistant"
    device_id: str | None = None
    volume: float = Field(default=1.0, ge=0, le=1)
    critical: bool = False
    expires_in_seconds: int = Field(default=30, ge=1, le=300)
    retention_seconds: int | None = Field(default=None, ge=60, le=86_400)

    @model_validator(mode="after")
    def validate_critical_kind(self) -> "RoomSpeakRequest":
        if self.critical and self.kind != "announcement":
            raise ValueError("only announcements may be critical")
        return self


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    language: str = Field(default="en", min_length=2, max_length=35)
    started_at: datetime | None = None
    source_device_id: str | None = Field(default=None, max_length=128)


class TranscriptSegmentInput(BaseModel):
    speaker_label: str | None = Field(default=None, max_length=100)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20_000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_timing(self) -> "TranscriptSegmentInput":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class MeetingTranscriptInput(BaseModel):
    segments: list[TranscriptSegmentInput] = Field(min_length=1, max_length=20_000)


class MeetingDecisionInput(BaseModel):
    summary: str = Field(min_length=1, max_length=4_000)
    segment_ids: list[str] = Field(default_factory=list, max_length=500)


class MeetingActionInput(BaseModel):
    task: str = Field(min_length=1, max_length=4_000)
    owner: str | None = Field(default=None, max_length=300)
    due_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    segment_ids: list[str] = Field(default_factory=list, max_length=500)


class MeetingAnalysisInput(BaseModel):
    summary: str = Field(min_length=1, max_length=20_000)
    decisions: list[MeetingDecisionInput] = Field(
        default_factory=list, max_length=1_000
    )
    action_items: list[MeetingActionInput] = Field(
        default_factory=list, max_length=2_000
    )


class EventHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def connect(self, socket: WebSocket) -> None:
        await socket.accept()
        async with self.lock:
            self.clients.add(socket)

    async def disconnect(self, socket: WebSocket) -> None:
        async with self.lock:
            self.clients.discard(socket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        async with self.lock:
            clients = tuple(self.clients)
        dead: list[WebSocket] = []
        for socket in clients:
            try:
                await socket.send_json(event)
            except Exception:
                dead.append(socket)
        for socket in dead:
            await self.disconnect(socket)


class DeviceConnection:
    def __init__(self, socket: WebSocket) -> None:
        self.socket = socket
        self.send_lock = asyncio.Lock()


class DeviceHub:
    def __init__(self) -> None:
        self.connections: dict[str, DeviceConnection] = {}
        self.lock = asyncio.Lock()

    async def connect(self, device_id: str, socket: WebSocket) -> None:
        await socket.accept()
        connection = DeviceConnection(socket)
        async with self.lock:
            previous = self.connections.get(device_id)
            self.connections[device_id] = connection
        if previous:
            try:
                await previous.socket.close(code=1012, reason="device reconnected")
            except Exception:
                pass

    async def disconnect(self, device_id: str, socket: WebSocket) -> None:
        async with self.lock:
            current = self.connections.get(device_id)
            if current and current.socket is socket:
                self.connections.pop(device_id, None)

    async def send(self, device_id: str, payload: dict[str, Any]) -> bool:
        async with self.lock:
            connection = self.connections.get(device_id)
        if not connection:
            return False
        try:
            async with connection.send_lock:
                await connection.socket.send_json(payload)
        except Exception:
            await self.disconnect(device_id, connection.socket)
            return False
        return True

    async def connected_ids(self) -> set[str]:
        async with self.lock:
            return set(self.connections)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer token required")
    return authorization.removeprefix("Bearer ").strip()


def create_app(settings: Settings, store: Store | None = None) -> FastAPI:
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    registry = Registry.from_settings(settings)
    owns_store = store is None
    database = store or Store(settings.server.database_path, settings)
    orchestrator = RoomOrchestrator(registry, database)
    integrations = Integrations(settings.integrations)
    media_states = MediaStateReader(registry, integrations)
    audio_assets = AudioAssets(
        database,
        settings.server.audio_asset_path,
        settings.server.audio_asset_max_bytes,
        settings.server.audio_asset_retention_seconds,
    )
    local_tts = LocalTTS(settings.integrations, settings.server.audio_asset_max_bytes)
    voice_pipeline = HomeAssistantVoicePipeline(settings.integrations)
    local_llm = OpenAICompatibleLLM(settings.integrations)
    assistant_tools = AssistantTools(
        registry,
        orchestrator,
        integrations,
        media_states,
        database,
    )
    conversation_engine = ConversationEngine(
        database,
        registry,
        assistant_tools,
        integrations,
        local_llm,
    )
    firmware_releases = FirmwareReleases(
        settings.server.firmware_asset_path,
        settings.server.firmware_asset_max_bytes,
    )
    meeting_recordings = MeetingRecordings(
        database,
        settings.server.meeting_asset_path,
        settings.server.meeting_asset_max_bytes,
    )
    hub = EventHub()
    device_hub = DeviceHub()
    dashboard_directory = Path(__file__).with_name("dashboard")
    focus_bridge: AssistFocusBridge | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal focus_bridge
        focus_bridge = AssistFocusBridge(
            settings.integrations,
            settings.rooms,
            queue_device_command,
        )
        focus_task = (
            asyncio.create_task(focus_bridge.run(), name="assist-focus-bridge")
            if focus_bridge.enabled
            else None
        )
        try:
            yield
        finally:
            if focus_bridge:
                await focus_bridge.stop()
            if focus_task:
                try:
                    await asyncio.wait_for(focus_task, timeout=6)
                except TimeoutError:
                    focus_task.cancel()
            if owns_store:
                database.close()

    app = FastAPI(title="Pilot Core", version=__version__, lifespan=lifespan)

    def dashboard_file(name: str, media_type: str) -> FileResponse:
        path = dashboard_directory / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="dashboard asset not found")
        return FileResponse(
            path,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            },
        )

    def authenticated_device(
        device_id: str,
        header_device_id: str,
        authorization: str | None,
    ) -> dict[str, Any]:
        if device_id != header_device_id:
            raise HTTPException(status_code=403, detail="device identity mismatch")
        if not database.authenticate_device(device_id, _bearer(authorization)):
            raise HTTPException(status_code=401, detail="invalid device credentials")
        device = next(
            (item for item in database.list_devices() if item["id"] == device_id),
            None,
        )
        if device is None:
            raise HTTPException(status_code=404, detail="device not found")
        return device

    def safe_weather(raw: dict[str, Any]) -> dict[str, Any]:
        current = raw.get("current") or {}
        attributes = current.get("attributes") or {}
        entity_id = str(raw.get("entity_id") or "")
        forecast_response = raw.get("forecast_response") or {}
        service_response = (
            forecast_response.get("service_response", forecast_response)
            if isinstance(forecast_response, dict)
            else {}
        )
        entity_forecast = (
            service_response.get(entity_id, {})
            if isinstance(service_response, dict)
            else {}
        )
        forecast = (
            entity_forecast.get("forecast", [])
            if isinstance(entity_forecast, dict)
            else []
        )
        today = forecast[0] if forecast and isinstance(forecast[0], dict) else {}
        tomorrow = (
            forecast[1] if len(forecast) > 1 and isinstance(forecast[1], dict) else {}
        )

        def value(source: dict[str, Any], key: str) -> Any:
            candidate = source.get(key)
            return candidate if isinstance(candidate, (str, int, float)) else None

        return {
            "status": "ok",
            "condition": value(current, "state"),
            "temperature": value(attributes, "temperature"),
            "apparent_temperature": value(attributes, "apparent_temperature"),
            "temperature_unit": value(attributes, "temperature_unit"),
            "humidity": value(attributes, "humidity"),
            "wind_speed": value(attributes, "wind_speed"),
            "wind_speed_unit": value(attributes, "wind_speed_unit"),
            "wind_bearing": value(attributes, "wind_bearing"),
            "high_temperature": value(today, "temperature"),
            "low_temperature": value(today, "templow"),
            "precipitation": value(today, "precipitation"),
            "precipitation_unit": value(attributes, "precipitation_unit"),
            "precipitation_probability": value(today, "precipitation_probability"),
            "forecast_condition": value(today, "condition"),
            "tomorrow_high_temperature": value(tomorrow, "temperature"),
            "tomorrow_low_temperature": value(tomorrow, "templow"),
            "tomorrow_precipitation_probability": value(
                tomorrow, "precipitation_probability"
            ),
            "tomorrow_condition": value(tomorrow, "condition"),
            "updated_at": value(current, "last_updated"),
        }

    def safe_temperature_history(raw: dict[str, Any]) -> dict[str, Any]:
        entity_id = str(raw.get("entity_id") or "")
        current = raw.get("current") or {}
        attributes = current.get("attributes") or {}
        history = raw.get("history") or []

        def numeric(candidate: Any) -> float | None:
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                return None
            return value if math.isfinite(value) and -100 <= value <= 100 else None

        def timestamp(candidate: Any) -> datetime | None:
            if not isinstance(candidate, str):
                return None
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)

        values: list[float] = []
        points: list[tuple[datetime, float]] = []
        current_value = numeric(current.get("state"))
        if current_value is not None:
            values.append(current_value)
            current_time = timestamp(
                current.get("last_updated") or current.get("last_changed")
            )
            if current_time is not None:
                points.append((current_time, current_value))
        if isinstance(history, list):
            for series in history:
                if not isinstance(series, list):
                    continue
                for state in series:
                    if not isinstance(state, dict):
                        continue
                    candidate = numeric(state.get("state"))
                    if candidate is not None:
                        values.append(candidate)
                        changed_at = timestamp(
                            state.get("last_changed") or state.get("last_updated")
                        )
                        if changed_at is not None:
                            points.append((changed_at, candidate))

        sample_count = 24
        period_hours = int(raw.get("period_hours") or 24)
        samples: list[float] = []
        if points:
            points.sort(key=lambda point: point[0])
            ended_at = points[-1][0]
            started_at = ended_at - timedelta(hours=period_hours)
            buckets: list[float | None] = [None] * sample_count
            period_seconds = max(1.0, (ended_at - started_at).total_seconds())
            for changed_at, candidate in points:
                if changed_at < started_at:
                    continue
                position = (changed_at - started_at).total_seconds() / period_seconds
                index = min(sample_count - 1, int(position * sample_count))
                buckets[index] = candidate
            previous = points[0][1]
            for candidate in buckets:
                if candidate is not None:
                    previous = candidate
                samples.append(round(previous, 2))

        unit = attributes.get("unit_of_measurement")
        updated_at = current.get("last_updated")
        return {
            "status": "ok" if current_value is not None and values else "unavailable",
            "entity_id": entity_id,
            "current": current_value,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "temperature_unit": unit if isinstance(unit, str) else None,
            "period_hours": period_hours,
            "samples": samples,
            "updated_at": updated_at if isinstance(updated_at, str) else None,
        }

    def safe_energy(raw: dict[str, dict[str, Any]]) -> dict[str, Any]:
        def measurement(name: str, *, percent: bool = False) -> dict[str, Any]:
            state = raw.get(name) or {}
            attributes = state.get("attributes") or {}
            unit = str(attributes.get("unit_of_measurement") or "")
            try:
                value: float | None = float(state.get("state"))
                if not math.isfinite(value):
                    value = None
            except (TypeError, ValueError):
                value = None
            if value is not None and not percent:
                if unit.casefold() == "kw":
                    value *= 1000
                elif unit.casefold() not in {"w", "watt", "watts"}:
                    value = None
            if value is not None:
                value = round(value, 1)
            return {
                "value": value,
                "unit": "%" if percent else "W",
                "observed_at": state.get("last_updated") or state.get("last_changed"),
            }

        solar = measurement("solar")
        grid = measurement("grid")
        battery = measurement("battery")
        battery_soc = measurement("battery_soc", percent=True)
        home_load = measurement("home_load")

        def direction(value: object, positive: str, negative: str) -> str:
            if not isinstance(value, (int, float)) or abs(value) < 25:
                return "idle"
            return positive if value > 0 else negative

        grid["direction"] = direction(grid["value"], "importing", "exporting")
        battery["direction"] = direction(
            battery["value"], "discharging", "charging"
        )
        return {
            "status": (
                "ok"
                if all(
                    item["value"] is not None
                    for item in (solar, grid, battery, battery_soc, home_load)
                )
                else "partial"
            ),
            "solar": solar,
            "grid": grid,
            "battery": battery,
            "battery_soc": battery_soc,
            "home_load": home_load,
        }

    async def queue_device_command(
        device_id: str, payload: dict[str, Any], expires_in_seconds: int
    ) -> dict[str, Any]:
        try:
            command = database.create_command(device_id, payload, expires_in_seconds)
        except KeyError:
            raise HTTPException(status_code=404, detail="device not found") from None
        if await device_hub.send(device_id, {"type": "command", "command": command}):
            database.mark_command_delivered(command["id"], device_id)
            command = database.get_command(command["id"]) or command
        return command

    async def audio_targets(room_id: str, device_id: str | None) -> tuple[Any, Any]:
        try:
            target = orchestrator.device(
                room_id,
                await device_hub.connected_ids(),
                "audio",
                device_id,
            )
            response_player = orchestrator.response_player(room_id)
        except ResolutionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        return target, response_player

    async def dispatch_audio_asset(
        room_id: str,
        asset: dict[str, Any],
        target: Any,
        response_player: Any,
        volume: float,
        critical: bool,
        expires_in_seconds: int,
    ) -> dict[str, Any]:
        payload = {
            "action": "play_audio",
            "audio_asset_id": asset["id"],
            "sha256": asset["sha256"],
            "size_bytes": asset["size_bytes"],
            "content_type": asset["content_type"],
            "kind": asset["kind"],
            "volume": volume,
            "critical": critical,
        }
        command = await queue_device_command(target.id, payload, expires_in_seconds)
        return {
            "room_id": room_id,
            "target": target.as_dict(),
            "response_player": response_player.as_dict(),
            "asset": audio_assets.public_view(asset),
            "command": command,
        }

    async def synthesize_room_speech(
        room_id: str,
        text: str,
        language: str | None,
        voice: str | None,
        kind: str,
        device_id: str | None,
        volume: float,
        critical: bool,
        expires_in_seconds: int,
        retention_seconds: int | None,
    ) -> dict[str, Any]:
        target, response_player = await audio_targets(room_id, device_id)
        try:
            synthesized = await local_tts.synthesize(text, language, voice)
        except TTSUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except TTSRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        try:
            asset = audio_assets.create(
                room_id,
                kind,
                synthesized.filename,
                synthesized.content_type,
                synthesized.content,
                retention_seconds,
            )
        except AudioAssetError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        delivery = await dispatch_audio_asset(
            room_id,
            asset,
            target,
            response_player,
            volume,
            critical,
            expires_in_seconds,
        )
        delivery["synthesis"] = synthesized.metadata()
        return delivery

    async def run_media_command(
        player_id: str,
        action: str,
        volume: int | None = None,
        media_uri: str | None = None,
        target_player_id: str | None = None,
        source: str | None = None,
    ) -> Any:
        player = registry.players.get(player_id)
        if not player:
            raise HTTPException(status_code=404, detail="player not found")
        if not player.control_enabled:
            raise HTTPException(
                status_code=409,
                detail=f"player {player.id} controls are disabled",
            )
        external_id = player.external_id or player.id
        if action in {"power_on", "power_off", "select_source"}:
            control_endpoint = player.control_endpoint or player.endpoint
            if not control_endpoint:
                raise HTTPException(
                    status_code=422,
                    detail=f"player {player.id} has no control endpoint",
                )
            if action == "select_source" and not source:
                raise HTTPException(status_code=422, detail="source is required")
            try:
                if control_endpoint.startswith(("http://", "https://")):
                    return await integrations.denon_avr_command(
                        control_endpoint,
                        action,
                        source=source,
                    )
                return await integrations.home_assistant_media_player_command(
                    control_endpoint,
                    action,
                    source=source,
                )
            except IntegrationUnavailable as error:
                raise HTTPException(status_code=503, detail=str(error)) from None
            except IntegrationRequestFailed as error:
                raise HTTPException(status_code=502, detail=str(error)) from None
        target_external_id: str | None = None
        if target_player_id is not None:
            target = registry.players.get(target_player_id)
            if target is None:
                raise HTTPException(status_code=404, detail="target player not found")
            if not target.control_enabled:
                raise HTTPException(
                    status_code=409,
                    detail=f"player {target.id} controls are disabled",
                )
            target_external_id = target.external_id or target.id
        command_map = {
            "play": ("players/cmd/play", {"player_id": external_id}),
            "pause": ("players/cmd/pause", {"player_id": external_id}),
            "stop": ("players/cmd/stop", {"player_id": external_id}),
            "set_volume": (
                "players/cmd/volume_set",
                {"player_id": external_id, "volume_level": volume},
            ),
            "play_media": (
                "player_queues/play_media",
                {"queue_id": external_id, "media": media_uri},
            ),
            "transfer": (
                "player_queues/transfer",
                {
                    "source_queue_id": external_id,
                    "target_queue_id": target_external_id,
                    "auto_play": True,
                },
            ),
        }
        if action not in command_map:
            raise HTTPException(status_code=422, detail="unsupported media action")
        if action == "set_volume" and volume is None:
            raise HTTPException(status_code=422, detail="volume is required")
        if action == "play_media" and not media_uri:
            raise HTTPException(status_code=422, detail="media_uri is required")
        if action == "transfer" and not target_player_id:
            raise HTTPException(status_code=422, detail="target_player_id is required")
        rpc_command, args = command_map[action]
        try:
            return await integrations.music_assistant(rpc_command, args)
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        configured = read_secret(settings.server.admin_token_env)
        if not configured or not secrets.compare_digest(
            _bearer(authorization), configured
        ):
            raise HTTPException(status_code=401, detail="invalid admin token")

    def require_bootstrap(authorization: str | None = Header(default=None)) -> None:
        if not settings.server.legacy_bootstrap_enabled:
            raise HTTPException(
                status_code=403, detail="legacy bootstrap registration is disabled"
            )
        configured = read_secret(settings.server.bootstrap_token_env)
        if not configured or not secrets.compare_digest(
            _bearer(authorization), configured
        ):
            raise HTTPException(status_code=401, detail="invalid bootstrap token")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse("/dashboard", status_code=307)

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return dashboard_file("index.html", "text/html")

    @app.get("/dashboard/assets/{asset_name}", include_in_schema=False)
    async def dashboard_asset(asset_name: str) -> FileResponse:
        allowed = {
            "app.css": "text/css",
            "app.js": "text/javascript",
        }
        media_type = allowed.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="dashboard asset not found")
        return dashboard_file(asset_name, media_type)

    @app.get("/readyz")
    async def ready() -> dict[str, Any]:
        return {
            "ready": True,
            "registry_revision": registry.revision,
            "room_count": len(registry.rooms),
            "player_count": len(registry.players),
            "tts_configured": local_tts.status()["configured"],
            "assistant": conversation_engine.status(),
            "legacy_bootstrap_enabled": settings.server.legacy_bootstrap_enabled,
        }

    @app.get("/v1/rooms", dependencies=[Depends(require_admin)])
    async def rooms() -> dict[str, Any]:
        return {"rooms": registry.list_rooms()}

    @app.post(
        "/v1/meetings",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def create_meeting(request: MeetingCreate) -> dict[str, Any]:
        started_at = request.started_at or datetime.now(UTC)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        return database.create_meeting(
            request.title.strip(),
            request.language,
            started_at.astimezone(UTC).isoformat(),
            request.source_device_id,
        )

    @app.get("/v1/meetings", dependencies=[Depends(require_admin)])
    async def list_meetings(
        limit: int = Query(default=50, ge=1, le=200),
        status: Literal["created", "recorded", "transcribed", "ready", "failed"]
        | None = None,
    ) -> dict[str, Any]:
        return {"meetings": database.list_meetings(limit, status)}

    @app.get(
        "/v1/meetings/{meeting_id}",
        dependencies=[Depends(require_admin)],
    )
    async def meeting_detail(meeting_id: str) -> dict[str, Any]:
        meeting = database.get_meeting(meeting_id)
        if meeting is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        return meeting

    @app.put(
        "/v1/meetings/{meeting_id}/recording",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def upload_meeting_recording(
        meeting_id: str,
        request: Request,
        x_pilot_filename: str = Header(default="recording"),
    ) -> dict[str, Any]:
        try:
            recording = await meeting_recordings.save(
                meeting_id,
                x_pilot_filename,
                request.headers.get("content-type", ""),
                request.stream(),
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="meeting not found") from None
        except MeetingRecordingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return {key: value for key, value in recording.items() if key != "path"}

    @app.get(
        "/v1/meetings/{meeting_id}/recording",
        dependencies=[Depends(require_admin)],
    )
    async def download_meeting_recording(meeting_id: str) -> FileResponse:
        if database.get_meeting(meeting_id) is None:
            raise HTTPException(status_code=404, detail="meeting not found")
        recording = database.get_meeting_recording(meeting_id)
        if recording is None:
            raise HTTPException(status_code=404, detail="recording not found")
        return FileResponse(
            recording["path"],
            media_type=recording["content_type"],
            filename=recording["filename"],
            headers={"Cache-Control": "no-store"},
        )

    @app.put(
        "/v1/meetings/{meeting_id}/transcript",
        dependencies=[Depends(require_admin)],
    )
    async def replace_meeting_transcript(
        meeting_id: str, request: MeetingTranscriptInput
    ) -> dict[str, Any]:
        try:
            return database.replace_transcript(
                meeting_id,
                [segment.model_dump() for segment in request.segments],
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="meeting not found") from None

    @app.put(
        "/v1/meetings/{meeting_id}/analysis",
        dependencies=[Depends(require_admin)],
    )
    async def replace_meeting_analysis(
        meeting_id: str, request: MeetingAnalysisInput
    ) -> dict[str, Any]:
        try:
            return database.replace_meeting_analysis(
                meeting_id,
                request.summary,
                [decision.model_dump() for decision in request.decisions],
                [
                    {
                        **action.model_dump(),
                        "due_at": (
                            (
                                action.due_at
                                if action.due_at.tzinfo is not None
                                else action.due_at.replace(tzinfo=UTC)
                            )
                            .astimezone(UTC)
                            .isoformat()
                            if action.due_at
                            else None
                        ),
                    }
                    for action in request.action_items
                ],
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="meeting not found") from None

    @app.get("/v1/state", dependencies=[Depends(require_admin)])
    async def whole_home_state() -> dict[str, Any]:
        connected = await device_hub.connected_ids()
        return {
            "registry_revision": registry.revision,
            "rooms": {
                room_id: orchestrator.room_state(room_id, connected)
                for room_id in sorted(registry.rooms)
            },
        }

    async def build_operations_snapshot() -> dict[str, Any]:
        connected = await device_hub.connected_ids()
        rooms_state = {
            room_id: orchestrator.room_state(room_id, connected)
            for room_id in sorted(registry.rooms)
        }
        diagnostics, media_snapshot = await asyncio.gather(
            integrations.diagnostics(),
            media_states.snapshot(),
        )
        tts_status = local_tts.status()
        tts_status["status"] = (
            "configured" if tts_status["configured"] else "not_configured"
        )
        diagnostics["tts"] = tts_status
        devices = database.list_devices()
        commands = database.list_commands(limit=50)
        events = database.recent_events(limit=50)
        recent_conversations = database.list_conversation_sessions(limit=8)

        armed_rooms: list[str] = []
        unarmed_rooms: list[str] = []
        for room_id, room_state_payload in rooms_state.items():
            armed = any(
                device.get("connected")
                and (
                    (device.get("health") or {})
                    .get("payload", {})
                    .get("audio_activation", {})
                    .get("allowed")
                    is True
                )
                for device in room_state_payload["devices"]
            )
            (armed_rooms if armed else unarmed_rooms).append(room_id)

        configured_integrations = [
            status
            for status in diagnostics.values()
            if status.get("configured") is True
        ]
        command_counts: dict[str, int] = {}
        for command_payload in commands:
            status = str(command_payload["status"])
            command_counts[status] = command_counts.get(status, 0) + 1

        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "deployment": {
                "version": __version__,
                "release": os.environ.get("PILOT_CORE_RELEASE", "development"),
                "started_at": started_at.isoformat(),
                "uptime_seconds": round(time.monotonic() - started_monotonic, 3),
                "legacy_bootstrap_enabled": settings.server.legacy_bootstrap_enabled,
            },
            "registry_revision": registry.revision,
            "summary": {
                "room_count": len(rooms_state),
                "device_count": len(devices),
                "connected_device_count": sum(
                    device["id"] in connected for device in devices
                ),
                "configured_integration_count": len(configured_integrations),
                "healthy_integration_count": sum(
                    status.get("status") == "ok" for status in configured_integrations
                ),
                "armed_room_count": len(armed_rooms),
                "unarmed_room_count": len(unarmed_rooms),
                "pending_command_count": sum(
                    command_counts.get(status, 0) for status in ("queued", "delivered")
                ),
            },
            "safety": {
                "audible_actions_gated": bool(unarmed_rooms),
                "armed_rooms": armed_rooms,
                "unarmed_rooms": unarmed_rooms,
            },
            "integrations": diagnostics,
            "media": media_snapshot,
            "rooms": rooms_state,
            "commands": commands,
            "command_counts": command_counts,
            "events": events,
            "assistant": {
                **conversation_engine.status(),
                "active_session_count": sum(
                    item["status"] == "active" for item in recent_conversations
                ),
                "recent_conversations": recent_conversations,
            },
        }
        payload["observability"] = evaluate_observability(payload)
        return payload

    @app.get("/v1/operations", dependencies=[Depends(require_admin)])
    async def operations(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return await build_operations_snapshot()

    @app.get("/v1/observability", dependencies=[Depends(require_admin)])
    async def observability(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return (await build_operations_snapshot())["observability"]

    @app.get(
        "/v1/metrics",
        dependencies=[Depends(require_admin)],
        response_class=PlainTextResponse,
    )
    async def metrics() -> PlainTextResponse:
        snapshot = await build_operations_snapshot()
        return PlainTextResponse(
            prometheus_metrics(snapshot, snapshot["observability"]),
            media_type="text/plain; version=0.0.4",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/v1/rooms/{room_id}", dependencies=[Depends(require_admin)])
    async def room(room_id: str) -> dict[str, Any]:
        if room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        payload = registry.room_view(room_id)
        payload["focus"] = database.room_focus(room_id)
        return payload

    @app.get("/v1/rooms/{room_id}/state", dependencies=[Depends(require_admin)])
    async def room_state(room_id: str) -> dict[str, Any]:
        try:
            return orchestrator.room_state(room_id, await device_hub.connected_ids())
        except ResolutionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None

    @app.get(
        "/v1/rooms/{room_id}/media-state",
        dependencies=[Depends(require_admin)],
    )
    async def room_media_state(room_id: str, response: Response) -> dict[str, Any]:
        if room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        response.headers["Cache-Control"] = "no-store"
        return await media_states.snapshot(room_id)

    @app.post(
        "/v1/rooms/{room_id}/control",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def room_control(room_id: str, request: RoomControlInput) -> dict[str, Any]:
        capability = request.capability or (
            "voice"
            if request.action
            in {"start_listening", "stop_listening", "assistant_start", "assistant_end"}
            else "audio"
        )
        try:
            target = orchestrator.device(
                room_id,
                await device_hub.connected_ids(),
                capability,
                request.device_id,
            )
        except ResolutionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        command = await queue_device_command(
            target.id, request.control_payload(), request.expires_in_seconds
        )
        return {
            "room_id": room_id,
            "target": target.as_dict(),
            "command": command,
        }

    @app.post(
        "/v1/rooms/{room_id}/media",
        dependencies=[Depends(require_admin)],
    )
    async def room_media(room_id: str, request: RoomMediaCommand) -> dict[str, Any]:
        try:
            player = orchestrator.music_player(room_id, request.player_id)
            target_player = (
                orchestrator.music_player(
                    request.target_room_id, request.target_player_id
                )
                if request.action == "transfer" and request.target_room_id
                else None
            )
        except ResolutionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        result = await run_media_command(
            player.id,
            request.action,
            request.volume,
            request.media_uri,
            target_player.id if target_player else None,
            request.source,
        )
        return {
            "room_id": room_id,
            "player": player.as_dict(),
            "target_room_id": request.target_room_id,
            "target_player": target_player.as_dict() if target_player else None,
            "result": result,
        }

    @app.post(
        "/v1/rooms/{room_id}/audio-assets",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def create_audio_asset(
        room_id: str,
        request: Request,
        kind: Literal["assistant", "announcement"] = Query(),
        filename: str = Query(default="speech", max_length=200),
        retention_seconds: int | None = Query(default=None, ge=60, le=86_400),
    ) -> dict[str, Any]:
        try:
            orchestrator.require_room(room_id)
        except ResolutionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.server.audio_asset_max_bytes:
                    raise HTTPException(
                        status_code=413, detail="audio asset is too large"
                    )
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="invalid content-length"
                ) from None
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > settings.server.audio_asset_max_bytes:
                raise HTTPException(status_code=413, detail="audio asset is too large")
        try:
            asset = audio_assets.create(
                room_id,
                kind,
                filename,
                request.headers.get("content-type", ""),
                bytes(content),
                retention_seconds,
            )
        except AudioAssetError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return audio_assets.public_view(asset)

    @app.get(
        "/v1/rooms/{room_id}/audio-assets",
        dependencies=[Depends(require_admin)],
    )
    async def room_audio_assets(room_id: str, limit: int = 100) -> dict[str, Any]:
        try:
            orchestrator.require_room(room_id)
        except ResolutionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        return {
            "assets": [
                audio_assets.public_view(asset)
                for asset in audio_assets.list(room_id, min(max(limit, 1), 500))
            ]
        }

    @app.post(
        "/v1/rooms/{room_id}/audio",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def room_audio(room_id: str, request: RoomAudioCommand) -> dict[str, Any]:
        asset = audio_assets.get(request.asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="audio asset not found")
        if asset["room_id"] != room_id:
            raise HTTPException(
                status_code=409, detail="audio asset belongs to another room"
            )
        if request.critical and asset["kind"] != "announcement":
            raise HTTPException(
                status_code=422,
                detail="only announcement assets may be critical",
            )
        target, response_player = await audio_targets(room_id, request.device_id)
        return await dispatch_audio_asset(
            room_id,
            asset,
            target,
            response_player,
            request.volume,
            request.critical,
            request.expires_in_seconds,
        )

    @app.get("/v1/tts", dependencies=[Depends(require_admin)])
    async def tts_status() -> dict[str, Any]:
        return local_tts.status()

    @app.post(
        "/v1/voice/acceptance",
        dependencies=[Depends(require_admin)],
    )
    async def voice_acceptance(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            result = await validate_voice_round_trip(local_tts, voice_pipeline)
        except (TTSUnavailable, VoicePipelineUnavailable) as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except (
            TTSRequestFailed,
            VoicePipelineFailed,
            VoiceAcceptanceFailed,
        ) as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        return result.as_dict()

    @app.post(
        "/v1/rooms/{room_id}/speak",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def room_speak(room_id: str, request: RoomSpeakRequest) -> dict[str, Any]:
        try:
            orchestrator.require_room(room_id)
        except ResolutionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        return await synthesize_room_speech(
            room_id,
            request.text,
            request.language,
            request.voice,
            request.kind,
            request.device_id,
            request.volume,
            request.critical,
            request.expires_in_seconds,
            request.retention_seconds,
        )

    @app.get("/v1/audio-assets/{asset_id}")
    async def download_audio_asset(
        asset_id: str,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        token = _bearer(authorization)
        if not database.authenticate_device(x_pilot_device_id, token):
            raise HTTPException(status_code=401, detail="invalid device credentials")
        asset = audio_assets.get(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="audio asset not found")
        device = next(
            (
                item
                for item in database.list_devices()
                if item["id"] == x_pilot_device_id
            ),
            None,
        )
        if device is None or device["room_id"] != asset["room_id"]:
            raise HTTPException(
                status_code=403, detail="device cannot access this room's audio"
            )
        return FileResponse(
            asset["path"],
            media_type=asset["content_type"],
            filename=asset["filename"],
            headers={
                "Cache-Control": "private, no-store",
                "X-Pilot-SHA256": asset["sha256"],
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.delete(
        "/v1/audio-assets/{asset_id}",
        dependencies=[Depends(require_admin)],
        status_code=204,
    )
    async def delete_audio_asset(asset_id: str) -> None:
        if not audio_assets.delete(asset_id):
            raise HTTPException(status_code=404, detail="audio asset not found")

    @app.get("/v1/players", dependencies=[Depends(require_admin)])
    async def players() -> dict[str, Any]:
        return {"players": registry.list_players()}

    @app.get("/v1/players/{player_id}", dependencies=[Depends(require_admin)])
    async def player(player_id: str) -> dict[str, Any]:
        if player_id not in registry.players:
            raise HTTPException(status_code=404, detail="player not found")
        return registry.players[player_id].as_dict()

    @app.get(
        "/v1/players/{player_id}/state",
        dependencies=[Depends(require_admin)],
    )
    async def player_state(player_id: str, response: Response) -> dict[str, Any]:
        player_config = registry.players.get(player_id)
        if player_config is None:
            raise HTTPException(status_code=404, detail="player not found")
        response.headers["Cache-Control"] = "no-store"
        snapshot = await media_states.snapshot(player_config.room_id)
        return snapshot["players"][player_id]

    @app.get("/v1/devices", dependencies=[Depends(require_admin)])
    async def devices() -> dict[str, Any]:
        connected = await device_hub.connected_ids()
        result = database.list_devices()
        for device in result:
            device["connected"] = device["id"] in connected
        return {"devices": result}

    @app.patch(
        "/v1/devices/{device_id}/capabilities",
        dependencies=[Depends(require_admin)],
    )
    async def update_device_capabilities(
        device_id: str,
        request: DeviceCapabilitiesUpdate,
        response: Response,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            device = database.update_device_capabilities(
                device_id, request.capabilities
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="device not found") from None
        return {"device": device}

    @app.post(
        "/v1/bootstrap-grants",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def create_bootstrap_grant(
        request: BootstrapGrantRequest,
        response: Response,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return database.create_bootstrap_grant(
                request.device_id,
                request.room_id,
                request.name,
                request.capabilities,
                request.expires_in_seconds,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="room not found") from None

    @app.post("/v1/devices/bootstrap", status_code=201)
    async def bootstrap_device(
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return database.redeem_bootstrap_grant(_bearer(authorization))
        except PermissionError:
            raise HTTPException(
                status_code=401, detail="invalid or expired bootstrap grant"
            ) from None

    @app.post("/v1/devices/register", dependencies=[Depends(require_bootstrap)])
    async def register(
        request: DeviceRegistration, response: Response
    ) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        try:
            token = database.register_device(
                request.device_id,
                request.room_id,
                request.name,
                request.capabilities,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="room not found") from None
        return {"device_id": request.device_id, "device_token": token}

    @app.get("/v1/devices/{device_id}/snapshot")
    async def display_node_snapshot(
        device_id: str,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        response.headers["Cache-Control"] = "no-store"

        async def weather_snapshot() -> dict[str, Any]:
            try:
                return safe_weather(await integrations.home_assistant_weather())
            except IntegrationUnavailable as error:
                return {"status": "not_configured", "detail": str(error)}
            except IntegrationRequestFailed as error:
                return {"status": "unavailable", "detail": str(error)}

        async def temperature_snapshot(entity_id: str) -> dict[str, Any]:
            if not entity_id:
                return {
                    "status": "not_configured",
                    "detail": "temperature entity is not configured",
                }
            try:
                raw = await integrations.home_assistant_temperature_history(entity_id)
                return safe_temperature_history(raw)
            except IntegrationUnavailable as error:
                return {"status": "not_configured", "detail": str(error)}
            except IntegrationRequestFailed as error:
                return {"status": "unavailable", "detail": str(error)}

        weather, outside_temperature, inside_temperature = await asyncio.gather(
            weather_snapshot(),
            temperature_snapshot(settings.integrations.outdoor_temperature_entity_id),
            temperature_snapshot(settings.integrations.indoor_temperature_entity_id),
        )
        return {
            "device_id": device_id,
            "room_id": device["room_id"],
            "server_time": datetime.now(UTC).isoformat(),
            "weather": weather,
            "temperature_extremes": {
                "outside": outside_temperature,
                "inside": inside_temperature,
            },
            "voice": voice_pipeline.status(),
            "tts": local_tts.status(),
        }

    @app.get("/v1/devices/{device_id}/surface")
    async def display_node_surface(
        device_id: str,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "display" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have display capability"
            )
        response.headers["Cache-Control"] = "no-store"

        async def energy_snapshot() -> dict[str, Any]:
            try:
                return safe_energy(await integrations.home_assistant_energy())
            except IntegrationUnavailable as error:
                return {"status": "not_configured", "detail": str(error)}
            except IntegrationRequestFailed as error:
                return {"status": "unavailable", "detail": str(error)}

        energy, now_playing = await asyncio.gather(
            energy_snapshot(),
            media_states.now_playing(),
        )
        return {
            "device_id": device_id,
            "room_id": device["room_id"],
            "server_time": datetime.now(UTC).isoformat(),
            "energy": energy,
            "now_playing": now_playing,
        }

    @app.post("/v1/devices/{device_id}/assistant")
    async def device_text_assistant(
        device_id: str,
        request: DeviceAssistantRequest,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "voice" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have voice capability"
            )
        room_id = device["room_id"]
        if request.room_id and request.room_id != room_id:
            if "portable-client" not in device["capabilities"]:
                raise HTTPException(
                    status_code=403,
                    detail="fixed-room device cannot change conversation room",
                )
            if request.room_id not in registry.rooms:
                raise HTTPException(status_code=404, detail="room not found")
            room_id = request.room_id
        try:
            result = await conversation_engine.respond(
                request.text,
                room_id,
                language=request.language,
                session_id=request.conversation_id,
                device_id=device_id,
            )
        except AssistantUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        response.headers["Cache-Control"] = "no-store"
        return {
            "device_id": device_id,
            "room_id": room_id,
            **result.as_dict(),
        }

    @app.get("/v1/devices/{device_id}/media")
    async def device_media_state(
        device_id: str,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "media-control" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have media-control capability"
            )
        response.headers["Cache-Control"] = "no-store"
        return {
            "device_id": device_id,
            "room_id": device["room_id"],
            "rooms": registry.list_rooms(),
            "media": await media_states.snapshot(),
        }

    @app.post("/v1/devices/{device_id}/media")
    async def device_media_control(
        device_id: str,
        request: RoomMediaCommand,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "media-control" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have media-control capability"
            )
        room_id = device["room_id"]
        if request.player_id:
            selected = registry.players.get(request.player_id)
            if selected is None:
                raise HTTPException(status_code=404, detail="player not found")
            if (
                selected.room_id != device["room_id"]
                and "portable-client" not in device["capabilities"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="fixed-room device cannot control another room",
                )
            room_id = selected.room_id
        if (
            request.action == "transfer"
            and request.target_room_id
            and request.target_room_id != device["room_id"]
            and "portable-client" not in device["capabilities"]
        ):
            raise HTTPException(
                status_code=403,
                detail="fixed-room device cannot transfer media to another room",
            )
        try:
            player = orchestrator.music_player(room_id, request.player_id)
            target_player = (
                orchestrator.music_player(
                    request.target_room_id, request.target_player_id
                )
                if request.action == "transfer" and request.target_room_id
                else None
            )
        except ResolutionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        result = await run_media_command(
            player.id,
            request.action,
            request.volume,
            request.media_uri,
            target_player.id if target_player else None,
            request.source,
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "device_id": device_id,
            "room_id": room_id,
            "player": player.as_dict(),
            "target_room_id": request.target_room_id,
            "target_player": target_player.as_dict() if target_player else None,
            "result": result,
        }

    @app.post("/v1/devices/{device_id}/media/search")
    async def device_media_search(
        device_id: str,
        request: MediaSearch,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> Any:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "media-control" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have media-control capability"
            )
        args: dict[str, Any] = {
            "search_query": request.query,
            "limit": request.limit,
            "library_only": request.library_only,
        }
        if request.media_types:
            args["media_types"] = request.media_types
        try:
            result = await integrations.music_assistant("music/search", args)
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.post("/v1/devices/{device_id}/voice")
    async def display_node_voice(
        device_id: str,
        request: Request,
        response: Response,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
        x_pilot_sample_rate: int = Header(default=16000, ge=8000, le=48000),
        x_pilot_language: str | None = Header(default=None),
        x_pilot_conversation_id: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "voice" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have voice capability"
            )
        normalized_type = request.headers.get("content-type", "").partition(";")[0]
        if normalized_type.lower() not in {"audio/l16", "application/octet-stream"}:
            raise HTTPException(
                status_code=415,
                detail="voice audio must be signed 16-bit little-endian mono PCM",
            )
        declared_length = request.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > settings.server.voice_audio_max_bytes:
                    raise HTTPException(
                        status_code=413, detail="voice audio is too large"
                    )
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="invalid content length"
                ) from None

        total_bytes = 0

        async def bounded_audio():
            nonlocal total_bytes
            async for chunk in request.stream():
                total_bytes += len(chunk)
                if total_bytes > settings.server.voice_audio_max_bytes:
                    raise VoicePipelineFailed("voice audio exceeds the size limit")
                if chunk:
                    yield chunk

        try:
            transcript = await voice_pipeline.transcribe(
                bounded_audio(),
                sample_rate=x_pilot_sample_rate,
                language=x_pilot_language,
            )
        except VoicePipelineUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except VoicePipelineFailed as error:
            status_code = 413 if "size limit" in str(error).lower() else 502
            raise HTTPException(status_code=status_code, detail=str(error)) from None
        if total_bytes < x_pilot_sample_rate // 2:
            raise HTTPException(status_code=422, detail="voice audio is too short")
        try:
            assistant_result = await conversation_engine.respond(
                transcript,
                device["room_id"],
                language=x_pilot_language
                or settings.integrations.home_assistant_assist_language,
                session_id=x_pilot_conversation_id,
                device_id=device_id,
            )
        except AssistantUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None

        try:
            synthesized = await local_tts.synthesize(
                assistant_result.response_text,
                x_pilot_language,
            )
        except TTSUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except TTSRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        try:
            asset = audio_assets.create(
                device["room_id"],
                "assistant",
                synthesized.filename,
                synthesized.content_type,
                synthesized.content,
                300,
            )
        except AudioAssetError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

        response.headers["Cache-Control"] = "no-store"
        return {
            "device_id": device_id,
            "room_id": device["room_id"],
            "transcript": transcript,
            "response_text": assistant_result.response_text,
            "conversation_id": assistant_result.session_id,
            "provider": assistant_result.provider,
            "continue_conversation": assistant_result.continue_conversation,
            "audio": {
                **audio_assets.public_view(asset),
                "download_url": f"/v1/audio-assets/{asset['id']}",
            },
            "synthesis": synthesized.metadata(),
        }

    @app.get("/v1/devices/{device_id}/firmware")
    async def display_node_firmware_manifest(
        device_id: str,
        target: str,
        current_version: str = "",
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "ota" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have OTA capability"
            )
        try:
            release = firmware_releases.latest(target)
        except FirmwareReleaseError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        if release is None:
            return {
                "target": target,
                "current_version": current_version,
                "update_available": False,
                "release": None,
            }
        return {
            "target": target,
            "current_version": current_version,
            "update_available": is_newer_version(release.version, current_version),
            "release": {
                **release.manifest(),
                "download_url": (
                    f"/v1/devices/{device_id}/firmware/image?target={target}"
                ),
            },
        }

    @app.get("/v1/devices/{device_id}/firmware/image")
    async def display_node_firmware_image(
        device_id: str,
        target: str,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        device = authenticated_device(device_id, x_pilot_device_id, authorization)
        if "ota" not in device["capabilities"]:
            raise HTTPException(
                status_code=403, detail="device does not have OTA capability"
            )
        try:
            release = firmware_releases.latest(target)
        except FirmwareReleaseError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        if release is None:
            raise HTTPException(status_code=404, detail="firmware release not found")
        return FileResponse(
            release.path,
            media_type="application/octet-stream",
            filename=release.filename,
            headers={
                "Cache-Control": "no-store",
                "X-Pilot-Firmware-Version": release.version,
                "X-Pilot-Firmware-SHA256": release.sha256,
            },
        )

    @app.post(
        "/v1/devices/{device_id}/commands",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def create_device_command(
        device_id: str, request: DeviceCommandInput
    ) -> dict[str, Any]:
        return await queue_device_command(
            device_id, request.control_payload(), request.expires_in_seconds
        )

    @app.get(
        "/v1/devices/{device_id}/commands",
        dependencies=[Depends(require_admin)],
    )
    async def device_commands(device_id: str, limit: int = 100) -> dict[str, Any]:
        if not any(device["id"] == device_id for device in database.list_devices()):
            raise HTTPException(status_code=404, detail="device not found")
        return {"commands": database.list_commands(device_id, min(max(limit, 1), 500))}

    @app.get("/v1/commands/{command_id}", dependencies=[Depends(require_admin)])
    async def command(command_id: int) -> dict[str, Any]:
        result = database.get_command(command_id)
        if not result:
            raise HTTPException(status_code=404, detail="command not found")
        return result

    @app.get("/v1/commands", dependencies=[Depends(require_admin)])
    async def commands(limit: int = 100) -> dict[str, Any]:
        return {"commands": database.list_commands(limit=min(max(limit, 1), 500))}

    @app.websocket("/v1/devices/ws")
    async def device_socket(socket: WebSocket, device_id: str) -> None:
        authorization = socket.headers.get("authorization", "")
        token = (
            authorization.removeprefix("Bearer ").strip()
            if authorization.startswith("Bearer ")
            else ""
        )
        if not token or not database.authenticate_device(device_id, token):
            await socket.close(code=1008, reason="invalid device credentials")
            return
        await device_hub.connect(device_id, socket)
        await device_hub.send(device_id, {"type": "hello", "device_id": device_id})
        for pending in database.pending_commands(device_id):
            if await device_hub.send(
                device_id, {"type": "command", "command": pending}
            ):
                database.mark_command_delivered(pending["id"], device_id)
        try:
            while True:
                message = await socket.receive_json()
                if message.get("type") == "heartbeat":
                    database.authenticate_device(device_id, token)
                    await device_hub.send(device_id, {"type": "heartbeat_ack"})
                    continue
                if message.get("type") != "command_result":
                    await device_hub.send(
                        device_id,
                        {"type": "error", "error": "unsupported device message"},
                    )
                    continue
                try:
                    command_id = int(message["command_id"])
                    result_status = str(message["status"])
                    result_payload = message.get("result", {})
                    if not isinstance(result_payload, dict):
                        raise ValueError("result must be an object")
                    completed = database.complete_command(
                        command_id,
                        device_id,
                        result_status,
                        result_payload,
                    )
                except (KeyError, TypeError, ValueError) as error:
                    await device_hub.send(
                        device_id, {"type": "error", "error": str(error)}
                    )
                    continue
                event = {
                    "type": "command_result",
                    "device_id": device_id,
                    "room_id": completed["room_id"],
                    "command": completed,
                }
                await hub.broadcast(event)
                await device_hub.send(
                    device_id,
                    {"type": "command_ack", "command_id": command_id},
                )
        except WebSocketDisconnect:
            pass
        finally:
            await device_hub.disconnect(device_id, socket)

    @app.post("/v1/events")
    async def event(
        request: EventInput,
        x_pilot_device_id: str = Header(),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        token = _bearer(authorization)
        if not database.authenticate_device(x_pilot_device_id, token):
            raise HTTPException(status_code=401, detail="invalid device credentials")
        if request.type == "source_state":
            source = request.payload.get("source")
            if source not in {"critical", "assistant", "bluetooth", "airplay", "music"}:
                raise HTTPException(status_code=422, detail="invalid source")
            if not isinstance(request.payload.get("active"), bool):
                raise HTTPException(status_code=422, detail="active must be boolean")
        try:
            recorded = database.record_event(
                x_pilot_device_id,
                request.room_id,
                request.type,
                request.payload,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from None
        await hub.broadcast(recorded)
        return recorded

    @app.get("/v1/events", dependencies=[Depends(require_admin)])
    async def events(limit: int = 100) -> dict[str, Any]:
        return {"events": database.recent_events(min(max(limit, 1), 500))}

    @app.websocket("/v1/events/ws")
    async def event_socket(socket: WebSocket) -> None:
        configured = read_secret(settings.server.admin_token_env)
        authorization = socket.headers.get("authorization")
        token = authorization.removeprefix("Bearer ").strip() if authorization else ""
        if not configured or not secrets.compare_digest(token, configured):
            await socket.close(code=1008, reason="invalid admin token")
            return
        await hub.connect(socket)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(socket)

    @app.get("/v1/media", dependencies=[Depends(require_admin)])
    async def media_status() -> Any:
        try:
            return await integrations.music_assistant("players/all", {})
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

    @app.get("/v1/media/state", dependencies=[Depends(require_admin)])
    async def media_state(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return await media_states.snapshot()

    @app.get(
        "/v1/integrations/diagnostics",
        dependencies=[Depends(require_admin)],
    )
    async def integration_diagnostics() -> dict[str, Any]:
        diagnostics = await integrations.diagnostics()
        diagnostics["tts"] = local_tts.status()
        return {"integrations": diagnostics}

    @app.post("/v1/media/search", dependencies=[Depends(require_admin)])
    async def media_search(request: MediaSearch) -> Any:
        args: dict[str, Any] = {
            "search_query": request.query,
            "limit": request.limit,
            "library_only": request.library_only,
        }
        if request.media_types:
            args["media_types"] = request.media_types
        try:
            return await integrations.music_assistant("music/search", args)
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

    @app.post("/v1/media", dependencies=[Depends(require_admin)])
    async def media(command: MediaCommand) -> Any:
        return await run_media_command(
            command.player_id,
            command.action,
            command.volume,
            command.media_uri,
            command.target_player_id,
            command.source,
        )

    @app.post("/v1/assistant", dependencies=[Depends(require_admin)])
    async def assistant(request: AssistantRequest) -> Any:
        if request.room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        try:
            assistant_result = await conversation_engine.respond(
                request.text,
                request.room_id,
                language=request.language,
                session_id=request.conversation_id,
                device_id=request.device_id,
            )
        except AssistantUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        result = assistant_result.as_dict()
        if request.speak:
            result["speech_delivery"] = await synthesize_room_speech(
                request.room_id,
                assistant_result.response_text,
                request.language,
                request.voice,
                "assistant",
                request.device_id,
                request.volume,
                False,
                request.expires_in_seconds,
                request.retention_seconds,
            )
        return result

    @app.get("/v1/assistant/status", dependencies=[Depends(require_admin)])
    async def assistant_status() -> dict[str, Any]:
        return conversation_engine.status()

    @app.get("/v1/conversations", dependencies=[Depends(require_admin)])
    async def conversations(
        room_id: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        if room_id is not None and room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        try:
            sessions = database.list_conversation_sessions(room_id, status, limit)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
        return {"conversations": sessions}

    @app.get(
        "/v1/conversations/{conversation_id}",
        dependencies=[Depends(require_admin)],
    )
    async def conversation(conversation_id: str) -> dict[str, Any]:
        session = database.get_conversation_session(
            conversation_id,
            include_turns=True,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return session

    @app.delete(
        "/v1/conversations/{conversation_id}",
        dependencies=[Depends(require_admin)],
        status_code=204,
    )
    async def end_conversation(conversation_id: str) -> None:
        if not database.end_conversation_session(conversation_id):
            raise HTTPException(
                status_code=404,
                detail="active conversation not found",
            )

    return app
