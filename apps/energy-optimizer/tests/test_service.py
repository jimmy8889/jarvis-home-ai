from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

from energy_optimizer.config import ENTITY, Settings
from energy_optimizer.models import DispatchInterval, Plan
from energy_optimizer.service import (
    CONTROL_ENTITIES,
    FAST_FRESHNESS_ENTITIES,
    HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES,
    HOME_ASSISTANT_RECORDER_ATTRIBUTE_LIMIT_BYTES,
    HOT_WATER_PHYSICAL_ENTITIES,
    EV_PHYSICAL_ENTITIES,
    Coordinator,
    dashboard_horizon_attributes,
    dashboard_plan_attributes,
    home_assistant_attribute_bytes,
)


def service_plan(start: datetime, *, plan_id: str = "service-plan") -> Plan:
    interval = DispatchInterval(
        start=start,
        duration_minutes=5,
        solar_kw=0.0,
        solar_low_kw=0.0,
        load_kw=1.0,
        hot_water_kw=0.0,
        ev_kw=0.0,
        import_price=0.16,
        export_price=0.30,
        battery_kw=1.0,
        site_grid_kw=0.0,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=79.8,
        cost=0.0,
        price_source="amber_live",
    )
    return Plan(
        plan_id=plan_id,
        generated_at=start,
        valid_until=start + timedelta(minutes=5),
        mode="active",
        actuation_allowed=True,
        action="self_consumption",
        reason="test",
        confidence=0.8,
        battery_power_target_kw=1.0,
        site_export_target_kw=0.0,
        pv_export_command="allow",
        pv_curtailment_target_kw=0.0,
        hot_water_command="off",
        ev_action="ready",
        ev_target_soc_pct=40.0,
        ev_required_kwh=0.0,
        ev_charge_amps_target=0,
        ev_power_target_kw=0.0,
        ev_charge_source="none",
        ev_solar_energy_kwh=0.0,
        ev_fallback_energy_kwh=0.0,
        ev_charge_start=None,
        ev_charge_end=None,
        ev_estimated_cost=0.0,
        morning_takeover=None,
        evening_crossover=None,
        expected_cost=0.0,
        expected_revenue=0.0,
        expected_wear_cost=0.0,
        intervals=[interval],
    )


def test_plan_commit_and_horizon_chunks_stay_below_ha_recorder_limit(tmp_path: Path) -> None:
    start = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
    intervals = [
        DispatchInterval(
            start=start + timedelta(minutes=30 * index),
            duration_minutes=30,
            solar_kw=1.0,
            solar_low_kw=0.8,
            load_kw=0.5,
            hot_water_kw=0.0,
            ev_kw=0.0,
            import_price=0.2,
            export_price=0.1,
            battery_kw=0.5,
            site_grid_kw=0.0,
            pv_curtailment_kw=0.0,
            soc_start_pct=50.0,
            soc_end_pct=49.0,
            cost=0.0,
            price_source="amber",
        )
        for index in range(72)
    ]
    plan = Plan(
        plan_id="test-plan",
        generated_at=start,
        valid_until=start + timedelta(minutes=10),
        mode="shadow",
        actuation_allowed=False,
        action="self_consume",
        reason="r" * 10_000,
        confidence=0.8,
        battery_power_target_kw=0.0,
        site_export_target_kw=0.0,
        pv_export_command="allow",
        pv_curtailment_target_kw=0.0,
        hot_water_command="off",
        ev_action="none",
        ev_target_soc_pct=40.0,
        ev_required_kwh=0.0,
        ev_charge_amps_target=0,
        ev_power_target_kw=0.0,
        ev_charge_source="none",
        ev_solar_energy_kwh=0.0,
        ev_fallback_energy_kwh=0.0,
        ev_charge_start=None,
        ev_charge_end=None,
        ev_estimated_cost=0.0,
        morning_takeover=None,
        evening_crossover=None,
        expected_cost=0.0,
        expected_revenue=0.0,
        expected_wear_cost=0.0,
        warnings=["w" * 2_000 for _ in range(20)],
        intervals=intervals,
    )

    attributes = dashboard_plan_attributes(plan)
    horizon_chunks = dashboard_horizon_attributes(plan)
    horizon = [
        interval
        for chunk in horizon_chunks
        for interval in chunk["intervals"]
    ]

    assert "intervals" not in attributes
    assert attributes["horizon_plan_id"] == plan.plan_id
    assert attributes["horizon_generated_at"] == plan.generated_at.isoformat()
    assert attributes["horizon_interval_count"] == 72
    assert attributes["horizon_chunk_count"] == len(horizon_chunks)
    assert len(horizon_chunks) > 1
    assert len(horizon) == 72
    assert set(horizon[0]) == {
        "start",
        "duration_minutes",
        "solar_kw",
        "solar_low_kw",
        "load_kw",
        "hot_water_kw",
        "hot_water_control_mode",
        "ev_kw",
        "import_price",
        "export_price",
        "battery_kw",
        "site_grid_kw",
        "soc_end_pct",
    }
    assert horizon[0]["duration_minutes"] == 30
    assert "pv_curtailment_kw" not in horizon[0]
    assert attributes["ev_power_target_kw"] == 0.0
    assert attributes["ev_charge_source"] == "none"
    assert attributes["ev_solar_energy_kwh"] == 0.0
    assert attributes["ev_fallback_energy_kwh"] == 0.0
    assert home_assistant_attribute_bytes(attributes) <= HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
    assert HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES < HOME_ASSISTANT_RECORDER_ATTRIBUTE_LIMIT_BYTES
    assert all(
        home_assistant_attribute_bytes(chunk) <= HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
        for chunk in horizon_chunks
    )

    class PublishingHA:
        def __init__(self) -> None:
            self.published: list[str] = []
            self.attributes: dict[str, dict] = {}

        async def publish_state(self, entity_id, state, attributes) -> None:
            self.published.append(entity_id)
            self.attributes[entity_id] = attributes

        async def close(self) -> None:
            return None

    publisher = PublishingHA()

    async def publish_scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=publisher)
        assert await coordinator._publish_plan(
            plan,
            {"fast_dispatch": True},
            expected_revision=0,
        )

    asyncio.run(publish_scenario())
    assert publisher.published[0] == "sensor.energy_optimizer_plan"
    assert "sensor.energy_optimizer_battery_power_target" in publisher.published[1:]
    assert attributes["horizon_entity_ids"]
    assert all(entity_id in publisher.published[1:] for entity_id in attributes["horizon_entity_ids"])
    assert all(
        home_assistant_attribute_bytes(entity_attributes)
        <= HOME_ASSISTANT_ATTRIBUTE_BUDGET_BYTES
        for entity_id, entity_attributes in publisher.attributes.items()
        if entity_id == "sensor.energy_optimizer_plan"
        or entity_id.startswith("sensor.energy_optimizer_horizon_")
    )

    stale_publisher = PublishingHA()

    async def stale_publish_scenario() -> bool:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=stale_publisher)
        original_publish = stale_publisher.publish_state

        async def publish_and_advance_revision(entity_id, state, attributes) -> None:
            await original_publish(entity_id, state, attributes)
            if entity_id == "sensor.energy_optimizer_battery_power_target":
                coordinator._dispatch_revision += 1

        stale_publisher.publish_state = publish_and_advance_revision
        return await coordinator._publish_plan(plan, expected_revision=0)

    assert asyncio.run(stale_publish_scenario()) is False
    assert stale_publisher.published[0] == "sensor.energy_optimizer_plan"


def test_fast_publish_is_bounded_and_commits_before_control_scalars(tmp_path: Path) -> None:
    start = datetime(2026, 8, 18, 9, 40, tzinfo=timezone.utc)
    full_plan = service_plan(start, plan_id="full-horizon")
    full_plan.intervals[0].hot_water_kw = 3.7
    full_plan.intervals[0].hot_water_control_mode = "solar_surplus"
    full_plan.hot_water_scheduled_hours = 3.0
    full_plan.hot_water_solar_energy_kwh = 11.1
    full_plan.ev_solar_energy_kwh = 8.4
    full_plan.ev_charge_start = start + timedelta(hours=1)
    full_plan.ev_charge_end = start + timedelta(hours=2)
    full_plan.expected_revenue = 12.34
    fast_plan = service_plan(
        start + timedelta(seconds=20),
        plan_id="eop-fast-20260818T194020-test",
    )
    fast_plan.ev_grid_allowed = True

    class PublishingHA:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.attributes: dict[str, dict] = {}

        async def publish_state(self, entity_id, state, attributes) -> None:
            if entity_id == "sensor.energy_optimizer_plan":
                assert self.calls == []
            self.calls.append(entity_id)
            self.attributes[entity_id] = attributes

        async def close(self) -> None:
            return None

    publisher = PublishingHA()

    async def scenario() -> bool:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=publisher)
        coordinator.last_full_plan = full_plan
        return await coordinator._publish_plan(
            fast_plan,
            {"fast_dispatch": True, "plan_id": "must-not-override"},
            expected_revision=0,
            fast_dispatch=True,
        )

    assert asyncio.run(scenario()) is True
    assert len(publisher.calls) == 7
    assert publisher.calls[0] == "sensor.energy_optimizer_plan"
    assert not any(
        entity_id.startswith("sensor.energy_optimizer_horizon_")
        for entity_id in publisher.calls
    )
    assert "sensor.energy_optimizer_solar_potential" not in publisher.calls
    assert "sensor.energy_optimizer_acceptance" not in publisher.calls
    assert publisher.attributes["sensor.energy_optimizer_ev"]["grid_charging_allowed"] is True
    hot_water = publisher.attributes["sensor.energy_optimizer_hot_water"]
    ev = publisher.attributes["sensor.energy_optimizer_ev"]
    assert hot_water["forecast_plan_id"] == full_plan.plan_id
    assert hot_water["expected_start"] == full_plan.intervals[0].start.isoformat()
    assert hot_water["scheduled_hours"] == 3.0
    assert hot_water["solar_energy_kwh"] == 11.1
    assert ev["forecast_plan_id"] == full_plan.plan_id
    assert ev["solar_energy_kwh"] == 8.4
    assert ev["charge_start"] == full_plan.ev_charge_start.isoformat()
    assert all(
        publisher.attributes[entity_id]["plan_id"] == fast_plan.plan_id
        for entity_id in publisher.calls
    )
    commit = publisher.attributes["sensor.energy_optimizer_plan"]
    assert commit["horizon_plan_id"] == full_plan.plan_id
    assert commit["horizon_generated_at"] == full_plan.generated_at.isoformat()
    assert commit["horizon_interval_count"] == len(full_plan.intervals)
    assert commit["horizon_storage"].startswith("retained_full_plan")
    assert commit["expected_revenue"] == 12.34


def test_fast_publish_revision_change_after_commit_aborts_remaining_mirrors(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 18, 9, 40, tzinfo=timezone.utc)
    full_plan = service_plan(start, plan_id="full-horizon")
    fast_plan = service_plan(
        start + timedelta(seconds=20),
        plan_id="eop-fast-20260818T194020-stale",
    )

    class BlockingHA:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.attributes: dict[str, dict] = {}
            self.battery_started = asyncio.Event()
            self.release_battery = asyncio.Event()

        async def publish_state(self, entity_id, state, attributes) -> None:
            self.calls.append(entity_id)
            self.attributes[entity_id] = attributes
            if entity_id == "sensor.energy_optimizer_battery_power_target":
                self.battery_started.set()
                await self.release_battery.wait()

        async def close(self) -> None:
            return None

    async def scenario() -> tuple[bool, BlockingHA]:
        publisher = BlockingHA()
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=publisher)
        coordinator.last_full_plan = full_plan
        publishing = asyncio.create_task(
            coordinator._publish_plan(
                fast_plan,
                {"fast_dispatch": True},
                expected_revision=0,
                fast_dispatch=True,
            )
        )
        await publisher.battery_started.wait()
        coordinator._dispatch_revision = 1
        publisher.release_battery.set()
        return await publishing, publisher

    published, publisher = asyncio.run(scenario())
    assert published is False
    assert publisher.calls[0] == "sensor.energy_optimizer_plan"
    assert len(publisher.calls) == 7
    assert all(
        attributes["plan_id"] == fast_plan.plan_id
        for attributes in publisher.attributes.values()
    )


def test_newer_fast_revision_wins_when_revision_changes_during_commit_post(
    tmp_path: Path,
) -> None:
    start = datetime(2026, 8, 18, 9, 40, tzinfo=timezone.utc)
    full_plan = service_plan(start, plan_id="full-horizon")
    older = service_plan(
        start + timedelta(seconds=20),
        plan_id="eop-fast-20260818T194020-older",
    )
    newer = service_plan(
        start + timedelta(seconds=21),
        plan_id="eop-fast-20260818T194021-newer",
    )

    class CommitBlockingHA:
        def __init__(self) -> None:
            self.latest: dict[str, tuple[object, dict]] = {}
            self.commit_ids: list[str] = []
            self.older_commit_started = asyncio.Event()
            self.release_older_commit = asyncio.Event()

        async def publish_state(self, entity_id, state, attributes) -> None:
            if entity_id == "sensor.energy_optimizer_plan":
                self.commit_ids.append(str(state))
                if state == older.plan_id:
                    self.older_commit_started.set()
                    await self.release_older_commit.wait()
            self.latest[entity_id] = (state, attributes)

        async def close(self) -> None:
            return None

    async def scenario() -> tuple[bool, bool, CommitBlockingHA]:
        publisher = CommitBlockingHA()
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=publisher)
        coordinator.last_full_plan = full_plan
        coordinator._dispatch_revision = 1
        older_publish = asyncio.create_task(
            coordinator._publish_plan(
                older,
                expected_revision=1,
                fast_dispatch=True,
            )
        )
        await publisher.older_commit_started.wait()
        coordinator._dispatch_revision = 2
        newer_publish = asyncio.create_task(
            coordinator._publish_plan(
                newer,
                expected_revision=2,
                fast_dispatch=True,
            )
        )
        publisher.release_older_commit.set()
        return await older_publish, await newer_publish, publisher

    older_published, newer_published, publisher = asyncio.run(scenario())
    assert older_published is False
    assert newer_published is True
    assert publisher.commit_ids == [older.plan_id, newer.plan_id]
    assert publisher.latest["sensor.energy_optimizer_plan"][0] == newer.plan_id
    assert all(
        attributes["plan_id"] == newer.plan_id
        for _, attributes in publisher.latest.values()
    )


def test_full_commit_advances_fast_base_before_journal_io(tmp_path: Path) -> None:
    start = datetime(2026, 8, 18, 9, 40, tzinfo=timezone.utc)
    committed = service_plan(start, plan_id="new-full-horizon")

    class FakeHA:
        async def states(self):
            return []

        async def publish_state(self, *_args, **_kwargs) -> None:
            return None

        async def close(self) -> None:
            return None

    class FakeOptimizer:
        @staticmethod
        def build_plan(*_args, **_kwargs) -> Plan:
            return committed

    class FakeOutcomes:
        @staticmethod
        def observe(*_args, **_kwargs):
            return []

        @staticmethod
        def summary():
            return {}

    async def scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        coordinator.optimizer = FakeOptimizer()
        coordinator.outcomes = FakeOutcomes()
        journal_started = asyncio.Event()
        release_journal = asyncio.Event()

        async def blocked_record(_plan: Plan) -> None:
            journal_started.set()
            await release_journal.wait()

        coordinator._record_plan_async = blocked_record
        run = asyncio.create_task(coordinator.run_once())
        await journal_started.wait()
        assert coordinator.last_plan is committed
        assert coordinator.last_full_plan is committed
        release_journal.set()
        assert await run is committed

    asyncio.run(scenario())


def test_amber_state_change_queues_immediate_replan(tmp_path: Path) -> None:
    class FakeHA:
        async def state_changes(self, entity_ids, on_subscribed=None):
            assert ENTITY["amber_fit"] in entity_ids
            assert ENTITY["mode"] in entity_ids
            if on_subscribed:
                on_subscribed()
            yield {
                "entity_id": ENTITY["amber_fit"],
                "old_state": {"state": "0.01"},
                "new_state": {"state": "0.91"},
            }
            await asyncio.Event().wait()

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        watcher = asyncio.create_task(coordinator._watch_state_changes())
        await asyncio.wait_for(coordinator._replan.wait(), timeout=0.2)
        trigger, received_at, received_monotonic = coordinator._take_pending_trigger()
        assert trigger == f"ha_state_changed:{ENTITY['amber_fit']}"
        assert received_at is not None
        assert received_monotonic is not None
        assert coordinator.last_price_event_at is not None
        assert coordinator.state_stream_status == "connected"
        revision, entity_id, _, _ = coordinator._fast_events.get_nowait()
        assert revision == 1
        assert entity_id == ENTITY["amber_fit"]
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    asyncio.run(scenario())


def test_amber_interval_rollover_is_relevant_even_when_numeric_price_is_unchanged() -> None:
    event = {
        "old_state": {
            "state": "0.16",
            "attributes": {
                "start_time": "2026-08-11T12:00:00+10:00",
                "end_time": "2026-08-11T12:05:00+10:00",
            },
        },
        "new_state": {
            "state": "0.16",
            "attributes": {
                "start_time": "2026-08-11T12:05:00+10:00",
                "end_time": "2026-08-11T12:10:00+10:00",
            },
        },
    }

    assert Coordinator._state_value(event, "old_state") == Coordinator._state_value(
        event, "new_state"
    )
    assert Coordinator._price_fingerprint(
        event, "old_state"
    ) != Coordinator._price_fingerprint(event, "new_state")


def test_soc_freshness_uses_same_integration_heartbeat_not_unchanged_soc_timestamp(
    tmp_path: Path,
) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    async def scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        observed_at = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
        observed_monotonic = 1_000.0
        for entity_id in FAST_FRESHNESS_ENTITIES:
            coordinator._cache_state(
                entity_id,
                {
                    "entity_id": entity_id,
                    "state": "50",
                    "last_reported": observed_at.isoformat(),
                    "last_updated": (observed_at - timedelta(hours=1)).isoformat(),
                },
                received_at=observed_at,
                received_monotonic=observed_monotonic,
            )
        coordinator._cache_state(
            ENTITY["battery_soc"],
            {
                "entity_id": ENTITY["battery_soc"],
                "state": "100",
                # An unchanged SOC value can retain an old report time even
                # while the same SAJ integration continues polling normally.
                "last_reported": (observed_at - timedelta(minutes=90)).isoformat(),
            },
            received_at=observed_at,
            received_monotonic=observed_monotonic,
        )

        health = coordinator._actuation_telemetry_health(observed_monotonic)
        soc_entity_age = coordinator._cached_state_age(
            {ENTITY["battery_soc"]}, observed_monotonic
        )

        assert health.soc_source_heartbeat_age_seconds == 0.0
        assert health.pv_age_seconds == 0.0
        assert health.load_age_seconds == 0.0
        assert soc_entity_age == 90 * 60
        assert ENTITY["battery_soc"] not in FAST_FRESHNESS_ENTITIES
        assert ENTITY["battery_soc_heartbeat"] in FAST_FRESHNESS_ENTITIES
        assert ENTITY["battery_usable"] not in FAST_FRESHNESS_ENTITIES

    asyncio.run(scenario())


def test_full_plan_uses_newer_websocket_value_with_its_cache_freshness(
    tmp_path: Path,
) -> None:
    observed_at = datetime.now(timezone.utc)
    interval_start = observed_at.replace(
        minute=observed_at.minute - observed_at.minute % 5,
        second=0,
        microsecond=0,
    )
    price_attributes = {
        "start_time": interval_start.isoformat(),
        "end_time": (interval_start + timedelta(minutes=5)).isoformat(),
    }
    reported = observed_at.isoformat()
    get_states = [
        {
            "entity_id": ENTITY["amber_fit"],
            "state": "0.30",
            "attributes": price_attributes,
            "last_reported": reported,
        },
        {
            "entity_id": ENTITY["amber_import"],
            "state": "0.16",
            "attributes": price_attributes,
            "last_reported": reported,
        },
        {
            "entity_id": ENTITY["battery_soc"],
            "state": "80",
            "last_reported": reported,
        },
        {
            "entity_id": ENTITY["battery_soc_heartbeat"],
            "state": "0",
            "last_reported": reported,
        },
        {
            "entity_id": ENTITY["pv_power"],
            "state": "0",
            "last_reported": reported,
        },
        {
            "entity_id": ENTITY["home_load"],
            "state": "1000",
            "last_reported": reported,
        },
        {"entity_id": ENTITY["battery_usable"], "state": "47"},
        {"entity_id": ENTITY["mode"], "state": "Active"},
        {"entity_id": ENTITY["battery_control"], "state": "on"},
        {"entity_id": ENTITY["rollout_approved"], "state": "on"},
        {"entity_id": ENTITY["manual_override"], "state": "off"},
        {"entity_id": ENTITY["ev_trip"], "state": "No trip"},
        {"entity_id": ENTITY["ev_soc"], "state": "40"},
        {"entity_id": ENTITY["ev_limit"], "state": "80"},
    ]

    class RacingHA:
        coordinator: Coordinator

        async def states(self):
            now = datetime.now(timezone.utc)
            self.coordinator._cache_state(
                ENTITY["battery_soc_heartbeat"],
                {
                    "entity_id": ENTITY["battery_soc_heartbeat"],
                    "state": "unavailable",
                    "last_reported": now.isoformat(),
                },
                received_at=now,
                received_monotonic=asyncio.get_running_loop().time(),
            )
            return get_states

        async def publish_state(self, *_args, **_kwargs) -> None:
            return None

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        ha = RacingHA()
        coordinator = Coordinator(
            Settings(data_dir=tmp_path, horizon_hours=4),
            ha=ha,
        )
        ha.coordinator = coordinator

        plan = await coordinator.run_once()

        assert plan.actuation_allowed is False
        assert any(
            "soc-source heartbeat is unavailable" in warning.lower()
            for warning in plan.warnings
        )

    asyncio.run(scenario())


def test_fast_worker_survives_one_event_failure(tmp_path: Path) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    async def scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        now = datetime.now(timezone.utc)
        plan = service_plan(now)
        coordinator.last_full_plan = plan

        class FakeOptimizer:
            @staticmethod
            def build_fast_price_plan(*_args, **_kwargs) -> Plan:
                return plan

        coordinator.optimizer = FakeOptimizer()
        first_attempt = asyncio.Event()
        recovered = asyncio.Event()
        publish_calls = 0

        async def flaky_publish(*_args, **_kwargs) -> bool:
            nonlocal publish_calls
            publish_calls += 1
            if publish_calls == 1:
                first_attempt.set()
                raise RuntimeError("transient Home Assistant publish failure")
            recovered.set()
            return True

        async def no_record(_plan: Plan) -> None:
            return None

        coordinator._publish_plan = flaky_publish
        coordinator._record_plan_async = no_record
        worker = asyncio.create_task(coordinator._run_fast_dispatch())
        loop = asyncio.get_running_loop()
        coordinator._dispatch_revision = 1
        await coordinator._fast_events.put((1, ENTITY["amber_fit"], now, loop.time()))
        await asyncio.wait_for(first_attempt.wait(), timeout=1.0)
        coordinator._dispatch_revision = 2
        await coordinator._fast_events.put((2, ENTITY["amber_fit"], now, loop.time()))
        await asyncio.wait_for(recovered.wait(), timeout=1.0)
        await asyncio.wait_for(coordinator._fast_events.join(), timeout=1.0)

        assert worker.done() is False
        assert publish_calls == 2
        assert coordinator.fast_dispatch_error is None
        assert coordinator.last_plan is plan
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

    asyncio.run(scenario())


def test_concurrent_plan_records_use_serialized_unique_temp_files(tmp_path: Path) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    async def scenario() -> None:
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        start = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
        first = service_plan(start, plan_id="first")
        second = service_plan(start + timedelta(seconds=1), plan_id="second")

        await asyncio.gather(
            coordinator._record_plan_async(first),
            coordinator._record_plan_async(second),
        )

        latest = json.loads((tmp_path / "latest-plan.json").read_text())
        journal = tmp_path / "plans" / "2026-08-11.jsonl"
        assert latest["plan_id"] == "second"
        assert len(journal.read_text().splitlines()) == 2
        assert list(tmp_path.glob("*.tmp")) == []

    asyncio.run(scenario())


def test_external_requirements_replan_but_actuator_feedback_does_not(tmp_path: Path) -> None:
    assert ENTITY["ev_charger"] == "switch.tesla_ble_039d9c_charger"
    assert ENTITY["ev_limit"] == "number.tesla_ble_039d9c_charging_limit"
    assert ENTITY["ev_charge_limit"] == "number.tesla_ble_039d9c_charging_limit"

    async def scenario(entity_id: str) -> None:
        class FakeHA:
            async def state_changes(self, entity_ids, on_subscribed=None):
                assert entity_id in entity_ids
                if on_subscribed:
                    on_subscribed()
                yield {
                    "entity_id": entity_id,
                    "old_state": {"state": "off"},
                    "new_state": {"state": "on"},
                }
                await asyncio.Event().wait()

            async def close(self) -> None:
                return None

        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        watcher = asyncio.create_task(coordinator._watch_state_changes())
        await asyncio.wait_for(coordinator._replan.wait(), timeout=0.2)
        trigger, _, _ = coordinator._take_pending_trigger()
        assert trigger == f"ha_state_changed:{entity_id}"
        assert coordinator._fast_events.empty()
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    assert ENTITY["ev_soc"] in EV_PHYSICAL_ENTITIES
    assert ENTITY["ev_power_local"] in EV_PHYSICAL_ENTITIES
    assert ENTITY["ev_charger"] in EV_PHYSICAL_ENTITIES
    assert ENTITY["hot_water_active"] in HOT_WATER_PHYSICAL_ENTITIES
    asyncio.run(scenario(ENTITY["ev_soc"]))
    asyncio.run(scenario(ENTITY["hot_water_satisfied"]))

    async def actuator_feedback_is_cached_without_replan() -> None:
        class FakeHA:
            async def state_changes(self, entity_ids, on_subscribed=None):
                assert ENTITY["hot_water_active"] in entity_ids
                if on_subscribed:
                    on_subscribed()
                yield {
                    "entity_id": ENTITY["hot_water_active"],
                    "old_state": {"state": "off"},
                    "new_state": {"state": "on"},
                }
                await asyncio.Event().wait()

            async def close(self) -> None:
                return None

        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
        watcher = asyncio.create_task(coordinator._watch_state_changes())
        await asyncio.sleep(0.05)
        assert coordinator._replan.is_set() is False
        assert ENTITY["hot_water_active"] in coordinator._cached_states
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    asyncio.run(actuator_feedback_is_cached_without_replan())


def test_dashboard_minimum_sell_price_triggers_immediate_replan() -> None:
    assert ENTITY["min_sell_price"] in CONTROL_ENTITIES


def test_physical_power_fingerprint_triggers_edges_not_running_noise() -> None:
    running_change = {
        "old_state": {"state": "3700"},
        "new_state": {"state": "3890"},
    }
    start = {
        "old_state": {"state": "0"},
        "new_state": {"state": "3700"},
    }

    assert Coordinator._physical_fingerprint(
        ENTITY["hot_water_power"], running_change, "old_state"
    ) == Coordinator._physical_fingerprint(
        ENTITY["hot_water_power"], running_change, "new_state"
    )
    assert Coordinator._physical_fingerprint(
        ENTITY["hot_water_power"], start, "old_state"
    ) != Coordinator._physical_fingerprint(
        ENTITY["hot_water_power"], start, "new_state"
    )


def test_readiness_rejects_failed_stale_and_expired_plans(tmp_path: Path) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    coordinator = Coordinator(
        Settings(data_dir=tmp_path, readiness_max_age_seconds=600),
        ha=FakeHA(),
    )
    coordinator.state_stream_status = "connected"
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert coordinator.readiness(now) == (False, "no successful plan yet")

    coordinator.last_plan = service_plan(now)
    coordinator.last_success = now
    assert coordinator.readiness(now + timedelta(minutes=6)) == (
        False,
        "published plan has expired",
    )

    coordinator.last_plan.valid_until = now + timedelta(hours=1)
    ready, reason = coordinator.readiness(now + timedelta(minutes=11))
    assert ready is False
    assert "stale" in reason

    coordinator.last_success = now
    coordinator.last_error = "boom"
    ready, reason = coordinator.readiness(now)
    assert ready is False
    assert "failed" in reason


def test_readiness_requires_live_immediate_price_dispatch_pipeline(tmp_path: Path) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    coordinator = Coordinator(Settings(data_dir=tmp_path), ha=FakeHA())
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    coordinator.last_plan = service_plan(now)
    coordinator.last_success = now

    coordinator.state_stream_status = "retrying"
    ready, reason = coordinator.readiness(now)
    assert ready is False
    assert "state stream" in reason

    coordinator.state_stream_status = "connected"
    coordinator.fast_dispatch_error = "worker failed"
    ready, reason = coordinator.readiness(now)
    assert ready is False
    assert "immediate price dispatch" in reason


def test_plan_journal_prunes_retention_and_compacts_fast_dispatch(tmp_path: Path) -> None:
    class FakeHA:
        async def close(self) -> None:
            return None

    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    old = plan_dir / "2026-08-16.jsonl"
    keep = plan_dir / "2026-08-17.jsonl"
    old.write_text("old\n")
    keep.write_text("keep\n")
    coordinator = Coordinator(
        Settings(data_dir=tmp_path, journal_retention_days=2),
        ha=FakeHA(),
    )
    plan = service_plan(
        datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc),
        plan_id="eop-fast-20260818T220000-test",
    )
    plan.intervals = plan.intervals * 3

    coordinator._record_plan(plan)

    assert old.exists() is False
    assert keep.exists() is False
    compressed_keep = plan_dir / "2026-08-17.jsonl.gz"
    assert compressed_keep.exists() is True
    with gzip.open(compressed_keep, "rt") as handle:
        assert handle.read() == "keep\n"
    record = json.loads((plan_dir / "2026-08-18.jsonl").read_text())
    assert len(record["intervals"]) == 1
    assert record["journal"]["record_type"] == "fast_dispatch"
    assert record["journal"]["outcome_status"] == "pending"


def test_hot_water_publish_includes_control_mode_and_per_day_schedule(tmp_path: Path) -> None:
    class PublishingHA:
        def __init__(self) -> None:
            self.attributes: dict[str, dict] = {}

        async def publish_state(self, entity_id, _state, attributes) -> None:
            self.attributes[entity_id] = attributes

        async def close(self) -> None:
            return None

    async def scenario() -> dict:
        publisher = PublishingHA()
        coordinator = Coordinator(Settings(data_dir=tmp_path), ha=publisher)
        start = datetime(2026, 8, 18, 3, 0, tzinfo=timezone.utc)
        plan = service_plan(start)
        plan.hot_water_command = "on"
        plan.hot_water_control_mode = "solar_surplus"
        plan.intervals[0].hot_water_kw = 3.7
        plan.intervals[0].hot_water_control_mode = "solar_surplus"
        await coordinator._publish_plan(plan)
        return publisher.attributes["sensor.energy_optimizer_hot_water"]

    attributes = asyncio.run(scenario())
    assert attributes["control_mode"] == "solar_surplus"
    assert attributes["daily_schedule"][0]["expected_hours"] == 0.08
