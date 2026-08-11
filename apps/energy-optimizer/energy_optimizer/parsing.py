from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta
import math
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from .models import Slot


UNAVAILABLE = {"", "unknown", "unavailable", "none", "null"}


def numeric_state(states: dict[str, dict[str, Any]], entity_id: str, default: float = 0.0) -> float:
    raw = states.get(entity_id, {}).get("state")
    if raw is None or str(raw).lower() in UNAVAILABLE:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def state_is_on(states: dict[str, dict[str, Any]], entity_id: str) -> bool:
    return str(states.get(entity_id, {}).get("state", "")).lower() in {"on", "true", "active", "home"}


def parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone)
    return result.astimezone(timezone)


def floor_time(value: datetime, minutes: int) -> datetime:
    minute = value.minute - value.minute % minutes
    return value.replace(minute=minute, second=0, microsecond=0)


def build_time_grid(now: datetime, horizon_hours: int, slot_minutes: int) -> list[datetime]:
    start = floor_time(now, slot_minutes)
    count = int(horizon_hours * 60 / slot_minutes)
    return [start + timedelta(minutes=slot_minutes * i) for i in range(count)]


def _price_points(entity: dict[str, Any], timezone: ZoneInfo) -> list[tuple[datetime, float]]:
    attrs = entity.get("attributes", {})
    raw = attrs.get("forecast") or attrs.get("forecasts") or attrs.get("chartForecast") or []
    points: list[tuple[datetime, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        when = parse_datetime(
            item.get("time") or item.get("x") or item.get("start_time") or item.get("nem_date"),
            timezone,
        )
        price_raw = item.get("value", item.get("y", item.get("per_kwh", item.get("price"))))
        try:
            price = float(price_raw)
        except (TypeError, ValueError):
            continue
        if when and math.isfinite(price):
            points.append((when, price))
    points.sort(key=lambda item: item[0])
    return points


def _fallback_price(when: datetime, *, export: bool) -> float:
    hour = when.hour + when.minute / 60
    if export:
        if 5 <= hour < 7.5:
            return 0.09
        if 7.5 <= hour < 10:
            return max(0.0, 0.09 - (hour - 7.5) * 0.035)
        if 10 <= hour < 15.5:
            return 0.0
        if 15.5 <= hour < 20.5:
            return 0.10
        return 0.06
    if 10.5 <= hour < 15:
        return 0.04
    if 16 <= hour < 21:
        return 0.33
    if 5 <= hour < 10:
        return 0.17
    return 0.16


def _sample_price(
    points: list[tuple[datetime, float]],
    when: datetime,
    *,
    export: bool,
) -> tuple[float, str]:
    if points:
        times = [item[0] for item in points]
        index = bisect_right(times, when) - 1
        if index >= 0 and when - times[index] <= timedelta(minutes=35):
            return points[index][1], "amber"
        future = index + 1
        if 0 <= future < len(points) and times[future] - when <= timedelta(minutes=15):
            return points[future][1], "amber"
    return _fallback_price(when, export=export), "historical_fallback"


def _slot_price(
    points: list[tuple[datetime, float]],
    when: datetime,
    duration: timedelta,
    *,
    export: bool,
) -> tuple[float, str]:
    within = [price for timestamp, price in points if when <= timestamp < when + duration]
    if within:
        return sum(within) / len(within), "amber"
    return _sample_price(points, when, export=export)


def _solar_points(entities: Iterable[dict[str, Any]], timezone: ZoneInfo) -> list[tuple[datetime, float, float, float]]:
    points: list[tuple[datetime, float, float, float]] = []
    for entity in entities:
        for item in entity.get("attributes", {}).get("detailedForecast", []):
            if not isinstance(item, dict):
                continue
            when = parse_datetime(item.get("period_start"), timezone)
            try:
                expected = max(0.0, float(item.get("pv_estimate", 0.0)))
                low = max(0.0, float(item.get("pv_estimate10", expected)))
                high = max(expected, float(item.get("pv_estimate90", expected)))
            except (TypeError, ValueError):
                continue
            if when:
                points.append((when, expected, low, high))
    unique = {item[0]: item for item in points}
    return [unique[key] for key in sorted(unique)]


def _sample_solar(
    points: list[tuple[datetime, float, float, float]],
    when: datetime,
    calibration_ratio: float,
    low_weather_factor: float,
) -> tuple[float, float, float]:
    if not points:
        return 0.0, 0.0, 0.0
    times = [item[0] for item in points]
    index = bisect_right(times, when) - 1
    if index < 0:
        index = 0
    if abs((times[index] - when).total_seconds()) > 2700:
        return 0.0, 0.0, 0.0
    _, expected, low, high = points[index]
    expected *= calibration_ratio
    low = min(expected, low * calibration_ratio * low_weather_factor)
    high = max(expected, high * calibration_ratio)
    return expected, low, high


def build_slots(
    *,
    now: datetime,
    horizon_hours: int,
    slot_minutes: int,
    timezone: ZoneInfo,
    fit_entity: dict[str, Any],
    import_entity: dict[str, Any],
    solar_entities: Iterable[dict[str, Any]],
    load_forecast: Callable[[datetime], float],
    calibration_ratio: float,
    weather_condition: str,
) -> list[Slot]:
    fit_points = _price_points(fit_entity, timezone)
    import_points = _price_points(import_entity, timezone)
    solar_points = _solar_points(solar_entities, timezone)
    weather = weather_condition.lower()
    low_weather_factor = 0.80 if weather in {"rainy", "pouring", "lightning-rainy"} else 0.90
    duration_h = slot_minutes / 60
    duration = timedelta(minutes=slot_minutes)
    slots: list[Slot] = []
    for when in build_time_grid(now, horizon_hours, slot_minutes):
        fit, fit_source = _slot_price(fit_points, when, duration, export=True)
        import_price, import_source = _slot_price(import_points, when, duration, export=False)
        solar, low, high = _sample_solar(solar_points, when, calibration_ratio, low_weather_factor)
        slots.append(Slot(
            start=when,
            duration_h=duration_h,
            solar_kw=solar,
            solar_low_kw=low,
            solar_high_kw=high,
            load_kw=max(0.2, float(load_forecast(when))),
            import_price=import_price,
            export_price=fit,
            price_source="amber" if fit_source == import_source == "amber" else "historical_fallback",
        ))
    return slots
