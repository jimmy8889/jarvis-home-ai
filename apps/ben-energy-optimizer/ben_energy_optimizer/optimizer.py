from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
from typing import Any

from .config import ENTITY, Settings


@dataclass(frozen=True)
class PriceSlot:
    start: datetime
    end: datetime
    import_price: float
    fit: float

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def _number(states: dict[str, dict[str, Any]], entity: str, default: float | None = None) -> float | None:
    try:
        value = float(states[entity]["state"])
        return value if math.isfinite(value) else default
    except (KeyError, TypeError, ValueError):
        return default


def _power_kw(states: dict[str, dict[str, Any]], entity: str) -> float | None:
    value = _number(states, entity)
    if value is None:
        return None
    unit = str(states.get(entity, {}).get("attributes", {}).get("unit_of_measurement", "kW")).lower()
    return value / 1000 if unit == "w" else value


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _price_window(state: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
    attrs = state.get("attributes", {})
    start = _timestamp(attrs.get("start_time"))
    end = _timestamp(attrs.get("end_time"))
    if not start or not end or not start <= now < end:
        return None
    duration = (end - start).total_seconds()
    return (start, end) if 240 <= duration <= 360 else None


def price_slots(states: dict[str, dict[str, Any]], now: datetime, horizon_hours: int = 36) -> list[PriceSlot]:
    fit_state = states.get(ENTITY["amber_fit"], {})
    import_state = states.get(ENTITY["amber_import"], {})
    fit_window = _price_window(fit_state, now)
    import_window = _price_window(import_state, now)
    if not fit_window or not import_window or fit_window != import_window:
        return []
    current_fit = _number(states, ENTITY["amber_fit"])
    current_import = _number(states, ENTITY["amber_import"])
    if current_fit is None or current_import is None:
        return []
    by_time: dict[datetime, dict[str, float]] = {}
    for key, label in (("amber_fit", "fit"), ("amber_import", "import_price")):
        forecast = states[ENTITY[key]].get("attributes", {}).get("forecast", [])
        if not isinstance(forecast, list):
            continue
        for point in forecast:
            if not isinstance(point, dict):
                continue
            stamp = _timestamp(point.get("time"))
            try:
                value = float(point.get("value"))
            except (TypeError, ValueError):
                continue
            if stamp and math.isfinite(value):
                by_time.setdefault(stamp, {})[label] = value
    result = [PriceSlot(fit_window[0], fit_window[1], current_import, current_fit)]
    ordered = sorted(t for t, v in by_time.items() if set(v) >= {"fit", "import_price"} and t >= fit_window[1])
    horizon = now + timedelta(hours=horizon_hours)
    for index, start in enumerate(ordered):
        if start >= horizon:
            break
        next_start = ordered[index + 1] if index + 1 < len(ordered) else start + timedelta(minutes=30)
        result.append(PriceSlot(start, min(next_start, horizon), by_time[start]["import_price"], by_time[start]["fit"]))
    return result


def dynamic_reserve_pct(settings: Settings, load_samples_kwh: list[float], hours_to_recovery: float) -> float:
    if len(load_samples_kwh) < 7:
        return settings.fallback_reserve_pct
    ordered = sorted(max(0.0, sample) for sample in load_samples_kwh)
    p90 = ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]
    reserve_kwh = p90 * max(1.0, hours_to_recovery) + 0.5
    return max(settings.min_soc_pct, min(100.0, reserve_kwh / settings.battery_capacity_kwh * 100))


def build_plan(
    states: dict[str, dict[str, Any]],
    settings: Settings,
    now: datetime | None = None,
    load_samples_kwh: list[float] | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    slots = price_slots(states, now, settings.horizon_hours)
    soc = _number(states, ENTITY["soc"])
    pv = _power_kw(states, ENTITY["pv"])
    load = _power_kw(states, ENTITY["load"])
    grid = _power_kw(states, ENTITY["grid"])
    buy = _number(states, ENTITY["buy_floor"], 0.05) or 0.05
    sell = _number(states, ENTITY["sell_floor"], 0.15) or 0.15
    enabled = states.get(ENTITY["enabled"], {}).get("state") == "on"
    manual = states.get(ENTITY["manual_mode"], {}).get("state", "Stopped")
    warnings: list[str] = []
    fresh = True
    # SOC changes slowly and HA does not refresh its timestamp when the value is
    # unchanged. The battery-power register is polled from the same Sigenergy
    # device and is therefore the authoritative liveness heartbeat for SOC.
    for key in ("battery", "pv", "load", "grid"):
        entity_state = states.get(ENTITY[key], {})
        stamp = _timestamp(entity_state.get("last_reported") or entity_state.get("last_updated"))
        value = _power_kw(states, ENTITY[key])
        if stamp is None or (now - stamp).total_seconds() > settings.telemetry_max_age_seconds or value is None:
            fresh = False
            warnings.append(f"{key}_telemetry_unavailable_or_stale")
    battery = _power_kw(states, ENTITY["battery"])
    if soc is None or not 0 <= soc <= 100 or pv is None or not 0 <= pv <= 100 or load is None or not 0 <= load <= 100 or grid is None or not -100 <= grid <= 100 or battery is None or not -100 <= battery <= 100:
        fresh = False
        warnings.append("telemetry_out_of_bounds")
    current = slots[0] if slots else None
    if current is None:
        warnings.append("amber_current_interval_invalid")
    hours_to_recovery = 6.0
    if slots:
        recoveries = [s for s in slots[1:] if s.import_price <= buy]
        if recoveries:
            hours_to_recovery = max(0.25, (recoveries[0].start - now).total_seconds() / 3600)
    reserve = dynamic_reserve_pct(settings, load_samples_kwh or [], hours_to_recovery)
    usable_kwh = max(0.0, ((soc or 0) - reserve) / 100 * settings.battery_capacity_kwh)
    room_kwh = max(0.0, (100 - (soc or 100)) / 100 * settings.battery_capacity_kwh)
    action = "self_consumption"
    battery_kw = 0.0
    site_grid_kw = 0.0
    export_limit_kw = settings.site_limit_kw
    reason = "Maximum self-consumption while waiting for an eligible price."
    expected_cost = expected_revenue = expected_wear = 0.0
    if manual != "Stopped":
        action = "manual_override"
        reason = "Persistent manual test has priority; Node-RED owns the setpoint."
    elif current and current.fit < 0:
        export_limit_kw = 0.0
        if current.import_price <= buy and room_kwh > 0.05:
            action = "charge"
            battery_kw = -min(settings.max_charge_kw, room_kwh / current.hours * settings.charge_efficiency, settings.site_limit_kw + max(0.0, (pv or 0) - (load or 0)))
            site_grid_kw = min(settings.site_limit_kw, max(0.0, (load or 0) - (pv or 0) - battery_kw))
            expected_cost = site_grid_kw * current.hours * current.import_price
            reason = "Negative FIT: zero export and charge below the buy ceiling."
        else:
            action = "zero_export"
            reason = "Negative FIT: grid export limit is zero and the battery follows site load."
    elif current:
        future_fit = max((s.fit for s in slots[1:] if s.fit >= sell), default=-math.inf)
        future_import = min((s.import_price for s in slots[1:] if s.import_price <= buy), default=math.inf)
        sell_margin = current.fit - settings.wear_per_kwh - settings.uncertainty_per_kwh
        if current.fit >= sell and usable_kwh > 0.02 and (current.fit >= future_fit - 0.005 or usable_kwh > settings.max_discharge_kw * current.hours):
            action = "discharge"
            battery_kw = min(settings.max_discharge_kw, usable_kwh * settings.discharge_efficiency / current.hours)
            site_grid_kw = -min(settings.site_limit_kw, max(0.0, battery_kw + (pv or 0) - (load or 0)))
            export_kwh = -site_grid_kw * current.hours
            expected_revenue = export_kwh * current.fit
            expected_wear = battery_kw * current.hours * settings.wear_per_kwh
            reason = "FIT is at/above the sell floor and this is the best retained-value window."
        elif current.import_price <= buy and room_kwh > 0.02:
            future_value = max(future_fit, min((s.import_price for s in slots[1:]), default=0.0))
            break_even = current.import_price / settings.charge_efficiency / settings.discharge_efficiency + settings.wear_per_kwh + settings.uncertainty_per_kwh
            if future_value > break_even and current.import_price <= future_import + 0.005:
                action = "charge"
                battery_kw = -min(settings.max_charge_kw, room_kwh / current.hours * settings.charge_efficiency, settings.site_limit_kw + max(0.0, (pv or 0) - (load or 0)))
                site_grid_kw = min(settings.site_limit_kw, max(0.0, (load or 0) - (pv or 0) - battery_kw))
                expected_cost = site_grid_kw * current.hours * current.import_price
                reason = "Import is below the buy ceiling and forecast resale/avoided cost clears losses, wear and uncertainty."
    allowed = bool(enabled and manual == "Stopped" and fresh and current)
    if not allowed and action not in {"manual_override"}:
        battery_kw = 0.0
        site_grid_kw = 0.0
        action = "self_consumption"
        reason = "Automatic actuation is disarmed or required live data is invalid."
    valid_until = current.end if current else now + timedelta(seconds=60)
    material = f"{now.isoformat()}:{action}:{battery_kw:.3f}:{site_grid_kw:.3f}"
    plan_id = "ben-" + hashlib.sha256(material.encode()).hexdigest()[:12]
    schedule = []
    for slot in slots:
        scheduled = "wait"
        if slot.fit >= sell:
            scheduled = "sell"
        elif slot.import_price <= buy:
            scheduled = "buy_candidate"
        schedule.append({"start": slot.start.isoformat(), "end": slot.end.isoformat(), "import_price": slot.import_price, "fit": slot.fit, "action": scheduled})
    next_buy = next((item for item in schedule if item["action"] == "buy_candidate"), None)
    next_sell = next((item for item in schedule if item["action"] == "sell"), None)
    return {
        "schema_version": 1, "revision": plan_id, "plan_id": plan_id,
        "generated_at": now.isoformat(), "valid_until": valid_until.isoformat(),
        "actuation_allowed": allowed, "action": action, "reason": reason,
        "battery_power_target_kw": round(battery_kw, 3),
        "site_grid_target_kw": round(site_grid_kw, 3),
        "grid_export_limit_kw": round(export_limit_kw, 3),
        "dynamic_reserve_pct": round(reserve, 2),
        "current_import_price": current.import_price if current else None,
        "current_fit": current.fit if current else None,
        "buy_ceiling": buy, "sell_floor": sell,
        "expected_charging_cost": round(expected_cost, 4),
        "expected_export_revenue": round(expected_revenue, 4),
        "expected_wear_cost": round(expected_wear, 4),
        "expected_net_benefit": round(expected_revenue - expected_cost - expected_wear, 4),
        "soc_pct": soc, "pv_kw": pv, "load_kw": load, "grid_kw": grid,
        "confidence": 0.8 if fresh and len(load_samples_kwh or []) >= 7 else 0.55,
        "warnings": sorted(set(warnings)), "schedule": schedule,
        "next_buy_window": next_buy,
        "next_sell_window": next_sell,
        "forecast_horizon_end": schedule[-1]["end"] if schedule else None,
        "predicted_soc_path": [
            {"time": now.isoformat(), "soc_pct": soc},
            {"time": valid_until.isoformat(), "soc_pct": soc, "reserve_pct": round(reserve, 2)},
        ],
    }
