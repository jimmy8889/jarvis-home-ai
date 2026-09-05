from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import gzip
import json
import logging
import shutil
from typing import Any
from zoneinfo import ZoneInfo

from .config import ENTITY, Settings
from .ha import HomeAssistantClient
from .models import Plan, TelemetryHealth
from .optimizer import EnergyOptimizer
from .outcomes import OutcomeRecorder
from .state import LearningState


LOG = logging.getLogger(__name__)

PRICE_ENTITIES = {ENTITY["amber_fit"], ENTITY["amber_import"]}
CONTROL_ENTITIES = {
    ENTITY["mode"],
    ENTITY["manual_override"],
    ENTITY["battery_control"],
    ENTITY["rollout_approved"],
    ENTITY["min_sell_price"],
}
EV_REQUIREMENT_ENTITIES = {
    ENTITY["ev_trip"],
    ENTITY["ev_custom_km"],
    ENTITY["ev_departure"],
    ENTITY["ev_charge_limit"],
    ENTITY["ev_allow_grid"],
}
EV_PHYSICAL_ENTITIES = {
    ENTITY["ev_power"],
    ENTITY["ev_power_local"],
    ENTITY["ev_charger"],
    ENTITY["ev_soc"],
    ENTITY["ev_limit"],
    ENTITY["ev_plugged"],
    ENTITY["ev_home"],
}
HOT_WATER_PHYSICAL_ENTITIES = {
    ENTITY["hot_water_runtime"],
    ENTITY["hot_water_power"],
    ENTITY["hot_water_active"],
    ENTITY["hot_water_control"],
    ENTITY["hot_water_satisfied"],
    ENTITY["hot_water_source"],
}
# Only external requirements and connection/SOC changes alter the horizon
# immediately. Charger/relay/power edges are cached for the next plan but must
# not feed the optimiser's own commands back into another full DP solve.
EV_EXTERNAL_ENTITIES = {
    ENTITY["ev_soc"],
    ENTITY["ev_limit"],
    ENTITY["ev_plugged"],
    ENTITY["ev_home"],
}
IMMEDIATE_REPLAN_ENTITIES = (
    PRICE_ENTITIES
    | CONTROL_ENTITIES
    | EV_REQUIREMENT_ENTITIES
    | EV_EXTERNAL_ENTITIES
    | {ENTITY["hot_water_satisfied"]}
)
TELEMETRY_CACHE_ENTITIES = {
    ENTITY["battery_soc"],
    ENTITY["battery_soc_heartbeat"],
    ENTITY["battery_usable"],
    ENTITY["pv_power"],
    ENTITY["pv_heartbeat"],
    ENTITY["home_load"],
    ENTITY["ev_source"],
    ENTITY["actuator_status"],
    ENTITY["actuation_ready"],
    *EV_PHYSICAL_ENTITIES,
    *HOT_WATER_PHYSICAL_ENTITIES,
}
FAST_FRESHNESS_ENTITIES = {
    ENTITY["battery_soc_heartbeat"],
    ENTITY["pv_power"],
    ENTITY["pv_heartbeat"],
    ENTITY["home_load"],
}
WATCHED_STATE_ENTITIES = IMMEDIATE_REPLAN_ENTITIES | TELEMETRY_CACHE_ENTITIES

HOME_ASSISTANT_RECORDER_ATTRIBUTE_LIMIT_BYTES = 16 * 1024
# Leave headroom for Home Assistant's JSON representation and future scalar
# contract fields.  Exceeding the recorder limit makes an otherwise valid
# commit marker disappear from history, so fail before publishing instead.
HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES = 12 * 1024
HORIZON_ENTITY_PREFIX = "sensor.energy_optimizer_horizon_"
PLAN_SOURCE_TIMESTAMP_KEYS = (
    "amber_fit",
    "amber_import",
    "battery_soc",
    "battery_soc_heartbeat",
    "pv_power",
    "pv_heartbeat",
    "home_load",
)


def home_assistant_attribute_bytes(attributes: dict[str, Any]) -> int:
    """Return the compact UTF-8 JSON size Home Assistant must record."""
    return len(
        json.dumps(
            attributes,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _bounded_text(value: Any, limit: int) -> str:
    return str(value)[:limit]


def _dashboard_interval(item: Any) -> dict[str, Any]:
    """Return the named interval fields consumed by the Lovelace dashboard."""
    return {
        "start": item.start.isoformat(),
        "duration_minutes": round(item.duration_minutes, 2),
        "solar_kw": round(item.solar_kw, 3),
        "solar_low_kw": round(item.solar_low_kw, 3),
        "load_kw": round(item.load_kw, 3),
        "hot_water_kw": round(item.hot_water_kw, 3),
        "hot_water_control_mode": _bounded_text(item.hot_water_control_mode, 32),
        "ev_kw": round(item.ev_kw, 3),
        "import_price": round(item.import_price, 6),
        "export_price": round(item.export_price, 6),
        "battery_kw": round(item.battery_kw, 3),
        "site_grid_kw": round(item.site_grid_kw, 3),
        "soc_end_pct": round(item.soc_end_pct, 2),
    }


def dashboard_horizon_attributes(plan: Plan) -> list[dict[str, Any]]:
    """Split the full dashboard horizon into recorder-safe sensor payloads."""
    serialized_intervals = [_dashboard_interval(item) for item in plan.intervals]
    interval_groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def provisional_payload(items: list[dict[str, Any]], offset: int) -> dict[str, Any]:
        return {
            "friendly_name": "Energy Optimizer Horizon 999/999",
            "icon": "mdi:chart-timeline-variant-shimmer",
            "plan_id": plan.plan_id,
            "generated_at": plan.generated_at.isoformat(),
            "valid_until": plan.valid_until.isoformat(),
            # Three digits deliberately overestimates the normal chunk metadata.
            "chunk_index": 999,
            "chunk_count": 999,
            "interval_offset": offset,
            "interval_count": len(items),
            "intervals": items,
        }

    offset = 0
    for interval in serialized_intervals:
        candidate = [*current, interval]
        if (
            current
            and home_assistant_attribute_bytes(provisional_payload(candidate, offset))
            > HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
        ):
            interval_groups.append(current)
            offset += len(current)
            current = [interval]
        else:
            current = candidate
        if (
            home_assistant_attribute_bytes(provisional_payload(current, offset))
            > HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
        ):
            raise ValueError("one dashboard horizon interval exceeds Home Assistant attribute budget")
    if current or not interval_groups:
        interval_groups.append(current)

    chunk_count = len(interval_groups)
    chunks: list[dict[str, Any]] = []
    offset = 0
    for index, items in enumerate(interval_groups, start=1):
        attributes = {
            "friendly_name": f"Energy Optimizer Horizon {index}/{chunk_count}",
            "icon": "mdi:chart-timeline-variant-shimmer",
            "plan_id": plan.plan_id,
            "generated_at": plan.generated_at.isoformat(),
            "valid_until": plan.valid_until.isoformat(),
            "chunk_index": index,
            "chunk_count": chunk_count,
            "interval_offset": offset,
            "interval_count": len(items),
            "intervals": items,
        }
        if home_assistant_attribute_bytes(attributes) > HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES:
            raise ValueError("dashboard horizon chunk exceeds Home Assistant attribute budget")
        chunks.append(attributes)
        offset += len(items)
    return chunks


def dashboard_plan_attributes(
    plan: Plan,
    *,
    horizon_plan: Plan | None = None,
    horizon_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the recorder-safe scalar schema-v2 commit-marker payload.

    A fast five-minute dispatch changes only the live control decision.  Its
    dashboard horizon can therefore continue to reference the last committed
    full plan instead of republishing every unchanged chunk before actuation.
    """
    horizon_source = horizon_plan or plan
    if horizon_chunks is None:
        horizon_chunks = dashboard_horizon_attributes(horizon_source)
    attributes = plan.to_dict(interval_limit=0)
    attributes.pop("intervals", None)
    # A fast dispatch is deliberately a live-command overlay on the last full
    # rolling solve.  Keep forecast totals and timestamps anchored to that full
    # solve so the dashboard does not appear to rewrite the day every five
    # minutes merely because the command interval is shorter.
    if horizon_source.plan_id != plan.plan_id:
        horizon_values = horizon_source.to_dict(interval_limit=0)
        forecast_fields = {
            "morning_takeover",
            "evening_crossover",
            "expected_cost",
            "expected_revenue",
            "expected_wear_cost",
            "forecast_confidence",
            "hot_water_scheduled_hours",
            "hot_water_unmet_hours",
            "hot_water_solar_energy_kwh",
            "hot_water_battery_energy_kwh",
            "hot_water_grid_energy_kwh",
            "ev_solar_energy_kwh",
            "ev_battery_energy_kwh",
            "ev_grid_energy_kwh",
            "ev_fallback_energy_kwh",
            "ev_unmet_kwh",
            "ev_charge_start",
            "ev_charge_end",
            "ev_estimated_cost",
            "house_solar_energy_kwh",
            "house_battery_energy_kwh",
            "house_grid_energy_kwh",
        }
        for field in forecast_fields:
            if field in horizon_values:
                attributes[field] = horizon_values[field]
    attributes["action"] = _bounded_text(plan.action, 128)
    attributes["reason"] = _bounded_text(plan.reason, 512)
    attributes["warnings"] = [
        _bounded_text(warning, 256) for warning in plan.warnings[:8]
    ]
    attributes["solar_potential_source"] = _bounded_text(
        plan.solar_potential_source,
        128,
    )
    attributes["source_timestamps"] = {
        key: plan.source_timestamps.get(key) for key in PLAN_SOURCE_TIMESTAMP_KEYS
    }
    attributes["horizon_plan_id"] = horizon_source.plan_id
    attributes["horizon_generated_at"] = horizon_source.generated_at.isoformat()
    attributes["horizon_interval_count"] = len(horizon_source.intervals)
    attributes["horizon_chunk_count"] = len(horizon_chunks)
    attributes["horizon_entity_ids"] = [
        f"{HORIZON_ENTITY_PREFIX}{index}"
        for index in range(1, len(horizon_chunks) + 1)
    ]
    attributes["horizon_storage"] = (
        "retained_full_plan_sensor_chunks_and_plan_journal"
        if horizon_source.plan_id != plan.plan_id
        else "recorder_safe_sensor_chunks_and_plan_journal"
    )
    if home_assistant_attribute_bytes(attributes) > HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES:
        raise ValueError("plan commit marker exceeds Home Assistant attribute budget")
    return attributes


class Coordinator:
    def __init__(self, settings: Settings, ha: HomeAssistantClient | None = None):
        self.settings = settings
        self.timezone = ZoneInfo(settings.timezone)
        self.learning = LearningState(settings.data_dir / "learning-state.json")
        self.optimizer = EnergyOptimizer(settings, self.learning)
        self.outcomes = OutcomeRecorder(settings)
        self.ha = ha or HomeAssistantClient(settings.ha_url, settings.ha_token_file)
        self.last_plan: Plan | None = None
        self.last_full_plan: Plan | None = None
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.last_trigger: str | None = None
        self.last_decision_latency_ms: float | None = None
        self.last_fast_dispatch_latency_ms: float | None = None
        self.last_cycle_ms: float | None = None
        self.last_price_event_at: datetime | None = None
        self.last_control_event_at: datetime | None = None
        self.state_stream_status = "starting"
        self.state_stream_error: str | None = None
        self.fast_dispatch_error: str | None = None
        self.outcome_error: str | None = None
        self.last_outcome_at: datetime | None = None
        self.realized_outcome_rows = 0
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
        self._last_journal_prune_date = None

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
        # Plan from the same merged cache used to derive freshness.  A
        # WebSocket update can arrive while the bulk GET is in flight; passing
        # the older HTTP snapshot with newer cache timestamps could otherwise
        # authorize a value that has already become unavailable.
        planning_states = list(self._cached_states.values())
        telemetry_health = self._actuation_telemetry_health(loop.time())
        try:
            completed_outcomes = await asyncio.to_thread(
                self.outcomes.observe,
                planning_states,
                self.last_plan,
                state_fetch_completed_at,
            )
            if completed_outcomes:
                self.last_outcome_at = state_fetch_completed_at.astimezone(self.timezone)
                self.realized_outcome_rows += len(completed_outcomes)
            self.outcome_error = None
        except Exception as exc:  # noqa: BLE001 - evidence failure must not stop safe dispatch
            self.outcome_error = f"{type(exc).__name__}: {exc}"
            LOG.exception("failed to record realized five-minute outcome")
        plan = await asyncio.to_thread(
            self.optimizer.build_plan,
            planning_states,
            telemetry_health=telemetry_health,
        )
        decision_latency_ms = (
            (loop.time() - trigger_received_monotonic) * 1000
            if trigger_received_monotonic is not None
            else (loop.time() - cycle_started) * 1000
        )
        publish_context = {
            "trigger": trigger,
            "trigger_received_at": trigger_received_at.isoformat() if trigger_received_at else None,
            "decision_latency_ms": round(decision_latency_ms, 1),
            "last_fast_dispatch_latency_ms": (
                round(self.last_fast_dispatch_latency_ms, 1)
                if self.last_fast_dispatch_latency_ms is not None
                else None
            ),
        }
        published = await self._publish_plan(
            plan,
            publish_context,
            expected_revision=expected_revision,
        )
        if not published:
            LOG.info("discarded stale full plan=%s after a newer dispatch event", plan.plan_id)
            return plan
        # _publish_plan advances these atomically under its lock; repeat the
        # assignment here to keep the caller contract explicit and testable
        # when publication is replaced by a transport stub.
        self.last_plan = plan
        self.last_full_plan = plan
        await self._record_plan_async(plan)
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

    @staticmethod
    def _physical_fingerprint(entity_id: str, event: dict[str, Any], key: str) -> Any:
        value = Coordinator._state_value(event, key)
        if entity_id not in {
            ENTITY["ev_power"],
            ENTITY["ev_power_local"],
            ENTITY["hot_water_power"],
        }:
            return value
        try:
            power = abs(float(value))
        except (TypeError, ValueError):
            return value
        # These two HA entities have historically used different units.  Only
        # the physical off/on edge needs an immediate replan; small telemetry
        # fluctuations during a charge/heating run must not launch a DP storm.
        power_kw = power / 1000 if power > 100 else power
        return power_kw >= 0.2

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
                    if entity_id in PRICE_ENTITIES:
                        changed = self._price_fingerprint(
                            event, "old_state"
                        ) != self._price_fingerprint(event, "new_state")
                    elif entity_id in EV_PHYSICAL_ENTITIES | HOT_WATER_PHYSICAL_ENTITIES:
                        changed = self._physical_fingerprint(
                            entity_id, event, "old_state"
                        ) != self._physical_fingerprint(entity_id, event, "new_state")
                    else:
                        changed = self._state_value(
                            event, "old_state"
                        ) != self._state_value(event, "new_state")
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
                    # EV requirement changes need a fresh full schedule: a
                    # retained-price fast plan would otherwise publish the
                    # previous EV target until the next periodic cycle.
                    if entity_id in PRICE_ENTITIES | CONTROL_ENTITIES:
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

    def _actuation_telemetry_health(self, now_monotonic: float) -> TelemetryHealth:
        def age(entity_id: str) -> float | None:
            updated = self._state_updated_monotonic.get(entity_id)
            return None if updated is None else max(0.0, now_monotonic - updated)

        return TelemetryHealth(
            soc_source_heartbeat_age_seconds=age(ENTITY["battery_soc_heartbeat"]),
            pv_age_seconds=age(ENTITY["pv_power"]),
            load_age_seconds=age(ENTITY["home_load"]),
            pv_source_heartbeat_age_seconds=age(ENTITY["pv_heartbeat"]),
        )

    async def _run_fast_dispatch(self) -> None:
        while not self._stop.is_set():
            revision, entity_id, received_at, received_monotonic = await self._fast_events.get()
            try:
                # Amber publishes import and FIT as separate HA state events.
                # Coalesce that pair so an incomplete interval never becomes a
                # transient hold/zero command. 250 ms remains comfortably inside
                # the one-second live-price response objective.
                if entity_id in PRICE_ENTITIES:
                    await asyncio.sleep(0.25)
                if revision != self._dispatch_revision or self.last_full_plan is None:
                    continue
                now_monotonic = asyncio.get_running_loop().time()
                plan = self.optimizer.build_fast_price_plan(
                    self.last_full_plan,
                    list(self._cached_states.values()),
                    telemetry_health=self._actuation_telemetry_health(now_monotonic),
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
                        "last_fast_dispatch_latency_ms": round(decision_latency_ms, 1),
                        "fast_dispatch": True,
                        "full_optimisation_pending": True,
                    },
                    expected_revision=revision,
                    fast_dispatch=True,
                )
                if not published:
                    continue
                self.last_plan = plan
                await self._record_plan_async(plan)
                self.last_success = datetime.now(self.timezone)
                self.last_error = None
                self.fast_dispatch_error = None
                self.last_trigger = f"fast_state_changed:{entity_id}"
                self.last_decision_latency_ms = decision_latency_ms
                self.last_fast_dispatch_latency_ms = decision_latency_ms
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
        journal_payload = (
            plan.to_dict(interval_limit=1)
            if plan.plan_id.startswith("eop-fast-")
            else full
        )
        journal_payload["journal"] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "record_type": "fast_dispatch" if plan.plan_id.startswith("eop-fast-") else "full_plan",
            "outcome_status": "pending",
        }
        with journal.open("a") as handle:
            handle.write(json.dumps(journal_payload, separators=(",", ":")) + "\n")
        self._prune_plan_journals(plan.generated_at)

    def _prune_plan_journals(self, now: datetime) -> None:
        local_date = now.astimezone(self.timezone).date()
        if self._last_journal_prune_date == local_date:
            return
        self._last_journal_prune_date = local_date
        cutoff = local_date - timedelta(days=max(1, self.settings.journal_retention_days) - 1)
        journal_dir = self.settings.data_dir / "plans"
        for path in journal_dir.glob("????-??-??.jsonl"):
            try:
                journal_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if journal_date < cutoff:
                path.unlink(missing_ok=True)
            elif journal_date < local_date:
                compressed = path.with_suffix(".jsonl.gz")
                if compressed.exists():
                    # A completed day is normally compressed once.  If an
                    # operator has restored an extra plain fragment, preserve
                    # both instead of silently overwriting either one.
                    continue
                temporary = compressed.with_name(f".{compressed.name}.tmp")
                with path.open("rb") as source, gzip.open(temporary, "wb") as destination:
                    shutil.copyfileobj(source, destination)
                temporary.replace(compressed)
                path.unlink()
        for path in journal_dir.glob("????-??-??.jsonl.gz"):
            try:
                journal_date = datetime.strptime(
                    path.name.removesuffix(".jsonl.gz"),
                    "%Y-%m-%d",
                ).date()
            except ValueError:
                continue
            if journal_date < cutoff:
                path.unlink(missing_ok=True)

    async def _publish_plan(
        self,
        plan: Plan,
        publish_context: dict[str, Any] | None = None,
        *,
        expected_revision: int | None = None,
        fast_dispatch: bool = False,
    ) -> bool:
        async with self._publish_lock:
            if (
                expected_revision is not None
                and expected_revision != self._dispatch_revision
            ):
                return False
            published = await self._publish_plan_unlocked(
                plan,
                publish_context,
                expected_revision=expected_revision,
                fast_dispatch=fast_dispatch,
            )
            if published:
                # Advance the in-memory authority while still holding the same
                # lock that serialized the HA commit.  A waiting price event can
                # never observe the new commit with the previous full horizon.
                self.last_plan = plan
                if not fast_dispatch:
                    self.last_full_plan = plan
            return published

    async def _publish_plan_unlocked(
        self,
        plan: Plan,
        publish_context: dict[str, Any] | None = None,
        *,
        expected_revision: int | None = None,
        fast_dispatch: bool = False,
    ) -> bool:
        if fast_dispatch:
            if not plan.plan_id.startswith("eop-fast-"):
                raise ValueError("fast publication requires an eop-fast plan")
            if self.last_full_plan is None:
                raise ValueError("fast publication requires a committed full horizon")
        horizon_plan = self.last_full_plan if fast_dispatch else plan
        horizon_chunks = dashboard_horizon_attributes(horizon_plan)
        summary = dashboard_plan_attributes(
            plan,
            horizon_plan=horizon_plan,
            horizon_chunks=horizon_chunks,
        )
        common = {
            **(publish_context or {}),
            "plan_id": plan.plan_id,
            "generated_at": plan.generated_at.isoformat(),
            "valid_until": plan.valid_until.isoformat(),
            "command_semantic_hash": plan.command_semantic_hash,
        }
        # Schedule metadata always comes from the committed full horizon. Live
        # commands below still come from `plan`, including fast Amber overlays.
        schedule_plan = horizon_plan
        hot_water_intervals = [
            item for item in schedule_plan.intervals if item.hot_water_kw > 0
        ]
        daily_hot_water: dict[str, list[Any]] = {}
        for item in hot_water_intervals:
            daily_hot_water.setdefault(item.start.astimezone(self.timezone).date().isoformat(), []).append(item)
        service_date = schedule_plan.generated_at.astimezone(self.timezone).date().isoformat()
        current_service_intervals = daily_hot_water.get(service_date, [])
        hot_water_start = current_service_intervals[0].start if current_service_intervals else None
        hot_water_end = (
            current_service_intervals[-1].start
            + timedelta(minutes=current_service_intervals[-1].duration_minutes)
            if current_service_intervals
            else None
        )
        hot_water_hours = sum(
            item.duration_minutes for item in current_service_intervals
        ) / 60
        hot_water_schedule = [
            {
                "date": date_key,
                "expected_start": items[0].start.isoformat(),
                "expected_end": (
                    items[-1].start + timedelta(minutes=items[-1].duration_minutes)
                ).isoformat(),
                "expected_hours": round(sum(item.duration_minutes for item in items) / 60, 2),
                "control_modes": sorted({item.hot_water_control_mode for item in items}),
            }
            for date_key, items in sorted(daily_hot_water.items())
        ]
        control_publish_specs: list[tuple[str, Any, dict[str, Any]]] = [
            ("sensor.energy_optimizer_status", plan.mode, {
                **common,
                "friendly_name": "Energy Optimizer Status",
                "icon": "mdi:home-lightning-bolt-outline",
                "action": plan.action,
                "reason": plan.reason,
                "confidence": plan.confidence,
                "warnings": plan.warnings,
            }),
            ("sensor.energy_optimizer_battery_power_target", round(plan.battery_power_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Battery Power Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
                "action": plan.action,
                "battery_mode": plan.battery_mode,
                "protected_soc_pct": plan.protected_soc_pct,
                "house_reserve_soc_pct": plan.house_reserve_soc_pct,
                "battery_charge_target_kw": plan.battery_charge_target_kw,
                "battery_discharge_target_kw": plan.battery_discharge_target_kw,
                "actuation_allowed": plan.actuation_allowed,
            }),
            ("sensor.energy_optimizer_site_export_target", round(plan.site_export_target_kw, 3), {
                **common,
                "friendly_name": "Energy Optimizer Site Export Target",
                "unit_of_measurement": "kW",
                "device_class": "power",
                "state_class": "measurement",
            }),
            ("sensor.energy_optimizer_pv_export", plan.pv_export_command, {
                **common,
                "friendly_name": "Energy Optimizer PV Export",
                "icon": "mdi:transmission-tower-export",
                "curtailment_target_kw": plan.pv_curtailment_target_kw,
            }),
            ("sensor.energy_optimizer_hot_water", plan.hot_water_command, {
                **common,
                "friendly_name": "Energy Optimizer Hot Water",
                "icon": "mdi:water-boiler",
                "forecast_plan_id": schedule_plan.plan_id,
                "forecast_generated_at": schedule_plan.generated_at.isoformat(),
                "evening_crossover": schedule_plan.evening_crossover.isoformat() if schedule_plan.evening_crossover else None,
                "expected_start": hot_water_start.isoformat() if hot_water_start else None,
                "expected_end": hot_water_end.isoformat() if hot_water_end else None,
                "expected_hours": round(hot_water_hours, 2),
                "scheduled_hours": round(schedule_plan.hot_water_scheduled_hours, 2),
                "unmet_hours": round(schedule_plan.hot_water_unmet_hours, 2),
                "control_mode": plan.hot_water_control_mode,
                "protected_soc_pct": plan.protected_soc_pct,
                "service_target_hours": plan.hot_water_service_target_hours,
                "rescue_source": plan.hot_water_rescue_source,
                "solar_energy_kwh": schedule_plan.hot_water_solar_energy_kwh,
                "battery_energy_kwh": schedule_plan.hot_water_battery_energy_kwh,
                "grid_energy_kwh": schedule_plan.hot_water_grid_energy_kwh,
                "daily_schedule": hot_water_schedule,
            }),
            ("sensor.energy_optimizer_ev", plan.ev_action, {
                **common,
                "friendly_name": "Energy Optimizer EV",
                "icon": "mdi:car-electric",
                "forecast_plan_id": schedule_plan.plan_id,
                "forecast_generated_at": schedule_plan.generated_at.isoformat(),
                "target_soc_pct": plan.ev_target_soc_pct,
                "required_kwh": plan.ev_required_kwh,
                "charge_amps_target": plan.ev_charge_amps_target,
                "schedule_amps": plan.ev_schedule_amps,
                "live_target_amps": plan.ev_live_target_amps,
                "power_target_kw": plan.ev_power_target_kw,
                "charge_source": plan.ev_charge_source,
                "source_budget": plan.ev_source_budget,
                "house_reserve_soc_pct": plan.house_reserve_soc_pct,
                "solar_energy_kwh": schedule_plan.ev_solar_energy_kwh,
                "battery_energy_kwh": schedule_plan.ev_battery_energy_kwh,
                "grid_energy_kwh": schedule_plan.ev_grid_energy_kwh,
                "fallback_energy_kwh": schedule_plan.ev_fallback_energy_kwh,
                "grid_charging_allowed": plan.ev_grid_allowed,
                "mandatory": plan.ev_mandatory,
                "unmet_kwh": schedule_plan.ev_unmet_kwh,
                "charge_start": schedule_plan.ev_charge_start.isoformat() if schedule_plan.ev_charge_start else None,
                "charge_end": schedule_plan.ev_charge_end.isoformat() if schedule_plan.ev_charge_end else None,
                "estimated_cost": schedule_plan.ev_estimated_cost,
            }),
        ]
        publish_specs = list(control_publish_specs)
        if not fast_dispatch:
            acceptance = self.outcomes.summary()
            publish_specs.extend([
                ("sensor.energy_optimizer_solar_potential", round(plan.solar_potential_kw, 3), {
                    **common,
                    "friendly_name": "Energy Optimizer Solar Potential",
                    "unit_of_measurement": "kW",
                    "device_class": "power",
                    "state_class": "measurement",
                    "actual_pv_kw": round(plan.solar_actual_kw, 3),
                    "estimated_curtailed_kw": round(plan.solar_curtailed_estimate_kw, 3),
                    "live_correction_factor": round(plan.solar_live_correction_factor, 3),
                    "source": plan.solar_potential_source,
                    "north_capacity_kwp": self.settings.solar_north_capacity_kwp,
                    "north_azimuth_deg": self.settings.solar_north_azimuth_deg,
                    "south_capacity_kwp": self.settings.solar_south_capacity_kwp,
                    "south_azimuth_deg": self.settings.solar_south_azimuth_deg,
                    "model_tilt_deg": self.settings.solar_tilt_deg,
                    "roof_calibration": plan.solar_calibration_report,
                }),
                ("sensor.energy_optimizer_solar_actual", round(plan.solar_actual_kw, 3), {
                    **common,
                    "friendly_name": "Energy Optimizer Solar Actual",
                    "unit_of_measurement": "kW",
                    "device_class": "power",
                    "state_class": "measurement",
                }),
                ("sensor.energy_optimizer_solar_curtailed", round(plan.solar_curtailed_estimate_kw, 3), {
                    **common,
                    "friendly_name": "Energy Optimizer Solar Curtailed Estimate",
                    "unit_of_measurement": "kW",
                    "device_class": "power",
                    "state_class": "measurement",
                }),
                (
                    "sensor.energy_optimizer_acceptance",
                    acceptance.get("status", "collecting"),
                    {
                        **common,
                        "friendly_name": "Energy Optimizer Acceptance",
                        "icon": "mdi:clipboard-check-outline",
                        "daily": acceptance.get("daily", []),
                        "rolling_7d": acceptance.get("rolling_7d", {}),
                        "rolling_30d": acceptance.get("rolling_30d", {}),
                        "outcome_error": self.outcome_error,
                    },
                ),
            ])
            publish_specs.extend(
                (
                    f"{HORIZON_ENTITY_PREFIX}{index}",
                    plan.plan_id,
                    attributes,
                )
                for index, attributes in enumerate(horizon_chunks, start=1)
            )
        # The plan entity is the complete atomic actuator contract. Commit it
        # first so the signed Amber edge reaches Node-RED without waiting for
        # dashboard mirror and horizon writes. Flexible-load governors remain
        # fail-closed until their matching mirror sensors arrive immediately
        # afterwards.
        commit_requested_at = datetime.now(timezone.utc)
        summary["dispatch_timestamps"] = {
            **plan.dispatch_timestamps,
            "ha_commit_requested_at": commit_requested_at.isoformat(),
        }
        commit_attributes = {
            "friendly_name": "Energy Optimizer Plan",
            "icon": "mdi:chart-timeline-variant-shimmer",
            **common,
            **summary,
        }
        if (
            home_assistant_attribute_bytes(commit_attributes)
            > HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
        ):
            raise ValueError("plan commit marker exceeds Home Assistant attribute budget")
        await self.ha.publish_state(
            "sensor.energy_optimizer_plan",
            plan.plan_id,
            commit_attributes,
        )
        if (
            expected_revision is not None
            and expected_revision != self._dispatch_revision
        ):
            return False

        await asyncio.gather(
            *(
                self.ha.publish_state(entity_id, state, attributes)
                for entity_id, state, attributes in publish_specs
            )
        )
        if (
            expected_revision is not None
            and expected_revision != self._dispatch_revision
        ):
            return False
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

    def readiness(self, now: datetime | None = None) -> tuple[bool, str]:
        now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        if self.last_plan is None or self.last_success is None:
            return False, "no successful plan yet"
        if self.last_error:
            return False, f"latest optimisation failed: {self.last_error}"
        plan_age = max(0.0, (now - self.last_success.astimezone(self.timezone)).total_seconds())
        if plan_age > self.settings.readiness_max_age_seconds:
            return False, f"last successful plan is stale ({plan_age:.0f}s old)"
        if now >= self.last_plan.valid_until.astimezone(self.timezone):
            return False, "published plan has expired"
        if self.state_stream_status != "connected":
            return False, f"Home Assistant state stream is {self.state_stream_status}"
        if self.fast_dispatch_error:
            return False, f"immediate price dispatch failed: {self.fast_dispatch_error}"
        return True, "ready"

    def health(self) -> dict[str, Any]:
        now = datetime.now(self.timezone)
        ready, readiness_reason = self.readiness(now)
        if self.last_error:
            status = "error"
        elif self.last_success is None:
            status = "starting"
        elif not ready:
            status = "stale"
        elif self.state_stream_status in {"retrying", "stopped"} or self.outcome_error:
            status = "degraded"
        else:
            status = "ok"
        plan_age_seconds = (
            max(0.0, (now - self.last_success.astimezone(self.timezone)).total_seconds())
            if self.last_success
            else None
        )
        return {
            "status": status,
            "ready": ready,
            "readiness_reason": readiness_reason,
            "plan_age_seconds": round(plan_age_seconds, 1) if plan_age_seconds is not None else None,
            "plan_valid_for_seconds": (
                round((self.last_plan.valid_until - now).total_seconds(), 1)
                if self.last_plan
                else None
            ),
            "journal_retention_days": self.settings.journal_retention_days,
            "last_outcome_at": self.last_outcome_at.isoformat() if self.last_outcome_at else None,
            "realized_outcome_rows": self.realized_outcome_rows,
            "outcome_error": self.outcome_error,
            "acceptance": self.outcomes.summary(),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "plan_id": self.last_plan.plan_id if self.last_plan else None,
            "mode": self.last_plan.mode if self.last_plan else None,
            "last_trigger": self.last_trigger,
            "last_decision_latency_ms": round(self.last_decision_latency_ms, 1) if self.last_decision_latency_ms is not None else None,
            "last_fast_dispatch_latency_ms": round(self.last_fast_dispatch_latency_ms, 1) if self.last_fast_dispatch_latency_ms is not None else None,
            "last_cycle_ms": round(self.last_cycle_ms, 1) if self.last_cycle_ms is not None else None,
            "last_price_event_at": self.last_price_event_at.isoformat() if self.last_price_event_at else None,
            "last_control_event_at": self.last_control_event_at.isoformat() if self.last_control_event_at else None,
            "state_stream_status": self.state_stream_status,
            "immediate_dispatch_ready": (
                self.state_stream_status == "connected"
                and self.fast_dispatch_error is None
            ),
            "state_stream_error": self.state_stream_error,
            "fast_dispatch_error": self.fast_dispatch_error,
        }
