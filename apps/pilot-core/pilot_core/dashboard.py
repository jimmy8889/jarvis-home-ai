from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import math
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

from .config import IntegrationSettings
from .integrations import IntegrationRequestFailed, IntegrationUnavailable, Integrations


FLOW_IDLE_WATTS = 25.0
GRID_FLOW_IDLE_WATTS = 100.0
VEHICLE_FLOW_IDLE_WATTS = 100.0
DASHBOARD_CACHE_SECONDS = 10.0


class DashboardService:
    """Build the small, stable home-monitoring contract used by every Pilot display."""

    def __init__(self, settings: IntegrationSettings, integrations: Integrations) -> None:
        self.settings = settings
        self.integrations = integrations
        self._cached_snapshot: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._refresh_lock = asyncio.Lock()

    async def snapshot(self) -> dict[str, Any]:
        now = monotonic()
        if self._cached_snapshot is not None and now - self._cached_at < DASHBOARD_CACHE_SECONDS:
            return deepcopy(self._cached_snapshot)
        async with self._refresh_lock:
            now = monotonic()
            if self._cached_snapshot is not None and now - self._cached_at < DASHBOARD_CACHE_SECONDS:
                return deepcopy(self._cached_snapshot)
            value = await self._fresh_snapshot()
            self._cached_snapshot = value
            self._cached_at = monotonic()
            return deepcopy(value)

    def invalidate(self) -> None:
        """Discard projected state after a successful dashboard mutation."""

        self._cached_snapshot = None
        self._cached_at = 0.0

    async def _fresh_snapshot(self) -> dict[str, Any]:
        entity_ids = self._configured_entity_ids()
        power_history_ids = tuple(
            entity_id
            for entity_id in (
                self.settings.energy_home_load_entity_id,
                self.settings.energy_battery_power_entity_id,
                self.settings.energy_solar_power_entity_id,
                self.settings.energy_vehicle_power_entity_id,
            )
            if entity_id
        )
        temperature_history_ids = tuple(
            dict.fromkeys(
                entity_id
                for entity_id in (
                    self.settings.temperature_office_entity_id,
                    self.settings.temperature_tv_room_entity_id,
                    self.settings.outdoor_temperature_entity_id,
                    self.settings.temperature_bedroom_entity_id,
                    self.settings.temperature_media_room_entity_id,
                )
                if entity_id
            )
        )
        history_started_at, history_ended_at = self._energy_calendar_window()
        states_result, power_history_result, temperature_history_result, weather_result = await asyncio.gather(
            self._states(entity_ids),
            self._energy_history(power_history_ids, history_started_at),
            self._temperature_history(temperature_history_ids),
            self._weather(),
        )
        state_by_id, state_error = states_result
        power_history_by_id, power_history_error = power_history_result
        temperature_history_by_id, temperature_history_error = temperature_history_result
        weather, weather_error = weather_result
        missing = [entity_id for entity_id in entity_ids if entity_id not in state_by_id]
        return {
            "schema_version": "pilot.dashboard.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "ok" if not missing else "partial" if state_by_id else "unavailable",
            "power": self._power(state_by_id),
            "scene": self._scene(state_by_id),
            "daily": self._daily(state_by_id),
            "vehicle": self._vehicle(state_by_id),
            "tariff": self._tariff(state_by_id),
            "temperatures": self._temperatures(state_by_id, temperature_history_by_id),
            "history": self._history_projection(
                power_history_by_id,
                history_started_at,
                history_ended_at,
            ),
            "weather": weather,
            "controls": self._controls(state_by_id),
            "diagnostics": {
                "missing_entities": missing,
                "state_error": state_error,
                "history_error": power_history_error,
                "temperature_history_error": temperature_history_error,
                "weather_error": weather_error,
            },
        }

    def _configured_entity_ids(self) -> tuple[str, ...]:
        values = (
            self.settings.energy_solar_power_entity_id,
            self.settings.energy_grid_power_entity_id,
            self.settings.energy_battery_power_entity_id,
            self.settings.energy_battery_soc_entity_id,
            self.settings.energy_home_load_entity_id,
            self.settings.energy_server_power_entity_id,
            self.settings.energy_vehicle_connected_entity_id,
            self.settings.energy_vehicle_power_entity_id,
            self.settings.energy_vehicle_soc_entity_id,
            self.settings.sun_entity_id,
            *self.settings.energy_solar_today_entity_ids,
            self.settings.energy_home_today_entity_id,
            self.settings.energy_grid_export_today_entity_id,
            self.settings.amber_import_price_entity_id,
            self.settings.amber_feed_in_price_entity_id,
            self.settings.amber_feed_in_forecast_entity_id,
            self.settings.tesla_charging_mode_entity_id,
            self.settings.temperature_office_entity_id,
            self.settings.temperature_tv_room_entity_id,
            self.settings.temperature_bedroom_entity_id,
            self.settings.temperature_media_room_entity_id,
            self.settings.outdoor_temperature_entity_id,
        )
        return tuple(dict.fromkeys(value for value in values if value))

    async def _states(
        self, entity_ids: tuple[str, ...]
    ) -> tuple[dict[str, dict[str, Any]], str | None]:
        if not entity_ids:
            return {}, "dashboard entities are not configured"
        try:
            return await self.integrations.home_assistant_selected_states(entity_ids), None
        except (IntegrationUnavailable, IntegrationRequestFailed) as error:
            return {}, str(error)

    async def _energy_history(
        self,
        entity_ids: tuple[str, ...],
        started_at: datetime,
    ) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
        if not entity_ids:
            return {}, "dashboard energy history entities are not configured"
        try:
            return await self.integrations.home_assistant_history(
                entity_ids,
                started_at=started_at,
                ended_at=datetime.now(UTC),
            ), None
        except (IntegrationUnavailable, IntegrationRequestFailed) as error:
            return {}, str(error)

    async def _temperature_history(
        self, entity_ids: tuple[str, ...]
    ) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
        if not entity_ids:
            return {}, "dashboard temperature history entities are not configured"
        try:
            return await self.integrations.home_assistant_history(
                entity_ids,
                hours=self.settings.temperature_history_hours,
            ), None
        except (IntegrationUnavailable, IntegrationRequestFailed) as error:
            return {}, str(error)

    def _energy_calendar_window(self) -> tuple[datetime, datetime]:
        local_now = datetime.now(ZoneInfo(self.settings.home_timezone))
        started_at = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return started_at, started_at + timedelta(days=1)

    async def _weather(self) -> tuple[dict[str, Any], str | None]:
        try:
            raw = await self.integrations.home_assistant_weather()
        except (IntegrationUnavailable, IntegrationRequestFailed) as error:
            return {"status": "unavailable", "forecast": []}, str(error)
        current = raw.get("current") or {}
        attrs = current.get("attributes") or {}
        response = raw.get("forecast_response") or {}
        service_response = (
            response.get("service_response", response)
            if isinstance(response, dict)
            else {}
        )
        entity = service_response.get(str(raw.get("entity_id") or ""), {})
        forecast = entity.get("forecast", []) if isinstance(entity, dict) else []
        return {
            "status": "ok",
            "condition": self._text(current.get("state")),
            "temperature_c": self._number(attrs.get("temperature")),
            "apparent_temperature_c": self._number(attrs.get("apparent_temperature")),
            "humidity_percent": self._number(attrs.get("humidity")),
            "wind_speed": self._number(attrs.get("wind_speed")),
            "wind_speed_unit": self._text(attrs.get("wind_speed_unit")),
            "wind_bearing": self._text(attrs.get("wind_bearing")),
            "forecast": [self._forecast_day(item) for item in forecast[:7] if isinstance(item, dict)],
            "observed_at": self._text(current.get("last_updated")),
        }, None

    def _power(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        solar = self._power_state(states, self.settings.energy_solar_power_entity_id)
        grid = self._power_state(states, self.settings.energy_grid_power_entity_id)
        battery = self._power_state(states, self.settings.energy_battery_power_entity_id)
        home = self._power_state(states, self.settings.energy_home_load_entity_id)
        server = self._power_state(states, self.settings.energy_server_power_entity_id)
        vehicle = self._power_state(states, self.settings.energy_vehicle_power_entity_id)
        soc = self._percent_state(states, self.settings.energy_battery_soc_entity_id)
        return {
            "solar_w": solar,
            "grid_w": grid,
            "battery_w": battery,
            "battery_soc_percent": soc,
            "home_load_w": home,
            "server_rack_w": server,
            "vehicle_w": vehicle,
            "directions": {
                "grid": self._direction(grid, "importing", "exporting", GRID_FLOW_IDLE_WATTS),
                "battery": self._direction(battery, "discharging", "charging", FLOW_IDLE_WATTS),
                "vehicle": (
                    "charging"
                    if vehicle is not None and vehicle >= VEHICLE_FLOW_IDLE_WATTS
                    else "idle"
                ),
                "server_rack": "consuming" if server is not None and server >= FLOW_IDLE_WATTS else "idle",
            },
            "flow_active": {
                "solar": solar is not None and solar >= FLOW_IDLE_WATTS,
                "grid": grid is not None and abs(grid) >= GRID_FLOW_IDLE_WATTS,
                "battery": battery is not None and abs(battery) >= FLOW_IDLE_WATTS,
                "home": home is not None and home >= FLOW_IDLE_WATTS,
                "server_rack": server is not None and server >= FLOW_IDLE_WATTS,
                "vehicle": vehicle is not None and vehicle >= VEHICLE_FLOW_IDLE_WATTS,
            },
        }

    def _scene(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        state = states.get(self.settings.sun_entity_id, {})
        sun_state = self._text(state.get("state"))
        normalized = sun_state.casefold() if sun_state else None
        is_day = (
            True
            if normalized == "above_horizon"
            else False
            if normalized == "below_horizon"
            else None
        )
        attributes = state.get("attributes") or {}
        return {
            "is_day": is_day,
            "sun_state": sun_state,
            "solar_elevation_degrees": self._number(attributes.get("elevation")),
            "next_rising": self._text(attributes.get("next_rising")),
            "next_setting": self._text(attributes.get("next_setting")),
        }

    def _daily(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        solar_values = [
            self._energy_state(states, entity_id)
            for entity_id in self.settings.energy_solar_today_entity_ids
        ]
        present = [value for value in solar_values if value is not None]
        return {
            "solar_generated_kwh": round(sum(present), 3) if present else None,
            "home_used_kwh": self._energy_state(states, self.settings.energy_home_today_entity_id),
            "grid_exported_kwh": self._energy_state(
                states, self.settings.energy_grid_export_today_entity_id
            ),
        }

    def _vehicle(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        connected = self._binary_state(
            states, self.settings.energy_vehicle_connected_entity_id
        )
        power = self._power_state(states, self.settings.energy_vehicle_power_entity_id)
        return {
            "name": "Jarvis",
            "connected": connected,
            "charging": bool(
                connected and power is not None and power >= VEHICLE_FLOW_IDLE_WATTS
            ),
            "power_w": power,
            "state_of_charge_percent": self._percent_state(
                states, self.settings.energy_vehicle_soc_entity_id
            ),
        }

    def _tariff(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        forecast_state = states.get(self.settings.amber_feed_in_forecast_entity_id, {})
        attributes = forecast_state.get("attributes", {})
        forecast = next(
            (
                attributes[key]
                for key in ("forecast", "forecasts", "prices")
                if isinstance(attributes.get(key), list)
            ),
            [],
        )
        forecast_unit = str(attributes.get("unit_of_measurement") or "c/kWh")

        def forecast_point(item: dict[str, Any]) -> dict[str, Any]:
            at = next(
                (
                    self._text(item.get(key))
                    for key in ("time", "start_time", "datetime", "date", "nem_date")
                    if self._text(item.get(key))
                ),
                None,
            )
            price = next(
                (
                    item.get(key)
                    for key in (
                        "value",
                        "per_kwh",
                        "price",
                        "cents_per_kwh",
                        "spot_per_kwh",
                    )
                    if item.get(key) is not None
                ),
                None,
            )
            unit = str(item.get("unit") or item.get("unit_of_measurement") or forecast_unit)
            return {"at": at, "cents_per_kwh": self._price_value(price, unit)}

        return {
            "import_cents_per_kwh": self._price_state(
                states, self.settings.amber_import_price_entity_id
            ),
            "feed_in_cents_per_kwh": self._price_state(
                states, self.settings.amber_feed_in_price_entity_id
            ),
            "feed_in_forecast": [forecast_point(item) for item in forecast[:96] if isinstance(item, dict)],
        }

    def _temperatures(
        self,
        states: dict[str, dict[str, Any]],
        history: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        configured = (
            ("office", "Office", self.settings.temperature_office_entity_id),
            ("tv-room", "TV room", self.settings.temperature_tv_room_entity_id),
            ("outdoor", "Outdoor", self.settings.outdoor_temperature_entity_id),
            ("bedroom", "Bedroom", self.settings.temperature_bedroom_entity_id),
            ("media-room", "Media room", self.settings.temperature_media_room_entity_id),
        )
        return [
            {
                "id": identifier,
                "label": label,
                "temperature_c": self._temperature_state(states, entity_id),
                "entity_id": entity_id,
                "history": self._temperature_history_points(history.get(entity_id, [])),
            }
            for identifier, label, entity_id in configured
            if entity_id
        ]

    def _history_projection(
        self,
        history: dict[str, list[dict[str, Any]]],
        started_at: datetime,
        ended_at: datetime,
    ) -> dict[str, Any]:
        configured = (
            (
                "home_load",
                "Home load",
                "#FF5D6C",
                self.settings.energy_home_load_entity_id,
                True,
            ),
            (
                "battery",
                "Battery power",
                "#55B6FF",
                self.settings.energy_battery_power_entity_id,
                False,
            ),
            (
                "solar",
                "Solar power",
                "#FFC247",
                self.settings.energy_solar_power_entity_id,
                False,
            ),
            (
                "tesla",
                "Tesla charging",
                "#D970FF",
                self.settings.energy_vehicle_power_entity_id,
                True,
            ),
        )
        return {
            "period_hours": 24,
            "window": "calendar_day",
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "series": [
                {
                    "id": identifier,
                    "label": label,
                    "color": color,
                    "unit": "W",
                    "points": self._history_points(
                        history.get(entity_id, []),
                        negative=negative,
                    ),
                }
                for identifier, label, color, entity_id, negative in configured
                if entity_id
            ],
        }

    def _controls(self, states: dict[str, dict[str, Any]]) -> dict[str, Any]:
        mode_state = states.get(self.settings.tesla_charging_mode_entity_id, {})
        current_mode = self._text(mode_state.get("state"))
        return {
            "tesla_charging_mode": {
                "entity_id": self.settings.tesla_charging_mode_entity_id or None,
                "value": current_mode,
                "options": ["Grid", "Solar"],
                "available": current_mode is not None,
            },
            "media_room_mode": {
                "on_script_id": self.settings.media_room_mode_on_script_id or None,
                "off_script_id": self.settings.media_room_mode_off_script_id or None,
                "available": bool(
                    self.settings.media_room_mode_on_script_id
                    and self.settings.media_room_mode_off_script_id
                ),
            },
        }

    def _history_points(
        self,
        values: list[dict[str, Any]],
        *,
        negative: bool = False,
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for item in values:
            value = self._number(item.get("state"))
            attrs = item.get("attributes") or {}
            unit = str(attrs.get("unit_of_measurement") or "W").casefold()
            if value is None or unit not in {"w", "watt", "watts", "kw"}:
                continue
            if unit == "kw":
                value *= 1000
            if negative:
                value = -abs(value)
            at = self._text(item.get("last_updated") or item.get("last_changed"))
            if at:
                points.append({"at": at, "value": round(value, 1)})
        if len(points) <= 288:
            return points
        return [
            points[round(index * (len(points) - 1) / 287)]
            for index in range(288)
        ]

    def _temperature_history_points(
        self, values: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for item in values:
            value = self._number(item.get("state"))
            attrs = item.get("attributes") or {}
            unit = str(attrs.get("unit_of_measurement") or "°C").casefold()
            if value is None or unit not in {"°c", "c", "celsius", "°f", "f", "fahrenheit"}:
                continue
            if unit in {"°f", "f", "fahrenheit"}:
                value = (value - 32) * 5 / 9
            if not -100 <= value <= 100:
                continue
            at = self._text(item.get("last_updated") or item.get("last_changed"))
            if at:
                points.append({"at": at, "value": round(value, 2)})
        if len(points) <= 96:
            return points
        stride = math.ceil(len(points) / 96)
        return [*points[::stride]][-96:]

    @staticmethod
    def _forecast_day(item: dict[str, Any]) -> dict[str, Any]:
        def number(value: Any) -> float | None:
            try:
                result = float(value)
            except (TypeError, ValueError):
                return None
            return round(result, 2) if math.isfinite(result) else None

        return {
            "at": item.get("datetime"),
            "condition": item.get("condition"),
            "high_temperature_c": number(item.get("temperature")),
            "low_temperature_c": number(item.get("templow")),
            "precipitation_probability": number(item.get("precipitation_probability")),
            "precipitation": number(item.get("precipitation")),
        }

    def _power_state(self, states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        state = states.get(entity_id, {})
        value = self._number(state.get("state"))
        unit = str(state.get("attributes", {}).get("unit_of_measurement") or "W").casefold()
        if value is None or unit not in {"w", "watt", "watts", "kw"}:
            return None
        return round(value * 1000 if unit == "kw" else value, 1)

    def _energy_state(self, states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        state = states.get(entity_id, {})
        value = self._number(state.get("state"))
        unit = str(state.get("attributes", {}).get("unit_of_measurement") or "kWh").casefold()
        if value is None or unit not in {"kwh", "wh"}:
            return None
        return round(value / 1000 if unit == "wh" else value, 3)

    def _percent_state(self, states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        value = self._number(states.get(entity_id, {}).get("state"))
        return round(value, 1) if value is not None and 0 <= value <= 100 else None

    def _temperature_state(self, states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        value = self._number(states.get(entity_id, {}).get("state"))
        return round(value, 1) if value is not None and -60 <= value <= 80 else None

    def _price_state(self, states: dict[str, dict[str, Any]], entity_id: str) -> float | None:
        state = states.get(entity_id, {})
        return self._price_value(
            state.get("state"),
            str(state.get("attributes", {}).get("unit_of_measurement") or "c/kWh"),
        )

    def _price_value(self, candidate: Any, unit: str) -> float | None:
        value = self._number(candidate)
        if value is None:
            return None
        normalized_unit = unit.casefold().replace(" ", "")
        if normalized_unit.startswith("$/") or normalized_unit in {"aud/kwh", "$/kwh"}:
            value *= 100
        return round(value, 4)

    @staticmethod
    def _binary_state(states: dict[str, dict[str, Any]], entity_id: str) -> bool | None:
        state = str(states.get(entity_id, {}).get("state") or "").casefold()
        if state in {"on", "true", "connected", "yes"}:
            return True
        if state in {"off", "false", "disconnected", "no"}:
            return False
        return None

    @staticmethod
    def _direction(value: float | None, positive: str, negative: str, threshold: float) -> str:
        if value is None or abs(value) < threshold:
            return "idle"
        return positive if value > 0 else negative

    @staticmethod
    def _number(candidate: Any) -> float | None:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _text(candidate: Any) -> str | None:
        return str(candidate)[:256] if isinstance(candidate, (str, int, float)) else None
