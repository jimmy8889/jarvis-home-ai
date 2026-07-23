from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse

import websockets

from .config import IntegrationSettings, Room
from .secret_values import read_secret


CommandSender = Callable[[str, dict[str, Any], int], Awaitable[dict[str, Any]]]


def focus_commands(previous: str | None, current: str) -> tuple[dict[str, Any], ...]:
    """Translate Home Assistant satellite state into fail-safe room focus state."""

    if current in {"listening", "processing"}:
        return (
            {"action": "assistant_end"},
            {"action": "start_listening", "ttl_seconds": 45},
        )
    if current == "responding":
        return (
            {"action": "stop_listening"},
            {"action": "assistant_start", "ttl_seconds": 120},
        )
    if previous in {"listening", "processing", "responding"}:
        return (
            {"action": "stop_listening"},
            {"action": "assistant_end"},
        )
    return ()


def _websocket_url(http_url: str) -> str:
    parsed = urlparse(http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))


class AssistFocusBridge:
    """Subscribe to HA state changes and forward bounded focus commands to rooms."""

    def __init__(
        self,
        integrations: IntegrationSettings,
        rooms: tuple[Room, ...],
        sender: CommandSender,
    ) -> None:
        self.integrations = integrations
        self.entity_rooms = {
            room.assist_satellite_entity_id: room
            for room in rooms
            if room.assist_satellite_entity_id and room.default_device_id
        }
        self.sender = sender
        self.stop_event = asyncio.Event()
        self.last_states: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(
            self.entity_rooms
            and self.integrations.home_assistant_url
            and read_secret(self.integrations.home_assistant_token_env)
        )

    async def stop(self) -> None:
        self.stop_event.set()

    async def run(self) -> None:
        if not self.enabled:
            return
        delay = 1.0
        while not self.stop_event.is_set():
            try:
                await self._connected()
                delay = 1.0
            except (OSError, ValueError, websockets.WebSocketException) as error:
                print(f"pilot-core: assist focus bridge reconnecting: {error}", flush=True)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 30)

    async def _connected(self) -> None:
        token = read_secret(self.integrations.home_assistant_token_env)
        if not token:
            return
        async with websockets.connect(
            _websocket_url(self.integrations.home_assistant_url),
            open_timeout=10,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=1_000_000,
        ) as socket:
            hello = json.loads(await socket.recv())
            if hello.get("type") != "auth_required":
                raise ValueError("unexpected Home Assistant WebSocket greeting")
            await socket.send(json.dumps({"type": "auth", "access_token": token}))
            auth = json.loads(await socket.recv())
            if auth.get("type") != "auth_ok":
                raise ValueError("Home Assistant WebSocket authentication failed")
            await socket.send(
                json.dumps(
                    {
                        "id": 1,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }
                )
            )
            subscribed = json.loads(await socket.recv())
            if subscribed.get("type") != "result" or not subscribed.get("success"):
                raise ValueError("Home Assistant state subscription failed")
            while not self.stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=5)
                except TimeoutError:
                    continue
                await self.handle_message(json.loads(raw))

    async def handle_message(self, message: dict[str, Any]) -> None:
        event = message.get("event") or {}
        data = event.get("data") or {}
        entity_id = data.get("entity_id")
        room = self.entity_rooms.get(entity_id)
        if room is None:
            return
        new_state = data.get("new_state") or {}
        current = str(new_state.get("state") or "unavailable").casefold()
        previous = self.last_states.get(entity_id)
        if current == previous:
            return
        self.last_states[entity_id] = current
        for command in focus_commands(previous, current):
            try:
                await self.sender(room.default_device_id, command, 30)
            except Exception as error:
                print(
                    f"pilot-core: focus command failed for {room.id}: {error}",
                    flush=True,
                )
