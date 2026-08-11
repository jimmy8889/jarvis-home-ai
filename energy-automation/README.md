# Home Energy Automation

This folder is the living, human-readable guide to the home's energy automation. It describes what the system is trying to achieve, how decisions are calculated, what is currently deployed, and how to operate or extend it safely.

The production implementation remains in [`apps/energy-optimizer`](../apps/energy-optimizer/README.md). Deployment configuration is in [`infra/energy-optimizer`](../infra/energy-optimizer), and the guarded inverter actuator is in [`apps/energy-optimizer/node-red`](../apps/energy-optimizer/node-red).

## Documentation rule

**Every material energy-automation change must update this README in the same commit.**

That includes changes to:

- optimisation calculations or economic assumptions;
- battery, solar, EV, or hot-water behaviour;
- Home Assistant entities, helpers, dashboards, or notifications;
- Node-RED validation or SAJ actuation;
- roof geometry, inverter limits, battery capacity, or other physical assumptions;
- deployment, rollback, safety controls, tests, or acceptance criteria.

Add a short entry to the change log and update the relevant section rather than recording the change only in the log.

## Objectives

The optimiser is designed to maximise household energy value while preserving hard equipment and service constraints:

1. Export solar and battery energy in the most profitable Amber FIT intervals.
2. Shape battery output by price instead of discharging at a fixed rate.
3. Reach approximately 5–10% battery SOC as morning solar sustainably overtakes load, while retaining energy for valuable early-morning FIT.
4. Reach approximately 99% SOC before evening solar falls below household demand when economically and physically feasible.
5. Avoid importing energy unless it is required or economically superior after efficiency, battery wear, and uncertainty.
6. Run hot water for three confirmed hours using the lowest-opportunity-cost solar periods.
7. Charge the Tesla from genuine solar surplus by default.
8. Never use the stationary battery to charge the Tesla unless an explicitly declared trip requires deadline charging; even then, stationary-battery discharge is blocked during the fallback charge slot.
9. Curtail solar instead of paying to export during negative FIT periods after useful flexible loads and battery charging have been considered.

“Fully cycle the battery” is a profit-led target, not permission to destroy value by exporting into poor prices.

## System architecture

```text
Amber prices ──────────────┐
Solcast forecast ──────────┤
Local irradiance / POA ────┤
House load history ────────┤
Battery / PV telemetry ────┼──> Python optimiser on 10.0.1.204
EV requirement ────────────┤         │
Hot-water requirement ─────┘         │ retained versioned plan
                                     ▼
                              Home Assistant
                              state + dashboard
                                     │
                                     ▼
                         guarded Node-RED actuator
                                     │
                                     ▼
                              SAJ inverter helpers
```

- The Python service recalculates a rolling 36-hour plan every five minutes.
- Amber state changes also trigger an immediate price dispatch path, typically publishing within milliseconds rather than waiting for the periodic cycle.
- The Home Assistant `sensor.energy_optimizer_plan` entity is the plan commit marker.
- Node-RED validates freshness, bounds, telemetry, mode exclusivity, and physical SAJ feedback before accepting a command.
- A stale or rejected plan safe-stops forced charging/discharging and restores normal PV charging/export behaviour.

## Economic calculation

The optimiser maximises:

```text
export revenue
− grid import cost
− $0.08 per discharged battery kWh
− charging/discharging losses
− $0.02/kWh uncertainty margin for new grid-arbitrage decisions
```

Battery energy is allocated across the horizon rather than simply reacting to whether the current FIT is “high.” If available battery energy is limited, a higher future FIT receives more power than a lower current FIT. An exceptional live FIT can request the verified full 28 kW discharge limit immediately, provided the retained future value and SOC floor permit it.

Important physical limits:

| Constraint | Value |
|---|---:|
| Battery hard floor | 5% SOC |
| Morning target | approximately 7% SOC |
| Evening target | 99% SOC |
| Maximum battery discharge | 28 kW |
| Maximum battery charge | 30 kW |
| Modelled battery capacity | 47 kWh |
| Charge efficiency | 90% |
| Discharge efficiency | 90% |

Any stricter live SAJ or site limit takes precedence.

## Solar forecast

### Roof model

The site has 36.58 kWp of DC solar on two shallow roof planes:

| Plane | Capacity | Azimuth | Initial model tilt |
|---|---:|---:|---:|
| North | 11.8 kWp | 9° | 12.5° |
| South | 24.78 kWp | 171° | 12.5° |

The tilt starts at the midpoint of the measured 10–15° roof slope and can be refined from trustworthy production history.

### Forecast inputs

- Solcast expected/P10/P90 interval forecasts.
- `sensor.gw1100c_solar_radiation` for local irradiance.
- `sensor.james_poa_irradiance_james_poa_10` for north-plane irradiance.
- `sensor.james_poa_irradiance_james_poa_190` for south-plane irradiance.
- `sensor.james_pv1_expected_power_from_poa` for north expected output.
- `sensor.james_pv2_plus_pv3_expected_power_from_poa` for south expected output.
- Actual SAJ PV output and daily generation.

The two local expected-power signals are added to produce current available PV potential. The ratio between this potential and Solcast's current forecast becomes a bounded live weather correction. It is strongest immediately and fades linearly back to calibrated Solcast over 90 minutes.

If either roof-plane signal is missing, stale, invalid, or implausible, the correction is not used. The optimiser falls back to its existing calibrated Solcast/actual-PV path.

### Curtailment-aware learning

Actual inverter PV is not a valid measure of available sunshine while export is curtailed. The optimiser identifies likely curtailment only when:

- available POA-derived power materially exceeds actual PV; and
- export is disabled or the FIT is zero/negative.

The estimated curtailed power is integrated and added back to the day's actual generation for forecast calibration. This prevents negative-price curtailment from being learned as cloud or a poor solar day.

The resulting low, expected, and high solar scenarios have different uses:

- **Low:** firm EV/hot-water commitments and evening battery readiness.
- **Expected:** normal economic dispatch.
- **High:** awareness of possible excess production without depending on it for required energy.

## Battery dispatch

- Positive battery target means discharge; negative means charge.
- `site_export_target_kw` is separate from `battery_power_target_kw`.
- Node-RED translates the desired site export using live PV and household load.
- Commands are applied at the full validated target immediately; there is no artificial command ramp delaying a five-minute FIT response.
- Battery discharge is shaped up or down across forecast prices according to available stored energy and future retained value.
- Battery discharge is never scheduled below the live SAJ floor or the configured 5% hard minimum.
- During forced discharge, PV charging is disabled before discharge is enabled.
- A post-command signed SAJ battery-power sample confirms physical direction and minimum response.

## Tesla charging

The local controls are:

- `number.tesla_ble_039d9c_charging_amps`
- `switch.tesla_ble_039d9c_charger`

Charging is three phase at approximately 247 V per phase, using 6–16 A, or roughly 4.45–11.86 kW.

Policy:

- `Unanswered` and `No trip` are direct-solar-only modes.
- Direct-solar charging is capped to conservative surplus after household load and hot water.
- `Local / 50 km`, `100 km`, `200 km`, or a positive custom distance creates an explicit departure requirement.
- Deadline fallback is allowed only for an explicit trip when solar alone is insufficient.
- A fallback/mixed EV slot cannot discharge the stationary battery. Solar or grid must supply the shortfall.
- The Home Assistant actuator independently rejects fallback unless a trip is explicit and `input_boolean.battery_discharge` is off.

## Hot water

- The element is modelled as a 3.7 kW binary load.
- It receives three hours in minimum 15-minute dwell blocks.
- Blocks are selected by lowest opportunity cost, including negative FIT periods and otherwise-curtailed solar.
- It should finish before the predicted evening crossover and never later than 4pm.
- An independent Home Assistant latest-start fallback still delivers the required service if the optimiser is unavailable.

## Notifications

The iPhone receives physical-event notifications through `notify.mobile_app_iphone` when:

- the battery genuinely starts selling to the grid;
- the Tesla genuinely starts charging;
- the hot-water element starts;
- hot water reaches three delivered hours for the day.

Notifications use sustained physical measurements and session-aware suppression rather than merely reporting a requested command.

## Dashboard

Open the Home Assistant **Energy Optimizer** dashboard at:

`http://10.0.2.72:8123/energy-optimizer-dashboard/overview`

It shows current action and reason, Amber prices, SOC trajectory, battery/site targets, expected economics, both solar crossovers, EV and hot-water plans, and the local solar-potential model.

Solar-specific telemetry:

- `sensor.energy_optimizer_solar_potential`
- `sensor.energy_optimizer_solar_actual`
- `sensor.energy_optimizer_solar_curtailed`

## Safety and control authority

- Home Assistant mode must be `Active`.
- Rollout approval and the relevant subsystem gate must be on.
- Manual override must be off.
- Plans older than ten minutes or beyond their interval expiry are rejected.
- Missing/stale SOC heartbeat, PV, or load telemetry prevents battery actuation.
- Conflicting force-charge/force-discharge modes are rejected.
- Plan expiry has a dedicated one-shot safe-stop as well as the periodic watchdog.
- Former Amber, fixed-reserve, sunrise/10:30, hot-water, and Tesla control authorities remain disabled to prevent competing writers.
- Low-level helper-to-SAJ bridge automations remain enabled as hardware translators.

## Deployment and validation

Production service:

- Host: `10.0.1.204`
- Container: `energy-optimizer`
- Health endpoint: `http://127.0.0.1:8785/healthz`
- Readiness endpoint: `http://127.0.0.1:8785/readyz`

Before deployment:

1. Run the complete Python optimiser test suite.
2. Run the Node-RED guard tests when actuator contracts are touched.
3. Validate JSON/YAML and whitespace.
4. Preserve unrelated worktree changes.
5. Deploy with `deploy/scripts/energy-optimizer-sync --apply`.
6. Confirm container health, zero unexpected restarts, connected HA stream, and a fresh plan.
7. Verify the physical outcome—not only the requested command—when hardware behaviour changes.

## Important implementation locations

| Area | Location |
|---|---|
| Optimiser | [`apps/energy-optimizer/energy_optimizer`](../apps/energy-optimizer/energy_optimizer) |
| Tests | [`apps/energy-optimizer/tests`](../apps/energy-optimizer/tests) |
| Node-RED guard and flow | [`apps/energy-optimizer/node-red`](../apps/energy-optimizer/node-red) |
| HA dashboard and automation exports | [`apps/energy-optimizer/home-assistant`](../apps/energy-optimizer/home-assistant) |
| Deployment script | [`deploy/scripts/energy-optimizer-sync`](../deploy/scripts/energy-optimizer-sync) |
| Docker Compose | [`infra/energy-optimizer/docker-compose.yml`](../infra/energy-optimizer/docker-compose.yml) |

## Change log

### 2026-08-12

- Created this dedicated living energy-automation guide.
- Documented the production optimiser, five-minute Amber fast path, price-shaped full-power battery dispatch, guarded Node-RED actuation, EV solar-only/fallback policy, hot-water scheduling, iPhone notifications, and dashboard.
- Added the 11.8 kWp north plus 24.78 kWp south two-plane solar model, local irradiance correction, and curtailment-independent solar learning.
