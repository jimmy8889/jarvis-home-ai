from datetime import datetime, timedelta, timezone
import json
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.config import ENTITY, Settings
from energy_optimizer.models import DispatchInterval, Plan
from energy_optimizer.outcomes import OutcomeRecorder


BRISBANE = ZoneInfo("Australia/Brisbane")


def states_at(
    when: datetime,
    *,
    grid_w: float = -6000,
    fit: float = -0.05,
    imports: float = 0.20,
    soc: float = 80,
) -> list[dict]:
    interval_start = when.replace(
        minute=when.minute - when.minute % 5,
        second=0,
        microsecond=0,
    )
    price_attributes = {
        "start_time": interval_start.isoformat(),
        "end_time": (interval_start + timedelta(minutes=5)).isoformat(),
    }

    def power(entity_id: str, value: float) -> dict:
        return {
            "entity_id": entity_id,
            "state": str(value),
            "attributes": {"unit_of_measurement": "W"},
            "last_reported": when.isoformat(),
        }

    return [
        {
            "entity_id": ENTITY["amber_fit"],
            "state": str(fit),
            "attributes": price_attributes,
            "last_reported": when.isoformat(),
        },
        {
            "entity_id": ENTITY["amber_import"],
            "state": str(imports),
            "attributes": price_attributes,
            "last_reported": when.isoformat(),
        },
        power(ENTITY["pv_power"], 10_000),
        power(ENTITY["home_load"], 2_000),
        power(ENTITY["grid_power"], grid_w),
        power(ENTITY["battery_soc_heartbeat"], 2_000),
        power(ENTITY["hot_water_power"], 3_700),
        power(ENTITY["ev_power"], 0),
        {"entity_id": ENTITY["hot_water_source"], "state": "solar"},
        {"entity_id": ENTITY["ev_source"], "state": "off"},
        {"entity_id": ENTITY["actuator_status"], "state": "feedback_confirmed | test"},
        {"entity_id": ENTITY["actuation_ready"], "state": "on"},
        {
            "entity_id": ENTITY["battery_soc"],
            "state": str(soc),
            "last_reported": when.isoformat(),
        },
    ]


def outcome_plan(when: datetime, *, protected_soc: float = 7.0) -> Plan:
    interval = DispatchInterval(
        start=when,
        duration_minutes=5,
        solar_kw=10.0,
        solar_low_kw=8.0,
        load_kw=2.0,
        hot_water_kw=3.7,
        ev_kw=0.0,
        import_price=0.2,
        export_price=-0.05,
        battery_kw=2.0,
        site_grid_kw=-6.0,
        pv_curtailment_kw=0.0,
        soc_start_pct=80.0,
        soc_end_pct=79.5,
        cost=0.0,
        price_source="amber_live",
    )
    return Plan(
        plan_id="outcome-plan",
        generated_at=when,
        valid_until=when + timedelta(minutes=5),
        mode="active",
        actuation_allowed=True,
        action="discharge_export",
        reason="test",
        confidence=0.8,
        battery_power_target_kw=2.0,
        site_export_target_kw=6.0,
        pv_export_command="allow",
        pv_curtailment_target_kw=0.0,
        hot_water_command="on",
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
        battery_mode="export",
        protected_soc_pct=protected_soc,
    )


def test_outcome_recorder_integrates_one_realized_row_per_completed_interval(tmp_path):
    recorder = OutcomeRecorder(Settings(data_dir=tmp_path))
    start = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    plan = outcome_plan(start)

    assert recorder.observe(states_at(start), plan, start) == []
    completed = recorder.observe(
        states_at(start + timedelta(minutes=5), fit=0.1),
        plan,
        start + timedelta(minutes=5),
    )

    assert len(completed) == 1
    row = completed[0]
    assert row["status"] == "measured"
    assert row["telemetry_coverage_seconds"] == 300
    assert row["solar_kwh"] == pytest.approx(10 * 5 / 60, abs=1e-5)
    assert row["grid_export_kwh"] == pytest.approx(6 * 5 / 60, abs=1e-5)
    assert row["battery_discharge_kwh"] == pytest.approx(2 * 5 / 60, abs=1e-5)
    assert row["hot_water_hours"] == pytest.approx(5 / 60, abs=1e-5)
    assert row["negative_fit_zero_export_met"] is False
    expected_benefit = 0.5 * -0.05 - (2 * 5 / 60) * 0.08
    assert row["net_benefit_after_wear"] == pytest.approx(expected_benefit, abs=1e-6)
    stored = (tmp_path / "outcomes" / "2026-08-18.jsonl").read_text().splitlines()
    assert len(stored) == 1
    assert json.loads(stored[0])["interval_start"] == start.astimezone(timezone.utc).isoformat()


def test_outcome_recorder_emits_explicit_gap_rows_and_rolling_summary(tmp_path):
    recorder = OutcomeRecorder(Settings(data_dir=tmp_path))
    start = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)

    recorder.observe(states_at(start), None, start)
    completed = recorder.observe(
        states_at(start + timedelta(minutes=15), fit=0.1),
        None,
        start + timedelta(minutes=15),
    )

    assert [row["status"] for row in completed] == [
        "measured",
        "no_observation",
        "no_observation",
    ]
    summary = recorder.summary()
    assert summary["status"] == "collecting"
    assert summary["rolling_7d"]["recorded_intervals"] == 3
    assert summary["rolling_7d"]["measured_intervals"] == 1
    assert summary["rolling_7d"]["negative_fit_export_violations"] == 1


def test_outcome_recorder_marks_protected_soc_breach(tmp_path):
    recorder = OutcomeRecorder(Settings(data_dir=tmp_path))
    start = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    plan = outcome_plan(start, protected_soc=7.0)

    recorder.observe(states_at(start, soc=6.0), plan, start)
    row = recorder.observe(
        states_at(start + timedelta(minutes=5), fit=0.1, soc=5.5),
        plan,
        start + timedelta(minutes=5),
    )[0]

    assert row["minimum_soc_pct"] == 5.5
    assert row["protected_soc_breach"] is True


def test_daily_acceptance_summarizes_confirmed_hot_water_service_hours():
    rows = [
        {
            "status": "measured",
            "local_date": "2026-08-18",
            "hot_water_coverage_seconds": 300.0,
            "hot_water_hours": 3.0 / 288,
            "negative_fit_seconds": 0.0,
            "protected_soc_breach": False,
        }
        for _ in range(288)
    ]

    summary = OutcomeRecorder._aggregate(rows, 288)

    assert summary["hot_water_service_days_assessed"] == 1
    assert summary["hot_water_service_days_completed"] == 1
    assert summary["hot_water_completion_pct"] == 100.0
    assert summary["protected_soc_compliance_pct"] == 100.0


def test_journal_retention_defaults_to_ninety_days():
    assert Settings().journal_retention_days == 90


def test_outcomes_record_sources_crossovers_departure_and_actuator_stability(tmp_path):
    recorder = OutcomeRecorder(Settings(data_dir=tmp_path))
    start = datetime(2026, 8, 18, 6, 0, tzinfo=BRISBANE)
    plan = outcome_plan(start)
    plan.morning_takeover = start + timedelta(minutes=2)
    plan.ev_target_soc_pct = 40.0
    departure = start + timedelta(minutes=3)

    first = states_at(start, soc=7.0)
    first.extend([
        {"entity_id": ENTITY["ev_soc"], "state": "45"},
        {"entity_id": ENTITY["ev_departure"], "state": departure.isoformat()},
    ])
    recorder.observe(first, plan, start)
    row = recorder.observe(
        states_at(start + timedelta(minutes=5), fit=0.1, soc=7.0),
        plan,
        start + timedelta(minutes=5),
    )[0]

    assert row["hot_water_solar_kwh"] == pytest.approx(3.7 * 5 / 60, abs=1e-5)
    assert row["morning_takeover_soc_pct"] == 7.0
    assert row["ev_departure_soc_pct"] == 45.0
    assert row["ev_departure_success"] is True
    assert row["actuator_rejections"] == 0
    assert row["actuator_failures"] == 0
    assert row["actuator_unconfirmed_seconds"] == 0.0

    summary = OutcomeRecorder._aggregate([row], 1)
    assert summary["morning_takeover_target_pct"] == 100.0
    assert summary["ev_departure_success_pct"] == 100.0
    assert summary["source_allocation_kwh"]["hot_water_solar_kwh"] > 0


def test_outcome_upgrade_discards_incomplete_accumulator_and_localises_ha_departure(tmp_path):
    (tmp_path / "outcome-state.json").write_text(
        json.dumps({"schema_version": 1, "current": {"interval_start": "stale"}})
    )
    (tmp_path / "acceptance-summary.json").write_text(
        json.dumps({"schema_version": 1, "status": "stale"})
    )
    recorder = OutcomeRecorder(Settings(data_dir=tmp_path))

    assert recorder._state == {"schema_version": 2, "current": None}
    assert recorder._summary["schema_version"] == 2
    parsed = recorder._parse_local_datetime("2026-08-25 07:00:00")
    assert parsed == datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)
