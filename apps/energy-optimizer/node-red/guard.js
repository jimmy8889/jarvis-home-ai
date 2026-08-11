"use strict";

const MAX_DISCHARGE_KW = 28;
const MAX_CHARGE_KW = 30;
const DEFAULT_DISCHARGE_CAP_KW = 28;
const RAMP_UP_STEP_KW = 14;

function finite(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "string" && (!value.trim() || ["unknown", "unavailable", "none", "null"].includes(value.trim().toLowerCase()))) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function on(value) {
  return String(value || "").toLowerCase() === "on";
}

function rejected(result, status) {
  return {
    ...result,
    actuate: false,
    safeStop: true,
    stopForced: true,
    status,
    action: "none",
    targetKw: 0,
    requestedTargetKw: 0,
    pvExportCommand: "allow",
  };
}

function validatePlan(input) {
  const nowMs = input.nowMs ?? Date.now();
  const entity = input.planEntity || {};
  const plan = entity.attributes || {};
  const mode = String(input.mode || plan.mode || "shadow").toLowerCase();
  const result = {
    actuate: false,
    safeStop: true,
    stopForced: true,
    status: "shadow",
    action: "none",
    targetKw: 0,
    requestedTargetKw: 0,
    plannedBatteryTargetKw: null,
    siteExportTargetKw: null,
    livePvKw: null,
    liveLoadKw: null,
    pvExportCommand: "allow",
    planId: String(plan.plan_id || entity.state || "unknown"),
  };

  // Every disarmed state is an explicit safe-stop request. This prevents a
  // previously latched SAJ forced mode surviving a mode/helper change.
  if (on(input.manualOverride)) {
    return {...result, status: "manual_override"};
  }
  if (mode !== "active") {
    return {...result, status: mode || "disabled"};
  }
  if (!on(input.rolloutApproved)) {
    return {...result, status: "rollout_not_approved"};
  }
  if (!on(input.batteryControl)) {
    return {...result, status: "battery_control_off"};
  }

  const validUntil = Date.parse(plan.valid_until || "");
  const generatedAt = Date.parse(plan.generated_at || "");
  if (plan.schema_version !== 1 || !Number.isFinite(validUntil) || !Number.isFinite(generatedAt)) {
    return rejected(result, "rejected_schema");
  }
  if (nowMs > validUntil || nowMs - generatedAt > 10 * 60 * 1000 || generatedAt > nowMs + 60 * 1000) {
    return rejected(result, "rejected_stale");
  }
  if (plan.actuation_allowed !== true || String(plan.mode).toLowerCase() !== "active") {
    return rejected(result, "rejected_not_allowed");
  }

  const pvExportCommand = String(plan.pv_export_command || "allow").toLowerCase();
  if (!["allow", "curtail"].includes(pvExportCommand)) {
    return rejected(result, "rejected_pv_command");
  }

  const target = finite(plan.battery_power_target_kw);
  const siteExport = finite(plan.site_export_target_kw);
  const soc = finite(input.soc);
  const inverterFloor = finite(input.minSocPct);
  const livePvKw = finite(input.pvPowerKw);
  const liveLoadKw = finite(input.homeLoadKw);
  if ([target, siteExport, soc, inverterFloor, livePvKw, liveLoadKw].some((value) => value === null)) {
    return rejected(result, "rejected_invalid_numeric");
  }

  const liveFloor = Math.max(5, inverterFloor);
  if (
    soc < liveFloor - 0.5 || soc > 100.5 ||
    inverterFloor < 5 || inverterFloor > 100 ||
    Math.abs(target) > MAX_CHARGE_KW + 0.01 ||
    siteExport < -0.01 || siteExport > 40 ||
    livePvKw < 0 || livePvKw > 100 || liveLoadKw < 0 || liveLoadKw > 100
  ) {
    return rejected(result, "rejected_bounds");
  }

  const action = String(plan.action || "idle").toLowerCase();
  const allowedActions = new Set(["discharge_export", "grid_charge", "curtail_pv", "self_consumption", "pv_charge", "idle"]);
  if (!allowedActions.has(action)) {
    return rejected(result, "rejected_conflicting_action");
  }

  const active = {
    ...result,
    actuate: true,
    safeStop: false,
    stopForced: false,
    action,
    plannedBatteryTargetKw: target,
    siteExportTargetKw: siteExport,
    livePvKw,
    liveLoadKw,
    pvExportCommand,
  };

  if (action === "discharge_export") {
    if (pvExportCommand !== "allow" || soc <= liveFloor + 1 || target <= 0 || target > MAX_DISCHARGE_KW + 0.01 || siteExport <= 0) {
      return rejected(active, "rejected_discharge_guard");
    }
    const configuredCap = finite(input.maxDischargeCapKw);
    const cap = Math.min(
      MAX_DISCHARGE_KW,
      configuredCap === null ? DEFAULT_DISCHARGE_CAP_KW : Math.max(0, configuredCap),
    );
    // A site export target is not a battery target. Supply the live household
    // load first, subtract live PV, then ask the battery only for the balance.
    const requiredBatteryKw = Math.max(0, siteExport + liveLoadKw - livePvKw);
    const requestedTargetKw = Math.min(requiredBatteryKw, cap);
    if (requestedTargetKw <= 0.05) {
      return {
        ...active,
        status: "accepted_discharge_pv_meets_target",
        stopForced: true,
        targetKw: 0,
        requestedTargetKw: 0,
      };
    }
    return {
      ...active,
      status: "accepted_discharge",
      targetKw: requestedTargetKw,
      requestedTargetKw,
    };
  }

  if (action === "grid_charge") {
    if (soc >= 99 || target >= 0) {
      return rejected(active, "rejected_charge_guard");
    }
    const requestedTargetKw = Math.min(MAX_CHARGE_KW, Math.abs(target));
    return {
      ...active,
      status: "accepted_grid_charge",
      targetKw: requestedTargetKw,
      requestedTargetKw,
    };
  }

  if (action === "curtail_pv" && pvExportCommand !== "curtail") {
    return rejected(active, "rejected_conflicting_action");
  }
  if (["self_consumption", "pv_charge", "idle"].includes(action) && pvExportCommand !== "allow") {
    return rejected(active, "rejected_conflicting_action");
  }

  return {
    ...active,
    stopForced: true,
    status: `accepted_normal_${action}`,
  };
}

// Ramp upward commands only. Reductions, rejections and stops take effect
// immediately; from rest a 28 kW request reaches 14 kW now and 28 kW on the
// next one-minute watchdog pass.
function rampTarget(previousKw, requestedKw, maxIncreaseKw = RAMP_UP_STEP_KW) {
  const previous = Math.max(0, finite(previousKw) ?? 0);
  const requested = Math.max(0, finite(requestedKw) ?? 0);
  const step = Math.max(0, finite(maxIncreaseKw) ?? RAMP_UP_STEP_KW);
  if (requested <= previous) return requested;
  return Math.min(requested, previous + step);
}

function evaluateFeedback(input) {
  const action = String(input.action || "");
  const targetKw = finite(input.targetKw);
  if (!["discharge_export", "grid_charge"].includes(action) || targetKw === null || targetKw <= 0) {
    return {ok: false, status: "feedback_invalid_command"};
  }

  const expectedDischarge = action === "discharge_export";
  const expectedMode = expectedDischarge ? on(input.dischargeMode) && !on(input.chargeMode) : on(input.chargeMode) && !on(input.dischargeMode);
  const currentSet = finite(expectedDischarge ? input.dischargeCurrentSet : input.chargeCurrentSet);
  if (currentSet === null) {
    return {ok: false, status: `feedback_unavailable_${expectedDischarge ? "discharge" : "charge"}`};
  }
  if (!expectedMode || currentSet <= 0) {
    return {ok: false, status: `feedback_mismatch_${expectedDischarge ? "discharge" : "charge"}`};
  }
  return {
    ok: true,
    status: `feedback_confirmed_${expectedDischarge ? "discharge" : "charge"}`,
    currentSet,
  };
}

if (typeof module !== "undefined") {
  module.exports = {
    DEFAULT_DISCHARGE_CAP_KW,
    MAX_CHARGE_KW,
    MAX_DISCHARGE_KW,
    RAMP_UP_STEP_KW,
    evaluateFeedback,
    finite,
    rampTarget,
    validatePlan,
  };
}
