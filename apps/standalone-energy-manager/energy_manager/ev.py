from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from enum import Enum
import math
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings


class EVTripMode(str, Enum):
    NO_TRIP = "no_trip"
    DISTANCE_100_KM = "distance_100_km"
    DISTANCE_200_KM = "distance_200_km"
    TARGET_80 = "target_80"
    TARGET_100 = "target_100"


TRIP_LABELS: dict[EVTripMode, str] = {
    EVTripMode.NO_TRIP: "No trip",
    EVTripMode.DISTANCE_100_KM: "100 km",
    EVTripMode.DISTANCE_200_KM: "200 km",
    EVTripMode.TARGET_80: "Charge to 80%",
    EVTripMode.TARGET_100: "Ensure 100%",
}

_ALIASES = {
    "": EVTripMode.NO_TRIP,
    "no trip": EVTripMode.NO_TRIP,
    "no trip / opportunistic": EVTripMode.NO_TRIP,
    "unanswered": EVTripMode.NO_TRIP,
    "100 km": EVTripMode.DISTANCE_100_KM,
    "100km": EVTripMode.DISTANCE_100_KM,
    "200 km": EVTripMode.DISTANCE_200_KM,
    "200km": EVTripMode.DISTANCE_200_KM,
    "charge to 80%": EVTripMode.TARGET_80,
    "charge to 80": EVTripMode.TARGET_80,
    "80%": EVTripMode.TARGET_80,
    "ensure 100%": EVTripMode.TARGET_100,
    "charge to 100%": EVTripMode.TARGET_100,
    "charge to 100": EVTripMode.TARGET_100,
    "100%": EVTripMode.TARGET_100,
}


def normalize_trip_mode(value: EVTripMode | str | None) -> EVTripMode:
    if isinstance(value, EVTripMode):
        return value
    raw = str(value or "").strip()
    try:
        return EVTripMode(raw)
    except ValueError:
        normalized = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())
        if normalized in _ALIASES:
            return _ALIASES[normalized]
        raise ValueError(f"unsupported EV trip profile: {raw!r}") from None


def trip_label(value: EVTripMode | str | None) -> str:
    return TRIP_LABELS[normalize_trip_mode(value)]


def opportunistic_fit_eligible(settings: Settings, fit_per_kwh: float | None) -> bool:
    """Single price gate shared by live dispatch and the rolling planner."""
    return fit_per_kwh is not None and fit_per_kwh <= settings.ev_opportunistic_fit_max_per_kwh


def next_ev_departure(settings: Settings, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(settings.timezone))
    departure = datetime.combine(
        local.date(),
        time(settings.ev_default_departure_hour),
        tzinfo=local.tzinfo,
    )
    if departure <= local:
        departure += timedelta(days=1)
    return departure.astimezone(UTC)


def parse_deadline(value: str | datetime | None, settings: Settings) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(settings.timezone))
    return parsed.astimezone(UTC)


def trip_consumption(settings: Settings) -> tuple[float, str]:
    learned = float(settings.ev_learned_consumption_kwh_per_km)
    if 0.08 <= learned <= 0.40:
        return learned, "teslamate_learned"
    return settings.ev_consumption_kwh_per_km, "fallback_0.18_kwh_per_km"


def target_soc_for_mode(settings: Settings, mode: EVTripMode) -> float:
    if mode is EVTripMode.DISTANCE_100_KM:
        distance = 100.0
    elif mode is EVTripMode.DISTANCE_200_KM:
        distance = 200.0
    else:
        distance = 0.0
    if distance:
        consumption, _ = trip_consumption(settings)
        trip_energy = distance * consumption * settings.ev_trip_energy_margin
        target = settings.ev_arrival_reserve_pct + 100 * trip_energy / settings.ev_usable_capacity_kwh
        return round(min(100.0, max(settings.ev_min_soc_pct, target)), 1)
    if mode is EVTripMode.TARGET_80:
        return 80.0
    if mode is EVTripMode.TARGET_100:
        return 100.0
    return float(settings.ev_charge_limit_pct)


@dataclass(frozen=True)
class EVRequirement:
    mode: EVTripMode
    label: str
    selected_profile: bool
    target_soc_pct: float
    command_limit_pct: int
    current_soc_pct: float | None
    required_input_kwh: float
    minimum_40_input_kwh: float
    mandatory: bool
    departure_at: datetime | None
    latest_start_at: datetime | None
    grid_guarantee: bool
    consumption_kwh_per_km: float
    consumption_source: str

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mode"] = self.mode.value
        for key in ("departure_at", "latest_start_at"):
            item = value[key]
            value[key] = item.isoformat() if isinstance(item, datetime) else None
        return value


def ev_requirement(
    settings: Settings,
    current_soc_pct: float | None,
    now: datetime,
) -> EVRequirement:
    mode = normalize_trip_mode(settings.ev_trip_profile or settings.ev_trip_requirement)
    selected = mode is not EVTripMode.NO_TRIP
    current = None if current_soc_pct is None else max(0.0, min(100.0, float(current_soc_pct)))
    target = target_soc_for_mode(settings, mode)
    if mode is EVTripMode.NO_TRIP and current is not None and current < settings.ev_min_soc_pct:
        target = float(settings.ev_min_soc_pct)
    required = 0.0
    minimum = 0.0
    if current is not None:
        required = max(0.0, target - current) / 100 * settings.ev_usable_capacity_kwh / settings.ev_charge_efficiency
        minimum = max(0.0, settings.ev_min_soc_pct - current) / 100 * settings.ev_usable_capacity_kwh / settings.ev_charge_efficiency
    deadline = None
    if selected:
        deadline = parse_deadline(settings.ev_trip_deadline, settings) or next_ev_departure(settings, now)
    mandatory = current is not None and (minimum > 1e-9 or (selected and required > 1e-9))
    latest_start = None
    if deadline is not None and required > 1e-9:
        maximum_kw = max(0.1, settings.ev_max_amps * settings.ev_three_phase_kw_per_amp)
        latest_start = deadline - timedelta(hours=required / maximum_kw)
    consumption, consumption_source = trip_consumption(settings)
    return EVRequirement(
        mode=mode,
        label=TRIP_LABELS[mode],
        selected_profile=selected,
        target_soc_pct=target,
        command_limit_pct=max(50, min(100, math.ceil(target))),
        current_soc_pct=current,
        required_input_kwh=round(required, 3),
        minimum_40_input_kwh=round(minimum, 3),
        mandatory=mandatory,
        departure_at=deadline,
        latest_start_at=latest_start,
        grid_guarantee=selected,
        consumption_kwh_per_km=consumption,
        consumption_source=consumption_source,
    )
