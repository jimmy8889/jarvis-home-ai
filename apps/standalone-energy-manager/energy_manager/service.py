from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
import hashlib
import logging
import math
from pathlib import Path
import socket
from typing import Any
from zoneinfo import ZoneInfo
from collections import deque

import aiohttp

from .config import Settings
from .devices import FlexibleLoadController, TeslaMateState
from .ev import EVTripMode, ev_requirement, next_ev_departure, normalize_trip_mode, parse_deadline, trip_label
from .feeds import AemoFeed, AmberFeed, EcowittIrradiance, SolarForecasts, amber_channels
from .flows import conserved_power_flow, export_split, source_allocation_from_flow
from .models import Command, DeviceState, PriceInterval, Telemetry, command_semantic_hash
from .nut import NutCollector
from .policy import Policy, fresh_price_value, next_boundary
from .planner import RollingPlanner, provider_power
from .reporting import InfluxReporter, MqttReporter, publish_discovery, publish_nut_discovery, publish_saj_discovery
from .resilience import allocate_ups_power, fuse_grid_health, resilience_stage
from .saj import SajController
from .shutdown import NodeShutdownCoordinator
from .storage import Storage

LOG = logging.getLogger(__name__)


def _semantic_digest(value: Any, volatile_keys: frozenset[str] = frozenset()) -> str:
    def stable(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: stable(child)
                for key, child in sorted(item.items())
                if key not in volatile_keys
            }
        if isinstance(item, list):
            return [stable(child) for child in item]
        return item

    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, default=str).encode()).hexdigest()[:20]


def plan_semantic_id(plan: dict[str, Any]) -> str:
    """Identify physical/economic plan changes, excluding build-time churn."""

    return _semantic_digest(plan, frozenset({"generated_at", "plan_id"}))


def forecast_semantic_digest(providers: dict[str, Any]) -> str:
    """Ignore provider receipt metadata while detecting changed forecasts."""

    return _semantic_digest(
        providers,
        frozenset({"issued_at", "received_at", "fetched_at", "updated_at"}),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def restorable_plan(plan: dict[str, Any] | None, settings: Settings, now: datetime | None = None) -> dict[str, Any] | None:
    """Reject expired or revision-incompatible state after restart/migration."""
    if not isinstance(plan, dict):
        return None
    now = now or datetime.now(UTC)
    try:
        horizon_end = datetime.fromisoformat(str(plan["horizon_end"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    if horizon_end.tzinfo is None:
        horizon_end = horizon_end.replace(tzinfo=UTC)
    if horizon_end <= now:
        return None
    if plan.get("software_revision") != settings.software_revision:
        return None
    if plan.get("configuration_revision") != settings.configuration_revision():
        return None
    return plan


def live_power_flow(telemetry: Telemetry, devices: DeviceState, server_rack_kw: float = 0.0) -> dict[str, Any]:
    ordinary = max(0.0, float(telemetry.load_kw or 0) - devices.ev_power_kw - devices.hot_water_power_kw)
    return conserved_power_flow(
        pv_kw=telemetry.pv_kw,
        battery_kw=telemetry.battery_kw,
        grid_kw=telemetry.grid_kw,
        ordinary_house_kw=ordinary,
        hot_water_kw=devices.hot_water_power_kw,
        ev_kw=devices.ev_power_kw,
        server_rack_kw=server_rack_kw,
        at=telemetry.measured_at,
    )


def source_allocation(
    telemetry: Telemetry,
    devices: DeviceState,
    server_rack_kw: float = 0.0,
) -> dict[str, dict[str, float]]:
    return source_allocation_from_flow(live_power_flow(telemetry, devices, server_rack_kw))


class MinuteAverageAccumulator:
    """Produce one arithmetic mean per UTC minute from coherent power frames."""

    def __init__(self) -> None:
        self.start: datetime | None = None
        self.sums: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    def add(self, at: datetime, values: dict[str, Any]) -> tuple[datetime, dict[str, float]] | None:
        minute = at.astimezone(UTC).replace(second=0, microsecond=0)
        complete = None
        if self.start is None:
            self.start = minute
        elif minute != self.start:
            complete = (
                self.start,
                {
                    key: total / self.counts[key]
                    for key, total in self.sums.items()
                    if self.counts.get(key, 0) > 0
                },
            )
            self.start = minute
            self.sums = {}
            self.counts = {}
        for key, value in values.items():
            if value is None or isinstance(value, bool):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            self.sums[key] = self.sums.get(key, 0.0) + number
            self.counts[key] = self.counts.get(key, 0) + 1
        return complete


class OutcomeAccumulator:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.start: datetime | None = None
        self.last_at: datetime | None = None
        self.values: dict[str, Any] = {}

    def _completed(self) -> dict[str, Any]:
        duration = float(self.values.get("duration_hours", 0.0))
        confidence = float(self.values.get("flow_confidence_weighted", 0.0)) / max(duration, 1e-9)
        result = {
            "interval_start": self.start.isoformat() if self.start else None,
            **{key: value for key, value in self.values.items() if key not in {"fit_price_weighted", "import_price_weighted", "flow_confidence_weighted"}},
            "average_fit_per_kwh": float(self.values.get("fit_price_weighted", 0.0)) / max(duration, 1e-9),
            "average_import_price_per_kwh": float(self.values.get("import_price_weighted", 0.0)) / max(duration, 1e-9),
            "export_attribution_method": "priority_inference_v1",
            "export_attribution_confidence_score": round(confidence, 3),
            "export_attribution_confidence_label": "high" if confidence >= 0.9 else "medium" if confidence >= 0.6 else "low",
        }
        for energy_key, power_key in (
            ("pv_kwh", "average_pv_kw"), ("pv1_kwh", "average_pv1_kw"),
            ("pv2_kwh", "average_pv2_kw"), ("pv3_kwh", "average_pv3_kw"),
            ("house_load_kwh", "average_house_load_kw"),
            ("whole_house_load_kwh", "average_whole_house_load_kw"), ("ev_kwh", "average_ev_kw"),
            ("hot_water_kwh", "average_hot_water_kw"), ("server_rack_kwh", "average_server_rack_kw"),
            ("battery_net_kwh", "average_battery_kw"), ("grid_net_kwh", "average_grid_kw"),
        ):
            result[power_key] = float(self.values.get(energy_key, 0.0)) / max(duration, 1e-9)
        return result

    def add(
        self,
        at: datetime,
        telemetry: Telemetry,
        devices: DeviceState,
        fit: float | None,
        import_price: float | None,
        server_rack_kw: float = 0.0,
        expected_pv_kw: float | None = None,
    ) -> dict[str, Any] | None:
        interval = datetime.fromtimestamp(int(at.timestamp()) // 300 * 300, UTC)
        complete = None
        if self.start is None:
            self.start = interval
        elif interval != self.start:
            complete = self._completed()
            self.start = interval
            self.values = {}
            self.last_at = None
        if self.last_at:
            hours = max(0.0, min(10.0, (at - self.last_at).total_seconds())) / 3600
            grid = float(telemetry.grid_kw or 0)
            battery = float(telemetry.battery_kw or 0)
            exported = max(0.0, -grid) * hours
            imported = max(0.0, grid) * hours
            flow = live_power_flow(telemetry, devices, server_rack_kw)
            solar_export_kw, battery_export_kw = export_split(flow)
            solar_exported = solar_export_kw * hours
            battery_exported = battery_export_kw * hours
            self.values["export_kwh"] = self.values.get("export_kwh", 0) + exported
            self.values["import_kwh"] = self.values.get("import_kwh", 0) + imported
            self.values["export_revenue"] = self.values.get("export_revenue", 0) + exported * float(fit or 0)
            self.values["solar_export_kwh"] = self.values.get("solar_export_kwh", 0) + solar_exported
            self.values["battery_export_kwh"] = self.values.get("battery_export_kwh", 0) + battery_exported
            self.values["solar_export_revenue"] = self.values.get("solar_export_revenue", 0) + solar_exported * float(fit or 0)
            self.values["battery_export_revenue"] = self.values.get("battery_export_revenue", 0) + battery_exported * float(fit or 0)
            self.values["import_cost"] = self.values.get("import_cost", 0) + imported * float(import_price or 0)
            self.values["battery_discharge_kwh"] = self.values.get("battery_discharge_kwh", 0) + max(0.0, battery) * hours
            self.values["wear_cost"] = self.values.get("wear_cost", 0) + max(0.0, battery) * hours * self.settings.battery_wear_per_kwh
            self.values["ev_kwh"] = self.values.get("ev_kwh", 0) + devices.ev_power_kw * hours
            self.values["hot_water_kwh"] = self.values.get("hot_water_kwh", 0) + devices.hot_water_power_kw * hours
            self.values["pv_kwh"] = self.values.get("pv_kwh", 0) + max(0.0, float(telemetry.pv_kw or 0)) * hours
            for field in ("pv1_kw", "pv2_kw", "pv3_kw"):
                key = field.replace("_kw", "_kwh")
                self.values[key] = self.values.get(key, 0) + max(0.0, float(getattr(telemetry, field) or 0)) * hours
            # The authoritative SAJ backup-output register is the whole-site
            # load.  Outcomes expose ordinary house demand separately, so do
            # not count the independently measured Tesla and hot-water loads
            # a second time.
            ordinary_house_kw = max(
                0.0,
                float(telemetry.load_kw or 0)
                - float(devices.ev_power_kw or 0)
                - float(devices.hot_water_power_kw or 0),
            )
            self.values["house_load_kwh"] = self.values.get("house_load_kwh", 0) + ordinary_house_kw * hours
            self.values["whole_house_load_kwh"] = self.values.get("whole_house_load_kwh", 0) + max(0.0, float(telemetry.load_kw or 0)) * hours
            self.values["battery_charge_kwh"] = self.values.get("battery_charge_kwh", 0) + max(0.0, -battery) * hours
            self.values["battery_net_kwh"] = self.values.get("battery_net_kwh", 0) + battery * hours
            self.values["grid_net_kwh"] = self.values.get("grid_net_kwh", 0) + grid * hours
            self.values["server_rack_kwh"] = self.values.get("server_rack_kwh", 0) + max(0.0, server_rack_kw) * hours
            self.values["duration_hours"] = self.values.get("duration_hours", 0) + hours
            self.values["fit_price_weighted"] = self.values.get("fit_price_weighted", 0) + float(fit or 0) * hours
            self.values["import_price_weighted"] = self.values.get("import_price_weighted", 0) + float(import_price or 0) * hours
            self.values["flow_confidence_weighted"] = self.values.get("flow_confidence_weighted", 0) + float(flow["confidence"]["score"]) * hours
            self.values["max_abs_meter_balance_error_kw"] = max(float(self.values.get("max_abs_meter_balance_error_kw", 0)), abs(float(flow["meter_balance_error_kw"])))
            if expected_pv_kw is not None:
                error = float(telemetry.pv_kw or 0) - float(expected_pv_kw)
                self.values["pv_forecast_error_kwh"] = self.values.get("pv_forecast_error_kwh", 0) + error * hours
                self.values["pv_forecast_abs_error_kwh"] = self.values.get("pv_forecast_abs_error_kwh", 0) + abs(error) * hours
            for consumer, sources in source_allocation_from_flow(flow).items():
                for source in ("solar_kw", "battery_kw", "grid_kw"):
                    key = f"{consumer}_{source.removesuffix('_kw')}_kwh"
                    self.values[key] = self.values.get(key, 0) + sources[source] * hours
        self.last_at = at
        return complete


class EnergyManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(settings.data_dir / "energy-manager.sqlite3")
        self.session: aiohttp.ClientSession | None = None
        self.saj = SajController(settings)
        self.telemetry: Telemetry | None = None
        self.devices = DeviceState(ev_limit_pct=settings.ev_charge_limit_pct)
        self.loads = FlexibleLoadController(settings, self.devices)
        self.teslamate = TeslaMateState(self.devices)
        self.mqtt = MqttReporter(settings)
        self.mqtt.tesla_callback = self.teslamate.message
        self.amber: AmberFeed | None = None
        self.aemo: AemoFeed | None = None
        self.solar: SolarForecasts | None = None
        self.irradiance: EcowittIrradiance | None = None
        self.nut = NutCollector(settings)
        self.influx: InfluxReporter | None = None
        self.shutdown: NodeShutdownCoordinator | None = None
        self.policy = Policy(settings)
        self.planner = RollingPlanner(settings)
        self.rolling_plan: dict[str, Any] | None = None
        self.command: Command | None = None
        self.command_phase = "starting"
        self.command_error: str | None = None
        self.started_at = datetime.now(UTC)
        self.tasks: list[asyncio.Task] = []
        self.replan_lock = asyncio.Lock()
        self.outcomes = OutcomeAccumulator(settings)
        self.power_minutes = MinuteAverageAccumulator()
        self.last_outcome: dict[str, Any] | None = None
        self.current_daily: dict[str, Any] | None = None
        self.last_ev_trip_result: dict[str, Any] | None = None
        self.last_export_change_at: datetime | None = None
        self.last_price_interval_start: datetime | None = None
        self.hw_start_baseline_kw: float | None = None
        self.hw_start_baseline_battery_kw: float | None = None
        self.hw_start_at: datetime | None = None
        self.hw_last_count_at: datetime | None = None
        self.hw_battery_violation_started: datetime | None = None
        self.hw_blocked_until: datetime | None = None
        self.aemo_summary: dict[str, Any] | None = None
        self.expected_pv_kw = 0.0
        self.expected_pv_measured_at: datetime | None = None
        self.expected_pv_source = "unavailable"
        self.control_expected = settings.control_enabled
        self.last_recorded_command_hash: str | None = None
        self.last_recorded_command_phase: str | None = None
        self.last_battery_record_at: datetime | None = None
        self.last_forecast_record_at: datetime | None = None
        self.last_saj_energy_record_at: datetime | None = None
        self.last_watchdog_expiry: datetime | None = None
        self.last_device_plan_signature: tuple[Any, ...] | None = None
        self.last_forecast_plan_digest: str | None = None
        self.startup_safe_state_pending = True
        self.hw_last_firmware_sync_at: datetime | None = None
        self.hw_confirmation_hold_until: datetime | None = None
        self.hw_confirmation_command: Command | None = None
        self.disabled_safe_negative_fit: bool | None = None
        self.last_amber_poll_success_at: datetime | None = None
        self.plan_dispatch_ready = False
        self.amber_price_ready = False
        self.saj_discovery_published = False
        self.nut_discovery_variables: frozenset[str] = frozenset()
        # Six hours of compact, one-second UPS telemetry for the standalone
        # dashboard.  Full-fidelity history continues to be written to Influx;
        # this bounded buffer keeps the web view fast and independent of it.
        self.nut_history: deque[dict[str, Any]] = deque(maxlen=6 * 60 * 60)
        self.last_telemetry_replan_at: datetime | None = None
        self.grid_health, self.protected_supply = fuse_grid_health(None, self.nut.state)
        self.ups_allocation = allocate_ups_power(self.nut.state)
        self.resilience_stage = "normal"
        self.outage_epoch: str | None = None
        self.outage_lost_at: datetime | None = None
        self.grid_restored_candidate_at: datetime | None = None
        self.grid_control_inhibit = False
        self.resilience_stage_candidate: str | None = None
        self.resilience_stage_candidate_at: datetime | None = None
        self.resilience_lock = asyncio.Lock()
        self.ups_daily: dict[str, Any] = {}
        self.last_ups_energy_at: datetime | None = None
        self.last_ups_persist_at: datetime | None = None

    async def start(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30, connect=8)
        self.session = aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(family=socket.AF_INET))
        self.amber = AmberFeed(self.settings, self.session)
        self.aemo = AemoFeed(self.settings, self.session)
        self.solar = SolarForecasts(self.settings, self.session)
        self.irradiance = EcowittIrradiance(self.settings, self.session)
        self.influx = InfluxReporter(self.settings, self.session, self.storage)
        self.shutdown = NodeShutdownCoordinator(self.settings, self.session)
        stored_trip = await self.storage.setting("ev_trip_profile", None)
        legacy_trip = await self.storage.setting("ev_trip_requirement", self.settings.ev_trip_requirement)
        trip_profile = normalize_trip_mode(stored_trip if stored_trip is not None else legacy_trip)
        trip_deadline = str(await self.storage.setting("ev_trip_deadline", self.settings.ev_trip_deadline))
        if trip_profile is not EVTripMode.NO_TRIP and parse_deadline(trip_deadline, self.settings) is None:
            trip_deadline = next_ev_departure(self.settings, datetime.now(UTC)).isoformat()
        self.settings = replace(
            self.settings,
            min_sell_price_per_kwh=float(await self.storage.setting("min_sell_price_per_kwh", self.settings.min_sell_price_per_kwh)),
            ev_opportunistic_fit_max_per_kwh=float(await self.storage.setting("ev_opportunistic_fit_max_per_kwh", self.settings.ev_opportunistic_fit_max_per_kwh)),
            ev_grid_allowed=bool(await self.storage.setting("ev_grid_allowed", self.settings.ev_grid_allowed)),
            ev_charge_limit_pct=int(await self.storage.setting("ev_charge_limit_pct", self.settings.ev_charge_limit_pct)),
            ev_learned_consumption_kwh_per_km=float(await self.storage.setting("ev_learned_consumption_kwh_per_km", self.settings.ev_learned_consumption_kwh_per_km)),
            ev_trip_profile=trip_profile.value,
            ev_trip_requirement=trip_label(trip_profile),
            ev_trip_deadline=trip_deadline,
            hot_water_fixed_timer=bool(await self.storage.setting("hot_water_fixed_timer", self.settings.hot_water_fixed_timer)),
            hot_water_enabled=bool(await self.storage.setting("hot_water_enabled", self.settings.hot_water_enabled)),
            control_enabled=bool(await self.storage.setting("control_enabled", self.settings.control_enabled)),
        )
        self.last_ev_trip_result = await self.storage.setting("last_ev_trip_result", None)
        self.ups_daily = await self.storage.ups_daily(datetime.now(ZoneInfo(self.settings.timezone)).date())
        self.control_expected = self.settings.control_enabled
        self.policy = Policy(self.settings)
        self.planner = RollingPlanner(self.settings)
        self.saj.settings = self.settings
        self.loads.settings = self.settings
        self.outcomes.settings = self.settings
        self.devices.ev_limit_pct = self.settings.ev_charge_limit_pct
        await self._prepare_hot_water_startup_baseline()
        local_today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        try:
            # The interval journal is authoritative. Rebuild today's roll-up on
            # restart so an older aggregation implementation cannot leave stale
            # or over-counted averages on either dashboard.
            self.current_daily = await self.storage.rebuild_daily_outcome(
                local_today, self.settings.timezone
            )
        except ValueError:
            self.current_daily = None
        self.rolling_plan = restorable_plan(await self.storage.latest_plan(), self.settings)
        cached_forecasts = await self.storage.setting("solar_forecasts", {})
        if isinstance(cached_forecasts, dict):
            self.solar.providers = cached_forecasts
            if cached_forecasts:
                self.last_forecast_plan_digest = forecast_semantic_digest(cached_forecasts)
        self.tasks = [
            asyncio.create_task(self._bootstrap_feeds(), name="bootstrap-feeds"),
            asyncio.create_task(self.mqtt.run(), name="mqtt"),
            asyncio.create_task(self._saj_loop(), name="saj"),
            asyncio.create_task(self._amber_loop(), name="amber"),
            asyncio.create_task(self._aemo_loop(), name="aemo"),
            asyncio.create_task(self._forecast_loop(), name="forecast"),
            asyncio.create_task(self._irradiance_loop(), name="irradiance"),
            asyncio.create_task(self._device_loop(), name="devices"),
            asyncio.create_task(self._nut_loop(), name="nut"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self._command_watchdog_loop(), name="command-watchdog"),
            asyncio.create_task(self.influx.run(), name="influx-outbox"),
        ]
        await publish_discovery(self.mqtt)
        await self.storage.event("service_started", {"control_enabled": self.settings.control_enabled})

    async def _prepare_hot_water_startup_baseline(self) -> None:
        """Establish a clean relay-off load baseline before production resumes.

        A fast process restart can otherwise turn an already-running element
        back on before SAJ load has fallen. The new process then has no 3.7 kW
        step to confirm and cannot safely credit service runtime.
        """

        if not self.settings.control_enabled or not self.settings.hot_water_enabled:
            return
        try:
            await self.loads.refresh()
            await self.loads.set_hot_water(False)
            self.devices.hot_water_confirmed = False
            self.devices.hot_water_power_kw = 0.0
            self.hw_start_at = None
            self.hw_start_baseline_kw = None
            self.hw_confirmation_hold_until = None
            self.hw_confirmation_command = None
            await asyncio.sleep(5)
            await self.loads.refresh()
            if self.devices.hot_water_on:
                raise RuntimeError("hot-water relay remained on during startup baseline")
            await self.storage.event("hot_water_startup_baseline_ready", {"settle_seconds": 5})
        except Exception as exc:
            self.devices.hot_water_available = False
            self.loads.hot_water_error = f"hot-water startup baseline failed: {exc}"
            LOG.warning("Hot-water startup baseline failed; live confirmation remains required: %s", exc)

    async def _bootstrap_feeds(self) -> None:
        assert self.amber and self.aemo
        try:
            await self._record_prices(await self.amber.poll())
            polled_at = datetime.now(UTC)
            fit, general = amber_channels(self.amber, polled_at)
            if fresh_price_value(self.settings, fit, polled_at) is None or fresh_price_value(self.settings, general, polled_at) is None:
                raise RuntimeError("Amber poll returned no fresh covering import/FIT pair")
            self.last_amber_poll_success_at = polled_at
            await self.replan("amber_startup")
        except Exception as exc:
            LOG.warning("Initial Amber fetch failed: %s", exc)
        try:
            await self._record_prices(await self.aemo.poll())
            self.aemo_summary = await self.aemo.summary()
        except Exception as exc:
            LOG.warning("Initial AEMO fetch failed: %s", exc)

    async def stop(self) -> None:
        # Flexible loads stop cleanly; SAJ returns to self-consumption unless a
        # fresh negative FIT still requires anti-reflux.
        if self.settings.control_enabled:
            try:
                await self.loads.set_ev(False, 0, safety_reduction=True)
            except Exception:
                pass
            try:
                await self.loads.set_hot_water(False)
            except Exception:
                pass
        if self.settings.control_enabled:
            try:
                # A stopped production controller must release forced modes.
                await self.saj.safe_state(False, emergency=True)
            except Exception:
                pass
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.loads.close()
        await self.nut.close()
        await self.saj.close()
        if self.session:
            await self.session.close()

    async def _saj_loop(self) -> None:
        while True:
            started_mono = asyncio.get_running_loop().time()
            try:
                telemetry = await self.saj.poll()
                self.telemetry = telemetry
                await self._update_resilience()
                await self.mqtt.publish("saj/realtime", telemetry.as_dict(), retain=True, qos=0)
                if self.settings.saj_mqtt_discovery_enabled and not self.saj_discovery_published:
                    await publish_saj_discovery(self.mqtt, telemetry.inverter_identity)
                    self.saj_discovery_published = True
                await self._restore_startup_safe_state()
                await self._hot_water_evidence(telemetry)
                await self._record_power(telemetry)
                if (
                    self.last_telemetry_replan_at is None
                    or (telemetry.measured_at - self.last_telemetry_replan_at).total_seconds() >= 5
                ):
                    await self.replan("telemetry")
                    self.last_telemetry_replan_at = telemetry.measured_at
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.command_error = f"SAJ telemetry: {exc}"
                LOG.warning("SAJ poll failed: %s", exc)
            elapsed = asyncio.get_running_loop().time() - started_mono
            await asyncio.sleep(max(0.05, self.settings.saj_poll_seconds - elapsed))

    async def _amber_loop(self) -> None:
        assert self.amber
        while True:
            now = datetime.now(UTC)
            boundary = next_boundary(now)
            await asyncio.sleep(max(0, (boundary - now).total_seconds()))
            # Act on the already-cached forecast exactly at the boundary.
            await self._promote_cached_amber(boundary)
            await self.replan("amber_boundary")
            previous_offset = 0.0
            for offset in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0):
                await asyncio.sleep(max(0, offset - previous_offset))
                previous_offset = offset
                try:
                    intervals = await self.amber.poll()
                    await self._record_prices(intervals)
                    fit, general = amber_channels(self.amber)
                    polled_at = datetime.now(UTC)
                    if fresh_price_value(self.settings, fit, polled_at) is not None and fresh_price_value(self.settings, general, polled_at) is not None:
                        self.last_amber_poll_success_at = polled_at
                    if fit and fit.start == boundary:
                        await self.replan("amber_confirmed")
                        break
                except Exception as exc:
                    LOG.warning("Amber poll at +%.1fs failed: %s", offset, exc)

    async def _promote_cached_amber(self, boundary: datetime) -> None:
        assert self.amber
        for channel, intervals in self.amber.forecast.items():
            match = next((item for item in intervals if item.start <= boundary < item.end), None)
            if match:
                metadata = dict(match.metadata)
                metadata["forecast_received_at"] = match.received_at.isoformat()
                metadata["promoted_at_boundary"] = True
                metadata["promoted_at"] = boundary.isoformat()
                # Promotion selects a cached interval; it must never forge a
                # fresh receipt time or stale forecasts could dispatch through
                # an Amber outage.
                self.amber.current[channel] = replace(match, metadata=metadata)

    async def _aemo_loop(self) -> None:
        assert self.aemo
        while True:
            now = datetime.now(UTC)
            boundary = next_boundary(now)
            await asyncio.sleep(max(0, (boundary - now).total_seconds() + 20))
            for index in range(8):
                try:
                    prior = self.aemo.current.end if self.aemo.current else None
                    intervals = await self.aemo.poll()
                    await self._record_prices(intervals)
                    if self.aemo.current and self.aemo.current.end != prior:
                        break
                except Exception as exc:
                    self.aemo.last_error = str(exc)
                    LOG.warning("AEMO poll failed: %s", exc)
                await asyncio.sleep(15)
            try:
                self.aemo_summary = await self.aemo.summary()
            except Exception as exc:
                LOG.debug("AEMO summary unavailable: %s", exc)

    async def _forecast_loop(self) -> None:
        assert self.solar
        last_solcast_date_hour: tuple[str, int] | None = None
        last_forecast_solar_at: datetime | None = None
        while True:
            local = datetime.now(ZoneInfo(self.settings.timezone))
            now = datetime.now(UTC)
            failed = False
            if last_forecast_solar_at is None or (now - last_forecast_solar_at).total_seconds() >= 3600:
                try:
                    await self.solar.forecast_solar()
                    last_forecast_solar_at = now
                except Exception as exc:
                    failed = True
                    LOG.warning(
                        "Forecast.Solar unavailable: %s status=%s",
                        type(exc).__name__,
                        getattr(exc, "status", "unknown"),
                    )
            solcast_due = (
                "solcast" not in self.solar.providers
                or (local.hour in {5, 9, 13, 17} and local.minute < 10 and last_solcast_date_hour != (local.date().isoformat(), local.hour))
            )
            if solcast_due:
                try:
                    await self.solar.solcast()
                    last_solcast_date_hour = (local.date().isoformat(), local.hour)
                except Exception as exc:
                    failed = True
                    # aiohttp exception strings include the full URL. Solcast
                    # authenticates in the query string, so never log it.
                    LOG.warning(
                        "Solcast unavailable: %s status=%s",
                        type(exc).__name__,
                        getattr(exc, "status", "unknown"),
                    )
            if self.solar.providers:
                digest = forecast_semantic_digest(self.solar.providers)
                if digest != self.last_forecast_plan_digest:
                    await self.storage.set_setting("solar_forecasts", self.solar.providers)
                    self.last_forecast_plan_digest = digest
                    # A provider refresh changes the rolling schedule exactly
                    # once. Device polling no longer acts as an accidental
                    # forecast-refresh trigger.
                    await self.replan("forecast_change")
            irradiance_fresh = bool(
                self.expected_pv_measured_at
                and (datetime.now(UTC) - self.expected_pv_measured_at).total_seconds() <= self.settings.irradiance_max_age_seconds
            )
            if not irradiance_fresh:
                self.expected_pv_kw = self._forecast_power_now()
                self.expected_pv_measured_at = None
                self.expected_pv_source = "provider_forecast"
            await self.mqtt.publish("forecast/combined", {"expected_pv_kw": self.expected_pv_kw, "providers": list(self.solar.providers), "at": datetime.now(UTC).isoformat()})
            await asyncio.sleep(300 if failed else 60)

    async def _irradiance_loop(self) -> None:
        assert self.irradiance
        while True:
            try:
                values = await self.irradiance.poll()
                # Live POA corrects the immediate dispatch input. At night it
                # must not erase the provider forecast used by future planning.
                self.expected_pv_kw = max(0.0, values["expected_uncurtailed_kw"])
                self.expected_pv_measured_at = self.irradiance.measured_at
                self.expected_pv_source = "ecowitt_irradiance"
                await self.mqtt.publish("forecast/irradiance", {**values, "measured_at": self.irradiance.measured_at.isoformat()})
            except Exception as exc:
                self.irradiance.last_error = str(exc)
                LOG.warning("Ecowitt irradiance unavailable: %s", exc)
            await asyncio.sleep(10)

    def _forecast_power_now(self) -> float:
        if not self.solar:
            return float(self.telemetry.pv_kw or 0) if self.telemetry else 0.0
        now = datetime.now(UTC)
        solcast_total = 0.0
        solcast = self.solar.providers.get("solcast", {}).get("roofs", {})
        for intervals in solcast.values():
            for item in intervals:
                end = parse_forecast_time(item.get("period_end"))
                if end and end - timedelta(minutes=30) <= now < end:
                    solcast_total += float(item.get("pv_estimate", 0))
                    break
        fs_total = 0.0
        fs = self.solar.providers.get("forecast-solar", {}).get("roofs", {})
        for result in fs.values():
            watts = result.get("watts", {}) if isinstance(result, dict) else {}
            candidates = [(parse_forecast_time(key), value) for key, value in watts.items()]
            valid = [(at, value) for at, value in candidates if at and at <= now]
            if valid:
                fs_total += float(max(valid, key=lambda pair: pair[0])[1]) / 1000
        if solcast_total and fs_total:
            return 0.75 * solcast_total + 0.25 * fs_total
        return max(solcast_total, fs_total, float(self.telemetry.pv_kw or 0) if self.telemetry else 0.0)

    def _device_plan_signature(self) -> tuple[Any, ...]:
        """Only planner-relevant device changes should rebuild a 36h plan."""

        soc = round(float(self.devices.ev_soc_pct), 1) if self.devices.ev_soc_pct is not None else None
        runtime_block = math.floor(max(0.0, self.devices.hot_water_runtime_hours) * 12 + 1e-6)
        return (
            self.devices.ev_home,
            self.devices.ev_plugged,
            self.devices.ev_ble_available,
            soc,
            int(self.devices.ev_limit_pct),
            self.devices.hot_water_available,
            self.devices.hot_water_on,
            self.devices.hot_water_confirmed,
            runtime_block,
        )

    def _fixed_hot_water_timer_active(self, now: datetime | None = None) -> bool:
        local = (now or datetime.now(UTC)).astimezone(ZoneInfo(self.settings.timezone))
        return (
            self.settings.hot_water_enabled
            and (self.settings.hot_water_fixed_timer or not self.settings.control_enabled)
            and self.settings.hot_water_timer_start_hour <= local.hour < self.settings.hot_water_timer_end_hour
        )

    async def _govern_fixed_hot_water_timer(self) -> None:
        """Apply the clock-only fallback without depending on SAJ dispatch."""
        if self.settings.hot_water_enabled and self.settings.control_enabled and not self.settings.hot_water_fixed_timer:
            return
        desired = self._fixed_hot_water_timer_active()
        if self.devices.hot_water_on == desired:
            return
        result = await self.loads.set_hot_water(desired)
        await self.storage.event("hot_water_fixed_timer_transition", {
            "relay_on": desired,
            "result": result,
            "window": "11:00-14:00",
            "saj_telemetry_healthy": bool(self.telemetry and self.telemetry.healthy),
            "source_control": "available" if self.telemetry and self.telemetry.healthy else "unavailable",
            "away_mode": not self.settings.hot_water_enabled,
            "energy_automation_enabled": self.settings.control_enabled,
        })

    async def _device_loop(self) -> None:
        while True:
            try:
                await self.loads.refresh()
                await self._govern_fixed_hot_water_timer()
                await self.loads.expire_ev_lease()
                signature = self._device_plan_signature()
                if signature != self.last_device_plan_signature:
                    self.last_device_plan_signature = signature
                    await self.replan("device_change")
            except Exception as exc:
                LOG.warning("Device refresh failed: %s", exc)
            await asyncio.sleep(10)

    async def _nut_loop(self) -> None:
        while True:
            cycle_started = asyncio.get_running_loop().time()
            state = await self.nut.poll()
            self.ups_allocation = allocate_ups_power(state)
            if state.available and state.measured_at is not None:
                local_date = state.measured_at.astimezone(ZoneInfo(self.settings.timezone)).date()
                if self.ups_daily.get("local_date") != local_date.isoformat():
                    self.ups_daily = await self.storage.ups_daily(local_date)
                    self.last_ups_energy_at = None
                if self.ups_daily.get("updated_at") is None and float((self.current_daily or {}).get("server_rack_kwh", 0.0)) > 0:
                    # Seed a newly introduced per-outlet journal from the
                    # existing conserved total, using the first live outlet
                    # proportions. Future seconds are then integrated exactly.
                    wall_kwh = float(self.current_daily["server_rack_kwh"])
                    wall_w = max(1.0, float(self.ups_allocation.get("wall_input_w") or 0.0))
                    self.ups_daily["rack_output_kwh"] = wall_kwh * float(self.ups_allocation.get("rack_output_w") or 0.0) / wall_w
                    self.ups_daily["office_output_kwh"] = wall_kwh * float(self.ups_allocation.get("office_output_w") or 0.0) / wall_w
                    self.ups_daily["conversion_loss_kwh"] = wall_kwh * float(self.ups_allocation.get("conversion_loss_w") or 0.0) / wall_w
                    self.ups_daily["wall_input_kwh"] = wall_kwh
                if self.last_ups_energy_at is not None:
                    hours = max(0.0, min(5.0, (state.measured_at - self.last_ups_energy_at).total_seconds())) / 3600
                    for target, source in (
                        ("rack_output_kwh", "rack_output_w"),
                        ("office_output_kwh", "office_output_w"),
                        ("conversion_loss_kwh", "conversion_loss_w"),
                        ("wall_input_kwh", "wall_input_w"),
                    ):
                        self.ups_daily[target] = float(self.ups_daily.get(target, 0.0)) + float(self.ups_allocation.get(source) or 0.0) * hours / 1000
                self.last_ups_energy_at = state.measured_at
                if self.last_ups_persist_at is None or (state.measured_at - self.last_ups_persist_at).total_seconds() >= 10:
                    self.ups_daily["updated_at"] = state.measured_at.isoformat()
                    await self.storage.set_ups_daily(self.ups_daily)
                    self.last_ups_persist_at = state.measured_at
            await self._update_resilience()
            if state.available and state.measured_at is not None:
                def variable_number(name: str) -> float | None:
                    try:
                        return float(state.variables[name])
                    except (KeyError, TypeError, ValueError):
                        return None

                self.nut_history.append({
                    "measured_at": state.measured_at.isoformat(),
                    "sample_sequence": state.sample_sequence,
                    "input_power_w": state.server_rack_power_w,
                    "output_real_power_w": state.raw_real_power_w,
                    "output_apparent_power_va": variable_number("ups.power"),
                    "load_pct": state.load_pct,
                    "efficiency_pct": state.efficiency_pct,
                    "battery_charge_pct": state.battery_charge_pct,
                    "battery_runtime_seconds": state.battery_runtime_seconds,
                    "input_voltage_v": state.input_voltage_v,
                    "input_frequency_hz": variable_number("input.frequency"),
                    "output_voltage_v": state.output_voltage_v,
                    "output_frequency_hz": variable_number("output.frequency"),
                    "output_current_a": variable_number("output.current"),
                    "output_powerfactor": variable_number("output.powerfactor"),
                    "temperature_c": variable_number("ups.temperature"),
                    "status": state.status,
                    "poll_duration_ms": state.poll_duration_ms,
                    "rack_output_w": self.ups_allocation["rack_output_w"],
                    "office_output_w": self.ups_allocation["office_output_w"],
                    "conversion_loss_w": self.ups_allocation["conversion_loss_w"],
                    "grid_state": self.grid_health.state,
                })
            await self.mqtt.publish("server-rack", {**state.as_dict(), **self.ups_allocation})
            await self.mqtt.publish("grid-health", self.grid_health.as_dict())
            await self.mqtt.publish("protected-supply", self.protected_supply.as_dict())
            await self.mqtt.publish("outage", self._outage_snapshot())
            for object_id, value in {
                "server_rack_power": state.server_rack_power_w if state.available else "unavailable",
                "server_rack_confidence": state.confidence if state.available else "unavailable",
            }.items():
                available = value != "unavailable"
                await self.mqtt.publish_absolute(
                    f"{self.settings.mqtt_prefix}/ha/{object_id}/availability",
                    "available" if available else "unavailable",
                )
                if available:
                    await self.mqtt.publish_absolute(
                        f"{self.settings.mqtt_prefix}/ha/{object_id}/state", value
                    )
            variable_names = frozenset(state.variables)
            if state.available and variable_names and variable_names != self.nut_discovery_variables:
                await publish_nut_discovery(self.mqtt, state.variables)
                self.nut_discovery_variables = variable_names
            if self.influx and state.available and state.server_rack_power_w is not None:
                try:
                    fields: dict[str, Any] = {
                        "raw_real_power_w": state.raw_real_power_w,
                        "server_rack_power_w": state.server_rack_power_w,
                        "efficiency_pct": state.efficiency_pct,
                        "legacy_80_power_w": state.legacy_80_power_w,
                        "confidence": state.confidence,
                        "load_pct": state.load_pct,
                        "battery_charge_pct": state.battery_charge_pct,
                        "battery_runtime_seconds": state.battery_runtime_seconds,
                        "input_voltage_v": state.input_voltage_v,
                        "output_voltage_v": state.output_voltage_v,
                        "status": state.status,
                        "sample_sequence": state.sample_sequence,
                        "poll_duration_ms": state.poll_duration_ms,
                        **{key: value for key, value in self.ups_allocation.items() if isinstance(value, (int, float))},
                    }
                    for key, raw in state.variables.items():
                        if not key.startswith(("battery.", "input.", "output.", "outlet.", "ups.")):
                            continue
                        try:
                            fields["nut_" + key.replace(".", "_")] = float(raw)
                        except (TypeError, ValueError):
                            continue
                    await self.influx.write(
                        "energy_nut",
                        fields,
                        tags={"ups": state.ups_name or "unknown"},
                        at=state.measured_at,
                    )
                except Exception as exc:
                    LOG.debug("NUT Influx write deferred: %s", exc)
            elapsed = asyncio.get_running_loop().time() - cycle_started
            await asyncio.sleep(max(0.05, self.settings.nut_poll_seconds - elapsed))

    def _outage_snapshot(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "active": self.outage_epoch is not None,
            "epoch": self.outage_epoch,
            "lost_at": self.outage_lost_at,
            "duration_seconds": (now - self.outage_lost_at).total_seconds() if self.outage_lost_at else 0.0,
            "stage": self.resilience_stage,
            "control_inhibit": self.grid_control_inhibit,
            "shutdown_enabled": self.settings.resilience_shutdown_enabled,
            "shutdown_signals": {},
            "recovery": "monitoring" if self.outage_epoch else "idle",
        }

    async def _emit_resilience_event(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"at": datetime.now(UTC).isoformat(), "kind": kind, "payload": payload}
        await self.storage.event(kind, payload)
        await self.mqtt.publish("events", event, retain=False, qos=1)
        if self.influx:
            await self.influx.write("energy_resilience_event", {"kind": kind, "payload": json.dumps(payload, separators=(",", ":"), default=str)})

    async def _update_resilience(self) -> None:
        """Fuse grid evidence and persist outage transitions.

        This rollout records shutdown stages but cannot signal a node: the
        maintenance-window gate remains off in configuration.
        """
        if self.resilience_lock.locked():
            return
        async with self.resilience_lock:
            now = datetime.now(UTC)
            previous = self.grid_health.state
            self.grid_health, self.protected_supply = fuse_grid_health(self.telemetry, self.nut.state, now)
            requested_stage = resilience_stage(
                self.grid_health.state,
                self.nut.state.battery_runtime_seconds,
                self.nut.state.battery_charge_pct,
                self.telemetry.soc_pct if self.telemetry else None,
            )
            if self.grid_health.state == "lost":
                self.grid_restored_candidate_at = None
                self.grid_control_inhibit = True
                if self.outage_epoch is None:
                    self.outage_lost_at = now
                    self.outage_epoch = now.strftime("%Y%m%dT%H%M%S.%fZ")
                    await self.storage.start_outage(self.outage_epoch, now, {
                        "grid_health": self.grid_health.as_dict(),
                        "protected_supply": self.protected_supply.as_dict(),
                    })
                    await self._emit_resilience_event("grid_lost", self._outage_snapshot())
                # Warning/arm needs 30 seconds of continuous threshold evidence;
                # more urgent stages are immediate but remain simulation-only.
                if requested_stage != self.resilience_stage_candidate:
                    self.resilience_stage_candidate = requested_stage
                    self.resilience_stage_candidate_at = now
                urgent = requested_stage in {"orderly_shutdown", "urgent_graceful_shutdown"}
                held = bool(self.resilience_stage_candidate_at and (now - self.resilience_stage_candidate_at).total_seconds() >= self.settings.resilience_warning_seconds)
                if urgent or held or requested_stage == "grid_outage_monitoring":
                    if requested_stage != self.resilience_stage:
                        self.resilience_stage = requested_stage
                        await self._emit_resilience_event("resilience_stage_changed", self._outage_snapshot())
                        if (
                            self.settings.resilience_shutdown_enabled
                            and requested_stage in {"orderly_shutdown", "urgent_graceful_shutdown"}
                            and self.shutdown is not None
                            and self.outage_epoch is not None
                        ):
                            try:
                                await self.shutdown.arm_recovery(self.outage_epoch)
                                signals = await self.shutdown.signal_nodes(self.outage_epoch)
                                await self._emit_resilience_event("node_shutdown_signals", {"epoch": self.outage_epoch, "signals": signals})
                            except Exception as exc:
                                await self._emit_resilience_event("node_shutdown_signal_failed", {"epoch": self.outage_epoch, "error": str(exc)})
                if self.outage_epoch:
                    await self.storage.update_outage(
                        self.outage_epoch,
                        stage=self.resilience_stage,
                        charge_pct=self.nut.state.battery_charge_pct,
                        runtime_seconds=self.nut.state.battery_runtime_seconds,
                        payload={"grid_health": self.grid_health.as_dict(), "protected_supply": self.protected_supply.as_dict(), **self._outage_snapshot()},
                    )
            elif self.outage_epoch is not None and self.grid_health.state == "healthy":
                if self.grid_restored_candidate_at is None:
                    self.grid_restored_candidate_at = now
                    self.resilience_stage = "restoration_stabilising"
                    await self._emit_resilience_event("grid_restoration_detected", self._outage_snapshot())
                elif (now - self.grid_restored_candidate_at).total_seconds() >= self.settings.resilience_restore_stable_seconds:
                    epoch = self.outage_epoch
                    await self.storage.finish_outage(epoch, now, "grid_stable_manager_reconciled", self._outage_snapshot())
                    await self._emit_resilience_event("grid_recovery_complete", self._outage_snapshot())
                    self.outage_epoch = None
                    self.outage_lost_at = None
                    self.grid_control_inhibit = False
                    self.resilience_stage = "normal"
                    self.resilience_stage_candidate = None
                    self.resilience_stage_candidate_at = None
            elif self.grid_health.state != "healthy" and self.outage_epoch is not None:
                # Unknown/degraded evidence cannot release the outage safety gate.
                self.grid_restored_candidate_at = None
                self.resilience_stage = "source_disagreement" if self.grid_health.disagreement else "restoration_unconfirmed"
            if self.grid_health.disagreement and previous != "degraded":
                await self._emit_resilience_event("grid_source_disagreement", self.grid_health.as_dict())

    def ups_series(self, minutes: int = 60, limit: int = 720) -> list[dict[str, Any]]:
        """Return a bounded, evenly sampled slice of recent UPS telemetry."""

        cutoff = datetime.now(UTC) - timedelta(minutes=max(1, min(minutes, 360)))
        selected = [
            sample for sample in self.nut_history
            if datetime.fromisoformat(sample["measured_at"]) >= cutoff
        ]
        if len(selected) <= limit:
            return selected
        # Preserve both endpoints and choose evenly spaced samples.  This is
        # deterministic, cheap and avoids sending thousands of SVG points.
        last = len(selected) - 1
        indexes = sorted({round(index * last / (limit - 1)) for index in range(limit)})
        return [selected[index] for index in indexes]

    async def _heartbeat_loop(self) -> None:
        while True:
            await self.mqtt.publish("status", self.snapshot())
            await self.mqtt.publish("tesla-ble", {
                **self.vehicle_snapshot(),
                "published_at": datetime.now(UTC).isoformat(),
            })
            await self.mqtt.publish(
                "tesla-ble/james-car-home",
                (
                    "ON" if self.devices.ev_ble_home else "OFF"
                    if self.devices.ev_ble_home is not None else "unavailable"
                ),
            )
            await self.mqtt.publish(
                "tesla-ble/garage-preset",
                (
                    str(int(round(self.devices.ev_garage_preset)))
                    if self.devices.ev_garage_preset is not None else "unavailable"
                ),
            )
            await self._publish_ha_scalars()
            await asyncio.sleep(10)

    def vehicle_snapshot(self) -> dict[str, Any]:
        available = bool(self.devices.ev_ble_available and self.devices.ev_ble_home)
        return {
            "available": available,
            "source": "tesla_esphome_ble",
            "home": self.devices.ev_ble_home,
            "garage_preset": self.devices.ev_garage_preset,
            "locked": self.devices.ev_car_locked,
            "charge_port_open": self.devices.ev_charge_port_open,
            "charge_port_latch": self.devices.ev_charge_port_latch,
            "climate_on": self.devices.ev_climate_on,
            "climate_target_c": self.devices.ev_climate_target_c,
            "interior_temperature_c": self.devices.ev_interior_temp_c,
            "exterior_temperature_c": self.devices.ev_exterior_temp_c,
            "asleep": self.devices.ev_asleep,
            "windows_open": self.devices.ev_windows_open,
            "steering_heat_on": self.devices.ev_steering_heat_on,
            "defrost_on": self.devices.ev_defrost_on,
            "range_km": self.devices.ev_range_km,
            "minutes_to_limit": self.devices.ev_minutes_to_limit,
            "charging_state": self.devices.ev_charging_state,
            "soc_pct": self.devices.ev_soc_pct,
            "plugged": self.devices.ev_plugged,
            "charging": self.devices.ev_charging,
            "charging_amps": self.devices.ev_amps,
            "charge_limit_pct": self.devices.ev_limit_pct,
        }

    def _fresh_negative_fit(self, now: datetime) -> bool:
        fit, _ = amber_channels(self.amber) if self.amber else (None, None)
        return bool(
            fit
            and fit.start <= now < fit.end
            and 0 <= (now - fit.received_at).total_seconds() <= 330
            and fit.price_per_kwh < 0
        )

    async def _restore_startup_safe_state(self) -> None:
        """Clear persistent force/PV-charge registers after every process start."""

        if not self.startup_safe_state_pending:
            return
        if not self.settings.control_enabled:
            self.startup_safe_state_pending = False
            await self.storage.event("startup_saj_write_skipped_control_disabled", {})
            return
        now = datetime.now(UTC)
        await self.saj.safe_state(self._fresh_negative_fit(now), emergency=True)
        self.disabled_safe_negative_fit = self._fresh_negative_fit(now)
        self.startup_safe_state_pending = False
        await self.storage.event(
            "startup_saj_safe_state_restored",
            {"pv_charge_limit_raw": 1100, "negative_fit": self._fresh_negative_fit(now)},
        )

    async def _force_safe_stop(self, reason: str) -> Command:
        now = datetime.now(UTC)
        negative_fit = False if reason == "control_disabled_safe_state" else self._fresh_negative_fit(now)
        failures: list[str] = []
        try:
            await self.saj.safe_state(negative_fit, emergency=True)
            self.disabled_safe_negative_fit = negative_fit
        except Exception as exc:
            failures.append(f"saj: {exc}")
        try:
            await self.loads.set_ev(False, 0, self.settings.ev_charge_limit_pct, safety_reduction=True)
        except Exception as exc:
            failures.append(f"ev: {exc}")
        hot_water_was_on = self.devices.hot_water_on
        try:
            await self.loads.set_hot_water(False)
        except Exception as exc:
            failures.append(f"hot_water: {exc}")
        if hot_water_was_on:
            await self._sync_hot_water_runtime(now, force=True)
        self.hw_confirmation_hold_until = None
        self.hw_confirmation_command = None
        try:
            await self.storage.clear_leases("ev", "hot_water")
        except Exception as exc:
            failures.append(f"leases: {exc}")
        if failures:
            await self.storage.event(
                "safe_state_partial_failure",
                {"reason": reason, "failures": failures},
            )
            raise RuntimeError("; ".join(failures))
        safe = Command(
            mode="self_consume",
            protected_soc_pct=max(self.settings.battery_floor_pct, self.saj.last_protected_reserve_pct),
            zero_export=negative_fit,
            pv_charge_limit_raw=1100,
            ev_target_soc_pct=self.settings.ev_charge_limit_pct,
            reason=reason,
            generated_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        safe.semantic_hash = command_semantic_hash(safe)
        self.command = safe
        self.command_phase = "safe_state"
        self.command_error = None
        await self.storage.command(safe.semantic_hash, "safe_state", safe.as_dict())
        await self.storage.event(reason, safe.as_dict())
        return safe

    async def force_safe_stop(self, reason: str = "manual_safe_state") -> Command:
        return await self._force_safe_stop(reason)

    async def _maintain_disabled_saj_safe_state(self, now: datetime) -> bool:
        """Disabled means no SAJ writes after the transition to self-consumption."""
        self.command_phase = "disabled_no_inverter_writes"
        self.command_error = None
        return False

    async def _command_watchdog_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            command = self.command
            now = datetime.now(UTC)
            if not self.settings.control_enabled:
                await self._maintain_disabled_saj_safe_state(now)
                continue
            requires_containment = bool(
                command
                and (
                    command.mode in {"export", "grid_charge"}
                    or command.ev_on
                    or command.hot_water_on
                    or command.zero_export
                    or command.pv_charge_limit_raw != 1100
                )
            )
            if (
                command is None
                or not requires_containment
                or command.expires_at is None
                or now < command.expires_at + timedelta(seconds=self.settings.command_watchdog_grace_seconds)
                or self.last_watchdog_expiry == command.expires_at
                or self.replan_lock.locked()
            ):
                continue
            try:
                expired_at = command.expires_at
                await self._force_safe_stop("command_expired_watchdog_safe_state")
                self.last_watchdog_expiry = expired_at
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.command_phase = "watchdog_retrying"
                self.command_error = f"command expiry safe-state failed: {exc}"
                LOG.error("Command-expiry watchdog safe-state failed; retrying: %s", exc)

    async def replan(self, trigger: str) -> None:
        await self._complete_expired_ev_trip(datetime.now(UTC))
        if self.telemetry is None or self.amber is None:
            return
        if self.replan_lock.locked() and trigger == "telemetry":
            return
        async with self.replan_lock:
            fit, general = amber_channels(self.amber)
            live_fit_value = fresh_price_value(self.settings, fit, plan_now := datetime.now(UTC))
            live_import_value = fresh_price_value(self.settings, general, plan_now)
            self.amber_price_ready = live_fit_value is not None and live_import_value is not None
            future_fit = self.amber.forecast.get("feedIn", [])
            hot_water = await self.storage.hot_water_today(datetime.now(ZoneInfo(self.settings.timezone)).date())
            self.devices.hot_water_runtime_hours = float(hot_water["confirmed_seconds"]) / 3600
            fresh_activation = bool(self.last_amber_poll_success_at and not self.plan_dispatch_ready)
            if trigger != "telemetry" or self.rolling_plan is None or fresh_activation:
                candidate_plan = self.planner.build(
                    plan_now, self.telemetry, self.devices, self.amber, self.solar,
                    self.devices.hot_water_runtime_hours, self._server_rack_kw()
                )
                plan_id = plan_semantic_id(candidate_plan)
                candidate_plan["plan_id"] = plan_id
                if fresh_activation or self.rolling_plan is None or self.rolling_plan.get("plan_id") != plan_id:
                    self.rolling_plan = candidate_plan
                    await self.storage.plan(
                        plan_id,
                        self.rolling_plan["generated_at"],
                        self.rolling_plan["horizon_end"],
                        self.rolling_plan,
                    )
                if self.last_amber_poll_success_at:
                    self.plan_dispatch_ready = True
            if not self.plan_dispatch_ready:
                self.command_phase = "waiting_for_fresh_amber_plan"
                return
            current_point = next((
                point for point in (self.rolling_plan or {}).get("points", [])
                if datetime.fromisoformat(point["start"]) <= plan_now < datetime.fromisoformat(point["end"])
            ), None)
            reserve_override = float(current_point["protected_soc_pct"]) if current_point and current_point.get("protected_soc_pct") is not None else None
            export_reserve_override = float(current_point["export_protected_soc_pct"]) if current_point and current_point.get("export_protected_soc_pct") is not None else None
            command = self.policy.command(
                self.telemetry,
                self.devices,
                fit,
                general,
                self.expected_pv_kw,
                float(hot_water["confirmed_seconds"]) / 3600,
                future_fit,
                protected_reserve_override_pct=reserve_override,
                expected_pv_measured_at=self.expected_pv_measured_at,
                hot_water_scheduled=bool(current_point.get("hot_water")) if current_point else None,
                ev_scheduled_kw=float(current_point.get("ev_kw", 0.0)) if current_point else None,
                export_reserve_override_pct=export_reserve_override,
            )
            command = self._stabilize_export(command, fit)
            if self.grid_control_inhibit:
                command.mode = "self_consume"
                command.battery_target_kw = 0.0
                command.site_export_target_kw = 0.0
                command.zero_export = False
                command.pv_charge_limit_raw = 1100
                command.ev_on = False
                command.ev_amps = 0
                command.hot_water_on = False
                command.hot_water_source = "off"
                command.reason = "grid_resilience_safety_override"
            if self.hw_blocked_until and datetime.now(UTC) < self.hw_blocked_until:
                command.hot_water_on = False
                command.hot_water_source = "off"
                command.reason += "_hot_water_safety_cooldown"
            command.semantic_hash = command_semantic_hash(command)
            if current_point and current_point.get("protected_soc_pct") is not None:
                command.protected_soc_pct = max(
                    self.settings.battery_floor_pct,
                    command.protected_soc_pct,
                    float(current_point["protected_soc_pct"]),
                )
                if command.mode == "export" and float(self.telemetry.soc_pct or 0) <= command.protected_soc_pct + 0.5:
                    command.mode = "self_consume"
                    command.battery_target_kw = 0.0
                    command.site_export_target_kw = 0.0
                    command.reason = "forecast_overnight_reserve_protected"
            if (
                current_point
                and current_point.get("battery_charge_deferred")
                and live_fit_value is not None
                and live_fit_value > 0
                and not command.zero_export
                and command.mode == "self_consume"
            ):
                command.pv_charge_limit_raw = 0
                command.reason = "morning_fit_defer_pv_charge_later_solar_secure"
            else:
                command.pv_charge_limit_raw = 1100
            command = self._isolate_hot_water_confirmation(command, plan_now)
            command.semantic_hash = command_semantic_hash(command)
            prior_hw = self.devices.hot_water_on
            try:
                prior_command_hash = self.command.semantic_hash if self.command else None
                phase = await self.saj.apply(command)
                if phase == "applied" and command.mode == "export":
                    self.last_export_change_at = datetime.now(UTC)
                if command.semantic_hash != self.last_recorded_command_hash or phase != self.last_recorded_command_phase:
                    await self.storage.command(command.semantic_hash, phase, command.as_dict())
                    if self.influx:
                        await self.influx.write(
                            "energy_command",
                            {
                                "battery_target_kw": command.battery_target_kw,
                                "site_export_target_kw": command.site_export_target_kw,
                                "protected_soc_pct": command.protected_soc_pct,
                                "zero_export": command.zero_export,
                                "pv_charge_limit_raw": command.pv_charge_limit_raw,
                                "ev_amps": command.ev_amps,
                                "ev_target_soc_pct": command.ev_target_soc_pct,
                                "hot_water_on": command.hot_water_on,
                                "semantic_hash": command.semantic_hash,
                                "phase": phase,
                                "reason": command.reason,
                            },
                            at=command.generated_at,
                        )
                    self.last_recorded_command_hash = command.semantic_hash
                    self.last_recorded_command_phase = phase
                self.command_phase = phase
                flexible_errors: list[str] = []
                if self.settings.control_enabled:
                    try:
                        ev_result = await self.loads.set_ev(
                            command.ev_on,
                            command.ev_amps,
                            command.ev_target_soc_pct,
                            safety_reduction=not command.ev_on,
                            ramp_before_stop=not command.ev_on,
                        )
                    except Exception as exc:
                        self.devices.ev_ble_available = False
                        if not self.loads.ev_error:
                            self.loads.ev_error = f"Tesla BLE command failed: {exc}"
                        flexible_errors.append(self.loads.ev_error)
                        LOG.error("EV actuation failed; SAJ remains %s: %s", phase, exc)
                        try:
                            await self.storage.event("ev_actuator_failed", {
                                "error": str(exc),
                                "saj_phase": phase,
                                "command_hash": command.semantic_hash,
                                "requested_on": command.ev_on,
                                "requested_amps": command.ev_amps,
                            })
                        except Exception as event_exc:
                            LOG.warning("Could not record EV actuator failure: %s", event_exc)
                    else:
                        if ev_result in {"applied", "lease_renewed"}:
                            await self.storage.lease(
                                "ev",
                                self.devices.ev_lease_until,
                                {"on": command.ev_on, "amps": command.ev_amps, "target_soc_pct": command.ev_target_soc_pct, "result": ev_result},
                            )
                    if command.hot_water_on and not prior_hw:
                        # SAJ and any available EV control have settled to the
                        # command proven stable on the preceding cycle. Capture
                        # the whole-site baseline immediately before closure.
                        self.hw_start_baseline_kw = self.telemetry.load_kw
                        self.hw_start_baseline_battery_kw = self.telemetry.battery_kw
                        self.hw_start_at = datetime.now(UTC)
                        self.devices.hot_water_confirmed = False
                    try:
                        hot_water_result = await self.loads.set_hot_water(command.hot_water_on)
                    except Exception as exc:
                        self.devices.hot_water_available = False
                        if not self.loads.hot_water_error:
                            self.loads.hot_water_error = f"hot-water command failed: {exc}"
                        flexible_errors.append(self.loads.hot_water_error)
                        LOG.error("Hot-water actuation failed; SAJ remains %s: %s", phase, exc)
                        try:
                            await self.storage.event("hot_water_actuator_failed", {
                                "error": str(exc),
                                "saj_phase": phase,
                                "command_hash": command.semantic_hash,
                                "requested_on": command.hot_water_on,
                            })
                        except Exception as event_exc:
                            LOG.warning("Could not record hot-water actuator failure: %s", event_exc)
                    else:
                        if command.hot_water_on and not prior_hw and hot_water_result in {"applied", "lease_renewed"}:
                            self.hw_confirmation_hold_until = datetime.now(UTC) + timedelta(seconds=45)
                            self.hw_confirmation_command = replace(command)
                        if prior_hw and not command.hot_water_on:
                            await self._sync_hot_water_runtime(force=True)
                            self.hw_confirmation_hold_until = None
                            self.hw_confirmation_command = None
                        if hot_water_result in {"applied", "lease_renewed"}:
                            await self.storage.lease(
                                "hot_water",
                                datetime.now(UTC) + timedelta(seconds=300) if command.hot_water_on else None,
                                {"on": command.hot_water_on, "source": command.hot_water_source, "result": hot_water_result},
                            )
                self.command = command
                self.command_error = "; ".join(flexible_errors) or None
                if trigger != "telemetry" or command.semantic_hash != prior_command_hash:
                    now = datetime.now(UTC)
                    await self.mqtt.publish("plan", {
                        "schema_version": 3,
                        "software_revision": self.settings.software_revision,
                        "configuration_revision": self.settings.configuration_revision(),
                        "source_timestamps": {
                            "saj": self.telemetry.measured_at.isoformat(),
                            "amber_fit": fit.received_at.isoformat() if fit else None,
                            "amber_import": general.received_at.isoformat() if general else None,
                            "irradiance": self.irradiance.measured_at.isoformat() if self.irradiance and self.irradiance.measured_at else None,
                        },
                        "dispatch_timestamps": {
                            "planned_at": command.generated_at.isoformat(),
                            "published_at": now.isoformat(),
                            "expires_at": command.expires_at.isoformat() if command.expires_at else None,
                        },
                        "current": {**command.as_dict(), "trigger": trigger, "phase": phase},
                        "rolling": self.rolling_plan,
                    })
            except Exception as exc:
                self.command_error = str(exc)
                self.command_phase = "failed"
                await self.storage.command(command.semantic_hash, "failed", {**command.as_dict(), "error": str(exc)})
                LOG.error("Plan application failed: %s", exc)

    @staticmethod
    def _confirmation_controls(command: Command) -> tuple[Any, ...]:
        return (
            command.mode,
            round(command.battery_target_kw, 1),
            round(command.site_export_target_kw, 1),
            int(command.protected_soc_pct + 0.999),
            command.zero_export,
            int(command.pv_charge_limit_raw),
            command.ev_on,
            int(command.ev_amps),
            int(command.ev_target_soc_pct),
        )

    def _isolate_hot_water_confirmation(self, command: Command, now: datetime) -> Command:
        """Hold site controls steady around the relay's 3.7 kW step test."""

        prior = self.command
        hold = self.hw_confirmation_command
        if self.devices.hot_water_on and not self.devices.hot_water_confirmed and hold:
            hold_active = bool(self.hw_confirmation_hold_until and now < self.hw_confirmation_hold_until)
            hard_stop = bool(
                not self.telemetry
                or not self.telemetry.healthy
                or (self.hw_blocked_until and now < self.hw_blocked_until)
            )
            if hard_stop:
                command.hot_water_on = False
                command.hot_water_source = "off"
                command.reason += "_hot_water_confirmation_safety_stop"
                return command
            # Normal planner, price, PV and EV changes are not reasons to
            # chatter the relay. Keep the exact pre-start controls steady until
            # the element step is confirmed. The evidence loop owns the 45 s
            # timeout and will stop on a genuine mismatch or battery funding.
            if not hold_active:
                command.reason += "_hot_water_confirmation_evidence_pending"
            for field in (
                "mode", "battery_target_kw", "site_export_target_kw", "protected_soc_pct",
                "zero_export", "pv_charge_limit_raw", "ev_on", "ev_amps", "ev_target_soc_pct",
            ):
                setattr(command, field, getattr(hold, field))
            command.hot_water_on = True
            command.hot_water_source = hold.hot_water_source
            command.reason += "_hot_water_confirmation_controls_held"
            return command

        if command.hot_water_on and not self.devices.hot_water_on:
            # If the Tesla is already physically charging and there is enough
            # proven headroom for the element, freeze the requested current at
            # the BLE-reported value for the confirmation window. Chasing a
            # moving calculated target must not postpone daily hot water.
            positive_fit_headroom_kw = max(0.0, -float(self.telemetry.grid_kw or 0)) if self.telemetry else 0.0
            curtailed_headroom_kw = (
                max(0.0, self.expected_pv_kw - float(self.telemetry.load_kw or 0))
                if self.telemetry and command.zero_export else 0.0
            )
            if (
                self.devices.ev_charging
                and int(self.devices.ev_amps or 0) >= self.settings.ev_min_amps
                and max(positive_fit_headroom_kw, curtailed_headroom_kw) >= self.settings.hot_water_kw + 0.5
            ):
                command.ev_on = True
                command.ev_amps = int(self.devices.ev_amps)
                command.reason += "_ev_current_pinned_for_hot_water_confirmation"
            seconds_remaining = (
                (command.expires_at - now).total_seconds()
                if command.expires_at is not None else 0.0
            )
            ev_state_matches = self.devices.ev_charging == command.ev_on
            if command.ev_on:
                ev_state_matches = ev_state_matches and int(self.devices.ev_amps or 0) == int(command.ev_amps)
            ev_state_age = (
                (now - self.devices.ev_last_command_at).total_seconds()
                if self.devices.ev_last_command_at is not None else float("inf")
            )
            controls_stable = bool(
                prior
                and self._confirmation_controls(prior) == self._confirmation_controls(command)
                and ev_state_matches
                and ev_state_age >= 30
            )
            if not controls_stable or seconds_remaining < 50:
                command.hot_water_on = False
                command.hot_water_source = "off"
                command.reason += "_hot_water_waiting_for_physical_ev_stability_and_45s_confirmation_window"
        return command

    def _stabilize_export(self, command: Command, fit: PriceInterval | None) -> Command:
        if not self.command or command.mode != "export" or self.command.mode != "export":
            self.last_price_interval_start = fit.start if fit else None
            return command
        new_interval = fit is not None and fit.start != self.last_price_interval_start
        if new_interval:
            self.last_price_interval_start = fit.start
            return command
        if self.last_export_change_at and (datetime.now(UTC) - self.last_export_change_at).total_seconds() < 60:
            # Safety reductions are immediate. Increases/ordinary oscillation hold.
            if command.battery_target_kw >= self.command.battery_target_kw:
                command.battery_target_kw = self.command.battery_target_kw
                command.site_export_target_kw = self.command.site_export_target_kw
                command.semantic_hash = self.command.semantic_hash
                command.reason += "_held_60s"
        return command

    def _server_rack_kw(self) -> float:
        state = self.nut.state
        if not state.available or state.server_rack_power_w is None or state.measured_at is None:
            return 0.0
        if (datetime.now(UTC) - state.measured_at).total_seconds() > max(30.0, self.settings.nut_poll_seconds * 3):
            return 0.0
        return max(0.0, state.server_rack_power_w / 1000)

    async def _complete_expired_ev_trip(self, now: datetime) -> None:
        mode = normalize_trip_mode(self.settings.ev_trip_profile)
        deadline = parse_deadline(self.settings.ev_trip_deadline, self.settings)
        if mode is EVTripMode.NO_TRIP or deadline is None or now < deadline:
            return
        requirement = ev_requirement(self.settings, self.devices.ev_soc_pct, now)
        actual_soc = self.devices.ev_soc_pct
        result = {
            "profile": mode.value,
            "requirement": trip_label(mode),
            "deadline": deadline.isoformat(),
            "target_soc_pct": requirement.target_soc_pct,
            "actual_soc_pct": actual_soc,
            "met": actual_soc is not None and actual_soc + 0.05 >= requirement.target_soc_pct,
            "completed_at": now.isoformat(),
        }
        self.last_ev_trip_result = result
        await self.storage.set_setting("last_ev_trip_result", result)
        await self.storage.event("ev_trip_completed", result)
        local_date = deadline.astimezone(ZoneInfo(self.settings.timezone)).date()
        await self.storage.merge_daily_outcome(local_date, {"ev_trip_result": result, "ev_trip_successes": int(result["met"]), "ev_trip_failures": int(not result["met"])})
        await self.mqtt.publish("ev/trip-result", result)
        if self.influx:
            await self.influx.write(
                "energy_ev_trip",
                {
                    "target_soc_pct": requirement.target_soc_pct,
                    "actual_soc_pct": actual_soc,
                    "met": bool(result["met"]),
                },
                tags={"profile": mode.value},
                at=deadline,
            )
        await self.storage.set_settings({
            "ev_trip_profile": EVTripMode.NO_TRIP.value,
            "ev_trip_requirement": trip_label(EVTripMode.NO_TRIP),
            "ev_trip_deadline": "",
        })
        self.settings = replace(
            self.settings,
            ev_trip_profile=EVTripMode.NO_TRIP.value,
            ev_trip_requirement=trip_label(EVTripMode.NO_TRIP),
            ev_trip_deadline="",
        )
        self.policy = Policy(self.settings)
        self.planner = RollingPlanner(self.settings)
        self.saj.settings = self.settings
        self.loads.settings = self.settings

    async def _hot_water_evidence(self, telemetry: Telemetry) -> None:
        now = datetime.now(UTC)
        if self.devices.hot_water_on and not self.devices.hot_water_confirmed and self.hw_start_at and self.hw_start_baseline_kw is not None:
            elapsed = (now - self.hw_start_at).total_seconds()
            step = float(telemetry.load_kw or 0) - self.hw_start_baseline_kw
            if 15 <= elapsed <= 45 and 2.8 <= step <= 4.5:
                battery_to_element_kw, flow = self._battery_to_hot_water_kw(telemetry)
                if battery_to_element_kw > 0.3:
                    await self.storage.event(
                        "hot_water_battery_contribution",
                        {
                            "battery_to_element_kw": battery_to_element_kw,
                            "flow_confidence": flow["confidence"],
                            "meter_balance_error_kw": flow["meter_balance_error_kw"],
                        },
                    )
                    if self.settings.control_enabled:
                        await self.loads.set_hot_water(False)
                    self.hw_blocked_until = now + timedelta(seconds=60)
                    self.hw_confirmation_hold_until = None
                    self.hw_confirmation_command = None
                    return
                self.devices.hot_water_confirmed = True
                self.hw_confirmation_hold_until = None
                self.hw_confirmation_command = None
                self.devices.hot_water_power_kw = self.settings.hot_water_kw
                self.hw_last_count_at = now
                await self.storage.event("hot_water_confirmed", {"step_kw": step})
            elif elapsed > 45:
                self.devices.hot_water_power_kw = 0.0
                await self.storage.event("hot_water_actuator_mismatch", {"step_kw": step})
                if self.settings.control_enabled:
                    await self.loads.set_hot_water(False)
                self.hw_confirmation_hold_until = None
                self.hw_confirmation_command = None
        if self.devices.hot_water_on and self.devices.hot_water_confirmed:
            unexpected_battery_kw, flow = self._battery_to_hot_water_kw(telemetry)
            if unexpected_battery_kw > 0.3:
                self.hw_battery_violation_started = self.hw_battery_violation_started or now
                if (now - self.hw_battery_violation_started).total_seconds() >= 15:
                    await self.storage.event(
                        "hot_water_battery_contribution",
                        {
                            "battery_to_element_kw": unexpected_battery_kw,
                            "flow_confidence": flow["confidence"],
                            "meter_balance_error_kw": flow["meter_balance_error_kw"],
                        },
                    )
                    self.hw_blocked_until = now + timedelta(seconds=60)
                    if self.settings.control_enabled:
                        await self.loads.set_hot_water(False)
                    self.hw_confirmation_hold_until = None
                    self.hw_confirmation_command = None
                    return
            else:
                self.hw_battery_violation_started = None
            if self.hw_last_count_at:
                seconds = min(10.0, max(0.0, (now - self.hw_last_count_at).total_seconds()))
                await self.storage.add_hot_water_seconds(now.astimezone(ZoneInfo(self.settings.timezone)).date(), seconds)
                self.devices.hot_water_runtime_hours += seconds / 3600
                await self._sync_hot_water_runtime(now)
            self.hw_last_count_at = now
            self.devices.hot_water_power_kw = self.settings.hot_water_kw
        elif not self.devices.hot_water_on:
            self.devices.hot_water_confirmed = False
            self.devices.hot_water_power_kw = 0.0
            self.hw_last_count_at = None
            self.hw_battery_violation_started = None
            self.hw_confirmation_hold_until = None
            self.hw_confirmation_command = None

    def _battery_to_hot_water_kw(self, telemetry: Telemetry) -> tuple[float, dict[str, Any]]:
        """Conservatively infer the stationary-battery tranche funding HW."""

        ordinary = max(
            0.0,
            float(telemetry.load_kw or 0)
            - self.settings.hot_water_kw
            - float(self.devices.ev_power_kw or 0),
        )
        flow = conserved_power_flow(
            pv_kw=telemetry.pv_kw,
            battery_kw=telemetry.battery_kw,
            grid_kw=telemetry.grid_kw,
            ordinary_house_kw=ordinary,
            hot_water_kw=self.settings.hot_water_kw,
            ev_kw=self.devices.ev_power_kw,
            server_rack_kw=self._server_rack_kw(),
            at=telemetry.measured_at,
        )
        battery_to_element = sum(
            float(edge.get("kw", 0.0))
            for edge in flow["edges"]
            if edge.get("from") == "battery" and edge.get("to") == "hot_water"
        )
        return battery_to_element, flow

    async def _sync_hot_water_runtime(self, now: datetime | None = None, force: bool = False) -> None:
        """Batch firmware persistence to avoid writing LittleFS every poll."""

        now = now or datetime.now(UTC)
        if (
            not force
            and self.hw_last_firmware_sync_at
            and (now - self.hw_last_firmware_sync_at).total_seconds() < self.settings.hot_water_confirmation_sync_seconds
        ):
            return
        try:
            await self.loads.set_hot_water_confirmed_seconds(round(self.devices.hot_water_runtime_hours * 3600))
            self.hw_last_firmware_sync_at = now
        except Exception as exc:
            LOG.warning("Hot-water firmware confirmation sync failed: %s", exc)

    async def _record_power(self, telemetry: Telemetry) -> None:
        fit, general = amber_channels(self.amber) if self.amber else (None, None)
        server_rack_kw = self._server_rack_kw()
        complete = self.outcomes.add(
            telemetry.measured_at,
            telemetry,
            self.devices,
            fit.price_per_kwh if fit else None,
            general.price_per_kwh if general else None,
            server_rack_kw,
            self.expected_pv_kw,
        )
        if self.influx:
            try:
                power_fields = {
                    "pv_kw": telemetry.pv_kw,
                    "pv1_kw": telemetry.pv1_kw,
                    "pv2_kw": telemetry.pv2_kw,
                    "pv3_kw": telemetry.pv3_kw,
                    "load_kw": telemetry.load_kw,
                    "load_total_kw": telemetry.load_total_kw,
                    "load_backup_kw": telemetry.load_backup_kw,
                    "ordinary_house_kw": max(
                        0.0,
                        float(telemetry.load_kw or 0)
                        - float(self.devices.ev_power_kw or 0)
                        - float(self.devices.hot_water_power_kw or 0),
                    ),
                    "load_balance_error_kw": telemetry.load_balance_error_kw,
                    "grid_kw": telemetry.grid_kw,
                    "flow_grid_kw": telemetry.flow_grid_kw,
                    "grid_l1_kw": telemetry.meter_phase_power_kw[0],
                    "grid_l2_kw": telemetry.meter_phase_power_kw[1],
                    "grid_l3_kw": telemetry.meter_phase_power_kw[2],
                    "grid_l1_v": telemetry.meter_phase_voltage_v[0],
                    "grid_l2_v": telemetry.meter_phase_voltage_v[1],
                    "grid_l3_v": telemetry.meter_phase_voltage_v[2],
                    "grid_l1_hz": telemetry.meter_phase_frequency_hz[0],
                    "grid_l2_hz": telemetry.meter_phase_frequency_hz[1],
                    "grid_l3_hz": telemetry.meter_phase_frequency_hz[2],
                    "battery_kw": telemetry.battery_kw,
                    "inverter_kw": telemetry.inverter_kw,
                    "ev_kw": self.devices.ev_power_kw,
                    "hot_water_kw": self.devices.hot_water_power_kw,
                    "server_rack_kw": server_rack_kw,
                    "sample_skew_ms": telemetry.sample_skew_ms,
                    "cycle_duration_ms": telemetry.cycle_duration_ms,
                    "sample_sequence": telemetry.sample_sequence,
                    "fault_count": telemetry.fault_count,
                }
                await self.influx.write("energy_power", power_fields, at=telemetry.measured_at)
                completed_minute = self.power_minutes.add(telemetry.measured_at, power_fields)
                if completed_minute:
                    minute_start, minute_fields = completed_minute
                    await self.influx.write("energy_power_1m", minute_fields, at=minute_start)
                await self.influx.write(
                    "energy_saj_status",
                    {
                        "grid_online": bool(telemetry.grid_online),
                        "grid_state": telemetry.grid_state,
                        "inverter_status": telemetry.inverter_status,
                        "fault_count": telemetry.fault_count,
                        "fault_severity": telemetry.fault_severity,
                        "read_errors": telemetry.modbus_read_errors,
                        "reconnects": telemetry.modbus_reconnects,
                        "sample_skew_ms": telemetry.sample_skew_ms,
                        "cycle_duration_ms": telemetry.cycle_duration_ms,
                    },
                    at=telemetry.measured_at,
                )
                if self.last_battery_record_at is None or (telemetry.measured_at - self.last_battery_record_at).total_seconds() >= 10:
                    model = telemetry.battery_model(self.settings.battery_capacity_kwh, self.settings.battery_floor_pct, self.settings.battery_discharge_efficiency, self.settings.battery_charge_efficiency)
                    await self.influx.write("energy_battery", {
                        "soc_pct": telemetry.soc_pct,
                        "soh_pct": telemetry.soh_pct,
                        "battery_temperature_c": telemetry.battery_temperature_c,
                        "inverter_temperature_c": telemetry.inverter_temperature_c,
                        "environment_temperature_c": telemetry.environment_temperature_c,
                        "battery_voltage_v": telemetry.battery_voltage_v,
                        "battery_cycle_count": telemetry.battery_cycle_count,
                        **model,
                    }, at=telemetry.measured_at)
                    self.last_battery_record_at = telemetry.measured_at
                if (
                    telemetry.energy_counters
                    and (
                        self.last_saj_energy_record_at is None
                        or (telemetry.measured_at - self.last_saj_energy_record_at).total_seconds() >= 60
                    )
                ):
                    await self.influx.write(
                        "energy_saj_energy",
                        telemetry.energy_counters,
                        at=telemetry.measured_at,
                    )
                    self.last_saj_energy_record_at = telemetry.measured_at
                if self.last_forecast_record_at is None or (telemetry.measured_at - self.last_forecast_record_at).total_seconds() >= 300:
                    await self.influx.write(
                        "energy_forecast",
                        {
                            "expected_pv_kw": self.expected_pv_kw,
                            "measured_pv_kw": telemetry.pv_kw,
                            "pv1_expected_kw": self._array_forecast_now()["pv1_kw"],
                            "pv2_expected_kw": self._array_forecast_now()["pv2_kw"],
                            "pv3_expected_kw": self._array_forecast_now()["pv3_kw"],
                            "pv1_measured_kw": telemetry.pv1_kw,
                            "pv2_measured_kw": telemetry.pv2_kw,
                            "pv3_measured_kw": telemetry.pv3_kw,
                            "irradiance_uncurtailed_kw": self.irradiance.expected_uncurtailed_kw if self.irradiance else None,
                            "ghi_wm2": self.irradiance.ghi_wm2 if self.irradiance else None,
                        },
                        tags={"provider": "ensemble_live"},
                        at=telemetry.measured_at,
                    )
                    self.last_forecast_record_at = telemetry.measured_at
                if complete:
                    await self.influx.write("energy_outcome", {key: value for key, value in complete.items() if key != "interval_start"}, at=datetime.fromisoformat(complete["interval_start"]))
            except Exception as exc:
                LOG.debug("Influx write deferred: %s", exc)
        if complete:
            self.last_outcome = complete
            await self.storage.execute("INSERT OR REPLACE INTO five_minute_outcomes(interval_start,payload) VALUES(?,?)", (complete["interval_start"], json.dumps(complete)))
            interval_at = datetime.fromisoformat(complete["interval_start"])
            local_date = interval_at.astimezone(ZoneInfo(self.settings.timezone)).date()
            daily = await self.storage.add_daily_outcome(local_date, complete)
            self.current_daily = daily
            await self.mqtt.publish("outcome", complete)
            await self.mqtt.publish("daily", daily)
            if self.influx:
                local_midnight = datetime.combine(local_date, datetime.min.time(), tzinfo=ZoneInfo(self.settings.timezone)).astimezone(UTC)
                await self.influx.write("energy_daily", {key: value for key, value in daily.items() if key != "local_date"}, at=local_midnight)

    async def _record_prices(self, intervals: list[PriceInterval]) -> None:
        for item in intervals:
            try:
                inserted = await self.storage.record_price(
                    (item.source, item.channel, item.start.isoformat(), item.end.isoformat(), item.price_per_kwh, item.received_at.isoformat(), item.published_at.isoformat() if item.published_at else None, int(item.estimate), json.dumps(item.metadata, default=str))
                )
                if inserted and self.influx:
                    await self.influx.write("energy_price", {"price_per_kwh": item.price_per_kwh, "estimate": item.estimate, "latency_seconds": max(0.0, (item.received_at - item.start).total_seconds())}, tags={"source": item.source, "channel": item.channel}, at=item.received_at)
            except Exception as exc:
                LOG.debug("Price record failed: %s", exc)

    async def _publish_ha_scalars(self) -> None:
        if not self.telemetry:
            return
        fit, general = amber_channels(self.amber) if self.amber else (None, None)
        model = self.telemetry.battery_model(self.settings.battery_capacity_kwh, self.settings.battery_floor_pct, self.settings.battery_discharge_efficiency, self.settings.battery_charge_efficiency)
        rolling = self.rolling_plan or {}
        summary = rolling.get("summary", {})
        hot_water = rolling.get("hot_water", {})
        ev = rolling.get("ev", {})
        export_windows = rolling.get("export_windows", [])
        next_export = export_windows[0] if export_windows else {}
        command = self.command
        array_forecast = self._array_forecast_now()
        values = {
            "status": self.command_phase,
            "pv_power": self.telemetry.pv_kw,
            "pv1_power": self.telemetry.pv1_kw,
            "pv2_power": self.telemetry.pv2_kw,
            "pv3_power": self.telemetry.pv3_kw,
            "pv1_expected": array_forecast["pv1_kw"],
            "pv2_expected": array_forecast["pv2_kw"],
            "pv3_expected": array_forecast["pv3_kw"],
            "pv1_forecast_error": float(self.telemetry.pv1_kw or 0) - array_forecast["pv1_kw"],
            "pv2_forecast_error": float(self.telemetry.pv2_kw or 0) - array_forecast["pv2_kw"],
            "pv3_forecast_error": float(self.telemetry.pv3_kw or 0) - array_forecast["pv3_kw"],
            "load_power": self.telemetry.load_kw,
            "load_total_power": self.telemetry.load_total_kw if self.telemetry.load_total_kw is not None else "unavailable",
            "load_backup_power": self.telemetry.load_backup_kw if self.telemetry.load_backup_kw is not None else "unavailable",
            "load_source": self.telemetry.load_source,
            "load_balance_error": self.telemetry.load_balance_error_kw if self.telemetry.load_balance_error_kw is not None else "unavailable",
            "server_rack_power": self.nut.state.server_rack_power_w if self.nut.state.available else "unavailable",
            "server_rack_confidence": self.nut.state.confidence if self.nut.state.available else "unavailable",
            "server_rack_energy_today": (self.current_daily or {}).get("server_rack_kwh", "unavailable"),
            "grid_health": self.grid_health.state,
            "protected_supply": self.protected_supply.state,
            "outage_active": "ON" if self.outage_epoch else "OFF",
            "outage_duration": self._outage_snapshot()["duration_seconds"],
            "resilience_stage": self.resilience_stage,
            "rack_power": self.ups_allocation.get("rack_output_w", "unavailable"),
            "office_power": self.ups_allocation.get("office_output_w", "unavailable"),
            "ups_conversion_loss": self.ups_allocation.get("conversion_loss_w", "unavailable"),
            "grid_power": self.telemetry.grid_kw,
            "battery_power": self.telemetry.battery_kw,
            "battery_soc": self.telemetry.soc_pct,
            "battery_soh": self.telemetry.soh_pct,
            "battery_stored": model["gross_stored_kwh"],
            "amber_fit": fit.price_per_kwh if fit else "unavailable",
            "amber_import": general.price_per_kwh if general else "unavailable",
            "aemo_price": self.aemo.current.price_per_kwh if self.aemo and self.aemo.current else "unavailable",
            "hot_water_power": self.devices.hot_water_power_kw * 1000,
            "hot_water_relay": "ON" if self.devices.hot_water_on else "OFF",
            "hot_water_runtime": self.devices.hot_water_runtime_hours,
            "ev_amps": self.devices.ev_amps,
            "ev_soc": self.devices.ev_soc_pct if self.devices.ev_soc_pct is not None else "unavailable",
            "james_car_home": (
                "ON" if self.devices.ev_ble_home else "OFF"
                if self.devices.ev_ble_home is not None else "unavailable"
            ),
            "garage_preset": (
                int(round(self.devices.ev_garage_preset))
                if self.devices.ev_garage_preset is not None else "unavailable"
            ),
            "tesla_climate_on": (
                "ON" if self.devices.ev_climate_on else "OFF"
                if self.devices.ev_climate_on is not None else "unavailable"
            ),
            "tesla_climate_target": self.devices.ev_climate_target_c if self.devices.ev_climate_target_c is not None else "unavailable",
            "tesla_interior_temperature": self.devices.ev_interior_temp_c if self.devices.ev_interior_temp_c is not None else "unavailable",
            "tesla_exterior_temperature": self.devices.ev_exterior_temp_c if self.devices.ev_exterior_temp_c is not None else "unavailable",
            "tesla_lock_state": (
                "locked" if self.devices.ev_car_locked else "unlocked"
                if self.devices.ev_car_locked is not None else "unavailable"
            ),
            "tesla_charge_port_open": (
                "ON" if self.devices.ev_charge_port_open else "OFF"
                if self.devices.ev_charge_port_open is not None else "unavailable"
            ),
            "tesla_charge_port_latch": self.devices.ev_charge_port_latch or "unavailable",
            "tesla_asleep": (
                "ON" if self.devices.ev_asleep else "OFF"
                if self.devices.ev_asleep is not None else "unavailable"
            ),
            "tesla_windows_open": (
                "ON" if self.devices.ev_windows_open else "OFF"
                if self.devices.ev_windows_open is not None else "unavailable"
            ),
            "tesla_steering_heat": (
                "ON" if self.devices.ev_steering_heat_on else "OFF"
                if self.devices.ev_steering_heat_on is not None else "unavailable"
            ),
            "tesla_defrost": (
                "ON" if self.devices.ev_defrost_on else "OFF"
                if self.devices.ev_defrost_on is not None else "unavailable"
            ),
            "tesla_range": self.devices.ev_range_km if self.devices.ev_range_km is not None else "unavailable",
            "tesla_minutes_to_limit": self.devices.ev_minutes_to_limit if self.devices.ev_minutes_to_limit is not None else "unavailable",
            "tesla_charging_state": self.devices.ev_charging_state or "unavailable",
            "ev_trip_profile": self.settings.ev_trip_profile,
            "ev_trip_deadline": self.settings.ev_trip_deadline or "unavailable",
            "ev_opportunistic_fit": self.settings.ev_opportunistic_fit_max_per_kwh,
            "current_action": command.mode if command else "unavailable",
            "current_reason": command.reason if command else "unavailable",
            "protected_reserve": command.protected_soc_pct if command else "unavailable",
            "site_export_target": command.site_export_target_kw if command else "unavailable",
            "battery_target": command.battery_target_kw if command else "unavailable",
            "zero_export": "ON" if command and command.zero_export else "OFF",
            "expected_pv": self.expected_pv_kw,
            "plan_generated": rolling.get("generated_at", "unavailable"),
            "plan_horizon_end": rolling.get("horizon_end", "unavailable"),
            "forecast_coverage_end": rolling.get("forecast_coverage_end", "unavailable"),
            "next_export_start": next_export.get("start", "unavailable"),
            "next_export_end": next_export.get("end", "unavailable"),
            "next_export_price": next_export.get("max_price_per_kwh", "unavailable"),
            "next_export_power": next_export.get("max_power_kw", "unavailable"),
            "export_window_count": len(export_windows),
            "hot_water_plan_start": hot_water.get("planned_start", "unavailable"),
            "hot_water_plan_end": hot_water.get("planned_end", "unavailable"),
            "hot_water_remaining": hot_water.get("remaining_hours", "unavailable"),
            "hot_water_deadline": hot_water.get("deadline", "unavailable"),
            "hot_water_source": command.hot_water_source if command else "unavailable",
            "ev_recommendation": ev.get("recommendation", "unavailable"),
            "ev_target_soc": ev.get("charge_limit_pct", "unavailable"),
            "predicted_soc_min": summary.get("predicted_soc_min_pct", "unavailable"),
            "predicted_soc_end": summary.get("predicted_soc_end_pct", "unavailable"),
            "expected_pv_energy": summary.get("expected_pv_kwh", "unavailable"),
            "expected_house_energy": summary.get("expected_house_load_kwh", "unavailable"),
            "expected_ev_energy": summary.get("expected_ev_input_kwh", "unavailable"),
            "planned_battery_export_energy": summary.get("battery_export_kwh", "unavailable"),
            "planned_battery_export_revenue": summary.get("battery_export_revenue", "unavailable"),
            "planned_battery_export_wear": summary.get("battery_export_wear_cost", "unavailable"),
            "planned_battery_export_net": summary.get("battery_export_net_benefit", "unavailable"),
            "planned_solar_export_revenue": summary.get("solar_export_revenue", "unavailable"),
            "planned_total_export_revenue": summary.get("total_export_revenue", "unavailable"),
            "realised_battery_export_revenue_today": (self.current_daily or {}).get("battery_export_revenue", "unavailable"),
            "realised_solar_export_revenue_today": (self.current_daily or {}).get("solar_export_revenue", "unavailable"),
            "realised_export_revenue_today": (self.current_daily or {}).get("export_revenue", "unavailable"),
            "realised_import_cost_today": (self.current_daily or {}).get("import_cost", "unavailable"),
            "realised_battery_wear_today": (self.current_daily or {}).get("wear_cost", "unavailable"),
            "realised_net_benefit_today": (
                float((self.current_daily or {}).get("export_revenue", 0.0))
                - float((self.current_daily or {}).get("import_cost", 0.0))
                - float((self.current_daily or {}).get("wear_cost", 0.0))
                if self.current_daily else "unavailable"
            ),
            "expected_pv_peak": summary.get("expected_pv_peak_kw", "unavailable"),
            "expected_pv_peak_time": summary.get("expected_pv_peak_at", "unavailable"),
            "influx_backlog": self.influx.backlog if self.influx else "unavailable",
        }
        for key, value in values.items():
            unavailable = value is None or value == "unavailable"
            await self.mqtt.publish(f"ha/{key}/availability", "unavailable" if unavailable else "available")
            if not unavailable:
                await self.mqtt.publish(f"ha/{key}/state", str(value))

    def _array_forecast_now(self) -> dict[str, float]:
        forecast = provider_power(self.solar, datetime.now(UTC), self.settings.timezone) if self.solar else {}
        pv1 = float(forecast.get("pv1_kw", 0.0))
        pv2 = float(forecast.get("pv2_kw", 0.0))
        pv3 = float(forecast.get("pv3_kw", 0.0))
        if (
            self.irradiance
            and self.irradiance.expected_uncurtailed_kw is not None
            and self.irradiance.measured_at is not None
            and (datetime.now(UTC) - self.irradiance.measured_at).total_seconds() <= self.settings.irradiance_max_age_seconds
        ):
            north = 0.84 * self.settings.north_capacity_kwp * float(self.irradiance.poa_north_wm2 or 0) / 1000
            south = 0.84 * self.settings.south_capacity_kwp * float(self.irradiance.poa_south_wm2 or 0) / 1000
            pv1, pv2, pv3 = north, south / 3.0, south * 2.0 / 3.0
        return {"pv1_kw": max(0.0, pv1), "pv2_kw": max(0.0, pv2), "pv3_kw": max(0.0, pv3)}

    async def update_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        updates = dict(updates)
        if "hot_water_fixed_timer" in updates and "hot_water_enabled" not in updates:
            # One-release Home Assistant compatibility: the installed helper's
            # historical entity_id is retained, but it now carries the enabled
            # / Away master state. There is no user-selectable fixed mode.
            updates["hot_water_enabled"] = updates.pop("hot_water_fixed_timer")
        allowed = {
            "min_sell_price_per_kwh", "ev_opportunistic_fit_max_per_kwh", "ev_grid_allowed",
            "ev_charge_limit_pct", "ev_trip_profile", "ev_trip_requirement", "control_enabled",
            "hot_water_fixed_timer", "hot_water_enabled",
        }
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"unsupported settings: {sorted(unknown)}")
        values = self.public_settings()
        values["ev_trip_deadline"] = self.settings.ev_trip_deadline
        if "min_sell_price_per_kwh" in updates:
            value = float(updates["min_sell_price_per_kwh"])
            if not 0 <= value <= 20:
                raise ValueError("min_sell_price_per_kwh must be between 0 and 20 AUD/kWh")
            values["min_sell_price_per_kwh"] = value
        if "ev_opportunistic_fit_max_per_kwh" in updates:
            value = float(updates["ev_opportunistic_fit_max_per_kwh"])
            if not 0 <= value <= 1:
                raise ValueError("ev_opportunistic_fit_max_per_kwh must be between 0 and 1 AUD/kWh")
            values["ev_opportunistic_fit_max_per_kwh"] = value
        if "ev_charge_limit_pct" in updates:
            value = int(updates["ev_charge_limit_pct"])
            if not 50 <= value <= 100:
                raise ValueError("ev_charge_limit_pct must be between 50 and 100")
            values["ev_charge_limit_pct"] = value
        for key in ("ev_grid_allowed", "control_enabled", "hot_water_fixed_timer", "hot_water_enabled"):
            if key in updates:
                if not isinstance(updates[key], bool):
                    raise ValueError(f"{key} must be a boolean")
                values[key] = updates[key]
        if "ev_trip_profile" in updates or "ev_trip_requirement" in updates:
            profile = normalize_trip_mode(updates.get("ev_trip_profile", updates.get("ev_trip_requirement")))
            if "ev_trip_profile" in updates and "ev_trip_requirement" in updates:
                if normalize_trip_mode(updates["ev_trip_requirement"]) is not profile:
                    raise ValueError("ev_trip_profile and ev_trip_requirement conflict")
            values["ev_trip_profile"] = profile.value
            values["ev_trip_requirement"] = trip_label(profile)
            values["ev_trip_deadline"] = (
                next_ev_departure(self.settings, datetime.now(UTC)).isoformat()
                if profile is not EVTripMode.NO_TRIP else ""
            )
        # The retired fixed-mode value remains false internally; only the
        # public compatibility attribute mirrors hot_water_enabled.
        values["hot_water_fixed_timer"] = self.settings.hot_water_fixed_timer
        persisted = {
            key: values[key] for key in (
                "min_sell_price_per_kwh", "ev_opportunistic_fit_max_per_kwh", "ev_grid_allowed",
                "ev_charge_limit_pct", "ev_trip_profile", "ev_trip_requirement", "ev_trip_deadline",
                "control_enabled",
                "hot_water_fixed_timer",
                "hot_water_enabled",
            )
        }
        disabling = self.settings.control_enabled and not bool(persisted["control_enabled"])
        if disabling:
            try:
                await self._force_safe_stop("control_disabled_safe_state")
            except Exception as exc:
                raise ValueError(f"control remains enabled because safe shutdown failed: {exc}") from exc
        await self.storage.set_settings(persisted)
        self.settings = replace(self.settings, **persisted)
        self.policy = Policy(self.settings)
        self.planner = RollingPlanner(self.settings)
        self.saj.settings = self.settings
        self.loads.settings = self.settings
        self.devices.ev_limit_pct = self.settings.ev_charge_limit_pct
        self.control_expected = self.settings.control_enabled
        if disabling or "hot_water_enabled" in updates:
            # Apply the independent timer/away governor immediately.  It must
            # not wait for SAJ telemetry or the next ten-second device poll.
            await self._govern_fixed_hot_water_timer()
        if not disabling:
            await self.replan("settings")
        return self.public_settings()

    def public_settings(self) -> dict[str, Any]:
        return {
            "min_sell_price_per_kwh": self.settings.min_sell_price_per_kwh,
            "ev_opportunistic_fit_max_per_kwh": self.settings.ev_opportunistic_fit_max_per_kwh,
            "ev_grid_allowed": self.settings.ev_grid_allowed,
            "ev_charge_limit_pct": self.settings.ev_charge_limit_pct,
            "ev_trip_profile": normalize_trip_mode(self.settings.ev_trip_profile).value,
            "ev_trip_requirement": trip_label(self.settings.ev_trip_profile),
            "ev_trip_deadline": self.settings.ev_trip_deadline or None,
            "control_enabled": self.settings.control_enabled,
            # Compatibility attribute for the existing HA helper entity_id.
            "hot_water_fixed_timer": self.settings.hot_water_enabled,
            "hot_water_enabled": self.settings.hot_water_enabled,
            "hot_water_mode": (
                "away" if not self.settings.hot_water_enabled
                else "fixed_timer" if self.settings.hot_water_fixed_timer or not self.settings.control_enabled
                else "automatic"
            ),
            "hot_water_timer_window": "11:00-14:00",
        }

    def snapshot(self) -> dict[str, Any]:
        fit, general = amber_channels(self.amber) if self.amber else (None, None)
        model = self.telemetry.battery_model(self.settings.battery_capacity_kwh, self.settings.battery_floor_pct, self.settings.battery_discharge_efficiency, self.settings.battery_charge_efficiency) if self.telemetry else None
        aemo = self.aemo.current if self.aemo else None
        matched_fit = next((item for item in self.amber.forecast.get("feedIn", []) if aemo and item.start == aemo.start and item.end == aemo.end), None) if self.amber else None
        matched_general = next((item for item in self.amber.forecast.get("general", []) if aemo and item.start == aemo.start and item.end == aemo.end), None) if self.amber else None
        receipts = [("amber", item.received_at) for item in (matched_fit, matched_general) if item]
        if aemo and (matched_fit or matched_general):
            receipts.append(("aemo", aemo.received_at))
        first_feed = min(receipts, key=lambda pair: pair[1])[0] if receipts else None
        array_forecast = self._array_forecast_now()
        return _jsonable({
            "service": {
                "started_at": self.started_at,
                "uptime_seconds": (datetime.now(UTC) - self.started_at).total_seconds(),
                "control_enabled": self.settings.control_enabled,
                "mqtt_connected": self.mqtt.connected,
                "influx_backlog": self.influx.backlog if self.influx else None,
                "influx_error": self.influx.last_error if self.influx else None,
                "command_phase": self.command_phase,
                "error": self.command_error,
                "ev_actuator_error": self.loads.ev_error,
                "hot_water_actuator_error": self.loads.hot_water_error,
                "amber_price_ready": self.amber_price_ready,
                "plan_id": self.rolling_plan.get("plan_id") if self.rolling_plan else None,
            },
            "plan_id": self.rolling_plan.get("plan_id") if self.rolling_plan else None,
            "grid_health": self.grid_health.as_dict(),
            "protected_supply": self.protected_supply.as_dict(),
            "outage": self._outage_snapshot(),
            "rack_power": {
                "output_w": self.ups_allocation.get("rack_output_w"),
                "wall_allocated_w": self.ups_allocation.get("rack_wall_allocated_w"),
            },
            "office_power": {
                "output_w": self.ups_allocation.get("office_output_w"),
                "wall_allocated_w": self.ups_allocation.get("office_wall_allocated_w"),
            },
            "daily_energy": {
                "solar_generated_kwh": (self.current_daily or {}).get("pv_kwh"),
                "house_consumed_kwh": (self.current_daily or {}).get("whole_house_load_kwh"),
                "grid_imported_kwh": (self.current_daily or {}).get("import_kwh"),
                "grid_exported_kwh": (self.current_daily or {}).get("export_kwh"),
                "battery_charged_kwh": (self.current_daily or {}).get("battery_charge_kwh"),
                "battery_discharged_kwh": (self.current_daily or {}).get("battery_discharge_kwh"),
                "ev_charged_kwh": (self.current_daily or {}).get("ev_kwh"),
                "hot_water_kwh": (self.current_daily or {}).get("hot_water_kwh"),
                **self.ups_daily,
            },
            "telemetry": self.telemetry,
            "battery": model,
            "devices": self.devices,
            "command": self.command,
            "prices": {
                "amber_fit": fit,
                "amber_import": general,
                "aemo": aemo,
                "comparison": {
                    "first_feed": first_feed,
                    "interval_aligned": bool(aemo and (matched_fit or matched_general)),
                    "comparison_interval_start": aemo.start if aemo and (matched_fit or matched_general) else None,
                    "amber_fit_minus_aemo_per_kwh": matched_fit.price_per_kwh - aemo.price_per_kwh if matched_fit and aemo else None,
                    "amber_import_minus_aemo_per_kwh": matched_general.price_per_kwh - aemo.price_per_kwh if matched_general and aemo else None,
                    "amber_fit_latency_seconds": max(0.0, (fit.received_at - fit.start).total_seconds()) if fit else None,
                    "amber_import_latency_seconds": max(0.0, (general.received_at - general.start).total_seconds()) if general else None,
                    "aemo_latency_seconds": max(0.0, (aemo.received_at - aemo.start).total_seconds()) if aemo else None,
                    "aemo_summary": self.aemo_summary,
                },
            },
            "forecast": {
                "expected_pv_kw": self.expected_pv_kw,
                "expected_pv_source": self.expected_pv_source,
                "expected_pv_measured_at": self.expected_pv_measured_at,
                "expected_pv_age_seconds": max(0.0, (datetime.now(UTC) - self.expected_pv_measured_at).total_seconds()) if self.expected_pv_measured_at else None,
                "expected_pv_fresh": bool(self.expected_pv_measured_at and (datetime.now(UTC) - self.expected_pv_measured_at).total_seconds() <= self.settings.irradiance_max_age_seconds),
                "arrays": {
                    "pv1": {"orientation": "north", "capacity_kwp": self.settings.north_capacity_kwp, "measured_kw": self.telemetry.pv1_kw if self.telemetry else None, "expected_kw": array_forecast["pv1_kw"], "error_kw": (float(self.telemetry.pv1_kw or 0) - array_forecast["pv1_kw"]) if self.telemetry else None},
                    "pv2": {"orientation": "south", "capacity_kwp": self.settings.south_capacity_kwp / 3.0, "measured_kw": self.telemetry.pv2_kw if self.telemetry else None, "expected_kw": array_forecast["pv2_kw"], "error_kw": (float(self.telemetry.pv2_kw or 0) - array_forecast["pv2_kw"]) if self.telemetry else None},
                    "pv3": {"orientation": "south", "capacity_kwp": self.settings.south_capacity_kwp * 2.0 / 3.0, "measured_kw": self.telemetry.pv3_kw if self.telemetry else None, "expected_kw": array_forecast["pv3_kw"], "error_kw": (float(self.telemetry.pv3_kw or 0) - array_forecast["pv3_kw"]) if self.telemetry else None},
                    "forecast_error_valid": bool(self.command and not self.command.zero_export),
                },
                "providers": list(self.solar.providers) if self.solar else [],
                "irradiance": {
                    "measured_at": self.irradiance.measured_at if self.irradiance else None,
                    "ghi_wm2": self.irradiance.ghi_wm2 if self.irradiance else None,
                    "poa_north_wm2": self.irradiance.poa_north_wm2 if self.irradiance else None,
                    "poa_south_wm2": self.irradiance.poa_south_wm2 if self.irradiance else None,
                    "expected_uncurtailed_kw": self.irradiance.expected_uncurtailed_kw if self.irradiance else None,
                    "error": self.irradiance.last_error if self.irradiance else None,
                },
            },
            "power_flow": live_power_flow(self.telemetry, self.devices, self._server_rack_kw()) if self.telemetry else None,
            "source_allocation": source_allocation(self.telemetry, self.devices, self._server_rack_kw()) if self.telemetry else None,
            "server_rack": {
                **self.nut.state.as_dict(),
                **self.ups_allocation,
                # Canonical dashboard units.  Retain the raw NUT watt fields
                # above for API compatibility and diagnostics.
                "input_power_kw": (
                    self.nut.state.server_rack_power_w / 1000
                    if self.nut.state.available and self.nut.state.server_rack_power_w is not None else None
                ),
                "output_power_kw": (
                    self.nut.state.raw_real_power_w / 1000
                    if self.nut.state.available and self.nut.state.raw_real_power_w is not None else None
                ),
                "energy_today_kwh": self.ups_daily.get("wall_input_kwh", (self.current_daily or {}).get("server_rack_kwh")),
            },
            "outcomes": {"latest_interval": self.last_outcome, "current_daily": self.current_daily, "last_ev_trip": self.last_ev_trip_result},
            "settings": self.public_settings(),
        })


def parse_forecast_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Australia/Brisbane"))
        return parsed.astimezone(UTC)
    except ValueError:
        return None
