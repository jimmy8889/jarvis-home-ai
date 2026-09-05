from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

from energy_optimizer.state import LearningState


BRISBANE = ZoneInfo("Australia/Brisbane")


def test_schema_one_migration_drops_duplicated_daily_counters_and_false_confidence(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "load_slots": {"1:12": {"mean": 2.4, "count": 96}},
        "solar_ratios": [1.4, 1.4, 1.4],
        "daily": {"2026-08-17": {"forecast_kwh": 90, "actual_kwh": 102}},
        "solar_power_observation": {"at": "2026-08-17T12:00:00+10:00"},
    }))

    state = LearningState(path)

    assert state.data["schema_version"] == 3
    assert state.data["daily"] == {}
    assert state.data["solar_ratios"] == [1.008]
    assert state.data["solar_power_observation"] == {}
    assert state.data["load_slots"]["1:12"] == {"mean": 2.4, "count": 3}
    assert state.data["migration"]["daily_observations_reset"] is True


def test_load_learning_samples_each_physical_five_minute_bucket_once(tmp_path):
    state = LearningState(tmp_path / "learning.json")
    when = datetime(2026, 8, 18, 9, 1, tzinfo=BRISBANE)

    assert state.update_load(when, 2.0) is True
    first = dict(state.data["load_slots"][state._load_key(when)])
    assert state.update_load(when + timedelta(minutes=3), 8.0) is False
    assert state.data["load_slots"][state._load_key(when)] == first
    assert state.update_load(when + timedelta(minutes=5), 3.0) is True
    assert state.data["load_slots"][state._load_key(when)]["count"] == 2
    assert state.update_load(when + timedelta(minutes=2), 9.0) is False
    assert state.data["load_slots"][state._load_key(when)]["count"] == 2


def test_daily_energy_counter_requires_current_date_and_new_timestamp(tmp_path):
    state = LearningState(tmp_path / "learning.json")
    current = datetime(2026, 8, 18, 12, 0, tzinfo=BRISBANE)
    stale = current - timedelta(days=1)

    assert state.observe_solar_day(
        "2026-08-18", 90.0, 20.0, observed_at=stale
    ) is False
    assert state.data["daily"] == {}
    assert state.observe_solar_day(
        "2026-08-18", 90.0, 20.0, observed_at=current
    ) is True
    assert state.observe_solar_day(
        "2026-08-18", 90.0, 99.0, observed_at=current
    ) is False
    assert state.data["daily"]["2026-08-18"]["actual_kwh"] == 20.0


def test_reset_persists_a_clean_schema_three_state(tmp_path):
    path = tmp_path / "learning.json"
    state = LearningState(path)
    state.data["daily"]["bad"] = {"actual_kwh": 100}

    state.reset()
    reloaded = LearningState(path)

    assert reloaded.data["schema_version"] == 3
    assert reloaded.data["daily"] == {}
    assert "manual_reset_at" in reloaded.data["migration"]


def test_corrupt_schema_two_members_are_safely_normalized(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "load_slots": ["wrong"],
        "solar_ratios": ["bad", 1.1, 99],
        "daily": "wrong",
        "solar_power_observation": [],
        "last_load_observation_bucket": 123,
        "migration": "wrong",
    }))

    state = LearningState(path)

    assert state.data["load_slots"] == {}
    assert state.data["solar_ratios"] == [1.1]
    assert state.data["daily"] == {}
    assert state.data["solar_power_observation"] == {}
    assert state.data["last_load_observation_bucket"] is None


def test_corrupt_nested_learning_values_cannot_break_finalization(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "load_slots": {},
        "solar_ratios": [1.0],
        "daily": {
            "not-a-date": {"forecast_kwh": 90, "actual_kwh": 80},
            "2026-08-17": {
                "forecast_kwh": "bad",
                "actual_kwh": float("nan"),
                "curtailed_kwh": 9999,
                "actual_observed_at": "not-a-time",
            },
        },
        "solar_power_observation": {
            "at": "not-a-time",
            "curtailed_kw": "bad",
        },
        "last_load_observation_bucket": "not-a-time",
    }))

    state = LearningState(path)
    state.finalize_previous_days("2026-08-18")

    assert "not-a-date" not in state.data["daily"]
    assert state.data["daily"] == {}
    assert state.solar_calibration_ratio == 1.0


def test_roof_learning_is_uncurtailed_time_binned_and_deduplicated(tmp_path):
    state = LearningState(tmp_path / "learning.json")
    when = datetime(2026, 8, 18, 9, 1, tzinfo=BRISBANE)

    assert state.observe_roof_power(
        when,
        roof="north",
        expected_kw=4.0,
        actual_kw=3.6,
        uncurtailed=True,
    ) is True
    assert state.observe_roof_power(
        when + timedelta(minutes=2),
        roof="north",
        expected_kw=4.0,
        actual_kw=4.0,
        uncurtailed=True,
    ) is False
    assert state.observe_roof_power(
        when + timedelta(minutes=5),
        roof="north",
        expected_kw=4.0,
        actual_kw=3.6,
        uncurtailed=False,
    ) is False
    for offset in (5, 10):
        assert state.observe_roof_power(
            when + timedelta(minutes=offset),
            roof="north",
            expected_kw=4.0,
            actual_kw=3.6,
            uncurtailed=True,
        ) is True

    assert state.roof_correction(when, "north") == 0.9
    report = state.roof_calibration_report["north"]
    assert report["observations"] == 3
    assert report["bias"] == 0.9
    assert report["time_bins"] == 1


def test_schema_two_migrates_without_discarding_valid_global_learning(tmp_path):
    path = tmp_path / "learning.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "load_slots": {"1:12": {"mean": 2.4, "count": 4}},
        "solar_ratios": [1.1],
        "daily": {},
    }))

    state = LearningState(path)

    assert state.data["schema_version"] == 3
    assert state.data["load_slots"]["1:12"]["mean"] == 2.4
    assert state.data["solar_ratios"] == [1.1]
    assert state.data["migration"]["roof_calibration_started"] is True
