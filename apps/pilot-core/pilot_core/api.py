from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .config import Settings
from .integrations import IntegrationRequestFailed, IntegrationUnavailable, Integrations
from .registry import Registry
from .storage import Store


class DeviceRegistration(BaseModel):
    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    room_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    capabilities: list[str] = Field(default_factory=list, max_length=100)


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
    language: str = "en"
    conversation_id: str | None = None


class MediaSearch(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    media_types: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=100)
    library_only: bool = False


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


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="bearer token required")
    return authorization.removeprefix("Bearer ").strip()


def create_app(settings: Settings, store: Store | None = None) -> FastAPI:
    registry = Registry.from_settings(settings)
    owns_store = store is None
    database = store or Store(settings.server.database_path, settings)
    integrations = Integrations(settings.integrations)
    hub = EventHub()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owns_store:
            database.close()

    app = FastAPI(title="Pilot Core", version="0.2.0", lifespan=lifespan)

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        configured = os.environ.get(settings.server.admin_token_env, "")
        if not configured or not secrets.compare_digest(_bearer(authorization), configured):
            raise HTTPException(status_code=401, detail="invalid admin token")

    def require_bootstrap(authorization: str | None = Header(default=None)) -> None:
        configured = os.environ.get(settings.server.bootstrap_token_env, "")
        if not configured or not secrets.compare_digest(_bearer(authorization), configured):
            raise HTTPException(status_code=401, detail="invalid bootstrap token")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> dict[str, Any]:
        return {
            "ready": True,
            "registry_revision": registry.revision,
            "room_count": len(registry.rooms),
            "player_count": len(registry.players),
        }

    @app.get("/v1/rooms", dependencies=[Depends(require_admin)])
    async def rooms() -> dict[str, Any]:
        return {"rooms": registry.list_rooms()}

    @app.get("/v1/rooms/{room_id}", dependencies=[Depends(require_admin)])
    async def room(room_id: str) -> dict[str, Any]:
        if room_id not in registry.rooms:
            raise HTTPException(status_code=404, detail="room not found")
        payload = registry.room_view(room_id)
        payload["focus"] = database.room_focus(room_id)
        return payload

    @app.get("/v1/players", dependencies=[Depends(require_admin)])
    async def players() -> dict[str, Any]:
        return {"players": registry.list_players()}

    @app.get("/v1/players/{player_id}", dependencies=[Depends(require_admin)])
    async def player(player_id: str) -> dict[str, Any]:
        if player_id not in registry.players:
            raise HTTPException(status_code=404, detail="player not found")
        return registry.players[player_id].as_dict()

    @app.get("/v1/devices", dependencies=[Depends(require_admin)])
    async def devices() -> dict[str, Any]:
        return {"devices": database.list_devices()}

    @app.post("/v1/devices/register", dependencies=[Depends(require_bootstrap)])
    async def register(request: DeviceRegistration) -> dict[str, str]:
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
        configured = os.environ.get(settings.server.admin_token_env, "")
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
        player = registry.players.get(command.player_id)
        if not player:
            raise HTTPException(status_code=404, detail="player not found")
        external_id = player.external_id or player.id
        command_map = {
            "play": ("players/cmd/play", {"player_id": external_id}),
            "pause": ("players/cmd/pause", {"player_id": external_id}),
            "stop": ("players/cmd/stop", {"player_id": external_id}),
            "set_volume": (
                "players/cmd/volume_set",
                {"player_id": external_id, "volume_level": command.volume},
            ),
            "play_media": (
                "player_queues/play_media",
                {"queue_id": external_id, "media": command.media_uri},
            ),
            "transfer": (
                "player_queues/transfer",
                {
                    "source_queue_id": external_id,
                    "target_queue_id": (
                        registry.players[command.target_player_id].external_id
                        or command.target_player_id
                        if command.target_player_id in registry.players
                        else command.target_player_id
                    ),
                    "auto_play": True,
                },
            ),
        }
        if command.action not in command_map:
            raise HTTPException(status_code=422, detail="unsupported media action")
        if command.action == "set_volume" and command.volume is None:
            raise HTTPException(status_code=422, detail="volume is required")
        if command.action == "play_media" and not command.media_uri:
            raise HTTPException(status_code=422, detail="media_uri is required")
        if command.action == "transfer" and not command.target_player_id:
            raise HTTPException(status_code=422, detail="target_player_id is required")
        rpc_command, args = command_map[command.action]
        try:
            return await integrations.music_assistant(rpc_command, args)
        except IntegrationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
        except IntegrationRequestFailed as error:
            raise HTTPException(status_code=502, detail=str(error)) from None

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
        return {"room_id": request.room_id, "result": response}

    return app
