from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ha_url: str = "http://10.0.2.72:8123"
    ha_token_file: Path = Path("/run/secrets/home_assistant_token")
    data_dir: Path = Path("/data")
    bind_host: str = "0.0.0.0"
    bind_port: int = 8785
    interval_seconds: int = 300
    horizon_hours: int = 36
    slot_minutes: int = 30
    timezone: str = "Australia/Brisbane"

    battery_capacity_kwh: float = 47.0
    battery_min_soc_pct: float = 5.0
    battery_morning_target_soc_pct: float = 7.0
    battery_evening_target_soc_pct: float = 99.0
    battery_max_charge_kw: float = 30.0
    battery_max_discharge_kw: float = 28.0
    battery_charge_efficiency: float = 0.90
    battery_discharge_efficiency: float = 0.90
    battery_wear_per_kwh: float = 0.08
    grid_charge_uncertainty_per_kwh: float = 0.02
    hot_water_kw: float = 3.7
    hot_water_required_hours: float = 3.0
    hot_water_latest_hour: int = 16

    ev_usable_capacity_kwh: float = 75.0
    ev_kwh_per_km: float = 0.18
    ev_trip_margin: float = 1.20
    ev_arrival_reserve_pct: float = 15.0
    ev_minimum_departure_soc_pct: float = 40.0
    # The Tesla wall connector is three phase.  The observed phase voltages are
    # approximately 243.4 V, 250.8 V and 246.9 V (247 V average), so 16 A is
    # about 11.86 kW rather than the 3.7 kW assumed by the former single-phase
    # model.  Keep these values configurable because voltage and the accepted
    # charging-current range are installation-specific.
    ev_phase_count: int = 3
    ev_phase_voltage_v: float = 247.0
    ev_min_charge_amps: int = 6
    ev_max_charge_amps: int = 16
    ev_max_charge_kw: float = 11.86
    ev_default_departure_hour: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()

        def value(name: str, default: object) -> object:
            raw = os.getenv(name)
            if raw is None:
                return default
            if isinstance(default, int):
                return int(raw)
            if isinstance(default, float):
                return float(raw)
            if isinstance(default, Path):
                return Path(raw)
            return raw

        return cls(**{
            field: value(f"ENERGY_OPTIMIZER_{field.upper()}", getattr(defaults, field))
            for field in defaults.__dataclass_fields__
        })


ENTITY = {
    "amber_fit": "sensor.amber_express_trader_sheena_street_feed_in_price",
    "amber_import": "sensor.amber_express_trader_sheena_street_general_price",
    "solcast_today": "sensor.solcast_pv_forecast_forecast_today",
    "solcast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "weather": "weather.geebung",
    "battery_soc": "sensor.saj_battery_1_soc",
    "battery_usable": "sensor.battery_usable_energy",
    "battery_power": "sensor.saj_battery_power_2",
    "pv_power": "sensor.pv_power_mqtt_abs",
    "pv_energy_today": "sensor.pv_energy_today_total",
    "home_load": "sensor.saj_home_load",
    "grid_power": "sensor.saj_ct_grid_power_total",
    "hot_water_runtime": "sensor.hot_water_runtime_today",
    "hot_water_power": "sensor.hot_water_power",
    "hot_water_active": "binary_sensor.hot_water_heating_active",
    "ev_power": "sensor.tesla_charging_power",
    "ev_soc": "sensor.tesla_battery_level",
    "ev_limit": "sensor.tesla_charge_limit_soc",
    "ev_plugged": "binary_sensor.tesla_plugged_in",
    "ev_home": "device_tracker.tesla_location_2",
    "mode": "input_select.energy_optimizer_mode",
    "manual_override": "input_boolean.energy_optimizer_manual_override",
    "battery_control": "input_boolean.energy_optimizer_battery_control",
    "rollout_approved": "input_boolean.energy_optimizer_rollout_approved",
    "shadow_started": "input_datetime.energy_optimizer_shadow_started",
    "hot_water_control": "input_boolean.energy_optimizer_hot_water_control",
    "ev_auto": "input_boolean.energy_optimizer_ev_auto",
    "ev_trip": "input_select.energy_optimizer_ev_trip",
    "ev_custom_km": "input_number.energy_optimizer_ev_custom_km",
    "ev_departure": "input_datetime.energy_optimizer_ev_departure",
}
