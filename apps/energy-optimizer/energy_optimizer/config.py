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
    amber_interval_minutes: int = 5
    amber_fine_horizon_minutes: int = 60
    fast_dispatch_state_max_age_seconds: int = 330
    fast_dispatch_plan_max_age_seconds: int = 600
    readiness_max_age_seconds: int = 660
    journal_retention_days: int = 90
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
    # Fallback used until Home Assistant supplies the dashboard helper.  The
    # live helper is expressed in cents/kWh for a human-friendly UI; the
    # optimiser converts it to dollars/kWh and never lets it undercut wear.
    battery_min_sell_price_per_kwh: float = 0.08
    grid_charge_uncertainty_per_kwh: float = 0.02
    hot_water_kw: float = 3.7
    hot_water_required_hours: float = 3.0
    # Schedule a small evidence margin so five-minute sampling and relay
    # transitions still deliver at least three confirmed element-hours.
    hot_water_service_target_hours: float = 3.05
    hot_water_latest_hour: int = 16
    hot_water_commit_lead_minutes: int = 60

    # Two physical roof planes.  The azimuths are confirmed by the existing
    # Solcast resources and the local POA model; tilt starts at the midpoint of
    # the measured 10-15 degree roof pitch and can be refined by learning.
    solar_north_capacity_kwp: float = 11.8
    solar_north_azimuth_deg: float = 9.0
    solar_south_capacity_kwp: float = 24.78
    solar_south_azimuth_deg: float = 171.0
    solar_tilt_deg: float = 12.5
    solar_live_correction_minutes: int = 90

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
    ev_expected_pv_attenuation: float = 0.92
    ev_max_charge_kw: float = 11.86
    ev_default_departure_hour: int = 7
    ev_opportunistic_fit_max: float = 0.01

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
    "solcast_power_now": "sensor.solcast_pv_forecast_power_now",
    "solar_radiation": "sensor.gw1100c_solar_radiation",
    "solar_poa_north": "sensor.james_poa_irradiance_james_poa_10",
    "solar_poa_south": "sensor.james_poa_irradiance_james_poa_190",
    "solar_expected_north": "sensor.james_pv1_expected_power_from_poa",
    "solar_expected_south": "sensor.james_pv2_plus_pv3_expected_power_from_poa",
    "solar_actual_north": "sensor.saj_pv1_power",
    "solar_actual_south_1": "sensor.saj_pv2_power",
    "solar_actual_south_2": "sensor.saj_pv3_power",
    "export_enabled": "input_boolean.export_power",
    "weather": "weather.geebung",
    "battery_soc": "sensor.saj_battery_1_soc",
    "battery_usable": "sensor.battery_usable_energy",
    "battery_power": "sensor.saj_battery_power_2",
    # Unlike the MQTT battery-power entity above, this entity is supplied by
    # the same polling SAJ Modbus integration as battery SOC.  Its fresh report
    # is the source-health heartbeat when an unchanged SOC value itself has an
    # old Home Assistant timestamp.
    "battery_soc_heartbeat": "sensor.saj_battery_power",
    "pv_power": "sensor.saj_pv_power",
    # The MQTT PV value can remain unchanged (and therefore acquire an old HA
    # timestamp) when production is genuinely zero overnight.  The polled SAJ
    # entity is an independent source heartbeat that continues to report zero.
    "pv_heartbeat": "sensor.saj_pv_power",
    "pv_energy_today": "sensor.pv_energy_today_total",
    "home_load": "sensor.saj_home_load",
    # The integration's Meter A total is the inverter meter's two-second grid
    # measurement. It is both faster and physically consistent with PV,
    # battery and home load; the former CT aggregate could disagree by several
    # kilowatts despite carrying a fresh Home Assistant timestamp.
    "grid_power": "sensor.saj_meter_a_real_power_total",
    "hot_water_runtime": "sensor.hot_water_confirmed_runtime_today",
    "hot_water_power": "sensor.energy_optimizer_hot_water_confirmed_power",
    "hot_water_active": "binary_sensor.hot_water_heating_active",
    "hot_water_satisfied": "input_boolean.energy_optimizer_hot_water_thermostat_satisfied",
    "hot_water_source": "sensor.energy_optimizer_hot_water_source",
    # The wall connector is the fastest independent proof that the car is
    # physically drawing power. Local BLE is the preferred command path, with
    # Tesla Fleet retained as the automatic fallback in Home Assistant.
    "ev_power": "sensor.tesla_wall_connector_total_power",
    "ev_power_local": "sensor.tesla_ble_charge_power",
    "ev_charger": "switch.tesla_ble_039d9c_charger",
    "ev_soc": "sensor.tesla_battery_level",
    "ev_limit": "number.tesla_ble_039d9c_charging_limit",
    "ev_charge_limit": "number.tesla_ble_039d9c_charging_limit",
    "ev_plugged": "binary_sensor.tesla_plugged_in",
    "ev_home": "device_tracker.tesla_location_2",
    "ev_source": "sensor.energy_optimizer_ev_source",
    "actuator_status": "input_text.energy_optimizer_actuator_status",
    "actuation_ready": "binary_sensor.energy_optimizer_actuation_ready",
    "mode": "input_select.energy_optimizer_mode",
    "manual_override": "input_boolean.energy_optimizer_manual_override",
    "battery_control": "input_boolean.energy_optimizer_battery_control",
    "rollout_approved": "input_boolean.energy_optimizer_rollout_approved",
    "min_sell_price": "input_number.energy_optimizer_min_sell_price_c_per_kwh",
    "shadow_started": "input_datetime.energy_optimizer_shadow_started",
    "hot_water_control": "input_boolean.energy_optimizer_hot_water_control",
    "ev_auto": "input_boolean.energy_optimizer_ev_auto",
    "ev_allow_grid": "input_boolean.energy_optimizer_ev_allow_grid",
    "ev_trip": "input_select.energy_optimizer_ev_trip",
    "ev_custom_km": "input_number.energy_optimizer_ev_custom_km",
    "ev_departure": "input_datetime.energy_optimizer_ev_departure",
}
