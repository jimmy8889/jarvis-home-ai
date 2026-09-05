from datetime import datetime, timedelta, timezone

from ben_energy_optimizer.config import ENTITY, Settings
from ben_energy_optimizer.optimizer import build_plan, dynamic_reserve_pct


NOW = datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc)


def state(value, *, attrs=None, updated=NOW):
    return {"state": str(value), "attributes": attrs or {}, "last_updated": updated.isoformat()}


def states(fit=0.20, imp=0.04, soc=50, pv=1, load=0.5):
    attrs_fit = {"start_time": NOW.isoformat(), "end_time": (NOW + timedelta(minutes=5)).isoformat(), "forecast": []}
    attrs_imp = dict(attrs_fit)
    return {
        ENTITY["amber_fit"]: state(fit, attrs=attrs_fit), ENTITY["amber_import"]: state(imp, attrs=attrs_imp),
        ENTITY["soc"]: state(soc), ENTITY["battery"]: state(0), ENTITY["pv"]: state(pv), ENTITY["load"]: state(load), ENTITY["grid"]: state(-0.5),
        ENTITY["buy_floor"]: state(0.05), ENTITY["sell_floor"]: state(0.15), ENTITY["enabled"]: state("on"), ENTITY["manual_mode"]: state("Stopped"), ENTITY["manual_rate"]: state(1),
    }


def test_sells_above_floor_and_never_below_reserve():
    plan = build_plan(states(), Settings(), NOW, [0.3] * 10)
    assert plan["action"] == "discharge"
    assert plan["battery_power_target_kw"] > 0
    assert plan["dynamic_reserve_pct"] >= 5


def test_does_not_sell_below_floor():
    assert build_plan(states(fit=0.14), Settings(), NOW, [0.3] * 10)["action"] != "discharge"


def test_buy_requires_ceiling_and_profitable_future():
    s = states(fit=0.01, imp=0.04, soc=20)
    future = NOW + timedelta(minutes=5)
    s[ENTITY["amber_fit"]]["attributes"]["forecast"] = [{"time": future.isoformat(), "value": 0.40}]
    s[ENTITY["amber_import"]]["attributes"]["forecast"] = [{"time": future.isoformat(), "value": 0.20}]
    assert build_plan(s, Settings(), NOW, [0.3] * 10)["action"] == "charge"
    s[ENTITY["amber_import"]]["state"] = "0.06"
    assert build_plan(s, Settings(), NOW, [0.3] * 10)["action"] != "charge"


def test_negative_fit_is_zero_export():
    plan = build_plan(states(fit=-0.02, imp=0.08), Settings(), NOW, [0.3] * 10)
    assert plan["action"] == "zero_export"
    assert plan["grid_export_limit_kw"] == 0


def test_manual_has_priority_and_optimizer_does_not_actuate():
    s = states()
    s[ENTITY["manual_mode"]]["state"] = "Export"
    plan = build_plan(s, Settings(), NOW, [0.3] * 10)
    assert plan["action"] == "manual_override"
    assert not plan["actuation_allowed"]


def test_invalid_or_stale_inputs_fail_closed():
    s = states()
    s[ENTITY["pv"]]["last_updated"] = (NOW - timedelta(minutes=6)).isoformat()
    plan = build_plan(s, Settings(), NOW, [0.3] * 10)
    assert not plan["actuation_allowed"]
    assert plan["battery_power_target_kw"] == 0


def test_unchanged_soc_uses_fresh_same_inverter_battery_heartbeat():
    s = states(fit=0.20, soc=50)
    s[ENTITY["soc"]]["last_updated"] = (NOW - timedelta(hours=1)).isoformat()
    assert build_plan(s, Settings(), NOW, [0.3] * 10)["actuation_allowed"]


def test_stale_battery_heartbeat_fails_closed():
    s = states(fit=0.20, soc=50)
    s[ENTITY["battery"]]["last_updated"] = (NOW - timedelta(minutes=6)).isoformat()
    assert not build_plan(s, Settings(), NOW, [0.3] * 10)["actuation_allowed"]


def test_price_window_must_be_exact_current_five_minutes():
    s = states()
    s[ENTITY["amber_fit"]]["attributes"]["end_time"] = (NOW + timedelta(hours=1)).isoformat()
    assert not build_plan(s, Settings(), NOW)["actuation_allowed"]


def test_reserve_fallback_and_learned_floor():
    cfg = Settings()
    assert dynamic_reserve_pct(cfg, [0.5] * 6, 4) == 14
    assert dynamic_reserve_pct(cfg, [0.2] * 10, 1) >= 5


def test_efficiency_wear_and_uncertainty_block_bad_cycle():
    s = states(fit=0.01, imp=0.05, soc=20)
    future = NOW + timedelta(minutes=5)
    s[ENTITY["amber_fit"]]["attributes"]["forecast"] = [{"time": future.isoformat(), "value": 0.14}]
    s[ENTITY["amber_import"]]["attributes"]["forecast"] = [{"time": future.isoformat(), "value": 0.10}]
    assert build_plan(s, Settings(), NOW, [0.3] * 10)["action"] != "charge"


def test_live_watt_telemetry_is_converted_to_kw():
    s = states(fit=0.20, soc=50)
    for key, value in (("pv", 1000), ("load", 500), ("grid", -500), ("battery", 0)):
        s[ENTITY[key]] = state(value, attrs={"unit_of_measurement": "W"})
    plan = build_plan(s, Settings(), NOW, [0.3] * 10)
    assert plan["actuation_allowed"]
    assert plan["pv_kw"] == 1
    assert plan["load_kw"] == 0.5
