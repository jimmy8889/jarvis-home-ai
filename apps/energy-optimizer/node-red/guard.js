"use strict";

const MAX_DISCHARGE_KW = 28;
const MAX_CHARGE_KW = 30;
const DEFAULT_DISCHARGE_CAP_KW = 28;
const MAX_SITE_EXPORT_TARGET_KW = 100;
const MAX_TELEMETRY_AGE_MS = 330 * 1000;
const MAX_PRICE_AGE_MS = 330 * 1000;
const MAX_FUTURE_SKEW_MS = 60 * 1000;
const MAX_FEEDBACK_AGE_MS = 60 * 1000;
const EXPORT_RATE_MIN_INTERVAL_MS = 60 * 1000;
const EXPORT_RATE_DEADBAND_KW = 1;
const EXPORT_RATE_DEADBAND_RATIO = 0.10;
const NORMAL_EXPORT_LIMIT = 1100;
const ZERO_EXPORT_LIMIT = 0;
const NORMAL_GRID_DISCHARGE_LIMIT = 1100;
const NORMAL_BATTERY_DISCHARGE_LIMIT = 1000;
const SAFE_RESERVE_FLOOR_PCT = 5;
const BATTERY_MODES = Object.freeze([
  "hold",
  "self_consume",
  "pv_charge",
  "grid_charge",
  "export",
]);

function finite(value) {
  if (value === null || value === undefined) return null;
  if (
    typeof value === "string" &&
    (!value.trim() || ["unknown", "unavailable", "none", "null"].includes(value.trim().toLowerCase()))
  ) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function on(value) {
  return String(value || "").toLowerCase() === "on";
}

function binaryOn(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "on") return true;
  if (normalized === "off") return false;
  return null;
}

function timestampMs(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const parsed = Date.parse(value || "");
  return Number.isFinite(parsed) ? parsed : null;
}

function freshAge(nowMs, measuredAtMs, maxAgeMs) {
  const measured = finite(measuredAtMs);
  if (measured === null) return null;
  const age = nowMs - measured;
  if (age > maxAgeMs || age < -MAX_FUTURE_SKEW_MS) return null;
  return age;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function forcePowerPercent(rateKw) {
  const value = finite(rateKw);
  if (value === null || value <= 0) return 0;
  return clamp(Math.round(value / 30 * 100), 0, 100);
}

function pvChargePowerLimitForKw(rateKw) {
  const value = finite(rateKw);
  if (value === null || value <= 0) return 0;
  const clamped = clamp(value, 1, 30);
  return clamp(Math.round((clamped - 1) / 29 * 10) * 100, 0, 1100);
}

function batteryDischargeLimitSensorToRegister(value, unit) {
  const percent = finite(value);
  const normalizedUnit = String(unit ?? "").trim().toLowerCase();
  // The writable 0x364E number uses 0..1100 while its independent sensor is
  // exposed by the integration as 0..110 %. Never guess when the unit is
  // absent: an ambiguous unit would make a dangerous 100 look like 10%.
  if (percent === null || normalizedUnit !== "%" || percent < 0 || percent > 110) return null;
  const registerValue = percent * 10;
  return registerValue >= 0 && registerValue <= 1100 ? registerValue : null;
}

function normalizedWholeReservePct(value) {
  const parsed = finite(value);
  if (parsed === null || parsed < 5 || parsed > 100.5) return null;
  return clamp(Math.ceil(parsed), 5, 100);
}

function preservedReservePct(value) {
  return normalizedWholeReservePct(value) ?? 5;
}

function safeReservePct(input) {
  const plan = input.planEntity?.attributes || {};
  const currentReserve = normalizedWholeReservePct(input.reserveSensorPct);
  const liveSoc = finite(input.soc);
  const liveSocCap = liveSoc === null || liveSoc < 5 || liveSoc > 100.5 ?
    null : clamp(Math.floor(liveSoc), 5, 100);
  const priorProtection = normalizedWholeReservePct(plan.protected_soc_pct);
  // A stale/invalid plan may preserve protection, but may not raise the floor
  // beyond fresh live SOC. The already-active independent reserve is the sole
  // exception: lowering it during reject/expiry handling caused a live 40->5
  // rollover and must never happen again.
  const safePriorProtection = liveSocCap === null || priorProtection === null ?
    null : Math.min(priorProtection, liveSocCap);
  return Math.max(
    SAFE_RESERVE_FLOOR_PCT,
    currentReserve ?? SAFE_RESERVE_FLOOR_PCT,
    safePriorProtection ?? SAFE_RESERVE_FLOOR_PCT,
  );
}

function sameTransactionIdentity(left, right) {
  return Boolean(left && right) &&
    String(left.planId || "") === String(right.planId || "") &&
    finite(left.revision) !== null && finite(left.revision) === finite(right.revision) &&
    finite(left.issuedAtMs) !== null && finite(left.issuedAtMs) === finite(right.issuedAtMs);
}

function samePlanCommit(left, right) {
  return Boolean(left && right) &&
    String(left.planId || "") === String(right.planId || "") &&
    finite(left.generatedAtMs) !== null && finite(left.generatedAtMs) === finite(right.generatedAtMs) &&
    finite(left.validUntilMs) !== null && finite(left.validUntilMs) === finite(right.validUntilMs) &&
    String(left.softwareVersion || "") === String(right.softwareVersion || "") &&
    String(left.configFingerprint || "") === String(right.configFingerprint || "");
}

function sameSemanticPhysicalCommand(transaction, confirmed, applied, applyingRevision, actual) {
  if (
    !transaction || !confirmed || !applied ||
    (applyingRevision !== null && applyingRevision !== undefined) ||
    !sameTransactionIdentity(confirmed, applied) ||
    !String(transaction.commandSemanticHash || "").trim() ||
    transaction.commandSemanticHash !== confirmed.commandSemanticHash ||
    Math.abs(Number(transaction.targetKw || 0) - Number(confirmed.targetKw || 0)) > 0.05
  ) return false;
  return verifyRegisterState(transaction, actual || {}).ok;
}

function exportRateOnlyEligible(transaction, confirmed, applied, applyingRevision) {
  if (
    transaction?.safeStop || transaction?.batteryMode !== "export" ||
    transaction?.forceDischargeOn !== true ||
    (applyingRevision !== null && applyingRevision !== undefined && applyingRevision !== transaction.revision) ||
    !sameTransactionIdentity(confirmed, applied) ||
    confirmed.batteryMode !== "export" || confirmed.forceDischargeOn !== true
  ) return false;
  const unchanged = [
    "reservePct", "batteryDischargeLimit", "pvExportCommand", "antiRefluxMode",
    "exportLimit", "gridMaxDischarge", "exportHelperOn", "pvChargeOn",
    "forceChargeOn", "forceDischargeOn", "chargePowerPercent",
    "pvChargePowerLimit", "softwareVersion", "configFingerprint",
    "priceIntervalStartMs",
  ];
  return unchanged.every((key) => transaction[key] === confirmed[key]);
}

function heldExportNoWriteEligible(transaction, applied, applyingRevision) {
  if (
    transaction?.safeStop || transaction?.batteryMode !== "export" ||
    transaction?.forceDischargeOn !== true ||
    !String(transaction?.reason || "").includes("held_60s") ||
    (applyingRevision !== null && applyingRevision !== undefined && applyingRevision !== transaction.revision) ||
    applied?.batteryMode !== "export" || applied?.forceDischargeOn !== true
  ) return false;
  const unchanged = [
    "targetKw", "reservePct", "batteryDischargeLimit", "pvExportCommand",
    "antiRefluxMode", "exportLimit", "gridMaxDischarge", "exportHelperOn",
    "pvChargeOn", "forceChargeOn", "forceDischargeOn", "chargePowerPercent",
    "dischargePowerPercent", "pvChargePowerLimit", "softwareVersion",
    "configFingerprint", "priceIntervalStartMs",
  ];
  return unchanged.every((key) => transaction[key] === applied[key]);
}

function conservativeCurtail(input, nowMs) {
  const fit = finite(input.liveFitPrice);
  const fitAge = freshAge(nowMs, input.liveFitMeasuredAtMs, MAX_PRICE_AGE_MS);
  // Anti-reflux is a price action, not the generic failure state. Unknown or
  // stale prices restore normal export; only a fresh signed-negative FIT may
  // force the site target to zero.
  return fit !== null && fitAge !== null && fit < 0;
}

function safeTransaction(input, reason) {
  const nowMs = input.nowMs ?? Date.now();
  const plan = input.planEntity?.attributes || {};
  const reserveControlAvailable = input.reserveControlAvailable === true;
  const reservePct = safeReservePct(input);
  const curtail = conservativeCurtail(input, nowMs);
  return {
    planId: String(plan.plan_id || input.planEntity?.state || "unknown"),
    batteryMode: "safe_stop",
    reason,
    safeStop: true,
    writeStrategy: "full",
    targetKw: 0,
    plannedBatteryTargetKw: 0,
    siteExportTargetKw: 0,
    protectedSocPct: reservePct,
    priorReservePct: finite(input.reserveSensorPct),
    reservePct,
    reserveControlAvailable,
    priorBatteryDischargeLimit: finite(input.batteryDischargeLimitSensor),
    batteryDischargeLimit: NORMAL_BATTERY_DISCHARGE_LIMIT,
    batteryDischargeLimitControlAvailable: input.batteryDischargeLimitControlAvailable === true,
    pvExportCommand: curtail ? "curtail" : "allow",
    antiRefluxMode: curtail ? 1 : 0,
    exportLimit: curtail ? ZERO_EXPORT_LIMIT : NORMAL_EXPORT_LIMIT,
    gridMaxDischarge: NORMAL_GRID_DISCHARGE_LIMIT,
    exportHelperOn: !curtail,
    pvChargeOn: true,
    forceChargeOn: false,
    forceDischargeOn: false,
    chargeRateKw: MAX_CHARGE_KW,
    dischargeRateKw: MAX_DISCHARGE_KW,
    chargePowerPercent: 0,
    dischargePowerPercent: 0,
    pvChargePowerLimit: pvChargePowerLimitForKw(MAX_CHARGE_KW),
    issuedAtMs: nowMs,
    validUntilMs: null,
    reassertCount: 0,
  };
}

function rejected(input, reason) {
  return {
    accepted: false,
    actuate: true,
    safeStop: true,
    status: reason,
    transaction: safeTransaction(input, reason),
  };
}

function sourceTimestampStatus(plan, nowMs) {
  const source = plan.source_timestamps;
  if (!source || typeof source !== "object" || Array.isArray(source)) return "rejected_source_timestamps";
  const required = [
    "amber_fit",
    "amber_import",
    "battery_soc",
    "battery_soc_heartbeat",
    "pv_power",
    "pv_heartbeat",
    "home_load",
  ];
  for (const key of required) {
    const parsed = timestampMs(source[key]);
    if (parsed === null) return `rejected_source_timestamp_${key}`;
    const maxAge = key === "battery_soc" ? 24 * 60 * 60 * 1000 :
      key.startsWith("amber_") ? MAX_PRICE_AGE_MS : MAX_TELEMETRY_AGE_MS;
    if (freshAge(nowMs, parsed, maxAge) === null) return `rejected_source_stale_${key}`;
  }
  return null;
}

function isNonActuatingSafeHold(plan, nowMs) {
  const generatedAt = timestampMs(plan.generated_at);
  const validUntil = timestampMs(plan.valid_until);
  const zeroTargets = [
    plan.battery_power_target_kw,
    plan.battery_charge_target_kw,
    plan.battery_discharge_target_kw,
    plan.site_export_target_kw,
  ].every((value) => typeof value === "number" && value === 0);
  return plan.schema_version === 2 &&
    generatedAt !== null && validUntil !== null && nowMs < validUntil &&
    nowMs - generatedAt <= 10 * 60 * 1000 && generatedAt <= nowMs + MAX_FUTURE_SKEW_MS &&
    Boolean(String(plan.plan_id || "").trim()) &&
    Boolean(String(plan.software_version || "").trim()) &&
    Boolean(String(plan.config_fingerprint || "").trim()) &&
    Boolean(String(plan.command_semantic_hash || "").trim()) &&
    plan.actuation_allowed === false &&
    String(plan.battery_mode || "").toLowerCase() === "hold" &&
    zeroTargets &&
    plan.live_fit_price === null && plan.live_import_price === null &&
    plan.price_interval_start === null && plan.price_interval_end === null;
}

function validatePlan(input) {
  const nowMs = input.nowMs ?? Date.now();
  const entity = input.planEntity || {};
  const plan = entity.attributes || {};
  const controlMode = String(input.mode || "shadow").toLowerCase();

  if (on(input.manualOverride)) return rejected(input, "manual_override");
  if (controlMode !== "active") return rejected(input, controlMode || "disabled");
  if (!on(input.rolloutApproved)) return rejected(input, "rollout_not_approved");
  if (!on(input.batteryControl)) return rejected(input, "battery_control_off");

  const validUntil = timestampMs(plan.valid_until);
  const generatedAt = timestampMs(plan.generated_at);
  const priceStart = timestampMs(plan.price_interval_start);
  const priceEnd = timestampMs(plan.price_interval_end);
  if (
    plan.schema_version !== 2 ||
    validUntil === null || generatedAt === null ||
    !String(plan.plan_id || "").trim() || !String(plan.software_version || "").trim() ||
    !String(plan.config_fingerprint || "").trim() ||
    !String(plan.command_semantic_hash || "").trim()
  ) return rejected(input, "rejected_schema_v2");

  // A fast publisher must never fabricate a price pair during the Amber
  // interval rollover. Its exact non-actuating hold shape is a deliberate
  // request for the guarded actuator to stop forced modes immediately while
  // retaining the independently observed reserve floor.
  if (isNonActuatingSafeHold(plan, nowMs)) {
    return rejected(input, "safe_hold_non_actuating");
  }
  if (priceStart === null || priceEnd === null) return rejected(input, "rejected_schema_v2");

  if (
    nowMs >= validUntil || nowMs - generatedAt > 10 * 60 * 1000 ||
    generatedAt > nowMs + MAX_FUTURE_SKEW_MS || priceStart >= priceEnd
  ) return rejected(input, "rejected_stale_plan");
  if (plan.actuation_allowed !== true || String(plan.mode || "").toLowerCase() !== "active") {
    return rejected(input, "rejected_not_allowed");
  }

  const replayGeneratedAtMs = finite(input.lastAcceptedGeneratedAtMs);
  const replayPlanId = String(input.lastAcceptedPlanId || "");
  if (
    replayGeneratedAtMs !== null &&
    (generatedAt < replayGeneratedAtMs || (generatedAt === replayGeneratedAtMs && replayPlanId && replayPlanId !== String(plan.plan_id)))
  ) return rejected(input, "rejected_plan_revision");

  const sourceError = sourceTimestampStatus(plan, nowMs);
  if (sourceError) return rejected(input, sourceError);

  const mode = String(plan.battery_mode || "").toLowerCase();
  const pvExportCommand = String(plan.pv_export_command || "").toLowerCase();
  if (!BATTERY_MODES.includes(mode)) return rejected(input, "rejected_battery_mode");
  if (!["allow", "curtail"].includes(pvExportCommand)) return rejected(input, "rejected_pv_command");

  const signedTarget = finite(plan.battery_power_target_kw);
  const chargeTarget = finite(plan.battery_charge_target_kw);
  const dischargeTarget = finite(plan.battery_discharge_target_kw);
  const siteExportTarget = finite(plan.site_export_target_kw);
  const protectedSoc = finite(plan.protected_soc_pct);
  const plannedFit = finite(plan.live_fit_price);
  const plannedImport = finite(plan.live_import_price);
  const minimumSellPrice = finite(plan.minimum_sell_price);
  const effectiveSellPrice = finite(plan.effective_sell_price);
  const soc = finite(input.soc);
  const inverterFloor = finite(input.minSocPct);
  const livePvKw = finite(input.pvPowerKw);
  const liveLoadKw = finite(input.homeLoadKw);
  if (
    [signedTarget, chargeTarget, dischargeTarget, siteExportTarget, protectedSoc, plannedFit, plannedImport,
      minimumSellPrice, effectiveSellPrice,
      soc, inverterFloor, livePvKw, liveLoadKw].some((value) => value === null)
  ) return rejected(input, "rejected_invalid_numeric");

  if (
    freshAge(nowMs, input.socHeartbeatMeasuredAtMs, MAX_TELEMETRY_AGE_MS) === null ||
    freshAge(nowMs, input.pvMeasuredAtMs, MAX_TELEMETRY_AGE_MS) === null ||
    freshAge(nowMs, input.homeLoadMeasuredAtMs, MAX_TELEMETRY_AGE_MS) === null
  ) return rejected(input, "rejected_live_telemetry_stale");

  // This Modbus setting sensor reports on value change, not on every poll.
  // Presence plus a numeric independent value is the preflight; a changed
  // target is proven later by a matching post-command sensor timestamp.
  if (
    input.reserveControlAvailable !== true ||
    finite(input.reserveNumberPct) === null || finite(input.reserveSensorPct) === null ||
    finite(input.reserveSensorMeasuredAtMs) === null
  ) return rejected(input, "rejected_reserve_control_unavailable");

  // 0x3644 is only a SOC floor; it did not immediately stop live self-use
  // discharge. 0x364E is therefore a separate mandatory, independently read
  // discharge inhibit/limit for every controlled transaction.
  if (
    input.batteryDischargeLimitControlAvailable !== true ||
    finite(input.batteryDischargeLimitNumber) === null ||
    finite(input.batteryDischargeLimitNumber) < 0 ||
    finite(input.batteryDischargeLimitNumber) > 1100 ||
    finite(input.batteryDischargeLimitSensor) === null ||
    finite(input.batteryDischargeLimitSensor) < 0 ||
    finite(input.batteryDischargeLimitSensor) > 1100 ||
    finite(input.batteryDischargeLimitSensorMeasuredAtMs) === null
  ) return rejected(input, "rejected_battery_discharge_limit_unavailable");

  // The live SAJ lower-limit sensor is the setting this transaction owns; a
  // preceding hold may have raised it. It is not an immutable hardware floor.
  const hardFloor = SAFE_RESERVE_FLOOR_PCT;
  if (
    inverterFloor < 5 || inverterFloor > 100 || soc < hardFloor - 0.5 || soc > 100.5 ||
    protectedSoc < hardFloor || protectedSoc > 100 || chargeTarget < 0 || chargeTarget > MAX_CHARGE_KW + 0.01 ||
    dischargeTarget < 0 || dischargeTarget > MAX_DISCHARGE_KW + 0.01 ||
    Math.abs(signedTarget) > MAX_CHARGE_KW + 0.01 ||
    minimumSellPrice < 0 || minimumSellPrice > 2 ||
    effectiveSellPrice < minimumSellPrice - 0.000001 || effectiveSellPrice > 2 ||
    siteExportTarget < 0 || siteExportTarget > MAX_SITE_EXPORT_TARGET_KW ||
    livePvKw < 0 || livePvKw > 100 || liveLoadKw < 0 || liveLoadKw > 100
  ) return rejected(input, "rejected_bounds");

  const liveFit = finite(input.liveFitPrice);
  const liveFitAge = freshAge(nowMs, input.liveFitMeasuredAtMs, MAX_PRICE_AGE_MS);
  const livePriceFresh = liveFit !== null && liveFitAge !== null;
  const liveImport = finite(input.liveImportPrice);
  const liveImportAge = freshAge(nowMs, input.liveImportMeasuredAtMs, MAX_PRICE_AGE_MS);
  const liveImportFresh = liveImport !== null && liveImportAge !== null;
  const daylight = input.sunState !== "below_horizon" || livePvKw > 0.1;
  if (livePriceFresh && liveFit < 0 && pvExportCommand !== "curtail") {
    return rejected(input, "rejected_negative_fit_requires_curtail");
  }
  if (!livePriceFresh && daylight) return rejected(input, "rejected_live_fit_stale");

  const priceSensitive = mode === "export" || mode === "grid_charge";
  if (priceSensitive) {
    if (!livePriceFresh) return rejected(input, "rejected_price_sensitive_without_live_fit");
    if (!liveImportFresh) return rejected(input, "rejected_price_sensitive_without_live_import");
    if (nowMs < priceStart || nowMs >= priceEnd) {
      return rejected(input, "rejected_price_interval");
    }
    const fitAdverse = mode === "export" ? liveFit < plannedFit - 0.005 : liveFit > plannedFit + 0.005;
    if (fitAdverse) return rejected(input, "rejected_live_fit_mismatch");
    if (liveImport > plannedImport + 0.005) return rejected(input, "rejected_live_import_mismatch");
  }

  if (
    (mode === "export" && (signedTarget <= 0 || dischargeTarget <= 0 || chargeTarget > 0.01)) ||
    (mode === "grid_charge" && (signedTarget >= 0 || chargeTarget <= 0 || dischargeTarget > 0.01)) ||
    (mode === "pv_charge" && (signedTarget >= 0 || chargeTarget <= 0 || dischargeTarget > 0.01)) ||
    (mode === "self_consume" && (signedTarget < -0.01 || chargeTarget > 0.01)) ||
    (mode === "hold" &&
      (Math.abs(signedTarget) > 0.01 || chargeTarget > 0.01 || dischargeTarget > 0.01))
  ) return rejected(input, "rejected_target_sign");
  if (
    (mode === "export" && Math.abs(signedTarget - dischargeTarget) > 0.05) ||
    (mode === "self_consume" && Math.abs(signedTarget - dischargeTarget) > 0.05) ||
    (["grid_charge", "pv_charge"].includes(mode) && Math.abs(Math.abs(signedTarget) - chargeTarget) > 0.05)
  ) return rejected(input, "rejected_target_components");
  if (mode === "export" && (pvExportCommand !== "allow" || siteExportTarget <= 0 || soc <= protectedSoc + 1)) {
    return rejected(input, "rejected_export_guard");
  }
  if (mode === "export" && liveFit + 0.000001 < effectiveSellPrice) {
    return rejected(input, "rejected_below_minimum_sell_price");
  }
  if (mode === "grid_charge" && soc >= 99) return rejected(input, "rejected_grid_charge_guard");

  const configuredCap = finite(input.maxDischargeCapKw);
  const dischargeCap = Math.min(
    MAX_DISCHARGE_KW,
    configuredCap === null ? DEFAULT_DISCHARGE_CAP_KW : Math.max(0, configuredCap),
  );
  let appliedTargetKw = 0;
  const hotWaterControlMode = String(plan.hot_water_control_mode || "off").toLowerCase();
  const gridOnlyHotWaterRescue = mode === "self_consume" && hotWaterControlMode === "service_rescue";
  if (mode === "export") {
    const siteBalanceKw = Math.max(0, siteExportTarget + liveLoadKw - livePvKw);
    appliedTargetKw = Math.min(siteBalanceKw, dischargeTarget, dischargeCap);
  } else if (mode === "grid_charge" || mode === "pv_charge") {
    appliedTargetKw = Math.min(chargeTarget, MAX_CHARGE_KW);
  } else if (gridOnlyHotWaterRescue) {
    appliedTargetKw = Math.min(dischargeTarget, dischargeCap);
  }

  const curtail = pvExportCommand === "curtail" || (livePriceFresh && liveFit < 0);
  const transaction = {
    planId: String(plan.plan_id),
    batteryMode: mode,
    reason: `accepted_${mode}`,
    safeStop: false,
    writeStrategy: "full",
    targetKw: appliedTargetKw,
    plannedBatteryTargetKw: signedTarget,
    siteExportTargetKw: siteExportTarget,
    protectedSocPct: protectedSoc,
    priorReservePct: finite(input.reserveSensorPct),
    // The SAJ register is whole-percent. Always round protection upward so the
    // physical floor can never land below the optimizer trajectory.
    reservePct: clamp(Math.ceil(protectedSoc), SAFE_RESERVE_FLOOR_PCT, 100),
    reserveControlAvailable: true,
    priorBatteryDischargeLimit: finite(input.batteryDischargeLimitSensor),
    // Never latch the normal battery-discharge allowance to zero.  The
    // inverter may cover household demand down to the protected reserve in
    // every non-forced situation; exclusive force switches still control grid
    // charge and export transactions.
    batteryDischargeLimit: NORMAL_BATTERY_DISCHARGE_LIMIT,
    batteryDischargeLimitControlAvailable: true,
    pvExportCommand: curtail ? "curtail" : "allow",
    antiRefluxMode: curtail ? 1 : 0,
    exportLimit: curtail ? ZERO_EXPORT_LIMIT : NORMAL_EXPORT_LIMIT,
    gridMaxDischarge: NORMAL_GRID_DISCHARGE_LIMIT,
    exportHelperOn: !curtail,
    // PV charging is never administratively inhibited. Forced export may win
    // momentarily inside the inverter, but the solar charge path remains open.
    pvChargeOn: true,
    forceChargeOn: mode === "grid_charge",
    forceDischargeOn: (mode === "export" || gridOnlyHotWaterRescue) && appliedTargetKw > 0.05,
    chargeRateKw: ["grid_charge", "pv_charge"].includes(mode) ? appliedTargetKw : MAX_CHARGE_KW,
    dischargeRateKw: (mode === "export" || gridOnlyHotWaterRescue) && appliedTargetKw > 0.05 ? appliedTargetKw : MAX_DISCHARGE_KW,
    liveFitPrice: liveFit,
    liveFitAgeMs: liveFitAge,
    liveImportPrice: liveImport,
    liveImportAgeMs: liveImportAge,
    livePvKw,
    liveLoadKw,
    soc,
    validUntilMs: validUntil,
    priceIntervalStartMs: priceStart,
    generatedAtMs: generatedAt,
    softwareVersion: String(plan.software_version),
    configFingerprint: String(plan.config_fingerprint),
    commandSemanticHash: String(plan.command_semantic_hash),
    hotWaterControlMode,
    issuedAtMs: nowMs,
    acceptedAtMs: nowMs,
    reassertCount: 0,
  };

  if (mode === "export" && appliedTargetKw <= 0.05) {
    transaction.forceDischargeOn = false;
    transaction.reason = "accepted_export_pv_meets_site_target";
  }
  if (gridOnlyHotWaterRescue && appliedTargetKw > 0.05) {
    transaction.reason = "accepted_self_consume_grid_only_hot_water_rescue";
  }
  transaction.chargePowerPercent = transaction.forceChargeOn ? forcePowerPercent(transaction.chargeRateKw) : 0;
  transaction.dischargePowerPercent = transaction.forceDischargeOn ? forcePowerPercent(transaction.dischargeRateKw) : 0;
  // The planned PV-charge target describes the surplus expected right now; it
  // must not become a ceiling on what the roof is allowed to produce.  Keep
  // the SAJ solar-to-battery path at its verified 30 kW limit in every mode.
  // Anti-reflux/export-limit registers independently hold grid export at zero
  // during negative FIT, so only surplus left after loads, flexible loads and
  // a full-rate battery is physically curtailed.
  transaction.pvChargePowerLimit = transaction.pvChargeOn ?
    pvChargePowerLimitForKw(MAX_CHARGE_KW) : 0;
  return {
    accepted: true,
    actuate: true,
    safeStop: false,
    status: transaction.reason,
    generatedAtMs: generatedAt,
    transaction,
  };
}

function feedbackTolerance(targetKw) {
  const target = finite(targetKw);
  return target === null ? null : Math.max(1, Math.abs(target) * 0.1);
}

function expectedRegisterState(transaction) {
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
  };
}

function verifyRegisterState(transaction, actual) {
  const expected = expectedRegisterState(transaction);
  const mismatches = [];
  const numeric = [
    ["antiRefluxMode", 0.01],
    ["exportLimit", 1],
    ["gridMaxDischarge", 1],
    ["chargePowerPercent", 0.51],
    ["dischargePowerPercent", 0.51],
    ["pvChargePowerLimit", 1],
  ];
  if (transaction.reserveControlAvailable === true) {
    numeric.unshift(["reserveSensorPct", 0.51]);
    numeric.unshift(["reserveNumberPct", 0.51]);
  }
  if (transaction.batteryDischargeLimitControlAvailable === true) {
    numeric.unshift(["batteryDischargeLimitSensor", 1]);
    numeric.unshift(["batteryDischargeLimitNumber", 1]);
  }
  for (const [key, tolerance] of numeric) {
    const observed = finite(actual[key]);
    if (observed === null || Math.abs(observed - expected[key]) > tolerance) mismatches.push(key);
  }
  for (const key of [
    "exportHelperOn", "pvChargeOn", "forceChargeOn", "forceDischargeOn",
    "physicalChargeOn", "physicalDischargeOn",
  ]) {
    if (actual[key] !== expected[key]) mismatches.push(key);
  }
  return {ok: mismatches.length === 0, mismatches, expected};
}

function reserveTargetChanged(transaction) {
  const prior = finite(transaction?.priorReservePct);
  const target = finite(transaction?.reservePct);
  return prior === null || target === null || Math.abs(prior - target) > 0.51;
}

function batteryDischargeLimitTargetChanged(transaction) {
  const prior = finite(transaction?.priorBatteryDischargeLimit);
  const target = finite(transaction?.batteryDischargeLimit);
  return prior === null || target === null || Math.abs(prior - target) > 1;
}

function evaluateDirectionFeedback(transaction, actual) {
  const batteryKw = finite(actual.batteryKw);
  const measuredAtMs = finite(actual.batteryMeasuredAtMs);
  const nowMs = finite(actual.nowMs) ?? Date.now();
  const issuedAtMs = finite(transaction.issuedAtMs);
  if (batteryKw === null || measuredAtMs === null || issuedAtMs === null) {
    return {ok: false, status: "feedback_direction_unavailable", batteryKw};
  }
  const ageMs = nowMs - measuredAtMs;
  if (ageMs < 0 || ageMs > MAX_FEEDBACK_AGE_MS) {
    return {ok: false, status: "feedback_direction_stale", batteryKw, ageMs};
  }
  if (measuredAtMs < issuedAtMs && transaction.writeStrategy !== "no_write") {
    return {ok: false, status: "feedback_direction_precommand", batteryKw, ageMs};
  }
  if (transaction.forceDischargeOn && batteryKw < 0.2) {
    return {ok: false, status: "feedback_direction_wrong_export", batteryKw, ageMs};
  }
  if (transaction.forceChargeOn && batteryKw > -0.2) {
    return {ok: false, status: "feedback_direction_wrong_grid_charge", batteryKw, ageMs};
  }
  return {ok: true, status: "confirmed_direction", batteryKw, ageMs};
}

function evaluateTargetFeedback(transaction, actual) {
  const batteryKw = finite(actual.batteryKw);
  const measuredAtMs = finite(actual.batteryMeasuredAtMs);
  const nowMs = finite(actual.nowMs) ?? Date.now();
  const issuedAtMs = finite(transaction.issuedAtMs);
  const targetKw = finite(transaction.targetKw);
  if (batteryKw === null || measuredAtMs === null || issuedAtMs === null || targetKw === null) {
    return {ok: false, status: "feedback_target_unavailable", batteryKw};
  }
  const ageMs = nowMs - measuredAtMs;
  if (ageMs < 0 || ageMs > MAX_FEEDBACK_AGE_MS ||
      (measuredAtMs < issuedAtMs && transaction.writeStrategy !== "no_write")) {
    return {ok: false, status: "feedback_target_stale", batteryKw, ageMs};
  }
  const soc = finite(actual.soc);
  if (transaction.batteryMode === "export" && soc !== null && soc <= transaction.protectedSocPct + 1) {
    return {ok: true, status: "confirmed_target_clipped_floor", batteryKw, clipped: true};
  }
  if (["grid_charge", "pv_charge"].includes(transaction.batteryMode) && soc !== null && soc >= 99) {
    return {ok: true, status: "confirmed_target_clipped_upper_soc", batteryKw, clipped: true};
  }
  if (transaction.batteryMode === "export" && String(transaction.reason || "").includes("held_60s")) {
    // During the deliberate stability window, register verification plus the
    // earlier signed battery-direction check are authoritative. Site export
    // can move as household load/PV changes even though the physical battery
    // rate has correctly remained fixed; do not turn that noise into a full
    // transaction reassertion.
    return {ok: true, status: "confirmed_export_rate_held", batteryKw};
  }

  let expectedKw;
  let observedKw;
  if (transaction.batteryMode === "export") {
    // Export is a site-level objective.  PV and house load can move after the
    // battery setpoint was translated, so battery power alone is not proof
    // that the requested grid export was missed.  Confirm the actual site
    // export using the fast SAJ grid meter (negative is export), while the
    // earlier feedback stage continues to prove the battery is discharging.
    const gridKw = finite(actual.gridKw);
    const gridMeasuredAtMs = finite(actual.gridMeasuredAtMs);
    const siteExportTargetKw = finite(transaction.siteExportTargetKw);
    if (gridKw === null || gridMeasuredAtMs === null || siteExportTargetKw === null) {
      return {ok: false, status: "feedback_target_grid_unavailable", batteryKw};
    }
    const gridAgeMs = nowMs - gridMeasuredAtMs;
    if (gridAgeMs < 0 || gridAgeMs > MAX_FEEDBACK_AGE_MS ||
        (gridMeasuredAtMs < issuedAtMs && transaction.writeStrategy !== "no_write")) {
      return {ok: false, status: "feedback_target_grid_stale", batteryKw, gridAgeMs};
    }
    expectedKw = siteExportTargetKw;
    observedKw = Math.max(0, -gridKw);
  } else if (transaction.batteryMode === "grid_charge") {
    expectedKw = targetKw;
    observedKw = Math.max(0, -batteryKw);
  } else if (transaction.batteryMode === "pv_charge") {
    const pvKw = finite(actual.pvKw);
    const loadKw = finite(actual.loadKw);
    if (pvKw === null || loadKw === null) return {ok: false, status: "feedback_target_solar_unavailable", batteryKw};
    // PV charging deliberately remains open at the inverter's full verified
    // rate. Confirm the solar actually available now, rather than treating the
    // optimiser's forecast target as a ceiling and rejecting beneficial extra
    // charge when irradiance is stronger than forecast.
    expectedKw = Math.min(MAX_CHARGE_KW, Math.max(0, pvKw - loadKw));
    observedKw = Math.max(0, -batteryKw);
    if (expectedKw < 0.2) return {ok: true, status: "confirmed_target_clipped_solar", batteryKw, clipped: true};
  } else if (transaction.batteryMode === "self_consume" && transaction.forceDischargeOn) {
    expectedKw = targetKw;
    observedKw = Math.max(0, batteryKw);
  } else if (transaction.batteryMode === "hold") {
    return {ok: true, status: "confirmed_no_forced_target", batteryKw};
  } else {
    return {ok: true, status: "confirmed_no_forced_target", batteryKw};
  }
  const toleranceKw = feedbackTolerance(expectedKw);
  const errorKw = Math.abs(observedKw - expectedKw);
  if (transaction.batteryMode === "export" && errorKw > toleranceKw) {
    // The owned discharge register and signed battery direction have already
    // been independently confirmed. Site export can diverge as load/PV move
    // after translation; replaying the identical full transaction cannot
    // correct that and creates a stop/start pulse. Report the deviation and
    // leave the next permitted 60-second planner update to change the rate.
    return {
      ok: true,
      status: "confirmed_export_rate_site_deviation",
      batteryKw,
      expectedKw,
      observedKw,
      errorKw,
      toleranceKw,
    };
  }
  return {
    ok: errorKw <= toleranceKw,
    status: errorKw <= toleranceKw ? "confirmed_target" : "feedback_target_mismatch",
    batteryKw,
    expectedKw,
    observedKw,
    errorKw,
    toleranceKw,
  };
}

function statusText(phase, transaction, detail = "") {
  // The audit service uses unescaped Mustache so Home Assistant stores the
  // controlled status text verbatim. Keep every dynamic component JSON-safe
  // and prevent an injected field delimiter from changing the status layout.
  const clean = (value) => String(value ?? "")
    .replace(/[\\"\u0000-\u001f]/g, "_")
    .replace(/\|/g, "/");
  const statusPhase = {
    confirmed: "feedback_confirmed",
    semantic_confirmed: "semantic_noop_confirmed",
  }[phase] || phase;
  const fields = [
    clean(statusPhase),
    clean(transaction?.planId || "unknown"),
    `mode=${clean(transaction?.batteryMode || "unknown")}`,
    `target=${Number(transaction?.targetKw || 0).toFixed(1)}kW`,
    `export=${clean(transaction?.pvExportCommand || "unknown")}`,
    `reserve=${transaction?.priorReservePct ?? "na"}->${transaction?.reservePct ?? "na"}%`,
  ];
  if (transaction?.acceptedAtMs) fields.push(`accepted_ms=${transaction.acceptedAtMs}`);
  if (transaction?.firstWriteAtMs) fields.push(`first_write_ms=${transaction.firstWriteAtMs}`);
  if (transaction?.appliedAtMs) fields.push(`applied_ms=${transaction.appliedAtMs}`);
  if (transaction?.confirmedAtMs) fields.push(`confirmed_ms=${transaction.confirmedAtMs}`);
  if (transaction?.reason) fields.push(`reason=${clean(transaction.reason)}`);
  if (detail) fields.push(clean(detail));
  return fields.join(" | ").slice(0, 250);
}

function nodeBundle(functions, body, constants = {}) {
  const constantSource = Object.entries(constants)
    .map(([key, value]) => `const ${key}=${JSON.stringify(value)};`)
    .join("\n");
  return [
    '"use strict";',
    constantSource,
    ...functions.map((fn) => fn.toString()),
    body.trim(),
  ].filter(Boolean).join("\n\n");
}

function buildNodeRedSources() {
  const sharedConstants = {
    MAX_DISCHARGE_KW,
    MAX_CHARGE_KW,
    DEFAULT_DISCHARGE_CAP_KW,
    MAX_SITE_EXPORT_TARGET_KW,
    MAX_TELEMETRY_AGE_MS,
    MAX_PRICE_AGE_MS,
    MAX_FUTURE_SKEW_MS,
    MAX_FEEDBACK_AGE_MS,
    EXPORT_RATE_MIN_INTERVAL_MS,
    EXPORT_RATE_DEADBAND_KW,
    EXPORT_RATE_DEADBAND_RATIO,
    NORMAL_EXPORT_LIMIT,
    ZERO_EXPORT_LIMIT,
    NORMAL_GRID_DISCHARGE_LIMIT,
    NORMAL_BATTERY_DISCHARGE_LIMIT,
    SAFE_RESERVE_FLOOR_PCT,
    BATTERY_MODES,
  };

  const validationFunctions = [
    finite, on, binaryOn, timestampMs, freshAge, clamp, forcePowerPercent, pvChargePowerLimitForKw,
    normalizedWholeReservePct, preservedReservePct, safeReservePct, sameTransactionIdentity,
    samePlanCommit, sameSemanticPhysicalCommand, exportRateOnlyEligible,
    expectedRegisterState, verifyRegisterState,
    conservativeCurtail, safeTransaction,
    rejected, sourceTimestampStatus, isNonActuatingSafeHold, validatePlan, statusText,
  ];
  const feedbackFunctions = [
    finite, binaryOn, timestampMs, freshAge, clamp, normalizedWholeReservePct,
    preservedReservePct, batteryDischargeLimitSensorToRegister,
    sameTransactionIdentity,
    feedbackTolerance, expectedRegisterState,
    verifyRegisterState, reserveTargetChanged, batteryDischargeLimitTargetChanged,
    evaluateDirectionFeedback, evaluateTargetFeedback, statusText,
  ];

  const readLiveState = nodeBundle([finite, binaryOn, timestampMs, batteryDischargeLimitSensorToRegister], `
const ha=global.get("homeassistant");
const states=ha?.homeAssistant?.states || ha?.states || {};
function entity(id){return states[id]||{};}
function raw(id){return entity(id).state;}
function measuredAt(id){const value=entity(id);for(const candidate of [value.last_reported,value.last_updated]){const parsed=timestampMs(candidate);if(parsed!==null)return parsed;}return null;}
function powerKw(id){const value=finite(raw(id));if(value===null)return null;const unit=String(entity(id).attributes?.unit_of_measurement||"").trim().toLowerCase();if(unit==="w")return value/1000;if(unit==="kw")return value;if(unit==="mw")return value*1000;return null;}
const preferredPv=entity("sensor.saj_pv_power");
const pvEntity=preferredPv.state!==undefined?"sensor.saj_pv_power":"sensor.pv_power_mqtt_abs";
msg.planEntity=entity("sensor.energy_optimizer_plan");
msg.mode=raw("input_select.energy_optimizer_mode");
msg.rolloutApproved=raw("input_boolean.energy_optimizer_rollout_approved");
msg.batteryControl=raw("input_boolean.energy_optimizer_battery_control");
msg.manualOverride=raw("input_boolean.energy_optimizer_manual_override");
msg.soc=raw("sensor.saj_battery_1_soc");
msg.socHeartbeatMeasuredAtMs=finite(raw("sensor.saj_battery_power"))===null?null:measuredAt("sensor.saj_battery_power");
msg.minSocPct=raw("sensor.saj_battery_discharge_soc_lower_limit");
msg.maxDischargeCapKw=raw("input_number.energy_optimizer_max_discharge_kw");
msg.pvPowerKw=powerKw(pvEntity);
msg.pvMeasuredAtMs=measuredAt(pvEntity);
msg.homeLoadKw=powerKw("sensor.saj_home_load");
msg.homeLoadMeasuredAtMs=measuredAt("sensor.saj_home_load");
msg.liveFitPrice=raw("sensor.amber_express_trader_sheena_street_feed_in_price");
msg.liveFitMeasuredAtMs=measuredAt("sensor.amber_express_trader_sheena_street_feed_in_price");
msg.liveImportPrice=raw("sensor.amber_express_trader_sheena_street_general_price");
msg.liveImportMeasuredAtMs=measuredAt("sensor.amber_express_trader_sheena_street_general_price");
msg.sunState=raw("sun.sun");
msg.reserveNumberPct=raw("number.saj_battery_on_grid_discharge_depth_input");
msg.reserveSensorPct=raw("sensor.saj_battery_on_grid_discharge_depth");
msg.reserveSensorMeasuredAtMs=measuredAt("sensor.saj_battery_on_grid_discharge_depth");
msg.reserveControlAvailable=finite(msg.reserveNumberPct)!==null&&finite(msg.reserveSensorPct)!==null&&msg.reserveSensorMeasuredAtMs!==null;
msg.batteryDischargeLimitNumber=raw("number.saj_battery_discharge_power_limit_input");
msg.batteryDischargeLimitSensor=batteryDischargeLimitSensorToRegister(raw("sensor.saj_battery_discharge_power_limit"),entity("sensor.saj_battery_discharge_power_limit").attributes?.unit_of_measurement);
msg.batteryDischargeLimitSensorMeasuredAtMs=measuredAt("sensor.saj_battery_discharge_power_limit");
msg.batteryDischargeLimitControlAvailable=finite(msg.batteryDischargeLimitNumber)!==null&&finite(msg.batteryDischargeLimitSensor)!==null&&msg.batteryDischargeLimitSensorMeasuredAtMs!==null;
msg.watchdogActual={
 reserveNumberPct:msg.reserveNumberPct,reserveSensorPct:msg.reserveSensorPct,
 batteryDischargeLimitNumber:msg.batteryDischargeLimitNumber,batteryDischargeLimitSensor:msg.batteryDischargeLimitSensor,
 antiRefluxMode:raw("number.saj_anti_reflux_mode_input"),exportLimit:raw("number.saj_export_limit_input"),gridMaxDischarge:raw("number.saj_grid_max_discharge_power_input"),
 exportHelperOn:binaryOn(raw("input_boolean.export_power")),pvChargeOn:binaryOn(raw("input_boolean.battery_pv_charge")),forceChargeOn:binaryOn(raw("input_boolean.battery_charge")),forceDischargeOn:binaryOn(raw("input_boolean.battery_discharge")),
 physicalChargeOn:binaryOn(raw("switch.saj_charging_control")),physicalDischargeOn:binaryOn(raw("switch.saj_discharging_control")),
 chargePowerPercent:raw("number.saj_charge1_power_percent_input"),dischargePowerPercent:raw("number.saj_discharge1_power_percent_input"),pvChargePowerLimit:raw("number.saj_battery_charge_power_limit_input")
};
msg.nowMs=Date.now();
return msg;`);

  const validateAndRequest = nodeBundle(validationFunctions, `
msg.lastAcceptedGeneratedAtMs=flow.get("energyOptimizerLastAcceptedGeneratedAtMs");
msg.lastAcceptedPlanId=flow.get("energyOptimizerLastAcceptedPlanId");
const result=validatePlan(msg);
const current=flow.get("energyOptimizerCurrentTransaction")||null;
const lastConfirmed=flow.get("energyOptimizerLastRegisterConfirmedTransaction")||null;
if(msg.topic==="watchdog"&&result.accepted&&current?.safeStop!==true&&
 current?.batteryMode===result.transaction.batteryMode&&samePlanCommit(current,result.transaction)){
 const registers=verifyRegisterState(current,msg.watchdogActual||{});
 if(registers.ok)return [null,null,null];
 const revision=Number(flow.get("energyOptimizerRevision")||0)+1;
 flow.set("energyOptimizerRevision",revision);
 const detail=registers.mismatches.join(",").slice(0,120);
 const transaction={
  ...current,revision,issuedAtMs:msg.nowMs??Date.now(),writeStrategy:"full",
  reason:"watchdog_drift_"+detail,reassertCount:0,
  priorReservePct:finite(msg.reserveSensorPct),reserveControlAvailable:msg.reserveControlAvailable===true,
  priorBatteryDischargeLimit:finite(msg.batteryDischargeLimitSensor),
  batteryDischargeLimitControlAvailable:msg.batteryDischargeLimitControlAvailable===true
 };
 flow.set("energyOptimizerCurrentTransaction",transaction);
 return [
  {...msg,transaction,payload:statusText("requested",transaction,"watchdog_physical_drift")},
  {transaction,optimizer:result},
  {...msg,transaction,payload:transaction.targetKw}
 ];
}
const revision=Number(flow.get("energyOptimizerRevision")||0)+1;
flow.set("energyOptimizerRevision",revision);
const transaction={...result.transaction,revision,issuedAtMs:msg.nowMs??Date.now()};
const lastApplied=flow.get("energyOptimizerLastAppliedTransaction")||null;
const applyingRevision=flow.get("energyOptimizerApplyingRevision");
// A new Amber settlement interval and every safety action remain immediate.
// Inside the same interval, hold the last physically applied export state for
// at least sixty seconds so the fast/full planner pair and PV/load noise cannot
// stop and restart export or chase every small correction.
const lastRateChange=finite(lastApplied?.exportRateChangedAtMs)??finite(lastApplied?.appliedAtMs);
const samePriceInterval=finite(lastApplied?.priceIntervalStartMs)!==null&&
 finite(lastApplied?.priceIntervalStartMs)===finite(transaction.priceIntervalStartMs);
const exportRateChanged=lastApplied?.batteryMode==="export"&&transaction.batteryMode==="export"&&
 Math.abs(Number(lastApplied.targetKw||0)-Number(transaction.targetKw||0))>0.05;
const exportRateDelta=Math.abs(Number(lastApplied?.targetKw||0)-Number(transaction.targetKw||0));
const exportRateDeadband=Math.max(EXPORT_RATE_DEADBAND_KW,
 Math.abs(Number(lastApplied?.targetKw||0))*EXPORT_RATE_DEADBAND_RATIO);
const exportRateInsideDeadband=exportRateChanged&&samePriceInterval&&
 exportRateDelta<exportRateDeadband;
if(exportRateChanged&&samePriceInterval&&lastRateChange!==null&&
 (transaction.issuedAtMs-lastRateChange<EXPORT_RATE_MIN_INTERVAL_MS||exportRateInsideDeadband)){
 transaction.deferredTargetKw=transaction.targetKw;
 transaction.targetKw=Number(lastApplied.targetKw||0);
 transaction.dischargeRateKw=Number(lastApplied.dischargeRateKw||transaction.targetKw);
 transaction.dischargePowerPercent=Number(lastApplied.dischargePowerPercent||0);
 // The physical battery rate remains the previously applied command, so its
 // feedback objective must remain the matching previously applied site target
 // too. Recomputing from a newer load/PV snapshot would describe a command we
 // deliberately did not send and can trigger a false reassertion.
 transaction.siteExportTargetKw=Number(lastApplied.siteExportTargetKw||0);
 transaction.reason=exportRateInsideDeadband?
  "accepted_export_rate_held_60s_deadband":"accepted_export_rate_held_60s";
}
const exportStopChanged=lastApplied?.batteryMode==="export"&&
 ["hold","self_consume"].includes(transaction.batteryMode)&&
 Number(lastApplied.targetKw||0)>0.05;
if(exportStopChanged&&samePriceInterval&&lastRateChange!==null&&
 transaction.issuedAtMs-lastRateChange<EXPORT_RATE_MIN_INTERVAL_MS&&
 transaction.safeStop!==true&&transaction.pvExportCommand!=="curtail"&&
 Number(transaction.liveFitPrice)>=0){
 transaction.deferredTargetKw=0;
 for(const key of [
  "batteryMode","targetKw","plannedBatteryTargetKw","siteExportTargetKw",
  "protectedSocPct","reservePct","batteryDischargeLimit","pvExportCommand",
  "antiRefluxMode","exportLimit","gridMaxDischarge","exportHelperOn",
  "pvChargeOn","forceChargeOn","forceDischargeOn","chargeRateKw",
  "dischargeRateKw","chargePowerPercent","dischargePowerPercent",
  "pvChargePowerLimit"
 ])transaction[key]=lastApplied[key];
 transaction.reason="accepted_export_stop_held_60s";
}
const exportStartChanged=lastApplied&&lastApplied.batteryMode!=="export"&&
 transaction.batteryMode==="export"&&Number(transaction.targetKw||0)>0.05;
if(exportStartChanged&&samePriceInterval&&lastRateChange!==null&&
 transaction.issuedAtMs-lastRateChange<EXPORT_RATE_MIN_INTERVAL_MS&&
 ["hold","self_consume"].includes(lastApplied.batteryMode)&&lastApplied.safeStop!==true){
 transaction.deferredTargetKw=transaction.targetKw;
 for(const key of [
  "batteryMode","targetKw","plannedBatteryTargetKw","siteExportTargetKw",
  "protectedSocPct","reservePct","batteryDischargeLimit","pvExportCommand",
  "antiRefluxMode","exportLimit","gridMaxDischarge","exportHelperOn",
  "pvChargeOn","forceChargeOn","forceDischargeOn","chargeRateKw",
  "dischargeRateKw","chargePowerPercent","dischargePowerPercent",
  "pvChargePowerLimit"
 ])transaction[key]=lastApplied[key];
 transaction.reason="accepted_export_start_held_60s";
}
const heldPhysicalExport=transaction.batteryMode==="export"&&
 String(transaction.reason||"").includes("held_60s")&&
 lastApplied?.batteryMode==="export"&&
 Math.abs(Number(lastApplied.targetKw||0)-Number(transaction.targetKw||0))<=0.05;
const semanticNoop=sameSemanticPhysicalCommand(
 transaction,lastConfirmed,lastApplied,applyingRevision,msg.watchdogActual||{}
);
// A held command is deliberately the already-applied physical export state.
// Rewriting the same discharge percentage is harmless and, critically, avoids
// the full transaction's stop/re-enable pulse while still advancing plan
// identity, deadline and feedback.
transaction.writeStrategy=semanticNoop?"semantic_noop":heldPhysicalExport?"no_write":
 exportRateOnlyEligible(transaction,lastConfirmed,lastApplied,applyingRevision)?
 "export_rate_only":"full";
flow.set("energyOptimizerCurrentTransaction",transaction);
if(result.accepted){
  flow.set("energyOptimizerLastAcceptedGeneratedAtMs",result.generatedAtMs);
  flow.set("energyOptimizerLastAcceptedPlanId",transaction.planId);
}
const requested={...msg,transaction,payload:statusText("requested",transaction,result.status)};
const deadline={transaction,optimizer:result};
return [requested,deadline,{...msg,transaction,payload:transaction.targetKw}];`, sharedConstants);

  const armDeadline = nodeBundle([finite], `
const transaction=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(transaction.revision!==current.revision||transaction.safeStop||finite(transaction.validUntilMs)===null){
  flow.set("energyOptimizerPlanDeadline",null);
  return {reset:true};
}
const now=Date.now();
flow.set("energyOptimizerPlanDeadline",{planId:transaction.planId,revision:transaction.revision,validUntilMs:transaction.validUntilMs});
return {deadlinePlanId:transaction.planId,deadlineRevision:transaction.revision,deadlineAtMs:transaction.validUntilMs,delay:Math.max(1,transaction.validUntilMs-now)};`);

  const expiry = nodeBundle([finite, clamp, normalizedWholeReservePct, preservedReservePct, statusText], `
const active=flow.get("energyOptimizerPlanDeadline")||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(active.planId!==msg.deadlinePlanId||active.revision!==msg.deadlineRevision)return [null,null,null];
const now=Date.now();
if(finite(msg.deadlineAtMs)!==null&&now<msg.deadlineAtMs)return [null,null,{...msg,delay:Math.max(1,msg.deadlineAtMs-now)}];
flow.set("energyOptimizerPlanDeadline",null);
const revision=Number(flow.get("energyOptimizerRevision")||0)+1;
flow.set("energyOptimizerRevision",revision);
const curtail=current.pvExportCommand==="curtail";
const transaction={...current,revision,planId:String(current.planId||"unknown"),batteryMode:"safe_stop",reason:"expired",safeStop:true,writeStrategy:"full",targetKw:0,siteExportTargetKw:0,priorReservePct:current.reservePct,reservePct:preservedReservePct(current.reservePct),priorBatteryDischargeLimit:current.batteryDischargeLimit,batteryDischargeLimit:1000,pvExportCommand:curtail?"curtail":"allow",antiRefluxMode:curtail?1:0,exportLimit:curtail?0:1100,exportHelperOn:!curtail,pvChargeOn:true,forceChargeOn:false,forceDischargeOn:false,chargeRateKw:30,dischargeRateKw:28,chargePowerPercent:0,dischargePowerPercent:0,pvChargePowerLimit:1000,issuedAtMs:now,validUntilMs:null,reassertCount:0,emergencyAttempted:true};
flow.set("energyOptimizerCurrentTransaction",transaction);
return [{transaction,payload:statusText("failed",transaction,"expired")},{transaction},null];`);

  const reserveRoute = `"use strict";\nreturn msg.transaction?.reserveControlAvailable?[msg,null]:[null,msg];`;
  const exportRoute = `"use strict";\nreturn msg.transaction?.pvExportCommand==="curtail"?[msg,null]:[null,msg];`;
  const pvRoute = `"use strict";\nreturn msg.transaction?.pvChargeOn?[msg,null]:[null,msg];`;
  const forcedRoute = `"use strict";\nconst tx=msg.transaction||{};return tx.forceChargeOn?[msg,null,null]:tx.forceDischargeOn?[null,msg,null]:[null,null,msg];`;
  const writeStrategyRoute = nodeBundle([finite, sameTransactionIdentity, exportRateOnlyEligible, heldExportNoWriteEligible], `
const tx=msg.transaction||{};
const confirmed=flow.get("energyOptimizerLastRegisterConfirmedTransaction")||null;
const applied=flow.get("energyOptimizerLastAppliedTransaction")||null;
const applying=flow.get("energyOptimizerApplyingRevision");
const noWrite=tx.writeStrategy==="no_write"&&heldExportNoWriteEligible(tx,applied,applying);
const fast=tx.writeStrategy==="export_rate_only"&&exportRateOnlyEligible(tx,confirmed,applied,applying);
const semantic=tx.writeStrategy==="semantic_noop"&&applying===tx.revision;
return semantic?[null,null,null,msg]:noWrite?[null,null,msg,null]:fast?[msg,null,null,null]:[null,{...msg,transaction:{...tx,writeStrategy:"full"}},null,null];`);

  const semanticConfirmed = nodeBundle([finite, sameTransactionIdentity, statusText], `
const tx=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(!sameTransactionIdentity(tx,current))return [null,null];
if(flow.get("energyOptimizerApplyingRevision")===tx.revision){
 flow.set("energyOptimizerApplyingRevision",null);
 flow.set("energyOptimizerApplyingStartedAtMs",null);
 flow.set("energyOptimizerApplyingTransaction",null);
}
const pending=flow.get("energyOptimizerPendingTransaction")||null;
flow.set("energyOptimizerPendingTransaction",null);
const previous=flow.get("energyOptimizerLastAppliedTransaction")||{};
const confirmedAtMs=Date.now();
const transaction={...tx,appliedAtMs:previous.appliedAtMs||confirmedAtMs,confirmedAtMs};
flow.set("energyOptimizerCurrentTransaction",transaction);
flow.set("energyOptimizerLastAppliedTransaction",transaction);
flow.set("energyOptimizerLastRegisterConfirmedTransaction",transaction);
flow.set("energyOptimizerLastConfirmedTransaction",transaction);
return [{transaction,payload:statusText("semantic_confirmed",transaction,"no_physical_write")},pending];`);

  const prepareParallelWrites = `"use strict";
const tx=msg.transaction||{};
const branches=["reserve","battery_discharge_limit","grid_max","export_policy","charge_percent","discharge_percent","pv_policy"];
const token=String(tx.revision)+":"+String(tx.issuedAtMs);
const transaction={...tx,writeToken:token};
flow.set("energyOptimizerApplyingTransaction",transaction);
flow.set("energyOptimizerWriteBarrier",{token,revision:tx.revision,issuedAtMs:tx.issuedAtMs,branches,done:{},failed:false,reasons:[]});
return branches.map((writeBranch)=>({...msg,transaction,writeToken:token,writeBranch}));`;

  const writeBarrier = nodeBundle([finite, sameTransactionIdentity, statusText], `
const tx=msg.transaction||{};
const barrier=flow.get("energyOptimizerWriteBarrier")||null;
const applying=flow.get("energyOptimizerApplyingRevision");
const token=String(msg.writeToken||tx.writeToken||"");
if(!barrier||barrier.token!==token||barrier.revision!==tx.revision||applying!==tx.revision){
 return [null,null,null,null];
}
const branch=String(msg.writeBranch||"");
if(!barrier.branches.includes(branch)){
 return [null,null,{transaction:tx,payload:statusText("failed",tx,"unknown_write_branch")},null];
}
if(barrier.done[branch])return [null,null,null,null];
if(msg.writeFailed){
 barrier.failed=true;
 const reason=String(msg.writeFailureReason||branch);
 if(!barrier.reasons.includes(reason))barrier.reasons.push(reason);
}
flow.set("energyOptimizerWriteBarrier",barrier);
// A red status is correlated and remembered, but it is not proof that the
// service call has returned. Only the branch's normal completion or catch may
// satisfy the barrier, preventing a late call from racing the safe fallback.
if(msg.writeStatusOnly)return [null,null,null,null];
barrier.done[branch]=true;
flow.set("energyOptimizerWriteBarrier",barrier);
if(Object.keys(barrier.done).length<barrier.branches.length)return [null,null,null,null];
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(!sameTransactionIdentity(current,tx)){
 const pending=flow.get("energyOptimizerPendingTransaction")||null;
 flow.set("energyOptimizerPendingTransaction",null);
 flow.set("energyOptimizerApplyingRevision",null);
 flow.set("energyOptimizerApplyingStartedAtMs",null);
 flow.set("energyOptimizerApplyingTransaction",null);
 flow.set("energyOptimizerWriteBarrier",null);
 return [null,null,null,pending];
}
if(barrier.failed){
 return [null,{transaction:tx,error:{message:"parallel_write_failed:"+barrier.reasons.join(",")}},null,null];
}
flow.set("energyOptimizerWriteBarrier",null);
return [{transaction:tx},null,null,null];`);

  const preForceCheck = nodeBundle([finite, sameTransactionIdentity, statusText], `
const tx=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
const applying=flow.get("energyOptimizerApplyingRevision");
if(sameTransactionIdentity(current,tx)&&applying===tx.revision)return [msg,null,null];
const pending=flow.get("energyOptimizerPendingTransaction")||null;
flow.set("energyOptimizerPendingTransaction",null);
if(applying===tx.revision){
 flow.set("energyOptimizerApplyingRevision",null);
 flow.set("energyOptimizerApplyingStartedAtMs",null);
 flow.set("energyOptimizerApplyingTransaction",null);
 flow.set("energyOptimizerWriteBarrier",null);
}
return [null,null,pending];`);

  const markParallelFailure = nodeBundle([statusText], `
const sourceId=String(msg.error?.source?.id||msg.status?.source?.id||"");
if(msg.topic==="node_status"&&msg.status?.fill!=="red")return [null,null];
const branchByNode={
 eop_reserve_route_002:"reserve",eop_export_route_002:"export_policy",eop_pv_route_002:"pv_policy",
 eop_set_reserve_002:"reserve",
 eop_set_battery_discharge_limit_002:"battery_discharge_limit",
 eop_set_grid_max_002:"grid_max",
 eop_set_anti_curtail_002:"export_policy",eop_set_export_zero_002:"export_policy",eop_export_helper_off_002:"export_policy",
 eop_set_export_normal_002:"export_policy",eop_set_anti_normal_002:"export_policy",eop_export_helper_on_002:"export_policy",
 eop_set_charge_percent_002:"charge_percent",eop_set_discharge_percent_002:"discharge_percent",
 eop_pv_charge_on_002:"pv_policy",eop_pv_charge_off_002:"pv_policy",eop_set_pv_limit_002:"pv_policy"
};
const barrier=flow.get("energyOptimizerWriteBarrier")||null;
const applyingTransaction=flow.get("energyOptimizerApplyingTransaction")||msg.transaction||{};
const branch=msg.writeBranch||branchByNode[sourceId];
if(barrier&&branch&&barrier.revision===applyingTransaction.revision){
 const reason=String(msg.error?.message||msg.status?.text||sourceId||"parallel_service_error").slice(0,80);
 return [{transaction:applyingTransaction,writeToken:barrier.token,writeBranch:branch,writeFailed:true,writeStatusOnly:msg.topic==="node_status",writeFailureReason:reason},null];
}
return [null,null];`);

  const applyQueue = nodeBundle([finite, sameTransactionIdentity, statusText], `
const tx=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(!sameTransactionIdentity(tx,current))return [null,null];
let applying=flow.get("energyOptimizerApplyingRevision");
const applyingStarted=Number(flow.get("energyOptimizerApplyingStartedAtMs")||0);
if(applying!==null&&applying!==undefined&&Date.now()-applyingStarted>30000){
 flow.set("energyOptimizerApplyingRevision",null);
 flow.set("energyOptimizerApplyingStartedAtMs",null);
 flow.set("energyOptimizerApplyingTransaction",null);
 flow.set("energyOptimizerPendingTransaction",null);
 flow.set("energyOptimizerWriteBarrier",null);
 applying=null;
}
if(applying!==null&&applying!==undefined){
 const pending=flow.get("energyOptimizerPendingTransaction");
 if(!pending||Number(tx.revision)>=Number(pending.transaction?.revision||-1))flow.set("energyOptimizerPendingTransaction",msg);
 return [null,{transaction:tx,payload:statusText("requested",tx,"queued_behind_atomic_transaction")}];
}
flow.set("energyOptimizerApplyingRevision",tx.revision);
flow.set("energyOptimizerApplyingStartedAtMs",Date.now());
const transaction={...tx,firstWriteAtMs:Date.now()};
flow.set("energyOptimizerApplyingTransaction",transaction);
flow.set("energyOptimizerCurrentTransaction",transaction);
return [{...msg,transaction},null];`);

  const applied = nodeBundle([finite, sameTransactionIdentity, statusText], `
const tx=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
if(flow.get("energyOptimizerApplyingRevision")===tx.revision){flow.set("energyOptimizerApplyingRevision",null);flow.set("energyOptimizerApplyingStartedAtMs",null);flow.set("energyOptimizerApplyingTransaction",null);flow.set("energyOptimizerWriteBarrier",null);}
const pending=flow.get("energyOptimizerPendingTransaction")||null;
flow.set("energyOptimizerPendingTransaction",null);
if(!sameTransactionIdentity(tx,current))return [null,null,pending];
const previous=flow.get("energyOptimizerLastAppliedTransaction")||null;
const appliedAtMs=Date.now();
const previousExportKw=previous?.batteryMode==="export"?Number(previous.targetKw||0):0;
const appliedExportKw=tx.batteryMode==="export"?Number(tx.targetKw||0):0;
const sameExportRate=previous&&Math.abs(previousExportKw-appliedExportKw)<=0.05;
const transaction={
 ...tx,
 appliedAtMs,
 exportRateChangedAtMs:sameExportRate?
  (finite(previous.exportRateChangedAtMs)??finite(previous.appliedAtMs)??appliedAtMs):
  appliedAtMs
};
flow.set("energyOptimizerCurrentTransaction",transaction);
if(transaction.reserveControlAvailable!==true)return [{transaction,payload:statusText("failed",transaction,"reserve_control_unavailable")},null,pending];
if(transaction.batteryDischargeLimitControlAvailable!==true)return [{transaction,payload:statusText("failed",transaction,"battery_discharge_limit_unavailable")},null,pending];
flow.set("energyOptimizerLastAppliedTransaction",transaction);
return [{transaction,payload:statusText("applied",transaction)},{transaction},pending];`);

  const feedbackPrelude = `
const tx=msg.transaction||{};
const current=flow.get("energyOptimizerCurrentTransaction")||{};
// Delayed observations are intentionally asynchronous. A superseded observer
// is silent: it must never replace the status of, reassert, or safe-stop a
// newer physical command.
if(!sameTransactionIdentity(tx,current))return [null,null,null,null];
const ha=global.get("homeassistant");
const states=ha?.homeAssistant?.states||ha?.states||{};
function entity(id){return states[id]||{};}
function raw(id){return entity(id).state;}
function measuredAt(id){const value=entity(id);for(const candidate of [value.last_reported,value.last_updated]){const parsed=timestampMs(candidate);if(parsed!==null)return parsed;}return null;}
function powerKw(id){const value=finite(raw(id));if(value===null)return null;const unit=String(entity(id).attributes?.unit_of_measurement||"").trim().toLowerCase();if(unit==="w")return value/1000;if(unit==="kw")return value;if(unit==="mw")return value*1000;return null;}
const actual={
 reserveNumberPct:raw("number.saj_battery_on_grid_discharge_depth_input"),reserveSensorPct:raw("sensor.saj_battery_on_grid_discharge_depth"),reserveSensorMeasuredAtMs:measuredAt("sensor.saj_battery_on_grid_discharge_depth"),
 batteryDischargeLimitNumber:raw("number.saj_battery_discharge_power_limit_input"),batteryDischargeLimitSensor:batteryDischargeLimitSensorToRegister(raw("sensor.saj_battery_discharge_power_limit"),entity("sensor.saj_battery_discharge_power_limit").attributes?.unit_of_measurement),batteryDischargeLimitSensorMeasuredAtMs:measuredAt("sensor.saj_battery_discharge_power_limit"),
 antiRefluxMode:raw("number.saj_anti_reflux_mode_input"),exportLimit:raw("number.saj_export_limit_input"),gridMaxDischarge:raw("number.saj_grid_max_discharge_power_input"),
 exportHelperOn:binaryOn(raw("input_boolean.export_power")),pvChargeOn:binaryOn(raw("input_boolean.battery_pv_charge")),forceChargeOn:binaryOn(raw("input_boolean.battery_charge")),forceDischargeOn:binaryOn(raw("input_boolean.battery_discharge")),
 physicalChargeOn:binaryOn(raw("switch.saj_charging_control")),physicalDischargeOn:binaryOn(raw("switch.saj_discharging_control")),
 chargePowerPercent:raw("number.saj_charge1_power_percent_input"),dischargePowerPercent:raw("number.saj_discharge1_power_percent_input"),pvChargePowerLimit:raw("number.saj_battery_charge_power_limit_input"),
 batteryKw:powerKw("sensor.saj_battery_power"),batteryMeasuredAtMs:measuredAt("sensor.saj_battery_power"),soc:finite(raw("sensor.saj_battery_1_soc")),
 gridKw:powerKw("sensor.saj_meter_a_real_power_total"),gridMeasuredAtMs:measuredAt("sensor.saj_meter_a_real_power_total"),
 pvKw:powerKw("sensor.saj_pv_power")??powerKw("sensor.pv_power_mqtt_abs"),loadKw:powerKw("sensor.saj_home_load"),nowMs:Date.now()
};`;

  const earlyFeedback = nodeBundle(feedbackFunctions, `${feedbackPrelude}
const registers=verifyRegisterState(tx,actual);
// The independent Modbus reserve sensor can trail its optimistic number
// entity by one slow-coordinator poll. Final confirmation below still
// requires the physical sensor to agree.
const earlyMismatches=registers.mismatches.filter((key)=>!["reserveSensorPct","batteryDischargeLimitSensor"].includes(key));
const earlyRegistersOk=earlyMismatches.length===0;
const direction=evaluateDirectionFeedback(tx,actual);
if(earlyRegistersOk&&direction.ok){
 const detail="battery="+(direction.batteryKw===null?"na":direction.batteryKw.toFixed(2)+"kW");
 const audit={transaction:tx,payload:statusText("confirmed_direction",tx,detail)};
 return [audit,null,{transaction:tx},null];
}
const detail=!earlyRegistersOk?"registers="+earlyMismatches.join(","):direction.status;
if(Number(tx.reassertCount||0)<1){
 const transaction={...tx,writeStrategy:"full",reassertCount:Number(tx.reassertCount||0)+1,issuedAtMs:Date.now(),reason:"reassert_"+detail};
 flow.set("energyOptimizerCurrentTransaction",transaction);
 return [{transaction,payload:statusText("requested",transaction,detail)},{transaction},null,null];
}
const revision=Number(flow.get("energyOptimizerRevision")||0)+1;flow.set("energyOptimizerRevision",revision);
const transaction={...tx,revision,batteryMode:"safe_stop",reason:"feedback_failed_"+detail,safeStop:true,writeStrategy:"full",targetKw:0,priorReservePct:tx.reservePct,reservePct:preservedReservePct(tx.reservePct),priorBatteryDischargeLimit:tx.batteryDischargeLimit,batteryDischargeLimit:1000,pvExportCommand:tx.pvExportCommand==="curtail"?"curtail":"allow",antiRefluxMode:tx.pvExportCommand==="curtail"?1:0,exportLimit:tx.pvExportCommand==="curtail"?0:1100,exportHelperOn:tx.pvExportCommand!=="curtail",pvChargeOn:true,forceChargeOn:false,forceDischargeOn:false,chargeRateKw:30,dischargeRateKw:28,chargePowerPercent:0,dischargePowerPercent:0,pvChargePowerLimit:1000,issuedAtMs:Date.now(),validUntilMs:null,reassertCount:1,emergencyAttempted:true};
flow.set("energyOptimizerCurrentTransaction",transaction);
return [{transaction,payload:statusText("failed",tx,detail)},null,null,{transaction}];`, sharedConstants);

  const targetFeedback = nodeBundle(feedbackFunctions, `${feedbackPrelude}
const registers=verifyRegisterState(tx,actual);
const reserveReadAt=finite(actual.reserveSensorMeasuredAtMs);
const reserveChanged=reserveTargetChanged(tx);
if(tx.reserveControlAvailable===true&&reserveChanged&&(reserveReadAt===null||reserveReadAt<finite(tx.issuedAtMs)||actual.nowMs-reserveReadAt>MAX_FEEDBACK_AGE_MS)){
 registers.ok=false;
 if(!registers.mismatches.includes("reserveSensorFresh"))registers.mismatches.push("reserveSensorFresh");
}
const dischargeLimitReadAt=finite(actual.batteryDischargeLimitSensorMeasuredAtMs);
const dischargeLimitChanged=batteryDischargeLimitTargetChanged(tx);
if(tx.batteryDischargeLimitControlAvailable===true&&dischargeLimitChanged&&(dischargeLimitReadAt===null||dischargeLimitReadAt<finite(tx.issuedAtMs)||actual.nowMs-dischargeLimitReadAt>MAX_FEEDBACK_AGE_MS)){
 registers.ok=false;
 if(!registers.mismatches.includes("batteryDischargeLimitSensorFresh"))registers.mismatches.push("batteryDischargeLimitSensorFresh");
}
const result=registers.ok?evaluateTargetFeedback(tx,actual):{ok:false,status:"feedback_register_mismatch"};
const detail=!registers.ok?"registers="+registers.mismatches.join(","):result.expectedKw===undefined?result.status:"expected="+result.expectedKw.toFixed(2)+" observed="+result.observedKw.toFixed(2)+" tol="+result.toleranceKw.toFixed(2);
if(registers.ok&&result.ok){
 const transaction={...tx,confirmedAtMs:Date.now()};
 flow.set("energyOptimizerCurrentTransaction",transaction);
 flow.set("energyOptimizerLastRegisterConfirmedTransaction",transaction);
 flow.set("energyOptimizerLastConfirmedTransaction",transaction);
 flow.set("energyOptimizerLastAppliedTransaction",transaction);
 return [{transaction,payload:statusText("confirmed",transaction,detail)},null,null,null];
}
if(Number(tx.reassertCount||0)<1){
 const transaction={...tx,writeStrategy:"full",reassertCount:1,issuedAtMs:Date.now(),reason:"reassert_target"};
 flow.set("energyOptimizerCurrentTransaction",transaction);
 return [{transaction,payload:statusText("requested",transaction,detail)},{transaction},null,null];
}
const revision=Number(flow.get("energyOptimizerRevision")||0)+1;flow.set("energyOptimizerRevision",revision);
const transaction={...tx,revision,batteryMode:"safe_stop",reason:"target_failed",safeStop:true,writeStrategy:"full",targetKw:0,priorReservePct:tx.reservePct,reservePct:preservedReservePct(tx.reservePct),priorBatteryDischargeLimit:tx.batteryDischargeLimit,batteryDischargeLimit:1000,pvExportCommand:tx.pvExportCommand==="curtail"?"curtail":"allow",antiRefluxMode:tx.pvExportCommand==="curtail"?1:0,exportLimit:tx.pvExportCommand==="curtail"?0:1100,exportHelperOn:tx.pvExportCommand!=="curtail",pvChargeOn:true,forceChargeOn:false,forceDischargeOn:false,chargeRateKw:30,dischargeRateKw:28,chargePowerPercent:0,dischargePowerPercent:0,pvChargePowerLimit:1000,issuedAtMs:Date.now(),validUntilMs:null,reassertCount:1,emergencyAttempted:true};
flow.set("energyOptimizerCurrentTransaction",transaction);
return [{transaction:tx,payload:statusText("failed",tx,detail)},null,null,{transaction}];`, sharedConstants);

const serviceFailure = nodeBundle([finite, clamp, normalizedWholeReservePct, preservedReservePct, sameTransactionIdentity, statusText], `
const status=msg.status||{};
if(msg.topic==="node_status"&&status.fill!=="red")return [null,null,null];
const current=flow.get("energyOptimizerCurrentTransaction")||msg.transaction||{};
const applying=flow.get("energyOptimizerApplyingRevision");
const transactionInFlight=flow.get("energyOptimizerApplyingTransaction")||null;
const failed=msg.transaction||transactionInFlight||current;
const source=msg.error?.message||status.text||"actuator_service_error";
const audit={transaction:failed,payload:statusText("failed",failed,String(source).slice(0,80))};
if(msg.topic==="node_status"&&(applying===null||applying===undefined))return [null,null,null];
if(finite(failed.revision)!==null&&applying!==null&&applying!==undefined&&failed.revision!==applying)return [null,null,null];
if(!sameTransactionIdentity(failed,current)){
 const pending=flow.get("energyOptimizerPendingTransaction")||null;
 if(applying===failed.revision){flow.set("energyOptimizerApplyingRevision",null);flow.set("energyOptimizerApplyingStartedAtMs",null);flow.set("energyOptimizerApplyingTransaction",null);flow.set("energyOptimizerWriteBarrier",null);}
 flow.set("energyOptimizerPendingTransaction",null);
 return [null,null,pending];
}
if(failed.emergencyAttempted){
 if(applying===failed.revision){flow.set("energyOptimizerApplyingRevision",null);flow.set("energyOptimizerApplyingStartedAtMs",null);flow.set("energyOptimizerApplyingTransaction",null);flow.set("energyOptimizerWriteBarrier",null);}
 return [audit,null,null];
}
const revision=Number(flow.get("energyOptimizerRevision")||0)+1;flow.set("energyOptimizerRevision",revision);
const curtail=failed.pvExportCommand==="curtail";
const transaction={...failed,revision,batteryMode:"safe_stop",reason:"actuator_error",safeStop:true,writeStrategy:"full",targetKw:0,priorReservePct:failed.reservePct,reservePct:preservedReservePct(failed.reservePct),priorBatteryDischargeLimit:failed.batteryDischargeLimit,batteryDischargeLimit:1000,pvExportCommand:curtail?"curtail":"allow",antiRefluxMode:curtail?1:0,exportLimit:curtail?0:1100,exportHelperOn:!curtail,pvChargeOn:true,forceChargeOn:false,forceDischargeOn:false,chargeRateKw:30,dischargeRateKw:28,chargePowerPercent:0,dischargePowerPercent:0,pvChargePowerLimit:1000,issuedAtMs:Date.now(),validUntilMs:null,reassertCount:1,emergencyAttempted:true};
flow.set("energyOptimizerCurrentTransaction",transaction);
flow.set("energyOptimizerApplyingRevision",null);
flow.set("energyOptimizerApplyingStartedAtMs",null);
flow.set("energyOptimizerApplyingTransaction",null);
flow.set("energyOptimizerWriteBarrier",null);
flow.set("energyOptimizerPendingTransaction",null);
return [audit,{transaction},null];`);

  return {
    readLiveState,
    validateAndRequest,
    armDeadline,
    expiry,
    reserveRoute,
    exportRoute,
    pvRoute,
    forcedRoute,
    writeStrategyRoute,
    semanticConfirmed,
    prepareParallelWrites,
    writeBarrier,
    preForceCheck,
    markParallelFailure,
    applyQueue,
    applied,
    earlyFeedback,
    targetFeedback,
    serviceFailure,
  };
}

module.exports = {
  BATTERY_MODES,
  batteryDischargeLimitSensorToRegister,
  binaryOn,
  DEFAULT_DISCHARGE_CAP_KW,
  MAX_CHARGE_KW,
  MAX_DISCHARGE_KW,
  MAX_PRICE_AGE_MS,
  MAX_SITE_EXPORT_TARGET_KW,
  MAX_TELEMETRY_AGE_MS,
  buildNodeRedSources,
  conservativeCurtail,
  evaluateDirectionFeedback,
  evaluateTargetFeedback,
    exportRateOnlyEligible,
    heldExportNoWriteEligible,
  expectedRegisterState,
  feedbackTolerance,
  finite,
  forcePowerPercent,
  isNonActuatingSafeHold,
  pvChargePowerLimitForKw,
  normalizedWholeReservePct,
  preservedReservePct,
  safeReservePct,
  samePlanCommit,
  sameSemanticPhysicalCommand,
  sameTransactionIdentity,
  batteryDischargeLimitTargetChanged,
  reserveTargetChanged,
  safeTransaction,
  statusText,
  validatePlan,
  verifyRegisterState,
};
