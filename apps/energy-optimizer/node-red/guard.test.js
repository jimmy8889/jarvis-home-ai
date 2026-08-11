"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {evaluateFeedback, rampTarget, validatePlan} = require("./guard.js");

const nodeRedFlow = JSON.parse(fs.readFileSync(`${__dirname}/energy-optimizer-flow.json`, "utf8"));

function flowNode(id) {
  return nodeRedFlow.find((node) => node.id === id);
}

function input(overrides = {}) {
  const now = Date.parse("2026-08-11T02:00:00Z");
  return {
    nowMs: now,
    mode: "Active",
    rolloutApproved: "on",
    batteryControl: "on",
    manualOverride: "off",
    soc: 50,
    minSocPct: 5,
    pvPowerKw: 8,
    homeLoadKw: 3,
    planEntity: {state: "plan", attributes: {
      schema_version: 1,
      plan_id: "plan",
      generated_at: "2026-08-11T01:55:00Z",
      valid_until: "2026-08-11T02:05:00Z",
      mode: "active",
      actuation_allowed: true,
      action: "discharge_export",
      battery_power_target_kw: 20,
      site_export_target_kw: 18,
      pv_export_command: "allow",
    }},
    ...overrides,
  };
}

test("shadow mode explicitly safe-stops latched force modes", () => {
  const result = validatePlan(input({mode: "Shadow"}));
  assert.equal(result.actuate, false);
  assert.equal(result.safeStop, true);
  assert.equal(result.stopForced, true);
  assert.equal(result.pvExportCommand, "allow");
});

test("manual override explicitly safe-stops instead of leaving a command latched", () => {
  const result = validatePlan(input({manualOverride: "on"}));
  assert.equal(result.status, "manual_override");
  assert.equal(result.safeStop, true);
  assert.equal(result.stopForced, true);
});

test("rollout or battery disable is independently guarded", () => {
  assert.equal(validatePlan(input({rolloutApproved: "off"})).status, "rollout_not_approved");
  assert.equal(validatePlan(input({batteryControl: "off"})).status, "battery_control_off");
});

test("site export target is translated with live load and PV", () => {
  const result = validatePlan(input());
  assert.equal(result.status, "accepted_discharge");
  assert.equal(result.targetKw, 13); // 18 kW site export + 3 kW load - 8 kW PV
  assert.equal(result.plannedBatteryTargetKw, 20);
});

test("missing cap defaults to the full verified 28 kW limit", () => {
  const value = input({pvPowerKw: 1, homeLoadKw: 5});
  value.planEntity.attributes.site_export_target_kw = 30;
  value.planEntity.attributes.battery_power_target_kw = 28;
  const result = validatePlan(value);
  assert.equal(result.status, "accepted_discharge");
  assert.equal(result.targetKw, 28);
});

test("a stricter configured live cap is retained", () => {
  const value = input({maxDischargeCapKw: 12, pvPowerKw: 1, homeLoadKw: 5});
  value.planEntity.attributes.site_export_target_kw = 30;
  value.planEntity.attributes.battery_power_target_kw = 28;
  assert.equal(validatePlan(value).targetKw, 12);
});

test("PV already meeting the site target stops forced discharge", () => {
  const result = validatePlan(input({pvPowerKw: 25, homeLoadKw: 3}));
  assert.equal(result.status, "accepted_discharge_pv_meets_target");
  assert.equal(result.targetKw, 0);
  assert.equal(result.stopForced, true);
  assert.equal(result.safeStop, false);
});

test("stale active plan requests safe defaults", () => {
  const result = validatePlan(input({nowMs: Date.parse("2026-08-11T02:20:00Z")}));
  assert.equal(result.safeStop, true);
  assert.equal(result.status, "rejected_stale");
  assert.equal(result.pvExportCommand, "allow");
});

test("low SOC and a stricter live SAJ floor reject export", () => {
  assert.equal(validatePlan(input({soc: 5.5})).status, "rejected_discharge_guard");
  assert.equal(validatePlan(input({soc: 11, minSocPct: 10})).status, "rejected_discharge_guard");
});

test("unavailable live PV, load, SOC or floor rejects the plan", () => {
  assert.equal(validatePlan(input({pvPowerKw: "unavailable"})).status, "rejected_invalid_numeric");
  assert.equal(validatePlan(input({homeLoadKw: "unknown"})).status, "rejected_invalid_numeric");
  assert.equal(validatePlan(input({soc: ""})).status, "rejected_invalid_numeric");
  assert.equal(validatePlan(input({minSocPct: null})).status, "rejected_invalid_numeric");
});

test("full 30 kW charge is allowed while conflicting signs are rejected", () => {
  const value = input();
  value.planEntity.attributes.action = "grid_charge";
  value.planEntity.attributes.battery_power_target_kw = -30;
  value.planEntity.attributes.site_export_target_kw = 0;
  let result = validatePlan(value);
  assert.equal(result.status, "accepted_grid_charge");
  assert.equal(result.targetKw, 30);

  value.planEntity.attributes.battery_power_target_kw = 5;
  result = validatePlan(value);
  assert.equal(result.status, "rejected_charge_guard");
  assert.equal(result.safeStop, true);
});

test("negative-FIT curtailment is an explicit normal-mode stop, not a rejection", () => {
  const value = input();
  value.planEntity.attributes.action = "curtail_pv";
  value.planEntity.attributes.battery_power_target_kw = 0;
  value.planEntity.attributes.site_export_target_kw = 0;
  value.planEntity.attributes.pv_export_command = "curtail";
  const result = validatePlan(value);
  assert.equal(result.actuate, true);
  assert.equal(result.safeStop, false);
  assert.equal(result.stopForced, true);
  assert.equal(result.pvExportCommand, "curtail");
});

test("unknown and contradictory actions are rejected", () => {
  const unknown = input();
  unknown.planEntity.attributes.action = "force_everything";
  assert.equal(validatePlan(unknown).status, "rejected_conflicting_action");

  const contradictory = input();
  contradictory.planEntity.attributes.pv_export_command = "curtail";
  assert.equal(validatePlan(contradictory).status, "rejected_discharge_guard");
});

test("upward ramp reaches full discharge promptly and reductions are immediate", () => {
  const first = rampTarget(0, 28);
  assert.equal(first, 14);
  assert.equal(rampTarget(first, 28), 28);
  assert.equal(rampTarget(28, 7), 7);
});

test("SAJ feedback confirms exclusive mode plus a non-zero device current setpoint", () => {
  assert.deepEqual(
    evaluateFeedback({
      action: "discharge_export",
      targetKw: 14,
      dischargeMode: "on",
      chargeMode: "off",
      dischargeCurrentSet: 28.5,
    }),
    {ok: true, status: "feedback_confirmed_discharge", currentSet: 28.5},
  );
  assert.equal(evaluateFeedback({
    action: "grid_charge",
    targetKw: 14,
    dischargeMode: "off",
    chargeMode: "on",
    chargeCurrentSet: "unavailable",
  }).status, "feedback_unavailable_charge");
  assert.equal(evaluateFeedback({
    action: "grid_charge",
    targetKw: 14,
    dischargeMode: "on",
    chargeMode: "on",
    chargeCurrentSet: 20,
  }).status, "feedback_mismatch_charge");
});

test("all exported Node-RED function nodes compile", () => {
  for (const node of nodeRedFlow.filter((candidate) => candidate.type === "function")) {
    assert.doesNotThrow(() => new Function("msg", "flow", "global", node.func), node.name);
  }
});

test("Node-RED router applies the live translation and two-pass full ramp", () => {
  const node = flowNode("eop_validate_002");
  const run = new Function("msg", "flow", "global", node.func);
  const context = new Map();
  const flow = {
    get: (key) => context.get(key),
    set: (key, value) => context.set(key, value),
  };
  const value = input({pvPowerKw: 1, homeLoadKw: 5});
  value.planEntity.attributes.site_export_target_kw = 30;
  value.planEntity.attributes.battery_power_target_kw = 28;

  let outputs = run(structuredClone(value), flow, {});
  assert.equal(outputs[2].payload, 14);
  assert.match(outputs[0].payload, /request=28\.0 apply=14\.0kW/);
  outputs = run(structuredClone(value), flow, {});
  assert.equal(outputs[2].payload, 28);
  assert.equal(outputs[1], null);
});

test("Node-RED router emits stop plus normal export for every disarmed state", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const context = new Map([["energyOptimizerLastCommand", {action: "discharge_export", targetKw: 28}]]);
  const flow = {get: (key) => context.get(key), set: (key, value) => context.set(key, value)};
  const outputs = run(input({manualOverride: "on"}), flow, {});
  assert.equal(outputs[0].optimizer.status, "manual_override");
  assert.equal(outputs[1].payload, 0);
  assert.equal(outputs[4], null);
  assert.equal(outputs[5].payload, 1);
  assert.equal(context.get("energyOptimizerLastCommand").action, "none");
});

test("Node-RED live-state reader normalizes W to kW and rejects unknown units", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_read_live_state_002").func);
  const states = {
    "sensor.pv_power_mqtt_abs": {state: "12500", attributes: {unit_of_measurement: "W"}},
    "sensor.saj_home_load": {state: "2.75", attributes: {unit_of_measurement: "kW"}},
  };
  const result = run({}, {}, {get: () => ({homeAssistant: {states}})});
  assert.equal(result.pvPowerKw, 12.5);
  assert.equal(result.homeLoadKw, 2.75);

  states["sensor.saj_home_load"].attributes.unit_of_measurement = "VA";
  assert.equal(run({}, {}, {get: () => ({homeAssistant: {states}})}).homeLoadKw, null);
});

test("feedback failure path cancels force modes and restores export", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_feedback_confirm_002").func);
  const command = {action: "discharge_export", targetKw: 14, planId: "plan"};
  const context = new Map([["energyOptimizerLastCommand", command]]);
  const flow = {get: (key) => context.get(key), set: (key, value) => context.set(key, value)};
  const states = {
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "sensor.saj_battery_discharge_current_set": {state: "25", attributes: {unit_of_measurement: "A"}},
    "sensor.saj_battery_power_2": {state: "0", attributes: {unit_of_measurement: "W"}},
  };
  const outputs = run({command}, flow, {get: () => ({homeAssistant: {states}})});
  assert.match(outputs[0].payload, /^feedback_mismatch_discharge/);
  assert.equal(outputs[1].payload, 0);
  assert.equal(outputs[2].payload, 1);
  assert.equal(context.get("energyOptimizerLastCommand").action, "none");
});

test("safe-stop chain resets charge to 30 kW before restoring PV charging", () => {
  assert.deepEqual(flowNode("eop_stop_forced_002").entityId, [
    "input_boolean.battery_charge",
    "input_boolean.battery_discharge",
  ]);
  assert.deepEqual(flowNode("eop_stop_forced_002").wires, [["eop_reset_charge_rate_002"]]);
  assert.equal(flowNode("eop_reset_charge_rate_002").data, "{\"value\":30}");
  assert.deepEqual(flowNode("eop_reset_charge_rate_002").wires, [["eop_allow_pv_002"]]);
});

test("profitable forced export disables PV charging before discharge", () => {
  assert.deepEqual(flowNode("eop_discharge_chargeoff_002").wires, [["eop_discharge_pvoff_002"]]);
  assert.equal(flowNode("eop_discharge_pvoff_002").action, "input_boolean.turn_off");
  assert.deepEqual(flowNode("eop_discharge_pvoff_002").entityId, ["input_boolean.battery_pv_charge"]);
  assert.deepEqual(flowNode("eop_discharge_pvoff_002").wires, [["eop_discharge_on_002"]]);
});

test("feedback rejection traverses the complete safe-stop and export-restore paths", () => {
  assert.deepEqual(flowNode("eop_feedback_confirm_002").wires[1], ["eop_stop_forced_002"]);
  assert.deepEqual(flowNode("eop_feedback_confirm_002").wires[2], ["eop_allow_export_002"]);
  assert.deepEqual(flowNode("eop_stop_forced_002").wires, [["eop_reset_charge_rate_002"]]);
  assert.deepEqual(flowNode("eop_reset_charge_rate_002").wires, [["eop_allow_pv_002"]]);
});
