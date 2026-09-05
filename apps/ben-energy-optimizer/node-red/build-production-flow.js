"use strict";

const fs = require("node:fs");

const [currentPath, guardedPath, outputPath] = process.argv.slice(2);
if (!currentPath || !guardedPath || !outputPath) {
  throw new Error("usage: node build-production-flow.js CURRENT GUARDED OUTPUT");
}
const current = JSON.parse(fs.readFileSync(currentPath, "utf8"));
const guarded = JSON.parse(fs.readFileSync(guardedPath, "utf8"));
const byId = new Map(current.filter(node => node && node.id).map(node => [node.id, node]));
const wanted = new Set([
  "sig_read_tab_06", "siteagg3_inject_001", "siteagg3_fn_001",
  "siteagg3_soc_sensor", "siteagg3_batt_sensor", "siteagg3_pv_sensor",
  "siteagg3_load_sensor", "siteagg3_grid_sensor", "14e2775f5787677a",
]);
for (const node of current) if (node.z === "sig_read_tab_06") wanted.add(node.id);

function strings(value, result = []) {
  if (typeof value === "string") result.push(value);
  else if (Array.isArray(value)) for (const item of value) strings(item, result);
  else if (value && typeof value === "object") for (const item of Object.values(value)) strings(item, result);
  return result;
}

let changed = true;
while (changed) {
  changed = false;
  for (const id of [...wanted]) {
    const node = byId.get(id);
    if (!node) continue;
    for (const reference of strings(node)) {
      if (byId.has(reference) && !wanted.has(reference)) {
        wanted.add(reference);
        changed = true;
      }
    }
  }
}
const retained = current.filter(node => wanted.has(node.id) && node.id !== "siteagg3_tab_001");
const tab = retained.find(node => node.id === "sig_read_tab_06");
if (!tab) throw new Error("working Sigenergy telemetry tab not found");
tab.label = "Ben Sigenergy Telemetry Bridge";
tab.info = "Minimal five-register Modbus telemetry retained until native Sigenergy plant-sensor parity is physically proven.";
for (const node of retained) {
  if (node.id.startsWith("siteagg3_") && node.z === "siteagg3_tab_001") node.z = "sig_read_tab_06";
}
const aggregateInject = retained.find(node => node.id === "siteagg3_inject_001");
aggregateInject.name = "Publish canonical site sensors every 2s";
aggregateInject.wires = [["siteagg3_fn_001"]];
const aggregate = retained.find(node => node.id === "siteagg3_fn_001");
aggregate.name = "Publish Sigenergy canonical telemetry";
aggregate.func = aggregate.func.replace("const profile = normProfile(msg.inverter_profile);", "const profile = 'sigenergy';");
for (const node of retained) {
  if (node.type === "server" && node.id === "14e2775f5787677a") node.enableGlobalContextStore = true;
}
const guardedController = guarded.find(node => node.id === "ben_controller");
guardedController.func = guardedController.func.replace(
  "const p=pe?.attributes||{}",
  "const p=msg.plan||flow.get('latestPlan')||pe?.attributes||{}",
);
guardedController.func = guardedController.func.replace(
  "const a=[svc('switch.turn_on','switch.sigen_plant_remote_ems_controlled_by_home_assistant'),svc('number.set_value','number.sigen_plant_grid_export_limitation'",
  "const a=[svc('switch.turn_on','switch.sigen_plant_remote_ems_controlled_by_home_assistant'),svc('number.set_value','number.sigen_plant_ess_discharge_cut_off_state_of_charge',{value:5}),svc('number.set_value','number.sigen_plant_grid_export_limitation'",
);
guardedController.func = guardedController.func.replace(
  "function stop(reason,cancel=false){let fit=",
  "function stop(reason,cancel=false){flow.set('activeCommand',null);let fit=",
);
guardedController.func = guardedController.func.replace(
  "context.set('activeCommand',{kind,batt,targetGrid,manual:mode!=='Stopped',tag,issued:now});",
  "flow.set('activeCommand',{kind,batt,targetGrid,manual:mode!=='Stopped',tag,issued:now});",
);
guardedController.func = guardedController.func.replace(
  "batt=load-pv-targetGrid;tag='manual '+mode",
  "batt=bp+grid-targetGrid;batt=mode==='Export'?Math.max(0,batt):Math.min(0,batt);tag='manual '+mode",
);
guardedController.func = guardedController.func.replace(
  "if(ids.some((id,i)=>!fresh(id)||vals[i]===null))",
  "if(ids.some((id,i)=>i>0&&(!fresh(id)||vals[i]===null))||!fresh(ids[1])||vals[0]===null)",
);
const guardedFeedback = guarded.find(node => node.id === "ben_feedback");
guardedFeedback.func = guardedFeedback.func.replace(
  "const c=msg.command||{},b=n('sensor.site_battery_power_nr_4'),g=n('sensor.site_grid_power_nr_4');",
  "const c=msg.command||{},active=flow.get('activeCommand');if(!active||active.issued!==c.issued||active.tag!==c.tag||active.kind!==c.kind||active.manual!==c.manual)return [null,null,null];const b=n('sensor.site_battery_power_nr_4'),g=n('sensor.site_grid_power_nr_4');",
);
guardedFeedback.func = guardedFeedback.func.replace(
  "Math.abs(g-c.targetGrid)<=2",
  "Math.abs(g-c.targetGrid)<=0.5",
);
guardedFeedback.func = guardedFeedback.func.replace(
  "if((msg.attempt||0)<1){msg.attempt=1;return [null,msg,status('Feedback retry '+c.tag)];}",
  "if((msg.attempt||0)<1){msg.attempt=1;if(c.manual){let corrected=c.batt+g-c.targetGrid;corrected=c.tag==='manual Export'?Math.max(0,corrected):Math.min(0,corrected);if(!Number.isFinite(corrected)||Math.abs(corrected)>25){flow.set('activeCommand',null);return [[svc('input_boolean.turn_on','input_boolean.ben_manual_fault'),svc('input_select.select_option','input_select.ben_manual_mode',{option:'Stopped'})],null,status('SAFE manual correction out of bounds')];}c.batt=corrected;c.kind=corrected>0.15?'discharge':corrected<-0.15?'charge':'self';c.issued=Date.now();flow.set('activeCommand',c);msg.command=c;const a=c.kind==='discharge'?[svc('number.set_value','number.sigen_plant_ess_max_charging_limit',{value:0}),svc('number.set_value','number.sigen_plant_ess_max_discharging_limit',{value:Math.abs(corrected)}),svc('select.select_option','select.sigen_plant_remote_ems_control_mode',{option:'Command Discharging (ESS First)'})]:c.kind==='charge'?[svc('number.set_value','number.sigen_plant_ess_max_discharging_limit',{value:0}),svc('number.set_value','number.sigen_plant_ess_max_charging_limit',{value:Math.abs(corrected)}),svc('select.select_option','select.sigen_plant_remote_ems_control_mode',{option:'Command Charging (Grid First)'})]:[svc('number.set_value','number.sigen_plant_ess_max_charging_limit',{value:25}),svc('number.set_value','number.sigen_plant_ess_max_discharging_limit',{value:25}),svc('select.select_option','select.sigen_plant_remote_ems_control_mode',{option:'Maximum Self Consumption'})];return [a,msg,status('Feedback correcting '+c.tag+' to '+corrected.toFixed(2)+' kW')];}return [null,msg,status('Feedback retry '+c.tag)];}",
);
guardedFeedback.func = guardedFeedback.func.replace(
  "const a=[svc('number.set_value','number.sigen_plant_grid_export_limitation'",
  "flow.set('activeCommand',null);const a=[svc('number.set_value','number.sigen_plant_grid_export_limitation'",
);
const ids = new Set(retained.map(node => node.id));
for (const node of guarded) {
  if (ids.has(node.id)) throw new Error(`duplicate Node-RED id: ${node.id}`);
  ids.add(node.id);
}
fs.writeFileSync(outputPath, JSON.stringify([...retained, ...guarded], null, 2) + "\n");
