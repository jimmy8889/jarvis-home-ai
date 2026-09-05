from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Telemetry:
    measured_at: datetime = field(default_factory=utcnow)
    pv_kw: float | None = None
    pv1_kw: float | None = None
    pv2_kw: float | None = None
    pv3_kw: float | None = None
    pv_north_kw: float | None = None
    pv_south_kw: float | None = None
    load_kw: float | None = None
    load_total_kw: float | None = None
    load_backup_kw: float | None = None
    load_source: str = "total_house_load"
    load_balance_error_kw: float | None = None
    grid_kw: float | None = None  # positive import, negative export
    flow_grid_kw: float | None = None
    meter_phase_power_kw: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meter_phase_voltage_v: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meter_phase_current_a: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meter_phase_frequency_hz: tuple[float, float, float] = (0.0, 0.0, 0.0)
    meter_phase_power_factor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    grid_state: str = "unknown"
    grid_online: bool | None = None
    grid_phase_present: tuple[bool, bool, bool] = (False, False, False)
    battery_kw: float | None = None  # positive discharge, negative charge
    inverter_kw: float | None = None
    soc_pct: float | None = None
    soh_pct: float | None = None
    battery_temperature_c: float | None = None
    battery_voltage_v: float | None = None
    inverter_temperature_c: float | None = None
    environment_temperature_c: float | None = None
    gfci_ma: float | None = None
    isolation_resistance_kohm: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    fault_words: tuple[int, int, int] = (0, 0, 0)
    active_faults: tuple[str, ...] = ()
    fault_count: int = 0
    fault_severity: str = "none"
    last_fault: str = "none"
    battery_fault_words: tuple[int, int, int, int] = (0, 0, 0, 0)
    battery_warning_words: tuple[int, int, int, int] = (0, 0, 0, 0)
    battery_cycle_count: int | None = None
    inverter_status: str = "unknown"
    sample_sequence: int = 0
    sample_started_at: datetime | None = None
    sample_completed_at: datetime | None = None
    sample_skew_ms: float | None = None
    cycle_duration_ms: float | None = None
    fast_read_mode: str = "combined"
    modbus_read_errors: int = 0
    modbus_reconnects: int = 0
    energy_counters: dict[str, float] = field(default_factory=dict)
    inverter_identity: dict[str, Any] = field(default_factory=dict)
    app_mode: int | None = None
    anti_reflux_mode: int | None = None
    export_limit: int | None = None
    charge_enabled: bool | None = None
    discharge_enabled: bool | None = None

    @property
    def healthy(self) -> bool:
        required = (self.pv_kw, self.load_kw, self.grid_kw, self.battery_kw, self.soc_pct, self.soh_pct)
        return all(value is not None for value in required) and not any(self.fault_words)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["measured_at"] = self.measured_at.isoformat()
        for key in ("sample_started_at", "sample_completed_at"):
            value = result.get(key)
            if isinstance(value, datetime):
                result[key] = value.isoformat()
        result["healthy"] = self.healthy
        result["age_seconds"] = max(0.0, (utcnow() - self.measured_at).total_seconds())
        return result

    def battery_model(self, capacity_kwh: float, floor_pct: float, discharge_eff: float, charge_eff: float) -> dict[str, float]:
        soc = max(0.0, min(100.0, float(self.soc_pct or 0)))
        soh = max(0.0, min(100.0, float(self.soh_pct or 0)))
        effective = capacity_kwh * soh / 100
        gross = effective * soc / 100
        usable = effective * max(soc - floor_pct, 0) / 100
        return {
            "effective_capacity_kwh": effective,
            "gross_stored_kwh": gross,
            "usable_above_floor_kwh": usable,
            "extractable_ac_kwh": usable * discharge_eff,
            "energy_to_full_ac_kwh": max(0.0, effective - gross) / max(charge_eff, 0.01),
        }


@dataclass
class PriceInterval:
    source: str
    channel: str
    start: datetime
    end: datetime
    price_per_kwh: float
    received_at: datetime = field(default_factory=utcnow)
    published_at: datetime | None = None
    estimate: bool = False
    raw_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceState:
    ev_soc_pct: float | None = None
    ev_plugged: bool | None = None
    ev_home: bool | None = None
    ev_ble_home: bool | None = None
    ev_garage_preset: float | None = None
    ev_car_locked: bool | None = None
    ev_charge_port_open: bool | None = None
    ev_charge_port_latch: str | None = None
    ev_climate_on: bool | None = None
    ev_climate_target_c: float | None = None
    ev_interior_temp_c: float | None = None
    ev_exterior_temp_c: float | None = None
    ev_asleep: bool | None = None
    ev_windows_open: bool | None = None
    ev_steering_heat_on: bool | None = None
    ev_defrost_on: bool | None = None
    ev_range_km: float | None = None
    ev_minutes_to_limit: float | None = None
    ev_charging_state: str | None = None
    ev_ble_available: bool = False
    ev_charging: bool = False
    ev_amps: int = 0
    ev_power_kw: float = 0.0
    ev_limit_pct: int = 80
    ev_last_command_at: datetime | None = None
    ev_lease_until: datetime | None = None
    hot_water_on: bool = False
    hot_water_available: bool = False
    hot_water_confirmed: bool = False
    hot_water_power_kw: float = 0.0
    hot_water_runtime_hours: float = 0.0
    hot_water_last_transition: datetime | None = None
    hot_water_source: str = "off"


@dataclass
class Command:
    mode: str
    battery_target_kw: float = 0.0
    site_export_target_kw: float = 0.0
    protected_soc_pct: float = 5.0
    zero_export: bool = False
    pv_charge_limit_raw: int = 1100
    ev_on: bool = False
    ev_amps: int = 0
    ev_target_soc_pct: int = 80
    hot_water_on: bool = False
    hot_water_source: str = "off"
    reason: str = "safe_self_consumption"
    generated_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    semantic_hash: str = ""
    battery_semantic_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("generated_at", "expires_at"):
            value = result[key]
            if isinstance(value, datetime):
                result[key] = value.isoformat()
        return result


def command_semantic_hash(command: Command) -> str:
    physical = {
        "mode": command.mode,
        "battery_target_kw": round(command.battery_target_kw, 1),
        "site_export_target_kw": round(command.site_export_target_kw, 1),
        "protected_soc_pct": int(command.protected_soc_pct + 0.999),
        "zero_export": command.zero_export,
        "pv_charge_limit_raw": max(0, min(1100, int(command.pv_charge_limit_raw))),
        "ev_on": command.ev_on,
        "ev_amps": command.ev_amps,
        "ev_target_soc_pct": command.ev_target_soc_pct if command.ev_on else None,
        "hot_water_on": command.hot_water_on,
        "hot_water_source": command.hot_water_source,
    }
    if command.mode in {"export", "grid_charge"} and command.expires_at is not None:
        physical["force_interval_start"] = int(command.generated_at.timestamp()) // 300 * 300
        physical["force_interval_end"] = int(command.expires_at.timestamp())
    return hashlib.sha256(json.dumps(physical, sort_keys=True).encode()).hexdigest()[:20]
