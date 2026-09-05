from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import httpx
from websockets.asyncio.client import connect

from .config import ENTITY, Settings
from .optimizer import build_plan


class Coordinator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.token = settings.ha_token_file.read_text().strip()
        if not self.token:
            raise RuntimeError("Home Assistant token is empty")
        self.http = httpx.AsyncClient(base_url=settings.ha_url, headers={"Authorization": f"Bearer {self.token}"}, timeout=20)
        self.last_plan: dict[str, Any] | None = None
        self.last_success: str | None = None
        self.last_error: str | None = None
        self.stream_connected = False
        self._closed = False
        self._lock = asyncio.Lock()

    async def close(self):
        self._closed = True
        await self.http.aclose()

    async def _states(self) -> dict[str, dict[str, Any]]:
        response = await self.http.get("/api/states")
        response.raise_for_status()
        return {s["entity_id"]: s for s in response.json()}

    def _load_samples(self) -> list[float]:
        path = self.settings.data_dir / "load-samples.json"
        try:
            data = json.loads(path.read_text())
            return [float(x) for x in data if float(x) >= 0]
        except (OSError, ValueError, TypeError):
            return []

    async def run_once(self):
        async with self._lock:
            states = await self._states()
            plan = build_plan(states, self.settings, load_samples_kwh=self._load_samples())
            response = await self.http.post(self.settings.nodered_plan_url, json=plan)
            response.raise_for_status()
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.settings.data_dir / f"latest-plan.{plan['plan_id']}.tmp"
            tmp.write_text(json.dumps(plan, indent=2))
            tmp.replace(self.settings.data_dir / "latest-plan.json")
            self.last_plan = plan
            self.last_success = datetime.now(timezone.utc).isoformat()
            self.last_error = None

    async def _stream(self):
        ws_url = self.settings.ha_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/api/websocket"
        watched = {ENTITY["amber_fit"], ENTITY["amber_import"], ENTITY["buy_floor"], ENTITY["sell_floor"], ENTITY["enabled"], ENTITY["manual_mode"], ENTITY["manual_rate"]}
        while not self._closed:
            try:
                async with connect(ws_url, ping_interval=20, ping_timeout=20) as socket:
                    await socket.recv()
                    await socket.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth = json.loads(await socket.recv())
                    if auth.get("type") != "auth_ok": raise RuntimeError("HA websocket auth failed")
                    await socket.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                    await socket.recv()
                    self.stream_connected = True
                    async for raw in socket:
                        event = json.loads(raw)
                        entity = event.get("event", {}).get("data", {}).get("entity_id")
                        if entity in watched:
                            await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.stream_connected = False
                self.last_error = f"stream: {type(exc).__name__}: {exc}"
                await asyncio.sleep(2)

    async def run_forever(self):
        stream = asyncio.create_task(self._stream())
        try:
            while not self._closed:
                try:
                    await self.run_once()
                except Exception as exc:
                    self.last_error = f"planner: {type(exc).__name__}: {exc}"
                await asyncio.sleep(self.settings.interval_seconds)
        finally:
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)

    def health(self):
        return {"status": "ok" if self.last_plan else "starting", "last_success": self.last_success, "last_error": self.last_error, "ha_stream_connected": self.stream_connected, "plan_id": self.last_plan.get("plan_id") if self.last_plan else None}
