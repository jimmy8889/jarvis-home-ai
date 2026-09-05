import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import pytest

from energy_manager.config import Settings
from energy_manager.feeds import AmberFeed
from energy_manager.models import Command, PriceInterval, Telemetry
from energy_manager.saj import SajController
from energy_manager.service import EnergyManager, forecast_semantic_digest, plan_semantic_id


async def test_complete_safe_stop_orders_saj_then_loads_then_lease_clear(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    order: list[str] = []

    async def safe_state(negative_fit=False, emergency=False):
        assert emergency is True
        order.append("saj")
        return "applied"

    async def ev_off(on, amps, target, safety_reduction=False):
        assert on is False and safety_reduction is True
        order.append("ev")
        return "applied"

    async def hw_off(on):
        assert on is False
        order.append("hot_water")
        return "applied"

    async def clear(*resources):
        assert resources == ("ev", "hot_water")
        order.append("leases")

    monkeypatch.setattr(manager.saj, "safe_state", safe_state)
    monkeypatch.setattr(manager.loads, "set_ev", ev_off)
    monkeypatch.setattr(manager.loads, "set_hot_water", hw_off)
    monkeypatch.setattr(manager.storage, "clear_leases", clear)
    await manager.force_safe_stop("test_safe_stop")
    assert order == ["saj", "ev", "hot_water", "leases"]


async def test_startup_establishes_clean_hot_water_confirmation_baseline(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    manager.devices.hot_water_on = True
    manager.devices.hot_water_confirmed = True
    manager.devices.hot_water_power_kw = 3.7
    order: list[str] = []

    async def refresh():
        order.append("refresh")

    async def hot_water(on):
        assert on is False
        order.append("off")
        manager.devices.hot_water_on = False
        return "applied"

    async def settle(seconds):
        assert seconds == 5
        order.append("settle")

    monkeypatch.setattr(manager.loads, "refresh", refresh)
    monkeypatch.setattr(manager.loads, "set_hot_water", hot_water)
    monkeypatch.setattr("energy_manager.service.asyncio.sleep", settle)
    await manager._prepare_hot_water_startup_baseline()
    assert order == ["refresh", "off", "settle", "refresh"]
    assert manager.devices.hot_water_on is False


@pytest.mark.asyncio
async def test_fixed_hot_water_timer_governs_relay_without_saj_telemetry(tmp_path, monkeypatch) -> None:
    settings = replace(Settings(), data_dir=tmp_path, control_enabled=True, hot_water_fixed_timer=True)
    manager = EnergyManager(settings)
    manager.telemetry = None
    manager.devices.hot_water_on = False
    calls: list[bool] = []

    async def set_hot_water(on: bool) -> str:
        calls.append(on)
        manager.devices.hot_water_on = on
        return "applied"

    monkeypatch.setattr(manager.loads, "set_hot_water", set_hot_water)
    monkeypatch.setattr(manager, "_fixed_hot_water_timer_active", lambda now=None: manager.settings.hot_water_enabled)
    await manager._govern_fixed_hot_water_timer()
    assert calls == [True]
    events = await manager.storage.recent_events(10)
    assert events[0]["kind"] == "hot_water_fixed_timer_transition"
    assert events[0]["payload"]["source_control"] == "unavailable"
    assert manager.devices.hot_water_confirmed is False
    assert manager.devices.hot_water_power_kw == 0


async def test_disabling_control_safe_stops_before_persisting_disabled(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    observed_enabled: list[bool] = []

    async def safe_stop(reason):
        observed_enabled.append(manager.settings.control_enabled)
        return Command(mode="self_consume", reason=reason)

    monkeypatch.setattr(manager, "_force_safe_stop", safe_stop)
    # Keep this control-ordering test independent of Brisbane wall-clock time;
    # between 11am and 2pm the intended disabled-mode policy starts hot water.
    async def skip_fixed_timer():
        return None

    monkeypatch.setattr(manager, "_govern_fixed_hot_water_timer", skip_fixed_timer)
    result = await manager.update_settings({"control_enabled": False})
    assert observed_enabled == [True]
    assert result["control_enabled"] is False
    assert await manager.storage.setting("control_enabled", True) is False


async def test_disabled_master_uses_clock_only_hot_water_and_away_overrides_it(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=False))
    manager.devices.hot_water_on = False
    calls: list[bool] = []

    async def set_hot_water(on: bool) -> str:
        calls.append(on)
        manager.devices.hot_water_on = on
        return "applied"

    monkeypatch.setattr(manager.loads, "set_hot_water", set_hot_water)
    monkeypatch.setattr(manager, "_fixed_hot_water_timer_active", lambda now=None: manager.settings.hot_water_enabled)
    await manager._govern_fixed_hot_water_timer()
    assert calls == [True]
    manager.settings = replace(manager.settings, hot_water_enabled=False)
    await manager._govern_fixed_hot_water_timer()
    assert calls == [True, False]


async def test_legacy_ha_hot_water_helper_updates_enabled_master(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))

    async def govern() -> None:
        return None

    async def replan(_reason: str) -> None:
        return None

    monkeypatch.setattr(manager, "_govern_fixed_hot_water_timer", govern)
    monkeypatch.setattr(manager, "replan", replan)
    result = await manager.update_settings({"hot_water_fixed_timer": False})
    assert result["hot_water_enabled"] is False
    assert result["hot_water_fixed_timer"] is False
    assert manager.settings.hot_water_fixed_timer is False


async def test_emergency_safe_state_writes_even_when_control_is_disabled(monkeypatch) -> None:
    controller = SajController(replace(Settings(), control_enabled=False))
    writes: list[int] = []

    async def write_and_confirm(target):
        writes.append(target.address)

    monkeypatch.setattr(controller, "_write_and_confirm", write_and_confirm)
    assert await controller.safe_state(False, emergency=True) == "applied"
    assert controller.REG_APP_MODE in writes
    assert controller.REG_DISCHARGE_ENABLE in writes


async def test_watchdog_contains_expired_forced_command_without_planner(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    expired = datetime.now(UTC) - timedelta(seconds=5)
    manager.command = Command(mode="export", battery_target_kw=10, expires_at=expired)
    contained = asyncio.Event()

    async def safe_stop(reason):
        assert reason == "command_expired_watchdog_safe_state"
        contained.set()
        return Command(mode="self_consume")

    monkeypatch.setattr(manager, "_force_safe_stop", safe_stop)
    task = asyncio.create_task(manager._command_watchdog_loop())
    try:
        await asyncio.wait_for(contained.wait(), timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert manager.last_watchdog_expiry == expired


async def test_safe_stop_continues_flexible_load_containment_when_saj_fails(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    order: list[str] = []

    async def saj_fail(*_args, **_kwargs):
        order.append("saj")
        raise RuntimeError("offline")

    async def ev_off(*_args, **_kwargs):
        order.append("ev")
        return "applied"

    async def hw_off(*_args, **_kwargs):
        order.append("hot_water")
        return "applied"

    async def clear(*_args):
        order.append("leases")

    monkeypatch.setattr(manager.saj, "safe_state", saj_fail)
    monkeypatch.setattr(manager.loads, "set_ev", ev_off)
    monkeypatch.setattr(manager.loads, "set_hot_water", hw_off)
    monkeypatch.setattr(manager.storage, "clear_leases", clear)
    with pytest.raises(RuntimeError, match="saj"):
        await manager.force_safe_stop("test_partial")
    assert order == ["saj", "ev", "hot_water", "leases"]


async def test_watchdog_grace_avoids_boundary_safe_state_churn(tmp_path, monkeypatch) -> None:
    settings = replace(Settings(), data_dir=tmp_path, control_enabled=True, command_watchdog_grace_seconds=5)
    manager = EnergyManager(settings)
    manager.command = Command(
        mode="export", battery_target_kw=10,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    called = False

    async def safe_stop(_reason):
        nonlocal called
        called = True
        return Command(mode="self_consume")

    monkeypatch.setattr(manager, "_force_safe_stop", safe_stop)
    task = asyncio.create_task(manager._command_watchdog_loop())
    try:
        await asyncio.sleep(1.2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert called is False


async def test_disabled_safety_maintainer_never_writes_to_saj(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=False))
    manager.disabled_safe_negative_fit = True
    manager.telemetry = Telemetry(
        pv_kw=0, load_kw=1, grid_kw=0, battery_kw=0, soc_pct=80, soh_pct=100,
        app_mode=manager.saj.APP_SELF_CONSUME, anti_reflux_mode=1, export_limit=0,
    )
    applied: list[bool] = []

    async def safe_state(negative_fit=False, emergency=False):
        assert emergency is True
        applied.append(negative_fit)
        return "applied"

    monkeypatch.setattr(manager, "_fresh_negative_fit", lambda _now: False)
    monkeypatch.setattr(manager.saj, "safe_state", safe_state)
    assert await manager._maintain_disabled_saj_safe_state(datetime.now(UTC)) is False
    assert applied == []
    assert manager.command_phase == "disabled_no_inverter_writes"


async def test_startup_restores_persistent_pv_charge_limit(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    calls: list[tuple[bool, bool]] = []

    async def safe_state(negative_fit=False, emergency=False):
        calls.append((negative_fit, emergency))
        return "applied"

    monkeypatch.setattr(manager.saj, "safe_state", safe_state)
    await manager._restore_startup_safe_state()
    await manager._restore_startup_safe_state()
    assert calls == [(False, True)]
    assert manager.startup_safe_state_pending is False


async def test_restored_or_unpriced_plan_is_display_only_until_fresh_amber_poll(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    manager.telemetry = Telemetry(pv_kw=0, load_kw=1, grid_kw=1, battery_kw=0, soc_pct=80, soh_pct=100)
    manager.amber = AmberFeed(manager.settings, None)  # type: ignore[arg-type]
    applied = False

    async def apply(_command):
        nonlocal applied
        applied = True
        return "applied"

    monkeypatch.setattr(manager.saj, "apply", apply)
    await manager.replan("telemetry")
    assert applied is False
    assert manager.command_phase == "waiting_for_fresh_amber_plan"
    assert manager.plan_dispatch_ready is False


async def test_clean_stop_does_not_write_saj_while_disabled(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=False))
    calls: list[tuple[bool, bool]] = []

    async def safe_state(negative_fit=False, emergency=False):
        calls.append((negative_fit, emergency))
        return "applied"

    async def close():
        return None

    monkeypatch.setattr(manager.saj, "safe_state", safe_state)
    monkeypatch.setattr(manager.saj, "close", close)
    monkeypatch.setattr(manager.loads, "close", close)
    await manager.stop()
    assert calls == []


async def test_cached_amber_promotion_preserves_original_receipt_age(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    manager.amber = AmberFeed(manager.settings, None)  # type: ignore[arg-type]
    boundary = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)
    received = boundary - timedelta(hours=12)
    interval = PriceInterval(
        "amber", "feedIn", boundary, boundary + timedelta(minutes=5), -0.05,
        received_at=received, estimate=True,
    )
    manager.amber.forecast = {"feedIn": [interval]}
    await manager._promote_cached_amber(boundary)
    assert manager.amber.current["feedIn"].received_at == received
    assert manager.amber.current["feedIn"].metadata["promoted_at"] == boundary.isoformat()


def test_plan_and_forecast_semantic_digests_ignore_receipt_only_churn() -> None:
    first = {"generated_at": "one", "horizon_end": "end", "points": [{"pv_kw": 1}]}
    second = {**first, "generated_at": "two", "plan_id": "old"}
    assert plan_semantic_id(first) == plan_semantic_id(second)
    assert forecast_semantic_digest({"issued_at": "one", "roofs": {"north": [1]}}) == forecast_semantic_digest({"issued_at": "two", "roofs": {"north": [1]}})
    assert forecast_semantic_digest({"roofs": {"north": [1]}}) != forecast_semantic_digest({"roofs": {"north": [2]}})


async def test_device_plan_signature_ignores_power_noise_but_tracks_material_state(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    manager.devices.ev_home = True
    manager.devices.ev_plugged = True
    first = manager._device_plan_signature()
    manager.devices.ev_power_kw = 7.1
    assert manager._device_plan_signature() == first
    manager.devices.ev_plugged = False
    assert manager._device_plan_signature() != first


async def test_hot_water_flow_detects_battery_element_contribution(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    manager.devices.hot_water_on = True
    manager.devices.ev_power_kw = 0
    telemetry = Telemetry(
        pv_kw=6, load_kw=8.7, battery_kw=2.7, grid_kw=0,
        soc_pct=80, soh_pct=100,
    )
    battery_to_element, _flow = manager._battery_to_hot_water_kw(telemetry)
    assert battery_to_element == pytest.approx(2.7)


async def test_hot_water_firmware_runtime_sync_is_batched(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, hot_water_confirmation_sync_seconds=60))
    manager.devices.hot_water_runtime_hours = 1
    calls: list[int] = []

    async def sync(seconds):
        calls.append(seconds)

    monkeypatch.setattr(manager.loads, "set_hot_water_confirmed_seconds", sync)
    at = datetime.now(UTC)
    await manager._sync_hot_water_runtime(at)
    await manager._sync_hot_water_runtime(at + timedelta(seconds=2))
    await manager._sync_hot_water_runtime(at + timedelta(seconds=61))
    assert calls == [3600, 3600]


async def test_stale_amber_releases_morning_pv_charge_deferral(tmp_path, monkeypatch) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    now = datetime.now(UTC)
    start = datetime.fromtimestamp(int(now.timestamp()) // 300 * 300, UTC)
    manager.telemetry = Telemetry(pv_kw=10, load_kw=2, grid_kw=0, battery_kw=0, soc_pct=60, soh_pct=100)
    manager.amber = AmberFeed(manager.settings, None)  # type: ignore[arg-type]
    stale_fit = PriceInterval(
        "amber", "feedIn", start, start + timedelta(minutes=5), 0.30,
        received_at=now - timedelta(minutes=10),
    )
    stale_import = PriceInterval(
        "amber", "general", start, start + timedelta(minutes=5), 0.20,
        received_at=now - timedelta(minutes=10),
    )
    manager.amber.current = {"feedIn": stale_fit, "general": stale_import}
    manager.amber.forecast = {"feedIn": [stale_fit], "general": [stale_import]}
    manager.plan_dispatch_ready = True
    manager.rolling_plan = {
        "plan_id": "restored",
        "points": [{
            "start": start.isoformat(), "end": (start + timedelta(minutes=5)).isoformat(),
            "protected_soc_pct": 5, "export_protected_soc_pct": 5,
            "battery_charge_deferred": True, "hot_water": False, "ev_kw": 0,
        }],
    }
    captured: list[Command] = []

    async def apply(command):
        captured.append(command)
        return "applied"

    async def no_op(*_args, **_kwargs):
        return "semantic_noop_confirmed"

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(manager.saj, "apply", apply)
    monkeypatch.setattr(manager.loads, "set_ev", no_op)
    monkeypatch.setattr(manager.loads, "set_hot_water", no_op)
    monkeypatch.setattr(manager.mqtt, "publish", publish)
    await manager.replan("telemetry")
    assert captured[-1].pv_charge_limit_raw == 1100
    assert manager.amber_price_ready is False


async def test_hot_water_confirmation_requires_and_holds_stable_site_controls(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    now = datetime.now(UTC)
    manager.telemetry = Telemetry(pv_kw=8, load_kw=2, grid_kw=0, battery_kw=0, soc_pct=80, soh_pct=100)
    manager.devices.ev_charging = True
    manager.devices.ev_amps = 6
    manager.devices.ev_last_command_at = now - timedelta(seconds=31)
    stable = Command(
        mode="self_consume", ev_on=True, ev_amps=6, hot_water_on=False,
        generated_at=now, expires_at=now + timedelta(minutes=4),
    )
    manager.command = stable
    start = replace(stable, hot_water_on=True, hot_water_source="solar")
    assert manager._isolate_hot_water_confirmation(start, now).hot_water_on is True
    changed = replace(start, ev_amps=7)
    assert manager._isolate_hot_water_confirmation(changed, now).hot_water_on is False

    manager.devices.ev_amps = 7
    manager.devices.ev_last_command_at = now
    assert manager._isolate_hot_water_confirmation(changed, now).hot_water_on is False

    manager.devices.hot_water_on = True
    manager.devices.hot_water_confirmed = False
    hold = replace(stable, hot_water_on=True, hot_water_source="solar")
    manager.hw_confirmation_command = hold
    manager.hw_confirmation_hold_until = now + timedelta(seconds=45)
    increase = replace(hold, ev_amps=10)
    held = manager._isolate_hot_water_confirmation(increase, now)
    assert held.hot_water_on is True
    assert held.ev_amps == 6
    reduction = replace(hold, ev_amps=5)
    held_reduction = manager._isolate_hot_water_confirmation(reduction, now)
    assert held_reduction.hot_water_on is True
    assert held_reduction.ev_amps == 6


async def test_hot_water_start_pins_physically_stable_ev_when_export_headroom_is_sufficient(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    now = datetime.now(UTC)
    manager.telemetry = Telemetry(
        pv_kw=12, load_kw=6.2, grid_kw=-5.8, battery_kw=0,
        soc_pct=100, soh_pct=97,
    )
    manager.devices.ev_charging = True
    manager.devices.ev_amps = 7
    manager.devices.ev_last_command_at = now - timedelta(seconds=31)
    manager.command = Command(
        mode="self_consume", ev_on=True, ev_amps=9, hot_water_on=False,
        generated_at=now, expires_at=now + timedelta(minutes=4),
    )
    requested = Command(
        mode="self_consume", ev_on=True, ev_amps=9,
        hot_water_on=True, hot_water_source="solar",
        generated_at=now, expires_at=now + timedelta(minutes=4),
    )
    first = manager._isolate_hot_water_confirmation(requested, now)
    assert first.hot_water_on is False
    assert first.ev_amps == 7
    manager.command = first
    second_request = replace(first, hot_water_on=True, hot_water_source="solar")
    second = manager._isolate_hot_water_confirmation(second_request, now + timedelta(seconds=1))
    assert second.hot_water_on is True
    assert second.ev_amps == 7


def _ready_actuator_manager(tmp_path, monkeypatch) -> tuple[EnergyManager, Command]:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path, control_enabled=True))
    now = datetime.now(UTC)
    start = datetime.fromtimestamp(int(now.timestamp()) // 300 * 300, UTC)
    end = start + timedelta(minutes=5)
    manager.telemetry = Telemetry(
        measured_at=now,
        pv_kw=10,
        load_kw=2,
        grid_kw=0,
        battery_kw=0,
        soc_pct=80,
        soh_pct=100,
    )
    manager.devices.ev_home = True
    manager.devices.ev_plugged = True
    manager.devices.ev_ble_available = True
    manager.devices.hot_water_available = True
    manager.amber = AmberFeed(manager.settings, None)  # type: ignore[arg-type]
    fit = PriceInterval("amber", "feedIn", start, end, 0.10, received_at=now)
    general = PriceInterval("amber", "general", start, end, 0.30, received_at=now)
    manager.amber.current = {"feedIn": fit, "general": general}
    manager.amber.forecast = {"feedIn": [fit], "general": [general]}
    manager.plan_dispatch_ready = True
    manager.rolling_plan = {
        "plan_id": "actuator-isolation",
        "points": [{
            "start": start.isoformat(),
            "end": end.isoformat(),
            "protected_soc_pct": 5,
            "export_protected_soc_pct": 5,
            "battery_charge_deferred": False,
            "hot_water": True,
            "ev_kw": 4.4,
        }],
    }
    command = Command(
        mode="self_consume",
        ev_on=True,
        ev_amps=6,
        ev_target_soc_pct=80,
        hot_water_on=True,
        hot_water_source="solar",
        generated_at=now,
        expires_at=now + timedelta(minutes=4),
    )
    manager.command = replace(command, hot_water_on=False, hot_water_source="off")
    monkeypatch.setattr(manager.policy, "command", lambda *_args, **_kwargs: command)
    monkeypatch.setattr(manager, "_isolate_hot_water_confirmation", lambda value, _now: value)
    return manager, command


async def test_ev_actuator_failure_does_not_suppress_hot_water_or_fail_saj_phase(tmp_path, monkeypatch) -> None:
    manager, _command = _ready_actuator_manager(tmp_path / "ev", monkeypatch)
    order: list[str] = []

    async def saj_apply(_command):
        order.append("saj")
        return "applied"

    async def ev_fail(*_args, **_kwargs):
        order.append("ev")
        manager.loads.ev_error = "Tesla BLE command failed: peer reset"
        raise RuntimeError("peer reset")

    async def hot_water_apply(_on):
        order.append("hot_water")
        return "applied"

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(manager.saj, "apply", saj_apply)
    monkeypatch.setattr(manager.loads, "set_ev", ev_fail)
    monkeypatch.setattr(manager.loads, "set_hot_water", hot_water_apply)
    monkeypatch.setattr(manager.mqtt, "publish", publish)

    await manager.replan("telemetry")

    assert order == ["saj", "ev", "hot_water"]
    assert manager.command_phase == "applied"
    assert manager.command is not None and manager.command.hot_water_on is True
    assert manager.command_error == "Tesla BLE command failed: peer reset"
    assert manager.devices.ev_ble_available is False
    assert manager.snapshot()["service"]["ev_actuator_error"] == manager.command_error
    assert "ev_actuator_failed" in {event["kind"] for event in await manager.storage.recent_events()}


async def test_hot_water_actuator_failure_does_not_suppress_ev_or_fail_saj_phase(tmp_path, monkeypatch) -> None:
    manager, _command = _ready_actuator_manager(tmp_path / "hot-water", monkeypatch)
    order: list[str] = []

    async def saj_apply(_command):
        order.append("saj")
        return "semantic_noop_confirmed"

    async def ev_apply(*_args, **_kwargs):
        order.append("ev")
        return "applied"

    async def hot_water_fail(_on):
        order.append("hot_water")
        manager.loads.hot_water_error = "hot-water command failed: reset"
        raise RuntimeError("reset")

    async def publish(*_args, **_kwargs):
        return None

    monkeypatch.setattr(manager.saj, "apply", saj_apply)
    monkeypatch.setattr(manager.loads, "set_ev", ev_apply)
    monkeypatch.setattr(manager.loads, "set_hot_water", hot_water_fail)
    monkeypatch.setattr(manager.mqtt, "publish", publish)

    await manager.replan("telemetry")

    assert order == ["saj", "ev", "hot_water"]
    assert manager.command_phase == "semantic_noop_confirmed"
    assert manager.command is not None and manager.command.ev_on is True
    assert manager.command_error == "hot-water command failed: reset"
    assert manager.devices.hot_water_available is False
    assert manager.snapshot()["service"]["hot_water_actuator_error"] == manager.command_error
    assert "hot_water_actuator_failed" in {event["kind"] for event in await manager.storage.recent_events()}
