from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, model_validator

from . import __version__
from .audio_assets import AudioAssetError, AudioAssets
from .config import Settings
from .integrations import IntegrationRequestFailed, IntegrationUnavailable, Integrations
from .media_state import MediaStateReader
from .orchestration import ResolutionError, RoomOrchestrator
from .registry import Registry
from .secret_values import read_secret
from .storage import Store
from .tts import LocalTTS, TTSRequestFailed, TTSUnavailable


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    room_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=100)


class BootstrapGrantRequest(DeviceRegistration):
    expires_in_seconds: int = Field(default=600, ge=60, le=3600)


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
        return self.model_dump(
            exclude={"expires_in_seconds"}, exclude_none=True
        )


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
        "play", "pause", "stop", "set_volume", "play_media", "transfer"
    ]
    player_id: str | None = None
    media_uri: str | None = None
    target_room_id: str | None = None
    target_player_id: str | None = None
    volume: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "RoomMediaCommand":
        if self.action == "set_volume" and self.volume is None:
            raise ValueError("volume is required for set_volume")
        if self.action == "play_media" and not self.media_uri:
            raise ValueError("media_uri is required for play_media")
        if self.action == "transfer" and not self.target_room_id:
            raise ValueError("target_room_id is required for transfer")
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
    local_tts = LocalTTS(
        settings.integrations, settings.server.audio_asset_max_bytes
    )
    hub = EventHub()
    device_hub = DeviceHub()
    dashboard_directory = Path(__file__).with_name("dashboard")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
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

    async def queue_device_command(
        device_id: str, payload: dict[str, Any], expires_in_seconds: int
    ) -> dict[str, Any]:
        try:
            command = database.create_command(
                device_id, payload, expires_in_seconds
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="device not found") from None
        if await device_hub.send(
            device_id, {"type": "command", "command": command}
        ):
            database.mark_command_delivered(command["id"], device_id)
            command = database.get_command(command["id"]) or command
        return command

    async def audio_targets(
        room_id: str, device_id: str | None
    ) -> tuple[Any, Any]:
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
        command = await queue_device_command(
            target.id, payload, expires_in_seconds
        )
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

    def assistant_speech(result: Any) -> str | None:
        try:
            speech = result["response"]["speech"]["plain"]["speech"]
        except (KeyError, TypeError):
            return None
        return speech.strip() if isinstance(speech, str) and speech.strip() else None

    async def run_media_command(
        player_id: str,
        action: str,
        volume: int | None = None,
        media_uri: str | None = None,
        target_player_id: str | None = None,
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
        if not configured or not secrets.compare_digest(_bearer(authorization), configured):
            raise HTTPException(status_code=401, detail="invalid admin token")

    def require_bootstrap(authorization: str | None = Header(default=None)) -> None:
        if not settings.server.legacy_bootstrap_enabled:
            raise HTTPException(
                status_code=403, detail="legacy bootstrap registration is disabled"
            )
        configured = read_secret(settings.server.bootstrap_token_env)
        if not configured or not secrets.compare_digest(_bearer(authorization), configured):
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
            "legacy_bootstrap_enabled": settings.server.legacy_bootstrap_enabled,
        }

    @app.get("/v1/rooms", dependencies=[Depends(require_admin)])
    async def rooms() -> dict[str, Any]:
        return {"rooms": registry.list_rooms()}

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

    @app.get("/v1/operations", dependencies=[Depends(require_admin)])
    async def operations(response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
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

        return {
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
                    status.get("status") == "ok"
                    for status in configured_integrations
                ),
                "armed_room_count": len(armed_rooms),
                "unarmed_room_count": len(unarmed_rooms),
                "pending_command_count": sum(
                    command_counts.get(status, 0)
                    for status in ("queued", "delivered")
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
        }

    @app.get("/v1/rooms/{room_id}", dependencies=[Depends(require_admin)])
    async def room(room_id: str) -> dict[str, Any]:
        if room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        payload = registry.room_view(room_id)
        payload["focus"] = database.room_focus(room_id)
        return payload

    @app.get(
        "/v1/rooms/{room_id}/state", dependencies=[Depends(require_admin)]
    )
    async def room_state(room_id: str) -> dict[str, Any]:
        try:
            return orchestrator.room_state(
                room_id, await device_hub.connected_ids()
            )
        except ResolutionError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None

    @app.get(
        "/v1/rooms/{room_id}/media-state",
        dependencies=[Depends(require_admin)],
    )
    async def room_media_state(
        room_id: str, response: Response
    ) -> dict[str, Any]:
        if room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        response.headers["Cache-Control"] = "no-store"
        return await media_states.snapshot(room_id)

    @app.post(
        "/v1/rooms/{room_id}/control",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def room_control(
        room_id: str, request: RoomControlInput
    ) -> dict[str, Any]:
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
    async def room_media(
        room_id: str, request: RoomMediaCommand
    ) -> dict[str, Any]:
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
                    raise HTTPException(status_code=413, detail="audio asset is too large")
            except ValueError:
                raise HTTPException(status_code=400, detail="invalid content-length") from None
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
    async def room_audio(
        room_id: str, request: RoomAudioCommand
    ) -> dict[str, Any]:
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
        "/v1/rooms/{room_id}/speak",
        dependencies=[Depends(require_admin)],
        status_code=201,
    )
    async def room_speak(
        room_id: str, request: RoomSpeakRequest
    ) -> dict[str, Any]:
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
    async def player_state(
        player_id: str, response: Response
    ) -> dict[str, Any]:
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
        return {
            "commands": database.list_commands(
                device_id, min(max(limit, 1), 500)
            )
        }

    @app.get(
        "/v1/commands/{command_id}", dependencies=[Depends(require_admin)]
    )
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
        await device_hub.send(
            device_id, {"type": "hello", "device_id": device_id}
        )
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
        )

    @app.post("/v1/assistant", dependencies=[Depends(require_admin)])
    async def assistant(request: AssistantRequest) -> Any:
        if request.room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        try:
            response = await integrations.home_assistant_conversation(
                request.text,
                request.language,
                request.conversation_id,
            )
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None
        result: dict[str, Any] = {"room_id": request.room_id, "result": response}
        if request.speak:
            text = assistant_speech(response)
            if not text:
                raise HTTPException(
                    status_code=502,
                    detail="Home Assistant returned no speakable response",
                )
            result["speech_delivery"] = await synthesize_room_speech(
                request.room_id,
                text,
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

    return app
