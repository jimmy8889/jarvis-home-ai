from __future__ import annotations

import os
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.homelab import HomeLabProviderError, HomeLabService, ProxmoxMonitor, TrueNASMonitor


class FakeProvider:
    def __init__(self, payload: dict | None = None, *, configured: bool = True) -> None:
        self.payload = payload
        self.configured = configured

    async def snapshot(self) -> dict:
        if self.payload is None:
            raise HomeLabProviderError("provider unavailable")
        return self.payload


class HomeLabTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxmox_snapshot_normalizes_cluster_resources(self) -> None:
        os.environ["TEST_PVE_SECRET"] = "secret"

        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                request.headers["Authorization"],
                "PVEAPIToken=pilot-monitor@pve!pilot-core=secret",
            )
            if request.url.path.endswith("/cluster/status"):
                return httpx.Response(
                    200,
                    json={"data": [{"type": "cluster", "name": "James-Home-Lab", "quorate": 1, "nodes": 3}]},
                )
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "node",
                            "node": "pvedell",
                            "status": "online",
                            "cpu": 0.25,
                            "maxcpu": 32,
                            "mem": 50,
                            "maxmem": 200,
                            "disk": 20,
                            "maxdisk": 100,
                        },
                        {
                            "type": "qemu",
                            "id": "qemu/120",
                            "vmid": 120,
                            "name": "apps01",
                            "node": "pvedell",
                            "status": "running",
                            "cpu": 0.1,
                            "mem": 4,
                            "maxmem": 16,
                        },
                        {
                            "type": "storage",
                            "id": "storage/pvedell/local",
                            "storage": "local",
                            "node": "pvedell",
                            "status": "available",
                            "disk": 25,
                            "maxdisk": 100,
                        },
                    ]
                },
            )

        settings = IntegrationSettings(
            proxmox_url="https://pve.example.test:8006",
            proxmox_token_id="pilot-monitor@pve!pilot-core",
            proxmox_token_secret_env="TEST_PVE_SECRET",
            proxmox_verify_tls=False,
        )
        monitor = ProxmoxMonitor(settings, transport=httpx.MockTransport(handler))
        snapshot = await monitor.snapshot()
        self.assertEqual(snapshot["cluster"]["name"], "James-Home-Lab")
        self.assertEqual(snapshot["nodes"][0]["memory_ratio"], 0.25)
        self.assertEqual(snapshot["workloads"][0]["name"], "apps01")
        self.assertEqual(snapshot["storages"][0]["usage_ratio"], 0.25)
        os.environ.pop("TEST_PVE_SECRET", None)

    def test_truenas_normalization_includes_smart_temperature_and_alerts(self) -> None:
        snapshot = TrueNASMonitor._normalize(
            {"hostname": "truenas", "version": "25.10", "physmem": 64},
            [{"id": 1, "name": "tank", "status": "ONLINE", "healthy": True, "size": 100, "allocated": 40, "free": 60}],
            [{"name": "sda", "model": "Disk", "serial": "ABC", "size": 100, "togglesmart": True}],
            {"sda": 38},
            [{"uuid": "alert-1", "level": "WARNING", "formatted": "Test alert", "dismissed": False}],
        )
        self.assertEqual(snapshot["pools"][0]["usage_ratio"], 0.4)
        self.assertEqual(snapshot["disks"][0]["temperature_c"], 38)
        self.assertTrue(snapshot["disks"][0]["smart_enabled"])
        self.assertEqual(snapshot["alerts"][0]["title"], "Test alert")

    async def test_service_combines_provider_and_agent_health(self) -> None:
        proxmox = FakeProvider(
            {
                "configured": True,
                "status": "ok",
                "cluster": {"name": "Cluster", "quorate": True},
                "nodes": [{"name": "pve", "status": "online"}],
                "workloads": [{"name": "apps01", "status": "running"}],
                "storages": [],
            }
        )
        truenas = FakeProvider(
            {
                "configured": True,
                "status": "ok",
                "system": {"hostname": "nas"},
                "pools": [{"name": "tank", "healthy": True}],
                "disks": [{"name": "sda", "temperature_c": 37}],
                "alerts": [],
            }
        )
        service = HomeLabService(IntegrationSettings(), proxmox=proxmox, truenas=truenas)
        service.update_agent(
            "ai3090",
            {
                "hostname": "ai3090",
                "cpu_ratio": 0.2,
                "memory_used_bytes": 8,
                "memory_total_bytes": 32,
                "gpus": [{"id": "0", "temperature_c": 62}],
                "temperatures": [],
            },
        )
        snapshot = await service.snapshot()
        self.assertEqual(snapshot["schema_version"], "pilot.homelab.v1")
        self.assertEqual(snapshot["status"], "healthy")
        self.assertEqual(snapshot["summary"]["online_node_count"], 1)
        self.assertEqual(snapshot["summary"]["hottest_temperature_c"], 62)


if __name__ == "__main__":
    unittest.main()
