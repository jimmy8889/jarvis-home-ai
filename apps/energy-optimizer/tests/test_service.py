from __future__ import annotations

from datetime import datetime, timedelta, timezone

from energy_optimizer.models import DispatchInterval, Plan
from energy_optimizer.service import dashboard_plan_attributes


def test_dashboard_plan_attributes_contains_full_compact_horizon() -> None:
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
    assert "duration_minutes" not in attributes["intervals"][0]
    assert "pv_curtailment_kw" not in attributes["intervals"][0]
    assert attributes["ev_power_target_kw"] == 0.0
    assert attributes["ev_charge_source"] == "none"
    assert attributes["ev_solar_energy_kwh"] == 0.0
    assert attributes["ev_fallback_energy_kwh"] == 0.0
