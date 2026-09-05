"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {buildNodeRedSources} = require("./guard.js");

const TAB_ID = "eop_guard_tab_002";
const RETIRED_ACTUATOR_TAB_IDS = new Set(["eop_guard_tab_001"]);
const SERVER_ID = "srv_ha_001";

function functionNode(id, name, func, outputs, x, y, wires) {
  return {
    id,
    type: "function",
    z: TAB_ID,
    name,
    func,
    outputs,
    noerr: 0,
    initialize: "",
    finalize: "",
    libs: [],
    x,
    y,
    wires,
  };
}

function serviceNode(id, name, action, entityIds, data, x, y, wires) {
  return {
    id,
    type: "api-call-service",
    z: TAB_ID,
    name,
    server: SERVER_ID,
    version: 7,
    debugenabled: false,
    action,
    floorId: [],
    areaId: [],
    deviceId: [],
    entityId: entityIds,
    labelId: [],
    data,
    dataType: "json",
    mergeContext: "",
    mustacheAltTags: false,
    outputProperties: [],
    queue: "none",
    blockInputOverrides: false,
    domain: action.split(".")[0],
    service: action.split(".")[1],
    x,
    y,
    wires,
  };
}

function stateTrigger(id, name, entities, x, y, target = "eop_read_live_state_002") {
  return {
    id,
    type: "server-state-changed",
    z: TAB_ID,
    name,
    server: SERVER_ID,
    version: 6,
    outputs: 1,
    exposeAsEntityConfig: "",
    entities: {entity: entities, substring: [], regex: []},
    outputInitially: true,
    stateType: "str",
    ifState: "",
    ifStateType: "str",
    ifStateOperator: "is",
    outputOnlyOnStateChange: true,
    for: "0",
    forType: "num",
    forUnits: "minutes",
    ignorePrevStateNull: false,
    ignorePrevStateUnknown: true,
    ignorePrevStateUnavailable: true,
    ignoreCurrentStateUnknown: false,
    ignoreCurrentStateUnavailable: false,
    outputProperties: [{property: "payload", propertyType: "msg", value: "", valueType: "entityState"}],
    x,
    y,
    wires: [[target]],
  };
}

function delayNode(id, name, seconds, x, y, target) {
  return {
    id,
    type: "delay",
    z: TAB_ID,
    name,
    pauseType: "delay",
    timeout: String(seconds),
    timeoutUnits: "seconds",
    rate: "1",
    nbRateUnits: "1",
    rateUnits: "second",
    randomFirst: "1",
    randomLast: "5",
    randomUnits: "seconds",
    drop: false,
    allowrate: false,
    outputs: 1,
    x,
    y,
    wires: [[target]],
  };
}

function buildFlow() {
  const source = buildNodeRedSources();
  const serialServiceIds = [
    "eop_stop_charge_physical_002",
    "eop_stop_discharge_physical_002",
    "eop_stop_force_helpers_002",
    "eop_set_battery_discharge_limit_002",
    "eop_set_reserve_002",
    "eop_set_grid_max_002",
    "eop_set_anti_curtail_002",
    "eop_set_export_zero_002",
    "eop_export_helper_off_002",
    "eop_set_export_normal_002",
    "eop_set_anti_normal_002",
    "eop_export_helper_on_002",
    "eop_set_charge_percent_002",
    "eop_set_discharge_percent_002",
    "eop_pv_charge_on_002",
    "eop_pv_charge_off_002",
    "eop_set_pv_limit_002",
    "eop_fast_set_discharge_percent_002",
    "eop_force_charge_physical_002",
    "eop_force_charge_helper_002",
    "eop_force_discharge_physical_002",
    "eop_force_discharge_helper_002",
  ];
  const guardedFunctionIds = [
    "eop_read_live_state_002",
    "eop_validate_002",
    "eop_arm_deadline_002",
    "eop_plan_deadline_expired_002",
    "eop_apply_queue_002",
    "eop_write_strategy_route_002",
    "eop_semantic_confirmed_002",
    "eop_reserve_route_002",
    "eop_export_route_002",
    "eop_pv_route_002",
    "eop_pre_force_check_002",
    "eop_forced_route_002",
    "eop_applied_002",
    "eop_feedback_confirm_002",
    "eop_target_confirm_002",
  ];

  const flow = [
    {
      id: TAB_ID,
      type: "tab",
      label: "Energy Optimizer - Guarded SAJ Actuator v3",
      disabled: false,
      info: "Schema-v2 production actuator and sole SAJ writer. Every SAJ integration service is serialized in dependency order on one latest-wins lock, preventing concurrent Modbus transactions. A semantic command hash confirms physically unchanged plans without rewriting registers. Confirmed same-mode export-rate changes use the one-register fast path. Every mode keeps normal battery discharge and PV charging available; hot-water service rescue forces only the non-element household tranche so grid supplies the element. Inverter-native zero export is requested only for a fresh signed-negative FIT. Rejects, expiry, errors and persistent feedback mismatches run the complete fail-safe transaction while preserving the independent reserve floor.",
      env: [],
    },
    stateTrigger("eop_plan_changed_002", "New schema-v2 optimizer plan", ["sensor.energy_optimizer_plan"], 150, 80),
    stateTrigger("eop_control_changed_002", "Control or safety gate changed", [
      "input_select.energy_optimizer_mode",
      "input_boolean.energy_optimizer_rollout_approved",
      "input_boolean.energy_optimizer_battery_control",
      "input_boolean.energy_optimizer_manual_override",
    ], 170, 130),
    stateTrigger("eop_price_changed_002", "Negative FIT emergency edge", [
      "sensor.amber_express_trader_sheena_street_feed_in_price",
    ], 160, 180, "eop_negative_fit_edge_002"),
    functionNode(
      "eop_negative_fit_edge_002",
      "Pass only a signed-negative live FIT edge",
      "const fit=Number(msg.payload); return Number.isFinite(fit) && fit < 0 ? msg : null;",
      1,
      430,
      180,
      [["eop_read_live_state_002"]],
    ),
    {
      id: "eop_watchdog_002",
      type: "inject",
      z: TAB_ID,
      name: "Price/plan freshness watchdog",
      props: [{p: "payload"}, {p: "topic", vt: "str"}],
      repeat: "60",
      crontab: "",
      once: true,
      onceDelay: "5",
      topic: "watchdog",
      payload: "",
      payloadType: "date",
      x: 170,
      y: 230,
      wires: [["eop_read_live_state_002"]],
    },
    functionNode("eop_read_live_state_002", "Read guarded HA state and physical reserve", source.readLiveState, 1, 460, 150, [["eop_validate_002"]]),
    functionNode("eop_validate_002", "Validate v2 and request complete transaction", source.validateAndRequest, 3, 760, 150, [
      ["eop_audit_002"],
      ["eop_arm_deadline_002"],
      ["eop_apply_queue_002"],
    ]),
    functionNode("eop_arm_deadline_002", "Arm exact plan-expiry deadline", source.armDeadline, 1, 1050, 90, [["eop_plan_deadline_timer_002"]]),
    {
      id: "eop_plan_deadline_timer_002",
      type: "trigger",
      z: TAB_ID,
      name: "Replaceable valid-until one-shot",
      op1: "",
      op2: "",
      op1type: "nul",
      op2type: "pay",
      duration: "1",
      extend: true,
      overrideDelay: true,
      units: "ms",
      reset: "",
      bytopic: "all",
      topic: "topic",
      outputs: 1,
      x: 1330,
      y: 90,
      wires: [["eop_plan_deadline_expired_002"]],
    },
    functionNode("eop_plan_deadline_expired_002", "Safe-stop at exact plan expiry", source.expiry, 3, 1630, 90, [
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
      ["eop_plan_deadline_timer_002"],
    ]),
    serviceNode("eop_audit_002", "Publish requested/applied/confirmed/failed", "input_text.set_value", [
      "input_text.energy_optimizer_actuator_status",
    ], "{\"value\":\"{{{payload}}}\"}", 2140, 50, [[]]),

    functionNode("eop_apply_queue_002", "Lock physical write phase; latest pending wins", source.applyQueue, 2, 810, 250, [
      ["eop_write_strategy_route_002"],
      ["eop_audit_002"],
    ]),
    functionNode("eop_write_strategy_route_002", "Recheck semantic/fast/full write path", source.writeStrategyRoute, 4, 1060, 250, [
      ["eop_fast_set_discharge_percent_002"],
      ["eop_stop_charge_physical_002"],
      ["eop_applied_002"],
      ["eop_semantic_confirmed_002"],
    ]),
    functionNode("eop_semantic_confirmed_002", "Confirm unchanged physical command without writes", source.semanticConfirmed, 2, 1370, 120, [
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
    ]),
    serviceNode("eop_fast_set_discharge_percent_002", "FAST: update export percentage only", "number.set_value", [
      "number.saj_discharge1_power_percent_input",
    ], "{\"value\":{{transaction.dischargePowerPercent}}}", 1350, 190, [["eop_applied_002"]]),

    serviceNode("eop_stop_charge_physical_002", "1 Stop physical force charge", "switch.turn_off", [
      "switch.saj_charging_control",
    ], "{}", 1350, 250, [["eop_stop_discharge_physical_002"]]),
    serviceNode("eop_stop_discharge_physical_002", "2 Stop physical force discharge", "switch.turn_off", [
      "switch.saj_discharging_control",
    ], "{}", 1600, 250, [["eop_stop_force_helpers_002"]]),
    serviceNode("eop_stop_force_helpers_002", "3 Sync force helpers off", "input_boolean.turn_off", [
      "input_boolean.battery_charge",
      "input_boolean.battery_discharge",
    ], "{}", 1850, 250, [["eop_reserve_route_002"]]),
    functionNode("eop_reserve_route_002", "4 Reserve write available?", source.reserveRoute, 2, 2100, 250, [
      ["eop_set_reserve_002"],
      ["eop_set_battery_discharge_limit_002"],
    ]),
    serviceNode("eop_set_reserve_002", "5 Set protected reserve floor", "number.set_value", [
      "number.saj_battery_on_grid_discharge_depth_input",
    ], "{\"value\":{{transaction.reservePct}}}", 2350, 210, [["eop_set_battery_discharge_limit_002"]]),
    serviceNode("eop_set_battery_discharge_limit_002", "6 Set battery discharge allowance", "number.set_value", [
      "number.saj_battery_discharge_power_limit_input",
    ], "{\"value\":{{transaction.batteryDischargeLimit}}}", 2600, 250, [["eop_set_grid_max_002"]]),
    serviceNode("eop_set_grid_max_002", "7 Reassert grid max discharge", "number.set_value", [
      "number.saj_grid_max_discharge_power_input",
    ], "{\"value\":{{transaction.gridMaxDischarge}}}", 2850, 250, [["eop_export_route_002"]]),
    functionNode("eop_export_route_002", "8 Apply export policy in safe order", source.exportRoute, 2, 3100, 250, [
      ["eop_set_anti_curtail_002"],
      ["eop_set_export_normal_002"],
    ]),
    serviceNode("eop_set_anti_curtail_002", "9 Curtail: anti-reflux first", "number.set_value", [
      "number.saj_anti_reflux_mode_input",
    ], "{\"value\":1}", 3350, 210, [["eop_set_export_zero_002"]]),
    serviceNode("eop_set_export_zero_002", "10 Curtail: set exact zero export", "number.set_value", [
      "number.saj_export_limit_input",
    ], "{\"value\":0}", 3600, 210, [["eop_export_helper_off_002"]]),
    serviceNode("eop_export_helper_off_002", "11 Curtail: sync export helper off", "input_boolean.turn_off", [
      "input_boolean.export_power",
    ], "{}", 3850, 210, [["eop_set_charge_percent_002"]]),
    serviceNode("eop_set_export_normal_002", "9 Allow: restore export limit first", "number.set_value", [
      "number.saj_export_limit_input",
    ], "{\"value\":1100}", 3350, 290, [["eop_set_anti_normal_002"]]),
    serviceNode("eop_set_anti_normal_002", "10 Allow: disable anti-reflux", "number.set_value", [
      "number.saj_anti_reflux_mode_input",
    ], "{\"value\":0}", 3600, 290, [["eop_export_helper_on_002"]]),
    serviceNode("eop_export_helper_on_002", "11 Allow: sync export helper on", "input_boolean.turn_on", [
      "input_boolean.export_power",
    ], "{}", 3850, 290, [["eop_set_charge_percent_002"]]),
    serviceNode("eop_set_charge_percent_002", "12 Set force-charge percentage", "number.set_value", [
      "number.saj_charge1_power_percent_input",
    ], "{\"value\":{{transaction.chargePowerPercent}}}", 4100, 250, [["eop_set_discharge_percent_002"]]),
    serviceNode("eop_set_discharge_percent_002", "13 Set force-discharge percentage", "number.set_value", [
      "number.saj_discharge1_power_percent_input",
    ], "{\"value\":{{transaction.dischargePowerPercent}}}", 4350, 250, [["eop_set_pv_limit_002"]]),
    serviceNode("eop_set_pv_limit_002", "14 Keep PV charging at full verified rate", "number.set_value", [
      "number.saj_battery_charge_power_limit_input",
    ], "{\"value\":{{transaction.pvChargePowerLimit}}}", 4600, 250, [["eop_pv_route_002"]]),
    functionNode("eop_pv_route_002", "15 Sync explicit PV charging policy", source.pvRoute, 2, 4850, 250, [
      ["eop_pv_charge_on_002"],
      ["eop_pv_charge_off_002"],
    ]),
    serviceNode("eop_pv_charge_on_002", "16 Allow PV battery charging", "input_boolean.turn_on", [
      "input_boolean.battery_pv_charge",
    ], "{}", 5100, 210, [["eop_pre_force_check_002"]]),
    serviceNode("eop_pv_charge_off_002", "16 Inhibit PV battery charging", "input_boolean.turn_off", [
      "input_boolean.battery_pv_charge",
    ], "{}", 5100, 290, [["eop_pre_force_check_002"]]),
    functionNode("eop_pre_force_check_002", "17 Recheck active revision before force enable", source.preForceCheck, 3, 5350, 250, [
      ["eop_forced_route_002"],
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
    ]),
    functionNode("eop_forced_route_002", "18 Enable at most one forced mode", source.forcedRoute, 3, 5600, 250, [
      ["eop_force_charge_physical_002"],
      ["eop_force_discharge_physical_002"],
      ["eop_applied_002"],
    ]),
    serviceNode("eop_force_charge_physical_002", "19 Enable physical grid charge", "switch.turn_on", [
      "switch.saj_charging_control",
    ], "{}", 5850, 210, [["eop_force_charge_helper_002"]]),
    serviceNode("eop_force_charge_helper_002", "20 Sync grid-charge helper", "input_boolean.turn_on", [
      "input_boolean.battery_charge",
    ], "{}", 6100, 210, [["eop_applied_002"]]),
    serviceNode("eop_force_discharge_physical_002", "19 Enable physical discharge", "switch.turn_on", [
      "switch.saj_discharging_control",
    ], "{}", 5850, 290, [["eop_force_discharge_helper_002"]]),
    serviceNode("eop_force_discharge_helper_002", "20 Sync discharge helper", "input_boolean.turn_on", [
      "input_boolean.battery_discharge",
    ], "{}", 6100, 290, [["eop_applied_002"]]),
    functionNode("eop_applied_002", "Release write lock after final serial service", source.applied, 3, 6350, 250, [
      ["eop_audit_002"],
      ["eop_feedback_delay_002"],
      ["eop_apply_queue_002"],
    ]),
    delayNode("eop_feedback_delay_002", "Asynchronous SAJ poll/readback", 15, 4360, 290, "eop_feedback_confirm_002"),
    functionNode("eop_feedback_confirm_002", "Revision-scoped registers and direction", source.earlyFeedback, 4, 4630, 290, [
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
      ["eop_target_delay_002"],
      ["eop_apply_queue_002"],
    ]),
    delayNode("eop_target_delay_002", "Asynchronous settled target tracking", 20, 4900, 290, "eop_target_confirm_002"),
    functionNode("eop_target_confirm_002", "Final current-revision physical confirmation", source.targetFeedback, 4, 5180, 290, [
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
      [],
      ["eop_apply_queue_002"],
    ]),

    {
      id: "eop_serial_catch_002",
      type: "catch",
      z: TAB_ID,
      name: "Catch serial/write-controller failure",
      scope: [...serialServiceIds, ...guardedFunctionIds],
      uncaught: false,
      x: 760,
      y: 490,
      wires: [["eop_service_failure_002"]],
    },
    {
      id: "eop_serial_status_002",
      type: "status",
      z: TAB_ID,
      name: "Observe serial service status",
      scope: serialServiceIds,
      x: 750,
      y: 540,
      wires: [["eop_mark_serial_status_002"]],
    },
    {
      id: "eop_mark_serial_status_002",
      type: "change",
      z: TAB_ID,
      name: "Mark serial node-status event",
      rules: [{t: "set", p: "topic", pt: "msg", to: "node_status", tot: "str"}],
      action: "",
      property: "",
      from: "",
      to: "",
      reg: false,
      x: 1010,
      y: 540,
      wires: [["eop_service_failure_002"]],
    },
    functionNode("eop_service_failure_002", "Fail current revision and attempt one safe-stop", source.serviceFailure, 3, 1610, 490, [
      ["eop_audit_002"],
      ["eop_apply_queue_002"],
      ["eop_apply_queue_002"],
    ]),
  ];

  return flow;
}

function writeFlow(file = path.join(__dirname, "energy-optimizer-flow.json")) {
  fs.writeFileSync(file, `${JSON.stringify(buildFlow(), null, 2)}\n`);
}

function replaceTab(fullFlow) {
  if (!Array.isArray(fullFlow)) throw new TypeError("fullFlow must be a Node-RED flow array");
  const replacedTabIds = new Set([TAB_ID, ...RETIRED_ACTUATOR_TAB_IDS]);
  const unrelated = fullFlow.filter(
    (node) => !replacedTabIds.has(node.id) && !replacedTabIds.has(node.z),
  );
  return [...unrelated, ...buildFlow()];
}

if (require.main === module) writeFlow();

module.exports = {TAB_ID, RETIRED_ACTUATOR_TAB_IDS, buildFlow, replaceTab, writeFlow};
