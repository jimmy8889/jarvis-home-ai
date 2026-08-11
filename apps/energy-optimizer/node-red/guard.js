"use strict";

function finite(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function on(value) {
  return String(value || "").toLowerCase() === "on";
}

function validatePlan(input) {
  const nowMs = input.nowMs || Date.now();
  const entity = input.planEntity || {};
  const plan = entity.attributes || {};
  const mode = String(input.mode || plan.mode || "shadow").toLowerCase();
  const armed = mode === "active" && on(input.batteryControl) && !on(input.manualOverride);
  const result = {
    actuate: false,
    safeStop: false,
    status: "shadow",
    action: "none",
    targetKw: 0,
    pvExportCommand: String(plan.pv_export_command || "allow"),
    planId: String(plan.plan_id || entity.state || "unknown"),
  };

  if (!armed) {
    result.status = on(input.manualOverride) ? "manual_override" : mode === "active" ? "battery_control_off" : mode;
    return result;
  }

  result.actuate = true;
  const validUntil = Date.parse(plan.valid_until || "");
  const generatedAt = Date.parse(plan.generated_at || "");
  if (plan.schema_version !== 1 || !Number.isFinite(validUntil) || !Number.isFinite(generatedAt)) {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_schema"};
  }
  if (nowMs > validUntil || nowMs - generatedAt > 10 * 60 * 1000 || generatedAt > nowMs + 60 * 1000) {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_stale"};
  }
  if (plan.actuation_allowed !== true || String(plan.mode).toLowerCase() !== "active") {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_not_allowed"};
  }
  if (!["allow", "curtail"].includes(result.pvExportCommand)) {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_pv_command"};
  }

  const target = finite(plan.battery_power_target_kw);
  const siteExport = finite(plan.site_export_target_kw);
  const soc = finite(input.soc);
  const configuredCap = finite(input.maxDischargeCapKw);
  if (target === null || siteExport === null || soc === null) {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_invalid_numeric"};
  }
  if (soc < 4.5 || soc > 100.5 || Math.abs(target) > 30.01 || siteExport < -0.01 || siteExport > 40) {
    return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_bounds"};
  }

  const action = String(plan.action || "idle");
  if (action === "discharge_export") {
    if (soc <= 6 || target <= 0 || siteExport <= 0) {
      return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_discharge_guard"};
    }
    const cap = Math.min(28, configuredCap === null ? 10 : Math.max(0, configuredCap));
    return {...result, status: "accepted_discharge", action, targetKw: Math.min(target, cap)};
  }
  if (action === "grid_charge") {
    if (soc >= 99 || target >= 0) {
      return {...result, safeStop: true, pvExportCommand: "allow", status: "rejected_charge_guard"};
    }
    return {...result, status: "accepted_grid_charge", action, targetKw: Math.min(30, Math.abs(target))};
  }

  return {...result, safeStop: true, status: `accepted_normal_${action}`, action};
}

if (typeof module !== "undefined") {
  module.exports = {validatePlan};
}
