# Pilot Energy Optimizer

Local, production, forecast-aware dispatch planning for Amber prices, SAJ battery/solar, hot water and three-phase Tesla charging.

## Current rollout state

- Deployed on `10.0.1.204` as the isolated `energy-optimizer` Docker service.
- Home Assistant exposes the versioned four-view dashboard at
  `/energy-optimizer-dashboard/overview` using
  `home-assistant/energy-optimizer-dashboard.yaml`.
- Replans a timezone-aware 36-hour horizon every five minutes and journals every plan under `/opt/energy-optimizer/data/plans`.
- Production mode uses explicit rollout, battery, hot-water and EV enable gates plus an immediate manual override.
- The guarded Node-RED actuator is installed as a separate flow and reports its decision to `input_text.energy_optimizer_actuator_status`.
- The former FIT, fixed-PV, hot-water and Tesla dispatch authorities are disabled and retained for deliberate rollback only.
- Node-RED direct editor/API authentication is enabled (`leave_front_door_open: false`); administration is through protected Home Assistant ingress.

## Safety model

- The Python service never writes to SAJ, hot-water or Tesla control entities.
- It publishes a plan to Home Assistant with a ten-minute expiry.
- Node-RED independently validates schema, freshness, enable helpers, manual override, SOC and power limits.
- `Active` mode is necessary but not sufficient: rollout approval and the relevant subsystem helper must also be enabled, and manual override must be off.
- A stale active plan stops forced charge/discharge and restores normal PV charging.
- Rejected or stale plans also restore normal PV export instead of retaining an old curtailment command.
- Disarmed and manual-override states explicitly stop forced battery modes and reset the normal PV charge limit to 30 kW.

## Optimisation model

- Battery floor 5%, morning target 7%, evening target 99%.
- Verified charge/discharge limits are 30/28 kW, with `input_number.energy_optimizer_max_discharge_kw` retaining any stricter live discharge limit.
- 90% charge and discharge efficiencies, $0.08/kWh discharged wear cost and $0.02/kWh grid-arbitrage uncertainty margin.
- Amber signed import/FIT prices, calibrated Solcast P10/P50/P90, weather, learned weekday/half-hour base load, 3.7 kW hot water and EV requirements share one plan.
- Tesla charging is modelled as three phase at 6–16 A (about 4.45–11.86 kW at the observed phase voltage). Conservative direct-solar slots are exhausted before a clearly labelled departure-deadline fallback is considered.
- A morning target is enforced only when pre-solar discharge has economic value and conservative solar can refill the battery, or the early price dominates later retained value. Poor-price days intentionally retain more SOC.
- Negative FIT first fills useful flexible loads and storage, then requests curtailment instead of paid export.

## Home Assistant contract

Published sensors:

- `sensor.energy_optimizer_status`
- `sensor.energy_optimizer_plan`
- `sensor.energy_optimizer_battery_power_target`
- `sensor.energy_optimizer_site_export_target`
- `sensor.energy_optimizer_pv_export`
- `sensor.energy_optimizer_hot_water`
- `sensor.energy_optimizer_ev`

Safety and user helpers:

- `input_select.energy_optimizer_mode`
- `input_boolean.energy_optimizer_manual_override`
- `input_boolean.energy_optimizer_rollout_approved`
- `input_boolean.energy_optimizer_battery_control`
- `input_boolean.energy_optimizer_hot_water_control`
- `input_boolean.energy_optimizer_ev_auto`
- `input_number.energy_optimizer_max_discharge_kw`
- `input_select.energy_optimizer_ev_trip`
- `input_number.energy_optimizer_ev_custom_km`
- `input_datetime.energy_optimizer_ev_departure`
- `input_datetime.energy_optimizer_shadow_started`
- `input_text.energy_optimizer_actuator_status`

The six `energy_optimizer_*` Home Assistant automations implement guarded hot-water control/fallback, the daily EV prompt and response, the advisory cheap-window alert, and disabled-by-helper local Tesla BLE auto-control.

## Local checks

```bash
uv run --extra test pytest
node --test node-red/guard.test.js
docker compose -f ../../infra/energy-optimizer/docker-compose.yml config
```

## Deployment

```bash
deploy/scripts/energy-optimizer-sync
deploy/scripts/energy-optimizer-sync --apply
ssh root@10.0.1.204 'curl -fsS http://127.0.0.1:8785/readyz'
```

The sync command is a dry run unless `--apply` is supplied. It only synchronizes the dedicated app and deployment directories.

## Historical replay

The versioned exporter uses the existing `solar-monitor` container's scoped InfluxDB access; no Influx token is copied into this service or repository.

```bash
ssh root@10.0.1.204 'docker exec -i solar-monitor node --input-type=module' \
  < tools/influx_replay_export.mjs \
  | uv run pilot-energy-replay --output reports/29-day-replay.json
```

The report covers 29 completed Brisbane days. It is a perfect-hindsight dispatch benchmark using actual 30-minute solar, load and prices, with end-of-day stored energy valued consistently in both cases. It establishes feasibility and an upper bound; retained production plans and outcomes provide the ongoing forecast and command-timing validation.

## Production and rollback checklist

1. Keep the retired FIT tiers, fixed reserve, sunrise/10:30 rules and duplicate Amber/Tesla/hot-water writers disabled so there is one dispatch authority.
2. Keep the SAJ 5% lower reserve and the guarded 28/30 kW limits in place.
3. Treat `input_boolean.energy_optimizer_manual_override` as the immediate disarm. It cancels forced battery modes; EV and hot-water actuators issue a one-shot stop and then leave manual control available.
4. Confirm plan age, Node-RED acceptance and SAJ feedback on the dashboard after every deployment.
5. For rollback, disarm the optimiser first, verify both forced modes are off and normal PV charging is restored, then deliberately re-enable only the required former authority from the checkpoint/flow backup.
