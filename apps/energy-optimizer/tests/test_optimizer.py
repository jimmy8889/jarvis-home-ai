from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.config import ENTITY, Settings
from energy_optimizer.models import DispatchInterval, Plan, Slot
from energy_optimizer.optimizer import EnergyOptimizer
from energy_optimizer.state import LearningState


BRISBANE = ZoneInfo("Australia/Brisbane")


def optimizer(tmp_path: Path) -> EnergyOptimizer:
    settings = Settings(data_dir=tmp_path, horizon_hours=4)
    return EnergyOptimizer(settings, LearningState(tmp_path / "state.json"))


def slots(now: datetime, *, fit: float, buy: float, solar: float = 0.0, load: float = 0.2, count: int = 8):
    return [Slot(
        start=now + timedelta(minutes=30 * index),
        duration_h=0.5,
        solar_kw=solar,
        solar_low_kw=solar,
        solar_high_kw=solar,
        load_kw=load,
        import_price=buy,
        export_price=fit,
        price_source="amber",
    ) for index in range(count)]


def ev_states(*, soc: float, departure: datetime) -> dict[str, dict[str, str]]:
    return {
        ENTITY["ev_trip"]: {"state": "No trip"},
        ENTITY["ev_soc"]: {"state": str(soc)},
        ENTITY["ev_limit"]: {"state": "80"},
        ENTITY["ev_plugged"]: {"state": "on"},
        ENTITY["ev_home"]: {"state": "home"},
        ENTITY["ev_departure"]: {"state": departure.isoformat()},
    }


def raw_state(entity_id: str, state: str) -> dict[str, str]:
    return {"entity_id": entity_id, "state": state}


def fast_base_plan(now: datetime, *, future_fit: float = 0.08) -> Plan:
    intervals = [DispatchInterval(
        start=now + timedelta(minutes=5 * index),
        duration_minutes=5,
        solar_kw=0.0,
        solar_low_kw=0.0,
        load_kw=1.0,
        hot_water_kw=0.0,
        ev_kw=0.0,
        import_price=0.16,
        export_price=future_fit,
        battery_kw=0.0,
        site_grid_kw=1.0,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=80.0,
        cost=0.0,
        price_source="amber",
    ) for index in range(12)]
    return Plan(
        plan_id="full-base",
        generated_at=now - timedelta(seconds=1),
        valid_until=now + timedelta(minutes=10),
        mode="active",
        actuation_allowed=True,
        action="idle",
        reason="base",
        confidence=0.8,
        battery_power_target_kw=0.0,
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
        morning_takeover=now + timedelta(hours=8),
        evening_crossover=None,
        expected_cost=0.0,
        expected_revenue=0.0,
        expected_wear_cost=0.0,
        intervals=intervals,
    )


def fast_states(now: datetime, *, fit: str, soc: str = "80") -> list[dict]:
    price_attributes = {
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(minutes=5)).isoformat(),
    }
    return [
        {"entity_id": ENTITY["amber_fit"], "state": fit, "attributes": price_attributes},
        {"entity_id": ENTITY["amber_import"], "state": "0.16", "attributes": price_attributes},
        raw_state(ENTITY["battery_soc"], soc),
        raw_state(ENTITY["battery_usable"], "47"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
    ]


def test_eight_cent_wear_blocks_low_value_export(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=0.08, buy=0.0), 80, 47, None)
    assert result[0].battery_kw <= 0


def test_high_fit_exports_but_never_crosses_five_percent_floor(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=0.30, buy=0.0), 80, 47, None)
    assert result[0].battery_kw > 0
    assert min(item.soc_end_pct for item in result) >= 5.0
    assert max(item.soc_end_pct for item in result) <= 100.0


def test_negative_fit_curtails_excess_solar(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=-0.05, buy=0.03, solar=10, load=1), 100, 47, None)
    assert result[0].site_grid_kw == 0
    assert result[0].pv_curtailment_kw > 8


def test_profitable_grid_arbitrage_charges_before_expensive_period(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.03, count=8)
    for item in plan_slots[3:]:
        item.import_price = 0.35
        item.load_kw = 5.0
    result = opt._dispatch(plan_slots, 20, 47, None)
    assert any(item.battery_kw < -0.5 for item in result[:3])
    assert any(item.battery_kw > 0.5 for item in result[3:])


def test_hot_water_is_three_point_seven_kw_and_six_half_hour_blocks(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=8.0, load=1.0, count=16)
    states = {"sensor.hot_water_runtime_today": {"state": "0"}}
    opt._schedule_hot_water(plan_slots, states, now, datetime(2026, 8, 11, 16, 30, tzinfo=BRISBANE))
    selected = [item for item in plan_slots if item.hot_water_kw > 0]
    assert len(selected) == 6
    assert {item.hot_water_kw for item in selected} == {3.7}


def test_hot_water_five_minute_prices_are_grouped_into_minimum_15_minute_runs(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BRISBANE)
    plan_slots = [Slot(
        start=now + timedelta(minutes=5 * index),
        duration_h=5 / 60,
        solar_kw=8.0,
        solar_low_kw=8.0,
        solar_high_kw=8.0,
        load_kw=1.0,
        import_price=0.05,
        export_price=(0.01, 0.40, 0.02, 0.30)[index // 3],
        price_source="amber",
    ) for index in range(12)]
    states = {ENTITY["hot_water_runtime"]: {"state": "2.5"}}

    opt._schedule_hot_water(plan_slots, states, now, now + timedelta(hours=2))

    selected = [index for index, item in enumerate(plan_slots) if item.hot_water_kw > 0]
    assert len(selected) == 6
    runs: list[list[int]] = []
    for index in selected:
        if not runs or index != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(index)
    assert all(len(run) >= 3 for run in runs)
    assert sum(plan_slots[index].duration_h for index in selected) >= 0.5


def test_evening_full_target_is_enforced_when_low_solar_can_fill_it(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=-0.05, buy=0.30, solar=20.0, load=1.0, count=8)
    evening = now + timedelta(hours=3)
    result = opt._dispatch(plan_slots, 50, 47, evening)
    at_crossover = next(item for item in result if item.start + timedelta(minutes=30) >= evening)
    assert at_crossover.soc_end_pct >= 99.0


def test_morning_target_is_enforced_when_discharge_has_value_and_solar_can_refill(tmp_path):
    opt = EnergyOptimizer(
        Settings(data_dir=tmp_path, battery_capacity_kwh=10.0),
        LearningState(tmp_path / "state.json"),
    )
    now = datetime(2026, 8, 11, 0, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.30, buy=0.20, load=1.0, count=36)
    for item in plan_slots[14:]:
        item.solar_kw = item.solar_low_kw = item.solar_high_kw = 8.0
        item.export_price = 0.06
        item.import_price = 0.30
    morning = now + timedelta(hours=7)
    evening = now + timedelta(hours=16)

    result = opt._dispatch(plan_slots, 90, 10, evening, morning)
    at_takeover = next(item for item in result if item.start + timedelta(minutes=30) >= morning)

    assert 5.0 <= at_takeover.soc_end_pct <= 10.0


def test_morning_target_does_not_destroy_value_on_poor_price_day(tmp_path):
    opt = EnergyOptimizer(
        Settings(data_dir=tmp_path, battery_capacity_kwh=10.0),
        LearningState(tmp_path / "state.json"),
    )
    now = datetime(2026, 8, 11, 0, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, load=0.2, count=36)
    for item in plan_slots[14:]:
        item.solar_kw = item.solar_low_kw = item.solar_high_kw = 8.0
        item.import_price = 0.30
    morning = now + timedelta(hours=7)
    evening = now + timedelta(hours=16)

    result = opt._dispatch(plan_slots, 90, 10, evening, morning)
    at_takeover = next(item for item in result if item.start + timedelta(minutes=30) >= morning)

    assert at_takeover.soc_end_pct > 10.0


def test_terminal_reserve_does_not_create_false_import_tail(tmp_path):
    opt = EnergyOptimizer(
        Settings(data_dir=tmp_path, battery_capacity_kwh=47.0),
        LearningState(tmp_path / "state.json"),
    )
    now = datetime(2026, 8, 11, 15, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.36, load=1.67, count=72)
    for item in plan_slots[12:]:
        item.import_price = 0.16
    for item in plan_slots[32:50]:
        item.solar_kw = item.solar_low_kw = item.solar_high_kw = 10.0

    result = opt._dispatch(plan_slots, 100, 47, None, now + timedelta(hours=16))
    imported_kwh = sum(max(0.0, item.site_grid_kw) * 0.5 for item in result)

    assert imported_kwh < 0.25
    assert 15.0 <= result[-1].soc_end_pct <= 60.0


def test_active_approved_battery_control_is_authorized_without_shadow_wait(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    price_attributes = {
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(minutes=5)).isoformat(),
    }
    base_states = [
        {
            "entity_id": ENTITY["amber_fit"],
            "state": "0.10",
            "attributes": price_attributes,
        },
        {
            "entity_id": ENTITY["amber_import"],
            "state": "0.16",
            "attributes": price_attributes,
        },
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    plan = opt.build_plan(base_states, now)

    assert plan.actuation_allowed is True
    assert not any("shadow validation gate" in warning.lower() for warning in plan.warnings)

    gated_states = [
        (ENTITY["mode"], "Shadow"),
        (ENTITY["battery_control"], "off"),
        (ENTITY["rollout_approved"], "off"),
        (ENTITY["manual_override"], "on"),
    ]
    for entity_id, value in gated_states:
        states = [item.copy() for item in base_states]
        next(item for item in states if item["entity_id"] == entity_id)["state"] = value
        assert opt.build_plan(states, now).actuation_allowed is False


def test_full_plan_cannot_actuate_without_valid_current_amber_interval(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 2, 30, tzinfo=BRISBANE)
    states = [
        {"entity_id": ENTITY["amber_fit"], "state": "0.91", "attributes": {}},
        {"entity_id": ENTITY["amber_import"], "state": "0.44", "attributes": {}},
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
        raw_state(ENTITY["battery_soc"], "80"),
        raw_state(ENTITY["battery_usable"], "47"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    plan = opt.build_plan(states, now)

    assert plan.actuation_allowed is False
    assert plan.intervals[0].price_source != "amber_live"
    assert any("current amber" in warning.lower() for warning in plan.warnings)


def test_full_plan_expires_at_current_settlement_interval_end(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 2, 30, tzinfo=BRISBANE)
    interval_start = now.replace(minute=0, second=0, microsecond=0)
    interval_end = interval_start + timedelta(minutes=5)
    attributes = {
        "start_time": interval_start.isoformat(),
        "end_time": interval_end.isoformat(),
    }
    states = [
        {"entity_id": ENTITY["amber_fit"], "state": "0.30", "attributes": attributes},
        {"entity_id": ENTITY["amber_import"], "state": "0.16", "attributes": attributes},
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
        raw_state(ENTITY["battery_soc"], "80"),
        raw_state(ENTITY["battery_usable"], "47"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    plan = opt.build_plan(states, now)

    assert plan.actuation_allowed is True
    assert plan.valid_until == interval_end
    assert plan.valid_until <= plan.generated_at + timedelta(minutes=10)


def test_three_phase_ev_current_conversion_matches_observed_supply(tmp_path):
    opt = optimizer(tmp_path)

    assert opt._ev_power_for_amps(6) == pytest.approx(4.446)
    assert opt._ev_power_for_amps(16) == pytest.approx(11.856)
    assert opt._ev_amps_for_power(11.856, round_up=True) == 16
    assert opt._ev_amps_for_power(4.446, round_up=True) == 6


def test_ev_uses_negative_fit_direct_solar_without_battery_or_grid_support(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 11, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.20, buy=0.05, solar=7.0, load=1.0, count=4)
    plan_slots[1].export_price = -0.05
    states = ev_states(soc=38.0, departure=now + timedelta(hours=3))

    schedule = opt._schedule_ev(plan_slots, states, now)

    assert plan_slots[0].ev_kw == 0.0
    assert plan_slots[1].ev_charge_source == "direct_solar"
    assert plan_slots[1].ev_charge_amps == 6
    assert plan_slots[1].ev_power_target_kw == pytest.approx(4.446)
    conservative_surplus = plan_slots[1].solar_low_kw - plan_slots[1].load_kw - plan_slots[1].hot_water_kw
    assert plan_slots[1].ev_power_target_kw <= conservative_surplus
    assert schedule.solar_energy_kwh == pytest.approx(schedule.required_kwh)
    assert schedule.fallback_energy_kwh == 0.0


def test_ev_adds_lowest_cost_deadline_fallback_only_after_solar_shortfall(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 11, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.20, solar=0.0, load=1.0, count=3)
    plan_slots[0].solar_kw = plan_slots[0].solar_low_kw = plan_slots[0].solar_high_kw = 7.0
    plan_slots[2].import_price = 0.01
    states = ev_states(soc=30.0, departure=now + timedelta(hours=2))

    schedule = opt._schedule_ev(plan_slots, states, now)

    direct_solar_capacity = opt._ev_power_for_amps(8) * plan_slots[0].duration_h
    assert schedule.solar_energy_kwh == pytest.approx(direct_solar_capacity)
    assert schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh - direct_solar_capacity)
    assert plan_slots[0].ev_charge_source == "direct_solar"
    assert plan_slots[1].ev_kw == 0.0
    assert plan_slots[2].ev_charge_source == "deadline_fallback"
    assert schedule.solar_energy_kwh + schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh)


def test_fast_live_high_fit_immediately_requests_full_safe_discharge(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit="0.55"),
        now=now,
    )

    assert plan.plan_id.startswith("eop-fast-")
    assert plan.actuation_allowed is True
    assert plan.action == "discharge_export"
    assert plan.battery_power_target_kw == 28.0
    assert plan.site_export_target_kw == 27.0
    assert plan.intervals[0].export_price == 0.55
    assert plan.intervals[0].soc_end_pct >= 5.0
    assert plan.valid_until == now + timedelta(minutes=5)


@pytest.mark.parametrize("fit", ["0.05", "-0.05", "unavailable"])
def test_fast_low_negative_or_malformed_fit_never_forces_discharge(tmp_path, fit):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit=fit),
        now=now,
    )

    assert plan.battery_power_target_kw == 0.0
    assert plan.action != "discharge_export"
    if fit == "-0.05":
        assert plan.action == "curtail_pv"
    if fit == "unavailable":
        assert plan.actuation_allowed is False


def test_fast_stale_state_and_near_floor_soc_are_fail_safe(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)

    stale = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.55"),
        now=now,
        state_age_seconds=331,
    )
    near_floor = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.55", soc="5.2"),
        now=now,
        soc_age_seconds=30,
    )

    assert stale.actuation_allowed is False
    assert stale.battery_power_target_kw == 0.0
    assert near_floor.battery_power_target_kw == 0.0
    assert near_floor.intervals[0].soc_end_pct >= 5.0


def test_fast_missing_or_stale_price_window_metadata_cannot_discharge(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    missing = fast_states(now, fit="0.55")
    next(item for item in missing if item["entity_id"] == ENTITY["amber_fit"])[
        "attributes"
    ] = {}
    stale = fast_states(now, fit="0.55")
    for item in stale:
        if item["entity_id"] in {ENTITY["amber_fit"], ENTITY["amber_import"]}:
            item["attributes"] = {
                "start_time": (now - timedelta(minutes=10)).isoformat(),
                "end_time": (now - timedelta(minutes=5)).isoformat(),
            }

    missing_plan = opt.build_fast_price_plan(base, missing, now=now)
    stale_plan = opt.build_fast_price_plan(base, stale, now=now)

    for plan in (missing_plan, stale_plan):
        assert plan.actuation_allowed is False
        assert plan.battery_power_target_kw == 0.0
        assert plan.action != "discharge_export"


def test_fast_dispatch_preserves_more_valuable_allocated_future_fit(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.80)
    base.intervals[2].battery_kw = 28.0
    base.intervals[2].site_grid_kw = -27.0

    plan = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.55"),
        now=now,
    )

    assert plan.battery_power_target_kw == 0.0
    assert plan.action != "discharge_export"


def test_fast_dispatch_keeps_already_planned_export_above_wear_cost(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0

    plan = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.09"),
        now=now,
    )

    assert plan.battery_power_target_kw == 10.0
    assert plan.action == "discharge_export"
