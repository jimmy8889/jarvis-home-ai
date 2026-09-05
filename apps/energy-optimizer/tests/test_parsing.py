from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from energy_optimizer.parsing import (
    _price_points,
    _slot_price,
    build_dispatch_grid,
    build_slots,
)


BRISBANE = ZoneInfo("Australia/Brisbane")


def test_signed_fit_and_solcast_are_preserved():
    now = datetime(2026, 8, 11, 11, 30, tzinfo=BRISBANE)
    fit = {"attributes": {"forecast": [
        {"time": now.isoformat(), "value": -0.01},
        {"time": (now + timedelta(minutes=30)).isoformat(), "value": 0.21},
    ]}}
    imports = {"attributes": {"forecast": [
        {"time": now.isoformat(), "value": 0.03},
        {"time": (now + timedelta(minutes=30)).isoformat(), "value": 0.30},
    ]}}
    solar = {"attributes": {"detailedForecast": [
        {"period_start": now.isoformat(), "pv_estimate": 10, "pv_estimate10": 7, "pv_estimate90": 11},
        {"period_start": (now + timedelta(minutes=30)).isoformat(), "pv_estimate": 9, "pv_estimate10": 5, "pv_estimate90": 10},
    ]}}
    slots = build_slots(
        now=now,
        horizon_hours=1,
        slot_minutes=30,
        timezone=BRISBANE,
        fit_entity=fit,
        import_entity=imports,
        solar_entities=[solar],
        load_forecast=lambda _: 1.5,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )
    assert slots[0].export_price == -0.01
    assert slots[1].export_price == 0.21
    assert slots[0].solar_kw == 10
    assert slots[0].solar_low_kw == 6.3


def test_local_irradiance_correction_fades_back_to_solcast_over_ninety_minutes():
    now = datetime(2026, 8, 12, 10, 0, tzinfo=BRISBANE)
    solar = {"attributes": {"detailedForecast": [
        {
            "period_start": (now + timedelta(minutes=30 * index)).isoformat(),
            "pv_estimate": 10,
            "pv_estimate10": 8,
            "pv_estimate90": 12,
        }
        for index in range(4)
    ]}}
    result = build_slots(
        now=now,
        horizon_hours=2,
        slot_minutes=30,
        timezone=BRISBANE,
        fit_entity={},
        import_entity={},
        solar_entities=[solar],
        load_forecast=lambda _: 1.0,
        calibration_ratio=1.0,
        weather_condition="sunny",
        live_solar_correction_factor=0.4,
        live_solar_correction_minutes=90,
    )

    assert result[0].solar_kw == 4.0
    assert result[1].solar_kw == 6.0
    assert result[2].solar_kw == 8.0
    assert result[3].solar_kw == 10.0


def test_incomplete_amber_horizon_uses_historical_fallback():
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BRISBANE)
    slots = build_slots(
        now=now,
        horizon_hours=2,
        slot_minutes=30,
        timezone=BRISBANE,
        fit_entity={},
        import_entity={},
        solar_entities=[],
        load_forecast=lambda _: 1.0,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )
    assert all(slot.price_source == "historical_fallback" for slot in slots)
    assert slots[-1].import_price == 0.04


def test_hybrid_dispatch_grid_is_gap_free_and_exactly_36_hours():
    now = datetime(2026, 8, 11, 12, 12, 30, tzinfo=BRISBANE)
    grid = build_dispatch_grid(
        now,
        horizon_hours=36,
        coarse_slot_minutes=30,
        fine_slot_minutes=5,
        fine_horizon_minutes=60,
    )

    assert grid[0][0] == now
    assert grid[0][1] == timedelta(minutes=2, seconds=30)
    for (start, duration), (following_start, _) in zip(grid, grid[1:]):
        assert duration.total_seconds() > 0
        assert start + duration == following_start
    assert grid[-1][0] + grid[-1][1] == now + timedelta(hours=36)
    assert sum((duration for _, duration in grid), timedelta()) == timedelta(hours=36)
    assert all(duration <= timedelta(minutes=5) for _, duration in grid[:12])
    assert any(duration == timedelta(minutes=30) for _, duration in grid[12:])


def test_live_amber_state_is_authoritative_for_remaining_active_interval():
    now = datetime(2026, 8, 11, 11, 32, tzinfo=BRISBANE)
    start = now.replace(minute=30)
    end = start + timedelta(minutes=5)
    future = end
    fit = {
        "state": "0.91",
        "attributes": {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "forecast": [
                {"time": start.isoformat(), "value": -0.01},
                {"time": future.isoformat(), "value": 0.21},
            ],
        },
    }
    imports = {
        "state": "0.44",
        "attributes": {
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "forecast": [
                {"time": start.isoformat(), "value": 0.03},
                {"time": future.isoformat(), "value": 0.30},
            ],
        },
    }

    slots = build_slots(
        now=now,
        horizon_hours=1,
        slot_minutes=30,
        amber_interval_minutes=5,
        amber_fine_horizon_minutes=60,
        timezone=BRISBANE,
        fit_entity=fit,
        import_entity=imports,
        solar_entities=[],
        load_forecast=lambda _: 1.0,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )

    assert slots[0].duration_h == 3 / 60
    assert slots[0].export_price == 0.91
    assert slots[0].import_price == 0.44
    assert slots[0].price_source == "amber_live"
    assert slots[1].start == end
    assert slots[1].export_price == 0.21
    assert slots[1].import_price == 0.30


def test_metadata_free_or_long_amber_window_is_never_live():
    now = datetime(2026, 8, 11, 11, 32, tzinfo=BRISBANE)
    invalid_windows = [
        {},
        {
            "start_time": (now - timedelta(minutes=1)).isoformat(),
            "end_time": (now + timedelta(minutes=59)).isoformat(),
        },
    ]

    for attributes in invalid_windows:
        fit = {"state": "0.91", "attributes": attributes}
        imports = {"state": "0.44", "attributes": attributes}
        result = build_slots(
            now=now,
            horizon_hours=1,
            slot_minutes=30,
            amber_interval_minutes=5,
            amber_fine_horizon_minutes=60,
            timezone=BRISBANE,
            fit_entity=fit,
            import_entity=imports,
            solar_entities=[],
            load_forecast=lambda _: 1.0,
            calibration_ratio=1.0,
            weather_condition="sunny",
        )

        assert result[0].price_source != "amber_live"
        assert result[0].export_price != 0.91
        assert result[0].import_price != 0.44


def test_fit_and_import_must_describe_the_same_live_interval():
    now = datetime(2026, 8, 11, 11, 32, tzinfo=BRISBANE)
    fit = {
        "state": "0.91",
        "attributes": {
            "start_time": now.replace(minute=30).isoformat(),
            "end_time": now.replace(minute=35).isoformat(),
        },
    }
    imports = {
        "state": "0.44",
        "attributes": {
            "start_time": now.replace(minute=31).isoformat(),
            "end_time": now.replace(minute=36).isoformat(),
        },
    }

    result = build_slots(
        now=now,
        horizon_hours=1,
        slot_minutes=30,
        amber_interval_minutes=5,
        amber_fine_horizon_minutes=60,
        timezone=BRISBANE,
        fit_entity=fit,
        import_entity=imports,
        solar_entities=[],
        load_forecast=lambda _: 1.0,
        calibration_ratio=1.0,
        weather_condition="sunny",
    )

    assert result[0].price_source != "amber_live"


def test_coarse_slot_price_is_weighted_by_actual_amber_interval_overlap():
    now = datetime(2026, 8, 11, 12, 7, tzinfo=BRISBANE)
    forecast = [
        {
            "start_time": "2026-08-11T12:00:00+10:00",
            "end_time": "2026-08-11T12:10:00+10:00",
            "value": 0.10,
        },
        {
            "start_time": "2026-08-11T12:10:00+10:00",
            "end_time": "2026-08-11T12:30:00+10:00",
            "value": 0.40,
        },
        {
            "start_time": "2026-08-11T12:30:00+10:00",
            "end_time": "2026-08-11T12:37:00+10:00",
            "value": -0.20,
        },
    ]

    price, source = _slot_price(
        _price_points({"attributes": {"forecast": forecast}}, BRISBANE),
        now,
        timedelta(minutes=30),
        export=True,
    )

    # The 12:07-12:37 slot overlaps 3, 20 and 7 minutes respectively.
    expected = (3 * 0.10 + 20 * 0.40 + 7 * -0.20) / 30
    assert price == pytest.approx(expected)
    assert source == "amber"


def test_partial_amber_overlap_cannot_dominate_uncovered_slot_duration():
    start = datetime(2026, 8, 11, 12, 0, tzinfo=BRISBANE)
    points = _price_points({
        "attributes": {
            "forecast": [{
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(minutes=5)).isoformat(),
                "value": 0.64,
            }],
        },
    }, BRISBANE)

    price, source = _slot_price(
        points,
        start,
        timedelta(minutes=30),
        export=True,
    )

    # Midday fallback FIT is zero, so only the covered five minutes carry the
    # Amber value.  Averaging over covered seconds alone would incorrectly
    # report the entire half-hour at $0.64/kWh.
    assert price == pytest.approx(0.64 * 5 / 30)
    assert source == "partial_amber_fallback"
