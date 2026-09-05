from dataclasses import replace
from datetime import UTC, datetime, timedelta
import pytest

from energy_manager.config import Settings
from energy_manager.models import Command, Telemetry
from energy_manager.saj import (
    decode_fault_words,
    SajController,
    forced_discharge_register_target_kw,
    select_site_load,
    semantic_hash,
    signed16,
)


def test_fault_decoder_preserves_known_and_unknown_bits() -> None:
    decoded = decode_fault_words((0x00000002, 0, 0x00000001 | 0x00000008))
    assert "Meter communication lost" in decoded
    assert "Relay error" in decoded
    assert "Temperature low" in decoded


def test_signed16() -> None:
    assert signed16(0) == 0
    assert signed16(32767) == 32767
    assert signed16(65535) == -1


def test_total_load_is_primary_even_when_backup_is_valid() -> None:
    selected, source, error = select_site_load(7.9, 4.1, 2.0, 2.0, 0.1)
    assert selected == 7.9
    assert source == "total_house_load"
    assert abs(error - 3.8) < 0.001


def test_invalid_total_load_falls_back_to_power_balance_not_backup() -> None:
    selected, source, _ = select_site_load(200, 9.0, 0, 2.3, 0)
    assert selected == 2.3
    assert source == "power_balance_fallback"


def test_backup_register_offset_matches_0x40ab() -> None:
    assert 0x40AB - 0x4095 == 22


def test_semantic_hash_ignores_reason_and_plan_time() -> None:
    first = Command(mode="export", battery_target_kw=12.34, protected_soc_pct=20, reason="a")
    second = replace(first, reason="b")
    assert semantic_hash(first) == semantic_hash(second)


async def test_final_targets_collapse_stop_then_enable_register() -> None:
    controller = SajController(Settings())
    generated = datetime(2026, 8, 26, 2, 1, tzinfo=UTC)
    command = Command(mode="export", battery_target_kw=15, protected_soc_pct=12, generated_at=generated, expires_at=generated + timedelta(minutes=4))
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert final[controller.REG_CHARGE_ENABLE] == 0
    assert final[controller.REG_DISCHARGE_ENABLE] == 1
    assert final[controller.REG_RESERVE] == 12
    assert final[controller.REG_PV_CHARGE_LIMIT] == 1100
    assert final[controller.REG_DISCHARGE_START] == (12 << 8) | 0
    assert final[controller.REG_DISCHARGE_END] == (12 << 8) | 5


async def test_profitable_export_register_tracks_site_target_not_house_load() -> None:
    controller = SajController(Settings())
    generated = datetime(2026, 8, 26, 2, 1, tzinfo=UTC)
    command = Command(
        mode="export",
        site_export_target_kw=4.2,
        battery_target_kw=5.4,
        generated_at=generated,
        expires_at=generated + timedelta(minutes=4),
    )
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert forced_discharge_register_target_kw(command) == 4.2
    assert final[controller.REG_DISCHARGE_MASK_POWER] & 0xFF == 14


async def test_load_segregation_export_keeps_battery_target() -> None:
    controller = SajController(Settings())
    generated = datetime(2026, 8, 26, 2, 1, tzinfo=UTC)
    command = Command(
        mode="export",
        site_export_target_kw=0,
        battery_target_kw=1.2,
        reason="hot_water_grid_only_rescue",
        generated_at=generated,
        expires_at=generated + timedelta(minutes=4),
    )
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert forced_discharge_register_target_kw(command) == 1.2
    assert final[controller.REG_DISCHARGE_MASK_POWER] & 0xFF == 4


def test_export_semantic_hash_uses_physical_site_target() -> None:
    generated = datetime(2026, 8, 26, 2, 1, tzinfo=UTC)
    base = Command(
        mode="export",
        site_export_target_kw=4.2,
        battery_target_kw=5.4,
        generated_at=generated,
        expires_at=generated + timedelta(minutes=4),
    )
    assert semantic_hash(base) == semantic_hash(replace(base, battery_target_kw=6.8))
    assert semantic_hash(base) != semantic_hash(replace(base, site_export_target_kw=5.0))


async def test_safe_self_consume_keeps_full_battery_support() -> None:
    controller = SajController(Settings())
    command = Command(mode="self_consume", protected_soc_pct=5)
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert final[controller.REG_APP_MODE] == controller.APP_SELF_CONSUME
    assert final[controller.REG_BATTERY_DISCHARGE_LIMIT] == 1100
    assert final[controller.REG_PV_CHARGE_LIMIT] == 1100


async def test_forecast_hold_only_changes_pv_charge_limit() -> None:
    controller = SajController(Settings())
    normal = Command(mode="self_consume", protected_soc_pct=7, pv_charge_limit_raw=1100)
    deferred = replace(normal, pv_charge_limit_raw=0)
    assert semantic_hash(normal) != semantic_hash(deferred)
    final = {target.address: target.value for target in controller.final_targets_for(deferred)}
    assert final[controller.REG_APP_MODE] == controller.APP_SELF_CONSUME
    assert final[controller.REG_BATTERY_DISCHARGE_LIMIT] == 1100
    assert final[controller.REG_PV_CHARGE_LIMIT] == 0


async def test_forced_window_crossing_local_midnight_falls_back_to_self_consume() -> None:
    controller = SajController(Settings())
    generated = datetime(2026, 8, 26, 13, 58, tzinfo=UTC)  # 23:58 Brisbane
    command = Command(mode="export", battery_target_kw=20, generated_at=generated, expires_at=generated + timedelta(minutes=2))
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert final[controller.REG_APP_MODE] == controller.APP_SELF_CONSUME
    assert final[controller.REG_DISCHARGE_ENABLE] == 0


async def test_grid_rescue_hold_uses_bounded_force_even_at_near_zero_target() -> None:
    controller = SajController(Settings())
    generated = datetime(2026, 8, 26, 2, 1, tzinfo=UTC)
    command = Command(
        mode="export", battery_target_kw=0.1,
        generated_at=generated, expires_at=generated + timedelta(minutes=4),
    )
    final = {target.address: target.value for target in controller.final_targets_for(command)}
    assert final[controller.REG_APP_MODE] == controller.APP_FORCE
    assert final[controller.REG_DISCHARGE_ENABLE] == 1


async def test_expired_material_command_is_rejected_before_any_write(monkeypatch) -> None:
    controller = SajController(replace(Settings(), control_enabled=True))
    controller.last = Telemetry(pv_kw=0, load_kw=1, grid_kw=1, battery_kw=0, soc_pct=80, soh_pct=100)
    writes: list[int] = []

    async def write(target):
        writes.append(target.address)

    monkeypatch.setattr(controller, "_write_and_confirm", write)
    now = datetime.now(UTC)
    with pytest.raises(RuntimeError, match="expired"):
        await controller.apply(Command(
            mode="export", battery_target_kw=10,
            generated_at=now - timedelta(minutes=5), expires_at=now - timedelta(seconds=1),
        ))
    assert writes == []


async def test_confirmation_failure_preserves_negative_fit_anti_reflux(monkeypatch) -> None:
    controller = SajController(replace(Settings(), control_enabled=True))
    controller.last = Telemetry(pv_kw=0, load_kw=1, grid_kw=0, battery_kw=0, soc_pct=80, soh_pct=100)
    fallback: dict[int, int] = {}

    async def fail(_target):
        raise RuntimeError("confirmation failed")

    async def record(target):
        fallback[target.address] = target.value

    monkeypatch.setattr(controller, "_write_and_confirm", fail)
    monkeypatch.setattr(controller, "_write", record)
    now = datetime.now(UTC)
    with pytest.raises(RuntimeError, match="confirmation failed"):
        await controller.apply(Command(
            mode="self_consume", zero_export=True,
            generated_at=now, expires_at=now + timedelta(minutes=4),
        ))
    assert fallback[controller.REG_ANTI_REFLUX] == 1
    assert fallback[controller.REG_EXPORT_LIMIT] == 0
