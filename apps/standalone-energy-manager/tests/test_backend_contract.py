from dataclasses import replace
from datetime import UTC, datetime, timedelta

from energy_manager.config import Settings
from energy_manager.api import SettingsPatch
from energy_manager.devices import EsphomeDevice, FlexibleLoadController
from energy_manager.ev import EVTripMode, ev_requirement, normalize_trip_mode, target_soc_for_mode
from energy_manager.economics import battery_export_economics, protected_surplus_export_economics
from energy_manager.flows import conserved_power_flow
from energy_manager.models import Command, DeviceState, Telemetry, command_semantic_hash
from energy_manager.nut import NutCollector, NutPowerState
from energy_manager.service import EnergyManager, MinuteAverageAccumulator, OutcomeAccumulator
from energy_manager.storage import Storage
from pydantic import ValidationError
import pytest


NOW = datetime(2026, 8, 26, 0, 0, tzinfo=UTC)


def test_config_uses_real_influx_org_and_release() -> None:
    settings = Settings()
    assert settings.influx_org == "jameshome"
    assert settings.software_revision == "standalone-0.5.5"
    assert settings.nut_host == "10.0.1.206"


def test_trip_profiles_and_compatibility_aliases() -> None:
    settings = Settings()
    assert normalize_trip_mode("100km") is EVTripMode.DISTANCE_100_KM
    assert target_soc_for_mode(settings, EVTripMode.DISTANCE_100_KM) == 43.8
    assert target_soc_for_mode(settings, EVTripMode.DISTANCE_200_KM) == 72.6
    assert target_soc_for_mode(settings, EVTripMode.TARGET_80) == 80
    assert target_soc_for_mode(settings, EVTripMode.TARGET_100) == 100


def test_trip_requirement_exposes_consumption_source_and_deadline() -> None:
    settings = replace(Settings(), ev_trip_profile="distance_100_km")
    requirement = ev_requirement(settings, 20, NOW)
    assert requirement.departure_at is not None
    assert requirement.grid_guarantee is True
    assert requirement.consumption_source == "fallback_0.18_kwh_per_km"
    learned = ev_requirement(replace(settings, ev_learned_consumption_kwh_per_km=0.2), 20, NOW)
    assert learned.consumption_source == "teslamate_learned"
    assert learned.target_soc_pct == 47.0


def test_ev_target_is_part_of_full_semantic_command_identity() -> None:
    first = Command(mode="self_consume", ev_on=True, ev_amps=6, ev_target_soc_pct=80)
    second = replace(first, ev_target_soc_pct=100)
    assert command_semantic_hash(first) != command_semantic_hash(second)
    assert command_semantic_hash(replace(first, ev_on=False)) == command_semantic_hash(replace(second, ev_on=False))


def test_export_marginal_cost_adds_retained_value_uncertainty_and_wear_once() -> None:
    values = battery_export_economics(Settings(), 0.30)
    assert values.acquisition_or_retained_per_kwh == pytest.approx(0.30 / 0.92)
    assert values.retained_value_per_kwh == pytest.approx(0.30 / 0.92 + 0.02)
    assert values.marginal_cost_per_kwh == pytest.approx(0.30 / 0.92 + 0.02 + 0.08)


def test_protected_surplus_export_does_not_double_count_import_retention() -> None:
    values = protected_surplus_export_economics(Settings())
    assert values.acquisition_or_retained_per_kwh == 0
    assert values.retained_value_per_kwh == pytest.approx(0.02)
    assert values.marginal_cost_per_kwh == pytest.approx(0.10)


def test_flow_contract_is_conserved_and_exposes_low_confidence_residual() -> None:
    flow = conserved_power_flow(
        pv_kw=5, battery_kw=2, grid_kw=-1, ordinary_house_kw=2,
        hot_water_kw=0, ev_kw=0, server_rack_kw=0.5, at=NOW,
    )
    assert flow["method"] == "priority_inference_v1"
    assert flow["conserved"] is True
    assert flow["balance_residual_kw"] == 0
    assert flow["confidence"]["label"] == "low"
    assert flow["meter_balance_error_kw"] == 4
    assert flow["sinks_kw"]["house"] == 2
    assert flow["site_load_kw"] == 2
    assert "server_rack" not in flow["sinks_kw"]
    assert flow["submeters_kw"]["server_rack"] == 0.5


async def test_nut_uses_live_efficiency_then_stales_after_three_misses(monkeypatch) -> None:
    collector = NutCollector(Settings())
    calls = 0

    async def fake_list(command: str, end: str) -> list[str]:
        nonlocal calls
        calls += 1
        if calls <= 2:
            if command == "LIST UPS":
                return ['UPS "ups" "desk"']
            return [
                'VAR ups ups.realpower "940"', 'VAR ups ups.efficiency "94"',
                'VAR ups ups.load "50"', 'VAR ups battery.charge "88"',
                'VAR ups battery.runtime "1200"', 'VAR ups input.voltage "240"',
                'VAR ups output.voltage "239"',
            ]
        raise RuntimeError("offline")

    monkeypatch.setattr(collector, "_list", fake_list)
    state = await collector.poll()
    assert state.server_rack_power_w == 1000
    assert state.legacy_80_power_w == 1175
    assert state.confidence == "live_efficiency"
    assert state.battery_charge_pct == 88
    assert (await collector.poll()).available is True
    assert (await collector.poll()).available is True
    assert (await collector.poll()).available is False


async def test_snapshot_server_rack_units_match_dashboard_contract(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    manager.nut.state = NutPowerState(
        measured_at=NOW,
        available=True,
        raw_real_power_w=940,
        server_rack_power_w=1000,
        confidence="live_efficiency",
        status="OL",
    )
    manager.current_daily = {"server_rack_kwh": 6.25}

    rack = manager.snapshot()["server_rack"]

    assert rack["input_power_kw"] == 1.0
    assert rack["output_power_kw"] == 0.94
    assert rack["energy_today_kwh"] == 6.25
    # The raw NUT fields remain available to API/Pilot compatibility clients.
    assert rack["server_rack_power_w"] == 1000
    assert rack["raw_real_power_w"] == 940

    manager.nut.state.available = False
    unavailable = manager.snapshot()["server_rack"]
    assert unavailable["input_power_kw"] is None
    assert unavailable["output_power_kw"] is None


async def test_ups_series_is_time_bounded_and_evenly_downsampled(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    now = datetime.now(UTC)
    manager.nut_history.extend(
        {
            "measured_at": (now - timedelta(seconds=900 - index)).isoformat(),
            "sample_sequence": index,
            "input_power_w": 500 + index,
        }
        for index in range(901)
    )

    series = manager.ups_series(minutes=15, limit=60)

    assert len(series) == 60
    assert series[0]["sample_sequence"] >= 0
    assert series[-1]["sample_sequence"] == 900
    assert [item["sample_sequence"] for item in series] == sorted(
        item["sample_sequence"] for item in series
    )


async def test_settings_transaction_and_series_are_atomic_and_ordered(tmp_path) -> None:
    storage = Storage(tmp_path / "state.sqlite3")
    await storage.set_settings({"ev_trip_profile": "target_80", "ev_trip_deadline": "deadline"})
    assert await storage.setting("ev_trip_profile", None) == "target_80"
    assert await storage.setting("ev_trip_deadline", None) == "deadline"


async def test_manager_settings_accept_canonical_profile_and_legacy_alias(tmp_path) -> None:
    manager = EnergyManager(replace(Settings(), data_dir=tmp_path))
    result = await manager.update_settings({
        "ev_trip_profile": "target_100",
        "ev_opportunistic_fit_max_per_kwh": 0.025,
    })
    assert result["ev_trip_profile"] == "target_100"
    assert result["ev_trip_requirement"] == "Ensure 100%"
    assert result["ev_trip_deadline"] is not None
    assert result["ev_opportunistic_fit_max_per_kwh"] == 0.025
    legacy = await manager.update_settings({"ev_trip_requirement": "No trip"})
    assert legacy["ev_trip_profile"] == "no_trip"
    assert legacy["ev_trip_deadline"] is None


async def test_native_hot_water_off_decision_renews_controller_lease(monkeypatch) -> None:
    state = DeviceState(hot_water_on=False)
    controller = FlexibleLoadController(Settings(), state)
    controller.hot_water_native = True
    commands: list[bool] = []

    async def command(on: bool):
        commands.append(on)

    monkeypatch.setattr(controller, "_native_hot_water_command", command)
    assert await controller.set_hot_water(False) == "lease_renewed"
    assert commands == [False]


async def test_tesla_refresh_captures_local_presence_and_garage_preset(monkeypatch) -> None:
    state = DeviceState()
    controller = FlexibleLoadController(Settings(), state)

    class Value:
        def __init__(self, value):
            self.state = value

    async def connect():
        return None

    def state_for(*names):
        key = " ".join(names)
        return {
            "james car home": Value(True),
            "garage preset": Value(17),
            "charging amps": Value(6),
            "charging limit": Value(80),
            "charger": Value(False),
        }.get(key)

    async def no_native_hot_water():
        return None

    async def hot_water_connect():
        raise RuntimeError("not part of Tesla telemetry test")

    monkeypatch.setattr(controller.tesla, "connect", connect)
    monkeypatch.setattr(controller.tesla, "state_for", state_for)
    monkeypatch.setattr(controller, "_native_hot_water_state", no_native_hot_water)
    monkeypatch.setattr(controller.hot_water, "connect", hot_water_connect)
    await controller.refresh()

    assert state.ev_ble_available is True
    assert state.ev_ble_home is True
    assert state.ev_home is True
    assert state.ev_garage_preset == 17


async def test_supported_manual_vehicle_controls_use_local_ble(monkeypatch) -> None:
    state = DeviceState(ev_home=True, ev_ble_available=True)
    controller = FlexibleLoadController(Settings(), state)
    calls: list[tuple] = []

    async def lock(value, *names):
        calls.append(("lock", value, names))

    async def button(*names):
        calls.append(("button", names))

    async def switch(value, *names):
        calls.append(("switch", value, names))

    async def number(value, *names):
        calls.append(("number", value, names))

    async def cover(value, *names):
        calls.append(("cover", value, names))

    monkeypatch.setattr(controller.tesla, "lock", lock)
    monkeypatch.setattr(controller.tesla, "button", button)
    monkeypatch.setattr(controller.tesla, "switch", switch)
    monkeypatch.setattr(controller.tesla, "number", number)
    monkeypatch.setattr(controller.tesla, "cover", cover)

    assert await controller.vehicle_control("unlock") == "applied"
    assert await controller.vehicle_control("unlock_charge_port") == "applied"
    assert await controller.vehicle_control("climate_on") == "applied"
    assert await controller.vehicle_control("set_climate_temperature", 22) == "applied"
    assert await controller.vehicle_control("steering_heat_on") == "applied"
    assert await controller.vehicle_control("open_charge_port") == "applied"
    assert calls == [
        ("lock", False, ("lock car",)),
        ("button", ("unlock charge port",)),
        ("switch", True, ("climate",)),
        ("number", 22.0, ("climate temperature",)),
        ("switch", True, ("steering wheel heat",)),
        ("cover", True, ("charge port",)),
    ]
    with pytest.raises(ValueError, match="between 15 and 28"):
        await controller.vehicle_control("set_climate_temperature", 35)


async def test_manual_vehicle_control_requires_local_presence() -> None:
    controller = FlexibleLoadController(Settings(), DeviceState(ev_home=False, ev_ble_available=True))
    with pytest.raises(RuntimeError, match="not home"):
        await controller.vehicle_control("unlock")


async def test_esphome_reset_detaches_client_and_suppresses_immediate_reconnect(monkeypatch) -> None:
    device = EsphomeDevice("127.0.0.1", 6053, reconnect_backoff_seconds=10)
    disconnects: list[bool] = []
    actions = 0

    class ResetClient:
        async def disconnect(self, force: bool = False) -> None:
            disconnects.append(force)

    stale = ResetClient()
    device.client = stale  # type: ignore[assignment]
    device.connected = True
    device.entities["charger"] = object()
    device.states[1] = object()

    await device.invalidate()

    assert device.client is None
    assert device.connected is False
    assert device.entities == {}
    assert device.states == {}
    assert disconnects == [True]
    assert device.reconnect_backoff_remaining > 9

    def unexpected_client(*_args, **_kwargs):
        nonlocal actions
        actions += 1
        raise AssertionError("backoff must prevent a new native-API client")

    monkeypatch.setattr("energy_manager.devices.APIClient", unexpected_client)
    with pytest.raises(RuntimeError, match="reconnect backoff active"):
        await device.connect()
    assert actions == 0


async def test_tesla_command_reset_invalidates_once_and_backoffs_retries(monkeypatch) -> None:
    state = DeviceState(
        ev_home=True,
        ev_plugged=True,
        ev_ble_available=True,
        ev_soc_pct=30,
        ev_limit_pct=80,
    )
    controller = FlexibleLoadController(Settings(), state)
    disconnects: list[bool] = []
    action_calls = 0

    class ResetClient:
        async def disconnect(self, force: bool = False) -> None:
            disconnects.append(force)

    controller.tesla.client = ResetClient()  # type: ignore[assignment]
    controller.tesla.connected = True

    async def reset_action(*_args, **_kwargs):
        nonlocal action_calls
        action_calls += 1
        raise ConnectionResetError("peer reset")

    monkeypatch.setattr(controller.tesla, "action", reset_action)
    with pytest.raises(RuntimeError, match="Tesla BLE command failed: peer reset"):
        await controller.set_ev(True, 10, 80)

    assert state.ev_ble_available is False
    assert controller.tesla.client is None
    assert controller.tesla.reconnect_backoff_active is True
    assert disconnects == [True]
    assert action_calls == 1
    assert await controller.set_ev(True, 10, 80) == "actuator_unavailable_backoff"
    assert action_calls == 1


async def test_active_tesla_ramps_to_six_amps_before_stopping(monkeypatch) -> None:
    state = DeviceState(
        ev_home=True,
        ev_plugged=True,
        ev_ble_available=True,
        ev_soc_pct=40,
        ev_limit_pct=80,
        ev_charging=True,
        ev_amps=7,
    )
    controller = FlexibleLoadController(Settings(), state)
    actions: list[dict] = []
    switches: list[bool] = []

    async def action(_name, payload):
        actions.append(payload)
        return True

    async def switch(value, *_names):
        switches.append(value)

    monkeypatch.setattr(controller.tesla, "action", action)
    monkeypatch.setattr(controller.tesla, "switch", switch)
    result = await controller.set_ev(
        False, 0, 80, safety_reduction=True, ramp_before_stop=True,
    )
    assert result == "applied"
    assert actions[-1]["charging"] is True
    assert actions[-1]["amps"] == 6
    assert state.ev_charging is True
    assert state.ev_amps == 6

    # A repeated stop request inside the same 30-second interval holds 6 A.
    result = await controller.set_ev(
        False, 0, 80, safety_reduction=True, ramp_before_stop=True,
    )
    assert result == "semantic_noop_confirmed"
    assert state.ev_charging is True

    # Noisy feedback returning to 7 A does not reset the internal stop ramp.
    state.ev_amps = 7
    controller._ev_stop_ramp_last_step_at = datetime.now(UTC) - timedelta(seconds=31)
    result = await controller.set_ev(
        False, 0, 80, safety_reduction=True, ramp_before_stop=True,
    )
    assert result == "applied"
    assert actions[-1]["charging"] is False
    assert switches[-1] is False
    assert state.ev_charging is False


async def test_tesla_stop_uses_lease_cancellation_and_direct_ble_switch(monkeypatch) -> None:
    state = DeviceState(
        ev_home=True, ev_plugged=True, ev_ble_available=True,
        ev_soc_pct=40, ev_limit_pct=80, ev_charging=True, ev_amps=6,
    )
    controller = FlexibleLoadController(Settings(), state)
    actions: list[dict] = []
    switches: list[bool] = []

    async def action(_name, payload):
        actions.append(payload)
        return True

    async def switch(value, *_names):
        switches.append(value)

    monkeypatch.setattr(controller.tesla, "action", action)
    monkeypatch.setattr(controller.tesla, "switch", switch)
    result = await controller.set_ev(False, 0, 80, safety_reduction=True)
    assert result == "applied"
    assert actions[-1]["charging"] is False
    assert switches == [False]
    assert state.ev_charging is False

    state.ev_amps = 7
    assert await controller.set_ev(False, 0, 80, safety_reduction=True) == "semantic_noop_confirmed"
    assert len(actions) == 1
    assert switches == [False]

def test_typed_settings_reject_invalid_profile_boolean_and_fit_range() -> None:
    with pytest.raises(ValidationError):
        SettingsPatch(ev_trip_profile="100 km")
    with pytest.raises(ValidationError):
        SettingsPatch(hot_water_fixed_timer="yes")
    with pytest.raises(ValidationError):
        SettingsPatch(hot_water_enabled="yes")
    with pytest.raises(ValidationError):
        SettingsPatch(ev_grid_allowed="false")
    with pytest.raises(ValidationError):
        SettingsPatch(ev_opportunistic_fit_max_per_kwh=1.001)
    assert SettingsPatch(ev_opportunistic_fit_max_per_kwh=1.0).ev_opportunistic_fit_max_per_kwh == 1.0


def test_five_minute_outcome_exposes_full_series_and_inferred_export_confidence() -> None:
    accumulator = OutcomeAccumulator(Settings())
    telemetry = Telemetry(
        measured_at=NOW, pv_kw=10, pv1_kw=3, pv2_kw=2, pv3_kw=5,
        load_kw=2, grid_kw=-10, battery_kw=2, soc_pct=80, soh_pct=97,
    )
    devices = DeviceState(ev_power_kw=0, hot_water_power_kw=0)
    assert accumulator.add(NOW, telemetry, devices, 0.5, 0.3, 0.8, 9) is None
    assert accumulator.add(NOW.replace(second=2), telemetry, devices, 0.5, 0.3, 0.8, 9) is None
    complete = accumulator.add(NOW.replace(minute=5), telemetry, devices, 0.5, 0.3, 0.8, 9)
    assert complete is not None
    for field in (
        "pv1_kwh", "pv2_kwh", "pv3_kwh", "average_pv1_kw", "average_house_load_kw",
        "average_battery_kw", "average_grid_kw", "average_ev_kw", "average_hot_water_kw",
        "average_server_rack_kw", "average_fit_per_kwh", "average_import_price_per_kwh",
        "solar_export_revenue", "battery_export_revenue", "wear_cost", "pv_forecast_abs_error_kwh",
    ):
        assert field in complete
    assert complete["export_attribution_method"] == "priority_inference_v1"
    assert complete["export_attribution_confidence_label"] in {"high", "medium", "low"}


def test_minute_average_accumulator_emits_one_preaggregated_frame() -> None:
    accumulator = MinuteAverageAccumulator()
    assert accumulator.add(NOW, {"pv_kw": 10.0, "grid_kw": -2.0, "state": "ok"}) is None
    assert accumulator.add(NOW.replace(second=30), {"pv_kw": 14.0, "grid_kw": -4.0}) is None
    complete = accumulator.add(NOW.replace(minute=1), {"pv_kw": 20.0, "grid_kw": -8.0})
    assert complete is not None
    at, fields = complete
    assert at == NOW
    assert fields == {"pv_kw": 12.0, "grid_kw": -3.0}


def test_outcome_ordinary_house_excludes_flexible_loads_from_backup_total() -> None:
    accumulator = OutcomeAccumulator(Settings())
    telemetry = Telemetry(
        measured_at=NOW, pv_kw=8, load_kw=8.7, grid_kw=0, battery_kw=-0.7,
        soc_pct=60, soh_pct=97,
    )
    devices = DeviceState(ev_power_kw=3.0, hot_water_power_kw=3.7)
    accumulator.add(NOW, telemetry, devices, 0.0, 0.3)
    accumulator.add(NOW.replace(second=2), telemetry, devices, 0.0, 0.3)
    complete = accumulator.add(NOW.replace(minute=5), telemetry, devices, 0.0, 0.3)
    assert complete is not None
    assert complete["average_house_load_kw"] == pytest.approx(2.0)
    assert complete["average_whole_house_load_kw"] == pytest.approx(8.7)
