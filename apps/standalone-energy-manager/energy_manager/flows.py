from __future__ import annotations

from datetime import datetime
from typing import Any


def _positive(value: float | int | None) -> float:
    return max(0.0, float(value or 0.0))


def conserved_power_flow(
    *,
    pv_kw: float | None,
    battery_kw: float | None,
    grid_kw: float | None,
    ordinary_house_kw: float | None,
    hot_water_kw: float | None,
    ev_kw: float | None,
    server_rack_kw: float | None = None,
    at: datetime | str | None = None,
    expected: bool = False,
) -> dict[str, Any]:
    """Return an exactly balanced, deterministic power-flow contract.

    SAJ signs are normalised at the boundary: battery/grid are positive into
    the site and negative away from it. Meter disagreement is retained as an
    explicit unaccounted source or sink instead of silently assigning energy.
    """
    ordinary = _positive(ordinary_house_kw)
    # Server + desk is a submeter within ordinary house demand.  Keep the
    # measured value visible, but never subtract it from the house total or add
    # it as another conserved sink.
    rack = min(ordinary, _positive(server_rack_kw))
    sources = {
        "solar": _positive(pv_kw),
        "battery": _positive(battery_kw),
        "grid": _positive(grid_kw),
    }
    sinks = {
        "house": ordinary,
        "hot_water": _positive(hot_water_kw),
        "ev": _positive(ev_kw),
        "battery": _positive(-float(battery_kw or 0.0)),
        "grid": _positive(-float(grid_kw or 0.0)),
    }
    measured_source = sum(sources.values())
    measured_sink = sum(sinks.values())
    raw_error = measured_source - measured_sink
    if raw_error > 0:
        sinks["unaccounted"] = raw_error
    elif raw_error < 0:
        sources["unaccounted"] = -raw_error

    remaining_sources = dict(sources)
    edges: list[dict[str, Any]] = []
    for sink, demand in sinks.items():
        remaining = demand
        for source in tuple(remaining_sources):
            supplied = min(remaining, remaining_sources[source])
            if supplied > 1e-9:
                edges.append({"from": source, "to": sink, "kw": round(supplied, 6)})
                remaining_sources[source] -= supplied
                remaining -= supplied
            if remaining <= 1e-9:
                break

    total_source = sum(sources.values())
    total_sink = sum(sinks.values())
    balance_residual = total_source - total_sink
    absolute_error = abs(raw_error)
    if absolute_error <= 0.1:
        confidence_score, confidence_label = 1.0, "high"
    elif absolute_error <= 0.3:
        confidence_score, confidence_label = 0.65, "medium"
    else:
        confidence_score = max(0.1, 1.0 - absolute_error / max(total_source, total_sink, 1.0))
        confidence_label = "low"
    timestamp = at.isoformat() if isinstance(at, datetime) else at
    return {
        "schema_version": 1,
        "method": "priority_inference_v1",
        "at": timestamp,
        "expected": bool(expected),
        # Non-additive headline total for dashboards. The conserved sinks below
        # remain disaggregated so hot water and EV can still be explained.
        "site_load_kw": round(ordinary + sinks["hot_water"] + sinks["ev"], 6),
        "sources_kw": {key: round(value, 6) for key, value in sources.items()},
        "sinks_kw": {key: round(value, 6) for key, value in sinks.items()},
        "submeters_kw": {"server_rack": round(rack, 6)},
        "edges": edges,
        "total_source_kw": round(total_source, 6),
        "total_sink_kw": round(total_sink, 6),
        "meter_balance_error_kw": round(raw_error, 6),
        "balance_residual_kw": round(balance_residual, 6),
        "confidence": {"score": round(confidence_score, 3), "label": confidence_label},
        "conserved": abs(balance_residual) < 1e-6,
    }


def source_allocation_from_flow(flow: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Compatibility projection for the original house/hot-water/EV table."""
    result = {
        name: {"load_kw": 0.0, "solar_kw": 0.0, "battery_kw": 0.0, "grid_kw": 0.0}
        for name in ("house", "hot_water", "ev", "house_total")
    }
    sinks = flow.get("sinks_kw", {})
    result["house"]["load_kw"] = float(sinks.get("house", 0))
    result["hot_water"]["load_kw"] = float(sinks.get("hot_water", 0))
    result["ev"]["load_kw"] = float(sinks.get("ev", 0))
    for edge in flow.get("edges", []):
        sink = str(edge.get("to"))
        consumer = "house" if sink == "house" else sink
        source = str(edge.get("from"))
        if consumer not in result or source not in {"solar", "battery", "grid"}:
            continue
        key = f"{source}_kw"
        result[consumer][key] += float(edge.get("kw", 0))
    result["house_total"]["load_kw"] = sum(result[name]["load_kw"] for name in ("house", "hot_water", "ev"))
    for source in ("solar_kw", "battery_kw", "grid_kw"):
        result["house_total"][source] = sum(result[name][source] for name in ("house", "hot_water", "ev"))
    return {
        consumer: {key: round(value, 3) for key, value in values.items()}
        for consumer, values in result.items()
    }


def export_split(flow: dict[str, Any]) -> tuple[float, float]:
    solar = 0.0
    battery = 0.0
    for edge in flow.get("edges", []):
        if edge.get("to") != "grid":
            continue
        if edge.get("from") == "solar":
            solar += float(edge.get("kw", 0))
        elif edge.get("from") == "battery":
            battery += float(edge.get("kw", 0))
    return solar, battery
