from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from .ha import HomeAssistantClient
from .models import Plan
from .optimizer import EnergyOptimizer
from .state import LearningState


LOG = logging.getLogger(__name__)

PRICE_ENTITIES = {ENTITY["amber_fit"], ENTITY["amber_import"]}
CONTROL_ENTITIES = {
    ENTITY["mode"],
    ENTITY["manual_override"],
    ENTITY["battery_control"],
    ENTITY["rollout_approved"],
}
IMMEDIATE_REPLAN_ENTITIES = PRICE_ENTITIES | CONTROL_ENTITIES
TELEMETRY_CACHE_ENTITIES = {
    ENTITY["battery_soc"],
    ENTITY["battery_usable"],
    ENTITY["pv_power"],
    ENTITY["home_load"],
}
FAST_FRESHNESS_ENTITIES = {
    ENTITY["battery_soc"],
    ENTITY["pv_power"],
    ENTITY["home_load"],
}
WATCHED_STATE_ENTITIES = IMMEDIATE_REPLAN_ENTITIES | TELEMETRY_CACHE_ENTITIES


def dashboard_plan_attributes(plan: Plan) -> dict[str, Any]:
    """Return the full dispatch horizon in a compact Home Assistant payload."""
    attributes = plan.to_dict(interval_limit=0)
    attributes["intervals"] = [
        {
            "start": item.start.isoformat(),
            "duration_minutes": item.duration_minutes,
            "solar_kw": item.solar_kw,
            "solar_low_kw": item.solar_low_kw,
            "load_kw": item.load_kw,
            "hot_water_kw": item.hot_water_kw,
            "ev_kw": item.ev_kw,
            "import_price": item.import_price,
            "export_price": item.export_price,
            "battery_kw": item.battery_kw,
            "site_grid_kw": item.site_grid_kw,
            "soc_end_pct": item.soc_end_pct,
        }
        for item in plan.intervals
    ]
    return attributes


class Coordinator:
    def __init__(self, settings: Settings, ha: HomeAssistantClient | None = None):
        self.settings = settings
        self.timezone = ZoneInfo(settings.timezone)
        self.learning = LearningState(settings.data_dir / "learning-state.json")
        self.optimizer = EnergyOptimizer(settings, self.learning)
        self.ha = ha or HomeAssistantClient(settings.ha_url, settings.ha_token_file)
        self.last_plan: Plan | None = None
        self.last_full_plan: Plan | None = None
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.last_trigger: str | None = None
        self.last_decision_latency_ms: float | None = None
        self.last_cycle_ms: float | None = None
        self.last_price_event_at: datetime | None = None
        self.last_control_event_at: datetime | None = None
        self.state_stream_status = "starting"
        self.state_stream_error: str | None = None
        self.fast_dispatch_error: str | None = None
        self._stop = asyncio.Event()
        self._replan = asyncio.Event()
        self._pending_entities: set[str] = set()
        self._pending_received_at: datetime | None = None
        self._pending_received_monotonic: float | None = None
        self._cached_states: dict[str, dict[str, Any]] = {}
        self._state_received_monotonic: dict[str, float] = {}
        self._state_updated_monotonic: dict[str, float] = {}
        self._dispatch_revision = 0
        self._fast_events: asyncio.Queue[tuple[int, str, datetime, float]] = asyncio.Queue()
        self._publish_lock = asyncio.Lock()
        self._record_lock = asyncio.Lock()

    async def close(self) -> None:
        self._stop.set()
        self._replan.set()
        await self.ha.close()

    async def run_forever(self) -> None:
        watcher = asyncio.create_task(self._watch_state_changes(), name="energy-optimizer-ha-events")
        fast_worker = asyncio.create_task(self._run_fast_dispatch(), name="energy-optimizer-fast-dispatch")
        trigger = "startup"
        trigger_received_at: datetime | None = None
        trigger_received_monotonic: float | None = None
        try:
            while not self._stop.is_set():
                started = asyncio.get_running_loop().time()
                try:
                    await self.run_once(
                        trigger=trigger,
                        trigger_received_at=trigger_received_at,
                        trigger_received_monotonic=trigger_received_monotonic,
                    )
                except Exception as exc:  # noqa: BLE001 - the service must remain alive and publish failure health
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    LOG.exception("optimisation cycle failed")
                    await self._publish_failure(self.last_error)
                elapsed = asyncio.get_running_loop().time() - started
                delay = max(0.0, self.settings.interval_seconds - elapsed)
                try:
                    await asyncio.wait_for(self._replan.wait(), timeout=delay)
                except TimeoutError:
                    trigger = "periodic"
                    trigger_received_at = None
                    trigger_received_monotonic = None
                else:
                    if self._stop.is_set():
                        break
                    (
                        trigger,
                        trigger_received_at,
                        trigger_received_monotonic,
                    ) = self._take_pending_trigger()
        finally:
            watcher.cancel()
            fast_worker.cancel()
            await asyncio.gather(watcher, fast_worker, return_exceptions=True)
            self.state_stream_status = "stopped"

    async def run_once(
        self,
        *,
        trigger: str = "manual",
        trigger_received_at: datetime | None = None,
        trigger_received_monotonic: float | None = None,
    ) -> Plan:
        loop = asyncio.get_running_loop()
        cycle_started = loop.time()
        expected_revision = self._dispatch_revision
        state_fetch_started = loop.time()
        states = await self.ha.states()
        state_fetch_completed = loop.time()
        state_fetch_completed_at = datetime.now(timezone.utc)
        for item in states:
            entity_id = str(item.get("entity_id", ""))
            if self._state_received_monotonic.get(entity_id, 0.0) <= state_fetch_started:
                self._cache_state(
                    entity_id,
                    item,
                    received_at=state_fetch_completed_at,
                    received_monotonic=state_fetch_completed,
                )
        plan = await asyncio.to_thread(self.optimizer.build_plan, states)
        decision_latency_ms = (
            (loop.time() - trigger_received_monotonic) * 1000
            if trigger_received_monotonic is not None
            else (loop.time() - cycle_started) * 1000
        )
        publish_context = {
            "trigger": trigger,
            "trigger_received_at": trigger_received_at.isoformat() if trigger_received_at else None,
            "decision_latency_ms": round(decision_latency_ms, 1),
        }
        published = await self._publish_plan(
            plan,
            publish_context,
            expected_revision=expected_revision,
        )
        if not published:
            LOG.info("discarded stale full plan=%s after a newer dispatch event", plan.plan_id)
            return plan
        await self._record_plan_async(plan)
        self.last_plan = plan
        self.last_full_plan = plan
        self.last_success = datetime.now(self.timezone)
        self.last_error = None
        self.last_trigger = trigger
        self.last_decision_latency_ms = decision_latency_ms
        self.last_cycle_ms = (loop.time() - cycle_started) * 1000
        LOG.info(
            "plan=%s trigger=%s decision_ms=%.1f cycle_ms=%.1f mode=%s action=%s battery_kw=%.2f export_kw=%.2f confidence=%.2f",
            plan.plan_id,
            trigger,
            decision_latency_ms,
            self.last_cycle_ms,
            plan.mode,
            plan.action,
            plan.battery_power_target_kw,
            plan.site_export_target_kw,
            plan.confidence,
        )
        return plan

    @staticmethod
    def _ha_updated_monotonic(
        state: dict[str, Any],
        *,
        received_at: datetime,
        received_monotonic: float,
    ) -> float | None:
        """Map Home Assistant's measurement timestamp onto the event-loop clock."""
        raw = (
            state.get("last_reported")
            or state.get("last_updated")
            or state.get("last_changed")
        )
        if not raw:
            return None
        try:
            updated = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if updated.tzinfo is None or received_at.tzinfo is None:
            return None
        age_seconds = (
            received_at.astimezone(timezone.utc) - updated.astimezone(timezone.utc)
        ).total_seconds()
        # Small negative ages can occur from clock rounding.  Larger future
        # timestamps are invalid rather than evidence that telemetry is fresh.
        if age_seconds < -5:
            return None
        return received_monotonic - max(0.0, age_seconds)

    def _cache_state(
        self,
        entity_id: str,
        state: dict[str, Any],
        *,
        received_at: datetime,
        received_monotonic: float,
    ) -> None:
        self._cached_states[entity_id] = state
        self._state_received_monotonic[entity_id] = received_monotonic
        updated_monotonic = self._ha_updated_monotonic(
            state,
            received_at=received_at,
            received_monotonic=received_monotonic,
        )
        if updated_monotonic is None:
            self._state_updated_monotonic.pop(entity_id, None)
        else:
            self._state_updated_monotonic[entity_id] = updated_monotonic

    def _mark_state_stream_connected(self) -> None:
        self.state_stream_status = "connected"
        self.state_stream_error = None

    @staticmethod
    def _state_value(event: dict[str, Any], key: str) -> str | None:
        state = event.get(key)
        if not isinstance(state, dict):
            return None
        value = state.get("state")
        return None if value is None else str(value)

    @staticmethod
    def _price_fingerprint(event: dict[str, Any], key: str) -> tuple[Any, Any, Any]:
        state = event.get(key)
        if not isinstance(state, dict):
            return None, None, None
        attributes = state.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        return (
            state.get("state"),
            attributes.get("start_time") or attributes.get("startTime"),
            attributes.get("end_time") or attributes.get("endTime"),
        )

    def _queue_immediate_replan(self, entity_id: str, received_at: datetime) -> None:
        loop = asyncio.get_running_loop()
        received_monotonic = loop.time()
        if not self._pending_entities:
            self._pending_received_at = received_at
            self._pending_received_monotonic = received_monotonic
        self._pending_entities.add(entity_id)
        self._replan.set()

    def _take_pending_trigger(self) -> tuple[str, datetime | None, float | None]:
        entities = sorted(self._pending_entities)
        received_at = self._pending_received_at
        received_monotonic = self._pending_received_monotonic
        self._pending_entities.clear()
        self._pending_received_at = None
        self._pending_received_monotonic = None
        self._replan.clear()
        trigger = "ha_state_changed:" + ",".join(entities) if entities else "ha_state_changed"
        return trigger, received_at, received_monotonic

    async def _watch_state_changes(self) -> None:
        reconnect_delay = 1.0
        while not self._stop.is_set():
            try:
                self.state_stream_status = "connecting"
                async for event in self.ha.state_changes(
                    WATCHED_STATE_ENTITIES,
                    on_subscribed=self._mark_state_stream_connected,
                ):
                    if self._stop.is_set():
                        return
                    entity_id = str(event.get("entity_id", ""))
                    new_state = event.get("new_state")
                    if isinstance(new_state, dict):
                        received_at = datetime.now(self.timezone)
                        received_monotonic = asyncio.get_running_loop().time()
                        self._cache_state(
                            entity_id,
                            {"entity_id": entity_id, **new_state},
                            received_at=received_at,
                            received_monotonic=received_monotonic,
                        )
                    else:
                        self._cached_states.pop(entity_id, None)
                        self._state_received_monotonic.pop(entity_id, None)
                        self._state_updated_monotonic.pop(entity_id, None)
                    changed = (
                        self._price_fingerprint(event, "old_state")
                        != self._price_fingerprint(event, "new_state")
                        if entity_id in PRICE_ENTITIES
                        else self._state_value(event, "old_state")
                        != self._state_value(event, "new_state")
                    )
                    if not changed:
                        continue
                    if entity_id not in IMMEDIATE_REPLAN_ENTITIES:
                        continue
                    received_at = datetime.now(self.timezone)
                    received_monotonic = asyncio.get_running_loop().time()
                    self._dispatch_revision += 1
                    revision = self._dispatch_revision
                    if entity_id in PRICE_ENTITIES:
                        self.last_price_event_at = received_at
                    else:
                        self.last_control_event_at = received_at
                    self._fast_events.put_nowait(
                        (revision, entity_id, received_at, received_monotonic)
                    )
                    self._queue_immediate_replan(entity_id, received_at)
                    reconnect_delay = 1.0
                if not self._stop.is_set():
                    raise RuntimeError("Home Assistant state stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - periodic planning remains the safe fallback
                self.state_stream_status = "retrying"
                self.state_stream_error = f"{type(exc).__name__}: {exc}"
                LOG.warning("Home Assistant event stream unavailable; retrying in %.0fs: %s", reconnect_delay, exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=reconnect_delay)
                except TimeoutError:
                    pass
                reconnect_delay = min(30.0, reconnect_delay * 2)

    def _cached_state_age(self, entity_ids: set[str], now_monotonic: float) -> float:
        ages = [
            now_monotonic - self._state_updated_monotonic[entity_id]
            for entity_id in entity_ids
            if entity_id in self._state_updated_monotonic
        ]
        if len(ages) != len(entity_ids):
            return float("inf")
        return max(0.0, max(ages, default=0.0))

    async def _run_fast_dispatch(self) -> None:
        while not self._stop.is_set():
            revision, entity_id, received_at, received_monotonic = await self._fast_events.get()
            try:
                if revision != self._dispatch_revision or self.last_full_plan is None:
                    continue
                now_monotonic = asyncio.get_running_loop().time()
                plan = self.optimizer.build_fast_price_plan(
                    self.last_full_plan,
                    list(self._cached_states.values()),
                    state_age_seconds=self._cached_state_age(
                        FAST_FRESHNESS_ENTITIES,
                        now_monotonic,
                    ),
                    soc_age_seconds=self._cached_state_age(
                        {ENTITY["battery_soc"]},
                        now_monotonic,
                    ),
                )
                decision_latency_ms = (
                    asyncio.get_running_loop().time() - received_monotonic
                ) * 1000
                published = await self._publish_plan(
                    plan,
                    {
                        "trigger": f"fast_state_changed:{entity_id}",
                        "trigger_received_at": received_at.isoformat(),
                        "decision_latency_ms": round(decision_latency_ms, 1),
                        "fast_dispatch": True,
                        "full_optimisation_pending": True,
                    },
                    expected_revision=revision,
                )
                if not published:
                    continue
                await self._record_plan_async(plan)
                self.last_plan = plan
                self.last_success = datetime.now(self.timezone)
                self.last_error = None
                self.fast_dispatch_error = None
                self.last_trigger = f"fast_state_changed:{entity_id}"
                self.last_decision_latency_ms = decision_latency_ms
                self.last_cycle_ms = (
                    asyncio.get_running_loop().time() - received_monotonic
                ) * 1000
                LOG.info(
                    "fast plan=%s trigger=%s decision_ms=%.1f cycle_ms=%.1f action=%s battery_kw=%.2f export_kw=%.2f",
                    plan.plan_id,
                    entity_id,
                    decision_latency_ms,
                    self.last_cycle_ms,
                    plan.action,
                    plan.battery_power_target_kw,
                    plan.site_export_target_kw,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad event must not kill the fast worker
                self.fast_dispatch_error = f"{type(exc).__name__}: {exc}"
                LOG.exception(
                    "fast dispatch failed for revision=%s entity=%s; worker remains active",
                    revision,
                    entity_id,
                )
            finally:
                self._fast_events.task_done()

    async def _record_plan_async(self, plan: Plan) -> None:
        async with self._record_lock:
            await asyncio.to_thread(self._record_plan, plan)

    def _record_plan(self, plan: Plan) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        full = plan.to_dict()
        latest = self.settings.data_dir / "latest-plan.json"
        temporary = latest.with_name(f".{latest.name}.{plan.plan_id}.tmp")
        temporary.write_text(json.dumps(full, indent=2, sort_keys=True))
        temporary.replace(latest)
        journal = self.settings.data_dir / "plans" / f"{plan.generated_at:%Y-%m-%d}.jsonl"
        journal.parent.mkdir(parents=True, exist_ok=True)
        with journal.open("a") as handle:
            handle.write(json.dumps(full, separators=(",", ":")) + "\n")

    async def _publish_plan(
        self,
        plan: Plan,
        publish_context: dict[str, Any] | None = None,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        async with self._publish_lock:
            if (
                expected_revision is not None
                and expected_revision != self._dispatch_revision
            ):
                return False
            return await self._publish_plan_unlocked(
                plan,
                publish_context,
                expected_revision=expected_revision,
            )

    async def _publish_plan_unlocked(
        self,
        plan: Plan,
        publish_context: dict[str, Any] | None = None,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        summary = dashboard_plan_attributes(plan)
        common = {
            "plan_id": plan.plan_id,
            "generated_at": plan.generated_at.isoformat(),
            "valid_until": plan.valid_until.isoformat(),
            **(publish_context or {}),
        }
        publishes = [
            self.ha.publish_state("sensor.energy_optimizer_status", plan.mode, {
                **common,
                "friendly_name": "Energy Optimizer Status",
                "icon": "mdi:home-lightning-bolt-outline",
                "action": plan.action,
                "reason": plan.reason,
                "confidence": plan.confidence,
                "warnings": plan.warnings,
            }),
            self.ha.publish_state("sensor.energy_optimizer_battery_power_target", round(plan.battery_power_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Battery Power Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
                "action": plan.action,
                "actuation_allowed": plan.actuation_allowed,
            }),
            self.ha.publish_state("sensor.energy_optimizer_site_export_target", round(plan.site_export_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Site Export Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
            }),
            self.ha.publish_state("sensor.energy_optimizer_pv_export", plan.pv_export_command, {
                **common,
                "friendly_name": "Energy Optimizer PV Export",
                "icon": "mdi:transmission-tower-export",
                "curtailment_target_kw": plan.pv_curtailment_target_kw,
            }),
            self.ha.publish_state("sensor.energy_optimizer_hot_water", plan.hot_water_command, {
                **common,
                "friendly_name": "Energy Optimizer Hot Water",
                "icon": "mdi:water-boiler",
                "evening_crossover": plan.evening_crossover.isoformat() if plan.evening_crossover else None,
            }),
            self.ha.publish_state("sensor.energy_optimizer_ev", plan.ev_action, {
                **common,
                "friendly_name": "Energy Optimizer EV",
                "icon": "mdi:car-electric",
                "target_soc_pct": plan.ev_target_soc_pct,
                "required_kwh": plan.ev_required_kwh,
                "charge_amps_target": plan.ev_charge_amps_target,
                "power_target_kw": plan.ev_power_target_kw,
                "charge_source": plan.ev_charge_source,
                "solar_energy_kwh": plan.ev_solar_energy_kwh,
                "fallback_energy_kwh": plan.ev_fallback_energy_kwh,
                "charge_start": plan.ev_charge_start.isoformat() if plan.ev_charge_start else None,
                "charge_end": plan.ev_charge_end.isoformat() if plan.ev_charge_end else None,
                "estimated_cost": plan.ev_estimated_cost,
            }),
        ]
        await asyncio.gather(*publishes)
        if (
            expected_revision is not None
            and expected_revision != self._dispatch_revision
        ):
            return False
        # The plan entity is the commit marker and event-driven actuator trigger.
        # Publish it only after every compact command sensor carries the same ID.
        await self.ha.publish_state("sensor.energy_optimizer_plan", plan.plan_id, {
            "friendly_name": "Energy Optimizer Plan",
            "icon": "mdi:chart-timeline-variant-shimmer",
            **common,
            **summary,
        })
        return True

    async def _publish_failure(self, error: str) -> None:
        try:
            await self.ha.publish_state("sensor.energy_optimizer_status", "error", {
                "friendly_name": "Energy Optimizer Status",
                "icon": "mdi:alert-circle",
                "error": error[:512],
                "safe_state": "Node-RED must reject stale plans and cancel forced operation",
            })
        except Exception:  # noqa: BLE001
            LOG.exception("failed to publish optimiser failure to Home Assistant")

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.last_success and not self.last_error else "starting" if not self.last_error else "error",
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "plan_id": self.last_plan.plan_id if self.last_plan else None,
            "mode": self.last_plan.mode if self.last_plan else None,
            "last_trigger": self.last_trigger,
            "last_decision_latency_ms": round(self.last_decision_latency_ms, 1) if self.last_decision_latency_ms is not None else None,
            "last_cycle_ms": round(self.last_cycle_ms, 1) if self.last_cycle_ms is not None else None,
            "last_price_event_at": self.last_price_event_at.isoformat() if self.last_price_event_at else None,
            "last_control_event_at": self.last_control_event_at.isoformat() if self.last_control_event_at else None,
            "state_stream_status": self.state_stream_status,
            "state_stream_error": self.state_stream_error,
            "fast_dispatch_error": self.fast_dispatch_error,
        }
