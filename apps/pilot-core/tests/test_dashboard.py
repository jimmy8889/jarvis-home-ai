from __future__ import annotations

import unittest
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
        self.assertEqual([item["id"] for item in result["history"]["series"]], [
            "home_load", "battery", "solar"
        ])
        self.assertEqual(result["controls"]["tesla_charging_mode"]["options"], ["Grid", "Solar"])
        self.assertNotIn("attributes", str(result))

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


if __name__ == "__main__":
    unittest.main()
