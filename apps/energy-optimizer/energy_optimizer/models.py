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
    warnings: list[str] = field(default_factory=list)
    intervals: list[DispatchInterval] = field(default_factory=list)
    solar_potential_kw: float = 0.0
    solar_actual_kw: float = 0.0
    solar_curtailed_estimate_kw: float = 0.0
    solar_live_correction_factor: float = 1.0
    solar_potential_source: str = "unavailable"

    def to_dict(self, *, interval_limit: int | None = None) -> dict[str, Any]:
        intervals = self.intervals if interval_limit is None else self.intervals[:interval_limit]
        return {
            "schema_version": 1,
            "plan_id": self.plan_id,
            "generated_at": self.generated_at.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "mode": self.mode,
            "actuation_allowed": self.actuation_allowed,
            "action": self.action,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "battery_power_target_kw": round(self.battery_power_target_kw, 3),
            "site_export_target_kw": round(self.site_export_target_kw, 3),
            "pv_export_command": self.pv_export_command,
            "pv_curtailment_target_kw": round(self.pv_curtailment_target_kw, 3),
            "hot_water_command": self.hot_water_command,
            "ev_action": self.ev_action,
            "ev_target_soc_pct": round(self.ev_target_soc_pct, 1),
            "ev_required_kwh": round(self.ev_required_kwh, 2),
            "ev_charge_amps_target": self.ev_charge_amps_target,
            "ev_power_target_kw": round(self.ev_power_target_kw, 3),
            "ev_charge_source": self.ev_charge_source,
            "ev_solar_energy_kwh": round(self.ev_solar_energy_kwh, 2),
            "ev_fallback_energy_kwh": round(self.ev_fallback_energy_kwh, 2),
            "ev_charge_start": self.ev_charge_start.isoformat() if self.ev_charge_start else None,
            "ev_charge_end": self.ev_charge_end.isoformat() if self.ev_charge_end else None,
            "ev_estimated_cost": round(self.ev_estimated_cost, 2),
            "morning_takeover": self.morning_takeover.isoformat() if self.morning_takeover else None,
            "evening_crossover": self.evening_crossover.isoformat() if self.evening_crossover else None,
            "expected_cost": round(self.expected_cost, 3),
            "expected_revenue": round(self.expected_revenue, 3),
            "expected_wear_cost": round(self.expected_wear_cost, 3),
            "solar_potential_kw": round(self.solar_potential_kw, 3),
            "solar_actual_kw": round(self.solar_actual_kw, 3),
            "solar_curtailed_estimate_kw": round(self.solar_curtailed_estimate_kw, 3),
            "solar_live_correction_factor": round(self.solar_live_correction_factor, 3),
            "solar_potential_source": self.solar_potential_source,
            "warnings": self.warnings,
            "intervals": [item.to_dict() for item in intervals],
        }
