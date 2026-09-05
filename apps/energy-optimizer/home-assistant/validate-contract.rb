# frozen_string_literal: true

# Static contract validation for the version-controlled Home Assistant exports.
# Uses Ruby's standard-library YAML parser so it can run on a stock macOS host:
#
#   ruby apps/energy-optimizer/home-assistant/validate-contract.rb

require "date"
require "yaml"

ROOT = File.expand_path(__dir__)

def fail_contract(message)
  warn "FAIL: #{message}"
  exit 1
end

def assert_contract(condition, message)
  fail_contract(message) unless condition
end

def read(name)
  File.read(File.join(ROOT, name))
end

def parse(name)
  YAML.safe_load(
    read(name),
    permitted_classes: [Date, Time],
    aliases: true,
    filename: name
  )
rescue Psych::Exception => error
  fail_contract("#{name} is not valid YAML: #{error.message}")
end

yaml_files = Dir[File.join(ROOT, "*.yaml")].sort
yaml_files.each do |path|
  name = File.basename(path)
  parsed = parse(name)
  assert_contract(!parsed.nil?, "#{name} parsed as an empty document")
end

automation_files = %w[
  energy-optimizer-auto-resume.yaml
  energy-optimizer-ev-auto-actuator.yaml
  energy-optimizer-ev-requirement-date.yaml
  energy-optimizer-hot-water-actuator.yaml
  energy-optimizer-notifications.yaml
  energy-optimizer-retired-automations.yaml
  energy-optimizer-saj-curtailment.yaml
]

automations = automation_files.flat_map do |name|
  document = parse(name)
  assert_contract(document.is_a?(Array), "#{name} must be an automation list")
  document
end

ids = automations.map { |item| item.fetch("id") }
duplicates = ids.group_by(&:itself).select { |_id, items| items.length > 1 }.keys
assert_contract(duplicates.empty?, "duplicate automation IDs: #{duplicates.join(', ')}")

helpers = parse("energy-optimizer-helpers-package.yaml")
assert_contract(helpers.is_a?(Hash), "helper package must be a mapping")
booleans = helpers.fetch("input_boolean")
%w[
  energy_optimizer_production_expected
  energy_optimizer_notify_battery_selling_active
  energy_optimizer_notify_ev_charging_active
  energy_optimizer_notify_hot_water_active
  energy_optimizer_notify_hot_water_complete_sent
  energy_optimizer_alert_degraded_active
  energy_optimizer_alert_saj_contract_active
].each do |helper_id|
  helper = booleans.fetch(helper_id)
  assert_contract(!helper.key?("initial"), "#{helper_id} must persist across restart")
end

max_discharge = helpers.fetch("input_number").fetch("energy_optimizer_max_discharge_kw")
assert_contract(!max_discharge.key?("initial"), "28 kW limit helper must restore across restart")
assert_contract(max_discharge.fetch("max") == 28, "full production discharge limit must be 28 kW")
minimum_sell = helpers.fetch("input_number").fetch("energy_optimizer_min_sell_price_c_per_kwh")
assert_contract(minimum_sell.fetch("min") == 8, "minimum sell helper must not undercut 8c battery wear")
assert_contract(minimum_sell.fetch("max") == 200, "minimum sell helper must support Amber spike pricing")
assert_contract(minimum_sell.fetch("unit_of_measurement") == "¢/kWh", "minimum sell helper must use dashboard cents/kWh")

helpers_raw = read("energy-optimizer-helpers-package.yaml")
%w[
  energy_optimizer_saj_control_contract_ready
  energy_optimizer_actuator_current_plan
  default_entity_id: binary_sensor.hot_water_heating_active
  source_unit
  number.saj_anti_reflux_mode_input
  number.saj_export_limit_input
  number.saj_grid_max_discharge_power_input
  number.saj_battery_on_grid_discharge_depth_input
  sensor.saj_battery_on_grid_discharge_depth
  switch.saj_charging_control
  switch.saj_discharging_control
  number.saj_charge1_power_percent_input
  number.saj_discharge1_power_percent_input
  number.saj_battery_charge_power_limit_input
  number.saj_battery_discharge_power_limit_input
  sensor.saj_battery_discharge_power_limit
  SAJ_BatDischargePower
  sensor.saj_pv_power
  last_reported
].each do |token|
  assert_contract(helpers_raw.include?(token), "helper safety contract missing #{token}")
end
assert_contract(!helpers_raw.include?("sensor.pv_power_mqtt_abs"), "MQTT PV must not gate overnight readiness")
assert_contract(!helpers_raw.include?("startswith('accepted_')"), "readiness must not accept requested-only actuation")
assert_contract(
  helpers_raw.include?("unique_id: hot_water_heating_active"),
  "hot-water activity must reuse the live entity registry identity"
)
assert_contract(
  !helpers_raw.include?("unique_id: energy_optimizer_hot_water_heating_active"),
  "hot-water activity must not allocate a competing template identity"
)
assert_contract(
  !helpers_raw.match?(/saj_battery_1_soc[^\n]*last_(?:updated|reported)/),
  "unchanged SOC timestamps must not gate telemetry freshness"
)

history_stats = helpers.fetch("sensor")
confirmed_runtime = history_stats.find do |item|
  item["unique_id"] == "energy_optimizer_hot_water_confirmed_runtime_today"
end
assert_contract(!confirmed_runtime.nil?, "confirmed hot-water history_stats sensor is missing")
assert_contract(
  confirmed_runtime["entity_id"] == "binary_sensor.hot_water_heating_active",
  "confirmed runtime must count physical element activity"
)

template_binary_sensors = helpers.fetch("template").flat_map do |block|
  block.fetch("binary_sensor", [])
end

heating_active = template_binary_sensors.find do |item|
  item["unique_id"] == "hot_water_heating_active"
end
assert_contract(!heating_active.nil?, "physical hot-water activity sensor is missing")
assert_contract(
  heating_active.fetch("availability").include?("is_state('switch.hot_water', 'off')"),
  "idle hot-water activity must remain available without a fresh static zero-power report"
)
assert_contract(
  heating_active.fetch("availability").include?("load_reported >= relay_changed - 2"),
  "running hot-water activity must require a post-relay SAJ load report"
)
assert_contract(
  heating_active.fetch("state").include?("is_state('switch.hot_water', 'on') and load_kw >= nominal_kw - 0.5"),
  "confirmed hot-water runtime must require the relay-on whole-house element signature"
)

template_sensors = helpers.fetch("template").flat_map do |block|
  block.fetch("sensor", [])
end
confirmed_power = template_sensors.find do |item|
  item["unique_id"] == "energy_optimizer_hot_water_confirmed_power"
end
assert_contract(!confirmed_power.nil?, "dedicated confirmed hot-water power sensor is missing")
assert_contract(
  confirmed_power.fetch("state").include?("binary_sensor.hot_water_heating_active"),
  "confirmed hot-water power must derive from physical activity evidence"
)

plan_fresh = template_binary_sensors.find do |item|
  item["unique_id"] == "energy_optimizer_plan_fresh"
end
assert_contract(!plan_fresh.nil?, "committed plan-fresh sensor is missing")
assert_contract(
  plan_fresh.fetch("state").include?("sensor.energy_optimizer_site_export_target"),
  "plan freshness must include the site-export target plan ID"
)

readback_refresh = automations.find do |item|
  item["id"] == "energy_optimizer_saj_control_readback_refresh"
end
assert_contract(!readback_refresh.nil?, "SAJ independent readback refresh automation is missing")
readback_refresh_raw = read("energy-optimizer-auto-resume.yaml")
%w[
  number.saj_battery_on_grid_discharge_depth_input
  number.saj_battery_discharge_power_limit_input
  sensor.saj_battery_on_grid_discharge_depth
  sensor.saj_battery_discharge_power_limit
  homeassistant.update_entity
].each do |token|
  assert_contract(readback_refresh_raw.include?(token), "SAJ readback refresh is missing #{token}")
end

ev_local_link = template_binary_sensors.find do |item|
  item["unique_id"] == "energy_optimizer_ev_local_link_fresh"
end
assert_contract(!ev_local_link.nil?, "EV local command-link sensor is missing")
ev_idle_link_state = ev_local_link.fetch("state")
%w[
  sensor.tesla_ble_039d9c_uptime
  binary_sensor.tesla_ble_039d9c_status
  switch.tesla_ble_039d9c_charger
  binary_sensor.tesla_wall_connector_vehicle_connected
  uptime_age
].each do |token|
  assert_contract(ev_idle_link_state.include?(token), "EV idle command link missing #{token}")
end
assert_contract(
  !ev_idle_link_state.include?("sensor.tesla_ble_charge_power"),
  "idle EV command readiness must not require the static zero-power entity"
)
assert_contract(
  !ev_idle_link_state.include?("sensor.tesla_wall_connector_wifi_rssi"),
  "idle EV command readiness must not require irregular wall-connector RSSI"
)
ev_link_attributes = ev_local_link.fetch("attributes")
assert_contract(
  ev_link_attributes.fetch("charge_power_fresh").include?("age <= 120"),
  "EV local link must publish a bounded charge-power freshness diagnostic"
)
assert_contract(
  ev_link_attributes.fetch("fleet_control_available").include?("energy_optimizer_tesla_fleet_fallback_ready") &&
    ev_link_attributes.fetch("control_path").include?("number.tesla_ble_039d9c_charging_amps") &&
    ev_link_attributes.fetch("ble_control_available").include?("number.tesla_ble_039d9c_charging_limit") &&
    ev_link_attributes.fetch("fleet_vehicle_data_available").include?("number.jarvis_charge_current"),
  "EV link must expose BLE primary control with Tesla Fleet fallback"
)

solar_start_ready = template_binary_sensors.find do |item|
  item["unique_id"] == "energy_optimizer_hot_water_solar_start_ready"
end
assert_contract(!solar_start_ready.nil?, "sustained hot-water solar-start sensor is missing")
assert_contract(
  solar_start_ready.dig("delay_on", "seconds") == 30,
  "ordinary hot-water start must require thirty continuous seconds of solar margin"
)
assert_contract(
  solar_start_ready.fetch("state").include?("relay_on_age < 60"),
  "hot-water solar headroom must tolerate only the bounded physical-confirmation grace"
)

saj_contract_ready = template_binary_sensors.find do |item|
  item["unique_id"] == "energy_optimizer_saj_control_contract_ready"
end
assert_contract(!saj_contract_ready.nil?, "SAJ control contract sensor is missing")
expected_saj_endpoints = %w[
  number.saj_anti_reflux_mode_input
  number.saj_export_limit_input
  number.saj_grid_max_discharge_power_input
  number.saj_battery_on_grid_discharge_depth_input
  sensor.saj_battery_on_grid_discharge_depth
  switch.saj_charging_control
  switch.saj_discharging_control
  number.saj_charge1_power_percent_input
  number.saj_discharge1_power_percent_input
  number.saj_battery_charge_power_limit_input
  number.saj_battery_discharge_power_limit_input
  sensor.saj_battery_discharge_power_limit
].sort
extract_saj_endpoints = lambda do |template|
  template.scan(/'(?:number|sensor|switch)\.saj_[a-z0-9_]+'/).map do |match|
    match.delete("'")
  end.sort
end
{
  "state" => saj_contract_ready.fetch("state"),
  "required_entities" => saj_contract_ready.fetch("attributes").fetch("required_entities"),
  "missing_entities" => saj_contract_ready.fetch("attributes").fetch("missing_entities")
}.each do |field, template|
  assert_contract(
    extract_saj_endpoints.call(template) == expected_saj_endpoints,
    "SAJ #{field} endpoint set must exactly match the sole Node-RED actuator"
  )
end

hot_water = read("energy-optimizer-hot-water-actuator.yaml")
%w[
  sensor.hot_water_confirmed_runtime_today
  binary_sensor.hot_water_heating_active
  binary_sensor.energy_optimizer_core_telemetry_fresh
  binary_sensor.energy_optimizer_plan_fresh
  command_valid_until_ts
  hot_water_plan_id
  control_mode
  solar_surplus
  service_rescue
  protected_soc_pct
  battery_guard_kw
  solar_margin_ok
  solar_start_sustained
  binary_sensor.energy_optimizer_hot_water_solar_start_ready
  guarantee_due
  startup_reconciliation
  hot_water_idle_values_ok
  element_power_age_seconds
  element_power_fresh
  relay_start_grace_seconds
  relay_start_grace_active
  physical_element_confirmed
  committed_solar_run
  active_plan_rollover_grace
  plan_stage_age_seconds
  thermostat_satisfied_now
  energy_optimizer_hot_water_thermostat_satisfied
  insufficient_solar
  stationary_battery_draw
  plan_commit_settling
  starting_awaiting_power
  switch.turn_off
].each do |token|
  assert_contract(hot_water.include?(token), "hot-water governor missing #{token}")
end
assert_contract(hot_water.include?("seconds: /10"), "hot-water watchdog must run every ten seconds")
assert_contract(hot_water.include?("event: start"), "hot-water governor needs startup reconciliation")
assert_contract(hot_water.include?("relay_start_grace_seconds: 60"), "hot-water physical confirmation grace must be sixty seconds")
assert_contract(hot_water.include?("battery_guard_kw: 0.3"), "hot-water battery guard must be a fixed 0.3 kW")
assert_contract(hot_water.include?("sensor.saj_pv_power"), "hot water must use polled SAJ PV")
assert_contract(!hot_water.include?("sensor.pv_power_mqtt_abs"), "hot water must not use stale MQTT PV")
assert_contract(!hot_water.include?("- delay:"), "hot-water governor must never delay hard-stop evaluation")
idle_values_block = hot_water[/hot_water_idle_values_ok: >-\n(.*?)        element_power_fresh:/m, 1]
assert_contract(!idle_values_block.nil?, "hot-water idle command readiness block is missing")
assert_contract(
  !idle_values_block.include?("last_reported") && !idle_values_block.include?("power_age"),
  "idle hot-water command readiness must not require static zero-power freshness"
)
assert_contract(
  hot_water.index("service_complete") < hot_water.index("hot_water_control_values_unavailable"),
  "hot-water completion must precede idle power/control diagnostics"
)
assert_contract(!hot_water.include?("deadline_1600"), "4pm must not hard-stop incomplete hot-water service")
assert_contract(hot_water.include?("deadline_ts | float(0) - remaining_h * 3600"), "hot-water service guarantee must calculate a dynamic latest start")
assert_contract(!hot_water.include?("physical_command_mismatch"), "a satisfied tank thermostat must not be treated as an actuator failure")
assert_contract(
  hot_water.scan("is_state('switch.hot_water', 'on') or off_dwell_complete | bool").length == 1,
  "ordinary starts must preserve off dwell while overdue service rescue starts immediately"
)
assert_contract(
  hot_water.include?("and solar_margin_ok | bool") &&
    hot_water.include?("and not solar_margin_ok | bool"),
  "ordinary hot water must start and remain on solar rather than drawing from the battery"
)
assert_contract(
  hot_water.include?("rescue_authorized | bool and runtime_due | bool") &&
    hot_water.include?("control_mode == 'service_rescue'") &&
    hot_water.include?("rescue_source') == 'grid_only'") &&
    hot_water.include?("and guarantee_due | bool"),
  "hot-water rescue must be a plan-authorized grid-only latest-start service"
)
assert_contract(
  hot_water.include?("committed_solar_run | bool") &&
    hot_water.include?("battery_discharge_kw | float(999) <= battery_guard_kw"),
  "an active solar hot-water run must survive replans without consuming the stationary battery"
)

hot_water_doc = parse("energy-optimizer-hot-water-actuator.yaml")
assert_contract(
  hot_water_doc.any? { |item| item["id"] == "energy_optimizer_hot_water_daily_reset" },
  "hot-water thermostat satisfaction must reset at local midnight"
)
retired_fallback = hot_water_doc.find do |item|
  item["id"] == "energy_optimizer_hot_water_deadline_fallback"
end
assert_contract(retired_fallback["initial_state"] == false, "old hot-water fallback must be disabled")
assert_contract(retired_fallback["actions"] == [], "old hot-water fallback must be inert")

ev = read("energy-optimizer-ev-auto-actuator.yaml")
%w[
  command_valid_until_ts
  ev_plan_id
  measured_ev_kw
  grace_ev_kw
  wall_power_age_seconds
  wall_power_fresh
  sensor.tesla_wall_connector_total_power
  switch.jarvis_charge
  number.jarvis_charge_current
  number.jarvis_charge_limit_2
  switch.tesla_ble_039d9c_charger
  number.tesla_ble_039d9c_charging_amps
  number.tesla_ble_039d9c_charging_limit
  control_backend
  charger_switch_entity
  charging_amps_entity
  button.jarvis_wake
  input_boolean.energy_optimizer_ev_allow_grid
  grid_allowed
  grid_charging_disabled
  import_trim_amps
  charger_on_seconds
  charger_start_grace_seconds
  charger_start_grace_active
  prior_start_epoch
  start_epoch=
  charger_session_active
  ev_power_confirmed
  wall_power_not_confirmed
  starting_awaiting_wall_power
  non_ev_load_kw
  charger_off_seconds
  tesla_wall_connector_vehicle_connected
  battery_discharge_kw
  battery_target_plan_id
  planned_battery_discharge_kw
  battery_target_authorized
  battery_discharge_allowance_kw
  battery_discharge_excess_kw
  battery_trim_amps
  insufficient_onsite_energy
  startup_reconciliation
  sensor.saj_pv_power
  command_amps
  amp_setting_age_seconds
  current_amps
  effective_current_amps
  physical_amps_estimate
  prior_command_amps
  prior_direct_solar_session
  solar_session_continuation
  mandatory_expected_solar_override
  physical_mandatory_solar_session
  physical_solar_minimum_hold
  active_session_rollover_grace
  plan_stage_age_seconds
  effective_direct_solar_source
  solar_feedforward_reliable
  committed_solar_session
].each do |token|
  assert_contract(ev.include?(token), "EV source guard missing #{token}")
end
assert_contract(ev.include?("charger_start_grace_seconds: 90"), "EV start confirmation grace must be exactly ninety seconds")
assert_contract(
  ev.include?("'start_epoch=' in status") &&
    ev.include?("states['switch.tesla_ble_039d9c_charger'].last_changed") &&
    ev.include?("if prior_start_epoch | float(0) > 0") &&
    ev.include?("not charger_start_grace_active | bool") &&
    ev.include?("and not ev_power_confirmed | bool"),
  "EV start grace must survive an optimistic switch-off without issuing repeated start commands"
)
assert_contract(
  ev.include?("'ble' if ble_control_ok | bool") &&
    ev.include?("else 'tesla_fleet' if fleet_control_ok | bool and fleet_values_ready | bool"),
  "EV control must prefer healthy local BLE and fall back to Tesla Fleet"
)
assert_contract(
  ev.include?("[measured_ev_kw | float(0), grace_ev_kw | float(0)] | max"),
  "EV inclusive-load correction must use confirmed power or only the bounded grace estimate"
)
assert_contract(ev.include?("seconds: /15"), "EV watchdog must run every fifteen seconds")
assert_contract(ev.include?("battery_guard_kw: 0.3"), "EV battery guard must be a fixed 0.3 kW")
assert_contract(
  ev.include?("battery_target_plan_id == committed_plan_id") &&
    ev.include?("battery_discharge_kw | float(0) -") &&
    ev.include?("planned_battery_discharge_kw | float(0)"),
  "EV battery guard must compare physical discharge with the matching committed battery allocation"
)
assert_contract(!ev.include?("- delay:"), "EV safety evaluation must never be blocked behind a start delay")
assert_contract(!ev.include?("sensor.pv_power_mqtt_abs"), "EV must not use stale MQTT PV")
assert_contract(!ev.include?("sensor.tesla_charging_power"), "EV control must not subtract a stale cloud charging value")
assert_contract(!ev.include?("sensor.tesla_wall_connector_wifi_rssi"), "EV start must not depend on irregular wall-connector RSSI")
assert_contract(
  ev.include?("wall_power_fresh | bool and wall_ev_kw | float(-1) > 0.5"),
  "EV physical confirmation must use fresh wall-connector power"
)
assert_contract(!ev.include?("off_dwell_complete | bool or fallback_authorized"), "mandatory fallback must not bypass EV restart dwell")
assert_contract(ev.include?("mode: single"), "EV actuator must serialize decisions to prevent stale start/stop service races")
assert_contract(ev.scan("entity_id: switch.jarvis_charge").length >= 1 &&
  ev.scan("entity_id: switch.tesla_ble_039d9c_charger").length >= 1,
  "EV hard stops must retain both Fleet and BLE containment")
assert_contract(
  ev.include?('entity_id: "{{ charging_amps_entity }}"') &&
    ev.include?('entity_id: "{{ charger_switch_entity }}"'),
  "EV start and amp control must use the selected healthy backend"
)
assert_contract(
  ev.include?("target_amps | int(0) > effective_current_amps | int(-1)") &&
    ev.include?("amp_setting_age_seconds | float(0) >= 60"),
  "EV upward setpoint changes must use a sixty-second rate limit"
)
assert_contract(
  ev.include?("stationary_battery_soc_pct") &&
    ev.include?("states('sensor.saj_battery_1_soc')") &&
    ev.include?("stationary_battery_soc_pct | float(-1)") &&
    ev.include?("plan_protected_soc_pct | float(100) + 1"),
  "EV battery support must compare stationary-battery SOC with its protected reserve"
)
assert_contract(
  ev.include?("battery_trim_amps") &&
    ev.include?("battery_discharge_excess_kw | float(0) - battery_guard_kw") &&
    !ev.include?("stationary_battery_discharge_above_plan"),
  "EV battery draw must proportionally trim current instead of hard-stopping"
)
assert_contract(
  ev.include?("expected_pv_attenuation: 0.92") &&
    ev.include?("expected_pv_fresh") &&
    ev.include?("pv_feedforward_kw") &&
    ev.include?("feedforward_solar_amps") &&
    !ev.include?("direct_solar_amps"),
  "EV current must use attenuated expected PV as feed-forward with actual-power feedback"
)
assert_contract(
  ev.include?("opportunistic_fit_max: 0.01") &&
    ev.include?("live_fit | float(999) <= opportunistic_fit_max") &&
    ev.include?("feedforward_solar_amps | int(0) >= 6") &&
    ev.include?("plan_action != 'charge'") &&
    ev.include?("and not solar_session_continuation | bool"),
  "a safe low-FIT expected-solar EV session must survive rolling planner withdrawal"
)
assert_contract(
  ev.include?("ev_mandatory | bool") &&
    ev.include?("explicit_trip_required | bool") &&
    ev.include?("mandatory_expected_solar_override | bool") &&
    ev.include?("feedforward_solar_amps | int(0) >= 6"),
  "a declared trip must use fresh expected solar even when the horizon is insufficient"
)
assert_contract(
  ev.include?("expected_pv_fresh | bool") &&
    ev.include?("live_fit | float(999) > 0 and pv_kw | float(-1) >= 0") &&
    ev.scan("and solar_feedforward_reliable | bool").length >= 3,
  "EV solar sessions must use actual PV only when positive FIT proves it is uncurtailed"
)
assert_contract(
  ev.include?("plan_action == 'insufficient_time'") &&
    ev.include?("grid_kw | float(999) <= -0.3") &&
    ev.include?("or physical_mandatory_solar_session | bool"),
  "a physically exporting mandatory EV session must survive transient planner withdrawal"
)
assert_contract(
  hot_water.include?("command_valid_until_ts | float(0) > as_timestamp(now()) - 15") &&
    ev.include?("command_valid_until_ts | float(0) > as_timestamp(now()) - 15"),
  "active flexible loads need a bounded fifteen-second safe plan-rollover bridge"
)
assert_contract(
  ev.include?("ble_stop_fallback_ready") &&
    ev.include?("as_timestamp(now()) - prior_stop_epoch | float(0) >= 15") &&
    ev.include?("not ble_control_ok | bool") &&
    ev.include?("or ble_stop_fallback_ready | bool"),
  "Tesla Fleet must be reserved for BLE unavailability or failed BLE stop containment"
)

ev_doc = parse("energy-optimizer-ev-auto-actuator.yaml").find do |item|
  item["id"] == "energy_optimizer_ev_auto_actuator"
end
ev_trigger_entities = ev_doc.fetch("triggers").flat_map { |trigger| Array(trigger["entity_id"]) }
assert_contract(
  !ev_trigger_entities.include?("sensor.energy_optimizer_battery_power_target") &&
    !ev_trigger_entities.include?("sensor.energy_optimizer_ev"),
  "EV actuator must not react to staged command sensors before the atomic plan commit"
)
%w[
  binary_sensor.energy_optimizer_core_telemetry_fresh
  binary_sensor.energy_optimizer_ev_local_link_fresh
  sensor.saj_battery_power
  sensor.saj_battery_1_soc
  sensor.james_pv1_expected_power_from_poa
  sensor.james_pv2_plus_pv3_expected_power_from_poa
  sensor.saj_meter_a_real_power_total
  sensor.amber_express_trader_sheena_street_feed_in_price
  sensor.tesla_wall_connector_total_power
  switch.jarvis_charge
  number.jarvis_charge_current
  number.jarvis_charge_limit_2
  input_boolean.energy_optimizer_ev_allow_grid
  switch.tesla_ble_039d9c_charger
  number.tesla_ble_039d9c_charging_amps
  number.tesla_ble_039d9c_charging_limit
].each do |entity_id|
  assert_contract(ev_trigger_entities.include?(entity_id), "EV immediate safety trigger missing #{entity_id}")
end

resume = read("energy-optimizer-auto-resume.yaml")
%w[
  energy_optimizer_validated_auto_resume
  energy_optimizer_saj_control_contract_guard
  energy_optimizer_production_expected
  energy_optimizer_saj_control_contract_ready
  energy_optimizer_actuator_current_plan
  energy_optimizer_home_assistant_started
  energy_optimizer_manual_override
  feedback_confirmed
  number.saj_anti_reflux_mode_input
  number.saj_export_limit_input
  number.saj_grid_max_discharge_power_input
  number.saj_battery_on_grid_discharge_depth_input
  sensor.saj_battery_on_grid_discharge_depth
  switch.saj_charging_control
  switch.saj_discharging_control
  number.saj_charge1_power_percent_input
  number.saj_discharge1_power_percent_input
  number.saj_battery_charge_power_limit_input
  number.saj_battery_discharge_power_limit_input
  sensor.saj_battery_discharge_power_limit
  notify.mobile_app_iphone
  value: 28
].each do |token|
  assert_contract(resume.include?(token), "validated resume/SAJ drift guard missing #{token}")
end
assert_contract(!resume.include?("startswith('accepted_')"), "auto-resume must not treat requested-only actuation as ready")
assert_contract(!resume.include?("accepted_applied"), "auto-resume must require final physical confirmation for every mode")
assert_contract(resume.include?("actuator_fields[0] in ['feedback_confirmed', 'semantic_noop_confirmed']"), "auto-resume must require physical or equivalent semantic confirmation")
assert_contract(!resume.include?("actuator.startswith('feedback_confirmed')"), "auto-resume must reject intermediate direction confirmation")
assert_contract(resume.include?("('mode=' ~ expected_mode) in actuator_fields"), "auto-resume must require confirmed plan-mode parity")

helpers = read("energy-optimizer-helpers-package.yaml")
assert_contract(helpers.include?("actuator_fields[0] in ['feedback_confirmed', 'semantic_noop_confirmed']"), "readiness must require physical or equivalent semantic confirmation")
assert_contract(!helpers.include?("actuator.startswith('feedback_confirmed')"), "readiness must reject intermediate feedback-confirmed prefixes")
assert_contract(!helpers.include?("accepted_applied"), "readiness must not accept an intermediate applied status")
assert_contract(helpers.include?("status_fields[1] == plan_id"), "current-plan status must use an exact plan-ID field")
assert_contract(!helpers.include?("and plan_id in status"), "current-plan status must not use substring plan-ID matching")
assert_contract(helpers.include?("('mode=' ~ expected_mode) in actuator_fields"), "readiness must require confirmed plan-mode parity")
assert_contract(helpers.include?("actuator_not_confirmed_for_plan_mode"), "readiness reason must expose safe-stop/mode mismatch")

def confirmed_status_matches_plan?(status, plan_id, expected_mode)
  fields = status.split(" | ")
  ["feedback_confirmed", "semantic_noop_confirmed"].include?(fields.first) &&
    fields[1] == plan_id &&
    fields.include?("mode=#{expected_mode}")
end

normal_confirmation = "feedback_confirmed | eop-test | mode=export | target=28.0kW"
safe_stop_confirmation = "feedback_confirmed | eop-test | mode=safe_stop | target=0.0kW"
direction_confirmation = "feedback_confirmed_direction | eop-test | mode=export | target=28.0kW"
semantic_confirmation = "semantic_noop_confirmed | eop-test | mode=export | target=28.0kW"
assert_contract(
  confirmed_status_matches_plan?(normal_confirmation, "eop-test", "export"),
  "normal confirmed plan status must remain eligible"
)
assert_contract(
  confirmed_status_matches_plan?(semantic_confirmation, "eop-test", "export"),
  "equivalent semantic confirmation must remain eligible"
)
assert_contract(
  !confirmed_status_matches_plan?(safe_stop_confirmation, "eop-test", "export"),
  "physically confirmed safe-stop must never satisfy plan readiness"
)
assert_contract(
  !confirmed_status_matches_plan?(direction_confirmation, "eop-test", "export"),
  "intermediate direction confirmation must never satisfy final readiness"
)

date_refresh = read("energy-optimizer-ev-requirement-date.yaml")
%w[event: start 07:00:05 tesla_ble_039d9c_charging_limit timedelta].each do |token|
  assert_contract(date_refresh.include?(token), "EV departure refresh missing #{token}")
end

%w[
  mandatory_session_transition
  latching_mandatory_session
  negative_fit_rollover_grace
  holding_negative_fit_rollover
  preserving_current_command
].each do |token|
  assert_contract(ev.include?(token), "EV actuator is missing mandatory-session plan-transition latch token #{token}")
end

notifications = read("energy-optimizer-notifications.yaml")
assert_contract(!notifications.include?("wait_for_trigger"), "notification rearming must not use volatile long waits")
%w[
  energy_optimizer_notify_battery_selling_active
  energy_optimizer_notify_ev_charging_active
  energy_optimizer_notify_hot_water_active
  energy_optimizer_notify_hot_water_complete_sent
  energy_optimizer_alert_degraded_active
  energy_optimizer_negative_fit_export_violation
  energy_optimizer_hot_water_battery_violation
  energy_optimizer_ev_battery_violation
].each do |token|
  assert_contract(notifications.include?(token), "notification contract missing #{token}")
end

curtail = read("energy-optimizer-saj-curtailment.yaml")
assert_contract(!curtail.include?("number.set_value"), "retired HA curtailment must not write numbers")
assert_contract(!curtail.include?("number.saj_export_limit_input"), "HA must not own the SAJ export-limit register")
assert_contract(!curtail.include?("number.saj_anti_reflux_mode_input"), "HA must not own the SAJ anti-reflux register")
curtail_doc = parse("energy-optimizer-saj-curtailment.yaml").first
assert_contract(curtail_doc["initial_state"] == false, "retired HA curtailment must be disabled")
assert_contract(curtail_doc["actions"] == [], "retired HA curtailment must be inert")

retired_automations = parse("energy-optimizer-retired-automations.yaml")
%w[
  energy_optimizer_ev_daily_prompt
  energy_optimizer_ev_trip_response
  energy_optimizer_ev_cheap_window
].each do |automation_id|
  retired = retired_automations.find { |item| item["id"] == automation_id }
  assert_contract(!retired.nil?, "retired automation record missing #{automation_id}")
  assert_contract(retired["initial_state"] == false, "#{automation_id} must remain disabled")
  assert_contract(retired["actions"] == [], "#{automation_id} must remain inert")
end

device_writers = automation_files.select do |name|
  read(name).match?(/entity_id:\s*switch\.hot_water/)
end
assert_contract(
  device_writers == ["energy-optimizer-hot-water-actuator.yaml"],
  "hot water must have one automation writer, found: #{device_writers.join(', ')}"
)

ev_writers = automation_files.select do |name|
  read(name).match?(/entity_id:\s*switch\.jarvis_charge/)
end
assert_contract(
  ev_writers == ["energy-optimizer-ev-auto-actuator.yaml"],
  "verified Tesla Fleet charger must have one automation writer, found: #{ev_writers.join(', ')}"
)

saj_number_writers = automation_files.select do |name|
  raw = read(name)
  raw.match?(/action:\s*number\.set_value/) && raw.include?("number.saj_")
end
assert_contract(
  saj_number_writers.empty?,
  "Home Assistant must not write SAJ number entities: #{saj_number_writers.join(', ')}"
)

dashboard_doc = parse("energy-optimizer-dashboard.yaml")
dashboard = read("energy-optimizer-dashboard.yaml")
assert_contract(
  dashboard.include?("input_number.energy_optimizer_min_sell_price_c_per_kwh"),
  "dashboard must expose the minimum battery sell price"
)
%w[
  energy_optimizer_actuation_ready
  energy_optimizer_readiness
  energy_optimizer_hot_water_outcome
  hot_water_confirmed_runtime_today
  energy_optimizer_ev_outcome
  tesla_wall_connector_vehicle_connected
  tesla_ble_039d9c_charging_limit
  energy_optimizer_ev_allow_grid
  energy_optimizer_ev_departure
  energy_optimizer_site_export_target
  amber_express_trader_sheena_street_feed_in_price
].each do |token|
  assert_contract(dashboard.include?(token), "dashboard missing #{token}")
end
overview = dashboard_doc.fetch("views").first
assert_contract(overview["type"] == "sections", "dashboard overview must use the UI-editable Sections layout")
assert_contract(overview["sections"].is_a?(Array) && overview["sections"].length == 5, "dashboard must keep five simple operator sections")
assert_contract(overview["sections"].all? { |section| section["type"] == "grid" }, "dashboard Sections children must use editable grids")
assert_contract(!dashboard.include?("sensor.hot_water_runtime_today"), "dashboard must not present relay runtime as confirmed service")
assert_contract(!dashboard.include?("float(0)"), "dashboard must not render missing measurements as zero")
assert_contract(!dashboard.include?("int(0)"), "dashboard must not render missing integer measurements as zero")
assert_contract(!dashboard.match?(/as_timestamp\([^\n]*,\s*0\)/), "dashboard must not render missing timestamps as epoch")
assert_contract(
  !dashboard.match?(/states\.[a-z0-9_]+\.[a-z0-9_]+\.attributes/),
  "dashboard must not directly dereference attributes on startup-optional entities"
)
%w[plan hw ev].each do |entity|
  guard = "#{entity}_entity.attributes if #{entity}_entity is not none else {}"
  assert_contract(dashboard.include?(guard), "dashboard missing startup-safe #{entity} attribute guard")
end
assert_contract(
  !dashboard.match?(/\b(?:p|hw|ev)\.(?!get\()[a-z_]/),
  "dashboard startup-optional attribute maps must use guarded get access"
)
assert_contract(dashboard.include?("sensor.saj_pv_power"), "dashboard must show the polled SAJ PV source")
assert_contract(!dashboard.include?("sensor.pv_power_mqtt_abs"), "dashboard must not show stale MQTT PV as live")

puts "OK: #{yaml_files.length} YAML files parsed; #{ids.length} unique automations; HA safety contract satisfied"
