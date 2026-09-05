from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TelemetryHealth:
    """Measurement ages required before either planner may actuate.

    The SAJ SOC entity can legitimately retain an old Home Assistant timestamp
    while its numeric value remains unchanged.  A separately polled power
    entity from the same SAJ Modbus integration is therefore the explicit
    source heartbeat for that value.  ``None`` means that freshness could not
    be established and must never be treated as healthy.
    """

    soc_source_heartbeat_age_seconds: float | None
    pv_age_seconds: float | None
    load_age_seconds: float | None
    pv_source_heartbeat_age_seconds: float | None = None


@dataclass
class Slot:
    start: datetime
    duration_h: float
    solar_kw: float
    solar_low_kw: float
    solar_high_kw: float
    load_kw: float
    import_price: float
    export_price: float
    price_source: str
    hot_water_kw: float = 0.0
    hot_water_control_mode: str = "off"
    ev_kw: float = 0.0
    ev_charge_amps: int = 0
    ev_power_target_kw: float = 0.0
    ev_charge_source: str = "none"


@dataclass
class DispatchInterval:
    start: datetime
    duration_minutes: float
    solar_kw: float
    solar_low_kw: float
    load_kw: float
    hot_water_kw: float
    ev_kw: float
    import_price: float
    export_price: float
    battery_kw: float
    site_grid_kw: float
    pv_curtailment_kw: float
    soc_start_pct: float
    soc_end_pct: float
    cost: float
    price_source: str
    hot_water_control_mode: str = "off"
    ev_charge_source: str = "none"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["start"] = self.start.isoformat()
        return result


@dataclass
class Plan:
    plan_id: str
    generated_at: datetime
    valid_until: datetime
    mode: str
    actuation_allowed: bool
    action: str
    reason: str
    confidence: float
    battery_power_target_kw: float
    site_export_target_kw: float
    pv_export_command: str
    pv_curtailment_target_kw: float
    hot_water_command: str
    ev_action: str
    ev_target_soc_pct: float
    ev_required_kwh: float
    ev_charge_amps_target: int
    ev_power_target_kw: float
    ev_charge_source: str
    ev_solar_energy_kwh: float
    ev_fallback_energy_kwh: float
    ev_charge_start: datetime | None
    ev_charge_end: datetime | None
    ev_estimated_cost: float
    morning_takeover: datetime | None
    evening_crossover: datetime | None
    expected_cost: float
    expected_revenue: float
    expected_wear_cost: float
    hot_water_solar_energy_kwh: float = 0.0
    hot_water_battery_energy_kwh: float = 0.0
    hot_water_grid_energy_kwh: float = 0.0
    ev_battery_energy_kwh: float = 0.0
    ev_grid_energy_kwh: float = 0.0
    house_total_energy_kwh: float = 0.0
    house_solar_energy_kwh: float = 0.0
    house_battery_energy_kwh: float = 0.0
    house_grid_energy_kwh: float = 0.0
    battery_export_energy_kwh: float = 0.0
    solar_export_energy_kwh: float = 0.0
    total_export_energy_kwh: float = 0.0
    minimum_sell_price: float = 0.08
    effective_sell_price: float = 0.08
    warnings: list[str] = field(default_factory=list)
    intervals: list[DispatchInterval] = field(default_factory=list)
    solar_potential_kw: float = 0.0
    solar_actual_kw: float = 0.0
    solar_curtailed_estimate_kw: float = 0.0
    solar_live_correction_factor: float = 1.0
    solar_potential_source: str = "unavailable"
    solar_calibration_report: dict[str, Any] = field(default_factory=dict)
    hot_water_control_mode: str = "off"
    hot_water_scheduled_hours: float = 0.0
    hot_water_unmet_hours: float = 0.0
    battery_mode: str = "hold"
    battery_charge_target_kw: float = 0.0
    battery_discharge_target_kw: float = 0.0
    protected_soc_pct: float = 5.0
    battery_capacity_kwh: float = 0.0
    battery_stored_energy_kwh: float | None = None
    battery_energy_consistent: bool | None = None
    ev_mandatory: bool = False
    ev_grid_allowed: bool = False
    ev_unmet_kwh: float = 0.0
    live_fit_price: float | None = None
    live_import_price: float | None = None
    price_interval_start: datetime | None = None
    price_interval_end: datetime | None = None
    source_timestamps: dict[str, str | None] = field(default_factory=dict)
    software_version: str = "0.2.0"
    config_fingerprint: str = ""
    command_semantic_hash: str = ""
    house_reserve_soc_pct: float = 5.0
    ev_schedule_amps: int = 0
    ev_live_target_amps: int = 0
    ev_source_budget: str = "none"
    hot_water_service_target_hours: float = 3.05
    hot_water_rescue_source: str = "grid_only"
    dispatch_timestamps: dict[str, str | None] = field(default_factory=dict)

    def to_dict(self, *, interval_limit: int | None = None) -> dict[str, Any]:
        intervals = self.intervals if interval_limit is None else self.intervals[:interval_limit]
        return {
            "schema_version": 2,
            "plan_id": self.plan_id,
            "generated_at": self.generated_at.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "mode": self.mode,
            "actuation_allowed": self.actuation_allowed,
            "action": self.action,
            "reason": self.reason,
            "battery_mode": self.battery_mode,
            "battery_charge_target_kw": round(self.battery_charge_target_kw, 3),
            "battery_discharge_target_kw": round(self.battery_discharge_target_kw, 3),
            "protected_soc_pct": round(self.protected_soc_pct, 1),
            "battery_capacity_kwh": round(self.battery_capacity_kwh, 3),
            "battery_stored_energy_kwh": (
                round(self.battery_stored_energy_kwh, 3)
                if self.battery_stored_energy_kwh is not None
                else None
            ),
            "battery_energy_consistent": self.battery_energy_consistent,
            "confidence": round(self.confidence, 3),
            "battery_power_target_kw": round(self.battery_power_target_kw, 3),
            "site_export_target_kw": round(self.site_export_target_kw, 3),
            "pv_export_command": self.pv_export_command,
            "pv_curtailment_target_kw": round(self.pv_curtailment_target_kw, 3),
            "hot_water_command": self.hot_water_command,
            "hot_water_control_mode": self.hot_water_control_mode,
            "hot_water_scheduled_hours": round(self.hot_water_scheduled_hours, 2),
            "hot_water_unmet_hours": round(self.hot_water_unmet_hours, 2),
            "ev_action": self.ev_action,
            "ev_target_soc_pct": round(self.ev_target_soc_pct, 1),
            "ev_required_kwh": round(self.ev_required_kwh, 2),
            "ev_charge_amps_target": self.ev_charge_amps_target,
            "ev_power_target_kw": round(self.ev_power_target_kw, 3),
            "ev_charge_source": self.ev_charge_source,
            "ev_solar_energy_kwh": round(self.ev_solar_energy_kwh, 2),
            "ev_fallback_energy_kwh": round(self.ev_fallback_energy_kwh, 2),
            "ev_mandatory": self.ev_mandatory,
            "ev_grid_allowed": self.ev_grid_allowed,
            "ev_unmet_kwh": round(self.ev_unmet_kwh, 2),
            "ev_charge_start": self.ev_charge_start.isoformat() if self.ev_charge_start else None,
            "ev_charge_end": self.ev_charge_end.isoformat() if self.ev_charge_end else None,
            "ev_estimated_cost": round(self.ev_estimated_cost, 2),
            "morning_takeover": self.morning_takeover.isoformat() if self.morning_takeover else None,
            "evening_crossover": self.evening_crossover.isoformat() if self.evening_crossover else None,
            "expected_cost": round(self.expected_cost, 3),
            "expected_revenue": round(self.expected_revenue, 3),
            "expected_wear_cost": round(self.expected_wear_cost, 3),
            "hot_water_solar_energy_kwh": round(self.hot_water_solar_energy_kwh, 2),
            "hot_water_battery_energy_kwh": round(self.hot_water_battery_energy_kwh, 2),
            "hot_water_grid_energy_kwh": round(self.hot_water_grid_energy_kwh, 2),
            "ev_battery_energy_kwh": round(self.ev_battery_energy_kwh, 2),
            "ev_grid_energy_kwh": round(self.ev_grid_energy_kwh, 2),
            "house_total_energy_kwh": round(self.house_total_energy_kwh, 2),
            "house_solar_energy_kwh": round(self.house_solar_energy_kwh, 2),
            "house_battery_energy_kwh": round(self.house_battery_energy_kwh, 2),
            "house_grid_energy_kwh": round(self.house_grid_energy_kwh, 2),
            "battery_export_energy_kwh": round(self.battery_export_energy_kwh, 2),
            "solar_export_energy_kwh": round(self.solar_export_energy_kwh, 2),
            "total_export_energy_kwh": round(self.total_export_energy_kwh, 2),
            "minimum_sell_price": round(self.minimum_sell_price, 6),
            "effective_sell_price": round(self.effective_sell_price, 6),
            "solar_potential_kw": round(self.solar_potential_kw, 3),
            "solar_actual_kw": round(self.solar_actual_kw, 3),
            "solar_curtailed_estimate_kw": round(self.solar_curtailed_estimate_kw, 3),
            "solar_live_correction_factor": round(self.solar_live_correction_factor, 3),
            "solar_potential_source": self.solar_potential_source,
            "solar_calibration_report": self.solar_calibration_report,
            "live_fit_price": (
                round(self.live_fit_price, 6) if self.live_fit_price is not None else None
            ),
            "live_import_price": (
                round(self.live_import_price, 6)
                if self.live_import_price is not None
                else None
            ),
            "price_interval_start": (
                self.price_interval_start.isoformat() if self.price_interval_start else None
            ),
            "price_interval_end": (
                self.price_interval_end.isoformat() if self.price_interval_end else None
            ),
            "source_timestamps": self.source_timestamps,
            "software_version": self.software_version,
            "config_fingerprint": self.config_fingerprint,
            "command_semantic_hash": self.command_semantic_hash,
            "house_reserve_soc_pct": round(self.house_reserve_soc_pct, 1),
            "ev_schedule_amps": self.ev_schedule_amps,
            "ev_live_target_amps": self.ev_live_target_amps,
            "ev_source_budget": self.ev_source_budget,
            "hot_water_service_target_hours": round(
                self.hot_water_service_target_hours, 2
            ),
            "hot_water_rescue_source": self.hot_water_rescue_source,
            "dispatch_timestamps": self.dispatch_timestamps,
            "warnings": self.warnings,
            "intervals": [item.to_dict() for item in intervals],
        }
