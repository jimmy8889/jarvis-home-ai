from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from typing import Any


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return float(value)


def battery_health(
    rows: Iterable[dict[str, Any]],
    *,
    capacity_rows: Iterable[dict[str, Any]] | None = None,
    configured_efficiency_wh_per_km: float | None = None,
    manual_baseline_kwh: float | None = None,
) -> dict[str, Any]:
    """Reproduce TeslaMate's qualified charge/rated-range capacity estimate.

    The modal efficiency uses completed sessions longer than ten minutes that
    finish at or below 95% and have positive rated-range and energy deltas. A
    capacity sample then uses each qualified TeslaMate charge point's usable
    SOC and rated range. Only the latest 100 samples contribute to "current";
    the observed baseline uses the final charge point from each session.
    """

    sessions = list(rows)
    efficiencies: list[float] = []
    for row in sessions:
        duration = _number(row.get("duration_min"))
        start_soc = _number(row.get("start_battery_level"))
        end_soc = _number(row.get("end_battery_level"))
        energy_added = _number(row.get("charge_energy_added"))
        start_range = _number(row.get("start_rated_range_km"))
        end_range = _number(row.get("end_rated_range_km"))
        if None in (start_soc, end_soc, energy_added, start_range, end_range):
            continue
        range_delta = end_range - start_range
        if (
            duration is None
            or duration <= 10
            or end_soc > 95
            or energy_added <= 0
            or range_delta <= 0
        ):
            continue
        efficiency_kwh_per_100km = round(energy_added / range_delta, 3) * 100
        if not 5 <= efficiency_kwh_per_100km <= 40:
            continue
        efficiencies.append(efficiency_kwh_per_100km)

    derived_efficiency_kwh_per_100km = None
    if efficiencies:
        counts = Counter(efficiencies)
        derived_efficiency_kwh_per_100km = min(
            (value for value, count in counts.items() if count == max(counts.values())),
            default=None,
        )
    configured_kwh_per_100km = (
        configured_efficiency_wh_per_km / 10
        if configured_efficiency_wh_per_km is not None
        else None
    )
    effective_efficiency = derived_efficiency_kwh_per_100km or configured_kwh_per_100km
    derived_wh_per_km = (
        derived_efficiency_kwh_per_100km * 10
        if derived_efficiency_kwh_per_100km is not None
        else None
    )
    if effective_efficiency is None:
        return {
            "status": "insufficient_data",
            "method": "teslamate_qualified_charging_sessions_v1",
            "sample_count": 0,
            "derived_efficiency_wh_per_km": derived_wh_per_km,
            "reason": "no_qualified_efficiency",
        }

    points = (
        list(capacity_rows)
        if capacity_rows is not None
        else [
            {
                "charging_process_id": index,
                "charge_energy_added": row.get("charge_energy_added"),
                "end_date": row.get("end_date"),
                "date": row.get("end_date") or row.get("start_date"),
                "rated_battery_range_km": row.get("end_rated_range_km"),
                "usable_battery_level": row.get("end_battery_level"),
            }
            for index, row in enumerate(sessions)
        ]
    )
    samples: list[dict[str, Any]] = []
    for point in points:
        energy_added = _number(point.get("charge_energy_added"))
        rated_range = _number(point.get("rated_battery_range_km"))
        usable_soc = _number(point.get("usable_battery_level"))
        if (
            energy_added is None
            or energy_added < effective_efficiency
            or rated_range is None
            or usable_soc is None
            or usable_soc <= 0
            or point.get("end_date") is None
        ):
            continue
        capacity = rated_range * effective_efficiency / usable_soc
        if 20 <= capacity <= 200:
            samples.append(
                {
                    "date": point.get("date"),
                    "charging_process_id": point.get("charging_process_id"),
                    "capacity_kwh": capacity,
                }
            )
    samples.sort(key=lambda item: str(item["date"] or ""), reverse=True)
    latest = samples[:100]
    if not latest:
        return {
            "status": "insufficient_data",
            "method": "teslamate_qualified_charging_sessions_v1",
            "sample_count": 0,
            "derived_efficiency_wh_per_km": derived_wh_per_km,
            "reason": "no_qualified_capacity_samples",
        }

    current = sum(item["capacity_kwh"] for item in latest) / len(latest)
    final_by_session: dict[Any, dict[str, Any]] = {}
    for item in samples:
        process_id = item["charging_process_id"]
        if process_id not in final_by_session:
            final_by_session[process_id] = item
    observed_max = max(item["capacity_kwh"] for item in final_by_session.values())
    baseline = manual_baseline_kwh or observed_max
    degradation = max(0.0, (1 - current / baseline) * 100) if baseline > 0 else 0.0
    dates = [item["date"] for item in latest if item["date"] is not None]
    return {
        "status": "estimate",
        "method": "teslamate_qualified_charging_sessions_v1",
        "sample_count": len(latest),
        "date_from": min(dates) if dates else None,
        "date_to": max(dates) if dates else None,
        "derived_efficiency_wh_per_km": (
            round(derived_wh_per_km, 2) if derived_wh_per_km is not None else None
        ),
        "effective_efficiency_wh_per_km": round(effective_efficiency * 10, 2),
        "estimated_capacity_kwh": round(current, 2),
        "baseline_capacity_kwh": round(baseline, 2),
        "baseline_source": "manual" if manual_baseline_kwh else "observed_maximum",
        "estimated_degradation_percent": round(degradation, 2),
    }
