# Home Energy Automation

This folder is the living, human-readable guide to the home's energy automation. It describes what the system is trying to achieve, how decisions are calculated, what is currently deployed, and how to operate or extend it safely.

The standalone replacement is in
[`apps/standalone-energy-manager`](../apps/standalone-energy-manager/README.md).
The former Home Assistant/Node-RED implementation remains in
[`apps/energy-optimizer`](../apps/energy-optimizer/README.md) only as a preserved
rollback artifact. It is no longer a live control authority.

This guide documents the current repository contract. It must not be read as
proof that a particular immutable release has been deployed or physically
accepted. Release identity, live Home Assistant/Node-RED state, and observed
grid/battery/load telemetry are separate evidence.

## Documentation rule

**Every material energy-automation change must update this README in the same commit.**

## Standalone 0.4.0 control and dashboard contract

Release `0.4.0` is the current repository contract. The independent manager is
the sole automatic writer for the SAJ inverter, Tesla BLE charger and hot-water
relay. Home Assistant, Pilot, MQTT, InfluxDB and Node-RED are optional consumers;
none is required for local planning, actuation or watchdog containment. A live
deployment must still be checked by its immutable release identity and physical
telemetry rather than inferred from this document.

The standalone web dashboard and Home Assistant
`/energy-control/overview` are paired surfaces over the same manager state:

- both show the manager's live conserved energy flow, schema-v3 plan, export
  economics, Amber forecast, flexible-load schedule and server-rack telemetry;
- both expose minimum battery sell price, opportunistic EV FIT ceiling, Tesla
  charge limit, EV grid permission, optimiser enable and the same EV trip
  profiles: `No trip`, `100 km`, `200 km`, `Charge to 80%`, and `Ensure 100%`;
- the internal UI and Home Assistant use the authenticated REST settings API;
  the manager remains the source of truth and Home Assistant refreshes it every
  two seconds; and
- MQTT remains publish-only while anonymous broker access exists. No dashboard
  sends an MQTT command or recreates a legacy SAJ/EV/hot-water writer.

The rolling 36-hour plan uses schema v3. Its narrative provides a current
summary and ordered next actions. Every interval can carry an authoritative,
conserved graph of edges between solar, battery, grid, ordinary house,
server rack, hot water, EV and an explicit unaccounted residual. Summary and
export-window values separate solar export, battery export, battery gross
revenue, wear cost, retained-energy value, battery net benefit and total export
revenue. Realised five-minute and daily reporting remains separate from these
forecasts.

Valuable morning FIT may defer PV battery charging while a confidence-adjusted
later-solar budget (90% of the calibrated forecast with a 5% energy margin)
still reaches the evening SOC target and contains a genuinely cheaper charging
block. The separate 75% low-solar case continues to protect stored battery
energy from export. The solve exports morning surplus, then begins charging at
the calculated latest safe point as later headroom shrinks. Stale Amber data
releases the hold immediately.

Five-minute outcome rows are the reporting source of truth. Daily energy and
currency fields are additive, power/price/confidence fields are
duration-weighted, balance error keeps the daily maximum, and the current
Brisbane day is rebuilt from interval rows whenever the service starts.

Read-only NUT polling adds server-and-desk input power, UPS state, confidence and
daily energy. The rack is modelled as an identified sub-load of ordinary house
consumption in the live graph, the forecast and InfluxDB outcomes. A valid UPS
efficiency converts output real power to estimated input power; otherwise the
manager reports the raw output with degraded confidence rather than fabricating
precision.

SQLite persists settings, plans, command evidence, controller leases and the
InfluxDB outbox. Influx reporting is write-through and non-blocking: an absent or
unavailable scoped token retains rows locally for replay without affecting
control. Pilot Core polls a timestamp-ordered, read-only cache of snapshot data
every two seconds and the full plan every 20 seconds or when plan identity
changes. Pilot never actuates the manager.

Every material command has an expiry. EV and hot-water leases are renewed while
their loads are authorised. A one-second watchdog restores safe SAJ
self-consumption, stops flexible loads and clears expired leases when a forced
action expires; failed containment is retried. Safe state keeps the battery
available for ordinary house load and retains anti-reflux only while a fresh
live Amber FIT remains negative.

The manager is the sole live Tesla BLE API client. Home Assistant's checkpointed
direct Tesla BLE and legacy hot-water ESPHome config entries are disabled: the
first otherwise competes for the bridge's API connection, while the second no
longer matches the pinned controller's authenticated HTTP interface. Home
Assistant receives their state from the manager through MQTT/REST. The SAJ Home
Assistant integration remains enabled for read-only native telemetry and UI.

The primary house-load source remains the SAJ backup real-power register because
the entire site is on the backup circuit. The dedicated SAJ battery-power
register remains authoritative for battery direction. Total PV plus PV1 north
(11.8 kWp), PV2 south (8.26 kWp) and PV3 south (16.52 kWp) remain separate for
forecast validation. Curtailed observations are visible but are not eligible for
forecast calibration.

The hot-water controller's exact ESPHome rollback definition and pinned custom
firmware build remain preserved. The custom firmware supplies authenticated
state/commands, a renewable controller lease and its outage-safe local fallback.
The manager uses local Tesla BLE for control; TeslaMate is retained telemetry and
Fleet control remains disabled.

Sections below that explicitly say **retired**, **legacy**, or **rollback**
describe the former Home Assistant/Node-RED implementation for forensic and
recovery purposes. They are not current control instructions.

## Standalone migration status — 2026-08-25 cutover record

- Proxmox HA LXC 103 (`energy-manager`, `10.0.1.205`) runs two hardened
  services: an independent control core on loopback and a dashboard/proxy on
  port 8787. Standalone production control was enabled at 20:19 AEST on
  2026-08-25.
- The LXC is an unprivileged Debian 13 guest with 2 vCPU, 2 GB RAM and 16 GB
  local ZFS. One-minute replication to `pvemini2` is healthy; strict HA node
  affinity prefers `pvedell` and automatic failback is disabled.
- Direct two-second SAJ polling, Amber, AEMO comparison, Ecowitt irradiance,
  Solcast, Forecast.Solar, TeslaMate MQTT and direct ESPHome API telemetry are
  operational without Home Assistant or Node-RED.
- Direct Tesla and hot-water communication uses the ESPHome 2026.8-compatible
  `aioesphomeapi` 45.x client. A transient Tesla bridge value of zero can never
  overwrite the configured 50–100% charge limit.
- SQLite WAL persists settings, plans, command evidence, five-minute outcomes,
  daily rollups and the Influx reporting outbox. MQTT publishes retained state
  and Home Assistant Discovery; MQTT commands are not accepted.
- The cutover-era immutable release `standalone-0.2.9` added semantic command identities,
  schema-v2 source/dispatch timestamps, explicit actuator readiness, forecast
  cache/retry, interval-aligned Amber/AEMO comparison and per-load live source
  allocation. It also promotes cached Amber advanced-price intervals at the
  exact five-minute boundary, while a fresh live interval supersedes them, and
  prevents negative FIT alone from starting hot water without enough solar.
  Restart and HA migration restore a persisted plan only when its expiry,
  software revision and effective configuration still match; otherwise the
  first fresh telemetry forces a replacement plan.
  A process-level exclusive lock complements Proxmox fencing and rejects any
  second controller inside the active guest before it can open a SAJ session.
  The live export gate applies the dashboard sell floor and independently
  requires FIT to beat retained import-avoidance value, wear and uncertainty;
  the user floor can never make an otherwise loss-making export eligible.
  Direct Amber feed-in values are converted from retailer billing sign to the
  customer convention: positive earns export revenue and negative means paid
  export. One-second API boundary skew is normalized to the exact NEM interval.
- Hot-water firmware 0.2.4 builds reproducibly for the existing ESP8285 and
  keeps controller-confirmed element seconds separate from its outage-only
  relay-time proxy. Absolute confirmation sync is idempotent, both state and
  command endpoints require the local bearer token, and the latest-start
  fallback remains independent of the LXC. The pinned Tesla BLE configuration
  also passes ESPHome 2026.8.1 validation with its five-minute local lease.
- Influx data is retained in the SQLite outbox whenever the configured scoped
  writer is unavailable. The service does not require InfluxDB or MQTT
  availability to continue planning and local control. Secret values are never
  recorded in this repository or runbook.
- Both legacy Node-RED energy-control tabs and 50 Home Assistant control
  automations were removed after a verified checkpoint. Node-RED now retains
  only the read-only POA-to-MQTT flow. Home Assistant's SAJ integration remains
  enabled at the operator's request for native entities and UI, while all
  automatic SAJ/EV/hot-water writers remain removed. Do not manually change an
  SAJ control entity while standalone production control is enabled.
- The production cutover physically confirmed normal SAJ self-consumption,
  battery-backed house load, near-zero grid exchange and a stable Tesla BLE
  start at 6 A. The EV drew approximately 4–5 kW and its five-minute command
  lease renewed without on/off chatter during the observation window.
- Rollback evidence is stored in Home Assistant at
  `/config/backups/standalone-cutover-20260825T2010/` and in LXC 103 at
  `/var/lib/energy-manager/backups/standalone-cutover-20260825T2010/`.
- A controlled HA migration to `pvemini2` and back to preferred `pvedell`
  preserved the same SQLite plan and restored both healthy services. Hot-water
  custom firmware flashing, negative-FIT zero-export verification,
  hot-water actuation, negative-FIT zero-export under the standalone authority,
  and stepped 5–30 kW battery commissioning remain
  physical acceptance gates; no host reboot or failure test is authorised by
  this rollout.

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
5. Supply every site load from solar first, then the stationary battery down to
   its 5% hard floor; grid is the last resort when energy or inverter power is
   physically insufficient.
6. Run hot water for three confirmed hours at the lowest-opportunity-cost time;
   it is never skipped merely because a perfect solar window did not occur.
7. Charge the Tesla from genuine solar surplus where possible, then the house
   battery, with grid used only for an otherwise infeasible deadline.
8. Treat import avoidance as a service priority rather than an arbitrage test:
   the configurable sell floor gates battery-to-grid export only.
9. Curtail solar instead of paying to export during negative FIT periods after useful flexible loads and battery charging have been considered.

“Fully cycle the battery” is a profit-led target, not permission to destroy value by exporting into poor prices.

## System architecture

```text
Amber / AEMO / forecasts / irradiance / TeslaMate / NUT
                              │
                              ▼
        Standalone Energy Manager, LXC 103 (10.0.1.205)
        ┌─────────────────────────────────────────────┐
        │ planner + policy + command owner            │
        │ direct SAJ Modbus / Tesla BLE / hot water   │
        │ SQLite plans, leases, evidence and outbox   │
        └─────────────────────────────────────────────┘
             │              │               │
             ▼              ▼               ▼
     web dashboard     MQTT / Influx     Pilot cache
                            │
                            ▼
                  Home Assistant dashboard
                  and authenticated settings
```

- The core recalculates a rolling 36-hour plan at least every five minutes;
  price, vehicle, flexible-load and material telemetry changes can wake it
  sooner.
- One direct SAJ connection owner serializes Modbus polling and writes, hashes
  semantically equivalent commands and verifies readback after material changes.
- The manager controls Tesla charging through local BLE and hot water through
  the pinned controller API. It does not call Home Assistant or Node-RED to
  actuate either load.
- SQLite is the durable control state. MQTT, InfluxDB, Pilot and Home Assistant
  may all be unavailable without stopping local operation.
- Proxmox HA fencing plus the guest's exclusive controller lock prevent two
  active SAJ writers. Node-RED contains no live energy actuator tab, and Home
  Assistant retains the SAJ integration for telemetry/manual UI only.

## Versioned plan contract

### Current standalone schema v3

The full plan is returned by `GET /api/v1/plan` and referenced from the live
snapshot. It includes:

- `schema_version: 3`, plan identity, generation/expiry times, software and
  configuration revisions;
- `narrative.current_summary`, ordered `narrative.next_actions`, and grouped
  `Now`, `Next`, `Today` and `Overnight` explanations;
- a protected reserve and predicted SOC path;
- planned hot-water and EV blocks, export windows and a summary covering
  forecast consumption, solar/battery/grid energy and financial outcomes;
- canonical battery/solar export kWh, battery gross revenue, wear cost,
  retained value, battery net benefit and total export revenue; and
- per-point `flow` graphs with explicit sources, sinks, directed kW edges,
  totals, meter-balance residual, confidence and conservation state.

The flow graph is authoritative when present. A client may infer allocation only
for a legacy schema-v2 payload and must visibly mark that fallback. The generic
flow object's own internal schema revision is independent of the plan schema.
Missing or stale values are shown as unavailable, never silently converted to
zero.

Commands are narrower than plans. Each includes source and dispatch timestamps,
expiry, configuration/software identity and a semantic command hash. An
equivalent physical command keeps its confirmation without rewriting the
inverter. Forced export, grid charge and active flexible-load commands are
leased; expiry invokes the complete safe-state watchdog transaction.

### Retired schema-v2 Home Assistant/Node-RED contract

The remainder of this subsection records the pre-cutover actuator contract for
rollback archaeology only. It must not be used to configure the standalone
manager.

The historical calculation, forecast, battery, Tesla, curtailment, hot-water
and notification sections that follow, through `Notifications`, belong to that
retired implementation. They preserve rationale and acceptance evidence; where
they name Home Assistant entities, Node-RED flows or `energy_optimizer`, they do
not describe the standalone control path. The current `Dashboard` section then
resumes the release-0.4.0 contract.

Compact command sensors are published first and
`sensor.energy_optimizer_plan` is the complete actuator contract and is
published first. Compact command/dashboard mirrors follow, so Amber actuation
does not wait for non-authoritative entity updates.
That retired actuator contract was schema v2:

- `schema_version: 2`, unique `plan_id`, generation/expiry timestamps, active
  interval, action/reason, and confidence;
- `battery_mode`: exactly `hold`, `self_consume`, `pv_charge`, `grid_charge`,
  or `export`;
- signed `battery_power_target_kw`, where positive is discharge and negative
  is charge;
- non-negative `battery_charge_target_kw` and
  `battery_discharge_target_kw`, consistent with the signed target;
- separate `site_export_target_kw` and `protected_soc_pct`;
- `pv_export_command`, `live_fit_price`, `live_import_price`, and exact
  `price_interval_start`/`price_interval_end`;
- dashboard `minimum_sell_price` and wear-bounded `effective_sell_price`;
- `source_timestamps` for Amber FIT/import, SOC and its zero-power heartbeat,
  PV and its zero-power heartbeat, and home load; and
- `software_version` plus `config_fingerprint`.

The commit marker deliberately contains scalar contract/dashboard metadata,
not the large 36-hour interval array. It is hard-tested below a 12 KiB safety
budget for Home Assistant's 16 KiB recorder attribute limit. A full plan
publishes its horizon across the recorder-safe entities named by
`horizon_entity_ids`. Immediate Amber dispatch does not rewrite those unchanged
chunks: it publishes the complete plan first and then exactly six control
mirrors concurrently, for seven Home Assistant calls independent of horizon size. The
fast commit's `horizon_plan_id` points to the last committed full horizon.
Dashboard calculations require every advertised chunk and matching horizon ID;
otherwise they show unavailable rather than a misleading zero. The immutable
journal retains the lossless full plan.

Mode is the actuator authority; human-readable `action` is not. `export` is
the only mode that can enable forced battery discharge. `grid_charge` is the
only mode that can enable grid force-charge. `pv_charge` permits PV charging
without grid force-charge. `self_consume` may describe a positive forecast
battery component for house support, but Node-RED never converts that into
forced export. `hold` means no forced arbitrage: both force switches remain off
while normal household self-consumption and PV charging stay available down to
the protected reserve. Because SAJ reserve is whole-percent, every active mode
writes `ceil(protected_soc_pct)` (clamped to 5–100%), so 39.7% becomes 40%
rather than 39%.

Node-RED is also the sole direct owner of
`number.saj_battery_discharge_power_limit_input`. Every accepted mode and every
safe-stop keeps the normal 1000 allowance: the optimiser never latches the
battery to zero, so it can cover ordinary household demand whenever SOC is
above the protected reserve. Exclusive force switches still own grid charging
and battery export. PV charging remains enabled in every mode. The
writable number is an optimistic 0–1100 view, while the independent
`sensor.saj_battery_discharge_power_limit` reports 0–110%. The guard requires
an explicit percent unit, normalizes the sensor by multiplying by ten, rejects
missing/ambiguous/out-of-range readback, and requires a post-command physical
sensor report whenever the target changes.

The guard rejects replayed/stale plans, source or price staleness, an expired
settlement window, live-price disagreement, invalid signs/components, unsafe
SOC, unavailable sensors, conflicting modes, and values beyond limits. Its
latest-wins lock covers the complete physical transaction: it stops old force
modes, applies reserve/limit/rate/export/PV writes through one ordered Modbus
chain, rechecks the active identity, and only then enables at most one forced
mode. The lock is released after the
last service succeeds. The 15-second direction and later target observers are
asynchronous; a stale observer is silent and cannot reassert or safe-stop a
newer command. Once an export transaction has final physical confirmation, a
same-mode target-only update uses one direct discharge-percentage write; any
other changed or uncertain invariant falls back to the complete transaction.
Persistent current-command mode, direction, or target disagreement safe-stops
the inverter.

The independent 60-second watchdog revalidates plan expiry, control gates,
prices, source freshness, and physical actuator state. For the same current
commit, matching registers, switches, and helpers are a true no-op: it emits no
status and preserves `feedback_confirmed` readiness. Only measured physical
drift causes a full correlated reassertion. A changed commit follows the normal
write path, while the replaceable `valid_until` one-shot remains the exact
expiry authority.

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

Battery export must clear the dashboard minimum sell price, the $0.08/kWh
marginal wear allowance, and the value of retaining that energy for a better
interval. The active floor is the greater of the dashboard value and wear. For example, a
$0.07085/kWh FIT cannot request battery export at any SOC. The battery may
still supply only the household deficit when doing so avoids a higher import
price; that is `self_consume` with a zero site-export target, not selling.

The 0.25 kWh DP lattice is coarser than a five-minute household-energy tranche:
its smallest five-minute discharge is 2.7 kW. Dispatch therefore performs a
continuous-power marginal pass after intertemporal optimisation. Whenever FIT
is below the active sell floor, it caps discharge to inflexible household load remaining
after PV; EV and hot water never enlarge that allowance. It starts from the
exact input SOC, not the rounded display value, and sequentially recalculates
SOC, grid flow, curtailment, and cashflow. The exact initial stored-energy point
is included in the DP lattice, preserving absolute evening targets and SOC
continuity. A profitable household tranche can no longer be bundled with
loss-making export. The morning SOC objective is not a hard upper constraint
and cannot force value-destroying discharge.

Amber interval prices are duration-weighted over each optimiser slot. A slot
that overlaps multiple five-minute prices therefore receives the correct
time-weighted value instead of an unweighted mean. The nominal battery capacity
is fixed at 47 kWh: telemetry may reconcile estimated stored energy with SOC,
but cannot silently redefine the physical capacity.

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

The current solver is a deterministic discrete dynamic programme using a
0.25 kWh stored-energy grid. It is not a continuous LP/MILP and does not use
HiGHS, so its answer is not a certificate of a globally optimal continuous
solution. A future solver change requires constraint-parity tests, replay and
runtime evidence, and renewed physical acceptance.

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
- Node-RED translates an export-mode site result using fresh telemetry as
  `site target + live load - live PV`, then clamps it by the plan discharge
  target, live helper cap, verified 28 kW limit, SOC protection, and any
  stricter SAJ/site limit.
- The first command for a new five-minute Amber interval and every safety stop
  are immediate. Within the same interval, ordinary export target corrections,
  stops, and restarts are limited to one physical battery-power change every
  60 seconds. Held plans advance plan identity and expiry without replaying a
  register write or toggling the force switch; this is a hold, not a gradual
  ramp. Fresh negative FIT bypasses the hold and curtails immediately.
- Settled export feedback is measured against the requested site export using
  the two-second SAJ grid meter. Battery power is still used to prove safe
  discharge direction, but moving PV/load is reported as a deviation and left
  for the next permitted planner update rather than replaying the same command.
- Battery discharge is shaped up or down across forecast prices according to available stored energy and future retained value.
- Morning solar is not automatically diverted into the battery. When FIT is
  valuable and the confidence-adjusted later-solar budget can still reach the
  evening SOC target, the optimiser exports morning surplus and defers charging
  until the calculated latest safe, lower-FIT period. The stricter low-solar
  case remains the battery-export reserve and the lost FIT is the charging
  opportunity cost.
- Battery discharge is never scheduled below the live SAJ floor or the configured 5% hard minimum.
- For a live site deficit, the fast path uses the 5% hard floor and covers
  normal house demand first. It may cover the explicitly authorised EV tranche,
  but it never assigns stationary-battery energy to hot water. A higher
  protected trajectory still governs optional battery export.
- PV battery charging remains enabled in every normal mode. During negative
  FIT, solar supplies active loads first, charges the stationary battery next,
  and only the remainder is curtailed at the inverter.
- During forced discharge, PV charging is disabled before discharge is enabled.
- A post-command signed SAJ battery-power sample confirms physical direction and minimum response.
- A fresh zero-PV or zero-battery-power reading remains valid because separate
  heartbeat timestamps prove the telemetry stream is alive; zero is not
  mistaken for a missing sensor update.
- An immediate Amber reprice inherits the committed full plan's dynamic
  `protected_soc_pct`. It may become more conservative, but can never reduce
  that reserve to the nominal 7% morning target. Fast-path export availability
  is calculated only from energy above the inherited reserve.
- Amber feed-in and import events are coalesced for 250 ms so one five-minute
  interval is committed atomically instead of briefly applying a mismatched
  price pair. Node-RED has a separate direct edge only for signed-negative FIT,
  allowing emergency zero export immediately; positive repricing waits for the
  optimiser's committed plan.
- A partial, stale, or non-overlapping FIT/import pair still publishes an
  explicit non-actuating `safe_hold`: battery and site targets are zero, the
  dynamic protected reserve is retained, and unknown price/window fields remain
  null. Publishing this fail-closed commit lets Node-RED cancel a previous
  forced mode immediately; suppressing it would leave the older command alive
  until expiry.
- With a valid pair, household supply remains a physical priority regardless of
  short-term price revisions. Battery-to-grid export is rechecked independently
  against live FIT, the editable sell floor, wear, and future retained value.

## Tesla charging

The verified controls and physical proof are:

- `number.tesla_ble_039d9c_charging_amps`
- `number.tesla_ble_039d9c_charging_limit`
- `switch.tesla_ble_039d9c_charger`
- `sensor.tesla_wall_connector_total_power`

Charging is three phase at approximately 247 V per phase, using 6–16 A, or roughly 4.45–11.86 kW.

Local BLE is the preferred start/stop/current/limit path. Tesla Fleet is a
paid last-resort fallback that is disabled by default and requires its explicit
dashboard helper plus fresh Fleet telemetry; fresh wall-connector power is the
independent proof of charging. Routine commands and the first safety stop use
BLE only. Fleet is called only when its explicit fallback is enabled and BLE is
unavailable or wall power remains after a BLE stop for 15 seconds. This prevents both a Tesla cloud entity outage
and avoidable paid Fleet API traffic from wasting an energy window.

Policy:

- The current protected battery floor is calculated backwards from the next
  morning solar takeover using conservative PV and ordinary household load.
  It reserves enough energy for the house to reach the approximately 7% morning
  target; EV and hot-water demand cannot consume this tranche.
- A confirmed direct-solar EV session survives rolling planner withdrawal while
  fresh expected roof output still supports at least 6 A, signed live FIT is at
  or below 1 c/kWh, telemetry and controls are healthy, grid import is no more
  than 0.3 kW, and battery use remains within the committed plan allowance.
  The rate continues to follow expected PV and the fast feedback trims it down;
  any failed condition stops it on the next 15-second evaluation.
- Battery-support authorization compares the SAJ stationary-battery SOC, not
  Tesla SOC, with the dynamic protected house reserve. This avoids false stops
  during short solar dips while a below-40% Tesla is charging.
- If solar falls and stationary-battery discharge rises above the committed
  house/battery target by more than 0.3 kW, the EV current is reduced by the
  equivalent three-phase amps instead of switching the charger off. A mandatory
  below-40% session may settle at the 6 A vehicle minimum only while the SAJ
  battery remains at least one percentage point above the protected reserve.
- Live EV current is feed-forward from 92% of the fresh north-plus-south POA
  expected output, less measured non-EV site load and the start/run margin.
  Actual PV is only the fallback when either expected-output sensor is stale.
  Fast grid and stationary-battery feedback attenuate the calculated amps;
  they no longer determine the initial rate. This allows the car to consume
  solar that is presently hidden by inverter curtailment.
- The planner uses the same attenuated roof expectation to grant the current
  negative-FIT interval permission to charge even when conservative P10 or
  curtailed actual PV sits just below the Tesla's 6 A minimum. Future intervals
  remain forecast-scheduled; actual grid/battery feedback governs the live rate.

- A connected Tesla below 40% immediately starts a mandatory 7am departure-reserve
  requirement under the single `No trip / opportunistic` state. With grid
  charging disabled, the optimiser may use house-battery
  energy above its protected floor for only the shortfall to 40%. The live
  import trim remains active.
- Above 40%, `No trip / opportunistic` is non-mandatory and never creates a
  grid or stationary-battery requirement.
- The unified no-trip state has no additional mandatory trip energy above 40%, but it may opportunistically use
  exceptionally low-FIT solar up to `number.tesla_ble_039d9c_charging_limit`
  when the conservative forecast still refills the house battery. Its 7am
  departure is advisory: later negative-FIT horizon slots remain eligible if
  the car is still physically home and connected.
- Direct-solar charging is capped to conservative surplus after household load and hot water.
- `Local / 50 km`, `100 km`, `200 km`, or a positive custom distance creates an explicit departure requirement.
- Grid deadline fallback is allowed for an explicit trip or the mandatory
  below-40% minimum when solar and protected house-battery energy are
  insufficient and `input_boolean.energy_optimizer_ev_allow_grid` is on. With
  that switch off, the scheduler creates only direct-solar blocks above 40%;
  below 40%, it may add the protected house-battery reserve tranche described
  above. The live governor trims or stops charging when the fast SAJ meter sees import.
  The switch is a native UI helper, defaults off, and restores its last value.
- Physical stationary-battery discharge is compared with the battery target
  from the exact same committed plan. The EV stops if discharge rises more than
  0.3 kW above that independent house/export allocation. This lets the battery
  keep covering house load or exporting at valuable FIT while solar or grid
  supplies the EV. The sole exception is the explicit below-40% reserve source,
  whose discharge is already included in the committed battery plan.
- The Home Assistant actuator independently requires production/EV gates, a
  fresh committed plan and telemetry, the local BLE control link, and a vehicle that
  is connected and home.
- The actuator reads the EV action from the optimiser sensor state and the
  source from `charge_source`; it derives the available three-phase current as
  `solar kW × 1000 / (3 × 247 V)`. This avoids treating a live solar plan as
  idle or underestimating the available current.
- It subtracts measured EV power from inclusive home load before calculating
  headroom, avoiding a self-canceling solar-surplus calculation.
- A live FIT spike immediately pauses non-mandatory charging so valuable solar
  and battery energy can export.
- Charger decisions are serialized, preventing rapid SAJ updates from racing
  stale turn-on/turn-off service calls. Normal start ordering is local BLE
  current-limit reassertion, then charge. A recorded 90-second start session
  allows the physical contactor to close. Fresh wall-connector power, rather
  than an optimistic integration switch, is the final confirmation. Every stop
  reason uses BLE containment first; Fleet is attempted only under the explicit
  healthy paid-fallback gate if BLE containment fails. Stop reassertions have a
  45-second cooldown and sleeping-car
  wakes a 60-second cooldown; an already-off, zero-power car makes no Tesla API
  call, preventing telemetry bursts from triggering Fleet rate limits.

## Negative-FIT curtailment

The SAJ integration's `Export Limit (Input)` is the correct zero-export
control, but its value only takes effect when anti-reflux mode is enabled.
The installed integration was extended with
`number.saj_anti_reflux_mode_input`, which writes register `0x365C`.

For every negative-FIT interval, the optimiser publishes
`pv_export_command=curtail` unconditionally. Flexible-load or battery decisions
do not weaken that site-export requirement. The guarded Node-RED transaction,
not a competing Home Assistant writer, applies:

| SAJ setting | Value | Meaning |
|---|---:|---|
| Anti-reflux mode | 1 | total-power anti-reflux |
| Export limit | 0 | no site export |
| Grid maximum discharge | 1100 | does not constrain normal solar self-consumption |
| Battery PV charge limit | 1000 | verified full 30 kW solar-to-battery capability |

The inverter itself then follows the instantaneous load. This keeps the house,
Tesla and hot water supplied from solar where available, opens the stationary
battery to the full verified 30 kW PV-charge rate, and imports only the small
remainder while holding export at zero during a negative FIT. The optimiser's
instantaneous battery target remains useful forecast accounting but never
becomes a physical PV ceiling. Only solar remaining after loads, flexible loads,
and feasible battery charging is curtailed. This is more precise and less
wasteful than artificially limiting all inverter output.
When export is allowed again, the same sole writer disables anti-reflux and
restores both limits to 1100. The former Home Assistant curtailment automation
is retained only as inert rollback/reference configuration.

Zero export is used only for a fresh signed-negative FIT. A positive FIT below
the battery sell floor still allows all solar export. A stale or unavailable
FIT cancels forced battery action and restores normal export instead of
guessing that curtailment is required.

## Hot water

- The element is modelled as a 3.7 kW binary load.
- It targets three confirmed physical element-hours by 4pm. Every Brisbane
  local day whose 4pm deadline is visible in the horizon is scheduled,
  including tomorrow when the 36-hour plan crosses midnight. A partial third
  day at the tail is deferred until its real solar and deadline window enters
  the horizon, avoiding a fictitious early grid rescue.
- Physical confirmation uses a fresh SAJ whole-house load report received
  after the relay turns on and the element's 3.7 kW load signature. The
  dedicated `sensor.energy_optimizer_hot_water_confirmed_power` drives runtime,
  outcomes, notifications, and load disaggregation; the older phase-delta
  sensor is no longer trusted as the production confirmation source.
- Both the planner and live governor use
  `sensor.hot_water_confirmed_runtime_today`; the former relay-on timer is not
  a service-completion input.
- Blocks are selected from qualified direct-solar periods first, prioritising
  negative FIT. If those blocks cannot deliver the daily service, the latest
  feasible low-cost rescue blocks use grid for the element while the battery
  remains available to cover ordinary house load.
- `sensor.energy_optimizer_hot_water` remains `on`/`off` and exposes
  `control_mode`; the plan mirrors it as `hot_water_control_mode`. Values are
  `off`, `solar_surplus`, and `service_rescue`.
- `solar_surplus` removes measured element power from the inclusive home load
  and starts only after measured solar can supply the element, ordinary load,
  protected battery charging, and a 0.5 kW margin. It stops within 15 seconds
  when that solar qualification is lost.
- `service_rescue` covers planned low-cost non-solar blocks and the continuously
  evaluated latest-start guarantee. The hot-water element is grid-only during
  rescue; the house battery may simultaneously cover ordinary household load
  but is capped so it cannot supply the element. The service never gets skipped:
  rescue runs the remaining confirmed element time when solar opportunities are
  insufficient.
- Normal dwell protection is 15 minutes on and 5 minutes off. Source/telemetry
  failures and safety stops are immediate; startup reconciliation and a
  10-second watchdog prevent an orphaned element.
- The Flexible Loads dashboard shows the expected optimiser start, finish, and
  scheduled hours for the current hot-water plan.
- It should finish before the predicted evening crossover and by 4pm; a missed
  target becomes immediate recovery, never a skipped hot-water day.
- There is one hot-water production authority. The former independent
  latest-start automation remains disabled; the guarded actuator's
  `service_rescue` path replaces the competing fallback writer.

## Notifications

The iPhone receives physical-event notifications through `notify.mobile_app_iphone` when:

- the battery genuinely starts selling to the grid;
- the Tesla genuinely starts charging;
- the hot-water element starts;
- hot water reaches three delivered hours for the day.

Notifications use sustained physical measurements and session-aware suppression rather than merely reporting a requested command.

## Dashboard

Open the standalone dashboard at:

`http://10.0.1.205:8787/`

Open the UI-editable Home Assistant **Energy Manager** Sections dashboard at:

`http://10.0.2.72:8123/energy-control/overview`

These are two views of the same manager-owned state and settings, not two
schedulers. The internal dashboard presents the live house flow, solar strings,
battery, Tesla, hot water, server rack, current reason, human-readable next
actions, Amber curves, 36-hour plan and export economics. Home Assistant embeds
the manager's canonical flow/plan/price surfaces and adds native Sections cards
for the same telemetry and settings.

Settings available on both surfaces are:

- minimum battery sell price;
- opportunistic EV charging FIT ceiling;
- Tesla charge limit;
- EV grid permission;
- optimiser enable; and
- EV trip profile: `No trip`, `100 km`, `200 km`, `Charge to 80%`, or
  `Ensure 100%`.

The canonical wire setting is `ev_trip_profile`; `ev_trip_requirement` exists
only as a compatibility alias. Both dashboards use the authenticated standalone
REST API, and Home Assistant refreshes settings every two seconds. MQTT remains
publish-only. A dashboard setting change can therefore be made from either
surface without creating a second control authority.

Financial presentation distinguishes planned battery export energy, gross
revenue, wear and net benefit from solar export and from realised battery export
revenue/net benefit today. Server-and-desk power, daily kWh, UPS state and NUT
confidence are also visible. Presentation rounds SOC to one decimal, prices to
one decimal c/kWh, power below 1 kW to whole watts and larger power to one
decimal kW; the API retains full calculation precision.

Home Assistant is optional. Stopping it does not stop SAJ, EV or hot-water
control. Its SAJ integration remains available for telemetry and manual UI, but
must not be used as a concurrent automatic writer.

## Current safety and control authority

- The standalone manager is the only automatic SAJ, EV and hot-water writer.
- Proxmox fencing and the guest controller lock prevent concurrent manager
  ownership. Direct SAJ Modbus operations are serialized by one connection
  owner.
- Fresh live Amber FIT is the only dispatch price. AEMO is observational.
  Negative live FIT applies anti-reflux while leaving PV available to loads and
  battery; positive FIT never forces zero export.
- The 5% battery floor and protected overnight reserve are hard constraints.
  Safe state restores self-consumption rather than forcing the battery to zero.
- Material commands carry expiry and semantic identity. Equivalent commands do
  not churn the inverter. The watchdog contains expired forced modes and
  flexible-load leases, and retries a failed safe-state transaction.
- Home Assistant, Node-RED, MQTT, InfluxDB, Pilot and either dashboard may fail
  without interrupting local control.

## Retired Home Assistant/Node-RED safety contract

The bullets below document the pre-cutover guards for rollback evidence only.
They are not prerequisites or control instructions for standalone release
`0.4.0`.

- Home Assistant mode must be `Active`.
- Rollout approval and the relevant subsystem gate must be on.
- Manual override must be off.
- The schema-v2 plan, exact price interval, all required source timestamps, and
  live Amber prices must be current. Ten minutes is an absolute upper bound,
  not permission to outlive the active settlement interval.
- Missing/stale SOC, battery heartbeat, PV, PV heartbeat, or load telemetry
  prevents battery actuation.
- Conflicting force-charge/force-discharge modes are rejected.
- Disarming any production gate immediately republishes the Python battery
  contract as `hold` with zero signed, charge, discharge, and site-export
  targets. The economic horizon remains available for analysis, but no cached
  force mode survives in the command fields.
- `hold` and safe-stop cancel forced arbitrage without disabling normal battery
  self-consumption or PV charging.
- Plan expiry has a dedicated one-shot safe-stop as well as the periodic
  watchdog. Rejection and persistent feedback mismatch use the same complete
  safe stop.
- Former Amber, fixed-reserve, sunrise/10:30, hot-water, and Tesla control authorities remain disabled to prevent competing writers.
- The guarded Node-RED flow is the only SAJ writer. Home Assistant curtailment
  and battery-writer exports remain inert; HA hot-water and EV actuators own
  only their respective physical load.
- Node-RED is latest-wins, and every SAJ write is serialized through one ordered
  physical transaction; delayed physical feedback never blocks a newer Amber
  command. A fully confirmed same-mode export-rate change is a single direct
  percentage write. Optimistic writable state alone is not accepted where an
  independent SAJ sensor exists.

## Retired Home Assistant validated auto-resume

`input_boolean.energy_optimizer_production_expected` persists the operator's
intent, but never blindly rearms hardware after Home Assistant starts:

1. startup records the event, forces battery/hot-water/EV/rescue gates off,
   and selects Shadow;
2. it waits for the full SAJ entity contract, a fresh committed plan, fresh
   core telemetry, and the current actuator plan;
3. it restores the verified 28 kW discharge cap, enables subsystem gates, and
   selects Active last; and
4. it waits for a current accepted command. `export` and `grid_charge` require
   physical feedback confirmation, while passive modes require a current
   accepted/applied result.

Failure returns every gate to off and mode to Shadow before a later retry. If a
required SAJ entity disappears, the contract guard also enables manual override
and sends a critical iPhone notification. Entity recovery does not silently
clear that override. Manual override always wins over saved production intent.

The repository validates this state machine, entity contract, and templates.
A real Home Assistant restart and observed inverter/EV/hot-water response are
still required for each release; static validation is not physical acceptance.

## Current persistence and reporting

The standalone core stores plans, settings, command evidence, renewable leases,
five-minute outcomes, daily rollups and the reporting outbox in SQLite WAL. It
writes the following InfluxDB measurements when the scoped writer is available:

- `energy_power` for two-second site, PV-string, battery, load, flexible-load
  and server-rack power;
- `energy_battery` for SOC, SOH and stored/usable/extractable energy;
- `energy_price` for Amber and observational AEMO prices and latency;
- `energy_forecast` and `energy_command` for forecast/actuator evidence;
- `energy_nut` for raw UPS output, efficiency-adjusted server input power,
  runtime, battery, voltage, status and confidence;
- `energy_outcome` once per five-minute settlement interval; and
- `energy_daily` for realised revenue, imports, exports, wear, forecast error,
  EV result, hot-water completion and server-rack energy.

Writes pass through the durable SQLite outbox. Network failure, an unavailable
InfluxDB service or missing runtime credential must not block planning or
actuation. Secrets are supplied by root-owned runtime files and never copied into
this document, source control, MQTT or Home Assistant state.

## Retired optimiser learning, journals, and reports

Learning state is schema-versioned and date/timestamp deduplicated. Repeated
plans cannot overweight the same observation. Compatible learning is migrated;
unknown/incompatible state resets safely instead of poisoning forecasts.

The persistent data volume contains:

| Path | Purpose |
|---|---|
| `/data/latest-plan.json` | Latest complete plan snapshot. |
| `/data/plans/YYYY-MM-DD.jsonl.gz` | Immutable completed-day plan journal; active day is JSONL. |
| `/data/outcomes/YYYY-MM-DD.jsonl.gz` | Realized five-minute rows, including explicit gaps; active day is JSONL. |
| `/data/outcome-state.json` | Outcome recorder checkpoint. |
| `/data/acceptance-summary.json` | Daily plus rolling 7/30-day realized summaries. |
| `/data/learning-state.json` | Versioned calibrated solar/load learning. |

Retention defaults to 90 days. Completed plan/outcome journals are gzip
compressed before old files are pruned, rather than being discarded at
rollover. Fast Amber dispatch also journals the compact current interval with
the same version/provenance fields.

Current realized acceptance covers interval battery/grid/hot-water evidence.
EV SOC at departure, SOC at the exact morning/evening crossover, and a matched
realized baseline cash delta remain explicitly unassessed.

Historical replay carries one continuous optimiser SOC across all days and
values terminal stored energy once. Flexible loads are included in dispatch
cashflow only when Influx export supplies separate `base_load_kw`,
`hot_water_kw`, and `ev_kw` interval series with complete coverage. Legacy
inclusive-load data fails explicitly. Replay uses actual future inputs and is
therefore a perfect-hindsight upper bound, not a forecast backtest or physical
acceptance result.

## Retired optimiser deployment, releases, and rollback

Production service:

- Host: `10.0.1.204`
- Container: `energy-optimizer`
- Health endpoint: `http://127.0.0.1:8785/healthz`
- Readiness endpoint: `http://127.0.0.1:8785/readyz`

`/healthz` reports process/state-stream diagnostics. `/readyz` also requires a
fresh unexpired committed plan, connected Home Assistant state stream, and
healthy immediate-price worker. Neither endpoint proves an inverter or load
responded physically.

The deployment and rollback scripts are dry-run by default:

```bash
deploy/scripts/energy-optimizer-sync
deploy/scripts/energy-optimizer-sync --apply
deploy/scripts/energy-optimizer-rollback
deploy/scripts/energy-optimizer-rollback --apply
```

The sync script derives an immutable release ID from the Git SHA and content
hash, stages it at
`/opt/jarvis-home-ai/releases/energy-optimizer/<release-id>`, builds a tagged
image, validates Compose, starts it, waits for readiness, and only then changes
the `current-energy-optimizer` symlink. Manifests in
`/opt/energy-optimizer/releases/` record content/config hashes, image, previous
release, and staged/active state. Superseded images are retained for 720 hours
after success.

The sync scope is only the dedicated app and infrastructure directories. It
does not install Home Assistant YAML or import the Node-RED flow. Those require
a separately reviewed backup/import/validation step.

Rollback selects the previous manifest or an explicit release. Applied
rollback enables manual override, stops both battery directions and flexible
loads, restores safe anti-reflux/export/grid limits, activates the immutable
release, and deliberately leaves manual override on. Physical verification is
required before rearming. Never enable a retired writer while guarded Node-RED
remains active.

### Local validation

```bash
cd apps/energy-optimizer
uv run --extra test pytest
node --test node-red/guard.test.js
node node-red/build-flow.js
ruby home-assistant/validate-contract.rb
uv run --with PyYAML --with Jinja2 python home-assistant/validate-templates.py
docker compose -f ../../infra/energy-optimizer/docker-compose.yml config --quiet
git diff --check
```

### Secret and container boundaries

- The Home Assistant token comes from protected
  `infra/secrets/home_assistant_token`, is installed mode `0400` for service
  UID/GID 10003, and is mounted only as
  `/run/secrets/home_assistant_token`.
- Never place tokens, SSH passwords/private keys, or Influx credentials in
  source, plans, journals, reports, or deployment manifests. Replay reuses the
  existing `solar-monitor` container's scoped Influx access.
- The former plaintext Tesla SSH recovery path is disabled/inert. Any
  replacement must use approved key/secret-backed access.
- The optimiser container runs non-root and read-only, drops all capabilities,
  sets `no-new-privileges`, exposes the API on loopback only, and has only the
  data volume writable.
- Node-RED administration stays authenticated through protected Home Assistant
  ingress.

### Physical acceptance limitations

Unit tests, static/template validators, replay, journal coverage, HTTP 200,
`/healthz`, and `/readyz` are necessary but are not physical proof. Before
calling a release production-validated, observe and store release-tagged
grid/battery/load evidence for:

- Already observed on 2026-08-18: a direct zero battery discharge-power limit
  stopped approximately 4–5 kW of self-use discharge that the raised reserve
  and disabled force switches had not immediately stopped. A staged
  `self_consume` command then held the physical reserve at 40%, restored the
  normal discharge limit, kept both forced modes off, and settled grid exchange
  around 20–30 W.
- That observation validates only the direct limit, reserve readback, and
  passive-mode path. Representative daylight and price acceptance is still
  pending, including profitable export, PV/grid charging, immediate Amber
  interval changes/expiry, and negative-FIT daytime curtailment.

- all five battery modes, signed targets, reserve protection, and site-export
  translation;
- immediate five-minute FIT response, interval expiry, and exact negative-FIT
  zero export;
- EV direct solar, high-FIT pause, configured limit, and declared-trip grid
  fallback without house-battery discharge;
- hot-water solar-surplus/rescue behaviour, three measured hours, and 4pm
  completion;
- Home Assistant restart auto-resume, missing-contract failure, manual
  override, stale-plan safe stop, and immutable rollback.

## Important implementation locations

| Area | Location |
|---|---|
| Standalone manager | [`apps/standalone-energy-manager/energy_manager`](../apps/standalone-energy-manager/energy_manager) |
| Standalone dashboard | [`apps/standalone-energy-manager/energy_manager/web`](../apps/standalone-energy-manager/energy_manager/web) |
| Home Assistant paired dashboard/package | [`apps/standalone-energy-manager/home-assistant`](../apps/standalone-energy-manager/home-assistant) |
| Standalone tests | [`apps/standalone-energy-manager/tests`](../apps/standalone-energy-manager/tests) |
| Pilot read-only cache | [`apps/pilot-core/pilot_core/energy_manager.py`](../apps/pilot-core/pilot_core/energy_manager.py) |
| Retired optimiser rollback | [`apps/energy-optimizer`](../apps/energy-optimizer/README.md) |

## Change log

### 2026-08-26 — standalone-0.4.0 repository contract

- Unified the standalone and Home Assistant dashboards around one authenticated
  settings contract. Added the five EV trip profiles, opportunistic charging
  FIT ceiling, Tesla limit, grid permission, sell floor and optimiser enable to
  both surfaces; MQTT remains publish-only.
- Promoted the 36-hour plan to schema v3 with a human-readable narrative,
  authoritative conserved source-to-sink flow edges and explicit residual and
  confidence. Added planned solar/battery export energy, gross revenue, wear,
  retained value and net benefit alongside realised five-minute/daily results.
- Added NUT server-and-desk power, UPS state/confidence and daily energy to the
  live graph, plan, Home Assistant Discovery, dashboard and Influx reporting.
- Documented rolling morning-FIT charge deferral: export morning surplus while
  the confidence-adjusted later energy budget still has sufficient charge-rate
  headroom to reach the evening SOC target, with the stricter low-solar case
  retained for stored-energy export protection.
- Added durable command leases and the one-second expiry watchdog. An expired
  forced mode or flexible load is contained into safe self-consumption with EV
  and hot water off; containment retries if the first transaction fails.
- Checkpointed and disabled Home Assistant's superseded direct Tesla BLE and
  hot-water ESPHome entries, leaving SAJ enabled. This gives the standalone
  manager sole BLE command ownership and removes an obsolete reconnect loop;
  both Home Assistant dashboards continue to use manager-owned state.
- Added ten-second ESPHome reconnect backoff with full stale-client teardown.
  EV and hot-water actuator errors are now isolated, so either load can recover
  independently and neither failure overwrites a successfully applied SAJ
  command; readiness and explicit actuator-error fields still expose the fault.
- Connected Pilot Core through a timestamp-ordered read-only snapshot/plan
  cache. Home Assistant, Pilot, MQTT and InfluxDB remain optional to control.
- This entry records repository implementation and documentation. Deployment
  identity and physical acceptance must be verified separately; no deployment
  is asserted by this change.

### 2026-08-12

- Created this dedicated living energy-automation guide.
- Documented the production optimiser, five-minute Amber fast path, price-shaped full-power battery dispatch, guarded Node-RED actuation, EV solar-only/fallback policy, hot-water scheduling, iPhone notifications, and dashboard.
- Added the 11.8 kWp north plus 24.78 kWp south two-plane solar model, local irradiance correction, and curtailment-independent solar learning.
- Confirmed and regression-tested high-FIT morning solar export with battery
  charging deferred to lower-FIT solar periods when the evening target remains
  conservatively feasible.
- Added the expected hot-water operating window and scheduled hours to the
  Flexible Loads dashboard.

### 2026-08-13

- Fixed the EV actuator's plan-field mapping and three-phase solar-current
  calculation; verified the wall connector charging from the current
  direct-solar plan.
- Replaced blind negative-FIT curtailment with a verified SAJ anti-reflux
  control: mode 1 plus a 0 W export limit. Live validation showed inverter
  output at 1.194 kW against a 1.247 kW house load, i.e. it followed demand
  and avoided export rather than throttling the whole inverter.
- Re-enabled the Hot Water Control production gate and corrected the actuator
  dwell condition. Live verification: planned state on, switch on, 3.914 kW
  measured element power, and physical heating confirmation on.

### 2026-08-18

- Made Node-RED the direct sole owner of the SAJ battery discharge-power limit.
  The optimistic 0–1100 number is now checked against the independent percent
  sensor after strict ×10 normalization; missing, ambiguous, or stale changed
  readback fails closed.
- Ceiled active protected SOC to the inverter's whole-percent reserve
  (`39.7% -> 40%`), retained `ceil(live SOC)` for hold, and made generic
  safe-stop restore the 1000 normal self-consumption discharge limit.
- Recorded staged physical evidence that a zero discharge limit stopped the
  previously continuing 4–5 kW discharge and that `self_consume` held 40%
  reserve with no forced mode and roughly 20–30 W grid exchange. Profitable
  export, charging, interval-change, and representative daylight acceptance
  remain pending.
- Documented the schema-v2 plan/battery contract and made Node-RED's sole SAJ
  ownership explicit, including signed targets, the five battery modes, source
  freshness, settlement expiry, feedback verification, and unconditional
  negative-FIT curtailment.
- Unified hot-water rescue and EV source safety under their single guarded Home
  Assistant actuators; removed the obsolete claim that a competing hot-water
  fallback writer remains enabled.
- Added guarded production auto-resume, immutable release/rollback behaviour,
  secret/container boundaries, 90-day compressed plan/outcome journals, and
  realized 7/30-day acceptance summaries.
- Recorded the current discrete-DP solver and replay/realized/physical
  acceptance limitations so static validation cannot be mistaken for live
  proof.
- Split the large dashboard horizon into plan-ID-matched, recorder-safe sensor
  chunks and kept the schema-v2 commit marker below a tested 12 KiB budget, so
  Home Assistant can retain plan history without losing the 36-hour view.
- Added an exact $0.07085/kWh FIT regression for both full and immediate paths:
  battery export is blocked below the $0.08/kWh wear allowance, while
  import avoidance covers every scheduled site load. Disarmed plans now
  publish `hold` and zero command targets even if their retained forecast had
  previously requested export.
- Corrected the full 36-hour DP after live plan
  `eop-20260818T182406-3a1dfa3c` exposed a quantized mixed tranche: 1.32 kW of
  valuable household supply had been bundled with 13.764 kW of export at a
  $0.0706667/kWh FIT. Removed the hard morning-SOC upper constraint and added a
  continuous marginal export floor that preserves household supply but caps
  below-wear battery export to zero. The exact journal replay now gives 1.32 kW
  battery, 0.0 kW site export, and no below-wear export interval.
- Refined the marginal pass to anchor on exact input SOC. The latest source
  priority expands below-floor discharge to the complete site deficit after PV,
  including planned hot water and EV demand; high-FIT export remains separately
  gated. Added partial-interval, flexible-load, exact-start, SOC-continuity,
  evening-target, and high-FIT regression coverage.
- Fixed immediate Amber dispatch so a full-plan 39.9–40% dynamic protected
  reserve cannot transiently fall to the 7% morning target. Added both
  self-consumption and high-FIT tests proving the reserve remains monotonic and
  discharge is limited to energy above it.
- Classified incomplete Amber rollover pairs as explicit non-actuating
  `safe_hold` commits with zero targets, retained dynamic reserve, and truthful
  null price metadata so an older forced mode is cancelled rather than left to
  expire. For valid pairs, preserved a cached full-plan household tranche
  across small import-price revisions within the 2 c/kWh uncertainty margin;
  the observed 0.32103 to 0.318468 $/kWh rollover now remains
  `self_consume`, while materially lower import prices still hold for the next
  full solve.
- Removed the unchanged 36-hour horizon, solar, and acceptance writes from the
  immediate Amber critical path. Fast publication now sends the complete
  schema-v2 contract first, followed by six plan-ID-matched mirrors, while
  `horizon_plan_id` retains the last committed full forecast. Revision changes
  before the commit suppress it; changes during the final Home Assistant POST
  are reported superseded and the queued newer revision becomes the final
  state. The newly committed full plan also becomes the fast-path base before
  journal I/O, eliminating a post-commit stale-horizon race.
- Reworked the guarded Node-RED actuator so its lock covers physical writes
  only. Full transitions now stop forced modes, execute every prerequisite in
  one ordered Modbus chain, then
  force-enable and release the lock before asynchronous feedback. Confirmed
  same-mode export changes use one direct percentage write. Static topology
  and race regressions pass, but physical acceptance of this new write
  pipeline is still pending.
- Made the 60-second watchdog idempotent for an unchanged physically matching
  commit, so it no longer replaces `feedback_confirmed` with redundant
  requested/applied states each minute. It still reasserts real physical drift,
  accepts newer commits, and safe-stops invalid or expired plans. Physical
  acceptance of the watchdog change is pending.
- Stabilised profitable battery export: same-interval target corrections and
  ordinary stop/restart now change the physical discharge rate no more than
  once per 60 seconds. Held decisions use a true no-write actuator path. Amber
  interval rollover, expiry, negative FIT and safety actions remain immediate.
  Settled feedback uses the fast SAJ site-grid meter and reports load-driven
  deviation without reasserting an unchanged command.

### 2026-08-20

- Replaced the oversized YAML-only operator dashboard with a five-section,
  UI-managed Home Assistant dashboard covering current energy, prices/selling,
  flexible loads, the short forecast, and controls.
- Fixed Tesla start/stop chatter caused by overlapping automation runs and by
  treating an unchanged positive BLE charge-power value as stale despite a
  healthy same-source BLE heartbeat. Physical sustained-charge acceptance is
  recorded separately from the static contract checks.
- Fixed the remaining Tesla start handshake race: the BLE charger switch could
  report `off` roughly 250 ms after an accepted start even though the wall
  connector was still closing its contactor. The actuator now carries a
  timestamped 90-second start session across that transient and waits for
  measured power instead of cancelling the start and resetting the dwell.
- Fixed the sleeping-car wake deadlock: controller uptime and the local wall
  connection now authorize the wake even when SOC, amps, limit, and vehicle
  last-update entities are still unknown. The same 90-second post-wake power
  confirmation remains fail-closed.
- Replaced the blanket EV battery-discharge stop with a same-plan marginal
  guard. Actual discharge may follow the already committed house/export target,
  but any EV-correlated excess above 0.3 kW still stops charging immediately.
- Made source priority explicit and forecastable: solar supplies normal house,
  hot water and Tesla first; battery then supplies the house and only authorised
  Tesla demand, while hot water never receives battery energy. Grid is last
  resort, including the guaranteed hot-water rescue. Negative FIT charges the stationary battery
  before curtailment. The dashboard now reports 36-hour source kWh for all three
  loads and upcoming solar/battery export windows. Production grid feedback was
  moved to the two-second SAJ Meter A total.
- Restarted only the Tesla BLE controller after its vehicle-data timestamp had
  stopped advancing. Controller uptime reset to 3.5 seconds, the vehicle
  heartbeat republished within about ten seconds, and the local-link guard
  returned healthy. A before-fix live trace captured the charger switch
  changing `on` to `off` in 247 ms while the wall contactor subsequently closed,
  providing the physical evidence for the handshake correction. The next
  economic charge window is currently scheduled for 00:30; sustained charging
  with this exact deployed correction remains a pending physical observation.

### 2026-08-22

- Deployed the streamlined whole-site policy: solar supplies loads first,
  stationary battery covers ordinary house demand and only authorised EV
  demand, and grid battery charging is restricted to a forecast ordinary-house
  reserve. The unified EV state is `No trip / opportunistic`; below 40% remains
  a mandatory solar-then-protected-battery tranche.
- Made hot water a single continuously evaluated service: qualified solar is
  preferred, grid-only latest-start rescue guarantees the daily service, and
  the stationary battery is physically excluded from element demand. Planner,
  governor, outcomes, and notifications now share the confirmed-power runtime
  and thermostat-satisfied completion latch.
- Coalesced each Amber FIT/import pair for 250 ms and limited Node-RED's direct
  price edge to signed-negative FIT. Positive repricing acts on the atomic plan;
  negative FIT still requests inverter-native zero export immediately.
- Made validated auto-resume idempotent once production is healthy, so ordinary
  five-minute plan rollovers do not replay gate writes or show a false arming
  phase.
- Stabilised export-rate writes with a 60-second same-interval hold plus a
  1 kW/10% deadband, while preserving immediate new-interval, expiry, safety,
  and negative-FIT actions.
- Migrated the live dashboard to the editable Sections view with the minimum
  battery sell price, export plan, and solar/battery/grid energy attribution for
  house, Tesla, and hot water.
- Activated immutable release `f4c0d14d0d54-3b5ba60a6f37`. Home Assistant and
  Node-RED rollback copies are under the dated `/config/backups/energy-optimizer-*`
  directory. Live rollout proved guarded disarm/rearm, confirmed SAJ
  self-consumption, zero hot-water battery allocation, and physical relay-off
  after thermostat satisfaction. Daylight solar, connected-EV, and a new
  negative-FIT interval remain condition-dependent physical observations.

### 2026-08-24

- Remediation release serializes every SAJ write in one ordered Node-RED
  transaction and removes the retired `eop_guard_tab_001`, leaving one inverter
  authority. Equivalent physical commands now advance confirmation by semantic
  hash without register rewrites; receipt, first-write, applied and confirmed
  timestamps are retained in actuator status.
- The complete plan is now the first Home Assistant publication on both full
  and fast dispatch. Dashboard mirrors and forecast chunks follow outside the
  Amber-to-actuator critical path.
- Hot water schedules a 3.05-hour evidence margin, runs ordinarily only from
  confirmed solar, and uses a coordinated latest-start grid-only rescue when
  daily service would otherwise miss 4pm. The relay is not called repeatedly
  while unavailable or already off.
- The Tesla uses BLE first, ramps down before stopping, protects the forecast
  overnight house reserve below 40%, and permits grid only through the explicit
  dashboard helper. Paid Fleet fallback now has its own disabled-by-default
  helper plus recent-telemetry circuit gate.
- Learning schema v3 separates measured PV from curtailed potential and learns
  independent north/south half-hour correction ratios only from uncurtailed
  production. The solar entity reports per-roof bias and low/high empirical
  calibration ranges.
- Five-minute outcomes now include realized house/hot-water/EV source
  allocation, planned-versus-realized value, morning/evening crossover SOC, EV
  departure success, and actuator rejection/failure/unconfirmed time for daily
  and rolling 7/30-day reports.
- Home Assistant templates use explicit unavailable-safe numeric defaults;
  three obsolete EV prompt/response/cheap-window definitions are retained as
  disabled inert rollback records. Amber configuration descriptions now inherit
  the Home Assistant 2026.8 entity-description contracts, and $/kWh rates no
  longer advertise an invalid measurement state class.
- Outcome state is schema v2. An in-progress pre-upgrade accumulator is safely
  discarded rather than interpreted with missing allocation fields, and
  timezone-less Home Assistant departure values are localized to Brisbane
  before EV departure scoring.
- An overdue grid-only hot-water rescue bypasses the ordinary five-minute
  economic off-dwell. Normal solar starts retain dwell protection, but rescue
  can no longer lose more service time after its calculated latest start.
- Live release `f4c0d14d0d54-440108c96c25` passed readiness after deployment.
  With live FIT at -$0.0073975/kWh, inverter-native anti-reflux held the
  two-second SAJ meter to approximately 4 W of export while PV continued
  supplying approximately 1.14 kW of house load. The actuator then reached
  independent `feedback_confirmed` state. This physically accepts the
  negative-FIT zero-export path for the observed interval; profitable forced
  export still awaits a naturally occurring price window.
- The live Home Assistant automation file was rebuilt from the pre-change raw
  checkpoint with a text-preserving replacement of exactly 30 canonical energy
  definitions. Seven legacy unquoted clock values were repaired as strings;
  all 122 automation IDs remained unique and a subsequent reload produced no
  new automation validation failures. The overdue rescue bypass was then
  physically exercised: the hot-water relay started immediately, found the
  element thermostat already satisfied, and shut down as complete without
  drawing stationary-battery energy.
- Final immutable release `f4c0d14d0d54-4432ef8f1f5b` is active and healthy.
  Its startup plan was physically equivalent to the already confirmed SAJ
  command, so Node-RED returned `semantic_noop_confirmed`, preserved the prior
  applied timestamp, performed no register rewrite, and kept actuation ready.

- Separated the live five-minute Amber command overlay from the committed
  36-hour forecast. Fast price decisions retain immediate control authority but
  no longer replace hot-water/EV windows, crossover times, forecast energy, or
  expected financial totals with a single short interval.
- Added physical session commitment. Solar-qualified hot water continues across
  harmless rolling replans but stops immediately for more than 0.3 kW of
  stationary-battery draw or lost solar cover. If solar cannot complete the
  service, plan-authorized latest-start rescue supplies the element from grid
  while the battery continues covering only ordinary house demand.
- Equal-value hot-water choices now commit to the earliest safe solar block.
  This removes the former rolling-latest tie-break that moved the displayed
  window forward at every solve without creating any financial benefit.
- A selected hot-water window becomes physically committed when its start is
  within 60 minutes. Subsequent full replans retain that block; completion or a
  genuinely missed/expired window releases it for solar-only recovery. Commit
  boundaries are minute-normalised so a partial live interval cannot leak a few
  microseconds into the next five-minute block and move the displayed finish.
- Added a low-FIT expected-solar continuation latch for the Tesla. A running BLE
  session is not stopped merely because a conservative rolling solve withdraws
  its current block while fresh expected PV still supports it; current still
  ramps down from grid/battery feedback, and high FIT, stale data, the charge
  limit, or insufficient onsite energy stop it.
- A declared mandatory trip also receives a guarded expected-solar override when
  the conservative rolling horizon says the whole requirement is infeasible.
  This uses available solar now instead of stopping merely because every trip
  kWh cannot be delivered; the no-grid and no-stationary-battery guards remain.
- Both physical flexible-load governors bridge the few-second plan-publication
  boundary for at most 15 seconds. They preserve an active session only while
  expected/actual solar, grid, stationary-battery, telemetry, charge-limit and
  production gates remain safe; a missing valid plan beyond that still stops.
- The bridge measures staged sensor publication from Home Assistant
  `last_updated`, not `last_changed`, because plan attributes and plan IDs can
  change while the visible EV/hot-water state string remains identical.
- EV feed-forward now treats fresh actual SAJ PV as reliable when signed FIT is
  positive, because export is uncurtailed in that state. During zero/negative
  FIT it still requires the roof expected-output sensors, avoiding a false stop
  when their slower update cadence briefly exceeds 120 seconds in full-solar
  positive-FIT operation without trusting curtailed actual PV.
- For an explicit mandatory trip that the horizon labels `insufficient_time`,
  confirmed physical charging is also latched while the fast meter proves at
  least 0.3 kW of site export and no excess stationary-battery draw. This keeps
  using real surplus through transient permission recalculation without ever
  turning a grid/battery-funded session into an implicit override.
- An already-running solar session now holds the Tesla's 6 A physical minimum
  when the conservative expected-PV calculation briefly dips below 6 A but the
  two-second SAJ meter still proves at least 0.3 kW of export and the stationary
  battery is not discharging beyond its plan. The forecast remains the upward
  rate target; grid and battery feedback still ramp down immediately.
- The actuator retains one `start_epoch` for the complete physical charging
  session instead of refreshing it when the 90-second start-confirmation grace
  ends. Dashboard timing and loss-of-power confirmation therefore remain stable.
- Simplified the dashboard wording to distinguish the rolling 36-hour export
  plan from flexible-load planned windows, and made the local BLE charger the
  visible primary EV switch.
- While a flexible load is physically active, the dashboard now says "Running
  now" or "Charging now" with its finish/current instead of repeatedly showing
  a past rolling start time as though it were a new decision.

### 2026-08-25 production cutover

- Checkpointed Home Assistant, Node-RED, LXC state, the deployed release and
  live SAJ state before changing authority.
- Removed both Node-RED energy actuator tabs and 50 legacy Home Assistant
  battery, curtailment, EV and hot-water writer automations. The remaining
  Node-RED POA flow is telemetry-only.
- Restored the Home Assistant SAJ integration at the operator's request while
  leaving its former automatic writers removed. Its native controls are now
  manual-only and must not be changed while standalone control is enabled.
- Enabled standalone production control. Live evidence showed SAJ
  self-consumption with approximately zero grid exchange and the battery
  supplying the combined home/EV load. Tesla BLE started below-40% charging at
  a stable 6 A and renewed its local controller lease without chatter.
- InfluxDB remains non-blocking: rows accumulate in the SQLite outbox until the
  dedicated token is installed.

### 2026-08-25 planning dashboards

- Deployed standalone release `standalone-0.3.2`. The local dashboard now
  presents the full 36-hour PV/load/SOC trajectory, grouped planned actions,
  export windows, expected battery-export revenue, flexible-load windows and
  plan/forecast freshness.
- Added Tesla demand to the future energy model. A below-40% vehicle receives a
  planned 6 A three-phase input from solar plus stationary energy above the
  protected reserve; the dashboard reports planned and unmet kWh and the
  predicted home-battery path includes that load.
- Added retained MQTT Discovery scalars for current action/reason, reserve,
  targets, forecast totals, next export, hot water, Tesla recommendation,
  predicted SOC and reporting backlog.
- Replaced Home Assistant's `Energy Optimizer` content with a UI-editable,
  four-section `Energy Manager` dashboard backed by 45 standalone MQTT entities.
  It contains no legacy `energy_optimizer` references and remains display-only.
- Rollback copies of the former dashboard and release evidence are under
  `/config/backups/standalone-dashboard-20260825T2030/` and
  `/var/lib/energy-manager/backups/dashboard-20260825T2030/`.
