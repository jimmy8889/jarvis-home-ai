# Pilot Energy Optimizer

Local, shadow-first, forecast-aware dispatch planning for Amber prices, SAJ battery/solar, hot water and Tesla charging.

## Current rollout state

- Deployed on `10.0.1.204` as the isolated `energy-optimizer` Docker service.
- Replans a timezone-aware 36-hour horizon every five minutes and journals every plan under `/opt/energy-optimizer/data/plans`.
- Mode is `Shadow`; rollout approval, battery control, hot-water control and EV auto-control all default off.
- The guarded Node-RED actuator is installed as a separate flow and reports its decision to `input_text.energy_optimizer_actuator_status`.
- The legacy FIT and battery flows remain enabled and unchanged during shadow validation. They must be disabled, not deleted, immediately before the first active battery stage.
- Node-RED direct editor/API authentication is enabled (`leave_front_door_open: false`); administration is through protected Home Assistant ingress.

## Safety model

- The Python service never writes to SAJ, hot-water or Tesla control entities.
- It publishes a plan to Home Assistant with a ten-minute expiry.
- Node-RED independently validates schema, freshness, enable helpers, manual override, SOC and power limits.
- The initial Home Assistant mode is `Shadow`; all actuation helpers default off.
- A stale active plan stops forced charge/discharge and restores normal PV charging.
- Rejected or stale plans also restore normal PV export instead of retaining an old curtailment command.

## Optimisation model

- Battery floor 5%, morning target 7%, evening target 99%.
- Charge/discharge limits 30/28 kW, with the first active stage additionally capped by `input_number.energy_optimizer_max_discharge_kw` (10 kW initially).
- 90% charge and discharge efficiencies, $0.08/kWh discharged wear cost and $0.02/kWh grid-arbitrage uncertainty margin.
- Amber signed import/FIT prices, calibrated Solcast P10/P50/P90, weather, learned weekday/half-hour base load, 3.7 kW hot water and EV requirements share one plan.
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

The report covers 29 completed Brisbane days. It is a perfect-hindsight dispatch benchmark using actual 30-minute solar, load and prices, with end-of-day stored energy valued consistently in both cases. It establishes feasibility and an upper bound; the seven-day shadow run is what validates forecast accuracy and real command timing.

## Activation checklist

1. Keep all four actuation/approval helpers off for at least seven complete days.
2. Review journal freshness, Solcast calibration, morning/evening SOC error, negative-FIT curtailment recommendations, hot-water completion and EV alerts.
3. Require zero stale-command or guard errors, then disable the legacy FIT tiers, fixed reserve, sunrise/10:30 switching and duplicate Amber battery authorities.
4. Enable rollout approval plus hot-water/EV alerts first.
5. Enable battery control at 10 kW only after the review; retain the 5% inverter floor and verify SAJ feedback for three error-free active days.
6. Raise to the verified live limit only after that stage. Enable EV auto only after at least seven successful recommendations and a separate local-Tesla-control review.

Do not turn on `input_boolean.energy_optimizer_rollout_approved` until the legacy battery authority has been disabled and the seven-day review has passed.
