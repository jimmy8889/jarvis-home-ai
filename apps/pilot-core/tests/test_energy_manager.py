from __future__ import annotations

from datetime import UTC, datetime, timedelta
import unittest

import httpx

from pilot_core.config import IntegrationSettings
from pilot_core.energy_manager import EnergyManagerClient


NOW = datetime(2026, 8, 26, 1, 20, tzinfo=UTC)


def snapshot(at: datetime, *, plan_id: str = "plan-1", pv_kw: float = 12.4) -> dict:
    return {
        "plan_id": plan_id,
        "service": {
            "control_enabled": True,
            "command_phase": "confirmed",
            "mqtt_connected": True,
            "error": None,
        },
        "telemetry": {
            "measured_at": at.isoformat(),
            "pv_kw": pv_kw,
            "pv1_kw": 3.1,
            "pv2_kw": 3.0,
            "pv3_kw": 6.3,
            "load_kw": 7.7,
            "grid_kw": -2.2,
            "battery_kw": 3.0,
            "soc_pct": 74.26,
            "soh_pct": 96.0,
        },
        "devices": {
            "ev_soc_pct": 63.0,
            "ev_plugged": True,
            "ev_home": True,
            "ev_charging": True,
            "ev_amps": 8,
            "ev_power_kw": 5.5,
            "ev_limit_pct": 80,
            "hot_water_on": True,
            "hot_water_available": True,
            "hot_water_confirmed": True,
            "hot_water_power_kw": 3.7,
            "hot_water_runtime_hours": 1.25,
            "hot_water_source": "solar",
        },
        "command": {
            "mode": "export",
            "reason": "profitable_fit",
            "protected_soc_pct": 18.0,
            "site_export_target_kw": 12.0,
            "battery_target_kw": 9.0,
            "zero_export": False,
        },
        "prices": {
            "amber_fit": {"price_per_kwh": 0.1042},
            "amber_import": {"price_per_kwh": 0.3121},
            "aemo": {"price_per_kwh": 0.083},
        },
        "forecast": {
            "arrays": {
                "pv1": {"orientation": "north", "capacity_kwp": 11.8, "expected_kw": 3.4, "error_kw": -0.3},
                "pv2": {"orientation": "south", "capacity_kwp": 8.26, "expected_kw": 3.2, "error_kw": -0.2},
                "pv3": {"orientation": "south", "capacity_kwp": 16.52, "expected_kw": 6.5, "error_kw": -0.2},
            }
        },
        "source_allocation": {
            "house": {"load_kw": 1.5, "solar_kw": 1.5, "battery_kw": 0, "grid_kw": 0},
            "hot_water": {"load_kw": 3.7, "solar_kw": 3.7, "battery_kw": 0, "grid_kw": 0},
            "ev": {"load_kw": 5.5, "solar_kw": 5.5, "battery_kw": 0, "grid_kw": 0},
        },
        "power_flow": {
            "method": "conserved_source_allocation",
            "confidence": {"label": "high", "score": 0.96},
            "balance_residual_kw": 0.08,
            "sources_kw": {"solar": 12.4, "battery": 3.0, "grid": 0.0},
            "sinks_kw": {"house": 1.5, "ev": 5.5, "hot_water": 3.7, "grid": 4.62},
            "submeters_kw": {"server_rack": 0.94},
            "edges": [
                {"from": "solar", "to": "house", "kw": 1.5},
                {"from": "solar", "to": "ev", "kw": 5.5},
                {"from": "solar", "to": "hot_water", "kw": 3.7},
                {"from": "battery", "to": "grid", "kw": 3.0},
            ],
        },
        "server_rack": {
            "server_rack_power_w": 940.0,
            "energy_today_kwh": 7.4,
            "confidence": "live_efficiency",
            "status": "OL",
            "battery_charge_pct": 98,
            "battery_runtime_seconds": 1800,
            "age_seconds": 1.2,
        },
        "outcomes": {
            "current_daily": {
                "battery_export_revenue": 1.23,
                "export_revenue": 2.34,
                "import_cost": 0.11,
                "wear_cost": 0.22,
            }
        },
    }


def plan(at: datetime, *, plan_id: str = "plan-1") -> dict:
    return {
        "current": {
            "mode": "export",
            "reason": "profitable_fit",
            "protected_soc_pct": 18.0,
            "site_export_target_kw": 12.0,
            "battery_target_kw": 9.0,
            "zero_export": False,
        },
        "rolling": {
            "plan_id": plan_id,
            "generated_at": at.isoformat(),
            "horizon_end": (at + timedelta(hours=36)).isoformat(),
            "summary": {
                "battery_export_kwh": 14.2,
                "battery_export_revenue": 4.27,
                "battery_export_wear_cost": 1.14,
                "battery_export_retained_value": 0.42,
                "battery_export_net_benefit": 2.71,
                "solar_export_revenue": 7.33,
                "total_export_revenue": 11.60,
            },
            "export_windows": [
                {
                    "start": at.isoformat(),
                    "end": (at + timedelta(minutes=30)).isoformat(),
                    "max_power_kw": 12.0,
                    "max_price_per_kwh": 0.1042,
                }
            ],
            "predicted_soc_path": [{"at": at.isoformat(), "soc_pct": 74.3}],
            "hot_water": {
                "planned_start": at.isoformat(),
                "planned_end": (at + timedelta(hours=2)).isoformat(),
                "remaining_hours": 1.8,
                "deadline": (at + timedelta(hours=6)).isoformat(),
            },
            "ev": {
                "planned_start": at.isoformat(),
                "planned_end": (at + timedelta(hours=1)).isoformat(),
                "planned_input_kwh": 5.5,
                "recommendation": "Charge from forecast solar",
                "trip_requirement": "No trip",
            },
            "points": [
                {
                    "start": at.isoformat(),
                    "end": (at + timedelta(minutes=5)).isoformat(),
                    "fit_per_kwh": 0.1042,
                    "import_per_kwh": 0.3121,
                }
            ],
        },
    }


def series(at: datetime) -> list[dict]:
    return [
        {
            "interval_start": at.isoformat(),
            "average_pv_kw": 12.4,
            "average_whole_house_load_kw": 7.7,
            "average_grid_kw": -2.2,
            "average_battery_kw": 3.0,
            "average_ev_kw": 5.5,
        }
    ]


def daily(at: datetime) -> list[dict]:
    return [
        {
            "local_date": at.astimezone().date().isoformat(),
            "pv_kwh": 120.08,
            "whole_house_load_kwh": 47.42,
            "export_kwh": 62.12,
        }
    ]


class EnergyManagerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_projects_live_plan_arrays_loads_and_financials(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("snapshot"):
                payload = snapshot(NOW)
            elif request.url.path.endswith("series"):
                payload = series(NOW)
            elif request.url.path.endswith("daily"):
                payload = daily(NOW)
            else:
                payload = plan(NOW)
            return httpx.Response(200, json=payload)

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )

        self.assertTrue(await client.poll_once(plan_due=True))
        energy = client.energy_snapshot()
        dashboard = client.dashboard_fields()

        self.assertEqual(energy["source"], "standalone_energy_manager")
        self.assertEqual(energy["status"], "ok")
        self.assertEqual(energy["solar"]["value"], 12_400)
        self.assertEqual(energy["grid"]["value"], -4_620)
        self.assertEqual(energy["battery"]["value"], 3_000)
        self.assertEqual(energy["home_load"]["value"], 10_700)
        self.assertEqual(energy["grid"]["direction"], "exporting")
        self.assertEqual(energy["battery"]["direction"], "discharging")
        self.assertEqual(energy["arrays"]["pv3"]["measured_w"], 6_300)
        self.assertEqual(energy["hot_water"]["power_w"], 3_700)
        self.assertEqual(energy["vehicle"]["amps"], 8)
        self.assertEqual(dashboard["server"]["power_w"], 940)
        self.assertEqual(dashboard["tariff"]["feed_in_cents_per_kwh"], 10.42)
        self.assertEqual(dashboard["financial"]["planned_export_revenue"], 11.60)
        self.assertEqual(dashboard["financial"]["planned_battery_export_net_benefit"], 2.71)
        self.assertEqual(dashboard["financial"]["realised_battery_export_revenue_today"], 1.23)
        self.assertEqual(dashboard["financial"]["realised_net_benefit_today"], 2.01)
        self.assertEqual(dashboard["server"]["confidence"], "live_efficiency")
        self.assertEqual(dashboard["server"]["energy_today_kwh"], 7.4)
        self.assertEqual(dashboard["power"]["source"], "power_flow")
        self.assertEqual(dashboard["power"]["vehicle_w"], 5_500)
        self.assertEqual(dashboard["power"]["hot_water_w"], 3_700)
        self.assertEqual(dashboard["flow"]["confidence"]["label"], "high")
        self.assertEqual(dashboard["flow"]["edges"][3]["to"], "grid")
        self.assertEqual(dashboard["plan"]["plan_id"], "plan-1")
        self.assertEqual(len(dashboard["plan"]["points"]), 1)
        self.assertEqual(dashboard["history"]["source"], "standalone_energy_manager_series")
        solar_history = next(
            item for item in dashboard["history"]["series"] if item["id"] == "solar"
        )
        self.assertEqual(solar_history["points"][0]["value"], 12_400)
        self.assertEqual(dashboard["daily"]["solar_generated_kwh"], 120.08)
        self.assertEqual(dashboard["daily"]["home_used_kwh"], 47.42)
        self.assertEqual(dashboard["daily"]["grid_exported_kwh"], 62.12)
        self.assertNotIn("points", energy["plan"])

    async def test_power_projection_exactly_matches_standalone_flow_contract(self) -> None:
        payload = snapshot(NOW)
        payload["telemetry"].update(
            {"pv_kw": 99.0, "load_kw": 88.0, "grid_kw": 77.0, "battery_kw": 66.0}
        )
        payload["devices"].update({"ev_power_kw": 55.0, "hot_water_power_kw": 44.0})
        payload["power_flow"] = {
            "site_load_kw": 1.126,
            "sources_kw": {"solar": 0.0, "battery": 1.126, "grid": 0.0},
            "sinks_kw": {
                "house": 1.126,
                "hot_water": 0.0,
                "ev": 0.0,
                "battery": 0.0,
                "grid": 0.041,
            },
            "submeters_kw": {"server_rack": 0.808511},
            "edges": [
                {"from": "battery", "to": "house", "kw": 1.126},
                {"from": "unaccounted", "to": "grid", "kw": 0.041},
            ],
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=payload if request.url.path.endswith("snapshot") else plan(NOW),
            )

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)

        power = client.dashboard_fields()["power"]
        self.assertEqual(power["source"], "power_flow")
        self.assertEqual(power["solar_w"], 0)
        self.assertEqual(power["home_load_w"], 1_126)
        self.assertEqual(power["battery_w"], 1_126)
        self.assertEqual(power["grid_w"], -41)
        self.assertEqual(power["server_rack_w"], 808.5)
        self.assertEqual(power["vehicle_w"], 0)
        self.assertEqual(power["hot_water_w"], 0)
        self.assertEqual(power["directions"]["battery"], "discharging")
        self.assertTrue(power["flow_active"]["battery"])
        self.assertTrue(power["flow_active"]["grid"])
        self.assertFalse(power["flow_active"]["solar"])

    async def test_daily_projection_prefers_snapshot_values_used_by_manager_ui(self) -> None:
        payload = snapshot(NOW)
        payload["daily_energy"] = {
            "local_date": NOW.astimezone().date().isoformat(),
            "solar_generated_kwh": 120.0779,
            "house_consumed_kwh": 51.0709,
            "grid_exported_kwh": 62.2266,
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("snapshot"):
                return httpx.Response(200, json=payload)
            if request.url.path.endswith("daily"):
                return httpx.Response(200, json=daily(NOW))
            if request.url.path.endswith("series"):
                return httpx.Response(200, json=series(NOW))
            return httpx.Response(200, json=plan(NOW))

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)

        self.assertEqual(
            client.daily_projection(),
            {
                "solar_generated_kwh": 120.0779,
                "home_used_kwh": 51.0709,
                "grid_exported_kwh": 62.2266,
            },
        )

    async def test_dashboard_plan_points_are_bounded_and_drop_nested_flow_graphs(self) -> None:
        payload = plan(NOW)
        payload["rolling"]["points"] = [
            {
                "start": (NOW + timedelta(minutes=5 * index)).isoformat(),
                "end": (NOW + timedelta(minutes=5 * (index + 1))).isoformat(),
                "fit_per_kwh": 0.10,
                "pv_kw": float(index),
                "predicted_soc_pct": 50.0,
                "flow": {
                    "edges": [
                        {"from": "solar", "to": "house", "kw": float(index)}
                    ]
                },
            }
            for index in range(432)
        ]

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=snapshot(NOW) if request.url.path.endswith("snapshot") else payload,
            )

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)

        points = client.dashboard_fields()["plan"]["points"]
        self.assertEqual(len(points), 144)
        self.assertEqual(points[0]["start"], payload["rolling"]["points"][0]["start"])
        self.assertEqual(points[-1]["end"], payload["rolling"]["points"][-1]["end"])
        self.assertTrue(all("flow" not in point for point in points))

    async def test_rejects_timestamp_regression_and_marks_old_cache_stale(self) -> None:
        snapshots = [snapshot(NOW), snapshot(NOW - timedelta(seconds=2), pv_kw=2.0)]

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("snapshot"):
                return httpx.Response(200, json=snapshots.pop(0))
            return httpx.Response(200, json=plan(NOW))

        clock = [NOW]
        client = EnergyManagerClient(
            IntegrationSettings(
                energy_manager_url="http://energy-manager.test:8787",
                energy_manager_stale_after_seconds=10,
            ),
            transport=httpx.MockTransport(handler),
            clock=lambda: clock[0],
        )
        await client.poll_once(plan_due=True)
        await client.poll_once()

        self.assertEqual(client.energy_snapshot()["solar"]["value"], 12_400)
        self.assertIn("regressed", client.health()["snapshot_error"])
        clock[0] = NOW + timedelta(seconds=11)
        self.assertEqual(client.health()["status"], "stale")
        self.assertTrue(client.energy_snapshot()["stale"])

    async def test_advertised_plan_id_refreshes_before_periodic_deadline(self) -> None:
        snapshots = [snapshot(NOW, plan_id="plan-1"), snapshot(NOW, plan_id="plan-2")]
        plans = [plan(NOW, plan_id="plan-1"), plan(NOW + timedelta(seconds=1), plan_id="plan-2")]
        plan_requests = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal plan_requests
            if request.url.path.endswith("snapshot"):
                return httpx.Response(200, json=snapshots.pop(0))
            if request.url.path.endswith("series"):
                return httpx.Response(200, json=series(NOW))
            if request.url.path.endswith("daily"):
                return httpx.Response(200, json=daily(NOW))
            plan_requests += 1
            return httpx.Response(200, json=plans.pop(0))

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)
        refreshed = await client.poll_once(plan_due=False)

        self.assertTrue(refreshed)
        self.assertEqual(plan_requests, 2)
        self.assertEqual(client.health()["plan_id"], "plan-2")

    async def test_plan_mismatch_is_stale_and_old_plan_is_not_projected(self) -> None:
        snapshots = [snapshot(NOW, plan_id="plan-1"), snapshot(NOW, plan_id="plan-2")]

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("snapshot"):
                return httpx.Response(200, json=snapshots.pop(0))
            if not snapshots:
                return httpx.Response(503, json={"detail": "planner unavailable"})
            return httpx.Response(200, json=plan(NOW, plan_id="plan-1"))

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)
        await client.poll_once(plan_due=False)

        self.assertTrue(client.health()["plan_stale"])
        self.assertFalse(client.health()["plan_consistent"])
        self.assertEqual(client.health()["advertised_plan_id"], "plan-2")
        self.assertIsNone(client.dashboard_fields()["plan"]["plan_id"])

    async def test_live_command_overrides_device_default_hot_water_source(self) -> None:
        payload = snapshot(NOW)
        payload["devices"]["hot_water_source"] = "off"
        payload["command"]["hot_water_source"] = "solar"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload if request.url.path.endswith("snapshot") else plan(NOW))

        client = EnergyManagerClient(
            IntegrationSettings(energy_manager_url="http://energy-manager.test:8787"),
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
        await client.poll_once(plan_due=True)

        self.assertEqual(client.energy_snapshot()["hot_water"]["source"], "solar")


if __name__ == "__main__":
    unittest.main()
