from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.config import ENTITY, Settings
from energy_optimizer.models import DispatchInterval, Plan, Slot, TelemetryHealth
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


def ev_states(
    *,
    soc: float,
    departure: datetime,
    trip: str = "No trip",
) -> dict[str, dict[str, str]]:
    return {
        ENTITY["ev_trip"]: {"state": trip},
        ENTITY["ev_soc"]: {"state": str(soc)},
        ENTITY["ev_limit"]: {"state": "80"},
        ENTITY["ev_plugged"]: {"state": "on"},
        ENTITY["ev_home"]: {"state": "home"},
        ENTITY["ev_departure"]: {"state": departure.isoformat()},
    }


def raw_state(entity_id: str, state: str) -> dict[str, str]:
    return {"entity_id": entity_id, "state": state}


def measured_state(entity_id: str, state: str, when: datetime) -> dict:
    return {
        "entity_id": entity_id,
        "state": state,
        "last_reported": when.isoformat(),
    }


def test_two_plane_poa_potential_corrects_near_term_forecast_and_detects_curtailment(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=BRISBANE)
    states = {
        item["entity_id"]: item
        for item in [
            measured_state(ENTITY["solar_expected_north"], "5900", now),
            measured_state(ENTITY["solar_expected_south"], "6195", now),
            raw_state(ENTITY["solcast_power_now"], "18000"),
            raw_state(ENTITY["pv_power"], "4000"),
            raw_state(ENTITY["amber_fit"], "-0.03"),
            raw_state(ENTITY["export_enabled"], "off"),
        ]
    }

    potential, actual, curtailed, correction, source = opt._solar_potential_context(states, now)

    assert potential == pytest.approx(12.095)
    assert actual == pytest.approx(4.0)
    assert curtailed == pytest.approx(8.095)
    assert correction == pytest.approx(12.095 / 18.0)
    assert source == "local_two_plane_poa"


def test_two_plane_poa_signal_fails_safely_when_either_plane_is_stale(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=BRISBANE)
    old = now - timedelta(minutes=10)
    states = {
        item["entity_id"]: item
        for item in [
            measured_state(ENTITY["solar_expected_north"], "5900", now),
            measured_state(ENTITY["solar_expected_south"], "6195", old),
            raw_state(ENTITY["pv_power"], "4000"),
        ]
    }

    potential, actual, curtailed, correction, source = opt._solar_potential_context(states, now)

    assert (potential, actual, curtailed, correction, source) == (
        4.0,
        4.0,
        0.0,
        1.0,
        "actual_fallback",
    )


def test_low_actual_pv_is_not_called_curtailment_while_export_is_allowed_at_positive_fit(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=BRISBANE)
    states = {
        item["entity_id"]: item
        for item in [
            measured_state(ENTITY["solar_expected_north"], "5900", now),
            measured_state(ENTITY["solar_expected_south"], "6195", now),
            raw_state(ENTITY["solcast_power_now"], "18000"),
            raw_state(ENTITY["pv_power"], "4000"),
            raw_state(ENTITY["amber_fit"], "0.12"),
            raw_state(ENTITY["export_enabled"], "on"),
        ]
    }

    assert opt._solar_potential_context(states, now)[2] == 0.0


def test_curtailment_independent_learning_integrates_available_power(tmp_path):
    learning = LearningState(tmp_path / "state.json")
    start = datetime(2026, 8, 12, 12, 0, tzinfo=BRISBANE)
    learning.observe_solar_power(start, actual_kw=4.0, potential_kw=12.0, curtailed=True)
    learning.observe_solar_power(
        start + timedelta(minutes=5),
        actual_kw=4.0,
        potential_kw=12.0,
        curtailed=True,
    )

    assert learning.data["daily"]["2026-08-12"]["curtailed_kwh"] == pytest.approx(2 / 3, abs=1e-5)


def test_load_learning_normalizes_hot_water_and_ev_power_units(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    states = {
        ENTITY["home_load"]: {
            "state": "6000",
            "attributes": {"unit_of_measurement": "W"},
            "last_reported": now.isoformat(),
        },
        ENTITY["hot_water_power"]: {
            "state": "3700",
            "attributes": {"unit_of_measurement": "W"},
        },
        ENTITY["ev_power"]: {
            "state": "1.0",
            "attributes": {"unit_of_measurement": "kW"},
        },
    }

    opt._update_learning(states, now, (0.0, 0.0, 0.0, 1.0, "actual_fallback"))

    record = opt.learning.data["load_slots"][opt.learning._load_key(now)]
    # 6.0 - 3.7 - 1.0 = 1.3 kW, blended once from the 1.67 kW seed.
    assert record["mean"] == pytest.approx(1.596)
    assert record["count"] == 1


def telemetry_health(
    *,
    heartbeat_age: float | None = 0.0,
    pv_age: float | None = 0.0,
    load_age: float | None = 0.0,
    pv_heartbeat_age: float | None = None,
) -> TelemetryHealth:
    return TelemetryHealth(
        soc_source_heartbeat_age_seconds=heartbeat_age,
        pv_age_seconds=pv_age,
        load_age_seconds=load_age,
        pv_source_heartbeat_age_seconds=pv_heartbeat_age,
    )


def live_telemetry_states(*, soc: str = "80") -> list[dict[str, str]]:
    return [
        raw_state(ENTITY["battery_soc"], soc),
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
    ]


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
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["battery_usable"], "47"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
    ]


def test_eight_cent_wear_blocks_export_but_not_house_supply(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=0.08, buy=0.0), 80, 47, None)
    assert result[0].battery_kw == pytest.approx(0.2)
    assert result[0].site_grid_kw == 0.0


def test_dashboard_minimum_sell_price_only_gates_battery_export(tmp_path):
    opt = optimizer(tmp_path)
    configured, effective = opt._sell_price_threshold({
        ENTITY["min_sell_price"]: {"state": "25"},
    })
    assert configured == pytest.approx(0.25)
    assert effective == pytest.approx(0.25)

    now = datetime(2026, 8, 20, 12, 0, tzinfo=BRISBANE)
    interval = DispatchInterval(
        start=now,
        duration_minutes=5,
        solar_kw=0.0,
        solar_low_kw=0.0,
        load_kw=1.0,
        hot_water_kw=0.0,
        ev_kw=0.0,
        import_price=0.30,
        export_price=0.20,
        battery_kw=10.0,
        site_grid_kw=-9.0,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=78.0,
        cost=0.0,
        price_source="amber_live",
    )
    projected = opt._remove_unprofitable_export_tranches(
        [interval], 47.0, 80.0, effective,
    )
    assert projected[0].battery_kw == 1.0
    assert projected[0].site_grid_kw == 0.0

    # The same floor never curtails solar at a non-negative FIT.
    solar = DispatchInterval(
        start=now,
        duration_minutes=5,
        solar_kw=5.0,
        solar_low_kw=5.0,
        load_kw=1.0,
        hot_water_kw=0.0,
        ev_kw=0.0,
        import_price=0.30,
        export_price=0.01,
        battery_kw=0.0,
        site_grid_kw=-4.0,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=80.0,
        cost=0.0,
        price_source="amber_live",
    )
    solar_result = opt._remove_unprofitable_export_tranches(
        [solar], 47.0, 80.0, effective,
    )[0]
    assert solar_result.site_grid_kw == -4.0
    assert solar_result.pv_curtailment_kw == 0.0


def test_source_forecast_attributes_solar_then_battery_then_grid(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 20, 12, 0, tzinfo=BRISBANE)
    intervals = [
        DispatchInterval(
            start=now,
            duration_minutes=60,
            solar_kw=5.0,
            solar_low_kw=5.0,
            load_kw=2.0,
            hot_water_kw=2.0,
            ev_kw=3.0,
            import_price=0.30,
            export_price=0.20,
            battery_kw=3.0,
            site_grid_kw=-1.0,
            pv_curtailment_kw=0.0,
            soc_start_pct=80.0,
            soc_end_pct=73.0,
            cost=0.0,
            price_source="amber",
        ),
        DispatchInterval(
            start=now + timedelta(hours=1),
            duration_minutes=60,
            solar_kw=0.0,
            solar_low_kw=0.0,
            load_kw=1.0,
            hot_water_kw=1.0,
            ev_kw=1.0,
            import_price=0.30,
            export_price=0.20,
            battery_kw=1.5,
            site_grid_kw=1.5,
            pv_curtailment_kw=0.0,
            soc_start_pct=73.0,
            soc_end_pct=69.0,
            cost=0.0,
            price_source="amber",
        ),
    ]

    summary = opt._source_energy_summary(intervals)

    assert summary["house_total_energy_kwh"] == pytest.approx(3.0)
    assert summary["house_solar_energy_kwh"] == pytest.approx(2.0)
    assert summary["house_battery_energy_kwh"] == pytest.approx(1.0)
    assert summary["house_grid_energy_kwh"] == 0.0
    assert summary["hot_water_solar_energy_kwh"] == pytest.approx(2.0)
    assert summary["hot_water_battery_energy_kwh"] == 0.0
    assert summary["hot_water_grid_energy_kwh"] == pytest.approx(1.0)
    assert summary["ev_solar_energy_kwh"] == pytest.approx(1.0)
    assert summary["ev_battery_energy_kwh"] == pytest.approx(2.5)
    assert summary["ev_grid_energy_kwh"] == pytest.approx(0.5)
    assert summary["battery_export_energy_kwh"] == pytest.approx(1.0)
    assert summary["solar_export_energy_kwh"] == 0.0
    assert summary["total_export_energy_kwh"] == pytest.approx(1.0)


def test_7_085_cent_fit_never_exports_battery_but_may_avoid_higher_import(
    tmp_path,
    monkeypatch,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 17, 0, tzinfo=BRISBANE)
    price_attributes = {
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(minutes=5)).isoformat(),
    }
    full_slots = slots(
        now,
        fit=0.07085,
        buy=0.16,
        solar=0.0,
        load=0.0,
        count=8,
    )
    for slot in full_slots:
        slot.price_source = "amber_live"
    monkeypatch.setattr(
        "energy_optimizer.optimizer.build_slots",
        lambda **_kwargs: full_slots,
    )
    full_states = [
        {
            "entity_id": ENTITY["amber_fit"],
            "state": "0.07085",
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
        raw_state(ENTITY["battery_soc"], "77"),
        raw_state(ENTITY["battery_usable"], "36.19"),
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "0"),
        raw_state(ENTITY["hot_water_runtime"], "3"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "80"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    full_plan = opt.build_plan(
        full_states,
        now,
        telemetry_health=telemetry_health(),
    )

    assert full_plan.actuation_allowed is True
    assert full_plan.battery_mode == "hold"
    assert full_plan.battery_power_target_kw == 0.0
    assert full_plan.battery_discharge_target_kw == 0.0
    assert full_plan.site_export_target_kw == 0.0
    assert full_plan.action != "discharge_export"

    no_load_states = fast_states(now, fit="0.07085", soc="77")
    next(
        item for item in no_load_states if item["entity_id"] == ENTITY["home_load"]
    )["state"] = "0"
    fast_hold = opt.build_fast_price_plan(
        fast_base_plan(now),
        no_load_states,
        now=now,
        telemetry_health=telemetry_health(),
    )
    fast_household = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit="0.07085", soc="77"),
        now=now,
        telemetry_health=telemetry_health(),
    )
    cached_export = fast_base_plan(now)
    cached_export.battery_mode = "export"
    cached_export.battery_power_target_kw = 10.0
    cached_export.battery_discharge_target_kw = 10.0
    cached_export.site_export_target_kw = 9.0
    cached_export.intervals[0].battery_kw = 10.0
    cached_export.intervals[0].site_grid_kw = -9.0
    repriced_cached_export = opt.build_fast_price_plan(
        cached_export,
        fast_states(now, fit="0.07085", soc="77"),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert fast_hold.battery_mode == "hold"
    assert fast_hold.battery_power_target_kw == 0.0
    assert fast_hold.site_export_target_kw == 0.0
    assert fast_hold.action != "discharge_export"
    assert fast_household.battery_mode == "self_consume"
    assert fast_household.battery_power_target_kw == 1.0
    assert fast_household.site_export_target_kw == 0.0
    assert fast_household.action == "self_consumption"
    assert repriced_cached_export.battery_mode == "self_consume"
    assert repriced_cached_export.battery_power_target_kw == 1.0
    assert repriced_cached_export.site_export_target_kw == 0.0
    assert repriced_cached_export.action == "self_consumption"


def test_realistic_36h_high_solar_horizon_never_bundles_below_wear_export(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 18, 24, 6, 300868, tzinfo=BRISBANE)
    horizon_end = now + timedelta(hours=36)
    active_interval_end = datetime(2026, 8, 18, 18, 25, tzinfo=BRISBANE)
    fine_horizon_end = datetime(2026, 8, 18, 19, 20, tzinfo=BRISBANE)
    cursor = now
    plan_slots: list[Slot] = []
    while cursor < horizon_end:
        if cursor < active_interval_end:
            duration_h = (active_interval_end - cursor).total_seconds() / 3600
        elif cursor < fine_horizon_end:
            duration_h = 5 / 60
        else:
            duration_h = 0.5
        duration_h = min(
            duration_h,
            (horizon_end - cursor).total_seconds() / 3600,
        )
        daylight = cursor.date() > now.date() and 8 <= cursor.hour < 16
        plan_slots.append(
            Slot(
                start=cursor,
                duration_h=duration_h,
                solar_kw=15.0 if daylight else 0.0,
                solar_low_kw=8.0 if daylight else 0.0,
                solar_high_kw=18.0 if daylight else 0.0,
                load_kw=1.4,
                import_price=0.3208301 if not daylight else 0.10,
                export_price=0.0706667 if not daylight else 0.01,
                price_source="amber",
            )
        )
        cursor += timedelta(hours=duration_h)

    dispatch = opt._dispatch(
        plan_slots,
        initial_soc_pct=76.0,
        capacity_kwh=47.0,
        evening=datetime(2026, 8, 19, 17, 20, tzinfo=BRISBANE),
        morning=datetime(2026, 8, 19, 7, 20, tzinfo=BRISBANE),
    )

    below_wear = [
        item
        for item in dispatch
        if item.export_price <= opt.settings.battery_wear_per_kwh
    ]
    assert dispatch[0].duration_minutes == pytest.approx(0.895)
    assert dispatch[0].soc_start_pct == 76.0
    assert dispatch[0].battery_kw == pytest.approx(1.4)
    assert dispatch[0].site_grid_kw == pytest.approx(0.0)
    assert any(item.battery_kw > 0 for item in below_wear)
    assert all(item.site_grid_kw >= -1e-6 for item in below_wear if item.battery_kw > 0)
    assert all(item.battery_kw <= max(0.0, item.load_kw - item.solar_kw) + 1e-6 for item in below_wear)
    assert all(
        earlier.soc_end_pct == later.soc_start_pct
        for earlier, later in zip(dispatch, dispatch[1:])
    )


def test_marginal_export_floor_uses_exact_soc_and_covers_flexible_loads(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 18, 24, 6, 300868, tzinfo=BRISBANE)
    partial_minutes = 0.895
    low_fit = DispatchInterval(
        start=now,
        duration_minutes=partial_minutes,
        solar_kw=0.0,
        solar_low_kw=0.0,
        load_kw=1.4,
        hot_water_kw=3.7,
        ev_kw=4.45,
        import_price=0.3208301,
        export_price=0.0706667,
        battery_kw=15.084,
        site_grid_kw=-5.534,
        pv_curtailment_kw=0.0,
        soc_start_pct=76.1,
        soc_end_pct=75.6,
        cost=0.0,
        price_source="amber_live",
    )

    adjusted = opt._remove_unprofitable_export_tranches(
        [low_fit],
        capacity_kwh=47.0,
        initial_soc_pct=76.09,
    )[0]
    battery_eligible_deficit_kw = 1.4 + 4.45
    exact_end_pct = 76.09 - (
        battery_eligible_deficit_kw
        * (partial_minutes / 60)
        / opt.settings.battery_discharge_efficiency
        / 47.0
        * 100
    )

    assert adjusted.battery_kw == pytest.approx(battery_eligible_deficit_kw)
    assert adjusted.site_grid_kw == pytest.approx(3.7)
    assert adjusted.soc_start_pct == 76.1
    assert adjusted.soc_end_pct == round(exact_end_pct, 1) == 75.9

    high_fit = DispatchInterval(
        start=now,
        duration_minutes=5.0,
        solar_kw=0.0,
        solar_low_kw=0.0,
        load_kw=1.4,
        hot_water_kw=3.7,
        ev_kw=4.45,
        import_price=0.3208301,
        export_price=0.30,
        battery_kw=10.0,
        site_grid_kw=-0.45,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=78.0,
        cost=0.0,
        price_source="amber_live",
    )

    unchanged = opt._remove_unprofitable_export_tranches(
        [high_fit],
        capacity_kwh=47.0,
        initial_soc_pct=80.0,
    )[0]

    assert unchanged.battery_kw == pytest.approx(5.85)
    assert unchanged.site_grid_kw == pytest.approx(3.7)


def test_high_fit_exports_but_never_crosses_five_percent_floor(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=0.30, buy=0.0), 80, 47, None)
    assert result[0].battery_kw > 0
    assert min(item.soc_end_pct for item in result) >= 5.0
    assert max(item.soc_end_pct for item in result) <= 100.0


def test_limited_battery_is_price_shaped_then_live_high_fit_uses_full_output(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    plan_slots = [
        Slot(
            start=now + timedelta(minutes=5 * index),
            duration_h=5 / 60,
            solar_kw=0.0,
            solar_low_kw=0.0,
            solar_high_kw=0.0,
            load_kw=0.0,
            import_price=0.0,
            export_price=fit,
            price_source="amber",
        )
        for index, fit in enumerate((0.12, 0.55))
    ]

    dispatch = opt._dispatch(
        plan_slots,
        initial_soc_pct=12.6,
        capacity_kwh=47.0,
        evening=None,
    )
    low_fit_export_kw = max(0.0, -dispatch[0].site_grid_kw)
    high_fit_export_kw = max(0.0, -dispatch[1].site_grid_kw)

    assert low_fit_export_kw < high_fit_export_kw
    assert high_fit_export_kw > 0.9 * opt.settings.battery_max_discharge_kw
    assert dispatch[-1].soc_end_pct >= opt.settings.battery_min_soc_pct

    # Once that high-value interval is live, the fast path is not constrained
    # by the dynamic-programming energy grid and can request the verified SAJ
    # output immediately, while still preserving the trajectory reserve.
    live_now = now + timedelta(minutes=5)
    live_plan = opt.build_fast_price_plan(
        fast_base_plan(live_now),
        fast_states(live_now, fit="0.55", soc="12.6"),
        now=live_now,
        telemetry_health=telemetry_health(),
    )

    assert live_plan.actuation_allowed is True
    assert live_plan.action == "discharge_export"
    assert live_plan.battery_power_target_kw == opt.settings.battery_max_discharge_kw
    assert live_plan.site_export_target_kw == opt.settings.battery_max_discharge_kw - 1.0


def test_negative_fit_curtails_excess_solar(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    result = opt._dispatch(slots(now, fit=-0.05, buy=0.03, solar=10, load=1), 100, 47, None)
    assert result[0].site_grid_kw == 0
    assert result[0].pv_curtailment_kw > 8


def test_negative_fit_charges_battery_from_surplus_before_curtailing(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 20, 12, 0, tzinfo=BRISBANE)
    result = opt._dispatch(
        slots(now, fit=-0.05, buy=0.30, solar=10.0, load=1.0, count=2),
        50,
        47,
        None,
    )
    assert result[0].battery_kw < 0
    assert result[0].site_grid_kw == 0
    assert result[0].pv_curtailment_kw == 0


def test_grid_charge_is_not_used_while_battery_can_supply_the_site(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.03, count=8)
    for item in plan_slots[3:]:
        item.import_price = 0.35
        item.load_kw = 5.0
    result = opt._dispatch(plan_slots, 20, 47, None)
    assert all(item.battery_kw >= 0.0 for item in result[:3])
    assert all(item.site_grid_kw <= 0.001 for item in result[:3])
    assert any(item.battery_kw > 0.5 for item in result[3:])


def test_hot_water_is_three_point_seven_kw_and_covers_service_margin(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=8.0, load=1.0, count=16)
    assert ENTITY["hot_water_runtime"] == "sensor.hot_water_confirmed_runtime_today"
    states = {ENTITY["hot_water_runtime"]: {"state": "0"}}
    opt._schedule_hot_water(plan_slots, states, now, datetime(2026, 8, 11, 16, 30, tzinfo=BRISBANE))
    selected = [item for item in plan_slots if item.hot_water_kw > 0]
    assert sum(item.duration_h for item in selected) >= 3.05
    assert sum(item.duration_h for item in selected) < 3.55
    assert {item.hot_water_kw for item in selected} == {3.7}


def test_equal_cost_hot_water_uses_earliest_safe_solar_block(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.01, buy=0.30, solar=8.0, load=1.0, count=16)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "2.5"}},
        now,
        None,
    )

    selected = [slot for slot in plan_slots if slot.hot_water_kw > 0]
    assert [slot.start for slot in selected] == [now, now + timedelta(minutes=30)]


def test_near_term_hot_water_window_is_committed_across_full_replans(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    states = {ENTITY["hot_water_runtime"]: {"state": "0"}}
    first = slots(now + timedelta(minutes=30), fit=0.01, buy=0.30, solar=8.0, load=1.0, count=8)
    for slot in first[:6]:
        slot.hot_water_kw = 3.7
        slot.hot_water_control_mode = "solar_surplus"

    opt._stabilize_hot_water_schedule(first, states, now)

    second = slots(now + timedelta(minutes=30), fit=0.01, buy=0.30, solar=8.0, load=1.0, count=8)
    for slot in second[1:7]:
        slot.hot_water_kw = 3.7
        slot.hot_water_control_mode = "solar_surplus"
    opt._stabilize_hot_water_schedule(second, states, now + timedelta(minutes=5))

    committed = [slot.start for slot in second if slot.hot_water_kw > 0]
    assert committed == [slot.start for slot in second[:6]]


def test_hot_water_thermostat_satisfaction_completes_daily_service(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 9, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=-0.05, buy=0.20, solar=12.0, load=1.0, count=8)

    opt._schedule_hot_water(
        plan_slots,
        {
            ENTITY["hot_water_runtime"]: {"state": "0.4"},
            ENTITY["hot_water_satisfied"]: {"state": "on"},
        },
        now,
        None,
    )

    assert all(slot.hot_water_kw == 0 for slot in plan_slots)


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
    assert sum(plan_slots[index].duration_h for index in selected) >= 0.55
    runs: list[list[int]] = []
    for index in selected:
        if not runs or index != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(index)
    assert all(len(run) >= 3 for run in runs)
    assert sum(plan_slots[index].duration_h for index in selected) < 0.80


def test_negative_fit_is_the_first_hot_water_opportunity(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 20, 10, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.20, buy=0.10, solar=8.0, load=1.0, count=4)
    plan_slots[1].export_price = -0.05
    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "2.5"}},
        now,
        None,
    )
    selected = [slot for slot in plan_slots if slot.hot_water_kw > 0]
    assert len(selected) == 2
    assert plan_slots[1] in selected
    assert selected[0].start == now
    assert {slot.hot_water_control_mode for slot in selected} == {"solar_surplus"}


def test_evening_full_target_is_enforced_when_low_solar_can_fill_it(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=-0.05, buy=0.30, solar=20.0, load=1.0, count=8)
    evening = now + timedelta(hours=3)
    result = opt._dispatch(plan_slots, 50, 47, evening)
    at_crossover = next(item for item in result if item.start + timedelta(minutes=30) >= evening)
    assert at_crossover.soc_end_pct >= 99.0


def test_high_morning_fit_exports_solar_and_defers_battery_charging_to_low_fit(tmp_path):
    opt = EnergyOptimizer(
        Settings(data_dir=tmp_path, battery_capacity_kwh=10.0),
        LearningState(tmp_path / "state.json"),
    )
    now = datetime(2026, 8, 12, 7, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.30, solar=10.0, load=1.0, count=8)
    for item in plan_slots[:2]:
        item.export_price = 0.30
    evening = now + timedelta(hours=4)

    result = opt._dispatch(
        plan_slots,
        initial_soc_pct=20.0,
        capacity_kwh=10.0,
        evening=evening,
    )

    # Valuable morning generation is exported, not diverted into the battery.
    assert all(item.battery_kw >= 0 for item in result[:2])
    assert all(item.site_grid_kw <= -9.0 for item in result[:2])
    # Charging is delayed until the FIT has fallen, while the conservative
    # later surplus still gets the battery full before evening crossover.
    assert any(item.battery_kw < 0 for item in result[2:])
    assert result[-1].soc_end_pct >= 99.0


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
        *live_telemetry_states(),
    ]

    plan = opt.build_plan(base_states, now, telemetry_health=telemetry_health())

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
        disarmed = opt.build_plan(
            states,
            now,
            telemetry_health=telemetry_health(),
        )
        assert disarmed.actuation_allowed is False
        assert disarmed.battery_mode == "hold"
        assert disarmed.battery_power_target_kw == 0.0
        assert disarmed.battery_charge_target_kw == 0.0
        assert disarmed.battery_discharge_target_kw == 0.0
        assert disarmed.site_export_target_kw == 0.0
        assert disarmed.action == "safe_hold"


def test_full_plan_accepts_unchanged_soc_with_fresh_saj_source_heartbeat(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    price_attributes = {
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(minutes=5)).isoformat(),
    }
    states = [
        {"entity_id": ENTITY["amber_fit"], "state": "0.30", "attributes": price_attributes},
        {"entity_id": ENTITY["amber_import"], "state": "0.16", "attributes": price_attributes},
        {
            "entity_id": ENTITY["battery_soc"],
            "state": "100",
            "last_reported": (now - timedelta(minutes=90)).isoformat(),
        },
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    plan = opt.build_plan(states, now, telemetry_health=telemetry_health())

    assert plan.actuation_allowed is True
    assert not any("soc-source" in warning.lower() for warning in plan.warnings)


def test_full_plan_is_non_actuating_when_source_heartbeat_or_live_telemetry_is_invalid(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 18, 0, tzinfo=BRISBANE)
    price_attributes = {
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(minutes=5)).isoformat(),
    }
    states = [
        {"entity_id": ENTITY["amber_fit"], "state": "0.30", "attributes": price_attributes},
        {"entity_id": ENTITY["amber_import"], "state": "0.16", "attributes": price_attributes},
        *live_telemetry_states(),
        raw_state(ENTITY["mode"], "Active"),
        raw_state(ENTITY["battery_control"], "on"),
        raw_state(ENTITY["rollout_approved"], "on"),
        raw_state(ENTITY["manual_override"], "off"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    stale_heartbeat = opt.build_plan(
        states,
        now,
        telemetry_health=telemetry_health(heartbeat_age=331),
    )
    next(item for item in states if item["entity_id"] == ENTITY["home_load"])[
        "state"
    ] = "unavailable"
    invalid_load = opt.build_plan(
        states,
        now,
        telemetry_health=telemetry_health(),
    )
    next(item for item in states if item["entity_id"] == ENTITY["home_load"])[
        "state"
    ] = "1000"
    next(item for item in states if item["entity_id"] == ENTITY["pv_power"])[
        "state"
    ] = "-1"
    out_of_bounds_pv = opt.build_plan(
        states,
        now,
        telemetry_health=telemetry_health(),
    )

    assert stale_heartbeat.actuation_allowed is False
    assert any("soc-source heartbeat is stale" in warning.lower() for warning in stale_heartbeat.warnings)
    assert invalid_load.actuation_allowed is False
    assert any("household-load telemetry is unavailable" in warning.lower() for warning in invalid_load.warnings)
    assert out_of_bounds_pv.actuation_allowed is False
    assert any("pv telemetry is outside" in warning.lower() for warning in out_of_bounds_pv.warnings)


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
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
    ]

    plan = opt.build_plan(states, now, telemetry_health=telemetry_health())

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
        raw_state(ENTITY["battery_soc_heartbeat"], "0"),
        raw_state(ENTITY["pv_power"], "0"),
        raw_state(ENTITY["home_load"], "1000"),
    ]

    plan = opt.build_plan(states, now, telemetry_health=telemetry_health())

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
    states = ev_states(
        soc=38.0,
        departure=now + timedelta(hours=3),
        trip="Local / 50 km",
    )

    schedule = opt._schedule_ev(plan_slots, states, now)

    assert plan_slots[0].ev_kw == 0.0
    assert plan_slots[1].ev_charge_source == "direct_solar"
    assert plan_slots[1].ev_charge_amps == 6
    assert plan_slots[1].ev_power_target_kw == pytest.approx(4.446)
    conservative_surplus = plan_slots[1].solar_low_kw - plan_slots[1].load_kw - plan_slots[1].hot_water_kw
    assert plan_slots[1].ev_power_target_kw <= conservative_surplus
    assert schedule.solar_energy_kwh == pytest.approx(schedule.required_kwh)


def test_current_negative_fit_uses_expected_pv_when_p10_is_curtailed_below_ev_minimum(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 23, 14, 20, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=-0.01, buy=0.03, solar=4.3, load=1.0, count=2)
    plan_slots[0].hot_water_kw = 3.7
    states = ev_states(
        soc=40.0,
        departure=now + timedelta(hours=17),
        trip="No trip / opportunistic",
    )
    states[ENTITY["ev_auto"]] = {"state": "on"}
    states[ENTITY["solar_expected_north"]] = measured_state(
        ENTITY["solar_expected_north"], "6200", now,
    )
    states[ENTITY["solar_expected_south"]] = measured_state(
        ENTITY["solar_expected_south"], "10500", now,
    )

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=100.0,
        battery_capacity_kwh=47.0,
        evening=now + timedelta(hours=3),
    )

    assert schedule.action == "recommend_charge"
    assert plan_slots[0].ev_charge_source == "direct_solar"
    assert plan_slots[0].ev_charge_amps >= opt.settings.ev_min_charge_amps


def test_unanswered_ev_uses_low_fit_surplus_up_to_editable_charge_limit(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.20, solar=12.0, load=1.0, count=4)
    plan_slots[0].export_price = 0.08
    for item in plan_slots[1:]:
        item.export_price = 0.0
    states = ev_states(soc=80, departure=now + timedelta(hours=5), trip="Unanswered")
    states[ENTITY["ev_charge_limit"]] = {"state": "90"}

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=80,
        battery_capacity_kwh=47,
        evening=now + timedelta(hours=2),
    )

    assert schedule.target_soc_pct == 90
    assert schedule.required_kwh > 0
    assert schedule.solar_energy_kwh > 0
    assert plan_slots[0].ev_charge_source == "none"
    assert any(item.ev_charge_source == "direct_solar" for item in plan_slots[1:])


def test_unanswered_ev_does_not_use_surplus_when_later_solar_cannot_refill_house_battery(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.20, solar=0.0, load=1.0, count=4)
    plan_slots[0].solar_kw = plan_slots[0].solar_low_kw = 12.0
    plan_slots[0].export_price = 0.0
    states = ev_states(soc=10, departure=now + timedelta(hours=5), trip="Unanswered")
    states[ENTITY["ev_charge_limit"]] = {"state": "90"}

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=10,
        battery_capacity_kwh=47,
        evening=now + timedelta(hours=2),
    )

    assert schedule.solar_energy_kwh == 0
    assert schedule.mandatory is True
    assert any(item.ev_charge_source == "house_battery" for item in plan_slots)
    assert schedule.fallback_energy_kwh > 0.0


def test_ev_adds_lowest_cost_deadline_fallback_only_after_solar_shortfall(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 11, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.20, solar=0.0, load=1.0, count=3)
    plan_slots[0].solar_kw = plan_slots[0].solar_low_kw = plan_slots[0].solar_high_kw = 7.0
    plan_slots[2].import_price = 0.01
    states = ev_states(
        soc=30.0,
        departure=now + timedelta(hours=2),
        trip="Local / 50 km",
    )
    states[ENTITY["ev_allow_grid"]] = {"state": "on"}

    schedule = opt._schedule_ev(plan_slots, states, now)

    direct_solar_capacity = opt._ev_power_for_amps(8) * plan_slots[0].duration_h
    assert schedule.solar_energy_kwh == pytest.approx(direct_solar_capacity)
    assert schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh - direct_solar_capacity)
    assert plan_slots[0].ev_charge_source == "solar_house_battery"
    assert plan_slots[1].ev_charge_source == "house_battery"
    assert plan_slots[2].ev_kw == 0.0
    assert schedule.solar_energy_kwh + schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh)


def test_explicit_trip_uses_house_battery_reserve_not_grid_when_dashboard_switch_is_off(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 11, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.01, solar=0.0, load=1.0, count=3)
    states = ev_states(
        soc=30.0,
        departure=now + timedelta(hours=2),
        trip="Local / 50 km",
    )
    states[ENTITY["ev_allow_grid"]] = {"state": "off"}

    schedule = opt._schedule_ev(plan_slots, states, now)

    assert schedule.mandatory is True
    assert schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh)
    assert schedule.unmet_kwh == 0.0
    assert schedule.action == "recommend_charge"
    assert any(slot.ev_charge_source == "house_battery" for slot in plan_slots)


@pytest.mark.parametrize("trip", ["Unanswered", "No trip"])
def test_ev_without_declared_trip_still_schedules_40pct_house_battery_reserve(tmp_path, trip):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 6, 40, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.31, buy=0.44, solar=1.3, load=1.0, count=2)
    states = ev_states(
        soc=35.0,
        departure=now + timedelta(minutes=20),
        trip=trip,
    )

    schedule = opt._schedule_ev(plan_slots, states, now)

    assert schedule.required_kwh > 0
    assert schedule.mandatory is True
    assert schedule.fallback_energy_kwh == pytest.approx(4.1666666667)
    assert any(item.ev_kw > 0.0 for item in plan_slots)
    assert any(item.ev_charge_source == "house_battery" for item in plan_slots)


def test_overnight_unanswered_ev_reaches_40pct_from_house_battery_without_grid(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 21, 21, 30, tzinfo=BRISBANE)
    departure = datetime(2026, 8, 22, 7, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.05, buy=0.30, solar=0.0, load=1.0, count=20)
    states = ev_states(soc=18.0, departure=departure, trip="Unanswered")
    states[ENTITY["ev_allow_grid"]] = {"state": "off"}

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=75.0,
        battery_capacity_kwh=47.0,
    )

    minimum_kwh = (40.0 - 18.0) / 100 * 75.0 / 0.90
    scheduled_before_departure = sum(
        slot.ev_kw * slot.duration_h
        for slot in plan_slots
        if slot.start < departure
    )
    assert schedule.mandatory is True
    assert schedule.fallback_energy_kwh == pytest.approx(minimum_kwh)
    assert scheduled_before_departure >= minimum_kwh
    assert schedule.unmet_kwh == pytest.approx(schedule.required_kwh - minimum_kwh)
    assert plan_slots[0].ev_kw > 0.0
    assert plan_slots[0].ev_charge_source == "house_battery"
    assert all(
        slot.ev_charge_source in ["none", "house_battery"]
        for slot in plan_slots
        if slot.start < departure
    )


def test_explicit_trip_deadline_fallback_uses_battery_before_grid(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 12, 6, 40, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.44, solar=1.3, load=1.0, count=2)
    plan_slots[0].ev_kw = opt._ev_power_for_amps(16)
    plan_slots[0].ev_charge_amps = 16
    plan_slots[0].ev_power_target_kw = opt._ev_power_for_amps(16)
    plan_slots[0].ev_charge_source = "deadline_fallback"

    dispatch = opt._dispatch(
        plan_slots,
        initial_soc_pct=80.0,
        capacity_kwh=47.0,
        evening=None,
    )

    expected_deficit = 1.0 + opt._ev_power_for_amps(16) - 1.3
    assert dispatch[0].battery_kw == pytest.approx(expected_deficit)
    assert dispatch[0].site_grid_kw == 0.0


def test_fast_live_high_fit_immediately_requests_full_safe_discharge(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit="0.55"),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.plan_id.startswith("eop-fast-")
    assert plan.actuation_allowed is True
    assert plan.action == "discharge_export"
    assert plan.battery_power_target_kw == 28.0
    assert plan.site_export_target_kw == 27.0
    assert plan.intervals[0].export_price == 0.55
    assert plan.intervals[0].soc_end_pct >= 5.0
    assert plan.valid_until == now + timedelta(minutes=5)


def test_fast_plan_never_lowers_cached_dynamic_protected_reserve(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 18, 24, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    base.protected_soc_pct = 39.9

    self_consume = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.0706667", soc="76"),
        now=now,
        telemetry_health=telemetry_health(),
    )
    constrained_export = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.55", soc="41"),
        now=now,
        telemetry_health=telemetry_health(),
    )
    available_kw = (
        (41.0 - 39.9)
        / 100
        * opt.settings.battery_capacity_kwh
        * opt.settings.battery_discharge_efficiency
        / (5 / 60)
    )

    assert self_consume.battery_mode == "self_consume"
    assert self_consume.battery_power_target_kw == 1.0
    assert self_consume.site_export_target_kw == 0.0
    assert self_consume.protected_soc_pct == 39.9
    assert constrained_export.battery_mode == "export"
    assert constrained_export.protected_soc_pct == 39.9
    assert constrained_export.battery_power_target_kw == pytest.approx(
        round(available_kw, 3)
    )
    assert constrained_export.battery_power_target_kw < opt.settings.battery_max_discharge_kw


@pytest.mark.parametrize("fit", ["0.05", "-0.05", "unavailable"])
def test_fast_low_negative_or_malformed_fit_never_forces_export(tmp_path, fit):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit=fit),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.site_export_target_kw == 0.0
    assert plan.action != "discharge_export"
    if fit == "0.05":
        assert plan.battery_power_target_kw == 1.0
        assert plan.action == "self_consumption"
    elif fit == "-0.05":
        assert plan.battery_power_target_kw == 1.0
        assert plan.action == "self_consumption"
    else:
        assert plan.battery_power_target_kw == 0.0
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
        telemetry_health=telemetry_health(pv_age=331),
    )
    near_floor = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.55", soc="5.2"),
        now=now,
        telemetry_health=telemetry_health(heartbeat_age=30),
    )

    assert stale.actuation_allowed is False
    assert stale.battery_power_target_kw == 0.0
    assert near_floor.battery_power_target_kw == 0.0
    assert near_floor.intervals[0].soc_end_pct >= 5.0


@pytest.mark.parametrize(
    ("entity_id", "value"),
    [
        (ENTITY["mode"], "Shadow"),
        (ENTITY["battery_control"], "off"),
        (ENTITY["rollout_approved"], "off"),
        (ENTITY["manual_override"], "on"),
    ],
)
def test_fast_control_disarm_cannot_republish_cached_force_mode(
    tmp_path,
    entity_id,
    value,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    base.action = "discharge_export"
    base.battery_mode = "export"
    base.battery_power_target_kw = 10.0
    base.battery_discharge_target_kw = 10.0
    base.site_export_target_kw = 9.0
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0
    states = fast_states(now, fit="0.55", soc="77")
    next(item for item in states if item["entity_id"] == entity_id)["state"] = value

    plan = opt.build_fast_price_plan(
        base,
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.actuation_allowed is False
    assert plan.battery_mode == "hold"
    assert plan.battery_power_target_kw == 0.0
    assert plan.battery_charge_target_kw == 0.0
    assert plan.battery_discharge_target_kw == 0.0
    assert plan.site_export_target_kw == 0.0
    assert plan.action != "discharge_export"


@pytest.mark.parametrize(
    ("entity_id", "value"),
    [
        (ENTITY["pv_power"], "-1"),
        (ENTITY["pv_power"], "100001"),
        (ENTITY["home_load"], "-1"),
        (ENTITY["home_load"], "100001"),
    ],
)
def test_fast_rejects_out_of_bounds_pv_or_load_telemetry(
    tmp_path,
    entity_id,
    value,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    states = fast_states(now, fit="0.55")
    next(item for item in states if item["entity_id"] == entity_id)["state"] = value

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.actuation_allowed is False
    assert plan.battery_power_target_kw == 0.0
    assert "outside 0-100 kw" in plan.reason.lower()


@pytest.mark.parametrize(
    ("heartbeat_age", "include_heartbeat"),
    [(331.0, True), (0.0, False)],
    ids=["stale", "missing"],
)
def test_fast_rejects_stale_or_missing_soc_source_heartbeat(
    tmp_path,
    heartbeat_age,
    include_heartbeat,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    states = fast_states(now, fit="0.55")
    if not include_heartbeat:
        states = [
            item
            for item in states
            if item["entity_id"] != ENTITY["battery_soc_heartbeat"]
        ]

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        states,
        now=now,
        telemetry_health=telemetry_health(heartbeat_age=heartbeat_age),
    )

    assert plan.actuation_allowed is False
    assert plan.battery_power_target_kw == 0.0
    assert "heartbeat" in plan.reason.lower()


def test_fast_missing_or_stale_price_window_metadata_cannot_discharge(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    base.action = "discharge_export"
    base.battery_mode = "export"
    base.battery_power_target_kw = 10.0
    base.battery_discharge_target_kw = 10.0
    base.site_export_target_kw = 9.0
    base.protected_soc_pct = 39.9
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0
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

    missing_plan = opt.build_fast_price_plan(
        base,
        missing,
        now=now,
        telemetry_health=telemetry_health(),
    )
    stale_plan = opt.build_fast_price_plan(
        base,
        stale,
        now=now,
        telemetry_health=telemetry_health(),
    )

    for plan in (missing_plan, stale_plan):
        assert plan.actuation_allowed is False
        assert plan.action == "safe_hold"
        assert plan.battery_mode == "hold"
        assert plan.battery_power_target_kw == 0.0
        assert plan.battery_charge_target_kw == 0.0
        assert plan.battery_discharge_target_kw == 0.0
        assert plan.site_export_target_kw == 0.0
        assert plan.protected_soc_pct == 39.9
        assert plan.live_fit_price is None
        assert plan.live_import_price is None
        assert plan.price_interval_start is None
        assert plan.price_interval_end is None
        assert plan.intervals[0].price_source == "invalid_live_price"
        assert now < plan.valid_until <= now + timedelta(minutes=5)


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
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 1.0
    assert plan.site_export_target_kw == 0.0
    assert plan.action == "self_consumption"


def test_fast_downward_fit_revision_drops_export_but_preserves_cached_household(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.80)
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0
    base.intervals[2].battery_kw = 28.0
    base.intervals[2].site_grid_kw = -27.0

    plan = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.09"),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 1.0
    assert plan.site_export_target_kw == 0.0
    assert plan.action == "self_consumption"


def test_fast_cached_household_supply_uses_live_import_value_against_future_fit(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.15)
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0
    base.intervals[2].battery_kw = 28.0
    base.intervals[2].site_grid_kw = -27.0

    plan = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.09"),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 1.0
    assert plan.site_export_target_kw == 0.0
    assert plan.action == "self_consumption"


def test_fast_preserves_cached_household_tranche_across_small_amber_revision(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 19, 20, 16, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.08)
    base.protected_soc_pct = 39.7
    base.intervals[0].load_kw = 1.645
    base.intervals[0].import_price = 0.32103
    base.intervals[0].battery_kw = 1.645
    base.intervals[0].site_grid_kw = 0.0
    # A higher-value household allocation later in the horizon previously
    # became an inappropriate global hurdle for the already-solved live slot.
    base.intervals[2].import_price = 0.44
    base.intervals[2].battery_kw = 1.0
    base.intervals[2].site_grid_kw = 0.0
    states = fast_states(now, fit="0.068519")
    next(item for item in states if item["entity_id"] == ENTITY["amber_import"])[
        "state"
    ] = "0.318468"
    next(item for item in states if item["entity_id"] == ENTITY["home_load"])[
        "state"
    ] = "1645"

    plan = opt.build_fast_price_plan(
        base,
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.actuation_allowed is True
    assert plan.action == "self_consumption"
    assert plan.battery_mode == "self_consume"
    assert plan.battery_power_target_kw == 1.645
    assert plan.site_export_target_kw == 0.0
    assert plan.protected_soc_pct == 39.7


def test_fast_keeps_house_supply_after_material_import_price_fall(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 19, 20, 16, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.08)
    base.intervals[0].load_kw = 1.645
    base.intervals[0].import_price = 0.32103
    base.intervals[0].battery_kw = 1.645
    base.intervals[0].site_grid_kw = 0.0
    base.intervals[2].import_price = 0.44
    base.intervals[2].battery_kw = 1.0
    base.intervals[2].site_grid_kw = 0.0
    states = fast_states(now, fit="0.068519")
    next(item for item in states if item["entity_id"] == ENTITY["amber_import"])[
        "state"
    ] = "0.29"
    next(item for item in states if item["entity_id"] == ENTITY["home_load"])[
        "state"
    ] = "1645"

    plan = opt.build_fast_price_plan(
        base,
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.actuation_allowed is True
    assert plan.action == "self_consumption"
    assert plan.battery_mode == "self_consume"
    assert plan.battery_power_target_kw == 1.645
    assert plan.site_export_target_kw == 0.0


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
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 10.0
    assert plan.action == "discharge_export"


def test_fast_cached_export_continues_when_live_fit_is_still_best_allocated_value(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.085)
    base.intervals[0].battery_kw = 10.0
    base.intervals[0].site_grid_kw = -9.0
    base.intervals[2].import_price = 0.80
    base.intervals[2].battery_kw = 28.0
    base.intervals[2].site_grid_kw = -28.0

    plan = opt.build_fast_price_plan(
        base,
        fast_states(now, fit="0.09"),
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 10.0
    assert plan.site_export_target_kw == 9.0
    assert plan.action == "discharge_export"


def test_fast_live_import_spike_immediately_supplies_house_without_weak_fit_export(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now, future_fit=0.15)
    base.intervals[2].import_price = 0.80
    base.intervals[2].battery_kw = 28.0
    base.intervals[2].site_grid_kw = -28.0
    states = fast_states(now, fit="0.05")
    next(item for item in states if item["entity_id"] == ENTITY["amber_import"])[
        "state"
    ] = "0.30"

    plan = opt.build_fast_price_plan(
        base,
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.battery_power_target_kw == 1.0
    assert plan.site_export_target_kw == 0.0
    assert plan.action == "self_consumption"


def test_fast_fit_spike_pauses_nonmandatory_ev_and_exports_battery_past_base_load(
    tmp_path,
):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 11, 17, 0, tzinfo=BRISBANE)
    base = fast_base_plan(now)
    base.ev_action = "charge"
    base.ev_charge_amps_target = 6
    base.ev_power_target_kw = opt._ev_power_for_amps(6)
    base.ev_charge_source = "direct_solar"
    base.ev_mandatory = False
    base.intervals[0].ev_kw = base.ev_power_target_kw
    states = fast_states(now, fit="0.30")
    next(item for item in states if item["entity_id"] == ENTITY["home_load"])[
        "state"
    ] = "6500"
    states.append(raw_state(ENTITY["ev_power_local"], "4.5"))

    plan = opt.build_fast_price_plan(
        base,
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.ev_action == "opportunity_wait"
    assert plan.ev_charge_amps_target == 0
    assert plan.ev_power_target_kw == 0.0
    assert plan.ev_charge_source == "none"
    assert plan.intervals[0].ev_kw == 0.0
    assert plan.intervals[0].load_kw == pytest.approx(2.0)
    assert plan.battery_power_target_kw == opt.settings.battery_max_discharge_kw
    assert plan.site_export_target_kw == pytest.approx(26.0)


def test_fixed_nominal_capacity_is_not_replaced_by_current_stored_energy(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 17, 0, tzinfo=BRISBANE)
    states = fast_states(now, fit="0.55", soc="80")
    next(item for item in states if item["entity_id"] == ENTITY["battery_usable"])[
        "state"
    ] = "10"

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )

    assert plan.actuation_allowed is True
    assert plan.battery_capacity_kwh == opt.settings.battery_capacity_kwh == 47.0
    assert plan.battery_stored_energy_kwh == 10.0
    assert plan.battery_energy_consistent is False
    assert plan.battery_power_target_kw == opt.settings.battery_max_discharge_kw


def test_fresh_polled_zero_pv_heartbeat_authorizes_night_operation(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 5, 30, tzinfo=BRISBANE)

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        fast_states(now, fit="0.55"),
        now=now,
        telemetry_health=telemetry_health(
            pv_age=3600,
            pv_heartbeat_age=0,
        ),
    )

    assert ENTITY["pv_power"] == ENTITY["pv_heartbeat"] == "sensor.saj_pv_power"
    assert plan.actuation_allowed is True


def test_full_plan_curtails_every_negative_fit_interval_even_with_zero_predicted_pv(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    states = [
        *fast_states(now, fit="-0.05", soc="80"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "40"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    plan = opt.build_plan(states, now, telemetry_health=telemetry_health())

    assert plan.intervals[0].solar_kw == 0.0
    assert plan.pv_curtailment_target_kw == 0.0
    assert plan.pv_export_command == "curtail"
    assert plan.site_export_target_kw == 0.0


def test_full_plan_intervals_round_trip_into_immediate_price_dispatch(tmp_path):
    """A freshly built horizon must contain every field used by the fast path."""
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    states = [
        *fast_states(now, fit="0.08", soc="80"),
        raw_state(ENTITY["ev_trip"], "No trip"),
        raw_state(ENTITY["ev_soc"], "54"),
        raw_state(ENTITY["ev_limit"], "80"),
    ]

    full = opt.build_plan(states, now, telemetry_health=telemetry_health())
    assert all(interval.ev_charge_source for interval in full.intervals)

    fast = opt.build_fast_price_plan(
        full,
        states,
        now=now + timedelta(seconds=5),
        telemetry_health=telemetry_health(),
    )
    assert fast.plan_id.startswith("eop-fast-")


def test_hot_water_is_planned_for_each_complete_local_service_day(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=8.0, load=1.0, count=64)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "0"}},
        now,
        None,
    )

    hours_by_date: dict[str, float] = {}
    for slot in plan_slots:
        if slot.hot_water_kw > 0:
            key = slot.start.date().isoformat()
            hours_by_date[key] = hours_by_date.get(key, 0.0) + slot.duration_h
            assert slot.hot_water_control_mode == "solar_surplus"
    assert hours_by_date == {"2026-08-18": 3.5, "2026-08-19": 3.5}


def test_hot_water_does_not_create_early_rescue_for_partial_tail_day(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 20, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=8.0, load=1.0, count=72)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "0"}},
        now,
        None,
    )

    scheduled_dates = {
        slot.start.date().isoformat()
        for slot in plan_slots
        if slot.hot_water_kw > 0
    }
    assert scheduled_dates == {"2026-08-18", "2026-08-19"}
    assert all(
        slot.hot_water_kw == 0
        for slot in plan_slots
        if slot.start.date().isoformat() == "2026-08-20"
    )


def test_hot_water_service_rescue_uses_only_latest_start_window(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 8, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=0.0, load=1.0, count=16)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "0"}},
        now,
        None,
    )

    selected = [slot for slot in plan_slots if slot.hot_water_kw > 0]
    assert selected[0].start == datetime(2026, 8, 18, 12, 30, tzinfo=BRISBANE)
    assert selected[-1].start == datetime(2026, 8, 18, 15, 30, tzinfo=BRISBANE)
    assert {slot.hot_water_control_mode for slot in selected} == {"service_rescue"}


def test_late_hot_water_service_rescue_runs_all_remaining_feasible_time(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 15, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.05, solar=0.0, load=1.0, count=2)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "0"}},
        now,
        None,
    )

    assert all(slot.hot_water_kw == 3.7 for slot in plan_slots)
    assert all(slot.hot_water_control_mode == "service_rescue" for slot in plan_slots)


def test_missed_four_pm_target_recovers_until_service_is_complete(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 20, 17, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.05, buy=0.20, solar=0.0, load=1.0, count=6)

    opt._schedule_hot_water(
        plan_slots,
        {ENTITY["hot_water_runtime"]: {"state": "1.5"}},
        now,
        None,
    )

    assert sum(slot.duration_h for slot in plan_slots if slot.hot_water_kw > 0) == 2.0
    assert all(
        slot.hot_water_control_mode == "service_rescue"
        for slot in plan_slots
        if slot.hot_water_kw > 0
    )


def test_hot_water_service_rescue_uses_grid_while_battery_covers_house(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 13, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.0, buy=0.80, solar=0.0, load=0.2, count=2)
    for slot in plan_slots:
        slot.hot_water_kw = opt.settings.hot_water_kw
        slot.hot_water_control_mode = "service_rescue"

    dispatch = opt._dispatch(plan_slots, 80.0, 47.0, None)

    assert all(item.battery_kw == pytest.approx(0.2) for item in dispatch)
    assert all(item.site_grid_kw == pytest.approx(3.7) for item in dispatch)


def test_grid_charge_is_only_the_forecast_ordinary_house_reserve(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 1, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.05, buy=0.10, solar=0.0, load=1.0, count=6)
    for slot in plan_slots:
        slot.hot_water_kw = 3.7
        slot.ev_kw = 4.45
    morning = now + timedelta(hours=3)

    targets = opt._home_reserve_grid_charge_targets(
        plan_slots,
        initial_soc_pct=5.0,
        capacity_kwh=47.0,
        morning=morning,
    )

    required_house_output = 3.0 + (0.07 - 0.05) * 47.0 * 0.90
    assert sum(
        targets.get(slot.start, 0.0) * slot.duration_h for slot in plan_slots
    ) == pytest.approx(required_house_output / (0.90 * 0.90))


def test_current_house_reserve_keeps_ordinary_load_until_morning(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 6, 0, tzinfo=BRISBANE)
    intervals = fast_base_plan(now).intervals
    morning = now + timedelta(hours=1)
    for interval in intervals:
        interval.load_kw = 1.0
        interval.solar_low_kw = 0.0
        # Flexible loads must not be allowed to inflate or consume the
        # stationary-battery energy protected for the ordinary house.
        interval.hot_water_kw = 3.7
        interval.ev_kw = 11.856

    reserve = opt._current_house_reserve_soc(intervals, morning, 47.0)
    expected = 7.0 + 1.0 / opt.settings.battery_discharge_efficiency / 47.0 * 100

    assert reserve == pytest.approx(expected)


def test_future_conservative_solar_can_reduce_current_house_reserve_to_floor(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 6, 0, tzinfo=BRISBANE)
    intervals = fast_base_plan(now).intervals
    morning = now + timedelta(hours=1)
    for interval in intervals:
        interval.load_kw = 1.0
        interval.solar_low_kw = 10.0

    reserve = opt._current_house_reserve_soc(intervals, morning, 47.0)

    assert reserve == opt.settings.battery_min_soc_pct


def test_grid_charge_is_not_used_when_existing_battery_covers_house_to_solar(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 1, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.05, buy=-0.10, solar=0.0, load=1.0, count=4)

    targets = opt._home_reserve_grid_charge_targets(
        plan_slots,
        initial_soc_pct=80.0,
        capacity_kwh=47.0,
        morning=now + timedelta(hours=2),
    )

    assert targets == {}


def test_sub_40_ev_uses_immediate_house_battery_before_grid_fallback(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.60, buy=0.05, solar=12.0, load=1.0, count=2)
    plan_slots[1].solar_kw = plan_slots[1].solar_low_kw = 0.0
    plan_slots[1].import_price = 0.02
    states = ev_states(
        soc=39.0,
        departure=now + timedelta(hours=2),
        trip="Local / 50 km",
    )
    states[ENTITY["ev_allow_grid"]] = {"state": "on"}

    schedule = opt._schedule_ev(plan_slots, states, now)

    assert schedule.mandatory is True
    assert plan_slots[0].ev_charge_source == "house_battery"
    assert plan_slots[1].ev_charge_source == "none"
    assert schedule.solar_energy_kwh == 0.0
    assert schedule.fallback_energy_kwh == pytest.approx(schedule.required_kwh)


@pytest.mark.parametrize("trip", ["Unanswered", "No trip"])
def test_nonmandatory_ev_never_consumes_high_fit_solar(tmp_path, trip):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.30, buy=0.02, solar=12.0, load=1.0, count=4)
    states = ev_states(soc=40.0, departure=now + timedelta(hours=3), trip=trip)

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=100.0,
        battery_capacity_kwh=47.0,
    )

    assert schedule.mandatory is False
    assert schedule.fallback_energy_kwh == 0.0
    assert all(slot.ev_kw == 0.0 for slot in plan_slots)


@pytest.mark.parametrize("trip", ["Unanswered", "No trip"])
def test_nonmandatory_ev_can_use_negative_fit_solar_after_advisory_departure(tmp_path, trip):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 6, 30, tzinfo=BRISBANE)
    plan_slots = slots(now, fit=0.30, buy=0.05, solar=0.0, load=1.0, count=8)
    for slot in plan_slots[1:]:
        slot.export_price = -0.03
        slot.solar_kw = slot.solar_low_kw = slot.solar_high_kw = 14.0
    departure = now + timedelta(minutes=30)
    states = ev_states(soc=20.0, departure=departure, trip=trip)

    schedule = opt._schedule_ev(
        plan_slots,
        states,
        now,
        battery_soc_pct=100.0,
        battery_capacity_kwh=47.0,
    )

    assert schedule.mandatory is True
    assert schedule.fallback_energy_kwh > 0.0
    assert any(slot.ev_charge_source == "house_battery" for slot in plan_slots)
    if trip == "Unanswered":
        assert any(slot.start >= departure and slot.ev_kw > 0 for slot in plan_slots)
    assert all(
        slot.ev_charge_source in ["direct_solar", "house_battery", "solar_house_battery"]
        for slot in plan_slots
        if slot.ev_kw > 0
    )


def test_missing_ev_soc_never_pretends_requirement_is_satisfied(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    states = ev_states(
        soc=20.0,
        departure=now + timedelta(hours=2),
        trip="Local / 50 km",
    )
    states[ENTITY["ev_soc"]]["state"] = "unavailable"

    schedule = opt._schedule_ev(
        slots(now, fit=-0.05, buy=0.02, solar=12.0, count=4),
        states,
        now,
    )

    assert schedule.action == "telemetry_unavailable"
    assert schedule.mandatory is True
    assert schedule.required_kwh == 0.0


def test_plan_schema_two_exposes_actuator_contract_and_source_metadata(tmp_path):
    opt = optimizer(tmp_path)
    now = datetime(2026, 8, 18, 17, 0, tzinfo=BRISBANE)
    states = fast_states(now, fit="0.55")
    for item in states:
        item["last_reported"] = now.isoformat()

    plan = opt.build_fast_price_plan(
        fast_base_plan(now),
        states,
        now=now,
        telemetry_health=telemetry_health(),
    )
    payload = plan.to_dict(interval_limit=1)

    assert payload["schema_version"] == 2
    assert payload["battery_mode"] == "export"
    assert payload["battery_power_target_kw"] > 0
    assert payload["battery_discharge_target_kw"] == payload["battery_power_target_kw"]
    assert payload["battery_charge_target_kw"] == 0.0
    assert payload["protected_soc_pct"] >= 5.0
    assert payload["live_fit_price"] == 0.55
    assert payload["live_import_price"] == 0.16
    assert payload["price_interval_start"] == now.isoformat()
    assert payload["price_interval_end"] == (now + timedelta(minutes=5)).isoformat()
    assert payload["source_timestamps"]["pv_heartbeat"] == now.isoformat()
    assert payload["software_version"] == "0.2.0"
    assert len(payload["config_fingerprint"]) == 16
