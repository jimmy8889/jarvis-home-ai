"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const {decide, feedback} = require("./guard");

const now = Date.parse("2026-08-18T04:00:00Z");
const st = value => ({state: String(value), last_updated: new Date(now).toISOString()});
const states = {soc: st(50), pv: st(1), load: st(0.5), grid: st(-0.5), battery: st(0)};
const plan = {schema_version: 1, plan_id: "p1", revision: "p1", generated_at: new Date(now).toISOString(), valid_until: new Date(now + 300000).toISOString(), actuation_allowed: true, battery_power_target_kw: 10, site_grid_target_kw: -10.5, grid_export_limit_kw: 25, dynamic_reserve_pct: 10};

test("accepted automatic command is immediate full target", () => assert.equal(decide({states, plan}, now).batteryKw, 10));
test("expired plan safe stops", () => assert.equal(decide({states, plan}, now + 300000).action, "safe_stop"));
test("disarmed plan safe stops", () => assert.equal(decide({states, plan: {...plan, actuation_allowed: false}}, now).action, "safe_stop"));
test("manual import has absolute priority and translates site target", () => {
  const result = decide({states, plan, manualMode: "Import", manualRate: 1}, now);
  assert.equal(result.manual, true); assert.equal(result.siteGridKw, 1); assert.equal(result.batteryKw, -1.5);
});
test("manual export translates site target", () => {
  const result = decide({states, manualMode: "Export", manualRate: 1}, now);
  assert.equal(result.siteGridKw, -1); assert.equal(result.batteryKw, 0.5);
});
test("manual export never commands charging during the transition", () => {
  const charging = {...states, battery: st(-1.2), grid: st(0)};
  assert.equal(decide({states: charging, manualMode: "Export", manualRate: 1}, now).batteryKw, 0);
});
test("manual import never commands discharging during the transition", () => {
  const discharging = {...states, battery: st(1.2), grid: st(0)};
  assert.equal(decide({states: discharging, manualMode: "Import", manualRate: 1}, now).batteryKw, 0);
});
test("invalid manual rate cancels and latches", () => assert.equal(decide({states, manualMode: "Export", manualRate: 26}, now).cancelManual, true));
test("manual discharge cannot cross 5 percent floor", () => assert.equal(decide({states: {...states, soc: st(5)}, manualMode: "Export", manualRate: 1}, now).fault, "soc_floor"));
test("stale telemetry fails closed", () => assert.equal(decide({states: {...states, pv: {...st(1), last_updated: new Date(now - 331000).toISOString()}}, plan}, now).fault, "telemetry_stale"));
test("unchanged SOC accepts a fresh same-inverter battery heartbeat", () => {
  const oldSoc = {...st(50), last_updated: new Date(now - 3600000).toISOString()};
  assert.equal(decide({states: {...states, soc: oldSoc}, plan}, now).ok, true);
});
test("stale battery heartbeat fails closed", () => {
  const oldBattery = {...st(0), last_updated: new Date(now - 331000).toISOString()};
  assert.equal(decide({states: {...states, battery: oldBattery}, plan}, now).fault, "telemetry_stale");
});
test("alarm fails closed", () => assert.equal(decide({states, plan, alarm: true}, now).action, "safe_stop"));
test("negative FIT plan can command zero export", () => assert.equal(decide({states, plan: {...plan, battery_power_target_kw: 0, site_grid_target_kw: 0, grid_export_limit_kw: 0}}, now).action, "zero_export"));
test("feedback proves discharge direction", () => assert.equal(feedback({action: "discharge", manual: false}, {...states, battery: st(2)}, now).ok, true));
test("feedback rejects wrong charge direction", () => assert.equal(feedback({action: "charge", manual: false}, {...states, battery: st(2)}, now).ok, false));
test("manual feedback checks physical site meter", () => assert.equal(feedback({action: "charge", manual: true, siteGridKw: 1}, {...states, battery: st(-2), grid: st(4)}, now).fault, "feedback_grid_target_missed"));
test("manual feedback calculates a closed-loop battery correction", () => {
  const result = feedback(
    {action: "discharge", manual: true, batteryKw: 0.65, siteGridKw: -1},
    {...states, battery: st(0.66), grid: st(-0.35)},
    now,
  );
  assert.equal(result.ok, false);
  assert.ok(Math.abs(result.correctedBatteryKw - 1.3) < 1e-9);
});
