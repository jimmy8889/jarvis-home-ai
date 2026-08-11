from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import json
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect as websocket_connect


class HomeAssistantClient:
    def __init__(
        self,
        base_url: str,
        token_file: Path,
        timeout: float = 20.0,
        websocket_factory: Any | None = None,
    ):
        token = token_file.read_text().strip()
        if not token:
            raise RuntimeError(f"Home Assistant token file is empty: {token_file}")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._websocket_factory = websocket_factory or websocket_connect
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def states(self) -> list[dict[str, Any]]:
        response = await self._client.get("/api/states")
        response.raise_for_status()
        return response.json()

    async def publish_state(self, entity_id: str, state: str | float, attributes: dict[str, Any]) -> None:
        response = await self._client.post(
            f"/api/states/{entity_id}",
            json={"state": state, "attributes": attributes},
        )
        response.raise_for_status()

    async def state_changes(
        self,
        entity_ids: set[str],
        on_subscribed: Callable[[], None] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield allowlisted HA state changes over its authenticated WebSocket."""
        if not entity_ids:
            raise ValueError("at least one Home Assistant entity is required")
        base = httpx.URL(self._base_url)
        if base.scheme not in {"http", "https"} or not base.host:
            raise ValueError("Home Assistant URL is invalid")
        websocket_url = base.copy_with(
            scheme="wss" if base.scheme == "https" else "ws",
            path="/api/websocket",
            query=None,
            fragment=None,
        )
        async with self._websocket_factory(
            str(websocket_url),
            open_timeout=10,
            close_timeout=5,
            max_size=4_000_000,
            ping_interval=20,
            ping_timeout=20,
        ) as socket:
            required = await self._receive_json(socket, timeout=10)
            if required.get("type") != "auth_required":
                raise RuntimeError("Home Assistant did not request WebSocket authentication")
            await socket.send(json.dumps(
                {"type": "auth", "access_token": self._token},
                separators=(",", ":"),
            ))
            authenticated = await self._receive_json(socket, timeout=10)
            if authenticated.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant WebSocket authentication failed")
            await socket.send(json.dumps(
                {"id": 1, "type": "subscribe_events", "event_type": "state_changed"},
                separators=(",", ":"),
            ))
            subscribed = await self._receive_json(socket, timeout=10)
            if (
                subscribed.get("type") != "result"
                or subscribed.get("id") != 1
                or subscribed.get("success") is not True
            ):
                raise RuntimeError("Home Assistant state subscription failed")
            if on_subscribed:
                on_subscribed()
            while True:
                payload = await self._receive_json(socket)
                if payload.get("type") != "event":
                    continue
                event = payload.get("event", {})
                data = event.get("data", {}) if isinstance(event, dict) else {}
                entity_id = data.get("entity_id") if isinstance(data, dict) else None
                if entity_id not in entity_ids:
                    continue
                old_state = data.get("old_state")
                new_state = data.get("new_state")
                if not isinstance(new_state, dict):
                    continue
                yield {
                    "entity_id": entity_id,
                    "old_state": old_state if isinstance(old_state, dict) else None,
                    "new_state": new_state,
                    "time_fired": event.get("time_fired"),
                }

    @staticmethod
    async def _receive_json(socket: Any, timeout: float | None = None) -> dict[str, Any]:
        receive = socket.recv()
        message = await asyncio.wait_for(receive, timeout=timeout) if timeout else await receive
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        if not isinstance(message, str) or len(message) > 4_000_000:
            raise ValueError("Home Assistant WebSocket message is invalid")
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise ValueError("Home Assistant WebSocket payload is not an object")
        return payload
