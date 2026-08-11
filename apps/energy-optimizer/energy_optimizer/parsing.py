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


def build_dispatch_grid(
    now: datetime,
    horizon_hours: int,
    coarse_slot_minutes: int,
    fine_slot_minutes: int,
    fine_horizon_minutes: int,
) -> list[tuple[datetime, timedelta]]:
    """Build a gap-free hybrid grid starting at the decision instant.

    Amber settles in five-minute intervals.  Keeping the active interval and
    the immediate forecast at that resolution prevents a short price spike
    from being averaged into a half-hour slot.  The rest of the 36-hour plan
    remains coarse so the battery dynamic programme stays inexpensive.
    """
    if min(horizon_hours, coarse_slot_minutes, fine_slot_minutes) <= 0:
        raise ValueError("dispatch grid durations must be positive")
    horizon_end = now + timedelta(hours=horizon_hours)
    active_start = floor_time(now, fine_slot_minutes)
    fine_end = min(
        horizon_end,
        active_start + timedelta(minutes=max(fine_slot_minutes, fine_horizon_minutes)),
    )
    cursor = now
    next_fine_boundary = active_start + timedelta(minutes=fine_slot_minutes)
    result: list[tuple[datetime, timedelta]] = []

    while cursor < fine_end:
        while next_fine_boundary <= cursor:
            next_fine_boundary += timedelta(minutes=fine_slot_minutes)
        slot_end = min(horizon_end, fine_end, next_fine_boundary)
        result.append((cursor, slot_end - cursor))
        cursor = slot_end
        next_fine_boundary += timedelta(minutes=fine_slot_minutes)

    coarse_duration = timedelta(minutes=coarse_slot_minutes)
    while cursor < horizon_end:
        slot_end = min(horizon_end, cursor + coarse_duration)
        result.append((cursor, slot_end - cursor))
        cursor = slot_end
    return result


def _price_points(entity: dict[str, Any], timezone: ZoneInfo) -> list[tuple[datetime, float]]:
    attrs = entity.get("attributes", {})
    if not isinstance(attrs, dict):
        return []
    raw = attrs.get("forecast") or attrs.get("forecasts") or attrs.get("chartForecast") or []
    if not isinstance(raw, list):
        return []
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


def active_price(
    entity: dict[str, Any],
    now: datetime,
    timezone: ZoneInfo,
    interval_minutes: int,
    *,
    require_explicit_window: bool = False,
) -> tuple[float, datetime, datetime] | None:
    """Return the live Amber price only while its five-minute window is active."""
    try:
        value = float(entity.get("state"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    attributes = entity.get("attributes", {})
    if not isinstance(attributes, dict):
        return None
    start = parse_datetime(
        attributes.get("start_time")
        or attributes.get("startTime")
        or attributes.get("nem_date"),
        timezone,
    )
    end = parse_datetime(
        attributes.get("end_time") or attributes.get("endTime"),
        timezone,
    )
    if require_explicit_window and (start is None or end is None or end <= start):
        return None
    if start is None:
        start = floor_time(now, interval_minutes)
    if end is None or end <= start:
        end = start + timedelta(minutes=interval_minutes)
    if require_explicit_window:
        expected_seconds = interval_minutes * 60
        actual_seconds = (end - start).total_seconds()
        # Amber settlement windows are five minutes.  Allow a small tolerance
        # for providers that round their boundary timestamps, but never turn a
        # malformed long-lived state into a current dispatch price.
        if abs(actual_seconds - expected_seconds) > 60:
            return None
    if start <= now < end:
        return value, start, end
    return None


def active_price_pair(
    fit_entity: dict[str, Any],
    import_entity: dict[str, Any],
    now: datetime,
    timezone: ZoneInfo,
    interval_minutes: int,
) -> tuple[
    tuple[float, datetime, datetime],
    tuple[float, datetime, datetime],
] | None:
    """Return a validated FIT/import pair for one current Amber interval."""
    fit = active_price(
        fit_entity,
        now,
        timezone,
        interval_minutes,
        require_explicit_window=True,
    )
    imports = active_price(
        import_entity,
        now,
        timezone,
        interval_minutes,
        require_explicit_window=True,
    )
    if fit is None or imports is None:
        return None
    if (
        abs((fit[1] - imports[1]).total_seconds()) > 1
        or abs((fit[2] - imports[2]).total_seconds()) > 1
    ):
        return None
    return fit, imports


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
    amber_interval_minutes: int | None = None,
    amber_fine_horizon_minutes: int = 0,
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
    fine_minutes = amber_interval_minutes or slot_minutes
    grid = build_dispatch_grid(
        now,
        horizon_hours,
        slot_minutes,
        fine_minutes,
        amber_fine_horizon_minutes,
    )
    active_pair = active_price_pair(
        fit_entity,
        import_entity,
        now,
        timezone,
        fine_minutes,
    )
    active_fit, active_import = active_pair if active_pair else (None, None)
    slots: list[Slot] = []
    for when, duration in grid:
        duration_h = duration.total_seconds() / 3600
        fit, fit_source = _slot_price(fit_points, when, duration, export=True)
        import_price, import_source = _slot_price(import_points, when, duration, export=False)
        slot_end = when + duration
        if active_fit and when < active_fit[2] and slot_end > active_fit[1]:
            fit = active_fit[0]
            fit_source = "amber_live"
        if active_import and when < active_import[2] and slot_end > active_import[1]:
            import_price = active_import[0]
            import_source = "amber_live"
        solar, low, high = _sample_solar(solar_points, when, calibration_ratio, low_weather_factor)
        price_sources = {fit_source, import_source}
        if price_sources == {"amber_live"}:
            price_source = "amber_live"
        elif all(item.startswith("amber") for item in price_sources):
            price_source = "amber"
        else:
            price_source = "historical_fallback"
        slots.append(Slot(
            start=when,
            duration_h=duration_h,
            solar_kw=solar,
            solar_low_kw=low,
            solar_high_kw=high,
            load_kw=max(0.2, float(load_forecast(when))),
            import_price=import_price,
            export_price=fit,
            price_source=price_source,
        ))
    return slots
