# Pilot Energy Optimizer

Local, production, forecast-aware dispatch planning for Amber prices, SAJ battery/solar, hot water and three-phase Tesla charging.

The canonical human-readable system guide is
[`energy-automation/README.md`](../../energy-automation/README.md). Every
material energy-automation change must update that guide in the same commit.

## Current rollout state

- Deployed on `10.0.1.204` as the isolated `energy-optimizer` Docker service.
- Home Assistant exposes the versioned four-view dashboard at
  `/energy-optimizer-dashboard/overview` using
  `home-assistant/energy-optimizer-dashboard.yaml`.
- Replans immediately when either live Amber price changes, while retaining a five-minute periodic safety refresh, and journals every plan under `/opt/energy-optimizer/data/plans`.
- Production mode uses explicit rollout, battery, hot-water and EV enable gates plus an immediate manual override.
- The guarded Node-RED actuator is installed as a separate flow and reports its decision to `input_text.energy_optimizer_actuator_status`.
- The former FIT, fixed-PV, hot-water and Tesla dispatch authorities are disabled and retained for deliberate rollback only.
- Node-RED direct editor/API authentication is enabled (`leave_front_door_open: false`); administration is through protected Home Assistant ingress.

## Safety model

- The Python service never writes to SAJ, hot-water or Tesla control entities.
- It publishes a plan to Home Assistant whose expiry is the end of the active
  Amber interval (with ten minutes retained only as the absolute maximum).
- Node-RED independently validates schema, freshness, enable helpers, manual
  override, SOC, fresh SOC/PV/load measurement timestamps and power limits.
- `Active` mode is necessary but not sufficient: rollout approval and the relevant subsystem helper must also be enabled, and manual override must be off.
- A stale active plan stops forced charge/discharge and restores normal PV charging.
- Rejected or stale plans also restore normal PV export instead of retaining an old curtailment command.
- Disarmed and manual-override states explicitly stop forced battery modes and reset the normal PV charge limit to 30 kW.
- Every plan directly reasserts the SAJ raw export-limit register (`0` to
  curtail, `1100` to allow) before synchronising the display helper. This avoids
  same-state helper calls silently skipping the hardware write.
- Every accepted plan arms a replaceable one-shot at `valid_until`; it
  safe-stops exactly at expiry if the following Amber event is missed. The
  independent 60-second watchdog remains as a second layer.
- Forced charge/discharge is checked 15 seconds after command issue against a
  fresh, post-command `sensor.saj_battery_power` sample with the expected sign
  and exclusive inverter mode. This is an observation window only; it does not
  delay the command.

## Optimisation model

- Battery floor 5%, morning target 7%, evening target 99%.
- Verified charge/discharge limits are 30/28 kW, with `input_number.energy_optimizer_max_discharge_kw` retaining any stricter live discharge limit. The guarded site-target semantic range is 0–100 kW so high PV plus 28 kW battery export is not rejected; this does not raise the inverter battery limit.
- 90% charge and discharge efficiencies, $0.08/kWh discharged wear cost and $0.02/kWh grid-arbitrage uncertainty margin.
- Amber signed import/FIT prices, calibrated Solcast P10/P50/P90, weather, learned weekday/half-hour base load, 3.7 kW hot water and EV requirements share one plan.
- The active Amber interval uses the exact live sensor state for the remaining settlement window. The next hour remains at five-minute resolution and the rest of the gap-free 36-hour horizon uses 30-minute slots, avoiding both price dilution and a costly all-day five-minute dynamic programme.
- Battery export power is price-shaped across that horizon: weaker FIT intervals
  are throttled so stored energy is retained for higher-value forecast windows,
  while the best feasible intervals can use the full verified inverter output.
  Node-RED applies each new target immediately; there is no smoothing ramp or
  deliberate command delay.
- Solar charging also carries an opportunity cost: valuable morning solar is
  exported and battery charging is deferred to lower-FIT periods whenever the
  conservative later-solar forecast can still satisfy the evening SOC target.
- A price event first publishes a short-lived current-interval dispatch from the last valid horizon, with no debounce, polling wait or command ramp. It requires explicit current Amber start/end metadata, fresh safety telemetry and all production gates; it preserves the cached morning reserve and any more valuable allocated future interval. Invalid, stale, low or negative pricing cannot inherit a forced export. The full 36-hour calculation then replaces it, normally about two seconds later on the measured development system.
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

The `energy_optimizer_*` Home Assistant automations implement guarded hot-water control/fallback, the daily EV prompt and response, the advisory cheap-window alert, local Tesla BLE auto-control, and edge-triggered iPhone activity notifications. The versioned notification export is in `home-assistant/energy-optimizer-notifications.yaml`; battery and EV alerts wait for physical power confirmation before notifying.

No Home Assistant webhook or unauthenticated optimiser endpoint is required. The service uses its existing secret-backed HA token to subscribe to `state_changed` over HA's local WebSocket API. Changes to either Amber price or the mode, rollout, battery-control and manual-override helpers wake the planner immediately. `/healthz` reports `state_stream_status`, the last trigger, and decision/cycle latency. The actuator should trigger from the completed `sensor.energy_optimizer_plan` update; that entity is published last as the plan commit marker, after the compact command sensors share the same plan ID. A revision check immediately before that marker prevents an overtaken calculation from actuating. Network and Home Assistant REST processing still impose unavoidable milliseconds of transport latency, but the optimiser adds no deliberate delay.

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
