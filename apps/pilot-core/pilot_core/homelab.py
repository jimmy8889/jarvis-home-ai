from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import math
import ssl
import secrets
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from websockets.asyncio.client import connect as websocket_connect

from .config import IntegrationSettings
from .secret_values import read_secret


class HomeLabProviderError(RuntimeError):
    pass


def _ratio(value: Any, maximum: Any) -> float | None:
    try:
        numerator = float(value)
        denominator = float(maximum)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator <= 0:
        return None
    return max(0.0, min(numerator / denominator, 1.0))


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class ProxmoxMonitor:
    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.proxmox_url
            and self.settings.proxmox_token_id
            and read_secret(self.settings.proxmox_token_secret_env)
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = read_secret(self.settings.proxmox_token_secret_env)
        if not self.settings.proxmox_url or not self.settings.proxmox_token_id or not token:
            raise HomeLabProviderError("Proxmox monitoring is not configured")
        try:
            async with httpx.AsyncClient(
                timeout=10,
                transport=self.transport,
                verify=self.settings.proxmox_verify_tls,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{self.settings.proxmox_url}/api2/json{path}",
                    params=params,
                    headers={
                        "Authorization": (
                            "PVEAPIToken="
                            f"{self.settings.proxmox_token_id}={token}"
                        )
                    },
                )
                response.raise_for_status()
                if len(response.content) > 8_000_000:
                    raise ValueError("Proxmox response is too large")
                payload = response.json()
                if not isinstance(payload, dict) or "data" not in payload:
                    raise ValueError("Proxmox response is invalid")
                return payload["data"]
        except (httpx.HTTPError, ValueError) as error:
            raise HomeLabProviderError("Proxmox is unavailable") from error

    async def _post(self, path: str, data: dict[str, Any]) -> Any:
        token = read_secret(self.settings.proxmox_migration_token_secret_env)
        if not self.settings.proxmox_url or not self.settings.proxmox_migration_token_id or not token:
            raise HomeLabProviderError("Proxmox migration is not configured")
        try:
            async with httpx.AsyncClient(timeout=30, verify=self.settings.proxmox_verify_tls) as client:
                response = await client.post(
                    f"{self.settings.proxmox_url}/api2/json{path}", data=data,
                    headers={"Authorization": f"PVEAPIToken={self.settings.proxmox_migration_token_id}={token}"},
                )
                response.raise_for_status()
                return response.json().get("data")
        except (httpx.HTTPError, ValueError) as error:
            raise HomeLabProviderError("Proxmox migration request failed") from error

    async def node_detail(self, node: str) -> dict[str, Any]:
        status = await self._get(f"/nodes/{node}/status")
        if not isinstance(status, dict):
            raise HomeLabProviderError("Proxmox returned invalid node detail")
        return {"node": node, "status": status}

    async def workload_detail(self, node: str, kind: str, vmid: int) -> dict[str, Any]:
        if kind not in {"qemu", "lxc"}:
            raise HomeLabProviderError("Unsupported workload kind")
        current, config = await asyncio.gather(
            self._get(f"/nodes/{node}/{kind}/{vmid}/status/current"),
            self._get(f"/nodes/{node}/{kind}/{vmid}/config"),
        )
        return {"node": node, "kind": kind, "vmid": vmid, "status": current, "config": config}

    async def migrate(self, node: str, kind: str, vmid: int, target: str, online: bool) -> Any:
        if kind not in {"qemu", "lxc"}:
            raise HomeLabProviderError("Unsupported workload kind")
        data: dict[str, Any] = {"target": target}
        if kind == "qemu":
            data["online"] = 1 if online else 0
        elif online:
            data["restart"] = 1
        return await self._post(f"/nodes/{node}/{kind}/{vmid}/migrate", data)

    async def snapshot(self) -> dict[str, Any]:
        cluster, resources = await asyncio.gather(
            self._get("/cluster/status"),
            self._get("/cluster/resources"),
        )
        if not isinstance(cluster, list) or not isinstance(resources, list):
            raise HomeLabProviderError("Proxmox returned an invalid snapshot")
        cluster_row = next(
            (row for row in cluster if isinstance(row, dict) and row.get("type") == "cluster"),
            {},
        )
        nodes = []
        workloads = []
        storages = []
        for item in resources:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type", ""))
            if kind == "node":
                nodes.append(
                    {
                        "id": str(item.get("node") or item.get("id") or "unknown"),
                        "name": str(item.get("node") or "Unknown node"),
                        "status": str(item.get("status") or "unknown"),
                        "cpu_ratio": _number(item.get("cpu")),
                        "cpu_threads": item.get("maxcpu"),
                        "memory_used_bytes": item.get("mem"),
                        "memory_total_bytes": item.get("maxmem"),
                        "memory_ratio": _ratio(item.get("mem"), item.get("maxmem")),
                        "disk_used_bytes": item.get("disk"),
                        "disk_total_bytes": item.get("maxdisk"),
                        "disk_ratio": _ratio(item.get("disk"), item.get("maxdisk")),
                        "uptime_seconds": item.get("uptime"),
                        "disk_read_bytes": item.get("diskread"),
                        "disk_write_bytes": item.get("diskwrite"),
                        "network_in_bytes": item.get("netin"),
                        "network_out_bytes": item.get("netout"),
                        "tags": str(item.get("tags") or "").split(";") if item.get("tags") else [],
                    }
                )
            elif kind in {"qemu", "lxc"}:
                workloads.append(
                    {
                        "id": str(item.get("id") or ""),
                        "vmid": item.get("vmid"),
                        "name": str(item.get("name") or f"VM {item.get('vmid', '?')}"),
                        "kind": kind,
                        "node": str(item.get("node") or ""),
                        "status": str(item.get("status") or "unknown"),
                        "cpu_ratio": _number(item.get("cpu")),
                        "memory_ratio": _ratio(item.get("mem"), item.get("maxmem")),
                        "memory_used_bytes": item.get("mem"),
                        "memory_total_bytes": item.get("maxmem"),
                        "uptime_seconds": item.get("uptime"),
                    }
                )
            elif kind == "storage":
                storages.append(
                    {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("storage") or "Storage"),
                        "node": str(item.get("node") or ""),
                        "status": str(item.get("status") or "unknown"),
                        "used_bytes": item.get("disk"),
                        "total_bytes": item.get("maxdisk"),
                        "usage_ratio": _ratio(item.get("disk"), item.get("maxdisk")),
                    }
                )
        return {
            "configured": True,
            "status": "ok",
            "cluster": {
                "name": str(cluster_row.get("name") or "Proxmox"),
                "quorate": bool(cluster_row.get("quorate", 0)),
                "expected_nodes": cluster_row.get("nodes"),
            },
            "nodes": sorted(nodes, key=lambda row: row["name"]),
            "workloads": sorted(workloads, key=lambda row: (row["node"], row["name"])),
            "storages": sorted(storages, key=lambda row: (row["node"], row["name"])),
        }


class TrueNASMonitor:
    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        websocket_factory: Any | None = None,
    ) -> None:
        self.settings = settings
        self.websocket_factory = websocket_factory or websocket_connect

    @property
    def configured(self) -> bool:
        return bool(self.settings.truenas_url and read_secret(self.settings.truenas_token_env))

    def _websocket_url(self) -> str:
        parsed = urlparse(self.settings.truenas_url)
        scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/current", "", "", ""))

    async def snapshot(self) -> dict[str, Any]:
        token = read_secret(self.settings.truenas_token_env)
        if not self.settings.truenas_url or not token:
            raise HomeLabProviderError("TrueNAS monitoring is not configured")
        if not self._websocket_url().startswith("wss://"):
            raise HomeLabProviderError(
                "TrueNAS API keys require encrypted WSS transport"
            )
        ssl_context: ssl.SSLContext | bool | None = None
        if self._websocket_url().startswith("wss://") and not self.settings.truenas_verify_tls:
            ssl_context = ssl._create_unverified_context()
        try:
            async with self.websocket_factory(
                self._websocket_url(),
                open_timeout=10,
                close_timeout=2,
                max_size=8_000_000,
                ssl=ssl_context,
            ) as socket:
                authenticated = await self._call(
                    socket, 1, "auth.login_with_api_key", [token]
                )
                if authenticated is not True:
                    raise HomeLabProviderError(
                        "TrueNAS rejected the configured API key"
                    )
                system = await self._call(socket, 2, "system.info", [])
                pools = await self._call(socket, 3, "pool.query", [[], {}])
                disks = await self._call(socket, 4, "disk.query", [[], {}])
                names = [
                    str(item.get("name"))
                    for item in disks
                    if isinstance(item, dict) and item.get("name")
                ]
                temperatures = await self._optional_call(
                    socket, 5, "disk.temperatures", [names, True], {}
                )
                alerts = await self._optional_call(socket, 6, "alert.list", [], [])
        except (OSError, TimeoutError, ValueError, TypeError) as error:
            raise HomeLabProviderError("TrueNAS is unavailable") from error
        return self._normalize(system, pools, disks, temperatures, alerts)

    @staticmethod
    async def _call(socket: Any, identifier: int, method: str, params: list[Any]) -> Any:
        await socket.send(
            json.dumps(
                {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
            )
        )
        while True:
            message = json.loads(await socket.recv())
            if message.get("id") != identifier:
                continue
            if "error" in message:
                raise ValueError(f"TrueNAS method {method} failed")
            return message.get("result")

    @classmethod
    async def _optional_call(
        cls,
        socket: Any,
        identifier: int,
        method: str,
        params: list[Any],
        fallback: Any,
    ) -> Any:
        try:
            return await cls._call(socket, identifier, method, params)
        except ValueError:
            return fallback

    @staticmethod
    def _normalize(
        system: Any,
        pools: Any,
        disks: Any,
        temperatures: Any,
        alerts: Any,
    ) -> dict[str, Any]:
        system = system if isinstance(system, dict) else {}
        pools = pools if isinstance(pools, list) else []
        disks = disks if isinstance(disks, list) else []
        temperatures = temperatures if isinstance(temperatures, dict) else {}
        normalized_pools = []
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            normalized_pools.append(
                {
                    "id": str(pool.get("id") or pool.get("name") or "pool"),
                    "name": str(pool.get("name") or "Pool"),
                    "status": str(pool.get("status") or "unknown"),
                    "healthy": pool.get("healthy"),
                    "warning": pool.get("warning"),
                    "size_bytes": pool.get("size"),
                    "allocated_bytes": pool.get("allocated"),
                    "free_bytes": pool.get("free"),
                    "usage_ratio": _ratio(pool.get("allocated"), pool.get("size")),
                    "scan": pool.get("scan"),
                }
            )
        normalized_disks = []
        for disk in disks:
            if not isinstance(disk, dict):
                continue
            name = str(disk.get("name") or disk.get("devname") or "disk")
            temperature = temperatures.get(name)
            if isinstance(temperature, dict):
                temperature_c = _number(
                    temperature.get("temperature") or temperature.get("current")
                )
                critical_c = _number(
                    temperature.get("critical") or temperature.get("critical_temperature")
                )
            elif isinstance(temperature, (list, tuple)):
                temperature_c = _number(temperature[0]) if temperature else None
                critical_c = _number(temperature[1]) if len(temperature) > 1 else None
            else:
                temperature_c = _number(temperature)
                critical_c = None
            normalized_disks.append(
                {
                    "id": str(disk.get("identifier") or disk.get("serial") or name),
                    "name": name,
                    "model": str(disk.get("model") or "Unknown disk"),
                    "serial": str(disk.get("serial") or ""),
                    "size_bytes": disk.get("size"),
                    "pool": disk.get("pool"),
                    "type": disk.get("type"),
                    "rotation_rate": disk.get("rotationrate"),
                    "smart_enabled": disk.get("togglesmart"),
                    "smart_options": disk.get("smartoptions"),
                    "temperature_c": temperature_c,
                    "critical_temperature_c": critical_c,
                }
            )
        active_alerts = [
            {
                "id": str(alert.get("uuid") or alert.get("id") or index),
                "level": str(alert.get("level") or "warning").lower(),
                "title": str(alert.get("formatted") or alert.get("klass") or "TrueNAS alert")[:500],
                "datetime": alert.get("datetime"),
            }
            for index, alert in enumerate(alerts if isinstance(alerts, list) else [])
            if isinstance(alert, dict) and not alert.get("dismissed")
        ]
        return {
            "configured": True,
            "status": "ok" if all(pool.get("healthy") is not False for pool in normalized_pools) else "degraded",
            "system": {
                "hostname": str(system.get("hostname") or "TrueNAS"),
                "version": str(system.get("version") or ""),
                "uptime_seconds": system.get("uptime_seconds"),
                "model": str(system.get("system_product") or system.get("model") or ""),
                "memory_total_bytes": system.get("physmem"),
                "cpu_model": str(system.get("model") or system.get("cpu_model") or ""),
                "cpu_cores": system.get("cores"),
            },
            "pools": sorted(normalized_pools, key=lambda row: row["name"]),
            "disks": sorted(normalized_disks, key=lambda row: row["name"]),
            "alerts": active_alerts[:100],
        }


class HomeLabService:
    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        proxmox: ProxmoxMonitor | None = None,
        truenas: TrueNASMonitor | None = None,
    ) -> None:
        self.settings = settings
        self.proxmox = proxmox or ProxmoxMonitor(settings)
        self.truenas = truenas or TrueNASMonitor(settings)
        self._cached: dict[str, Any] | None = None
        self._cached_monotonic = 0.0
        self._lock = asyncio.Lock()
        self._agents: dict[str, dict[str, Any]] = {}
        self._migrations: dict[str, dict[str, Any]] = {}

    async def node_detail(self, node: str) -> dict[str, Any]:
        detail = await self.proxmox.node_detail(node)
        detail["agent"] = next(
            (agent for agent in self._agents.values() if agent.get("hostname") == node), None
        )
        return detail

    async def workload_detail(self, node: str, kind: str, vmid: int) -> dict[str, Any]:
        return await self.proxmox.workload_detail(node, kind, vmid)

    async def prepare_migration(
        self, *, device_id: str, node: str, kind: str, vmid: int, target: str, online: bool
    ) -> dict[str, Any]:
        snapshot = await self.snapshot(force=True)
        nodes = {item["name"]: item for item in snapshot["providers"]["proxmox"]["nodes"]}
        workload = next(
            (item for item in snapshot["providers"]["proxmox"]["workloads"] if item.get("vmid") == vmid and item.get("kind") == kind and item.get("node") == node), None
        )
        if workload is None or target not in nodes or nodes[target].get("status") != "online" or target == node:
            raise HomeLabProviderError("Migration source or target is not eligible")
        detail = await self.proxmox.workload_detail(node, kind, vmid)
        config = detail.get("config") or {}
        locked = config.get("lock")
        disk_values = [
            value for key, value in config.items()
            if key.startswith(("scsi", "sata", "virtio", "ide", "rootfs", "mp"))
            and isinstance(value, str) and ":" in value
        ]
        storage_names = {value.split(":", 1)[0] for value in disk_values}
        storage_rows = await self.proxmox._get("/storage")
        definitions = {
            str(item.get("storage")): item
            for item in storage_rows if isinstance(item, dict) and item.get("storage")
        }
        unsafe_storage = []
        for name in sorted(storage_names):
            definition = definitions.get(name) or {}
            allowed_nodes = {
                value.strip() for value in str(definition.get("nodes") or "").split(",")
                if value.strip()
            }
            if not bool(definition.get("shared")) or (allowed_nodes and target not in allowed_nodes):
                unsafe_storage.append(name)
        if locked or unsafe_storage:
            reason = (
                "workload is locked" if locked
                else f"storage is not shared with {target}: {', '.join(unsafe_storage)}"
            )
            raise HomeLabProviderError(f"Migration is not safe: {reason}")
        migration_id = secrets.token_urlsafe(18)
        expires_at = time.monotonic() + 120
        self._migrations[migration_id] = {
            "device_id": device_id, "node": node, "kind": kind, "vmid": vmid,
            "target": target, "online": online, "expires": expires_at,
        }
        return {
            "id": migration_id, "status": "confirmation_required", "workload": workload,
            "source_node": node, "target_node": target, "online": online,
            "expires_in_seconds": 120,
        }

    async def confirm_migration(self, migration_id: str, device_id: str) -> dict[str, Any]:
        request = self._migrations.pop(migration_id, None)
        if request is None or request["device_id"] != device_id or request["expires"] < time.monotonic():
            raise HomeLabProviderError("Migration confirmation is invalid or expired")
        upid = await self.proxmox.migrate(
            request["node"], request["kind"], request["vmid"], request["target"], request["online"]
        )
        self._cached = None
        return {"id": migration_id, "status": "accepted", "task": upid, **{k: v for k, v in request.items() if k != "expires"}}

    @property
    def configured(self) -> bool:
        return self.proxmox.configured or self.truenas.configured or bool(self._agents)

    def update_agent(self, device_id: str, payload: dict[str, Any]) -> None:
        self._agents[device_id] = {
            **payload,
            "device_id": device_id,
            "received_at": datetime.now(UTC).isoformat(),
            "received_monotonic": time.monotonic(),
        }
        self._cached = None

    async def snapshot(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if (
            not force
            and self._cached is not None
            and now - self._cached_monotonic < self.settings.homelab_cache_seconds
        ):
            return self._cached
        async with self._lock:
            now = time.monotonic()
            if (
                not force
                and self._cached is not None
                and now - self._cached_monotonic < self.settings.homelab_cache_seconds
            ):
                return self._cached
            previous = self._cached
            proxmox, truenas = await asyncio.gather(
                self._provider_snapshot(self.proxmox, "proxmox"),
                self._provider_snapshot(self.truenas, "truenas"),
            )
            agents = []
            for device_id, agent in sorted(self._agents.items()):
                age = max(0, now - float(agent.get("received_monotonic", now)))
                agents.append(
                    {
                        key: value
                        for key, value in agent.items()
                        if key != "received_monotonic"
                    }
                    | {"stale": age > 45, "age_seconds": round(age, 1)}
                )
            snapshot = self._compose(proxmox, truenas, agents)
            if snapshot["status"] == "unavailable" and previous is not None:
                snapshot = {
                    **previous,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "status": "stale",
                    "stale": True,
                    "providers": snapshot["providers"],
                }
            self._cached = snapshot
            self._cached_monotonic = now
            return snapshot

    @staticmethod
    async def _provider_snapshot(provider: Any, name: str) -> dict[str, Any]:
        empty = (
            {"cluster": None, "nodes": [], "workloads": [], "storages": []}
            if name == "proxmox"
            else {"system": None, "pools": [], "disks": [], "alerts": []}
        )
        if not provider.configured:
            return {"configured": False, "status": "not_configured", **empty}
        try:
            return await provider.snapshot()
        except HomeLabProviderError as error:
            return {
                "configured": True,
                "status": "error",
                "error": str(error),
                "provider": name,
                **empty,
            }

    @staticmethod
    def _compose(
        proxmox: dict[str, Any],
        truenas: dict[str, Any],
        agents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        providers = {"proxmox": proxmox, "truenas": truenas}
        configured = [item for item in providers.values() if item.get("configured")]
        provider_errors = sum(item.get("status") == "error" for item in configured)
        nodes = list(proxmox.get("nodes") or [])
        online_nodes = sum(node.get("status") == "online" for node in nodes)
        workloads = list(proxmox.get("workloads") or [])
        running_workloads = sum(item.get("status") == "running" for item in workloads)
        disks = list(truenas.get("disks") or [])
        temperatures = [
            value
            for value in (_number(item.get("temperature_c")) for item in disks)
            if value is not None
        ]
        for agent in agents:
            for gpu in agent.get("gpus") or []:
                value = _number(gpu.get("temperature_c"))
                if value is not None:
                    temperatures.append(value)
            for sensor in agent.get("temperatures") or []:
                value = _number(sensor.get("temperature_c"))
                if value is not None:
                    temperatures.append(value)
        if not configured and not agents:
            status = "unavailable"
        elif provider_errors or any(node.get("status") != "online" for node in nodes):
            status = "degraded"
        else:
            status = "healthy"
        return {
            "schema_version": "pilot.homelab.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "stale": False,
            "summary": {
                "node_count": len(nodes),
                "online_node_count": online_nodes,
                "workload_count": len(workloads),
                "running_workload_count": running_workloads,
                "pool_count": len(truenas.get("pools") or []),
                "disk_count": len(disks),
                "active_alert_count": len(truenas.get("alerts") or []),
                "hottest_temperature_c": max(temperatures) if temperatures else None,
            },
            "providers": providers,
            "agents": agents,
        }
