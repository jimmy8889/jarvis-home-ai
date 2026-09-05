from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import math
from time import monotonic
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from .config import IntegrationSettings


FLOW_IDLE_WATTS = 25.0
POWER_IDLE_WATTS = 100.0
PILOT_PLAN_POINT_LIMIT = 144
PILOT_PLAN_POINT_FIELDS = (
    "start",
    "end",
    "fit_per_kwh",
    "import_per_kwh",
    "pv_kw",
    "load_kw",
    "server_rack_kw",
    "hot_water",
    "ev_kw",
    "ev_source",
    "export",
    "battery_charge_deferred",
    "battery_target_kw",
    "site_export_target_kw",
    "battery_charge_kw",
    "battery_discharge_kw",
    "battery_export_kw",
    "solar_export_kw",
    "grid_import_kw",
    "curtailed_kw",
    "predicted_soc_pct",
    "protected_soc_pct",
    "total_export_revenue",
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value[:limit] if isinstance(item, dict)]


def _compact_plan_points(value: Any) -> list[dict[str, Any]]:
    """Bound Pilot's display contract without copying per-point flow graphs."""

    if not isinstance(value, list):
        return []
    points = [item for item in value if isinstance(item, dict)]
    if not points:
        return []
    step = max(1, math.ceil(len(points) / PILOT_PLAN_POINT_LIMIT))
    selected = points[::step]
    if selected[-1] is not points[-1]:
        if len(selected) >= PILOT_PLAN_POINT_LIMIT:
            selected[-1] = points[-1]
        else:
            selected.append(points[-1])
    return [
        {
            key: deepcopy(point[key])
            for key in PILOT_PLAN_POINT_FIELDS
            if key in point
        }
        for point in selected
    ]


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _watts(value_kw: Any) -> float | None:
    value = _number(value_kw)
    return round(value * 1000, 1) if value is not None else None


def _direction(value: float | None, positive: str, negative: str) -> str:
    if value is None or abs(value) < POWER_IDLE_WATTS:
        return "idle"
    return positive if value > 0 else negative


class EnergyManagerClient:
    """Read-only, timestamp-ordered cache for the standalone energy manager."""

    def __init__(
        self,
        settings: IntegrationSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = settings.energy_manager_url.rstrip("/")
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self._snapshot: dict[str, Any] | None = None
        self._plan: dict[str, Any] | None = None
        self._snapshot_observed_at: datetime | None = None
        self._plan_generated_at: datetime | None = None
        self._plan_id: str | None = None
        self._last_snapshot_success: datetime | None = None
        self._last_plan_success: datetime | None = None
        self._snapshot_error: str | None = None
        self._plan_error: str | None = None
        self._history_samples: list[dict[str, Any]] = []
        self._client: httpx.AsyncClient | None = None
        self._stop_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def run(self) -> None:
        if not self.configured:
            return
        self._stop_event.clear()
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.settings.energy_manager_timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            self._client = client
            next_plan_at = 0.0
            try:
                while not self._stop_event.is_set():
                    now = monotonic()
                    plan_due = now >= next_plan_at
                    plan_refreshed = await self.poll_once(plan_due=plan_due)
                    if plan_refreshed or plan_due:
                        next_plan_at = monotonic() + self.settings.energy_manager_plan_interval_seconds
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=self.settings.energy_manager_snapshot_interval_seconds,
                        )
                    except TimeoutError:
                        pass
            finally:
                self._client = None

    async def stop(self) -> None:
        self._stop_event.set()

    async def poll_once(self, *, plan_due: bool = False) -> bool:
        """Refresh live state and fetch a plan when due or its advertised ID changes."""

        async with self._refresh_lock:
            accepted = await self._refresh_snapshot()
            advertised_plan_id = self._advertised_plan_id(self._snapshot)
            plan_changed = bool(
                accepted
                and advertised_plan_id
                and advertised_plan_id != self._plan_id
            )
            if plan_due or plan_changed:
                return await self._refresh_plan()
            return False

    async def _request_json(self, path: str) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.get(path)
        else:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.settings.energy_manager_timeout_seconds,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(path)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("response is not an object")
        return payload

    async def _refresh_snapshot(self) -> bool:
        try:
            payload = await self._request_json("/api/v1/snapshot")
            telemetry = _mapping(payload.get("telemetry"))
            observed_at = _timestamp(telemetry.get("measured_at"))
            if observed_at is None:
                raise ValueError("telemetry measured_at is missing or invalid")
            if (
                self._snapshot_observed_at is not None
                and observed_at < self._snapshot_observed_at
            ):
                raise ValueError("telemetry timestamp regressed")
        except (httpx.HTTPError, ValueError) as error:
            self._snapshot_error = str(error)[:300]
            return False
        self._snapshot = deepcopy(payload)
        self._snapshot_observed_at = observed_at
        self._record_history(payload, observed_at)
        self._last_snapshot_success = self.clock()
        self._snapshot_error = None
        return True

    def _record_history(
        self,
        payload: dict[str, Any],
        observed_at: datetime,
    ) -> None:
        if self._history_samples:
            previous = _timestamp(self._history_samples[-1].get("at"))
            if previous is not None and (observed_at - previous).total_seconds() < 10:
                return
        telemetry = _mapping(payload.get("telemetry"))
        devices = _mapping(payload.get("devices"))
        self._history_samples.append(
            {
                "at": observed_at.isoformat(),
                "solar_w": _watts(telemetry.get("pv_kw")),
                "home_load_w": _watts(telemetry.get("load_kw")),
                "battery_w": _watts(telemetry.get("battery_kw")),
                "vehicle_w": _watts(devices.get("ev_power_kw")),
            }
        )
        cutoff = observed_at - timedelta(hours=24)
        self._history_samples = [
            sample
            for sample in self._history_samples
            if (sample_at := _timestamp(sample.get("at"))) is not None
            and sample_at >= cutoff
        ]

    async def _refresh_plan(self) -> bool:
        try:
            payload = await self._request_json("/api/v1/plan")
            rolling = _mapping(payload.get("rolling"))
            generated_at = _timestamp(rolling.get("generated_at"))
            if rolling and generated_at is None:
                raise ValueError("plan generated_at is missing or invalid")
            if (
                generated_at is not None
                and self._plan_generated_at is not None
                and generated_at < self._plan_generated_at
            ):
                raise ValueError("plan timestamp regressed")
        except (httpx.HTTPError, ValueError) as error:
            self._plan_error = str(error)[:300]
            return False
        self._plan = deepcopy(payload)
        self._plan_generated_at = generated_at
        self._plan_id = self._plan_identifier(payload)
        self._last_plan_success = self.clock()
        self._plan_error = None
        return True

    @staticmethod
    def _advertised_plan_id(snapshot: dict[str, Any] | None) -> str | None:
        if not snapshot:
            return None
        candidates = (
            snapshot.get("plan_id"),
            _mapping(snapshot.get("plan")).get("plan_id"),
            _mapping(snapshot.get("command")).get("plan_id"),
            _mapping(snapshot.get("service")).get("plan_id"),
        )
        return next((str(value) for value in candidates if value), None)

    @staticmethod
    def _plan_identifier(payload: dict[str, Any]) -> str | None:
        rolling = _mapping(payload.get("rolling"))
        value = rolling.get("plan_id") or payload.get("plan_id")
        return str(value) if value else None

    def health(self) -> dict[str, Any]:
        now = self.clock()
        age_seconds = (
            max(0.0, (now - self._snapshot_observed_at).total_seconds())
            if self._snapshot_observed_at is not None
            else None
        )
        snapshot_stale = age_seconds is None or age_seconds > self.settings.energy_manager_stale_after_seconds
        advertised_plan_id = self._advertised_plan_id(self._snapshot)
        plan_consistent = bool(
            self._plan is not None
            and (
                advertised_plan_id is None
                or (self._plan_id is not None and advertised_plan_id == self._plan_id)
            )
        )
        plan_poll_age_seconds = (
            max(0.0, (now - self._last_plan_success).total_seconds())
            if self._last_plan_success is not None
            else None
        )
        # A rolling plan normally refreshes every 20 seconds. Do not project
        # an old plan after two missed polls, even when live power telemetry is
        # still healthy.
        plan_stale_after = max(
            self.settings.energy_manager_stale_after_seconds,
            self.settings.energy_manager_plan_interval_seconds * 2.5,
        )
        plan_stale = (
            plan_poll_age_seconds is None
            or plan_poll_age_seconds > plan_stale_after
            or not plan_consistent
        )
        stale = snapshot_stale or plan_stale
        return {
            "configured": self.configured,
            "status": (
                "not_configured"
                if not self.configured
                else "unavailable"
                if self._snapshot is None
                else "stale"
                if stale
                else "ok"
            ),
            "stale": stale if self.configured else False,
            "snapshot_stale": snapshot_stale if self.configured else False,
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "advertised_plan_id": advertised_plan_id,
            "plan_consistent": plan_consistent,
            "plan_stale": plan_stale if self.configured else False,
            "plan_poll_age_seconds": (
                round(plan_poll_age_seconds, 1)
                if plan_poll_age_seconds is not None
                else None
            ),
            "observed_at": (
                self._snapshot_observed_at.isoformat()
                if self._snapshot_observed_at is not None
                else None
            ),
            "plan_id": self._plan_id,
            "plan_generated_at": (
                self._plan_generated_at.isoformat()
                if self._plan_generated_at is not None
                else None
            ),
            "last_snapshot_success": (
                self._last_snapshot_success.isoformat()
                if self._last_snapshot_success is not None
                else None
            ),
            "last_plan_success": (
                self._last_plan_success.isoformat()
                if self._last_plan_success is not None
                else None
            ),
            "snapshot_error": self._snapshot_error,
            "plan_error": self._plan_error,
        }

    def energy_snapshot(self) -> dict[str, Any]:
        """Return the compact energy contract used by surfaces and assistant tools."""

        fields = self._projection(include_plan_points=False)
        power = fields["power"]
        observed_at = fields["observed_at"]

        def measurement(value: float | None, *, percent: bool = False) -> dict[str, Any]:
            return {
                "value": value,
                "unit": "%" if percent else "W",
                "observed_at": observed_at,
            }

        solar = measurement(power["solar_w"])
        grid = measurement(power["grid_w"])
        battery = measurement(power["battery_w"])
        battery_soc = measurement(power["battery_soc_percent"], percent=True)
        home_load = measurement(power["home_load_w"])
        grid["direction"] = power["directions"]["grid"]
        battery["direction"] = power["directions"]["battery"]
        return {
            "status": fields["energy_status"],
            "source": "standalone_energy_manager",
            "observed_at": observed_at,
            "stale": fields["stale"],
            "solar": solar,
            "grid": grid,
            "battery": battery,
            "battery_soc": battery_soc,
            "home_load": home_load,
            "power": power,
            "arrays": fields["arrays"],
            "vehicle": fields["vehicle"],
            "hot_water": fields["hot_water"],
            "tariff": fields["tariff"],
            "plan": fields["plan"],
            "flow": fields["flow"],
            "financial": fields["financial"],
            "server": fields["server"],
            "manager_health": fields["manager_health"],
        }

    def dashboard_fields(self) -> dict[str, Any]:
        fields = self._projection(include_plan_points=True)
        fields["history"] = self.history_projection()
        return fields

    def history_projection(self) -> dict[str, Any]:
        timezone = ZoneInfo(self.settings.home_timezone)
        now = self.clock()
        local_now = now.astimezone(timezone)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        started_at = local_start.astimezone(UTC)
        ended_at = (local_start + timedelta(days=1)).astimezone(UTC)
        samples = [
            sample
            for sample in self._history_samples
            if (sample_at := _timestamp(sample.get("at"))) is not None
            and started_at <= sample_at <= now
        ]
        if len(samples) > 288:
            step = math.ceil(len(samples) / 288)
            selected = samples[::step]
            if selected[-1] is not samples[-1]:
                selected.append(samples[-1])
            samples = selected[-288:]

        configured = (
            ("home_load", "Home load", "#FF5D6C", "home_load_w", True, None, "smooth"),
            ("battery", "Battery power", "#55B6FF", "battery_w", False, POWER_IDLE_WATTS, "step"),
            ("solar", "Solar power", "#FFC247", "solar_w", False, None, "smooth"),
            ("tesla", "Tesla charging", "#D970FF", "vehicle_w", True, POWER_IDLE_WATTS, "step"),
        )
        return {
            "period_hours": 24,
            "window": "calendar_day",
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "source": "standalone_energy_manager_cache",
            "series": [
                {
                    "id": identifier,
                    "label": label,
                    "color": color,
                    "unit": "W",
                    "activity_threshold_w": threshold,
                    "render_mode": render_mode,
                    "points": [
                        {
                            "at": sample["at"],
                            "value": -float(sample[key]) if negative else float(sample[key]),
                        }
                        for sample in samples
                        if (value := sample.get(key)) is not None
                    ],
                }
                for identifier, label, color, key, negative, threshold, render_mode in configured
            ],
        }

    def _projection(self, *, include_plan_points: bool) -> dict[str, Any]:
        snapshot = deepcopy(self._snapshot) if self._snapshot is not None else {}
        health = self.health()
        # Never mix a fresh snapshot with an older advertised plan. Live power
        # remains useful, but plan/revenue fields stay unavailable until the
        # matching plan has been fetched successfully.
        plan_payload = (
            deepcopy(self._plan)
            if self._plan is not None and not health["plan_stale"]
            else {}
        )
        telemetry = _mapping(snapshot.get("telemetry"))
        devices = _mapping(snapshot.get("devices"))
        forecast = _mapping(snapshot.get("forecast"))
        forecast_arrays = _mapping(forecast.get("arrays"))
        command = _mapping(snapshot.get("command"))
        service = _mapping(snapshot.get("service"))
        prices = _mapping(snapshot.get("prices"))
        rolling = _mapping(plan_payload.get("rolling"))
        # The snapshot command is polled every two seconds; /plan's copy may be
        # up to one plan interval old and must not replace the live actuator state.
        current = command or _mapping(plan_payload.get("current"))

        solar_w = _watts(telemetry.get("pv_kw"))
        grid_w = _watts(telemetry.get("grid_kw"))
        battery_w = _watts(telemetry.get("battery_kw"))
        home_w = _watts(telemetry.get("load_kw"))
        soc = _number(telemetry.get("soc_pct"))
        vehicle_w = _watts(devices.get("ev_power_kw"))
        hot_water_w = _watts(devices.get("hot_water_power_kw"))

        server = (
            _mapping(snapshot.get("server_rack"))
            or _mapping(snapshot.get("server"))
            or _mapping(snapshot.get("server_desk"))
        )
        server_w = next(
            (
                value
                for candidate in (
                    server.get("server_rack_power_w"),
                    server.get("power_w"),
                    telemetry.get("server_desk_w"),
                    telemetry.get("server_w"),
                )
                if (value := _number(candidate)) is not None
            ),
            None,
        )
        server_kw = next(
            (
                value
                for candidate in (
                    telemetry.get("server_desk_kw"),
                    telemetry.get("server_kw"),
                    server.get("power_kw"),
                    server.get("server_desk_kw"),
                )
                if (value := _number(candidate)) is not None
            ),
            None,
        )
        if server_w is None and server_kw is not None:
            server_w = round(server_kw * 1000, 1)

        directions = {
            "grid": _direction(grid_w, "importing", "exporting"),
            "battery": _direction(battery_w, "discharging", "charging"),
            "vehicle": "charging" if vehicle_w is not None and vehicle_w >= POWER_IDLE_WATTS else "idle",
            "hot_water": "heating" if hot_water_w is not None and hot_water_w >= 1000 else "idle",
            "server_rack": "consuming" if server_w is not None and server_w >= FLOW_IDLE_WATTS else "idle",
        }
        power = {
            "solar_w": solar_w,
            "grid_w": grid_w,
            "battery_w": battery_w,
            "battery_soc_percent": round(soc, 1) if soc is not None else None,
            "home_load_w": home_w,
            "server_rack_w": server_w,
            "vehicle_w": vehicle_w,
            "hot_water_w": hot_water_w,
            "directions": directions,
            "flow_active": {
                "solar": solar_w is not None and solar_w >= FLOW_IDLE_WATTS,
                "grid": grid_w is not None and abs(grid_w) >= POWER_IDLE_WATTS,
                "battery": battery_w is not None and abs(battery_w) >= POWER_IDLE_WATTS,
                "home": home_w is not None and home_w >= FLOW_IDLE_WATTS,
                "server_rack": server_w is not None and server_w >= FLOW_IDLE_WATTS,
                "vehicle": vehicle_w is not None and vehicle_w >= POWER_IDLE_WATTS,
                "hot_water": hot_water_w is not None and hot_water_w >= 1000,
            },
        }

        arrays: dict[str, Any] = {}
        for identifier in ("pv1", "pv2", "pv3"):
            item = _mapping(forecast_arrays.get(identifier))
            measured_kw = _number(telemetry.get(f"{identifier}_kw"))
            expected_kw = _number(item.get("expected_kw"))
            arrays[identifier] = {
                "orientation": item.get("orientation"),
                "capacity_kwp": _number(item.get("capacity_kwp")),
                "measured_w": round(measured_kw * 1000, 1) if measured_kw is not None else None,
                "expected_w": round(expected_kw * 1000, 1) if expected_kw is not None else None,
                "error_w": _watts(item.get("error_kw")),
            }

        rolling_hot_water = _mapping(rolling.get("hot_water"))
        hot_water = {
            "available": devices.get("hot_water_available") is True,
            "relay_on": devices.get("hot_water_on") is True,
            "confirmed": devices.get("hot_water_confirmed") is True,
            "power_w": hot_water_w,
            "runtime_hours": _number(devices.get("hot_water_runtime_hours")),
            # DeviceState historically defaulted this field to "off". The
            # live command is the authoritative source allocation decision.
            "source": current.get("hot_water_source") or devices.get("hot_water_source") or "off",
            "planned_start": rolling_hot_water.get("planned_start"),
            "planned_end": rolling_hot_water.get("planned_end"),
            "deadline": rolling_hot_water.get("deadline"),
            "remaining_hours": _number(rolling_hot_water.get("remaining_hours")),
        }
        rolling_ev = _mapping(rolling.get("ev"))
        vehicle = {
            "name": "Jarvis",
            "home": devices.get("ev_home") is True,
            "connected": devices.get("ev_plugged") is True,
            "plugged": devices.get("ev_plugged") is True,
            "charging": devices.get("ev_charging") is True or (vehicle_w is not None and vehicle_w >= POWER_IDLE_WATTS),
            "power_w": vehicle_w,
            "state_of_charge_percent": _number(devices.get("ev_soc_pct")),
            "charge_limit_percent": _number(devices.get("ev_limit_pct")),
            "amps": _number(devices.get("ev_amps")),
            "planned_start": rolling_ev.get("planned_start"),
            "planned_end": rolling_ev.get("planned_end"),
            "planned_input_kwh": _number(rolling_ev.get("planned_input_kwh")),
            "recommendation": rolling_ev.get("recommendation"),
            "trip_requirement": rolling_ev.get("trip_requirement"),
        }

        def price(channel: str) -> float | None:
            value = _number(_mapping(prices.get(channel)).get("price_per_kwh"))
            return round(value * 100, 3) if value is not None else None

        points = _list(rolling.get("points"), 432)
        tariff = {
            "import_cents_per_kwh": price("amber_import"),
            "feed_in_cents_per_kwh": price("amber_fit"),
            "aemo_cents_per_kwh": price("aemo"),
            "feed_in_forecast": [
                {
                    "at": point.get("start"),
                    "end": point.get("end"),
                    "cents_per_kwh": (
                        round(value * 100, 3)
                        if (value := _number(point.get("fit_per_kwh"))) is not None
                        else None
                    ),
                }
                for point in points
            ],
            "import_forecast": [
                {
                    "at": point.get("start"),
                    "end": point.get("end"),
                    "cents_per_kwh": (
                        round(value * 100, 3)
                        if (value := _number(point.get("import_per_kwh"))) is not None
                        else None
                    ),
                }
                for point in points
            ],
        }

        summary = _mapping(rolling.get("summary"))
        plan = {
            "plan_id": rolling.get("plan_id"),
            "generated_at": rolling.get("generated_at"),
            "horizon_end": rolling.get("horizon_end"),
            "protected_reserve_percent": _number(
                current.get("protected_soc_pct")
                if current.get("protected_soc_pct") is not None
                else rolling.get("protected_reserve_pct")
            ),
            "current_action": current.get("mode"),
            "current_reason": current.get("reason"),
            "site_export_target_kw": _number(current.get("site_export_target_kw")),
            "battery_target_kw": _number(current.get("battery_target_kw")),
            "zero_export": current.get("zero_export") is True,
            "summary": deepcopy(summary),
            "export_windows": _list(rolling.get("export_windows"), 36),
            "predicted_soc_path": _list(rolling.get("predicted_soc_path"), 144),
            "hot_water": deepcopy(rolling_hot_water),
            "ev": deepcopy(rolling_ev),
        }
        if include_plan_points:
            plan["points"] = _compact_plan_points(points)

        allocation = _mapping(snapshot.get("source_allocation"))
        authoritative_flow = (
            _mapping(snapshot.get("power_flow"))
            or _mapping(snapshot.get("flow"))
        )
        flow = deepcopy(authoritative_flow)
        flow.update({
            "source_allocation": deepcopy(allocation),
            "mode": current.get("mode"),
            "reason": current.get("reason"),
            "battery_target_kw": _number(current.get("battery_target_kw")),
            "site_export_target_kw": _number(current.get("site_export_target_kw")),
            "zero_export": current.get("zero_export") is True,
        })
        manager_health = {
            **health,
            "control_enabled": service.get("control_enabled") is True,
            "command_phase": service.get("command_phase"),
            "service_error": service.get("error"),
            "mqtt_connected": service.get("mqtt_connected"),
        }
        outcomes = _mapping(snapshot.get("outcomes"))
        daily = _mapping(outcomes.get("current_daily"))
        battery_revenue = _number(summary.get("battery_export_revenue"))
        total_revenue = _number(summary.get("total_export_revenue"))
        realised_battery_revenue = _number(daily.get("battery_export_revenue"))
        realised_export_revenue = _number(daily.get("export_revenue"))
        realised_import_cost = _number(daily.get("import_cost"))
        realised_wear = _number(daily.get("wear_cost"))
        realised_net = (
            realised_export_revenue - (realised_import_cost or 0.0) - (realised_wear or 0.0)
            if realised_export_revenue is not None
            else None
        )
        return {
            "source": "standalone_energy_manager",
            "observed_at": health["observed_at"],
            "stale": health["stale"],
            "energy_status": health["status"],
            "power": power,
            "arrays": arrays,
            "vehicle": vehicle,
            "hot_water": hot_water,
            "tariff": tariff,
            "plan": plan,
            "flow": flow,
            "financial": {
                # Retain the original aggregate key for existing Pilot clients.
                "planned_export_revenue": total_revenue if total_revenue is not None else battery_revenue,
                "planned_total_export_revenue": total_revenue,
                "planned_solar_export_revenue": _number(summary.get("solar_export_revenue")),
                "planned_battery_export_revenue": battery_revenue,
                "planned_battery_export_kwh": _number(summary.get("battery_export_kwh")),
                "planned_battery_export_wear": _number(summary.get("battery_export_wear_cost")),
                "planned_battery_export_retained_value": _number(summary.get("battery_export_retained_value")),
                "planned_battery_export_net_benefit": _number(summary.get("battery_export_net_benefit")),
                "realised_battery_export_revenue_today": realised_battery_revenue,
                "realised_export_revenue_today": realised_export_revenue,
                "realised_import_cost_today": realised_import_cost,
                "realised_battery_wear_today": realised_wear,
                "realised_net_benefit_today": realised_net,
            },
            "server": {
                "label": "Server + desk",
                "power_w": server_w,
                "energy_today_kwh": _number(server.get("energy_today_kwh")),
                "available": server_w is not None,
                "confidence": server.get("confidence"),
                "ups_status": server.get("status"),
                "battery_soc_percent": _number(server.get("battery_charge_pct")),
                "battery_runtime_seconds": _number(server.get("battery_runtime_seconds")),
                "age_seconds": _number(server.get("age_seconds")),
            },
            "manager_health": manager_health,
        }
