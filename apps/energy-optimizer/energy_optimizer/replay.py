from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .config import Settings
from .models import DispatchInterval, Slot
from .optimizer import EnergyOptimizer
from .state import LearningState


BRISBANE = ZoneInfo("Australia/Brisbane")


@dataclass
class ReplayDay:
    date: str
    baseline_net_benefit: float
    optimized_net_benefit: float
    baseline_import_kwh: float
    optimized_import_kwh: float
    baseline_negative_fit_export_kwh: float
    optimized_curtailed_kwh: float
    baseline_morning_soc_pct: float | None
    optimized_morning_soc_pct: float | None
    baseline_evening_soc_pct: float | None
    optimized_evening_soc_pct: float | None
    baseline_full_cycle: bool
    morning_target_feasible: bool
    optimized_morning_target: bool
    optimized_evening_target: bool
    evening_target_feasible: bool
    hot_water_blocks_available: int
    hot_water_scheduled_hours: float
    ev_50km_naive_cost: float | None
    ev_50km_optimized_cost: float | None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float("inf") else default


def _local_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BRISBANE)
    return parsed.astimezone(BRISBANE)


def _crossover(slots: list[Slot]) -> tuple[datetime | None, datetime | None]:
    morning = None
    evening = None
    for index, slot in enumerate(slots[:-1]):
        following = slots[index + 1]
        hour = slot.start.hour + slot.start.minute / 60
        above = slot.solar_kw >= slot.load_kw + 0.3 and following.solar_kw >= following.load_kw + 0.3
        below = slot.solar_kw < slot.load_kw and following.solar_kw < following.load_kw
        if morning is None and 5 <= hour <= 10.5 and above:
            morning = slot.start
        if evening is None and 13 <= hour <= 20 and below:
            if any(item.solar_kw >= item.load_kw + 0.3 for item in slots[max(0, index - 12):index]):
                evening = slot.start
    return morning, evening


def _value_at(intervals: list[dict[str, Any]], when: datetime | None, key: str) -> float | None:
    if when is None:
        return None
    candidate = min(intervals, key=lambda item: abs((_local_time(item["timestamp"]) - when).total_seconds()))
    return _float(candidate.get(key), default=float("nan"))


def _dispatch_value_at(intervals: list[DispatchInterval], when: datetime | None) -> float | None:
    if when is None or not intervals:
        return None
    candidate = min(intervals, key=lambda item: abs((item.start - when).total_seconds()))
    return candidate.soc_start_pct


def _schedule_hot_water(slots: list[Slot], evening: datetime | None, settings: Settings) -> list[Slot]:
    deadline = datetime.combine(slots[0].start.date(), time(settings.hot_water_latest_hour), BRISBANE)
    if evening:
        deadline = min(deadline, evening)
    candidates = [slot for slot in slots if slot.start < deadline]
    selected = sorted(
        candidates,
        key=lambda slot: (
            max(0.0, slot.export_price)
            if slot.solar_kw - slot.load_kw >= settings.hot_water_kw
            else slot.import_price,
            slot.start,
        ),
    )[:6]
    return selected


def _morning_target_feasible(
    slots: list[Slot],
    morning: datetime | None,
    evening: datetime | None,
    initial_soc: float,
    settings: Settings,
) -> bool:
    if morning is None:
        return False
    required_stored_kwh = max(
        0.0,
        settings.battery_capacity_kwh
        * (initial_soc - settings.battery_morning_target_soc_pct)
        / 100,
    )
    valuable_stored_kwh = 0.0
    for slot in slots:
        if slot.start >= morning:
            break
        household_output_kw = slot.load_kw if slot.import_price > settings.battery_wear_per_kwh else 0.0
        export_output_kw = 0.0
        if slot.export_price > settings.battery_wear_per_kwh + settings.grid_charge_uncertainty_per_kwh:
            export_output_kw = max(0.0, settings.battery_max_discharge_kw - household_output_kw)
        valuable_stored_kwh += (
            household_output_kw + export_output_kw
        ) * slot.duration_h / settings.battery_discharge_efficiency
    morning_target = settings.battery_capacity_kwh * settings.battery_morning_target_soc_pct / 100
    evening_target = settings.battery_capacity_kwh * settings.battery_evening_target_soc_pct / 100
    post_morning_surplus = sum(
        max(0.0, slot.solar_low_kw - slot.load_kw) * slot.duration_h * settings.battery_charge_efficiency
        for slot in slots
        if slot.start >= morning and (evening is None or slot.start <= evening)
    )
    can_refill = morning_target + post_morning_surplus >= evening_target
    before = [slot for slot in slots if slot.start < morning]
    after = [slot for slot in slots if slot.start >= morning]
    best_early = max((max(slot.import_price, slot.export_price) for slot in before), default=0.0)
    best_later = max((max(slot.import_price, slot.export_price) for slot in after), default=0.0)
    exceptional_value = best_early > (
        best_later + settings.battery_wear_per_kwh + settings.grid_charge_uncertainty_per_kwh
    )
    return valuable_stored_kwh + 0.25 >= required_stored_kwh and (can_refill or exceptional_value)


def _ev_window_cost(
    intervals: list[dict[str, Any]],
    day: datetime,
    *,
    optimized: bool,
    required_kwh: float = 50 * 0.18 * 1.20,
    charge_kw: float = 3.7,
) -> float | None:
    start = datetime.combine(day.date(), time(17), BRISBANE)
    end = datetime.combine(day.date() + timedelta(days=1), time(7), BRISBANE)
    candidates = [item for item in intervals if start <= _local_time(item["timestamp"]) < end]
    if not candidates:
        return None
    if optimized:
        candidates.sort(key=lambda item: (_float(item.get("import_price"), 1.0), _local_time(item["timestamp"])))
    else:
        candidates.sort(key=lambda item: _local_time(item["timestamp"]))
    remaining = required_kwh
    cost = 0.0
    for item in candidates:
        allocated = min(remaining, charge_kw * 0.5)
        cost += allocated * _float(item.get("import_price"), 0.20)
        remaining -= allocated
        if remaining <= 1e-9:
            return cost
    return None


def _day_slots(intervals: list[dict[str, Any]]) -> list[Slot]:
    return [
        Slot(
            start=_local_time(item["timestamp"]),
            duration_h=0.5,
            solar_kw=max(0.0, _float(item.get("solar_kw"))),
            solar_low_kw=max(0.0, _float(item.get("solar_kw")) * 0.90),
            solar_high_kw=max(0.0, _float(item.get("solar_kw")) * 1.05),
            load_kw=max(0.2, _float(item.get("load_kw"), 1.67)),
            import_price=_float(item.get("import_price"), 0.20),
            export_price=_float(item.get("export_price"), 0.0),
            price_source="historical_actual",
        )
        for item in intervals
    ]


def _daily_counter(payload: dict[str, Any], date: str, key: str, fallback: float) -> float:
    record = next((item for item in payload.get("daily", []) if item.get("date") == date), None)
    return _float(record.get(key), fallback) if record else fallback


def run_replay(payload: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings()
    optimizer = EnergyOptimizer(settings, LearningState(Path("/dev/null")))
    source = sorted(payload.get("intervals", []), key=lambda item: item["timestamp"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in source:
        grouped[_local_time(item["timestamp"]).date().isoformat()].append(item)

    days: list[ReplayDay] = []
    for date, actual in sorted(grouped.items()):
        if len(actual) < 44:
            continue
        slots = _day_slots(actual)
        morning, evening = _crossover(slots)
        initial_soc = _float(actual[0].get("soc_pct"), 50.0)
        dispatch = optimizer._dispatch(slots, initial_soc, settings.battery_capacity_kwh, evening, morning)
        baseline_import = sum(max(0.0, _float(item.get("grid_kw"))) * 0.5 for item in actual)
        baseline_export = sum(max(0.0, -_float(item.get("grid_kw"))) * 0.5 for item in actual)
        baseline_revenue = sum(
            max(0.0, -_float(item.get("grid_kw"))) * 0.5 * _float(item.get("export_price")) for item in actual
        )
        baseline_cost = sum(
            max(0.0, _float(item.get("grid_kw"))) * 0.5 * _float(item.get("import_price")) for item in actual
        )
        discharge = _daily_counter(payload, date, "battery_discharge_kwh", 0.0)
        baseline_net = baseline_revenue - baseline_cost - discharge * settings.battery_wear_per_kwh
        optimized_net = -sum(item.cost for item in dispatch)
        maximum_import = max((slot.import_price for slot in slots), default=0.20)
        terminal_value = max(
            0.0,
            min(0.30, maximum_import) - settings.battery_wear_per_kwh,
        ) * settings.battery_discharge_efficiency
        baseline_end_soc = _float(actual[-1].get("soc_pct"), initial_soc)
        optimized_end_soc = dispatch[-1].soc_end_pct
        baseline_net += (
            settings.battery_capacity_kwh * (baseline_end_soc - initial_soc) / 100 * terminal_value
        )
        optimized_net += (
            settings.battery_capacity_kwh * (optimized_end_soc - initial_soc) / 100 * terminal_value
        )
        optimized_import = sum(max(0.0, item.site_grid_kw) * item.duration_minutes / 60 for item in dispatch)
        optimized_curtailment = sum(item.pv_curtailment_kw * item.duration_minutes / 60 for item in dispatch)
        baseline_negative_export = sum(
            max(0.0, -_float(item.get("grid_kw"))) * 0.5
            for item in actual
            if _float(item.get("export_price")) < 0
        )
        observed_soc = [_float(item.get("soc_pct"), 50.0) for item in actual]
        baseline_morning = _value_at(actual, morning, "soc_pct")
        baseline_evening = _value_at(actual, evening, "soc_pct")
        optimized_morning = _dispatch_value_at(dispatch, morning)
        optimized_evening = _dispatch_value_at(dispatch, evening)
        initial_energy = settings.battery_capacity_kwh * initial_soc / 100
        evening_slots = [slot for slot in slots if evening and slot.start <= evening]
        conservative_surplus = sum(
            max(0.0, slot.solar_low_kw - slot.load_kw) * slot.duration_h * settings.battery_charge_efficiency
            for slot in evening_slots
        )
        feasible = bool(evening) and initial_energy + conservative_surplus >= (
            settings.battery_capacity_kwh * settings.battery_evening_target_soc_pct / 100
        )
        hot_water = _schedule_hot_water(slots, evening, settings)
        day_start = datetime.combine(_local_time(actual[0]["timestamp"]).date(), time(0), BRISBANE)
        days.append(ReplayDay(
            date=date,
            baseline_net_benefit=round(baseline_net, 3),
            optimized_net_benefit=round(optimized_net, 3),
            baseline_import_kwh=round(_daily_counter(payload, date, "grid_import_kwh", baseline_import), 3),
            optimized_import_kwh=round(optimized_import, 3),
            baseline_negative_fit_export_kwh=round(baseline_negative_export, 3),
            optimized_curtailed_kwh=round(optimized_curtailment, 3),
            baseline_morning_soc_pct=baseline_morning,
            optimized_morning_soc_pct=optimized_morning,
            baseline_evening_soc_pct=baseline_evening,
            optimized_evening_soc_pct=optimized_evening,
            baseline_full_cycle=(
                baseline_morning is not None
                and 5 <= baseline_morning <= 10
                and baseline_evening is not None
                and baseline_evening >= 98
            ),
            morning_target_feasible=_morning_target_feasible(slots, morning, evening, initial_soc, settings),
            optimized_morning_target=optimized_morning is not None and 5 <= optimized_morning <= 10,
            optimized_evening_target=optimized_evening is not None and optimized_evening >= 98,
            evening_target_feasible=feasible,
            hot_water_blocks_available=len(hot_water),
            hot_water_scheduled_hours=len(hot_water) * 0.5,
            ev_50km_naive_cost=_ev_window_cost(source, day_start, optimized=False),
            ev_50km_optimized_cost=_ev_window_cost(source, day_start, optimized=True),
        ))

    if not days:
        raise ValueError("No complete replay days were supplied")

    def average(values: Iterable[float | None]) -> float:
        clean = [float(item) for item in values if item is not None]
        return sum(clean) / len(clean) if clean else 0.0

    feasible_days = [day for day in days if day.evening_target_feasible]
    feasible_mornings = [day for day in days if day.morning_target_feasible]
    daily_records = payload.get("daily", [])
    known_baseline = payload.get("known_baseline", {})
    return {
        "schema_version": 1,
        "method": "historical actuals replay (perfect-hindsight battery benchmark; forecasting is validated separately in shadow mode)",
        "period": {"start": days[0].date, "end": days[-1].date, "completed_days": len(days)},
        "baseline": {
            "solar_kwh_per_day": round(average(_float(item.get("solar_kwh")) for item in daily_records), 2),
            "home_kwh_per_day": round(average(_float(item.get("home_kwh")) for item in daily_records), 2),
            "export_kwh_per_day": round(average(_float(item.get("grid_export_kwh")) for item in daily_records), 2),
            "import_kwh_per_day": round(average(day.baseline_import_kwh for day in days), 2),
            "net_benefit_after_wear": round(sum(day.baseline_net_benefit for day in days), 2),
            "near_full_cycles": int(known_baseline.get("near_full_cycles", sum(day.baseline_full_cycle for day in days))),
            "morning_soc_pct": _float(
                known_baseline.get("morning_soc_pct"),
                round(average(day.baseline_morning_soc_pct for day in days), 1),
            ),
            "negative_fit_export_kwh": round(sum(day.baseline_negative_fit_export_kwh for day in days), 2),
            "morning_fit_reserve_blocked_pct": _float(known_baseline.get("morning_fit_reserve_blocked_pct"), 11.7),
        },
        "optimized_hindsight": {
            "net_benefit_after_wear": round(sum(day.optimized_net_benefit for day in days), 2),
            "benefit_delta": round(sum(day.optimized_net_benefit - day.baseline_net_benefit for day in days), 2),
            "import_kwh_per_day": round(average(day.optimized_import_kwh for day in days), 2),
            "morning_target_success_pct_feasible_days": round(
                100 * sum(day.optimized_morning_target for day in feasible_mornings) / len(feasible_mornings), 1
            ) if feasible_mornings else None,
            "feasible_morning_days": len(feasible_mornings),
            "profit_led_morning_exceptions": sum(
                not day.optimized_morning_target and not day.morning_target_feasible for day in days
            ),
            "evening_target_success_pct_feasible_days": round(
                100 * sum(day.optimized_evening_target for day in feasible_days) / len(feasible_days), 1
            ) if feasible_days else None,
            "feasible_evening_days": len(feasible_days),
            "curtailed_negative_fit_kwh": round(sum(day.optimized_curtailed_kwh for day in days), 2),
            "hot_water_completion_pct": round(100 * sum(day.hot_water_scheduled_hours >= 3 for day in days) / len(days), 1),
            "ev_50km_cost_naive": round(sum(day.ev_50km_naive_cost or 0 for day in days), 2),
            "ev_50km_cost_optimized": round(sum(day.ev_50km_optimized_cost or 0 for day in days), 2),
        },
        "forecast_baseline": payload.get("forecast_baseline", {}),
        "days": [asdict(day) for day in days],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay historical 30-minute energy data")
    parser.add_argument("input", nargs="?", help="JSON input path; stdin when omitted")
    parser.add_argument("--output", help="Optional JSON report path")
    args = parser.parse_args()
    if args.input:
        payload = json.loads(Path(args.input).read_text())
    else:
        payload = json.load(sys.stdin)
    report = run_replay(payload)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
