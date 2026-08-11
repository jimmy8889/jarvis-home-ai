"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {validatePlan} = require("./guard.js");

const nodeRedFlow = JSON.parse(fs.readFileSync(`${__dirname}/energy-optimizer-flow.json`, "utf8"));

function flowNode(id) {
  return nodeRedFlow.find((node) => node.id === id);
}

function upstreamNodeIds(targetId) {
  return nodeRedFlow
    .filter((node) => (node.wires || []).some((output) => output.includes(targetId)))
    .map((node) => node.id)
    .sort();
}

function runFeedback(command, states, nowMs = Date.parse("2026-08-11T02:00:00Z"), lastCommand = null) {
  const run = new Function("msg", "flow", "global", flowNode("eop_feedback_confirm_002").func);
  const stampedCommand = {issuedAtMs: nowMs - 12_000, ...command};
  const stampedLastCommand = lastCommand === null
    ? stampedCommand
    : {issuedAtMs: nowMs - 1_000, ...lastCommand};
  const context = new Map([["energyOptimizerLastCommand", stampedLastCommand]]);
  const flow = {get: (key) => context.get(key), set: (key, value) => context.set(key, value)};
  const outputs = run({command: stampedCommand, nowMs}, flow, {get: () => ({homeAssistant: {states}})});
  return {command: stampedCommand, context, lastCommand: stampedLastCommand, outputs};
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
    socHeartbeatMeasuredAtMs: now - 60 * 1000,
    pvMeasuredAtMs: now - 60 * 1000,
    homeLoadMeasuredAtMs: now - 60 * 1000,
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

test("high-PV site target remains valid while battery output is hard-clamped to 28 kW", () => {
  const value = input({pvPowerKw: 20, homeLoadKw: 1});
  value.planEntity.attributes.site_export_target_kw = 47;
  value.planEntity.attributes.battery_power_target_kw = 28;
  const result = validatePlan(value);
  assert.equal(result.status, "accepted_discharge");
  assert.equal(result.targetKw, 28); // 47 kW site + 1 kW load - 20 kW PV

  value.planEntity.attributes.site_export_target_kw = 100.01;
  assert.equal(validatePlan(value).status, "rejected_bounds");
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

  const exactExpiry = validatePlan(input({nowMs: Date.parse("2026-08-11T02:05:00Z")}));
  assert.equal(exactExpiry.status, "rejected_stale");
  assert.equal(exactExpiry.safeStop, true);
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

test("telemetry older than 330 seconds or missing measurement time safe-stops", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  for (const timestampField of ["socHeartbeatMeasuredAtMs", "pvMeasuredAtMs", "homeLoadMeasuredAtMs"]) {
    const stale = validatePlan(input({[timestampField]: now - 330001}));
    assert.equal(stale.status, "rejected_telemetry_stale", timestampField);
    assert.equal(stale.safeStop, true, timestampField);
    assert.equal(stale.stopForced, true, timestampField);
  }
  assert.equal(validatePlan(input({socHeartbeatMeasuredAtMs: null})).status, "rejected_telemetry_timestamp");
  assert.equal(validatePlan(input({pvMeasuredAtMs: "unknown"})).status, "rejected_telemetry_timestamp");

  const exactBoundary = validatePlan(input({
    socHeartbeatMeasuredAtMs: now - 330000,
    pvMeasuredAtMs: now - 330000,
    homeLoadMeasuredAtMs: now - 330000,
  }));
  assert.equal(exactBoundary.status, "accepted_discharge");
  assert.equal(exactBoundary.telemetryAgeSeconds.socHeartbeat, 330);
});

test("static inverter floor needs no measurement timestamp", () => {
  const result = validatePlan(input({soc: 12, minSocPct: 10}));
  assert.equal(result.status, "accepted_discharge");
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

test("all exported Node-RED function nodes compile", () => {
  for (const node of nodeRedFlow.filter((candidate) => candidate.type === "function")) {
    assert.doesNotThrow(() => new Function("msg", "flow", "global", node.func), node.name);
  }
});

test("Node-RED router applies the full translated 28 kW target on its first invocation", () => {
  const node = flowNode("eop_validate_002");
  const run = new Function("msg", "flow", "global", node.func);
  const context = new Map();
  const flow = {
    get: (key) => context.get(key),
    set: (key, value) => context.set(key, value),
  };
  const value = input({pvPowerKw: 20, homeLoadKw: 1});
  value.planEntity.attributes.site_export_target_kw = 47;
  value.planEntity.attributes.battery_power_target_kw = 28;

  const outputs = run(structuredClone(value), flow, {});
  assert.equal(outputs[2].payload, 28);
  assert.match(outputs[0].payload, /request=28\.0 apply=28\.0kW/);
  assert.equal(outputs[1], null);
  assert.deepEqual(context.get("energyOptimizerLastCommand"), {
    action: "discharge_export",
    targetKw: 28,
    planId: "plan",
    issuedAtMs: value.nowMs,
  });
  assert.equal(outputs[2].command.issuedAtMs, value.nowMs);
});

test("accepted plans arm a replaceable dynamic one-shot without delaying command output", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_arm_deadline_002").func);
  const context = new Map();
  const flow = {get: (key) => context.get(key), set: (key, value) => context.set(key, value)};
  const firstDeadline = Date.now() + 5000;
  const first = run({optimizer: {
    actuate: true,
    safeStop: false,
    planId: "first",
    validUntilMs: firstDeadline,
  }}, flow, {});
  assert.equal(first.deadlinePlanId, "first");
  assert.equal(first.deadlineAtMs, firstDeadline);
  assert.ok(first.delay > 0 && first.delay <= 5000);
  assert.deepEqual(context.get("energyOptimizerPlanDeadline"), {
    planId: "first",
    validUntilMs: firstDeadline,
  });

  const replacementDeadline = Date.now() + 10000;
  const replacement = run({optimizer: {
    actuate: true,
    safeStop: false,
    planId: "replacement",
    validUntilMs: replacementDeadline,
  }}, flow, {});
  assert.equal(replacement.deadlinePlanId, "replacement");
  assert.deepEqual(context.get("energyOptimizerPlanDeadline"), {
    planId: "replacement",
    validUntilMs: replacementDeadline,
  });

  const reset = run({optimizer: {actuate: false, safeStop: true, planId: "rejected"}}, flow, {});
  assert.equal(reset.reset, true);
  assert.equal(context.get("energyOptimizerPlanDeadline"), null);

  const timer = flowNode("eop_plan_deadline_timer_002");
  assert.equal(timer.op1type, "nul");
  assert.equal(timer.extend, true);
  assert.equal(timer.overrideDelay, true);
  assert.equal(timer.units, "ms");
  assert.equal(timer.bytopic, "all");
  assert.equal(flowNode("eop_watchdog_002").repeat, "60");
  assert.deepEqual(flowNode("eop_validate_002").wires[2], ["eop_set_discharge_002"]);
});

test("matching one-shot expiry immediately safe-stops while superseded deadlines are ignored", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_plan_deadline_expired_002").func);
  const expiredAt = Date.now() - 1;
  const context = new Map([
    ["energyOptimizerPlanDeadline", {planId: "expired", validUntilMs: expiredAt}],
    ["energyOptimizerLastCommand", {action: "discharge_export", targetKw: 28, planId: "expired"}],
  ]);
  const flow = {get: (key) => context.get(key), set: (key, value) => context.set(key, value)};
  const outputs = run({deadlinePlanId: "expired", deadlineAtMs: expiredAt}, flow, {});
  assert.match(outputs[0].payload, /^rejected_expired_deadline \| expired/);
  assert.equal(outputs[1].payload, 0);
  assert.equal(outputs[2].payload, 1);
  assert.equal(outputs[3], null);
  assert.equal(context.get("energyOptimizerPlanDeadline"), null);
  assert.deepEqual(context.get("energyOptimizerLastCommand"), {
    action: "none",
    targetKw: 0,
    planId: "expired",
  });
  assert.deepEqual(flowNode("eop_plan_deadline_expired_002").wires, [
    ["eop_audit_002"],
    ["eop_stop_forced_002"],
    ["eop_allow_export_raw_002"],
    ["eop_plan_deadline_timer_002"],
  ]);

  context.set("energyOptimizerPlanDeadline", {planId: "newer", validUntilMs: expiredAt + 300000});
  const superseded = run({deadlinePlanId: "expired", deadlineAtMs: expiredAt}, flow, {});
  assert.deepEqual(superseded, [null, null, null, null]);

  const futureDeadline = Date.now() + 5000;
  context.set("energyOptimizerPlanDeadline", {planId: "future", validUntilMs: futureDeadline});
  const early = run({deadlinePlanId: "future", deadlineAtMs: futureDeadline}, flow, {});
  assert.equal(early[0], null);
  assert.equal(early[1], null);
  assert.equal(early[2], null);
  assert.ok(early[3].delay > 0 && early[3].delay <= 5000);
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

test("stale unchanged SOC uses the fresh SAJ battery-power heartbeat", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  const freshHeartbeat = "2026-08-11T01:59:50Z";
  const staleSocTimestamp = "2026-08-11T01:00:00Z";
  const states = {
    "sensor.saj_battery_1_soc": {
      state: "100",
      attributes: {unit_of_measurement: "%"},
      last_reported: staleSocTimestamp,
      last_updated: staleSocTimestamp,
    },
    "sensor.saj_battery_power": {
      state: "0",
      attributes: {unit_of_measurement: "W"},
      last_reported: freshHeartbeat,
      last_updated: staleSocTimestamp,
    },
    "sensor.pv_power_mqtt_abs": {
      state: "20000",
      attributes: {unit_of_measurement: "W"},
      last_reported: "invalid",
      last_updated: "2026-08-11T01:59:45Z",
    },
    "sensor.saj_home_load": {
      state: "1",
      attributes: {unit_of_measurement: "kW"},
      last_updated: "2026-08-11T01:59:40Z",
    },
  };
  const read = new Function("msg", "flow", "global", flowNode("eop_read_live_state_002").func);
  const live = read({}, {}, {get: () => ({homeAssistant: {states}})});
  assert.equal(live.socHeartbeatMeasuredAtMs, Date.parse(freshHeartbeat));
  assert.notEqual(live.socHeartbeatMeasuredAtMs, Date.parse(staleSocTimestamp));
  assert.equal(live.pvMeasuredAtMs, Date.parse("2026-08-11T01:59:45Z"));
  assert.equal(live.homeLoadMeasuredAtMs, Date.parse("2026-08-11T01:59:40Z"));

  const value = input({
    nowMs: now,
    soc: live.soc,
    pvPowerKw: live.pvPowerKw,
    homeLoadKw: live.homeLoadKw,
    socHeartbeatMeasuredAtMs: live.socHeartbeatMeasuredAtMs,
    pvMeasuredAtMs: live.pvMeasuredAtMs,
    homeLoadMeasuredAtMs: live.homeLoadMeasuredAtMs,
  });
  value.planEntity.attributes.site_export_target_kw = 47;
  value.planEntity.attributes.battery_power_target_kw = 28;
  const accepted = validatePlan(value);
  assert.equal(accepted.status, "accepted_discharge");
  assert.equal(accepted.targetKw, 28);
  assert.equal(accepted.telemetryAgeSeconds.socHeartbeat, 10);
});

test("missing, unavailable or stale SAJ battery-power heartbeat safe-stops", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  const baseStates = {
    "sensor.saj_battery_1_soc": {
      state: "100",
      attributes: {unit_of_measurement: "%"},
      last_reported: "2026-08-11T01:00:00Z",
    },
    "sensor.pv_power_mqtt_abs": {
      state: "8000",
      attributes: {unit_of_measurement: "W"},
      last_reported: "2026-08-11T01:59:45Z",
    },
    "sensor.saj_home_load": {
      state: "1",
      attributes: {unit_of_measurement: "kW"},
      last_reported: "2026-08-11T01:59:40Z",
    },
  };
  const read = new Function("msg", "flow", "global", flowNode("eop_read_live_state_002").func);
  const readStates = (states) => read({}, {}, {get: () => ({homeAssistant: {states}})});
  const validateRead = (live) => validatePlan(input({
    nowMs: now,
    soc: live.soc,
    pvPowerKw: live.pvPowerKw,
    homeLoadKw: live.homeLoadKw,
    socHeartbeatMeasuredAtMs: live.socHeartbeatMeasuredAtMs,
    pvMeasuredAtMs: live.pvMeasuredAtMs,
    homeLoadMeasuredAtMs: live.homeLoadMeasuredAtMs,
  }));

  const missing = readStates(baseStates);
  assert.equal(missing.socHeartbeatMeasuredAtMs, null);
  assert.equal(validateRead(missing).status, "rejected_telemetry_timestamp");

  const unavailable = readStates({...baseStates, "sensor.saj_battery_power": {
    state: "unavailable",
    attributes: {unit_of_measurement: "W"},
    last_reported: "2026-08-11T01:59:50Z",
  }});
  assert.equal(unavailable.socHeartbeatMeasuredAtMs, null);
  assert.equal(validateRead(unavailable).status, "rejected_telemetry_timestamp");

  const stale = readStates({...baseStates, "sensor.saj_battery_power": {
    state: "0",
    attributes: {unit_of_measurement: "W"},
    last_reported: "2026-08-11T01:54:29.999Z",
  }});
  assert.equal(validateRead(stale).status, "rejected_telemetry_stale");

  const boundary = readStates({...baseStates, "sensor.saj_battery_power": {
    state: "0",
    attributes: {unit_of_measurement: "W"},
    last_reported: "2026-08-11T01:54:30.000Z",
  }});
  assert.equal(validateRead(boundary).status, "accepted_discharge");
});

test("fresh signed physical battery power confirms discharge and charge", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  const discharge = {action: "discharge_export", targetKw: 28, planId: "discharge"};
  const dischargeResult = runFeedback(discharge, {
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "sensor.saj_battery_power": {
      state: "3400",
      attributes: {unit_of_measurement: "W"},
      last_reported: "2026-08-11T01:59:50Z",
    },
  }, now);
  assert.match(dischargeResult.outputs[0].payload, /^feedback_confirmed_discharge/);
  assert.match(dischargeResult.outputs[0].payload, /battery=3\.40kW min=1\.00kW age=10000ms after_issue=2000ms mode=exclusive/);
  assert.equal(dischargeResult.outputs[1], null);
  assert.equal(dischargeResult.outputs[2], null);
  assert.deepEqual(dischargeResult.context.get("energyOptimizerLastCommand"), dischargeResult.command);

  const charge = {action: "grid_charge", targetKw: 30, planId: "charge"};
  const chargeResult = runFeedback(charge, {
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "input_boolean.battery_charge": {state: "on", attributes: {}},
    "sensor.saj_battery_power": {
      state: "-6.8",
      attributes: {unit_of_measurement: "kW"},
      last_reported: "invalid",
      last_updated: "2026-08-11T01:59:50Z",
    },
  }, now);
  assert.match(chargeResult.outputs[0].payload, /^feedback_confirmed_charge/);
  assert.match(chargeResult.outputs[0].payload, /battery=-6\.80kW min=1\.00kW age=10000ms after_issue=2000ms mode=exclusive/);
  assert.equal(chargeResult.outputs[1], null);
  assert.equal(chargeResult.outputs[2], null);
});

test("missing, stale, future, pre-command, wrong-sign and too-small physical feedback safe-stop", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  const discharge = {action: "discharge_export", targetKw: 14, planId: "plan"};
  const base = {
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
  };
  const cases = [
    {name: "missing entity", states: base, expected: "feedback_unavailable_discharge"},
    {name: "unavailable state", states: {...base, "sensor.saj_battery_power": {
      state: "unavailable", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
    }}, expected: "feedback_unavailable_discharge"},
    {name: "invalid unit", states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "VA"}, last_reported: "2026-08-11T01:59:50Z",
    }}, expected: "feedback_unavailable_discharge"},
    {name: "missing timestamp", states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "W"},
    }}, expected: "feedback_unavailable_discharge"},
    {name: "stale timestamp", states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:58:59.999Z",
    }}, expected: "feedback_stale_discharge"},
    {name: "future timestamp", states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T02:00:00.001Z",
    }}, expected: "feedback_stale_discharge"},
    {name: "sample predates command", states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:47.999Z",
    }}, expected: "feedback_precommand_discharge"},
    {name: "missing command issuance", command: {
      action: "discharge_export", targetKw: 14, planId: "missing-issued", issuedAtMs: null,
    }, states: {...base, "sensor.saj_battery_power": {
      state: "3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
    }}, expected: "feedback_invalid_command"},
    {name: "wrong discharge sign", states: {...base, "sensor.saj_battery_power": {
      state: "-3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
    }}, expected: "feedback_wrong_sign_discharge"},
    {name: "too little achieved power", states: {...base, "sensor.saj_battery_power": {
      state: "100", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
    }}, expected: "feedback_too_small_discharge"},
    {name: "non-exclusive helper mode", states: {...base,
      "input_boolean.battery_charge": {state: "on", attributes: {}},
      "sensor.saj_battery_power": {
        state: "3400", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
      },
    }, expected: "feedback_mode_mismatch_discharge"},
    {name: "wrong charge sign", command: {action: "grid_charge", targetKw: 30, planId: "charge"}, states: {
      "input_boolean.battery_discharge": {state: "off", attributes: {}},
      "input_boolean.battery_charge": {state: "on", attributes: {}},
      "sensor.saj_battery_power": {
        state: "6800", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-11T01:59:50Z",
      },
    }, expected: "feedback_wrong_sign_charge"},
  ];

  for (const scenario of cases) {
    const command = scenario.command || discharge;
    const {context, outputs} = runFeedback(command, scenario.states, now);
    assert.match(outputs[0].payload, new RegExp(`^${scenario.expected}`), scenario.name);
    assert.equal(outputs[1].payload, 0, scenario.name);
    assert.equal(outputs[2].payload, 1, scenario.name);
    assert.deepEqual(context.get("energyOptimizerLastCommand"), {
      action: "none",
      targetKw: 0,
      planId: command.planId,
    }, scenario.name);
  }
});

test("same-target delayed feedback cannot supersede a newer plan or command issuance", () => {
  const now = Date.parse("2026-08-11T02:00:00Z");
  const states = {
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "sensor.saj_battery_power": {
      state: "3400",
      attributes: {unit_of_measurement: "W"},
      last_reported: "2026-08-11T01:59:59Z",
    },
  };
  const delayed = {action: "discharge_export", targetKw: 28, planId: "old-plan"};
  const newerPlan = {action: "discharge_export", targetKw: 28, planId: "new-plan"};
  const planResult = runFeedback(delayed, states, now, newerPlan);
  assert.match(planResult.outputs[0].payload, /^feedback_superseded \| old-plan/);
  assert.equal(planResult.outputs[1], null);
  assert.equal(planResult.outputs[2], null);
  assert.deepEqual(planResult.context.get("energyOptimizerLastCommand"), planResult.lastCommand);

  const samePlan = {action: "discharge_export", targetKw: 28, planId: "same-plan"};
  const issuanceResult = runFeedback(samePlan, states, now, samePlan);
  assert.match(issuanceResult.outputs[0].payload, /^feedback_superseded \| same-plan/);
  assert.equal(issuanceResult.outputs[1], null);
  assert.equal(issuanceResult.outputs[2], null);
  assert.deepEqual(issuanceResult.context.get("energyOptimizerLastCommand"), issuanceResult.lastCommand);
});

test("physical feedback uses a 15-second post-command observation window", () => {
  const delay = flowNode("eop_feedback_delay_002");
  assert.equal(delay.pauseType, "delay");
  assert.equal(delay.timeout, "15");
  assert.equal(delay.timeoutUnits, "seconds");
  assert.deepEqual(delay.wires, [["eop_feedback_confirm_002"]]);
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
  assert.deepEqual(flowNode("eop_feedback_confirm_002").wires[2], ["eop_allow_export_raw_002"]);
  assert.deepEqual(flowNode("eop_stop_forced_002").wires, [["eop_reset_charge_rate_002"]]);
  assert.deepEqual(flowNode("eop_reset_charge_rate_002").wires, [["eop_allow_pv_002"]]);
});

test("every curtail path reasserts raw register 0 before helper synchronization", () => {
  const raw = flowNode("eop_curtail_raw_002");
  assert.equal(raw.action, "number.set_value");
  assert.deepEqual(raw.entityId, ["number.saj_export_limit_input"]);
  assert.equal(raw.data, "{\"value\":0}");
  assert.deepEqual(raw.wires, [["eop_curtail_002"]]);
  assert.deepEqual(upstreamNodeIds("eop_curtail_raw_002"), ["eop_validate_002"]);
  assert.deepEqual(upstreamNodeIds("eop_curtail_002"), ["eop_curtail_raw_002"]);
  assert.equal(flowNode("eop_curtail_002").action, "input_boolean.turn_off");
});

test("every allow and safe-stop path reasserts raw register 1100 before helper synchronization", () => {
  const raw = flowNode("eop_allow_export_raw_002");
  assert.equal(raw.action, "number.set_value");
  assert.deepEqual(raw.entityId, ["number.saj_export_limit_input"]);
  assert.equal(raw.data, "{\"value\":1100}");
  assert.deepEqual(raw.wires, [["eop_allow_export_002"]]);
  assert.deepEqual(upstreamNodeIds("eop_allow_export_raw_002"), [
    "eop_feedback_confirm_002",
    "eop_plan_deadline_expired_002",
    "eop_validate_002",
  ]);
  assert.deepEqual(upstreamNodeIds("eop_allow_export_002"), ["eop_allow_export_raw_002"]);
  assert.equal(flowNode("eop_allow_export_002").action, "input_boolean.turn_on");
});
