from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import aiohttp

from .config import Settings


NODE_ORDER = ("pvebackup", "pvedell", "pve3080")


class NodeShutdownCoordinator:
    """Orderly physical-node signalling only; no guest or power-cut API exists."""

    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session
        self.signalled: set[tuple[str, str]] = set()

    async def arm_recovery(self, epoch: str) -> dict[str, Any]:
        secret = self.settings.secret("recovery_hmac")
        if not secret:
            raise RuntimeError("recovery_hmac secret is missing")
        timestamp = str(int(time.time()))
        body = json.dumps({"epoch": epoch}, separators=(",", ":")).encode()
        signature = hmac.new(secret.encode(), timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
        async with self.session.post(
            self.settings.recovery_companion_url.rstrip("/") + "/v1/arm",
            data=body,
            headers={"Content-Type": "application/json", "X-Energy-Timestamp": timestamp, "X-Energy-Signature": signature},
        ) as response:
            if response.status >= 300:
                raise RuntimeError(f"recovery companion rejected arm: HTTP {response.status}")
            return await response.json()

    async def signal_nodes(self, epoch: str) -> dict[str, str]:
        if not self.settings.resilience_shutdown_enabled:
            return {node: "disabled_pending_maintenance_window" for node in NODE_ORDER}
        token = self.settings.secret("proxmox_shutdown_token")
        if not token:
            raise RuntimeError("proxmox_shutdown_token secret is missing")
        results: dict[str, str] = {}
        for node in NODE_ORDER:
            key = (epoch, node)
            if key in self.signalled:
                results[node] = "already_signalled"
                continue
            url = f"https://{node}:8006/api2/json/nodes/{node}/status"
            error = "unknown"
            for attempt in range(2):
                try:
                    async with self.session.post(
                        url,
                        data={"command": "shutdown"},
                        headers={"Authorization": f"PVEAPIToken={token}"},
                        ssl=False,
                    ) as response:
                        if response.status < 300:
                            self.signalled.add(key)
                            results[node] = "accepted"
                            break
                        error = f"HTTP {response.status}"
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                if attempt == 1:
                    results[node] = f"failed: {error}"
        return results
