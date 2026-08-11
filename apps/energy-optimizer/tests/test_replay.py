from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from energy_optimizer.config import Settings
from energy_optimizer.replay import run_replay


TZ = ZoneInfo("Australia/Brisbane")


def test_replay_reports_cashflow_targets_and_flexible_loads():
    start = datetime(2026, 7, 13, tzinfo=TZ)
    intervals = []
    for index in range(48):
        when = start + timedelta(minutes=30 * index)
        daylight = 7 <= when.hour < 17
        solar = 8.0 if daylight else 0.0
        load = 1.5
        export_price = -0.05 if 11 <= when.hour < 13 else (0.25 if 5 <= when.hour < 7 else 0.06)
        grid = load - solar
        intervals.append({
            "timestamp": when.isoformat(),
            "solar_kw": solar,
            "load_kw": load,
            "grid_kw": grid,
            "soc_pct": 8 if when.hour == 7 else (99 if when.hour >= 16 else 50),
            "import_price": 0.20,
            "export_price": export_price,
        })
    payload = {
        "intervals": intervals,
        "daily": [{
            "date": "2026-07-13",
            "solar_kwh": 80,
            "home_kwh": 36,
            "grid_import_kwh": 10,
            "grid_export_kwh": 44,
            "battery_discharge_kwh": 20,
        }],
        "known_baseline": {"morning_fit_reserve_blocked_pct": 11.7},
        "forecast_baseline": {"p50_mae_kwh": 12.1, "p10_p90_coverage_pct": 57},
    }

    report = run_replay(payload, Settings(battery_capacity_kwh=10.0))

    assert report["period"]["completed_days"] == 1
    assert report["baseline"]["solar_kwh_per_day"] == 80
    assert report["baseline"]["morning_fit_reserve_blocked_pct"] == 11.7
    assert report["optimized_hindsight"]["hot_water_completion_pct"] == 100
    assert report["forecast_baseline"]["p50_mae_kwh"] == 12.1
    assert report["days"][0]["baseline_negative_fit_export_kwh"] > 0
