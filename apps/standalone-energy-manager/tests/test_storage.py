from datetime import UTC, date, datetime, timedelta
import json

import pytest

from energy_manager.storage import Storage


async def test_price_observation_keeps_first_receipt_per_revision(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    first = ("amber", "feedIn", "2026-08-25T00:00:00+00:00", "2026-08-25T00:05:00+00:00", 0.12, "2026-08-25T00:00:01+00:00", None, 0, "{}")
    second = (*first[:5], "2026-08-25T00:00:03+00:00", *first[6:])
    assert await storage.record_price(first) is True
    assert await storage.record_price(second) is False


async def test_daily_outcome_accumulates_completed_intervals(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    day = date(2026, 8, 25)
    first = await storage.add_daily_outcome(day, {"interval_start": datetime(2026, 8, 25, tzinfo=UTC).isoformat(), "export_kwh": 1.2})
    second = await storage.add_daily_outcome(day, {"interval_start": datetime(2026, 8, 25, 0, 5, tzinfo=UTC).isoformat(), "export_kwh": 0.8})
    assert first["intervals"] == 1
    assert second["intervals"] == 2
    assert second["export_kwh"] == 2.0


async def test_daily_outcome_uses_duration_weighted_averages_and_explicit_rollups(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    day = date(2026, 8, 25)
    first_start = datetime(2026, 8, 25, tzinfo=UTC).isoformat()
    second_start = datetime(2026, 8, 25, 0, 15, tzinfo=UTC).isoformat()

    await storage.add_daily_outcome(day, {
        "interval_start": first_start,
        "duration_hours": 0.25,
        "average_pv_kw": 4.0,
        "average_fit_per_kwh": 0.10,
        "export_attribution_confidence_score": 0.2,
        "export_attribution_confidence_label": "low",
        "export_attribution_method": "priority_inference_v1",
        "quality_note": "initial",
        "inferred_attribution": True,
        "max_abs_meter_balance_error_kw": 0.7,
        "export_kwh": 1.0,
        "battery_export_revenue": 0.10,
        "wear_cost": 0.03,
    })
    daily = await storage.add_daily_outcome(day, {
        "interval_start": second_start,
        "duration_hours": 0.75,
        "average_pv_kw": 12.0,
        "average_fit_per_kwh": 0.30,
        "export_attribution_confidence_score": 0.8,
        "export_attribution_confidence_label": "high",
        "export_attribution_method": "priority_inference_v1",
        "quality_note": "stable",
        "inferred_attribution": True,
        "max_abs_meter_balance_error_kw": 0.3,
        "export_kwh": 2.0,
        "battery_export_revenue": 0.60,
        "wear_cost": 0.05,
    })

    assert daily["intervals"] == 2
    assert daily["duration_hours"] == 1.0
    assert daily["average_pv_kw"] == pytest.approx(10.0)
    assert daily["average_fit_per_kwh"] == pytest.approx(0.25)
    assert daily["export_attribution_confidence_score"] == pytest.approx(0.65)
    assert daily["export_attribution_confidence_label"] == "medium"
    assert daily["max_abs_meter_balance_error_kw"] == 0.7
    assert daily["export_kwh"] == 3.0
    assert daily["battery_export_revenue"] == pytest.approx(0.70)
    assert daily["wear_cost"] == pytest.approx(0.08)
    assert daily["export_attribution_method"] == "priority_inference_v1"
    assert daily["quality_note"] == "stable"
    assert daily["inferred_attribution"] is True
    assert daily["first_interval_start"] == first_start
    assert daily["last_interval_start"] == second_start


async def test_daily_outcome_clamps_confidence_and_does_not_sum_numeric_metadata(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    day = date(2026, 8, 25)
    first = await storage.add_daily_outcome(day, {
        "interval_start": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
        "duration_hours": 0.5,
        "export_attribution_confidence_score": 4.0,
        "schema_version": 3,
    })
    second = await storage.add_daily_outcome(day, {
        "interval_start": datetime(2026, 8, 25, 0, 30, tzinfo=UTC).isoformat(),
        "duration_hours": 0.5,
        "export_attribution_confidence_score": -2.0,
        "schema_version": 4,
    })

    assert first["export_attribution_confidence_score"] == 1.0
    assert second["export_attribution_confidence_score"] == 0.5
    assert second["export_attribution_confidence_label"] == "low"
    assert second["schema_version"] == 4


async def test_daily_outcome_can_be_rebuilt_from_authoritative_intervals(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    day = date(2026, 8, 25)
    intervals = [
        {
            "interval_start": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
            "duration_hours": 0.25,
            "average_grid_kw": -2.0,
            "export_kwh": 0.5,
        },
        {
            "interval_start": datetime(2026, 8, 25, 0, 15, tzinfo=UTC).isoformat(),
            "duration_hours": 0.75,
            "average_grid_kw": -6.0,
            "export_kwh": 4.5,
        },
    ]
    for interval in intervals:
        await storage.execute(
            "INSERT INTO five_minute_outcomes(interval_start,payload) VALUES(?,?)",
            (interval["interval_start"], json.dumps(interval)),
        )
    await storage.merge_daily_outcome(day, {
        "intervals": 2,
        "duration_hours": 1.0,
        "average_grid_kw": -8.0,
        "export_kwh": 5.0,
    })

    rebuilt = await storage.rebuild_daily_outcome(day, "Australia/Brisbane")

    assert rebuilt["intervals"] == 2
    assert rebuilt["duration_hours"] == 1.0
    assert rebuilt["average_grid_kw"] == pytest.approx(-5.0)
    assert rebuilt["export_kwh"] == 5.0


async def test_latest_plan_and_lease_survive_storage_reopen(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    storage = Storage(path)
    payload = {"plan_id": "abc", "generated_at": "2026-08-25T00:00:00+00:00"}
    await storage.plan("abc", payload["generated_at"], "2026-08-26T12:00:00+00:00", payload)
    await storage.lease("ev", datetime(2026, 8, 25, 1, tzinfo=UTC), {"on": True, "amps": 6})
    reopened = Storage(path)
    assert await reopened.latest_plan() == payload


async def test_large_plan_journal_is_bounded_to_recent_revisions(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    for index in range(55):
        generated = (datetime(2026, 8, 25, tzinfo=UTC) + timedelta(minutes=index)).isoformat()
        await storage.plan(
            f"plan-{index}", generated, "2026-08-27T00:00:00+00:00",
            {"plan_id": f"plan-{index}", "generated_at": generated},
        )
    assert await storage.plan_count() == 48
    assert (await storage.latest_plan())["plan_id"] == "plan-54"
