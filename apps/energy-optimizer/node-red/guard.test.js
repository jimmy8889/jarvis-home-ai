"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {validatePlan} = require("./guard.js");

function input(overrides = {}) {
  const now = Date.parse("2026-08-11T02:00:00Z");
  return {
    nowMs: now,
    mode: "Active",
    batteryControl: "on",
    manualOverride: "off",
    soc: 50,
    maxDischargeCapKw: 10,
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

test("shadow mode never actuates", () => {
  const result = validatePlan(input({mode: "Shadow"}));
  assert.equal(result.actuate, false);
});

test("discharge target is capped during initial rollout", () => {
  const result = validatePlan(input());
  assert.equal(result.status, "accepted_discharge");
  assert.equal(result.targetKw, 10);
});

test("stale active plan requests a safe stop", () => {
  const result = validatePlan(input({nowMs: Date.parse("2026-08-11T02:20:00Z")}));
  assert.equal(result.safeStop, true);
  assert.equal(result.status, "rejected_stale");
  assert.equal(result.pvExportCommand, "allow");
});

test("low SOC rejects export", () => {
  const result = validatePlan(input({soc: 5.5}));
  assert.equal(result.safeStop, true);
  assert.equal(result.status, "rejected_discharge_guard");
});

test("manual override prevents any service action", () => {
  const result = validatePlan(input({manualOverride: "on"}));
  assert.equal(result.actuate, false);
  assert.equal(result.status, "manual_override");
});

test("negative FIT curtailment is accepted only as an explicit command", () => {
  const value = input();
  value.planEntity.attributes.action = "curtail_pv";
  value.planEntity.attributes.battery_power_target_kw = 0;
  value.planEntity.attributes.site_export_target_kw = 0;
  value.planEntity.attributes.pv_export_command = "curtail";
  const result = validatePlan(value);
  assert.equal(result.actuate, true);
  assert.equal(result.safeStop, true);
  assert.equal(result.pvExportCommand, "curtail");
});
