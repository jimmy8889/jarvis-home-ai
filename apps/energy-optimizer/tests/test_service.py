from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from energy_optimizer.config import ENTITY, Settings
from energy_optimizer.models import DispatchInterval, Plan
from energy_optimizer.service import (
    FAST_FRESHNESS_ENTITIES,
    Coordinator,
    dashboard_plan_attributes,
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


def test_dashboard_plan_attributes_contains_full_compact_horizon(tmp_path: Path) -> None:
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
        reason="test",
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
        intervals=intervals,
    )

    attributes = dashboard_plan_attributes(plan)

    assert len(attributes["intervals"]) == 72
    assert set(attributes["intervals"][0]) == {
        "start",
        "duration_minutes",
        "solar_kw",
        "solar_low_kw",
        "load_kw",
        "hot_water_kw",
        "ev_kw",
        "import_price",
        "export_price",
        "battery_kw",
        "site_grid_kw",
        "soc_end_pct",
    }
    assert attributes["intervals"][0]["duration_minutes"] == 30
    assert "pv_curtailment_kw" not in attributes["intervals"][0]
    assert attributes["ev_power_target_kw"] == 0.0
    assert attributes["ev_charge_source"] == "none"
    assert attributes["ev_solar_energy_kwh"] == 0.0
    assert attributes["ev_fallback_energy_kwh"] == 0.0

    class PublishingHA:
        def __init__(self) -> None:
            self.published: list[str] = []

        async def publish_state(self, entity_id, state, attributes) -> None:
            self.published.append(entity_id)

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
    assert publisher.published[-1] == "sensor.energy_optimizer_plan"
    assert "sensor.energy_optimizer_battery_power_target" in publisher.published[:-1]

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
    assert "sensor.energy_optimizer_plan" not in stale_publisher.published


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
        await asyncio.wait_for(first_attempt.wait(), timeout=0.2)
        coordinator._dispatch_revision = 2
        await coordinator._fast_events.put((2, ENTITY["amber_fit"], now, loop.time()))
        await asyncio.wait_for(recovered.wait(), timeout=0.2)
        await asyncio.wait_for(coordinator._fast_events.join(), timeout=0.2)

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
