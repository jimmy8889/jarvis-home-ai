from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .models import Telemetry
from .nut import NutPowerState


@dataclass(frozen=True)
class GridHealth:
    state: str
    confidence: str
    reason: str
    disagreement: bool
    saj_fresh: bool
    nut_fresh: bool
    utility_source: str
    measured_at: datetime

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["measured_at"] = self.measured_at.isoformat()
        return value


@dataclass(frozen=True)
class ProtectedSupply:
    state: str
    confidence: str
    reason: str
    measured_at: datetime

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["measured_at"] = self.measured_at.isoformat()
        return value


def _saj_evidence(telemetry: Telemetry | None, now: datetime) -> tuple[str | None, bool]:
    if telemetry is None or (now - telemetry.measured_at).total_seconds() > 5:
        return None, False
    phases = tuple(bool(value) for value in telemetry.grid_phase_present)
    if all(phases) and telemetry.grid_state not in {"lost", "offline"}:
        return "healthy", True
    if any(phases):
        return "degraded", True
    if telemetry.grid_online is False or telemetry.grid_state in {"lost", "offline"}:
        return "lost", True
    return "unknown", True


def _nut_evidence(state: NutPowerState, now: datetime) -> tuple[str | None, bool, str]:
    fresh = bool(
        state.available
        and state.measured_at
        and (now - state.measured_at).total_seconds() <= 3
    )
    if not fresh:
        return None, False, "unknown"
    status = set((state.status or "").split())
    if "OB" in status:
        return "lost", True, "ups_battery"
    input_ok = bool(state.input_voltage_v and state.input_voltage_v >= 180)
    if "OL" in status and input_ok:
        return "healthy", True, "mains"
    if "OL" in status:
        return "degraded", True, "mains"
    return "unknown", True, "unknown"


def fuse_grid_health(
    telemetry: Telemetry | None,
    nut: NutPowerState,
    now: datetime | None = None,
) -> tuple[GridHealth, ProtectedSupply]:
    now = now or datetime.now(UTC)
    saj, saj_fresh = _saj_evidence(telemetry, now)
    nut_grid, nut_fresh, supply_state = _nut_evidence(nut, now)
    disagreement = bool(
        saj_fresh and nut_fresh and saj in {"healthy", "lost"}
        and nut_grid in {"healthy", "lost"} and saj != nut_grid
    )
    if disagreement:
        grid = GridHealth(
            "degraded", "medium", f"SAJ reports {saj}; UPS reports {nut_grid}",
            True, saj_fresh, nut_fresh, "disagreement", now,
        )
    elif saj_fresh:
        confidence = "high" if saj in {"healthy", "lost"} else "medium"
        grid = GridHealth(
            saj or "unknown", confidence, "fresh SAJ three-phase telemetry",
            False, True, nut_fresh, "saj", now,
        )
    elif nut_fresh:
        # A UPS input is single-point evidence, so it can confirm loss but only
        # provide a degraded-confidence healthy fallback.
        state = "lost" if nut_grid == "lost" else "degraded" if nut_grid == "healthy" else "unknown"
        grid = GridHealth(
            state, "medium" if state != "unknown" else "low",
            "SAJ stale; inferred from fresh NUT input/status", False, False, True, "nut_fallback", now,
        )
    else:
        grid = GridHealth(
            "unknown", "unavailable", "SAJ and NUT evidence stale", False,
            False, False, "none", now,
        )
    protected = ProtectedSupply(
        supply_state,
        "high" if nut_fresh and supply_state != "unknown" else "unavailable",
        "fresh NUT OL/input" if supply_state == "mains" else "fresh NUT OB" if supply_state == "ups_battery" else "NUT unavailable",
        now,
    )
    return grid, protected


def allocate_ups_power(state: NutPowerState) -> dict[str, float | str | None]:
    """Allocate protected output and conversion loss without double counting."""

    def number(name: str) -> float | None:
        try:
            return max(0.0, float(state.variables[name]))
        except (KeyError, TypeError, ValueError):
            return None

    rack = number("outlet.realpower")
    if rack is None:
        rack = number("outlet.0.realpower")
    office = number("outlet.1.realpower") or 0.0
    output = state.raw_real_power_w
    if rack is None and output is not None:
        rack = max(0.0, output - office)
    rack = rack or 0.0
    protected_output = max(0.0, output if output is not None else rack + office)
    # Guard inconsistent per-outlet samples while preserving total conservation.
    subtotal = rack + office
    if subtotal > 0 and protected_output > 0 and abs(subtotal - protected_output) > 25:
        scale = protected_output / subtotal
        rack *= scale
        office *= scale
    wall = state.server_rack_power_w if state.server_rack_power_w is not None else protected_output
    loss = max(0.0, wall - protected_output)
    share_total = rack + office
    rack_loss = loss * rack / share_total if share_total else loss
    office_loss = loss - rack_loss
    return {
        "rack_output_w": rack,
        "office_output_w": office,
        "protected_output_w": protected_output,
        "conversion_loss_w": loss,
        "wall_input_w": wall,
        "rack_wall_allocated_w": rack + rack_loss,
        "office_wall_allocated_w": office + office_loss,
        "confidence": state.confidence,
    }


def resilience_stage(
    grid_state: str,
    runtime_seconds: float | None,
    charge_pct: float | None,
    house_soc_pct: float | None,
) -> str:
    if grid_state != "lost":
        return "normal"
    runtime_minutes = runtime_seconds / 60 if runtime_seconds is not None else None
    if (runtime_minutes is not None and runtime_minutes <= 8) or (house_soc_pct is not None and house_soc_pct <= 8):
        return "urgent_graceful_shutdown"
    if (runtime_minutes is not None and runtime_minutes <= 12) or (charge_pct is not None and charge_pct <= 30):
        return "orderly_shutdown"
    if (runtime_minutes is not None and runtime_minutes <= 20) or (charge_pct is not None and charge_pct <= 50) or (house_soc_pct is not None and house_soc_pct <= 10):
        return "warning_arm"
    return "grid_outage_monitoring"
