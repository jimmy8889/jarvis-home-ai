from __future__ import annotations

from dataclasses import dataclass, fields
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ha_url: str = "http://127.0.0.1:8123"
    nodered_plan_url: str = "http://127.0.0.1:1880/ben-energy-optimizer/plan"
    ha_token_file: Path = Path("/run/secrets/home_assistant_token")
    data_dir: Path = Path("/data")
    bind_host: str = "0.0.0.0"
    bind_port: int = 8786
    interval_seconds: int = 300
    horizon_hours: int = 36
    timezone: str = "Australia/Brisbane"
    battery_capacity_kwh: float = 48.0
    min_soc_pct: float = 5.0
    fallback_reserve_pct: float = 14.0
    max_charge_kw: float = 25.0
    max_discharge_kw: float = 25.0
    site_limit_kw: float = 25.0
    charge_efficiency: float = 0.90
    discharge_efficiency: float = 0.90
    wear_per_kwh: float = 0.08
    uncertainty_per_kwh: float = 0.02
    telemetry_max_age_seconds: int = 330

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        values = {}
        for field in fields(defaults):
            raw = os.getenv(f"BEN_ENERGY_OPTIMIZER_{field.name.upper()}")
            default = getattr(defaults, field.name)
            if raw is None:
                values[field.name] = default
            elif isinstance(default, int):
                values[field.name] = int(raw)
            elif isinstance(default, float):
                values[field.name] = float(raw)
            elif isinstance(default, Path):
                values[field.name] = Path(raw)
            else:
                values[field.name] = raw
        return cls(**values)


ENTITY = {
    "amber_fit": "sensor.amber_express_trader_container_feed_in_price",
    "amber_import": "sensor.amber_express_trader_container_general_price",
    "soc": "sensor.site_battery_soc_nr_4",
    "battery": "sensor.site_battery_power_nr_4",
    "pv": "sensor.site_pv_power_nr_4",
    "load": "sensor.site_load_power_nr_4",
    "grid": "sensor.site_grid_power_nr_4",
    "buy_floor": "input_number.ben_optimizer_buy_price",
    "sell_floor": "input_number.ben_optimizer_sell_price",
    "enabled": "input_boolean.ben_optimizer_enabled",
    "manual_mode": "input_select.ben_manual_mode",
    "manual_rate": "input_number.ben_manual_grid_rate",
}
