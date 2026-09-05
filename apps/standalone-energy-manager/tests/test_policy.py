from dataclasses import replace
from datetime import UTC, datetime, timedelta

from energy_manager.config import Settings
from energy_manager.models import DeviceState, PriceInterval, Telemetry
from energy_manager.policy import Policy


NOW = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)  # midday Brisbane


def telemetry(**updates) -> Telemetry:
    base = Telemetry(
        measured_at=NOW,
        pv_kw=8,
        load_kw=2,
        grid_kw=0,
        battery_kw=0,
        soc_pct=70,
        soh_pct=97,
    )
    return replace(base, **updates)


def price(value: float, channel: str = "feedIn") -> PriceInterval:
    return PriceInterval("amber", channel, NOW - timedelta(minutes=1), NOW + timedelta(minutes=4), value, received_at=NOW)


def test_negative_fit_is_zero_export_and_never_battery_export() -> None:
    command = Policy(Settings()).command(telemetry(), DeviceState(), price(-0.01), price(0.20, "general"), 20, 3.05, now=NOW)
    assert command.zero_export is True
    assert command.mode == "self_consume"
    assert command.battery_target_kw == 0


def test_profitable_export_respects_minimum_sell_price() -> None:
    settings = replace(Settings(), min_sell_price_per_kwh=0.20)
    policy = Policy(settings)
    low = policy.command(telemetry(), DeviceState(), price(0.19), None, 8, 3.05, now=NOW)
    high = policy.command(telemetry(), DeviceState(), price(0.25), None, 8, 3.05, now=NOW)
    assert low.mode == "self_consume"
    assert high.mode == "export"
    assert high.battery_target_kw > 0


def test_protected_surplus_above_sell_floor_is_not_blocked_by_live_import_price() -> None:
    settings = replace(Settings(), min_sell_price_per_kwh=0.10)
    command = Policy(settings).command(
        telemetry(pv_kw=0), DeviceState(), price(0.108), price(0.34, "general"), 0, 3.05, now=NOW
    )
    assert command.mode == "export"
    assert command.battery_target_kw > 0


def test_live_sell_floor_case_exports_only_above_protected_reserve() -> None:
    settings = replace(Settings(), min_sell_price_per_kwh=0.10)
    devices = DeviceState()
    above = Policy(settings).command(
        telemetry(pv_kw=0, load_kw=1.3, soc_pct=91.6), devices,
        price(0.1018529), price(0.3551349, "general"), 0, 3.05,
        now=NOW, protected_reserve_override_pct=44.9,
        export_reserve_override_pct=44.9,
    )
    assert above.mode == "export"
    assert above.site_export_target_kw > 0
    assert above.battery_target_kw > above.site_export_target_kw

    protected = Policy(settings).command(
        telemetry(pv_kw=0, load_kw=1.3, soc_pct=45.2), devices,
        price(0.1018529), price(0.3551349, "general"), 0, 3.05,
        now=NOW, protected_reserve_override_pct=44.9,
        export_reserve_override_pct=44.9,
    )
    assert protected.mode == "self_consume"
    assert protected.battery_target_kw == 0


def test_high_fit_can_exceed_import_avoidance_wear_and_sell_floor() -> None:
    settings = replace(Settings(), min_sell_price_per_kwh=0.10)
    command = Policy(settings).command(
        telemetry(), DeviceState(), price(0.50), price(0.34, "general"), 0, 3.05, now=NOW
    )
    assert command.mode == "export"
    assert command.battery_target_kw > 0


def test_hot_water_positive_fit_requires_measured_solar() -> None:
    command = Policy(Settings()).command(
        telemetry(pv_kw=1, load_kw=1), DeviceState(), price(0.05), None, 15, 0, now=NOW
    )
    assert command.hot_water_on is False


def test_hot_water_fixed_timer_ignores_price_forecast_and_completed_runtime() -> None:
    settings = replace(Settings(), hot_water_fixed_timer=True)
    command = Policy(settings).command(
        telemetry(pv_kw=0, load_kw=2), DeviceState(), price(2.00), None, 0, 3.05, now=NOW
    )
    assert command.hot_water_on is True
    assert command.hot_water_source == "fixed_timer_grid"
    assert command.reason == "hot_water_fixed_timer_grid_only"


def test_hot_water_fixed_timer_is_off_outside_11am_to_2pm() -> None:
    settings = replace(Settings(), hot_water_fixed_timer=True)
    before = datetime(2026, 8, 25, 0, 59, tzinfo=UTC)  # 10:59 Brisbane
    after = datetime(2026, 8, 25, 4, 0, tzinfo=UTC)  # 14:00 Brisbane
    assert Policy(settings).command(telemetry(), DeviceState(), None, None, 0, 0, now=before).hot_water_on is False
    assert Policy(settings).command(telemetry(), DeviceState(), None, None, 0, 0, now=after).hot_water_on is False


def test_hot_water_away_master_overrides_fixed_timer() -> None:
    settings = replace(Settings(), hot_water_enabled=False, hot_water_fixed_timer=True)
    command = Policy(settings).command(
        telemetry(pv_kw=20, load_kw=1), DeviceState(), price(-1.00), None, 20, 0, now=NOW
    )
    assert command.hot_water_on is False
    assert command.hot_water_source == "away"


def test_hot_water_negative_fit_can_use_uncurtailed_potential() -> None:
    command = Policy(Settings()).command(
        telemetry(pv_kw=1, load_kw=1), DeviceState(), price(-0.01), None, 15, 0,
        now=NOW, expected_pv_measured_at=NOW
    )
    assert command.hot_water_on is True
    assert command.zero_export is True


def test_hot_water_negative_fit_without_solar_waits_for_rescue() -> None:
    command = Policy(Settings()).command(
        telemetry(pv_kw=0, load_kw=2), DeviceState(), price(-0.01), None, 0, 0, now=NOW
    )
    assert command.hot_water_on is False
    assert command.hot_water_source == "off"


def test_cached_amber_forecast_is_valid_at_exact_boundary() -> None:
    cached = price(0.25)
    cached.estimate = True
    cached.received_at = NOW - timedelta(hours=2)
    command = Policy(Settings()).command(telemetry(), DeviceState(), cached, None, 8, 3.05, now=NOW)
    assert command.mode == "export"


def test_hot_water_source_is_off_after_deadline() -> None:
    evening = datetime(2026, 8, 25, 8, 45, tzinfo=UTC)
    command = Policy(Settings()).command(
        telemetry(), DeviceState(), None, None, 0, 0, now=evening
    )
    assert command.hot_water_on is False
    assert command.hot_water_source == "off"


def test_ev_below_40_charges_from_energy_above_reserve() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=30, ev_limit_pct=80)
    command = Policy(Settings()).command(telemetry(soc_pct=80), devices, price(0.05), None, 8, 3.05, now=NOW)
    assert command.ev_on is True
    assert 6 <= command.ev_amps <= 16


def test_ev_stops_at_reserve_when_grid_not_allowed_and_no_solar() -> None:
    settings = replace(Settings(), ev_grid_allowed=False)
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=30, ev_limit_pct=80)
    command = Policy(settings).command(telemetry(pv_kw=0, load_kw=2, soc_pct=5), devices, price(0.05), None, 0, 3.05, now=NOW)
    assert command.ev_on is False


def test_opportunistic_fit_threshold_is_configurable() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=50, ev_limit_pct=80)
    low = Policy(replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.03)).command(
        telemetry(pv_kw=12, load_kw=1), devices, price(0.025), None, 12, 3.05, now=NOW
    )
    high = Policy(replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.02)).command(
        telemetry(pv_kw=12, load_kw=1), devices, price(0.025), None, 12, 3.05, now=NOW
    )
    assert low.ev_on is True
    assert high.ev_on is False


def test_hot_water_already_on_does_not_self_cancel_from_its_own_load() -> None:
    devices = DeviceState(hot_water_on=True, hot_water_power_kw=3.7)
    command = Policy(Settings()).command(
        telemetry(pv_kw=6.3, load_kw=5.7), devices, price(0.02), None, 6.3, 0,
        now=NOW, expected_pv_measured_at=NOW,
    )
    assert command.hot_water_on is True


def test_stale_expected_pv_cannot_start_negative_fit_flexible_loads() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=50, ev_limit_pct=80)
    stale = Policy(Settings()).command(
        telemetry(pv_kw=0, load_kw=1), devices, price(-0.01), None, 15, 0,
        now=NOW, expected_pv_measured_at=NOW - timedelta(minutes=2),
    )
    assert stale.hot_water_on is False
    assert stale.ev_on is False
    fresh = Policy(Settings()).command(
        telemetry(pv_kw=0, load_kw=1), devices, price(-0.01), None, 15, 0,
        now=NOW, expected_pv_measured_at=NOW,
    )
    assert fresh.hot_water_on is True
    assert fresh.ev_on is True


def test_forecast_reserve_override_blocks_non_grid_minimum_ev_charge() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=30, ev_limit_pct=80)
    command = Policy(Settings()).command(
        telemetry(pv_kw=0, load_kw=2, soc_pct=35), devices, price(0.05), None, 0, 3.05,
        now=NOW, protected_reserve_override_pct=35,
    )
    assert command.protected_soc_pct == 35
    assert command.ev_on is False
    too_little_headroom = Policy(Settings()).command(
        telemetry(pv_kw=0, load_kw=2, soc_pct=35.6), devices, price(0.05), None, 0, 3.05,
        now=NOW, protected_reserve_override_pct=35,
    )
    assert too_little_headroom.ev_on is False


def test_ev_grid_import_feedback_ramps_down_when_grid_is_disabled() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=50, ev_limit_pct=80, ev_amps=12)
    baseline = Policy(Settings()).command(
        telemetry(pv_kw=15, load_kw=2, grid_kw=0), devices, price(0), None, 15, 3.05,
        now=NOW, expected_pv_measured_at=NOW,
    )
    importing = Policy(Settings()).command(
        telemetry(pv_kw=15, load_kw=2, grid_kw=2), devices, price(0), None, 15, 3.05,
        now=NOW, expected_pv_measured_at=NOW,
    )
    assert importing.ev_amps < baseline.ev_amps


def test_selected_trip_can_use_grid_only_at_projected_final_shortfall() -> None:
    devices = DeviceState(ev_home=True, ev_plugged=True, ev_ble_available=True, ev_soc_pct=10, ev_limit_pct=80)
    urgent = replace(Settings(), ev_trip_profile="target_100", ev_trip_deadline=(NOW + timedelta(hours=1)).isoformat(), ev_grid_allowed=False)
    urgent_command = Policy(urgent).command(
        telemetry(pv_kw=0, load_kw=2, soc_pct=5), devices, price(0.05), None, 0, 3.05, now=NOW,
        protected_reserve_override_pct=5,
    )
    assert urgent_command.ev_on is True
    early = replace(urgent, ev_trip_deadline=(NOW + timedelta(hours=12)).isoformat(), ev_grid_allowed=True)
    early_command = Policy(early).command(
        telemetry(pv_kw=0, load_kw=2, soc_pct=5), devices, price(0.05), None, 0, 3.05, now=NOW,
        protected_reserve_override_pct=5,
    )
    assert early_command.ev_on is False


def test_live_low_fit_solar_opportunity_overrides_stale_rolling_ev_schedule() -> None:
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=50, ev_limit_pct=80,
    )
    command = Policy(Settings()).command(
        telemetry(pv_kw=15, load_kw=1), devices, price(0), None, 15, 0,
        now=NOW, expected_pv_measured_at=NOW,
        hot_water_scheduled=False, ev_scheduled_kw=0,
    )
    assert command.hot_water_on is False
    assert command.ev_on is True


def test_live_ev_current_uses_fresh_expected_pv_not_scheduled_power() -> None:
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=50, ev_limit_pct=80,
    )
    command = Policy(Settings()).command(
        telemetry(pv_kw=20, load_kw=1), devices, price(0), None, 20, 3.05,
        now=NOW, expected_pv_measured_at=NOW, ev_scheduled_kw=6.9,
    )
    assert command.ev_on is True
    assert command.ev_amps == 16


def test_planned_six_amp_opportunistic_block_survives_live_conversion() -> None:
    settings = replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.03)
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=40, ev_limit_pct=80,
        hot_water_on=True, hot_water_power_kw=3.7,
    )
    command = Policy(settings).command(
        telemetry(pv_kw=12.66, load_kw=4.95, battery_kw=0, grid_kw=-7.7, soc_pct=100),
        devices, price(0.0007), price(0.034, "general"), 9.9, 1.8,
        now=NOW, expected_pv_measured_at=NOW,
        hot_water_scheduled=True,
        ev_scheduled_kw=settings.ev_min_amps * settings.ev_three_phase_kw_per_amp,
    )
    assert command.ev_on is True
    assert command.ev_amps == 9


def test_planned_six_amp_charge_survives_curtailed_pv_and_meter_flicker() -> None:
    settings = replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.03)
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=40, ev_limit_pct=80,
    )
    command = Policy(settings).command(
        telemetry(pv_kw=1.0, load_kw=1.1, battery_kw=0, grid_kw=0.19, soc_pct=100),
        devices, price(-0.0015), price(0.029, "general"), 5.8, 1.86,
        now=NOW, expected_pv_measured_at=NOW,
        hot_water_scheduled=False,
        ev_scheduled_kw=settings.ev_min_amps * settings.ev_three_phase_kw_per_amp,
    )
    assert command.ev_on is True
    assert command.ev_amps == settings.ev_min_amps


def test_negative_fit_uses_fresh_ecowitt_power_even_when_plan_has_no_ev() -> None:
    settings = replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.03)
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=40, ev_limit_pct=80,
    )
    command = Policy(settings).command(
        telemetry(pv_kw=1.0, load_kw=1.0, battery_kw=0, grid_kw=0, soc_pct=100),
        devices, price(-0.0015), price(0.029, "general"), 11.0, 3.05,
        now=NOW, expected_pv_measured_at=NOW,
        hot_water_scheduled=False,
        ev_scheduled_kw=0,
    )
    assert command.ev_on is True
    assert command.ev_amps == 14


def test_negative_fit_ecowitt_budget_can_run_hot_water_and_six_amp_ev() -> None:
    settings = replace(Settings(), ev_opportunistic_fit_max_per_kwh=0.03)
    devices = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=40, ev_limit_pct=80,
        ev_power_kw=4.14,
        hot_water_on=True, hot_water_power_kw=3.7,
    )
    command = Policy(settings).command(
        telemetry(pv_kw=6.1, load_kw=9.2, battery_kw=0, grid_kw=0, soc_pct=100),
        devices, price(-0.004), price(0.03, "general"), 9.7, 2.0,
        now=NOW, expected_pv_measured_at=NOW,
        hot_water_scheduled=True,
        ev_scheduled_kw=0,
    )
    assert command.hot_water_on is True
    assert command.ev_on is True
    assert command.ev_amps == settings.ev_min_amps


def test_hot_water_grid_rescue_uses_bounded_force_not_self_consume() -> None:
    rescue_now = datetime(2026, 8, 25, 4, 0, tzinfo=UTC)  # 2pm Brisbane
    command = Policy(Settings()).command(
        telemetry(pv_kw=3, load_kw=2, soc_pct=70), DeviceState(), None, None, 3, 0,
        now=rescue_now,
    )
    assert command.hot_water_on is True
    assert command.hot_water_source == "grid_rescue"
    assert command.mode == "export"
    assert command.battery_target_kw == 0.1


def test_export_specific_reserve_blocks_sale_without_blocking_house_reserve() -> None:
    command = Policy(Settings()).command(
        telemetry(soc_pct=95), DeviceState(), price(0.50), price(0.30, "general"), 8, 3.05,
        now=NOW, protected_reserve_override_pct=35, export_reserve_override_pct=99,
    )
    assert command.protected_soc_pct == 35
    assert command.mode == "self_consume"
