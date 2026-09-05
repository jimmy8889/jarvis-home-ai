from dataclasses import replace
from datetime import UTC, datetime, timedelta

from energy_manager.config import Settings
from energy_manager.models import DeviceState, PriceInterval, Telemetry
from energy_manager.planner import RollingPlanner
from energy_manager.policy import Policy


class Amber:
    def __init__(self, start: datetime):
        self.forecast = {"feedIn": [], "general": []}
        for index in range(24 * 12):
            at = start + timedelta(minutes=5 * index)
            fit = 1.0 if index in {5, 6} else 0.02
            self.forecast["feedIn"].append(PriceInterval("amber", "feedIn", at, at + timedelta(minutes=5), fit))
            self.forecast["general"].append(PriceInterval("amber", "general", at, at + timedelta(minutes=5), 0.30))


def test_rolling_plan_is_36_hours_and_marks_profitable_export() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=95, soh_pct=97)
    settings = replace(Settings(), battery_evening_target_pct=5)
    plan = RollingPlanner(settings).build(now, telemetry, DeviceState(), Amber(now), None, 3.05)  # type: ignore[arg-type]
    assert len(plan["points"]) == 36 * 12
    assert plan["export_windows"]
    assert plan["export_windows"][0]["max_price_per_kwh"] == 1.0
    assert plan["summary"]["battery_export_kwh"] > 0
    assert plan["summary"]["battery_export_revenue"] > 0
    assert plan["summary"]["predicted_soc_min_pct"] >= Settings().battery_floor_pct
    assert plan["summary"]["priced_horizon_hours"] == 24.0
    assert plan["schema_version"] == 3
    assert plan["narrative"]["current_summary"]
    assert set(plan["narrative"]["groups"]) == {"Now", "Next", "Today", "Overnight"}
    assert all(point["flow"]["conserved"] for point in plan["points"])
    window = plan["export_windows"][0]
    for field in ("battery_export_kwh", "solar_export_kwh", "battery_export_revenue", "battery_export_wear_cost", "battery_export_net_benefit", "min_price_per_kwh", "max_price_per_kwh"):
        assert field in window
    summary = plan["summary"]
    assert summary["total_export_revenue"] == round(summary["solar_export_revenue"] + summary["battery_export_revenue"], 2)
    assert summary["expected_house_load_kwh"] == summary["expected_total_house_load_kwh"]
    assert summary["expected_house_load_kwh"] >= summary["expected_ordinary_house_load_kwh"]
    assert summary["battery_export_net_benefit"] == round(summary["battery_export_revenue"] - summary["battery_export_wear_cost"] - summary["battery_export_retained_value"], 2)


def test_hot_water_falls_back_to_latest_blocks_without_solar() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=80, soh_pct=97)
    plan = RollingPlanner(replace(Settings(), control_enabled=True)).build(now, telemetry, DeviceState(), Amber(now), None, 0)  # type: ignore[arg-type]
    hot = plan["hot_water"]
    assert hot["blocks"] == 37
    deadline = datetime.fromisoformat(hot["deadline"])
    assert datetime.fromisoformat(hot["planned_end"]) == deadline
    assert len(hot["daily_schedules"]) >= 2
    assert hot["daily_schedules"][1]["scheduled_blocks"] == 37


def test_hot_water_current_interval_is_not_deferred_at_replan_boundary() -> None:
    boundary = datetime(2026, 8, 25, 2, 45, tzinfo=UTC)
    now = boundary + timedelta(seconds=5)
    telemetry = Telemetry(pv_kw=20, load_kw=1, grid_kw=0, battery_kw=-19, soc_pct=65, soh_pct=97)
    amber = Amber(boundary)

    class Solar:
        providers = {
            "forecast-solar": {
                "roofs": {
                    "north": {"watts": {(boundary + timedelta(minutes=5 * index)).isoformat(): 10000 for index in range(40)}},
                    "south": {"watts": {(boundary + timedelta(minutes=5 * index)).isoformat(): 10000 for index in range(40)}},
                }
            }
        }

    plan = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), amber, Solar(), 0.033)  # type: ignore[arg-type]
    assert plan["points"][0]["start"] == boundary.isoformat()
    assert plan["points"][0]["hot_water"] is True
    assert plan["hot_water"]["planned_start"] == boundary.isoformat()


def test_running_hot_water_keeps_current_block_committed() -> None:
    boundary = datetime(2026, 8, 25, 2, 45, tzinfo=UTC)
    now = boundary + timedelta(seconds=5)
    telemetry = Telemetry(pv_kw=6, load_kw=4.7, grid_kw=0, battery_kw=0, soc_pct=65, soh_pct=97)
    amber = Amber(boundary)
    # Make all later slots economically preferable. An active element must
    # nevertheless retain the current block instead of chattering off.
    amber.forecast["feedIn"][0].price_per_kwh = 1.0
    devices = DeviceState(hot_water_on=True, hot_water_power_kw=3.7)
    plan = RollingPlanner(Settings()).build(now, telemetry, devices, amber, None, 1.0)  # type: ignore[arg-type]
    assert plan["points"][0]["hot_water"] is True


def test_hot_water_complete_today_still_schedules_tomorrow() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=80, soh_pct=97)
    plan = RollingPlanner(replace(Settings(), control_enabled=True)).build(now, telemetry, DeviceState(), Amber(now), None, 3.05)  # type: ignore[arg-type]
    schedules = plan["hot_water"]["daily_schedules"]
    assert schedules[0]["complete"] is True
    assert schedules[0]["scheduled_blocks"] == 0
    assert schedules[1]["scheduled_blocks"] == 37
    assert plan["hot_water"]["planned_start"] == schedules[1]["planned_start"]


def test_evening_target_is_an_export_floor_not_a_house_or_ev_floor() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=95, soh_pct=100)
    plan = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), Amber(now), None, 3.05)  # type: ignore[arg-type]
    first = plan["points"][0]
    assert first["export_protected_soc_pct"] == 99
    assert first["protected_soc_pct"] < first["export_protected_soc_pct"]
    assert first["battery_export_kw"] == 0


def test_ev_plan_explains_immediate_below_minimum_charge() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=80, soh_pct=97)
    devices = DeviceState(ev_soc_pct=10, ev_home=True, ev_plugged=True)
    plan = RollingPlanner(Settings()).build(now, telemetry, devices, Amber(now), None, 3.05)  # type: ignore[arg-type]
    assert plan["ev"]["planned_start"] == now.isoformat()
    assert "immediately" in plan["ev"]["recommendation"]
    assert plan["ev"]["planned_input_kwh"] > 0
    assert plan["summary"]["expected_ev_input_kwh"] == plan["ev"]["planned_input_kwh"]
    assert any(point["ev_kw"] > 0 for point in plan["points"])


def test_ev_plan_shows_optional_solar_charging_at_very_low_fit() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    amber = Amber(now)
    for interval in amber.forecast["feedIn"]:
        interval.price_per_kwh = -0.01

    class Solar:
        providers = {
            "forecast-solar": {
                "roofs": {
                    "north": {"watts": {now.isoformat(): 12000}},
                    "south": {"watts": {now.isoformat(): 0}},
                }
            }
        }

    telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=1, soc_pct=80, soh_pct=97)
    devices = DeviceState(ev_soc_pct=40, ev_home=True, ev_plugged=True, ev_limit_pct=80)
    plan = RollingPlanner(Settings()).build(now, telemetry, devices, amber, Solar(), 3.05)  # type: ignore[arg-type]
    assert plan["ev"]["planned_start"] == now.isoformat()
    assert "forecast solar" in plan["ev"]["recommendation"]
    assert plan["ev"]["planned_input_kwh"] > 0
    assert any(point["ev_kw"] > 0 for point in plan["points"])


def test_morning_fit_defers_pv_charge_only_when_later_solar_is_conservatively_sufficient() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)  # 10am Brisbane
    amber = Amber(now)
    for interval in amber.forecast["feedIn"]:
        interval.price_per_kwh = 0.20
    for interval in amber.forecast["feedIn"][1:]:
        interval.price_per_kwh = 0.01

    class SunnyLater:
        providers = {
            "forecast-solar": {
                "roofs": {
                    "north": {"watts": {(now + timedelta(hours=hour)).isoformat(): 12000 for hour in range(8)}},
                    "south": {"watts": {(now + timedelta(hours=hour)).isoformat(): 12000 for hour in range(8)}},
                }
            }
        }

    telemetry = Telemetry(pv_kw=20, load_kw=2, grid_kw=0, battery_kw=0, soc_pct=50, soh_pct=100)
    plan = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), amber, SunnyLater(), 3.05)  # type: ignore[arg-type]
    assert plan["points"][0]["battery_charge_deferred"] is True
    assert plan["points"][0]["battery_charge_kw"] == 0
    assert plan["points"][0]["battery_charge_defer_budget_kwh"] >= (
        plan["points"][0]["battery_charge_required_to_evening_kwh"]
        * Settings().morning_defer_energy_margin
    )
    assert plan["points"][0]["battery_charge_lower_fit_budget_kwh"] > 0
    assert any(action["title"] == "Defer battery charging for morning FIT" for action in plan["narrative"]["next_actions"])

    class CloudyLater:
        providers = {"forecast-solar": {"roofs": {"north": {"watts": {now.isoformat(): 12000}}, "south": {"watts": {now.isoformat(): 12000}}}}}

    cloudy = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), amber, CloudyLater(), 3.05)  # type: ignore[arg-type]
    assert cloudy["points"][0]["battery_charge_deferred"] is False
    assert cloudy["points"][0]["battery_charge_kw"] > 0
    assert cloudy["points"][0]["protected_soc_pct"] > plan["points"][0]["protected_soc_pct"]

    for interval in amber.forecast["feedIn"]:
        interval.price_per_kwh = 0.20
    equal_price = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), amber, SunnyLater(), 3.05)  # type: ignore[arg-type]
    assert equal_price["points"][0]["battery_charge_deferred"] is False


def test_morning_deferral_does_not_double_book_selected_trip_solar() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    amber = Amber(now)
    for interval in amber.forecast["feedIn"]:
        interval.price_per_kwh = 0.20
    for interval in amber.forecast["feedIn"][1:]:
        interval.price_per_kwh = 0.01

    class ModerateLater:
        providers = {
            "forecast-solar": {
                "roofs": {
                    "north": {"watts": {(now + timedelta(hours=hour)).isoformat(): 7000 for hour in range(8)}},
                    "south": {"watts": {(now + timedelta(hours=hour)).isoformat(): 7000 for hour in range(8)}},
                }
            }
        }

    telemetry = Telemetry(pv_kw=12, load_kw=2, grid_kw=0, battery_kw=0, soc_pct=50, soh_pct=100)
    no_trip = RollingPlanner(Settings()).build(now, telemetry, DeviceState(), amber, ModerateLater(), 3.05)  # type: ignore[arg-type]
    assert no_trip["points"][0]["battery_charge_deferred"] is True
    settings = replace(
        Settings(), ev_trip_profile="target_100",
        ev_trip_deadline=(now + timedelta(hours=21)).isoformat(),
    )
    devices = DeviceState(ev_soc_pct=50, ev_home=True, ev_plugged=True, ev_limit_pct=100)
    selected_trip = RollingPlanner(settings).build(now, telemetry, devices, amber, ModerateLater(), 3.05)  # type: ignore[arg-type]
    assert selected_trip["points"][0]["battery_charge_deferred"] is False


def test_planner_and_live_policy_share_export_power_ramp() -> None:
    now = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
    amber = Amber(now)
    for interval in amber.forecast["feedIn"]:
        interval.price_per_kwh = 0.20
        interval.received_at = now
    for interval in amber.forecast["general"]:
        interval.price_per_kwh = 0.02
        interval.received_at = now
    settings = replace(Settings(), battery_evening_target_pct=5)
    telemetry = Telemetry(pv_kw=0, load_kw=1.7, grid_kw=0, battery_kw=0, soc_pct=95, soh_pct=100)
    plan = RollingPlanner(settings).build(now, telemetry, DeviceState(), amber, None, 3.05)  # type: ignore[arg-type]
    point = plan["points"][0]
    live = Policy(settings).command(
        telemetry, DeviceState(), amber.forecast["feedIn"][0], amber.forecast["general"][0],
        0, 3.05, amber.forecast["feedIn"], now=now,
        protected_reserve_override_pct=point["protected_soc_pct"],
        export_reserve_override_pct=point["export_protected_soc_pct"],
        hot_water_scheduled=False, ev_scheduled_kw=0,
    )
    assert live.mode == "export"
    assert point["battery_target_kw"] == live.battery_target_kw
