from __future__ import annotations

from dataclasses import dataclass, fields
import os
from pathlib import Path
import hashlib
import json


def _secret(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("/var/lib/energy-manager")
    secret_dir: Path = Path("/etc/energy-manager/secrets")
    bind_host: str = "0.0.0.0"
    bind_port: int = 8788
    timezone: str = "Australia/Brisbane"
    software_revision: str = "standalone-0.5.5"

    saj_host: str = "10.0.6.24"
    saj_port: int = 502
    saj_unit: int = 1
    saj_poll_seconds: float = 1.0
    saj_mqtt_discovery_enabled: bool = False
    control_enabled: bool = False

    mqtt_host: str = "10.0.1.64"
    mqtt_port: int = 1883
    mqtt_prefix: str = "energy-manager"
    home_assistant_host: str = "10.0.2.72"
    influx_url: str = "http://10.0.1.29:8086"
    influx_org: str = "jameshome"
    influx_bucket: str = "energy_manager"

    amber_api_url: str = "https://api.amber.com.au/v1"
    amber_forecast_max_age_seconds: float = 21600.0
    aemo_api_url: str = "https://visualisations.aemo.com.au/aemo/apps/api/report"
    forecast_solar_url: str = "https://api.forecast.solar"
    solcast_url: str = "https://api.solcast.com.au"

    latitude: float = -27.375711680426168
    longitude: float = 153.0484771728516
    north_capacity_kwp: float = 11.8
    north_azimuth_deg: float = 9.0
    south_capacity_kwp: float = 24.78
    south_azimuth_deg: float = 171.0
    roof_tilt_deg: float = 12.5
    ecowitt_host: str = "10.0.2.234"
    irradiance_max_age_seconds: float = 30.0
    command_watchdog_grace_seconds: float = 2.0

    battery_capacity_kwh: float = 50.0
    battery_floor_pct: float = 5.0
    battery_morning_target_pct: float = 7.0
    battery_evening_target_pct: float = 99.0
    battery_charge_efficiency: float = 0.92
    battery_discharge_efficiency: float = 0.92
    battery_wear_per_kwh: float = 0.08
    uncertainty_per_kwh: float = 0.02
    # Morning PV-charge deferral is re-evaluated every five minutes. Use a
    # confidence-adjusted expected forecast plus a small energy margin, while
    # retaining the stricter 75% case for protected export reserves.
    morning_defer_solar_confidence: float = 0.90
    morning_defer_energy_margin: float = 1.05
    morning_defer_min_price_gap_per_kwh: float = 0.001
    min_sell_price_per_kwh: float = 0.10
    max_discharge_kw: float = 28.0
    max_charge_kw: float = 28.0

    ev_host: str = "10.0.2.36"
    ev_port: int = 6053
    ev_min_amps: int = 6
    ev_max_amps: int = 16
    ev_min_soc_pct: float = 40.0
    ev_pv_attenuation: float = 0.92
    ev_opportunistic_fit_max_per_kwh: float = 0.01
    ev_grid_allowed: bool = False
    ev_charge_limit_pct: int = 80
    ev_trip_profile: str = "no_trip"
    # Compatibility alias for pre-v3 clients. Runtime settings normalise this
    # to the human label matching ev_trip_profile.
    ev_trip_requirement: str = "No trip"
    ev_trip_deadline: str = ""
    ev_default_departure_hour: int = 7
    ev_lease_seconds: int = 300
    ev_usable_capacity_kwh: float = 75.0
    ev_charge_efficiency: float = 0.90
    ev_three_phase_kw_per_amp: float = 0.69
    ev_consumption_kwh_per_km: float = 0.18
    ev_learned_consumption_kwh_per_km: float = 0.0
    ev_trip_energy_margin: float = 1.20
    ev_arrival_reserve_pct: float = 15.0

    hot_water_host: str = "10.0.2.237"
    hot_water_port: int = 6053
    hot_water_kw: float = 3.7
    hot_water_target_hours: float = 3.05
    hot_water_deadline_hour: int = 16
    hot_water_confirmation_sync_seconds: float = 60.0
    # False uses forecast/economic scheduling. True is the deliberately simple
    # failsafe schedule: relay requested on from 11:00 until 14:00 Brisbane.
    hot_water_fixed_timer: bool = False
    hot_water_enabled: bool = True
    hot_water_timer_start_hour: int = 11
    hot_water_timer_end_hour: int = 14

    nut_host: str = "10.0.1.206"
    nut_port: int = 3493
    nut_ups_name: str = ""
    # The Pi's usbhid-ups driver has pollinterval=1. Polling NUT faster would
    # only duplicate its cached values; one second captures every driver tick.
    nut_poll_seconds: float = 1.0
    # Retained only as a configuration compatibility field. Runtime power uses
    # live ups.efficiency and reports the former /0.80 value as a diagnostic.
    nut_power_multiplier: float = 1.25

    # Node shutdown remains deliberately disabled until a separately approved
    # maintenance window.  The API token and recovery-companion secrets are
    # read from protected files only when their features are enabled.
    resilience_shutdown_enabled: bool = False
    resilience_warning_seconds: float = 30.0
    resilience_restore_stable_seconds: float = 300.0
    recovery_companion_url: str = "http://10.0.1.206:8766"

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        values: dict[str, object] = {}
        for item in fields(defaults):
            default = getattr(defaults, item.name)
            raw = os.getenv(f"ENERGY_MANAGER_{item.name.upper()}")
            if raw is None:
                values[item.name] = default
            elif isinstance(default, bool):
                values[item.name] = raw.strip().lower() in {"1", "true", "yes", "on"}
            elif isinstance(default, int):
                values[item.name] = int(raw)
            elif isinstance(default, float):
                values[item.name] = float(raw)
            elif isinstance(default, Path):
                values[item.name] = Path(raw)
            else:
                values[item.name] = raw
        return cls(**values)

    def secret(self, name: str) -> str | None:
        return _secret(self.secret_dir / name)

    def configuration_revision(self) -> str:
        public = {
            item.name: str(getattr(self, item.name))
            for item in fields(self)
            if item.name not in {"data_dir", "secret_dir", "software_revision"}
        }
        return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()[:12]
