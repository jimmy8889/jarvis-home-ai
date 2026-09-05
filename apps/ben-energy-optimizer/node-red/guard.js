"use strict";

const SITE_LIMIT_KW = 25;
const MAX_AGE_MS = 330000;

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function ageMs(state, nowMs) {
  const stamp = Date.parse(state && (state.last_reported || state.last_updated));
  return Number.isFinite(stamp) ? nowMs - stamp : Infinity;
}

function decide(input, nowMs = Date.now()) {
  const s = input.states || {};
  // Battery power is polled from the same inverter and is the heartbeat for
  // slowly-changing SOC, whose HA timestamp may remain unchanged for minutes.
  const telemetry = [s.pv, s.load, s.grid, s.battery];
  if (telemetry.some(item => !item || ageMs(item, nowMs) < -60000 || ageMs(item, nowMs) > MAX_AGE_MS)) {
    return {ok: false, fault: "telemetry_stale", action: "safe_stop"};
  }
  const soc = finite(s.soc.state), pv = finite(s.pv.state), load = finite(s.load.state), grid = finite(s.grid.state);
  if (soc === null || pv === null || load === null || grid === null || soc < 0 || soc > 100 || pv < 0 || pv > 100 || load < 0 || load > 100 || Math.abs(grid) > 100) {
    return {ok: false, fault: "telemetry_invalid", action: "safe_stop"};
  }
  if (input.alarm === true || input.available === false) return {ok: false, fault: "sigenergy_unavailable_or_alarm", action: "safe_stop"};
  const manualMode = input.manualMode || "Stopped";
  if (manualMode !== "Stopped") {
    const rate = finite(input.manualRate);
    if (!rate || rate < 0.1 || rate > SITE_LIMIT_KW) return {ok: false, fault: "manual_rate_invalid", action: "safe_stop", cancelManual: true};
    const siteGridKw = manualMode === "Import" ? rate : -rate;
    // Correct from the physical meter and present battery power. This remains
    // accurate when the inverter's reported site-load channel omits auxiliaries.
    const correctedBatteryKw = finite(s.battery.state) + grid - siteGridKw;
    // A manual export may never command charging, and a manual import may
    // never command discharging. The feedback loop can then increase power in
    // the requested direction without crossing through an opposing mode.
    const batteryKw = manualMode === "Export"
      ? Math.max(0, correctedBatteryKw)
      : Math.min(0, correctedBatteryKw);
    if (batteryKw > 0 && soc <= 5) return {ok: false, fault: "soc_floor", action: "safe_stop", cancelManual: true};
    if (batteryKw < 0 && soc >= 100) return {ok: false, fault: "soc_ceiling", action: "safe_stop", cancelManual: true};
    if (Math.abs(batteryKw) > SITE_LIMIT_KW) return {ok: false, fault: "manual_target_unachievable", action: "safe_stop", cancelManual: true};
    return command(batteryKw, siteGridKw, SITE_LIMIT_KW, true, input.sessionId || "manual");
  }
  const p = input.plan || {};
  const generated = Date.parse(p.generated_at), expires = Date.parse(p.valid_until);
  if (p.schema_version !== 1 || !p.plan_id || p.revision !== p.plan_id || !p.actuation_allowed || !Number.isFinite(generated) || !Number.isFinite(expires) || nowMs < generated - 60000 || nowMs >= expires || nowMs - generated > 600000) {
    return {ok: false, fault: "plan_invalid_stale_or_disarmed", action: "safe_stop"};
  }
  const batteryKw = finite(p.battery_power_target_kw), siteGridKw = finite(p.site_grid_target_kw), exportLimit = finite(p.grid_export_limit_kw);
  if (batteryKw === null || siteGridKw === null || exportLimit === null || Math.abs(batteryKw) > SITE_LIMIT_KW || Math.abs(siteGridKw) > SITE_LIMIT_KW || exportLimit < 0 || exportLimit > SITE_LIMIT_KW) {
    return {ok: false, fault: "plan_bounds", action: "safe_stop"};
  }
  if (batteryKw > 0 && soc <= Math.max(5, finite(p.dynamic_reserve_pct) || 5)) return {ok: false, fault: "reserve_reached", action: "safe_stop"};
  if (batteryKw < 0 && soc >= 100) return {ok: false, fault: "soc_ceiling", action: "safe_stop"};
  return command(batteryKw, siteGridKw, exportLimit, false, p.plan_id, p.valid_until);
}

function command(batteryKw, siteGridKw, exportLimitKw, manual, planId, validUntil = null) {
  let action = "self_consumption";
  if (batteryKw > 0.15) action = "discharge";
  else if (batteryKw < -0.15) action = "charge";
  else if (exportLimitKw === 0) action = "zero_export";
  return {ok: true, action, manual, planId, validUntil, batteryKw, siteGridKw, exportLimitKw};
}

function feedback(command, states, nowMs = Date.now()) {
  const battery = finite(states.battery && states.battery.state);
  const grid = finite(states.grid && states.grid.state);
  if (battery === null || grid === null || ageMs(states.battery, nowMs) > 60000 || ageMs(states.grid, nowMs) > 60000) return {ok: false, fault: "feedback_stale"};
  if (command.action === "discharge" && battery < 0.2) return {ok: false, fault: "feedback_wrong_discharge_direction"};
  if (command.action === "charge" && battery > -0.2) return {ok: false, fault: "feedback_wrong_charge_direction"};
  if (command.manual && Math.abs(grid - command.siteGridKw) > 0.5) {
    return {
      ok: false,
      fault: "feedback_grid_target_missed",
      correctedBatteryKw: finite(command.batteryKw) + grid - command.siteGridKw,
    };
  }
  return {ok: true, batteryKw: battery, gridKw: grid};
}

module.exports = {SITE_LIMIT_KW, decide, feedback};
