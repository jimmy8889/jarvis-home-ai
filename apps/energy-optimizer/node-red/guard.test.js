"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {
  BATTERY_MODES,
  batteryDischargeLimitTargetChanged,
  batteryDischargeLimitSensorToRegister,
  binaryOn,
  buildNodeRedSources,
  conservativeCurtail,
  evaluateDirectionFeedback,
  evaluateTargetFeedback,
  exportRateOnlyEligible,
  sameSemanticPhysicalCommand,
  feedbackTolerance,
  forcePowerPercent,
  pvChargePowerLimitForKw,
  reserveTargetChanged,
  statusText,
  validatePlan,
  verifyRegisterState,
} = require("./guard.js");
const {TAB_ID, buildFlow, replaceTab} = require("./build-flow.js");

const flowJson = JSON.parse(fs.readFileSync(`${__dirname}/energy-optimizer-flow.json`, "utf8"));
const nodeSources = buildNodeRedSources();
const NOW = Date.parse("2026-08-18T02:00:00Z");

function flowNode(id) {
  return flowJson.find((node) => node.id === id);
}

function context(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    flow: {
      get: (key) => values.get(key),
      set: (key, value) => values.set(key, value),
    },
  };
}

function planForMode(mode) {
  const targets = {
    export: {signed: 28, charge: 0, discharge: 28, site: 30, pv: "allow"},
    grid_charge: {signed: -30, charge: 30, discharge: 0, site: 0, pv: "allow"},
    pv_charge: {signed: -20, charge: 20, discharge: 0, site: 0, pv: "allow"},
    self_consume: {signed: 0, charge: 0, discharge: 0, site: 0, pv: "allow"},
    hold: {signed: 0, charge: 0, discharge: 0, site: 0, pv: "allow"},
  }[mode];
  return {
    schema_version: 2,
    plan_id: `plan-${mode}`,
    generated_at: "2026-08-18T01:59:30Z",
    valid_until: "2026-08-18T02:09:30Z",
    price_interval_start: "2026-08-18T01:55:00Z",
    price_interval_end: "2026-08-18T02:05:00Z",
    mode: "active",
    actuation_allowed: true,
    battery_mode: mode,
    battery_power_target_kw: targets.signed,
    battery_charge_target_kw: targets.charge,
    battery_discharge_target_kw: targets.discharge,
    site_export_target_kw: targets.site,
    protected_soc_pct: 7,
    pv_export_command: targets.pv,
    live_fit_price: 0.45,
    live_import_price: 0.31,
    minimum_sell_price: 0.12,
    effective_sell_price: 0.12,
    source_timestamps: {
      amber_fit: "2026-08-18T01:59:50Z",
      amber_import: "2026-08-18T01:59:50Z",
      battery_soc: "2026-08-18T01:59:50Z",
      battery_soc_heartbeat: "2026-08-18T01:59:50Z",
      pv_power: "2026-08-18T01:59:50Z",
      pv_heartbeat: "2026-08-18T01:59:50Z",
      home_load: "2026-08-18T01:59:50Z",
    },
    software_version: "2.0.0",
    config_fingerprint: "sha256:test-config",
    command_semantic_hash: `semantic-${mode}`,
    hot_water_control_mode: "off",
  };
}

function input(mode = "export", overrides = {}) {
  return {
    nowMs: NOW,
    mode: "Active",
    rolloutApproved: "on",
    batteryControl: "on",
    manualOverride: "off",
    soc: 50.2,
    minSocPct: 5,
    maxDischargeCapKw: 28,
    pvPowerKw: 12,
    homeLoadKw: 3,
    socHeartbeatMeasuredAtMs: NOW - 10_000,
    pvMeasuredAtMs: NOW - 10_000,
    homeLoadMeasuredAtMs: NOW - 10_000,
    liveFitPrice: 0.45,
    liveFitMeasuredAtMs: NOW - 10_000,
    liveImportPrice: 0.31,
    liveImportMeasuredAtMs: NOW - 10_000,
    sunState: "above_horizon",
    reserveNumberPct: 5,
    reserveSensorPct: 5,
    reserveSensorMeasuredAtMs: NOW - 10_000,
    reserveControlAvailable: true,
    batteryDischargeLimitNumber: 1000,
    batteryDischargeLimitSensor: 1000,
    batteryDischargeLimitSensorMeasuredAtMs: NOW - 10_000,
    batteryDischargeLimitControlAvailable: true,
    planEntity: {state: `plan-${mode}`, attributes: planForMode(mode)},
    ...overrides,
  };
}

function mutatePlan(value, attributes) {
  value.planEntity = {
    ...value.planEntity,
    attributes: {...value.planEntity.attributes, ...attributes},
  };
  return value;
}

function expectedActual(transaction, overrides = {}) {
  return {
    reserveNumberPct: transaction.reservePct,
    reserveSensorPct: transaction.reservePct,
    batteryDischargeLimitNumber: transaction.batteryDischargeLimit,
    batteryDischargeLimitSensor: transaction.batteryDischargeLimit,
    antiRefluxMode: transaction.antiRefluxMode,
    exportLimit: transaction.exportLimit,
    gridMaxDischarge: transaction.gridMaxDischarge,
    exportHelperOn: transaction.exportHelperOn,
    pvChargeOn: transaction.pvChargeOn,
    forceChargeOn: transaction.forceChargeOn,
    forceDischargeOn: transaction.forceDischargeOn,
    physicalChargeOn: transaction.forceChargeOn,
    physicalDischargeOn: transaction.forceDischargeOn,
    chargePowerPercent: transaction.chargePowerPercent,
    dischargePowerPercent: transaction.dischargePowerPercent,
    pvChargePowerLimit: transaction.pvChargePowerLimit,
    ...overrides,
  };
}

test("schema-v2 implements all five explicit modes as complete transactions", () => {
  assert.deepEqual(BATTERY_MODES, ["hold", "self_consume", "pv_charge", "grid_charge", "export"]);
  const results = Object.fromEntries(BATTERY_MODES.map((mode) => [mode, validatePlan(input(mode))]));
  for (const [mode, result] of Object.entries(results)) {
    assert.equal(result.accepted, true, mode);
    assert.equal(result.transaction.batteryMode, mode);
    assert.equal(result.transaction.reservePct, 7);
    assert.equal(result.transaction.antiRefluxMode, 0);
    assert.equal(result.transaction.exportLimit, 1100);
    assert.equal(result.transaction.gridMaxDischarge, 1100);
  }
  assert.equal(results.hold.transaction.pvChargeOn, true);
  assert.equal(results.hold.transaction.pvChargePowerLimit, 1000);
  assert.equal(results.hold.transaction.batteryDischargeLimit, 1000);
  assert.equal(results.hold.transaction.forceChargeOn, false);
  assert.equal(results.hold.transaction.forceDischargeOn, false);
  assert.equal(results.self_consume.transaction.pvChargeOn, true);
  assert.equal(results.self_consume.transaction.pvChargePowerLimit, 1000);
  assert.equal(results.self_consume.transaction.batteryDischargeLimit, 1000);
  assert.equal(results.pv_charge.transaction.chargeRateKw, 20);
  assert.equal(results.pv_charge.transaction.pvChargePowerLimit, 1000);
  assert.equal(results.pv_charge.transaction.batteryDischargeLimit, 1000);
  assert.equal(results.pv_charge.transaction.chargePowerPercent, 0);
  assert.equal(results.grid_charge.transaction.forceChargeOn, true);
  assert.equal(results.grid_charge.transaction.chargePowerPercent, 100);
  assert.equal(results.grid_charge.transaction.batteryDischargeLimit, 1000);
  assert.equal(results.export.transaction.forceDischargeOn, true);
  assert.equal(results.export.transaction.dischargePowerPercent, 70);
  assert.equal(results.export.transaction.pvChargePowerLimit, 1000);
  assert.equal(results.export.transaction.batteryDischargeLimit, 1000);
});

test("direct SAJ rate mappings match the established 30kW and PV-limit scales", () => {
  assert.equal(forcePowerPercent(0), 0);
  assert.equal(forcePowerPercent(21), 70);
  assert.equal(forcePowerPercent(28), 93);
  assert.equal(forcePowerPercent(30), 100);
  assert.equal(pvChargePowerLimitForKw(0), 0);
  assert.equal(pvChargePowerLimitForKw(1), 0);
  assert.equal(pvChargePowerLimitForKw(20), 700);
  assert.equal(pvChargePowerLimitForKw(30), 1000);
});

test("independent discharge-limit percent is normalized to writable register units", () => {
  assert.equal(batteryDischargeLimitSensorToRegister("100.0", "%"), 1000);
  assert.equal(batteryDischargeLimitSensorToRegister("0", "%"), 0);
  assert.equal(batteryDischargeLimitSensorToRegister("110", "%"), 1100);
  assert.equal(batteryDischargeLimitSensorToRegister("110.1", "%"), null);
  assert.equal(batteryDischargeLimitSensorToRegister("-0.1", "%"), null);
  assert.equal(batteryDischargeLimitSensorToRegister("100", ""), null);
  assert.equal(batteryDischargeLimitSensorToRegister("1000", null), null);
  assert.equal(batteryDischargeLimitSensorToRegister("unavailable", "%"), null);
});

test("site export target is translated once against live PV/load and applied immediately at full rate", () => {
  const result = validatePlan(input("export"));
  assert.equal(result.transaction.targetKw, 21); // 30 site + 3 load - 12 PV
  assert.equal(result.transaction.dischargeRateKw, 21);

  const capped = input("export", {pvPowerKw: 1, homeLoadKw: 5, maxDischargeCapKw: 12});
  mutatePlan(capped, {site_export_target_kw: 50});
  assert.equal(validatePlan(capped).transaction.targetKw, 12);

  const pvMeetsTarget = input("export", {pvPowerKw: 40, homeLoadKw: 2});
  const met = validatePlan(pvMeetsTarget);
  assert.equal(met.accepted, true);
  assert.equal(met.transaction.targetKw, 0);
  assert.equal(met.transaction.forceDischargeOn, false);
  assert.equal(met.status, "accepted_export_pv_meets_site_target");
});

test("legacy schema, unknown modes, missing build identity and replayed revisions fail safe", () => {
  const legacy = input();
  mutatePlan(legacy, {schema_version: 1});
  assert.equal(validatePlan(legacy).status, "rejected_schema_v2");

  const unknown = input();
  mutatePlan(unknown, {battery_mode: "idle"});
  assert.equal(validatePlan(unknown).status, "rejected_battery_mode");

  const noFingerprint = input();
  mutatePlan(noFingerprint, {config_fingerprint: ""});
  assert.equal(validatePlan(noFingerprint).status, "rejected_schema_v2");

  const replay = input("export", {
    lastAcceptedGeneratedAtMs: NOW - 10_000,
    lastAcceptedPlanId: "newer",
  });
  assert.equal(validatePlan(replay).status, "rejected_plan_revision");
});

test("exact non-actuating null-price hold is an immediate reserve-preserving safe-stop", () => {
  const rollover = input("hold", {reserveNumberPct: 40, reserveSensorPct: 40, soc: 50});
  mutatePlan(rollover, {
    actuation_allowed: false,
    protected_soc_pct: 39.9,
    live_fit_price: null,
    live_import_price: null,
    price_interval_start: null,
    price_interval_end: null,
  });
  const result = validatePlan(rollover);
  assert.equal(result.accepted, false);
  assert.equal(result.status, "safe_hold_non_actuating");
  assert.equal(result.transaction.safeStop, true);
  assert.equal(result.transaction.batteryMode, "safe_stop");
  assert.equal(result.transaction.reservePct, 40);
  assert.equal(result.transaction.batteryDischargeLimit, 1000);
  assert.equal(result.transaction.forceChargeOn, false);
  assert.equal(result.transaction.forceDischargeOn, false);

  mutatePlan(rollover, {battery_discharge_target_kw: 1});
  assert.equal(validatePlan(rollover).status, "rejected_schema_v2");
});

test("signed and component targets must agree with each explicit mode", () => {
  const cases = [
    ["export", {battery_power_target_kw: -10}, "rejected_target_sign"],
    ["export", {battery_power_target_kw: 20, battery_discharge_target_kw: 18}, "rejected_target_components"],
    ["grid_charge", {battery_power_target_kw: 10}, "rejected_target_sign"],
    ["pv_charge", {battery_discharge_target_kw: 1}, "rejected_target_sign"],
    ["hold", {battery_power_target_kw: 1}, "rejected_target_sign"],
    ["self_consume", {battery_charge_target_kw: 1}, "rejected_target_sign"],
  ];
  for (const [mode, attributes, expected] of cases) {
    const value = input(mode);
    mutatePlan(value, attributes);
    assert.equal(validatePlan(value).status, expected, mode);
  }

  const selfSupply = input("self_consume");
  mutatePlan(selfSupply, {battery_power_target_kw: 4, battery_discharge_target_kw: 4});
  const accepted = validatePlan(selfSupply);
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.transaction.forceDischargeOn, false);
  assert.equal(accepted.transaction.plannedBatteryTargetKw, 4);
});

test("reserve writer and independent physical sensor are mandatory", () => {
  for (const overrides of [
    {reserveControlAvailable: false},
    {reserveNumberPct: "unavailable"},
    {reserveSensorPct: "unknown"},
  ]) {
    const result = validatePlan(input("hold", overrides));
    assert.equal(result.accepted, false);
    assert.equal(result.status, "rejected_reserve_control_unavailable");
    assert.equal(result.transaction.forceChargeOn, false);
    assert.equal(result.transaction.forceDischargeOn, false);
  }
});

test("battery discharge-limit writer and independent physical sensor are mandatory", () => {
  for (const overrides of [
    {batteryDischargeLimitControlAvailable: false},
    {batteryDischargeLimitNumber: "unavailable"},
    {batteryDischargeLimitSensor: "unknown"},
    {batteryDischargeLimitSensorMeasuredAtMs: null},
    {batteryDischargeLimitNumber: 1101},
    {batteryDischargeLimitSensor: -1},
  ]) {
    const result = validatePlan(input("hold", overrides));
    assert.equal(result.accepted, false);
    assert.equal(result.status, "rejected_battery_discharge_limit_unavailable");
    assert.equal(result.transaction.forceChargeOn, false);
    assert.equal(result.transaction.forceDischargeOn, false);
    // Rejection restores fail-safe normal self-consumption; it must not leave a
    // preceding hold's zero-discharge latch behind indefinitely.
    assert.equal(result.transaction.batteryDischargeLimit, 1000);
  }
});

test("manual override stops force modes while preserving an already stricter floor", () => {
  const result = validatePlan(input("export", {manualOverride: "on", minSocPct: 18, reserveSensorPct: 18}));
  assert.equal(result.status, "manual_override");
  assert.equal(result.transaction.safeStop, true);
  assert.equal(result.transaction.reservePct, 18);
  assert.equal(result.transaction.pvChargeOn, true);
  assert.equal(result.transaction.chargePowerPercent, 0);
  assert.equal(result.transaction.dischargePowerPercent, 0);
  assert.equal(result.transaction.pvChargePowerLimit, 1000);
  assert.equal(result.transaction.batteryDischargeLimit, 1000);
});

test("every disarm and rejection preserves the prior protected reserve", () => {
  for (const overrides of [
    {mode: "Shadow"},
    {rolloutApproved: "off"},
    {batteryControl: "off"},
    {nowMs: Date.parse("2026-08-18T02:10:00Z")},
  ]) {
    const result = validatePlan(input("export", overrides));
    assert.equal(result.accepted, false);
    assert.equal(result.transaction.safeStop, true);
    assert.equal(result.transaction.reservePct, 7);
    assert.equal(result.transaction.forceChargeOn, false);
    assert.equal(result.transaction.forceDischargeOn, false);
    assert.equal(result.transaction.chargePowerPercent, 0);
    assert.equal(result.transaction.dischargePowerPercent, 0);
    assert.equal(result.transaction.batteryDischargeLimit, 1000);
  }
});

test("rejected rollover preserves live reserve and stale protection cannot exceed live SOC", () => {
  const rollover = input("hold", {
    soc: 40.2,
    reserveNumberPct: 40,
    reserveSensorPct: 40,
  });
  mutatePlan(rollover, {
    protected_soc_pct: 39.9,
    price_interval_start: null,
    price_interval_end: null,
  });
  const result = validatePlan(rollover);
  assert.equal(result.accepted, false);
  assert.equal(result.status, "rejected_schema_v2");
  assert.equal(result.transaction.safeStop, true);
  assert.equal(result.transaction.priorReservePct, 40);
  assert.equal(result.transaction.reservePct, 40);

  const staleHigh = input("export", {soc: 39.2, reserveNumberPct: 5, reserveSensorPct: 5});
  mutatePlan(staleHigh, {protected_soc_pct: 99, price_interval_start: null});
  const capped = validatePlan(staleHigh);
  assert.equal(capped.accepted, false);
  assert.equal(capped.transaction.reservePct, 39);
  assert.ok(capped.transaction.reservePct <= staleHigh.soc);

  const alreadyHigher = input("export", {soc: 39.2, reserveNumberPct: 60, reserveSensorPct: 60});
  mutatePlan(alreadyHigher, {protected_soc_pct: 99, price_interval_start: null});
  assert.equal(validatePlan(alreadyHigher).transaction.reservePct, 60);

  const noLiveSoc = input("export", {soc: "unavailable", reserveNumberPct: 5, reserveSensorPct: 5});
  mutatePlan(noLiveSoc, {protected_soc_pct: 99, price_interval_start: null});
  assert.equal(validatePlan(noLiveSoc).transaction.reservePct, 5);
});

test("negative live FIT always produces inverter-native exact zero export", () => {
  const contradictory = input("export", {liveFitPrice: -0.04});
  mutatePlan(contradictory, {live_fit_price: -0.04});
  const rejected = validatePlan(contradictory);
  assert.equal(rejected.status, "rejected_negative_fit_requires_curtail");
  assert.equal(rejected.transaction.pvExportCommand, "curtail");
  assert.equal(rejected.transaction.antiRefluxMode, 1);
  assert.equal(rejected.transaction.exportLimit, 0);
  assert.equal(rejected.transaction.gridMaxDischarge, 1100);

  const charge = input("pv_charge", {liveFitPrice: -0.04});
  mutatePlan(charge, {live_fit_price: -0.04, pv_export_command: "curtail"});
  const accepted = validatePlan(charge);
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.transaction.antiRefluxMode, 1);
  assert.equal(accepted.transaction.exportLimit, 0);
  assert.equal(accepted.transaction.pvChargeOn, true);
  assert.equal(accepted.transaction.chargeRateKw, 20);
  assert.equal(accepted.transaction.pvChargePowerLimit, 1000);
});

test("stale or unknown live FIT never forces zero export", () => {
  const daylight = input("self_consume", {liveFitPrice: "unavailable", liveFitMeasuredAtMs: null});
  const stopped = validatePlan(daylight);
  assert.equal(stopped.status, "rejected_live_fit_stale");
  assert.equal(stopped.transaction.pvExportCommand, "allow");

  const night = input("self_consume", {
    liveFitPrice: "unavailable",
    liveFitMeasuredAtMs: null,
    sunState: "below_horizon",
    pvPowerKw: 0,
  });
  const accepted = validatePlan(night);
  assert.equal(accepted.accepted, true);
  assert.equal(accepted.transaction.pvExportCommand, "allow");

  assert.equal(conservativeCurtail(daylight, NOW), false);
  assert.equal(conservativeCurtail(night, NOW), false);
});

test("battery export is rejected below the dashboard minimum sell price", () => {
  const below = input("export", {liveFitPrice: 0.119});
  mutatePlan(below, {live_fit_price: 0.119});
  assert.equal(validatePlan(below).status, "rejected_below_minimum_sell_price");

  const atFloor = input("export", {liveFitPrice: 0.12});
  mutatePlan(atFloor, {live_fit_price: 0.12});
  assert.equal(validatePlan(atFloor).accepted, true);
});

test("price-sensitive plans require the current interval and reject adverse price drift", () => {
  const oldWindow = input("export");
  mutatePlan(oldWindow, {price_interval_end: "2026-08-18T02:00:00Z"});
  assert.equal(validatePlan(oldWindow).status, "rejected_price_interval");

  const lower = input("export", {liveFitPrice: 0.20});
  assert.equal(validatePlan(lower).status, "rejected_live_fit_mismatch");

  const higher = input("export", {liveFitPrice: 0.60});
  assert.equal(validatePlan(higher).accepted, true);

  const changedChargePrice = input("grid_charge", {liveFitPrice: 0.60});
  assert.equal(validatePlan(changedChargePrice).status, "rejected_live_fit_mismatch");

  const higherImport = input("grid_charge", {liveImportPrice: 0.50});
  assert.equal(validatePlan(higherImport).status, "rejected_live_import_mismatch");
  const lowerImport = input("grid_charge", {liveImportPrice: 0.20});
  assert.equal(validatePlan(lowerImport).accepted, true);
});

test("plan source heartbeats and separate live telemetry heartbeats are bounded", () => {
  const staleSource = input();
  mutatePlan(staleSource, {source_timestamps: {
    ...staleSource.planEntity.attributes.source_timestamps,
    pv_heartbeat: "2026-08-18T01:54:29.999Z",
  }});
  assert.equal(validatePlan(staleSource).status, "rejected_source_stale_pv_heartbeat");

  const missingSource = input();
  const source = {...missingSource.planEntity.attributes.source_timestamps};
  delete source.amber_fit;
  mutatePlan(missingSource, {source_timestamps: source});
  assert.equal(validatePlan(missingSource).status, "rejected_source_timestamp_amber_fit");

  for (const key of ["socHeartbeatMeasuredAtMs", "pvMeasuredAtMs", "homeLoadMeasuredAtMs"]) {
    assert.equal(validatePlan(input("export", {[key]: NOW - 330_001})).status, "rejected_live_telemetry_stale", key);
  }
});

test("bounds retain verified 28kW discharge, 30kW charge and protected SOC", () => {
  const exportTooLarge = input("export");
  mutatePlan(exportTooLarge, {battery_power_target_kw: 28.1, battery_discharge_target_kw: 28.1});
  assert.equal(validatePlan(exportTooLarge).status, "rejected_bounds");

  const charge = validatePlan(input("grid_charge"));
  assert.equal(charge.transaction.targetKw, 30);

  const belowProtection = input("export", {soc: 7.9});
  assert.equal(validatePlan(belowProtection).status, "rejected_export_guard");

  const lowerThanLiveFloor = input("self_consume", {minSocPct: 15});
  const transition = validatePlan(lowerThanLiveFloor);
  assert.equal(transition.accepted, true);
  assert.equal(transition.transaction.reservePct, 7);
});

test("all active modes ceil decimal protection to the whole-percent SAJ reserve", () => {
  for (const mode of ["self_consume", "pv_charge", "grid_charge", "export"]) {
    const value = input(mode);
    mutatePlan(value, {protected_soc_pct: 39.7});
    const result = validatePlan(value);
    assert.equal(result.accepted, true, mode);
    assert.equal(result.transaction.protectedSocPct, 39.7, mode);
    assert.equal(result.transaction.reservePct, 40, mode);
  }
});

test("register verification covers every SAJ register and helper in the transaction", () => {
  const transaction = validatePlan(input("export")).transaction;
  assert.deepEqual(verifyRegisterState(transaction, expectedActual(transaction)), {
    ok: true,
    mismatches: [],
    expected: expectedActual(transaction),
  });
  const mismatch = verifyRegisterState(transaction, expectedActual(transaction, {
    reserveSensorPct: 5,
    antiRefluxMode: 1,
    forceChargeOn: true,
    physicalChargeOn: true,
    physicalDischargeOn: false,
    chargePowerPercent: 10,
    dischargePowerPercent: 69,
    pvChargePowerLimit: 100,
    batteryDischargeLimitSensor: 900,
  }));
  assert.equal(mismatch.ok, false);
  assert.deepEqual(mismatch.mismatches.sort(), [
    "antiRefluxMode",
    "batteryDischargeLimitSensor",
    "chargePowerPercent",
    "dischargePowerPercent",
    "forceChargeOn",
    "physicalChargeOn",
    "physicalDischargeOn",
    "pvChargePowerLimit",
    "reserveSensorPct",
  ]);
  assert.equal(binaryOn("on"), true);
  assert.equal(binaryOn("off"), false);
  assert.equal(binaryOn("unavailable"), null);
  assert.deepEqual(
    verifyRegisterState(transaction, expectedActual(transaction, {physicalDischargeOn: null})).mismatches,
    ["physicalDischargeOn"],
  );
});

test("reserve change detection compares the independent pre-command value with the target", () => {
  assert.equal(reserveTargetChanged({priorReservePct: 7, reservePct: 7}), false);
  assert.equal(reserveTargetChanged({priorReservePct: 7, reservePct: 7.5}), false);
  assert.equal(reserveTargetChanged({priorReservePct: 5, reservePct: 7}), true);
  assert.equal(reserveTargetChanged({priorReservePct: null, reservePct: 7}), true);
});

test("battery discharge-limit change detection compares independent pre-command state", () => {
  assert.equal(batteryDischargeLimitTargetChanged({priorBatteryDischargeLimit: 1000, batteryDischargeLimit: 1000}), false);
  assert.equal(batteryDischargeLimitTargetChanged({priorBatteryDischargeLimit: 1000, batteryDischargeLimit: 0}), true);
  assert.equal(batteryDischargeLimitTargetChanged({priorBatteryDischargeLimit: null, batteryDischargeLimit: 0}), true);
});

test("a value-static reserve timestamp stays usable at preflight", () => {
  const unchanged = input("self_consume", {
    reserveNumberPct: 7,
    reserveSensorPct: 7,
    reserveSensorMeasuredAtMs: NOW - 24 * 60 * 60 * 1000,
  });
  const unchangedResult = validatePlan(unchanged);
  assert.equal(unchangedResult.accepted, true);
  assert.equal(reserveTargetChanged(unchangedResult.transaction), false);

  const changed = input("self_consume", {
    reserveNumberPct: 5,
    reserveSensorPct: 5,
    reserveSensorMeasuredAtMs: NOW - 24 * 60 * 60 * 1000,
  });
  const changedResult = validatePlan(changed);
  assert.equal(changedResult.accepted, true);
  assert.equal(reserveTargetChanged(changedResult.transaction), true);
});

test("early feedback requires a fresh post-command physical direction", () => {
  const exportTx = {...validatePlan(input("export")).transaction, issuedAtMs: NOW - 15_000};
  const accepted = evaluateDirectionFeedback(exportTx, {
    batteryKw: 3.2,
    batteryMeasuredAtMs: NOW - 5_000,
    nowMs: NOW,
  });
  assert.equal(accepted.ok, true);

  assert.equal(evaluateDirectionFeedback(exportTx, {
    batteryKw: -3,
    batteryMeasuredAtMs: NOW - 5_000,
    nowMs: NOW,
  }).status, "feedback_direction_wrong_export");

  const chargeTx = {...validatePlan(input("grid_charge")).transaction, issuedAtMs: NOW - 15_000};
  assert.equal(evaluateDirectionFeedback(chargeTx, {
    batteryKw: -4,
    batteryMeasuredAtMs: NOW - 5_000,
    nowMs: NOW,
  }).ok, true);
  assert.equal(evaluateDirectionFeedback(chargeTx, {
    batteryKw: -4,
    batteryMeasuredAtMs: NOW - 16_000,
    nowMs: NOW,
  }).status, "feedback_direction_precommand");
  assert.equal(evaluateDirectionFeedback({...exportTx, writeStrategy: "no_write"}, {
    batteryKw: 4,
    batteryMeasuredAtMs: NOW - 16_000,
    nowMs: NOW,
  }).ok, true);
});

test("settled target feedback uses site export, max(1kW,10%) and recognises physical clipping", () => {
  assert.equal(feedbackTolerance(5), 1);
  assert.ok(Math.abs(feedbackTolerance(28) - 2.8) < 1e-9);
  const tx = {...validatePlan(input("export")).transaction, targetKw: 20, siteExportTargetKw: 18, issuedAtMs: NOW - 30_000};
  const base = {batteryMeasuredAtMs: NOW - 2_000, nowMs: NOW, soc: 50};
  assert.equal(evaluateTargetFeedback(tx, {...base, batteryKw: 20, gridKw: -16.3, gridMeasuredAtMs: NOW - 2_000}).ok, true);
  const mismatch = evaluateTargetFeedback(tx, {...base, batteryKw: 20, gridKw: -16.1, gridMeasuredAtMs: NOW - 2_000});
  assert.equal(mismatch.ok, true);
  assert.equal(mismatch.status, "confirmed_export_rate_site_deviation");
  assert.equal(mismatch.toleranceKw, 1.8);
  assert.equal(evaluateTargetFeedback(tx, {...base, batteryKw: 20}).status, "feedback_target_grid_unavailable");
  assert.equal(evaluateTargetFeedback(tx, {...base, batteryKw: 20, gridKw: -18, gridMeasuredAtMs: NOW - 31_000}).status, "feedback_target_grid_stale");

  const held = {...tx, reason: "accepted_export_rate_held_60s"};
  assert.equal(evaluateTargetFeedback(held, {...base, batteryKw: 20, gridKw: -30, gridMeasuredAtMs: NOW - 2_000}).status, "confirmed_export_rate_held");
  const heldNoWrite = {...held, writeStrategy: "no_write"};
  assert.equal(evaluateTargetFeedback(heldNoWrite, {
    ...base,
    batteryMeasuredAtMs: NOW - 31_000,
    batteryKw: 20,
    gridKw: -18,
    gridMeasuredAtMs: NOW - 31_000,
  }).status, "confirmed_export_rate_held");

  assert.equal(evaluateTargetFeedback(tx, {...base, soc: 7.5, batteryKw: 0, gridKw: 0, gridMeasuredAtMs: NOW - 2_000}).status, "confirmed_target_clipped_floor");
  const grid = {...validatePlan(input("grid_charge")).transaction, issuedAtMs: NOW - 30_000};
  assert.equal(evaluateTargetFeedback(grid, {...base, soc: 99, batteryKw: 0}).status, "confirmed_target_clipped_upper_soc");

  const pv = {...validatePlan(input("pv_charge")).transaction, issuedAtMs: NOW - 30_000};
  assert.equal(evaluateTargetFeedback(pv, {...base, batteryKw: -8, pvKw: 11, loadKw: 3}).ok, true);
  const strongerThanForecast = evaluateTargetFeedback(
    pv,
    {...base, batteryKw: -14.5, pvKw: 15.7, loadKw: 1.2},
  );
  assert.equal(strongerThanForecast.ok, true);
  assert.equal(strongerThanForecast.expectedKw, 14.5);
  assert.equal(evaluateTargetFeedback(pv, {...base, batteryKw: 0, pvKw: 2, loadKw: 3}).status, "confirmed_target_clipped_solar");
  assert.equal(evaluateTargetFeedback(pv, {...base, soc: 99, batteryKw: 0, pvKw: 15, loadKw: 1}).status, "confirmed_target_clipped_upper_soc");
});

test("every status phase keeps the committed plan id in the second field", () => {
  const tx = validatePlan(input("export")).transaction;
  const phases = {
    requested: "requested",
    applied: "applied",
    confirmed_direction: "confirmed_direction",
    confirmed: "feedback_confirmed",
    failed: "failed",
  };
  for (const [phase, prefix] of Object.entries(phases)) {
    assert.match(statusText(phase, tx), new RegExp(`^${prefix} \\| ${tx.planId} \\|`));
  }
  const literal = statusText("confirmed", {...tx, planId: "plan|unsafe\"", reason: "a=b"}, "detail=x=y");
  assert.match(literal, /^feedback_confirmed \| plan\/unsafe_ \|/);
  assert.match(literal, /reason=a=b/);
  assert.match(literal, /detail=x=y/);
  assert.doesNotMatch(literal, /&#x3D;/);
  assert.ok(statusText("failed", {...tx, reason: "x".repeat(500)}).length <= 250);
});

test("checked-in flow is exactly generated from guard.js sources", () => {
  assert.deepEqual(flowJson, buildFlow());
  const mapping = {
    eop_read_live_state_002: "readLiveState",
    eop_validate_002: "validateAndRequest",
    eop_arm_deadline_002: "armDeadline",
    eop_plan_deadline_expired_002: "expiry",
    eop_write_strategy_route_002: "writeStrategyRoute",
    eop_semantic_confirmed_002: "semanticConfirmed",
    eop_pre_force_check_002: "preForceCheck",
    eop_reserve_route_002: "reserveRoute",
    eop_export_route_002: "exportRoute",
    eop_pv_route_002: "pvRoute",
    eop_forced_route_002: "forcedRoute",
    eop_apply_queue_002: "applyQueue",
    eop_applied_002: "applied",
    eop_feedback_confirm_002: "earlyFeedback",
    eop_target_confirm_002: "targetFeedback",
    eop_service_failure_002: "serviceFailure",
  };
  for (const [id, key] of Object.entries(mapping)) assert.equal(flowNode(id).func, nodeSources[key], id);
});

test("all embedded Node-RED functions compile", () => {
  for (const node of flowJson.filter((candidate) => candidate.type === "function")) {
    assert.doesNotThrow(() => new Function("msg", "flow", "global", node.func), node.name);
  }
});

test("direct Amber edge actuates only signed-negative FIT", () => {
  const trigger = flowNode("eop_price_changed_002");
  assert.deepEqual(trigger.entities.entity, [
    "sensor.amber_express_trader_sheena_street_feed_in_price",
  ]);
  assert.deepEqual(trigger.wires, [["eop_negative_fit_edge_002"]]);
  const run = new Function("msg", "flow", "global", flowNode("eop_negative_fit_edge_002").func);
  assert.deepEqual(run({payload: "-0.01"}, {}, {}), {payload: "-0.01"});
  assert.equal(run({payload: "0"}, {}, {}), null);
  assert.equal(run({payload: "1.50"}, {}, {}), null);
  assert.equal(run({payload: "unavailable"}, {}, {}), null);
});

test("embedded validator is parity-equivalent and emits requested before immediate apply", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const value = input("export");
  const pure = validatePlan(value);
  const state = context();
  const outputs = run(structuredClone(value), state.flow, {});
  assert.match(outputs[0].payload, /^requested \| plan-export \|/);
  assert.deepEqual(outputs[2].transaction, {...pure.transaction, revision: 1, issuedAtMs: NOW});
  assert.equal(outputs[2].transaction.targetKw, 21);
  assert.equal(state.values.get("energyOptimizerCurrentTransaction").planId, "plan-export");
  assert.equal(state.values.get("energyOptimizerLastAcceptedPlanId"), "plan-export");
});

test("watchdog leaves an identical physically confirmed plan and readiness status untouched", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const current = {
    ...validatePlan(input("export")).transaction,
    revision: 5,
    issuedAtMs: NOW - 40_000,
    appliedAtMs: NOW - 39_000,
  };
  const state = context({
    energyOptimizerRevision: 5,
    energyOptimizerCurrentTransaction: current,
    energyOptimizerLastRegisterConfirmedTransaction: current,
    energyOptimizerLastAppliedTransaction: current,
    energyOptimizerLastAcceptedGeneratedAtMs: current.generatedAtMs,
    energyOptimizerLastAcceptedPlanId: current.planId,
  });
  const result = run({
    ...input("export"),
    topic: "watchdog",
    watchdogActual: expectedActual(current),
  }, state.flow, {});
  assert.deepEqual(result, [null, null, null]);
  assert.equal(state.values.get("energyOptimizerRevision"), 5);
  assert.equal(state.values.get("energyOptimizerCurrentTransaction"), current);
});

test("watchdog reasserts only real physical drift in the confirmed current plan", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const current = {
    ...validatePlan(input("export")).transaction,
    revision: 8,
    issuedAtMs: NOW - 40_000,
  };
  const state = context({
    energyOptimizerRevision: 8,
    energyOptimizerCurrentTransaction: current,
    energyOptimizerLastRegisterConfirmedTransaction: current,
    energyOptimizerLastAppliedTransaction: current,
    energyOptimizerLastAcceptedGeneratedAtMs: current.generatedAtMs,
    energyOptimizerLastAcceptedPlanId: current.planId,
  });
  const result = run({
    ...input("export"),
    topic: "watchdog",
    watchdogActual: expectedActual(current, {physicalDischargeOn: false}),
  }, state.flow, {});
  assert.match(result[0].payload, /^requested \| plan-export \|/);
  assert.match(result[0].payload, /watchdog_physical_drift/);
  assert.equal(result[2].transaction.revision, 9);
  assert.equal(result[2].transaction.writeStrategy, "full");
  assert.match(result[2].transaction.reason, /physicalDischargeOn/);
  assert.equal(result[2].transaction.forceDischargeOn, true);
});

test("watchdog still safe-stops an expired plan and accepts a genuinely newer commit", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const current = {
    ...validatePlan(input("export")).transaction,
    revision: 12,
    issuedAtMs: NOW - 40_000,
  };
  const initial = {
    energyOptimizerRevision: 12,
    energyOptimizerCurrentTransaction: current,
    energyOptimizerLastRegisterConfirmedTransaction: current,
    energyOptimizerLastAppliedTransaction: current,
    energyOptimizerLastAcceptedGeneratedAtMs: current.generatedAtMs,
    energyOptimizerLastAcceptedPlanId: current.planId,
  };
  const expiredInput = input("export");
  expiredInput.topic = "watchdog";
  expiredInput.watchdogActual = expectedActual(current);
  mutatePlan(expiredInput, {valid_until: "2026-08-18T01:59:59Z"});
  const expiredState = context(initial);
  const expired = run(expiredInput, expiredState.flow, {});
  assert.equal(expired[2].transaction.batteryMode, "safe_stop");
  assert.equal(expired[2].transaction.safeStop, true);
  assert.equal(expired[2].transaction.reason, "rejected_stale_plan");

  const newerInput = input("export");
  newerInput.topic = "watchdog";
  newerInput.watchdogActual = expectedActual(current);
  mutatePlan(newerInput, {
    plan_id: "plan-export-newer",
    generated_at: "2026-08-18T01:59:40Z",
  });
  const newerState = context(initial);
  const newer = run(newerInput, newerState.flow, {});
  assert.equal(newer[2].transaction.planId, "plan-export-newer");
  assert.equal(newer[2].transaction.batteryMode, "export");
  assert.equal(newer[2].transaction.revision, 13);
  assert.doesNotMatch(newer[2].transaction.reason, /watchdog_drift/);
});

test("confirmed same-mode export target changes select exactly the one-register fast path", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const desired = validatePlan(input("export")).transaction;
  const previous = {
    ...desired,
    revision: 7,
    targetKw: 18,
    siteExportTargetKw: 27,
    dischargeRateKw: 18,
    dischargePowerPercent: 60,
  };
  assert.equal(exportRateOnlyEligible({...desired, revision: 8}, previous, previous, null), true);
  assert.equal(exportRateOnlyEligible({...desired, revision: 8, reservePct: 8}, previous, previous, null), false);

  const state = context({
    energyOptimizerRevision: 7,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const outputs = run(structuredClone(input("export")), state.flow, {});
  assert.equal(outputs[2].transaction.revision, 8);
  assert.equal(outputs[2].transaction.writeStrategy, "export_rate_only");
  const fast = flowNode("eop_fast_set_discharge_percent_002");
  assert.equal(fast.action, "number.set_value");
  assert.deepEqual(fast.entityId, ["number.saj_discharge1_power_percent_input"]);
  assert.equal(fast.data, "{\"value\":{{transaction.dischargePowerPercent}}}");
  assert.deepEqual(fast.wires, [["eop_applied_002"]]);

  const changed = input("export");
  mutatePlan(changed, {protected_soc_pct: 8});
  const changedOutputs = run(changed, state.flow, {});
  assert.equal(changedOutputs[2].transaction.writeStrategy, "full");
});

test("same-interval export corrections and restarts are held for 60 seconds but Amber rollover is immediate", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_validate_002").func);
  const desired = validatePlan(input("export")).transaction;
  const previous = {
    ...desired,
    planId: "plan-export-previous",
    revision: 7,
    issuedAtMs: NOW - 30_000,
    appliedAtMs: NOW - 30_000,
    exportRateChangedAtMs: NOW - 30_000,
    targetKw: 18,
    siteExportTargetKw: 27,
    dischargeRateKw: 18,
    dischargePowerPercent: 60,
  };
  const state = context({
    energyOptimizerRevision: 7,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const changed = input("export");
  mutatePlan(changed, {site_export_target_kw: 35});

  const held = run(changed, state.flow, {});
  assert.equal(held[2].transaction.targetKw, 18);
  assert.equal(held[2].transaction.dischargePowerPercent, 60);
  assert.equal(held[2].transaction.siteExportTargetKw, previous.siteExportTargetKw);
  assert.equal(held[2].transaction.deferredTargetKw, 26);
  assert.equal(held[2].transaction.reason, "accepted_export_rate_held_60s");
  assert.equal(held[2].transaction.writeStrategy, "no_write");

  const elapsedState = context({
    energyOptimizerRevision: 8,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const elapsed = run({...changed, nowMs: NOW + 61_000}, elapsedState.flow, {});
  assert.equal(elapsed[2].transaction.targetKw, 26);

  const smallCorrection = input("export");
  mutatePlan(smallCorrection, {site_export_target_kw: previous.siteExportTargetKw + 0.5});
  const deadband = run({...smallCorrection, nowMs: NOW + 61_000}, context({
    energyOptimizerRevision: 8,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  }).flow, {});
  assert.equal(deadband[2].transaction.targetKw, 18);
  assert.equal(deadband[2].transaction.reason, "accepted_export_rate_held_60s_deadband");
  assert.equal(deadband[2].transaction.writeStrategy, "no_write");

  const stopped = {
    ...validatePlan(input("self_consume")).transaction,
    planId: "plan-stopped-previous",
    revision: 9,
    issuedAtMs: NOW - 30_000,
    appliedAtMs: NOW - 30_000,
    exportRateChangedAtMs: NOW - 30_000,
  };
  const restartState = context({
    energyOptimizerRevision: 9,
    energyOptimizerLastRegisterConfirmedTransaction: stopped,
    energyOptimizerLastAppliedTransaction: stopped,
  });
  const heldRestart = run(changed, restartState.flow, {});
  assert.equal(heldRestart[2].transaction.batteryMode, "self_consume");
  assert.equal(heldRestart[2].transaction.targetKw, 0);
  assert.equal(heldRestart[2].transaction.deferredTargetKw, 26);
  assert.equal(heldRestart[2].transaction.reason, "accepted_export_start_held_60s");

  const stopInput = input("self_consume");
  const stopState = context({
    energyOptimizerRevision: 11,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const heldStop = run(stopInput, stopState.flow, {});
  assert.equal(heldStop[2].transaction.batteryMode, "export");
  assert.equal(heldStop[2].transaction.targetKw, 18);
  assert.equal(heldStop[2].transaction.dischargePowerPercent, 60);
  assert.equal(heldStop[2].transaction.deferredTargetKw, 0);
  assert.equal(heldStop[2].transaction.reason, "accepted_export_stop_held_60s");
  assert.equal(heldStop[2].transaction.writeStrategy, "no_write");

  const negativeStop = input("self_consume");
  negativeStop.liveFitPrice = -0.01;
  negativeStop.nowMs = NOW;
  const immediateNegativeStop = run(negativeStop, context({
    energyOptimizerRevision: 12,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  }).flow, {});
  assert.notEqual(immediateNegativeStop[2].transaction.batteryMode, "export");
  assert.equal(immediateNegativeStop[2].transaction.pvExportCommand, "curtail");

  const elapsedRestartState = context({
    energyOptimizerRevision: 10,
    energyOptimizerLastRegisterConfirmedTransaction: stopped,
    energyOptimizerLastAppliedTransaction: stopped,
  });
  const elapsedRestart = run({...changed, nowMs: NOW + 61_000}, elapsedRestartState.flow, {});
  assert.equal(elapsedRestart[2].transaction.batteryMode, "export");
  assert.equal(elapsedRestart[2].transaction.targetKw, 26);

  const rolloverState = context({
    energyOptimizerRevision: 8,
    energyOptimizerLastRegisterConfirmedTransaction: previous,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const rollover = structuredClone(changed);
  mutatePlan(rollover, {
    price_interval_start: "2026-08-18T02:00:00Z",
    price_interval_end: "2026-08-18T02:05:00Z",
  });
  const immediate = run(rollover, rolloverState.flow, {});
  assert.equal(immediate[2].transaction.targetKw, 26);
  assert.equal(immediate[2].transaction.writeStrategy, "full");
  assert.notEqual(immediate[2].transaction.reason, "accepted_export_rate_held_60s");
});

test("applying an export stop records the sixty-second restart boundary", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_applied_002").func);
  const previous = {
    ...validatePlan(input("export")).transaction,
    revision: 4,
    issuedAtMs: NOW - 10_000,
    appliedAtMs: NOW - 10_000,
    exportRateChangedAtMs: NOW - 10_000,
  };
  const stopped = {
    ...validatePlan(input("self_consume")).transaction,
    revision: 5,
    issuedAtMs: NOW,
  };
  const state = context({
    energyOptimizerCurrentTransaction: stopped,
    energyOptimizerApplyingRevision: 5,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const before = Date.now();
  const outputs = run({transaction: stopped}, state.flow, {});
  const applied = outputs[1].transaction;
  assert.equal(applied.batteryMode, "self_consume");
  assert.ok(applied.exportRateChangedAtMs >= before);
  assert.equal(applied.exportRateChangedAtMs, applied.appliedAtMs);
});

test("live-state reader uses SAJ PV first and preflights both independent physical readbacks", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_read_live_state_002").func);
  const states = {
    "sensor.saj_pv_power": {state: "12500", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-18T01:59:50Z"},
    "sensor.pv_power_mqtt_abs": {state: "99", attributes: {unit_of_measurement: "kW"}, last_reported: "2026-08-18T01:59:50Z"},
    "sensor.saj_home_load": {state: "2.5", attributes: {unit_of_measurement: "kW"}, last_reported: "2026-08-18T01:59:50Z"},
    "sensor.saj_battery_power": {state: "0", attributes: {unit_of_measurement: "W"}, last_reported: "2026-08-18T01:59:50Z"},
    "number.saj_battery_on_grid_discharge_depth_input": {state: "5", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "5", attributes: {}, last_reported: "2026-08-18T01:59:50Z"},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100.0", attributes: {unit_of_measurement: "%"}, last_reported: "2026-08-18T01:59:50Z"},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "70", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "0", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "off", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "on", attributes: {}},
    "sensor.amber_express_trader_sheena_street_feed_in_price": {state: "-0.05", attributes: {}, last_reported: "2026-08-18T01:59:50Z"},
    "sensor.amber_express_trader_sheena_street_general_price": {state: "0.31", attributes: {}, last_reported: "2026-08-18T01:59:50Z"},
  };
  const result = run({}, {}, {get: () => ({homeAssistant: {states}})});
  assert.equal(result.pvPowerKw, 12.5);
  assert.equal(result.homeLoadKw, 2.5);
  assert.equal(result.liveFitPrice, "-0.05");
  assert.equal(result.liveImportPrice, "0.31");
  assert.equal(result.reserveControlAvailable, true);
  assert.equal(result.batteryDischargeLimitControlAvailable, true);
  assert.equal(result.batteryDischargeLimitSensor, 1000);
  assert.equal(result.watchdogActual.physicalDischargeOn, true);
  assert.equal(result.watchdogActual.dischargePowerPercent, "70");
  assert.equal(result.watchdogActual.batteryDischargeLimitSensor, 1000);
  delete states["sensor.saj_battery_on_grid_discharge_depth"];
  assert.equal(run({}, {}, {get: () => ({homeAssistant: {states}})}).reserveControlAvailable, false);
  states["sensor.saj_battery_on_grid_discharge_depth"] = {state: "5", attributes: {}, last_reported: "2026-08-18T01:59:50Z"};
  delete states["sensor.saj_battery_discharge_power_limit"];
  assert.equal(run({}, {}, {get: () => ({homeAssistant: {states}})}).batteryDischargeLimitControlAvailable, false);

  states["sensor.saj_battery_discharge_power_limit"] = {state: "100", attributes: {}, last_reported: "2026-08-18T01:59:50Z"};
  assert.equal(run({}, {}, {get: () => ({homeAssistant: {states}})}).batteryDischargeLimitControlAvailable, false);
  states["sensor.saj_battery_discharge_power_limit"] = {state: "111", attributes: {unit_of_measurement: "%"}, last_reported: "2026-08-18T01:59:50Z"};
  assert.equal(run({}, {}, {get: () => ({homeAssistant: {states}})}).batteryDischargeLimitControlAvailable, false);
});

test("topology has one versioned tab and one complete SAJ transaction owner", () => {
  assert.equal(flowJson.filter((node) => node.type === "tab").length, 1);
  assert.equal(flowJson[0].id, TAB_ID);
  assert.equal(TAB_ID, "eop_guard_tab_002");
  assert.equal(flowNode("eop_audit_002").data, '{"value":"{{{payload}}}"}');

  const directSajEntities = new Set(flowJson
    .filter((node) => node.type === "api-call-service")
    .flatMap((node) => node.entityId || [])
    .filter((id) => id.startsWith("number.saj_")));
  assert.deepEqual([...directSajEntities].sort(), [
    "number.saj_anti_reflux_mode_input",
    "number.saj_battery_charge_power_limit_input",
    "number.saj_battery_discharge_power_limit_input",
    "number.saj_battery_on_grid_discharge_depth_input",
    "number.saj_charge1_power_percent_input",
    "number.saj_discharge1_power_percent_input",
    "number.saj_export_limit_input",
    "number.saj_grid_max_discharge_power_input",
  ]);

  assert.deepEqual(flowNode("eop_stop_charge_physical_002").entityId, ["switch.saj_charging_control"]);
  assert.deepEqual(flowNode("eop_stop_discharge_physical_002").entityId, ["switch.saj_discharging_control"]);
  assert.deepEqual(flowNode("eop_force_charge_physical_002").entityId, ["switch.saj_charging_control"]);
  assert.deepEqual(flowNode("eop_force_discharge_physical_002").entityId, ["switch.saj_discharging_control"]);
  const directSajSwitches = new Set(flowJson
    .filter((node) => node.type === "api-call-service")
    .flatMap((node) => node.entityId || [])
    .filter((id) => id.startsWith("switch.saj_")));
  assert.deepEqual([...directSajSwitches].sort(), [
    "switch.saj_charging_control",
    "switch.saj_discharging_control",
  ]);
  const legacyRateWriters = flowJson.filter((node) =>
    (node.entityId || []).some((id) => [
      "input_number.battery_charge_rate",
      "input_number.battery_discharge_rate",
    ].includes(id)));
  assert.deepEqual(legacyRateWriters, []);

  const dischargeLimitWriters = flowJson.filter((node) =>
    node.type === "api-call-service" &&
    (node.entityId || []).includes("number.saj_battery_discharge_power_limit_input"));
  assert.deepEqual(dischargeLimitWriters.map((node) => node.id), ["eop_set_battery_discharge_limit_002"]);
  assert.equal(dischargeLimitWriters[0].action, "number.set_value");
  assert.equal(dischargeLimitWriters[0].data, "{\"value\":{{transaction.batteryDischargeLimit}}}");

  const catchScope = new Set(flowNode("eop_serial_catch_002").scope);
  const statusScope = new Set(flowNode("eop_serial_status_002").scope);
  const actuatorServices = flowJson.filter((node) =>
    node.type === "api-call-service" && node.id !== "eop_audit_002");
  for (const node of actuatorServices) {
    assert.equal(catchScope.has(node.id), true, `catch: ${node.id}`);
    assert.equal(statusScope.has(node.id), true, `status: ${node.id}`);
  }
});

test("tab replacement removes old actuator orphans without touching unrelated full-flow nodes", () => {
  const fullFlow = [
    {id: "srv_ha_001", type: "server", name: "Home Assistant"},
    {id: "unrelated_tab", type: "tab", label: "Unrelated"},
    {id: "unrelated_node", type: "inject", z: "unrelated_tab"},
    {id: "eop_guard_tab_001", type: "tab", label: "Retired actuator"},
    {id: "retired_writer", type: "api-call-service", z: "eop_guard_tab_001"},
    {id: TAB_ID, type: "tab", label: "Old actuator"},
    {id: "old_orphan", type: "function", z: TAB_ID},
  ];
  const merged = replaceTab(fullFlow);
  assert.ok(merged.some((node) => node.id === "srv_ha_001"));
  assert.ok(merged.some((node) => node.id === "unrelated_tab"));
  assert.ok(merged.some((node) => node.id === "unrelated_node"));
  assert.equal(merged.some((node) => node.id === "eop_guard_tab_001"), false);
  assert.equal(merged.some((node) => node.id === "retired_writer"), false);
  assert.equal(merged.some((node) => node.id === "old_orphan"), false);
  assert.equal(merged.filter((node) => node.id === TAB_ID).length, 1);
  assert.equal(merged.filter((node) => node.z === TAB_ID).length, flowJson.length - 1);
});

test("safe ordering enables forced modes only after every register, rate and PV decision", () => {
  assert.deepEqual(flowNode("eop_apply_queue_002").wires[0], ["eop_write_strategy_route_002"]);
  assert.deepEqual(flowNode("eop_write_strategy_route_002").wires, [
    ["eop_fast_set_discharge_percent_002"],
    ["eop_stop_charge_physical_002"],
    ["eop_applied_002"],
    ["eop_semantic_confirmed_002"],
  ]);
  assert.deepEqual(flowNode("eop_fast_set_discharge_percent_002").wires, [["eop_applied_002"]]);
  assert.deepEqual(flowNode("eop_stop_charge_physical_002").wires, [["eop_stop_discharge_physical_002"]]);
  assert.deepEqual(flowNode("eop_stop_discharge_physical_002").wires, [["eop_stop_force_helpers_002"]]);
  assert.deepEqual(flowNode("eop_stop_force_helpers_002").wires, [["eop_reserve_route_002"]]);
  assert.deepEqual(flowNode("eop_reserve_route_002").wires, [
    ["eop_set_reserve_002"], ["eop_set_battery_discharge_limit_002"],
  ]);
  assert.deepEqual(flowNode("eop_set_reserve_002").wires, [["eop_set_battery_discharge_limit_002"]]);
  assert.deepEqual(flowNode("eop_set_battery_discharge_limit_002").wires, [["eop_set_grid_max_002"]]);
  assert.deepEqual(flowNode("eop_set_grid_max_002").wires, [["eop_export_route_002"]]);
  assert.deepEqual(flowNode("eop_set_anti_curtail_002").wires, [["eop_set_export_zero_002"]]);
  assert.deepEqual(flowNode("eop_set_export_normal_002").wires, [["eop_set_anti_normal_002"]]);
  assert.deepEqual(flowNode("eop_export_helper_off_002").wires, [["eop_set_charge_percent_002"]]);
  assert.deepEqual(flowNode("eop_export_helper_on_002").wires, [["eop_set_charge_percent_002"]]);
  assert.deepEqual(flowNode("eop_set_charge_percent_002").wires, [["eop_set_discharge_percent_002"]]);
  assert.deepEqual(flowNode("eop_set_discharge_percent_002").wires, [["eop_set_pv_limit_002"]]);
  assert.deepEqual(flowNode("eop_set_pv_limit_002").wires, [["eop_pv_route_002"]]);
  assert.deepEqual(flowNode("eop_pv_charge_on_002").wires, [["eop_pre_force_check_002"]]);
  assert.deepEqual(flowNode("eop_pv_charge_off_002").wires, [["eop_pre_force_check_002"]]);
  assert.deepEqual(flowNode("eop_pre_force_check_002").wires[0], ["eop_forced_route_002"]);
  assert.deepEqual(flowNode("eop_forced_route_002").wires, [
    ["eop_force_charge_physical_002"],
    ["eop_force_discharge_physical_002"],
    ["eop_applied_002"],
  ]);
  assert.equal(flowNode("eop_feedback_delay_002").timeout, "15");
  assert.equal(flowNode("eop_target_delay_002").timeout, "20");
  assert.deepEqual(flowNode("eop_force_discharge_physical_002").wires, [["eop_force_discharge_helper_002"]]);
  assert.deepEqual(flowNode("eop_force_discharge_helper_002").wires, [["eop_applied_002"]]);
});

test("negative-FIT branch uses anti-reflux before zero limit; restore reverses safe order", () => {
  assert.deepEqual(flowNode("eop_export_route_002").wires, [
    ["eop_set_anti_curtail_002"],
    ["eop_set_export_normal_002"],
  ]);
  assert.equal(flowNode("eop_set_anti_curtail_002").data, "{\"value\":1}");
  assert.equal(flowNode("eop_set_export_zero_002").data, "{\"value\":0}");
  assert.equal(flowNode("eop_set_export_normal_002").data, "{\"value\":1100}");
  assert.equal(flowNode("eop_set_anti_normal_002").data, "{\"value\":0}");
});

test("semantic no-op preserves confirmation without any physical write", () => {
  const previous = {...validatePlan(input("hold")).transaction, revision: 20, issuedAtMs: NOW - 30_000};
  const next = {...validatePlan(input("hold")).transaction, planId: "plan-hold-next", revision: 21, issuedAtMs: NOW};
  assert.equal(
    sameSemanticPhysicalCommand(next, previous, previous, null, expectedActual(next)),
    true,
  );
  assert.equal(
    sameSemanticPhysicalCommand({...next, reservePct: 8}, previous, previous, null, expectedActual(next)),
    false,
  );
  const confirm = new Function("msg", "flow", "global", flowNode("eop_semantic_confirmed_002").func);
  const state = context({
    energyOptimizerCurrentTransaction: next,
    energyOptimizerApplyingRevision: 21,
    energyOptimizerLastAppliedTransaction: previous,
  });
  const result = confirm({transaction: next}, state.flow, {});
  assert.match(result[0].payload, /^semantic_noop_confirmed \| plan-hold-next \|/);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), null);
  assert.equal(state.values.get("energyOptimizerLastRegisterConfirmedTransaction").planId, "plan-hold-next");
});

test("expiry, feedback mismatch, catch and red status all converge on the complete safe transaction", () => {
  assert.deepEqual(flowNode("eop_plan_deadline_expired_002").wires[1], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_feedback_confirm_002").wires[1], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_feedback_confirm_002").wires[3], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_target_confirm_002").wires[1], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_target_confirm_002").wires[3], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_service_failure_002").wires[1], ["eop_apply_queue_002"]);
  assert.deepEqual(flowNode("eop_serial_catch_002").wires, [["eop_service_failure_002"]]);
  assert.deepEqual(flowNode("eop_serial_status_002").wires, [["eop_mark_serial_status_002"]]);
});

test("latest-wins queue serializes complete transactions without delaying an idle actuator", () => {
  const enqueue = new Function("msg", "flow", "global", flowNode("eop_apply_queue_002").func);
  const finish = new Function("msg", "flow", "global", flowNode("eop_applied_002").func);
  const first = {...validatePlan(input("export")).transaction, revision: 1};
  const second = {...validatePlan(input("grid_charge")).transaction, revision: 2};
  const third = {...validatePlan(input("hold")).transaction, revision: 3};
  const state = context({energyOptimizerCurrentTransaction: first});

  const startsNow = enqueue({transaction: first}, state.flow, {});
  assert.equal(startsNow[0].transaction.revision, 1);
  assert.equal(startsNow[1], null);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), 1);

  state.flow.set("energyOptimizerCurrentTransaction", second);
  const queued = enqueue({transaction: second}, state.flow, {});
  assert.equal(queued[0], null);
  assert.match(queued[1].payload, /queued_behind_atomic_transaction/);

  state.flow.set("energyOptimizerCurrentTransaction", third);
  const newestQueued = enqueue({transaction: third}, state.flow, {});
  assert.equal(newestQueued[0], null);
  assert.equal(state.values.get("energyOptimizerPendingTransaction").transaction.revision, 3);

  const completedOld = finish({transaction: first}, state.flow, {});
  assert.equal(completedOld[0], null);
  assert.equal(completedOld[1], null);
  assert.equal(completedOld[2].transaction.revision, 3);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), null);

  const startsPending = enqueue(completedOld[2], state.flow, {});
  assert.equal(startsPending[0].transaction.revision, 3);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), 3);
});

test("feedback delays never hold the write lock and stale observers are silent", () => {
  const enqueue = new Function("msg", "flow", "global", flowNode("eop_apply_queue_002").func);
  const finish = new Function("msg", "flow", "global", flowNode("eop_applied_002").func);
  const observe = new Function("msg", "flow", "global", flowNode("eop_feedback_confirm_002").func);
  const first = {...validatePlan(input("export")).transaction, revision: 40, issuedAtMs: NOW};
  const second = {...validatePlan(input("hold")).transaction, revision: 41, issuedAtMs: NOW + 1};
  const state = context({energyOptimizerCurrentTransaction: first});

  enqueue({transaction: first}, state.flow, {});
  const applied = finish({transaction: first}, state.flow, {});
  assert.equal(applied[1].transaction.revision, 40); // feedback may now wait 15s
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), null);

  const reassertedIdentity = {...first, issuedAtMs: NOW + 1, reason: "reassert"};
  state.flow.set("energyOptimizerCurrentTransaction", reassertedIdentity);
  const staleSameRevision = observe(
    {transaction: first},
    state.flow,
    {get: () => ({homeAssistant: {states: {}}})},
  );
  assert.deepEqual(staleSameRevision, [null, null, null, null]);

  state.flow.set("energyOptimizerCurrentTransaction", second);
  const immediate = enqueue({transaction: second}, state.flow, {});
  assert.equal(immediate[0].transaction.revision, 41);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), 41);

  const stale = observe({transaction: first}, state.flow, {get: () => ({homeAssistant: {states: {}}})});
  assert.deepEqual(stale, [null, null, null, null]);
  assert.equal(state.values.get("energyOptimizerCurrentTransaction").revision, 41);
  assert.equal(state.values.has("energyOptimizerLastRegisterConfirmedTransaction"), false);
});

test("a lost transaction lock expires after 30 seconds instead of wedging restart recovery", () => {
  const enqueue = new Function("msg", "flow", "global", flowNode("eop_apply_queue_002").func);
  const tx = {...validatePlan(input("export")).transaction, revision: 9};
  const state = context({
    energyOptimizerCurrentTransaction: tx,
    energyOptimizerApplyingRevision: 8,
    energyOptimizerApplyingStartedAtMs: Date.now() - 30_001,
    energyOptimizerPendingTransaction: {transaction: {revision: 8}},
  });
  const result = enqueue({transaction: tx}, state.flow, {});
  assert.equal(result[0].transaction.revision, 9);
  assert.equal(result[1], null);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), 9);
});

test("initial missing reserve readback fails closed and is never reported applied", () => {
  const applied = new Function("msg", "flow", "global", flowNode("eop_applied_002").func);
  const invalid = input("export", {
    reserveControlAvailable: false,
    reserveNumberPct: "unavailable",
    reserveSensorPct: "unknown",
    reserveSensorMeasuredAtMs: null,
  });
  const rejected = validatePlan(invalid);
  assert.equal(rejected.accepted, false);
  assert.equal(rejected.status, "rejected_reserve_control_unavailable");
  assert.equal(rejected.transaction.reserveControlAvailable, false);
  const tx = {...rejected.transaction, revision: 4};
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerApplyingRevision: 4});
  const result = applied({transaction: tx}, state.flow, {});
  assert.match(result[0].payload, /^failed \| plan-export \|/);
  assert.match(result[0].payload, /reserve_control_unavailable/);
  assert.equal(result[1], null);
});

test("missing independent discharge-limit readback is never reported applied", () => {
  const applied = new Function("msg", "flow", "global", flowNode("eop_applied_002").func);
  const tx = {...validatePlan(input("export", {batteryDischargeLimitControlAvailable: false})).transaction, revision: 5};
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerApplyingRevision: 5});
  const result = applied({transaction: tx}, state.flow, {});
  assert.match(result[0].payload, /^failed \| plan-export \|/);
  assert.match(result[0].payload, /battery_discharge_limit_unavailable/);
  assert.equal(result[1], null);
});

test("final confirmation waits for independent physical reserve readback", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_target_confirm_002").func);
  const tx = {...validatePlan(input("export")).transaction, revision: 6, issuedAtMs: Date.now() - 30_000, reassertCount: 0};
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerRevision: 6});
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "7", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "5", attributes: {}, last_reported: new Date().toISOString()},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "off", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "on", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "70", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "0", attributes: {}},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100.0", attributes: {unit_of_measurement: "%"}, last_reported: new Date().toISOString()},
    "sensor.saj_battery_power": {state: "21000", attributes: {unit_of_measurement: "W"}, last_reported: new Date().toISOString()},
    "sensor.saj_battery_1_soc": {state: "50", attributes: {}},
  };
  const result = run({transaction: tx}, state.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(result[0].payload, /^requested \| plan-export \|/);
  assert.match(result[0].payload, /reserveSensorPct/);
  assert.equal(result[1].transaction.reassertCount, 1);
});

test("final reserve confirmation accepts unchanged matching state but changed targets need post-command evidence", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_target_confirm_002").func);
  const now = Date.now();
  const baseTx = {
    ...validatePlan(input("self_consume")).transaction,
    priorReservePct: 7,
    reservePct: 7,
    revision: 10,
    issuedAtMs: now - 30_000,
    reassertCount: 0,
  };
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "7", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {
      state: "7",
      attributes: {},
      last_reported: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    },
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "off", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "1000", attributes: {}},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {
      state: "100.0",
      attributes: {unit_of_measurement: "%"},
      last_reported: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
    },
    "sensor.saj_battery_power": {
      state: "0",
      attributes: {unit_of_measurement: "W"},
      last_reported: new Date(now).toISOString(),
    },
    "sensor.saj_battery_1_soc": {state: "50", attributes: {}},
  };

  const unchangedState = context({energyOptimizerCurrentTransaction: baseTx, energyOptimizerRevision: 10});
  const unchanged = run({transaction: baseTx}, unchangedState.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(unchanged[0].payload, /^feedback_confirmed \| plan-self_consume \|/);
  assert.equal(unchanged[1], null);

  const changedTx = {...baseTx, priorReservePct: 5};
  const changedState = context({energyOptimizerCurrentTransaction: changedTx, energyOptimizerRevision: 10});
  const precommand = run({transaction: changedTx}, changedState.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(precommand[0].payload, /^requested \| plan-self_consume \|/);
  assert.match(precommand[0].payload, /reserveSensorFresh/);
  assert.equal(precommand[1].transaction.reassertCount, 1);

  states["sensor.saj_battery_on_grid_discharge_depth"].last_reported = new Date(now).toISOString();
  const freshState = context({energyOptimizerCurrentTransaction: changedTx, energyOptimizerRevision: 10});
  const postcommand = run({transaction: changedTx}, freshState.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(postcommand[0].payload, /^feedback_confirmed \| plan-self_consume \|/);
});

test("decimal protected SOC confirms against the ceiled whole-percent physical reserve", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_target_confirm_002").func);
  const now = Date.now();
  const value = input("self_consume", {reserveNumberPct: 39, reserveSensorPct: 39});
  mutatePlan(value, {protected_soc_pct: 39.7});
  const tx = {
    ...validatePlan(value).transaction,
    revision: 11,
    issuedAtMs: now - 30_000,
    reassertCount: 0,
  };
  assert.equal(tx.priorReservePct, 39);
  assert.equal(tx.reservePct, 40);
  assert.equal(reserveTargetChanged(tx), true);
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "40", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "40", attributes: {}, last_reported: new Date(now).toISOString()},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100.0", attributes: {unit_of_measurement: "%"}, last_reported: new Date(now).toISOString()},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "off", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_power": {state: "0", attributes: {unit_of_measurement: "W"}, last_reported: new Date(now).toISOString()},
    "sensor.saj_battery_1_soc": {state: "50", attributes: {}},
  };
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerRevision: 11});
  const confirmed = run({transaction: tx}, state.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(confirmed[0].payload, /^feedback_confirmed \| plan-self_consume \|/);
  assert.equal(confirmed[1], null);
});

test("hold restores normal discharge allowance and needs post-command evidence when it changed", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_target_confirm_002").func);
  const now = Date.now();
  const baseTx = {
    ...validatePlan(input("hold", {
      soc: 50,
      batteryDischargeLimitNumber: 0,
      batteryDischargeLimitSensor: 0,
    })).transaction,
    priorReservePct: 7,
    priorBatteryDischargeLimit: 0,
    batteryDischargeLimit: 1000,
    revision: 12,
    issuedAtMs: now - 30_000,
    reassertCount: 0,
  };
  const old = new Date(now - 24 * 60 * 60 * 1000).toISOString();
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "7", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "7", attributes: {}, last_reported: old},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100", attributes: {unit_of_measurement: "%"}, last_reported: old},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "off", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_power": {state: "0", attributes: {unit_of_measurement: "W"}, last_reported: new Date(now).toISOString()},
    "sensor.saj_battery_1_soc": {state: "50", attributes: {}},
  };

  const changedTx = baseTx;
  const changedState = context({energyOptimizerCurrentTransaction: changedTx, energyOptimizerRevision: 12});
  const stale = run({transaction: changedTx}, changedState.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(stale[0].payload, /^requested \| plan-hold \|/);
  assert.match(stale[0].payload, /batteryDischargeLimitSensorFresh/);

  states["sensor.saj_battery_discharge_power_limit"].last_reported = new Date(now).toISOString();
  const freshState = context({energyOptimizerCurrentTransaction: changedTx, energyOptimizerRevision: 12});
  const fresh = run({transaction: changedTx}, freshState.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(fresh[0].payload, /^feedback_confirmed \| plan-hold \|/);
});

test("mismatch gets one complete reassertion, then fails closed", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_feedback_confirm_002").func);
  const baseTx = {...validatePlan(input("export")).transaction, revision: 7, issuedAtMs: NOW - 20_000, reassertCount: 0};
  const state = context({energyOptimizerCurrentTransaction: baseTx, energyOptimizerRevision: 7});
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "7", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "7", attributes: {}},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "off", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "on", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "off", attributes: {}}, // physical mismatch
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "69", attributes: {}}, // physical register mismatch
    "number.saj_battery_charge_power_limit_input": {state: "0", attributes: {}},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100.0", attributes: {unit_of_measurement: "%"}, last_reported: new Date().toISOString()},
    "sensor.saj_battery_power": {state: "20000", attributes: {unit_of_measurement: "W"}, last_reported: new Date().toISOString()},
    "sensor.saj_battery_1_soc": {state: "50", attributes: {}},
  };
  const first = run({transaction: baseTx}, state.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(first[0].payload, /^requested \| plan-export \|/);
  assert.match(first[0].payload, /physicalDischargeOn/);
  assert.match(first[0].payload, /dischargePowerPercent/);
  assert.equal(first[1].transaction.reassertCount, 1);
  assert.equal(first[3], null);

  const retryTx = first[1].transaction;
  state.flow.set("energyOptimizerCurrentTransaction", retryTx);
  const second = run({transaction: retryTx}, state.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(second[0].payload, /^failed \| plan-export \|/);
  assert.equal(second[1], null);
  assert.equal(second[3].transaction.batteryMode, "safe_stop");
  assert.equal(second[3].transaction.forceDischargeOn, false);
  assert.equal(second[3].transaction.chargePowerPercent, 0);
  assert.equal(second[3].transaction.dischargePowerPercent, 0);
  assert.equal(second[3].transaction.pvChargePowerLimit, 1000);
  assert.equal(second[3].transaction.batteryDischargeLimit, 1000);
});

test("service errors attempt safe-stop once and cannot recurse forever", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_service_failure_002").func);
  const tx = {...validatePlan(input("export")).transaction, revision: 2};
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerRevision: 2});
  const first = run({transaction: tx, error: {message: "Modbus timeout"}}, state.flow, {});
  assert.match(first[0].payload, /^failed \| plan-export \|/);
  assert.equal(first[1].transaction.emergencyAttempted, true);
  assert.equal(first[1].transaction.batteryMode, "safe_stop");
  assert.equal(first[1].transaction.chargePowerPercent, 0);
  assert.equal(first[1].transaction.dischargePowerPercent, 0);
  assert.equal(first[1].transaction.pvChargePowerLimit, 1000);
  assert.equal(first[1].transaction.batteryDischargeLimit, 1000);
  const second = run({transaction: first[1].transaction, error: {message: "still down"}}, state.flow, {});
  assert.match(second[0].payload, /^failed \| plan-export \|/);
  assert.equal(second[1], null);
});

test("a stale write failure cannot safe-stop or overwrite the newer revision", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_service_failure_002").func);
  const oldTx = {...validatePlan(input("export")).transaction, revision: 50};
  const newTx = {...validatePlan(input("hold")).transaction, revision: 51};
  const state = context({
    energyOptimizerCurrentTransaction: newTx,
    energyOptimizerApplyingRevision: 50,
    energyOptimizerApplyingTransaction: oldTx,
    energyOptimizerPendingTransaction: {transaction: newTx},
    energyOptimizerRevision: 51,
  });
  const result = run({transaction: oldTx, error: {message: "late timeout"}}, state.flow, {});
  assert.equal(result[0], null);
  assert.equal(result[1], null);
  assert.equal(result[2].transaction.revision, 51);
  assert.equal(state.values.get("energyOptimizerCurrentTransaction").revision, 51);
  assert.equal(state.values.get("energyOptimizerApplyingRevision"), null);
});

test("emergency fallback records the immediately previous register targets", () => {
  const run = new Function("msg", "flow", "global", flowNode("eop_service_failure_002").func);
  const hold = {...validatePlan(input("hold")).transaction, revision: 13};
  assert.equal(hold.batteryDischargeLimit, 1000);
  const state = context({energyOptimizerCurrentTransaction: hold, energyOptimizerRevision: 13});
  const failed = run({transaction: hold, error: {message: "test"}}, state.flow, {});
  const fallback = failed[1].transaction;
  assert.equal(fallback.priorBatteryDischargeLimit, 1000);
  assert.equal(fallback.batteryDischargeLimit, 1000);
  assert.equal(batteryDischargeLimitTargetChanged(fallback), false);
  assert.equal(fallback.priorReservePct, hold.reservePct);
  assert.equal(fallback.reservePct, hold.reservePct);
  assert.equal(reserveTargetChanged(fallback), false);
});

test("exact expiry is replaceable and safe-stops only the matching revision", () => {
  const arm = new Function("msg", "flow", "global", flowNode("eop_arm_deadline_002").func);
  const expire = new Function("msg", "flow", "global", flowNode("eop_plan_deadline_expired_002").func);
  const value = input("self_consume", {reserveNumberPct: 40, reserveSensorPct: 40});
  mutatePlan(value, {protected_soc_pct: 39.9});
  const tx = {...validatePlan(value).transaction, revision: 3, validUntilMs: Date.now() + 5000};
  assert.equal(tx.reservePct, 40);
  const state = context({energyOptimizerCurrentTransaction: tx, energyOptimizerRevision: 3});
  const armed = arm({transaction: tx}, state.flow, {});
  assert.equal(armed.deadlineRevision, 3);
  assert.ok(armed.delay > 0);

  const superseded = expire({deadlinePlanId: tx.planId, deadlineRevision: 2, deadlineAtMs: Date.now() - 1}, state.flow, {});
  assert.deepEqual(superseded, [null, null, null]);

  state.flow.set("energyOptimizerPlanDeadline", {planId: tx.planId, revision: 3, validUntilMs: Date.now() - 1});
  const expired = expire({deadlinePlanId: tx.planId, deadlineRevision: 3, deadlineAtMs: Date.now() - 1}, state.flow, {});
  assert.match(expired[0].payload, /^failed \| plan-self_consume \|/);
  assert.equal(expired[1].transaction.batteryMode, "safe_stop");
  assert.equal(expired[1].transaction.priorReservePct, 40);
  assert.equal(expired[1].transaction.reservePct, 40);
  assert.equal(expired[1].transaction.chargePowerPercent, 0);
  assert.equal(expired[1].transaction.dischargePowerPercent, 0);
  assert.equal(expired[1].transaction.pvChargePowerLimit, 1000);
  assert.equal(expired[1].transaction.batteryDischargeLimit, 1000);

  const confirm = new Function("msg", "flow", "global", flowNode("eop_target_confirm_002").func);
  const confirmedTx = {...expired[1].transaction, issuedAtMs: Date.now() - 30_000};
  state.flow.set("energyOptimizerCurrentTransaction", confirmedTx);
  const old = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const states = {
    "number.saj_battery_on_grid_discharge_depth_input": {state: "40", attributes: {}},
    "sensor.saj_battery_on_grid_discharge_depth": {state: "40", attributes: {}, last_reported: old},
    "number.saj_battery_discharge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_discharge_power_limit": {state: "100.0", attributes: {unit_of_measurement: "%"}, last_reported: old},
    "number.saj_anti_reflux_mode_input": {state: "0", attributes: {}},
    "number.saj_export_limit_input": {state: "1100", attributes: {}},
    "number.saj_grid_max_discharge_power_input": {state: "1100", attributes: {}},
    "input_boolean.export_power": {state: "on", attributes: {}},
    "input_boolean.battery_pv_charge": {state: "on", attributes: {}},
    "input_boolean.battery_charge": {state: "off", attributes: {}},
    "input_boolean.battery_discharge": {state: "off", attributes: {}},
    "switch.saj_charging_control": {state: "off", attributes: {}},
    "switch.saj_discharging_control": {state: "off", attributes: {}},
    "number.saj_charge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_discharge1_power_percent_input": {state: "0", attributes: {}},
    "number.saj_battery_charge_power_limit_input": {state: "1000", attributes: {}},
    "sensor.saj_battery_power": {state: "0", attributes: {unit_of_measurement: "W"}, last_reported: new Date().toISOString()},
    "sensor.saj_battery_1_soc": {state: "40.2", attributes: {}},
  };
  const feedback = confirm({transaction: confirmedTx}, state.flow, {get: () => ({homeAssistant: {states}})});
  assert.match(feedback[0].payload, /^feedback_confirmed \| plan-self_consume \|/);
  assert.match(feedback[0].payload, /\| mode=safe_stop \|/);
  assert.equal(feedback[1], null);
});
