from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import AsyncMock

from pilot_core.config import IntegrationSettings
from pilot_core.dashboard import DashboardService


def state(entity_id: str, value: object, unit: str = "") -> dict:
    return {
        "entity_id": entity_id,
        "state": str(value),
        "last_updated": "2026-07-22T04:00:00+00:00",
        "attributes": {"unit_of_measurement": unit},
    }


class DashboardServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_bounded_energy_vehicle_tariff_and_climate_contract(self) -> None:
        settings = IntegrationSettings(
            weather_entity_id="weather.home",
            sun_entity_id="sun.sun",
            outdoor_temperature_entity_id="sensor.outdoor",
            energy_solar_power_entity_id="sensor.solar",
            energy_grid_power_entity_id="sensor.grid",
            energy_battery_power_entity_id="sensor.battery",
            energy_battery_soc_entity_id="sensor.battery_soc",
            energy_home_load_entity_id="sensor.home",
            energy_server_power_entity_id="sensor.server",
            energy_vehicle_connected_entity_id="binary_sensor.car",
            energy_vehicle_power_entity_id="sensor.car_power",
            energy_vehicle_soc_entity_id="sensor.car_soc",
            energy_solar_today_entity_ids=("sensor.pv1", "sensor.pv2", "sensor.pv3"),
            energy_home_today_entity_id="sensor.home_today",
            energy_grid_export_today_entity_id="sensor.export_today",
            amber_import_price_entity_id="sensor.buy",
            amber_feed_in_price_entity_id="sensor.fit",
            amber_feed_in_forecast_entity_id="sensor.fit_forecast",
            tesla_charging_mode_entity_id="input_select.car_mode",
            office_sim_rig_switch_entity_id="switch.sim_rig",
            codex_usage_used_entity_id="sensor.codex_used",
            codex_usage_remaining_entity_id="sensor.codex_remaining",
            codex_usage_reset_entity_id="sensor.codex_reset",
            media_room_mode_on_script_id="script.movie_on",
            media_room_mode_off_script_id="script.movie_off",
            temperature_office_entity_id="sensor.office",
            temperature_tv_room_entity_id="sensor.tv",
            temperature_bedroom_entity_id="sensor.bedroom",
            temperature_media_room_entity_id="sensor.media",
        )
        integrations = AsyncMock()
        states = {
            "sensor.solar": state("sensor.solar", 8.2, "kW"),
            "sensor.grid": state("sensor.grid", 99, "W"),
            "sensor.battery": state("sensor.battery", -3.1, "kW"),
            "sensor.battery_soc": state("sensor.battery_soc", 77, "%"),
            "sensor.home": state("sensor.home", 5.6, "kW"),
            "sensor.server": state("sensor.server", 662.5, "W"),
            "binary_sensor.car": state("binary_sensor.car", "on"),
            "sensor.car_power": state("sensor.car_power", 4.54, "kW"),
            "sensor.car_soc": state("sensor.car_soc", 52, "%"),
            "sensor.pv1": state("sensor.pv1", 25.67, "kWh"),
            "sensor.pv2": state("sensor.pv2", 15.34, "kWh"),
            "sensor.pv3": state("sensor.pv3", 28.63, "kWh"),
            "sensor.home_today": state("sensor.home_today", 34.82, "kWh"),
            "sensor.export_today": state("sensor.export_today", 5.52, "kWh"),
            "sensor.buy": state("sensor.buy", 8.91326, "c/kWh"),
            "sensor.fit": state("sensor.fit", 5.10226, "c/kWh"),
            "sensor.fit_forecast": {
                **state("sensor.fit_forecast", 0.07, "$/kWh"),
                "attributes": {
                    "unit_of_measurement": "$/kWh",
                    "forecast": [{"time": "2026-07-22T14:30:00+10:00", "value": 0.0598}],
                },
            },
            "input_select.car_mode": state("input_select.car_mode", "Solar"),
            "switch.sim_rig": state("switch.sim_rig", "on"),
            "sensor.codex_used": state("sensor.codex_used", 39, "%"),
            "sensor.codex_remaining": state("sensor.codex_remaining", 61, "%"),
            "sensor.codex_reset": state(
                "sensor.codex_reset", "2026-08-18T10:02:13+10:00"
            ),
            "sensor.office": state("sensor.office", 21.9, "°C"),
            "sensor.tv": state("sensor.tv", 22.0, "°C"),
            "sensor.bedroom": state("sensor.bedroom", 22.5, "°C"),
            "sensor.media": state("sensor.media", 22.3, "°C"),
            "sensor.outdoor": state("sensor.outdoor", 21.0, "°C"),
            "sun.sun": {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "last_updated": "2026-07-22T04:00:00+00:00",
                "attributes": {
                    "elevation": 31.4,
                    "next_rising": "2026-07-22T20:30:00+00:00",
                    "next_setting": "2026-07-22T07:10:00+00:00",
                },
            },
        }
        integrations.home_assistant_selected_states.return_value = states
        integrations.home_assistant_history.return_value = {
            "sensor.home": [state("sensor.home", 5000, "W")],
            "sensor.battery": [state("sensor.battery", -3000, "W")],
            "sensor.solar": [state("sensor.solar", 8100, "W")],
            # Home Assistant's minimal history response omits attributes after
            # the first state. The current entity unit must therefore supply
            # the kW-to-W conversion for this series.
            "sensor.car_power": [
                {
                    "entity_id": "sensor.car_power",
                    "state": "4.54",
                    "last_updated": "2026-07-22T04:00:00+00:00",
                }
            ],
            "sensor.office": [state("sensor.office", 21.6, "°C")],
        }
        integrations.home_assistant_weather.return_value = {
            "entity_id": "weather.home",
            "current": {
                "state": "sunny",
                "last_updated": "2026-07-22T04:00:00+00:00",
                "attributes": {"temperature": 21, "humidity": 77},
            },
            "forecast_response": {
                "service_response": {
                    "weather.home": {
                        "forecast": [
                            {
                                "datetime": "2026-07-22T14:00:00+10:00",
                                "condition": "sunny",
                                "temperature": 25,
                                "templow": 15,
                            }
                        ]
                    }
                }
            },
        }

        service = DashboardService(settings, integrations)
        result = await service.snapshot()

        self.assertEqual(result["schema_version"], "pilot.dashboard.v1")
        self.assertEqual(result["power"]["solar_w"], 8200)
        self.assertFalse(result["power"]["flow_active"]["grid"])
        self.assertEqual(result["power"]["directions"]["grid"], "idle")
        self.assertEqual(result["power"]["directions"]["battery"], "charging")
        self.assertTrue(result["scene"]["is_day"])
        self.assertEqual(result["scene"]["solar_elevation_degrees"], 31.4)
        self.assertTrue(result["vehicle"]["connected"])
        self.assertTrue(result["vehicle"]["charging"])
        self.assertEqual(result["vehicle"]["state_of_charge_percent"], 52)
        self.assertEqual(result["daily"]["solar_generated_kwh"], 69.64)
        self.assertEqual(result["tariff"]["feed_in_forecast"][0]["cents_per_kwh"], 5.98)
        self.assertEqual(len(result["temperatures"]), 5)
        self.assertEqual(result["temperatures"][0]["history"][0]["value"], 21.6)
        self.assertEqual([item["id"] for item in result["history"]["series"]], [
            "home_load", "battery", "solar", "tesla"
        ])
        self.assertEqual(result["history"]["window"], "calendar_day")
        self.assertEqual(
            result["history"]["series"][0]["points"][0]["value"],
            -5000,
        )
        self.assertEqual(
            result["history"]["series"][3]["points"][0]["value"],
            -4540,
        )
        self.assertEqual(result["history"]["series"][1]["activity_threshold_w"], 100)
        self.assertEqual(result["history"]["series"][1]["render_mode"], "step")
        self.assertEqual(result["history"]["series"][3]["activity_threshold_w"], 100)
        self.assertEqual(result["history"]["series"][3]["render_mode"], "step")
        started_at = datetime.fromisoformat(result["history"]["started_at"])
        ended_at = datetime.fromisoformat(result["history"]["ended_at"])
        self.assertEqual((started_at.hour, started_at.minute), (0, 0))
        self.assertEqual((ended_at - started_at).total_seconds(), 86_400)
        self.assertNotIn("tesla_charging_mode", result["controls"])
        self.assertEqual(result["controls"]["sim_rig"]["value"], "on")
        self.assertTrue(result["controls"]["sim_rig"]["available"])
        self.assertEqual(result["codex_usage"]["used_percent"], 39)
        self.assertEqual(result["codex_usage"]["remaining_percent"], 61)
        self.assertEqual(
            result["codex_usage"]["reset_at"], "2026-08-18T10:02:13+10:00"
        )
        self.assertTrue(result["codex_usage"]["available"])
        self.assertNotIn("attributes", str(result))

        energy_call, temperature_call = integrations.home_assistant_history.await_args_list[:2]
        self.assertEqual(
            energy_call.args[0],
            ("sensor.home", "sensor.battery", "sensor.solar", "sensor.car_power"),
        )
        self.assertIn("started_at", energy_call.kwargs)
        self.assertIn("ended_at", energy_call.kwargs)
        self.assertEqual(len(temperature_call.args[0]), 5)
        self.assertEqual(temperature_call.kwargs, {"hours": 24})

        cached = await service.snapshot()
        self.assertEqual(cached["generated_at"], result["generated_at"])
        integrations.home_assistant_selected_states.assert_awaited_once()
        service.invalidate()
        await service.snapshot()
        self.assertEqual(integrations.home_assistant_selected_states.await_count, 2)

    async def test_tesla_flow_uses_one_hundred_watt_deadband_without_hiding_presence(self) -> None:
        settings = IntegrationSettings(
            energy_vehicle_connected_entity_id="binary_sensor.car",
            energy_vehicle_power_entity_id="sensor.car_power",
        )
        integrations = AsyncMock()
        integrations.home_assistant_selected_states.return_value = {
            "binary_sensor.car": state("binary_sensor.car", "on"),
            "sensor.car_power": state("sensor.car_power", 1.6, "W"),
        }
        integrations.home_assistant_history.return_value = {}
        integrations.home_assistant_weather.return_value = {
            "entity_id": "",
            "current": {},
            "forecast_response": {},
        }

        result = await DashboardService(settings, integrations).snapshot()

        self.assertTrue(result["vehicle"]["connected"])
        self.assertFalse(result["vehicle"]["charging"])
        self.assertEqual(result["vehicle"]["power_w"], 1.6)
        self.assertFalse(result["power"]["flow_active"]["vehicle"])
        self.assertEqual(result["power"]["directions"]["vehicle"], "idle")

    async def test_battery_flow_uses_one_hundred_watt_deadband(self) -> None:
        settings = IntegrationSettings(
            energy_battery_power_entity_id="sensor.battery",
        )
        integrations = AsyncMock()
        integrations.home_assistant_selected_states.return_value = {
            "sensor.battery": state("sensor.battery", 76, "W"),
        }
        integrations.home_assistant_history.return_value = {}
        integrations.home_assistant_weather.return_value = {
            "entity_id": "",
            "current": {},
            "forecast_response": {},
        }

        result = await DashboardService(settings, integrations).snapshot()

        self.assertFalse(result["power"]["flow_active"]["battery"])
        self.assertEqual(result["power"]["directions"]["battery"], "idle")

    async def test_manager_overlay_stays_live_while_ha_context_is_cached(self) -> None:
        class Manager:
            configured = True

            def __init__(self) -> None:
                self.solar_w = 12_400.0

            def dashboard_fields(self) -> dict:
                return deepcopy(
                    {
                        "source": "standalone_energy_manager",
                        "observed_at": "2026-08-26T01:20:00+00:00",
                        "stale": False,
                        "energy_status": "ok",
                        "power": {
                            "solar_w": self.solar_w,
                            "grid_w": -2_000.0,
                            "battery_w": 3_000.0,
                            "battery_soc_percent": 74.3,
                            "home_load_w": 7_400.0,
                            "server_rack_w": 940.0,
                            "vehicle_w": 0.0,
                            "hot_water_w": 3_700.0,
                            "directions": {"grid": "exporting", "battery": "discharging"},
                            "flow_active": {},
                        },
                        "daily": {
                            "solar_generated_kwh": 120.08,
                            "home_used_kwh": 47.42,
                            "grid_exported_kwh": 62.12,
                        },
                        "arrays": {"pv1": {"measured_w": 3_100.0}},
                        "vehicle": {"home": True, "connected": True},
                        "hot_water": {"relay_on": True, "confirmed": True},
                        "tariff": {"feed_in_cents_per_kwh": 10.4},
                        "plan": {"plan_id": "plan-1"},
                        "flow": {"mode": "export"},
                        "financial": {"planned_export_revenue": 4.27},
                        "server": {"label": "Server + desk", "power_w": 940.0},
                        "manager_health": {"status": "ok", "age_seconds": 0.2},
                        "history": {
                            "window": "calendar_day",
                            "started_at": "2026-08-25T14:00:00+00:00",
                            "ended_at": "2026-08-26T14:00:00+00:00",
                            "series": [],
                        },
                    }
                )

        settings = IntegrationSettings(
            energy_manager_url="http://energy-manager.test:8787",
            sun_entity_id="sun.sun",
            energy_solar_power_entity_id="sensor.solar",
            energy_grid_power_entity_id="sensor.grid",
            energy_battery_power_entity_id="sensor.battery",
            energy_battery_soc_entity_id="sensor.battery_soc",
            energy_home_load_entity_id="sensor.home",
            energy_vehicle_power_entity_id="sensor.ev",
        )
        integrations = AsyncMock()
        integrations.home_assistant_selected_states.return_value = {
            "sun.sun": {
                "entity_id": "sun.sun",
                "state": "above_horizon",
                "attributes": {},
            }
        }
        integrations.home_assistant_history.return_value = {}
        integrations.home_assistant_weather.return_value = {
            "entity_id": "",
            "current": {},
            "forecast_response": {},
        }
        manager = Manager()
        service = DashboardService(settings, integrations, manager)  # type: ignore[arg-type]

        first = await service.snapshot()
        manager.solar_w = 13_200.0
        second = await service.snapshot()

        self.assertEqual(first["power"]["solar_w"], 12_400.0)
        self.assertEqual(second["power"]["solar_w"], 13_200.0)
        self.assertEqual(second["source"], "standalone_energy_manager")
        self.assertEqual(second["daily"]["solar_generated_kwh"], 120.08)
        self.assertEqual(second["manager_health"]["status"], "ok")
        selected = integrations.home_assistant_selected_states.await_args.args[0]
        self.assertEqual(selected, ("sun.sun",))
        integrations.home_assistant_history.assert_not_awaited()

    def test_scene_falls_back_to_unknown_when_sun_is_not_configured(self) -> None:
        service = DashboardService(IntegrationSettings(), AsyncMock())

        self.assertEqual(
            service._scene({}),
            {
                "is_day": None,
                "sun_state": None,
                "solar_elevation_degrees": None,
                "next_rising": None,
                "next_setting": None,
            },
        )

    def test_energy_history_keeps_higher_resolution_and_negative_loads(self) -> None:
        service = DashboardService(IntegrationSettings(), AsyncMock())
        values = [
            {
                "state": str(index),
                "last_updated": f"2026-07-22T00:{index % 60:02d}:00+00:00",
                "attributes": {"unit_of_measurement": "W"},
            }
            for index in range(600)
        ]

        points = service._history_points(values, negative=True)

        self.assertEqual(len(points), 288)
        self.assertEqual(points[-1]["value"], -599)
        self.assertTrue(all(point["value"] <= 0 for point in points))


if __name__ == "__main__":
    unittest.main()
