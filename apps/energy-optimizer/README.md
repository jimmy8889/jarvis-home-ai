# Pilot Energy Optimizer

Local, forecast-aware dispatch planning for Amber prices, SAJ battery/solar,
hot water, and three-phase Tesla charging.

The canonical human-readable system guide is
[`energy-automation/README.md`](../../energy-automation/README.md). Every
material energy-automation change must update that guide in the same commit.

This README describes the repository contract. A passing test, valid plan, or
healthy container is not proof that the same release is active on the inverter
or that the commanded physical result occurred.

## Control ownership

There is one battery/inverter writer: the guarded Node-RED flow in
[`node-red/`](node-red/). The Python service is a planner and publisher. It
does not write SAJ registers, the hot-water switch, or Tesla charging controls.
Home Assistant is the state/UI hub and contains separate guarded hot-water and
EV actuators. Retired Amber/FIT, fixed-reserve, sunrise/10:30, curtailment,
hot-water, and Tesla writers must remain disabled.

The complete actuator contract is published first on
`sensor.energy_optimizer_plan`; compact command and dashboard mirrors follow.
This removes mirror publication from the Amber-to-inverter critical path.
Node-RED accepts only a complete, current schema-v2 plan and then owns all SAJ
settings required by that transaction, including anti-reflux, raw export and
grid limits, on-grid reserve, the battery discharge-power limit, PV-charge
policy, rates, and forced modes. In particular, no helper bridge or Home
Assistant automation may also write the SAJ battery discharge-power limit.

The commit marker contains only scalar schema/actuation/dashboard metadata and
is kept below a 12 KiB safety budget for Home Assistant's 16 KiB recorder
attribute limit. Immediate Amber dispatch commits the plan first, then publishes
six compact mirrors concurrently, with no solar, acceptance, or horizon rewrite
on its critical path. A full optimisation uses the same plan-first contract and
then publishes mirrors, acceptance data and recorder-safe horizon chunks. Its
`horizon_plan_id` explicitly retains the last
committed full horizon. Lovelace accepts only a complete set of chunks matching
that ID and renders horizon-derived values unavailable on any mismatch. The
lossless full plan remains in the immutable plan journal.

## Schema-v2 battery contract

Every committed plan contains:

- `schema_version: 2`, a unique `plan_id`, generation/expiry timestamps, the
  active interval, action/reason, and forecast confidence;
- `battery_mode`, exactly one of `hold`, `self_consume`, `pv_charge`,
  `grid_charge`, or `export`;
- signed `battery_power_target_kw`: positive is discharge and negative is
  charge;
- non-negative `battery_charge_target_kw` and
  `battery_discharge_target_kw`, consistent with the signed target;
- `site_export_target_kw`, which is a site result and not a battery-power
  alias;
- `protected_soc_pct`, always at least the 5% inverter floor;
- `house_reserve_soc_pct`, the forecast energy reserved for ordinary household
  demand through sustainable morning solar takeover;
- `command_semantic_hash`, which identifies the physical command independently
  of rolling plan IDs and forecast-only changes;
- `pv_export_command`, `curtail` or `allow`;
- `live_fit_price`, `live_import_price`, and `price_interval_start` /
  `price_interval_end`;
- configured `minimum_sell_price` and wear-bounded `effective_sell_price`;
- EV schedule/live amps and source budget, the 3.05-hour hot-water service
  target and grid-only rescue source, dispatch latency timestamps, and freshness
  evidence in `source_timestamps`; and
- `software_version` and `config_fingerprint` for release/config provenance.

Mode semantics are intentionally strict:

| Mode | Node-RED behaviour |
|---|---|
| `hold` | No forced mode; protected reserve is enforced while normal house support and PV charging remain enabled. |
| `self_consume` | No forced mode; normal house support is allowed with the battery discharge-power limit restored to 1000. A positive forecast component does not authorize forced export. |
| `pv_charge` | PV charging and its rate may be enabled; grid force-charge remains off and ordinary self-consumption remains available. |
| `grid_charge` | Grid force-charge is enabled at the validated charge target; the force switch, not a latched zero discharge limit, provides exclusivity. |
| `export` | The only mode that authorizes forced battery discharge; its normal 1000 discharge-power limit is restored before forcing export. |

The SAJ writable entity
`number.saj_battery_discharge_power_limit_input` is an optimistic 0–1100
register view. Its independent physical readback,
`sensor.saj_battery_discharge_power_limit`, reports 0–110%. Node-RED accepts
only an explicit `%` unit in the 0–110 range and normalizes it by multiplying
by ten before comparing it with the writable register. Missing, ambiguous, or
out-of-range independent readback fails closed at preflight and cannot reach
final feedback confirmation if it becomes invalid later. If a limit changes,
final confirmation additionally requires a post-command independent sensor
report.

The SAJ reserve control is whole-percent. Every active mode uses
`ceil(protected_soc_pct)`, clamped to 5–100%; for example, 39.7% is written and
verified as 40%, never 39%. `hold` means no forced arbitrage, not a frozen
battery: normal household self-consumption and PV charging remain available.
Generic
rejection, expiry, manual-override, and actuator-error safe-stop restores the
1000 (100%) battery discharge limit along with normal PV/self-consumption
operation. Accepted modes retain that 1000 allowance as well; exclusive force
switches control grid-charge and export transactions without ever latching
ordinary house support to zero.

For export, Node-RED converts the requested site result using fresh telemetry:

```text
requested battery discharge
= site_export_target_kw + live home load_kw - live pv_kw
```

It clamps that result by the plan's discharge target, the configured live cap,
the verified 28 kW discharge limit, SOC protection, and any stricter SAJ/site
limit. Charge is capped at 30 kW. The guarded site-target range is 0–100 kW so
high PV plus battery export is representable without increasing the battery
limit.

Node-RED rejects mismatched component signs, stale/replayed plans, expired
price windows, stale or missing source timestamps, live-price disagreement,
unsafe SOC, unavailable sensors, conflicting modes, and out-of-range values.
Its latest-wins lock serializes the complete physical write phase. A full
transition stops both force modes, applies reserve, discharge allowance, grid
limit, export policy, charge/discharge rates and PV policy in one ordered
chain, rechecks the active identity, and only then enables at most one forced
mode. This prevents overlapping Modbus transactions while preserving immediate
entry when the actuator is idle. The lock is released after the last service
succeeds; direction and target feedback remain asynchronous, and
stale observers cannot publish status, reassert, or safe-stop a newer command.
After final physical confirmation, a same-mode export target update writes only
`number.saj_discharge1_power_percent_input`; any invariant change or uncertainty
uses the full path. Within one Amber settlement interval, ordinary target
corrections are held so battery export power changes at most once every 60
seconds, including ordinary stop/restart decisions. Same-interval corrections
inside the larger of 1 kW or 10% are also ignored. A held plan takes a true
no-write path, so the discharge register and force switch remain untouched.
Safety actions, negative FIT, and the first command for a new Amber interval
remain immediate. Export observation uses
`sensor.saj_meter_a_real_power_total` as the site-level outcome; battery power
continues to prove discharge direction. Load/PV-driven site deviation is
reported for the next permitted plan correction and does not replay the same
physical command. A register or direction mismatch is still reasserted once
and then safe-stopped. Plan expiry,
rejection, and watchdog failure all cancel forced modes and return the inverter
to safe normal self-consumption/PV operation.

The 60-second watchdog revalidates safety and expiry without replaying a
healthy command. When the committed plan identity and every owned physical
register, switch, and helper still match the current transaction, it produces
no output and preserves confirmation. A new plan with the same semantic hash
and matching live register state advances to `semantic_noop_confirmed` without
any physical write. The watchdog performs a full
reassertion only for measured drift; a newer commit is processed normally, and
the dedicated `valid_until` one-shot still enforces exact expiry.

At a fresh negative FIT, `pv_export_command=curtail` is unconditional. Node-RED enables
SAJ anti-reflux and writes a zero raw export limit so the inverter follows site
load instead of paying to export. The plan may still use otherwise-curtailed
energy for protected battery charging, hot water, or the EV. The physical SAJ
PV-charge limit remains at the verified full 30 kW setting: the planned charge
target is a forecast, not a ceiling on roof production. Actual PV is curtailed
only after live demand, flexible loads, and all feasible battery charging have
absorbed the available solar.
Positive FIT always leaves solar export enabled, even below the configured
battery sell price. Unknown or stale FIT restores normal export and cancels
forced battery action; it never guesses that zero export is required.

## Optimisation model

- Fixed nominal battery capacity: 47 kWh. Telemetry may reconcile estimated
  stored energy with SOC, but it never silently changes nominal capacity.
- Hard floor 5%, normal morning target about 7%, and evening target 99% when
  feasible and economic.
- 90% charge/discharge efficiencies, $0.08 per discharged kWh wear, and a
  $0.02/kWh uncertainty margin for new grid-arbitrage decisions.
- `input_number.energy_optimizer_min_sell_price_c_per_kwh` is the editable
  dashboard battery-export floor. The active floor is the greater of that
  value and the $0.08/kWh wear allowance; changing it triggers an immediate
  replan. It does not gate positive-FIT solar export or household support.
- Battery energy is never exported when the live FIT is below the active sell
  floor. A higher import price may justify supplying only
  the live household deficit; that remains `self_consume` with zero requested
  site export.
- Because the DP's 0.25 kWh energy lattice implies a 2.7 kW minimum transition
  in a five-minute slot, a continuous-power pass separates the household and
  export tranches after optimisation. It caps below-wear discharge to
  the complete site deficit except hot water. The EV is included only when its
  source contract explicitly permits house-battery energy, such as the sub-40%
  reserve. It starts from exact input SOC, preserves that point in the
  DP lattice, and recalculates the entire SOC/grid/cost trajectory. Morning SOC
  is a soft economic objective, not a hard upper constraint that can force
  discharge.
- Amber prices are signed and duration-weighted over every optimisation slot;
  partial overlaps do not receive an unweighted interval average.
- Calibrated Solcast low/expected/high scenarios combine roof geometry, local
  irradiance/POA expected power, actual PV, and curtailment-aware learning.
- Household learning is timestamp/date deduplicated and schema-versioned;
  migrations either preserve compatible data or reset safely.
- Hot water first uses qualified solar blocks, prioritising negative FIT. Any
  remaining service is placed only in the latest grid-rescue window; the
  stationary battery is limited to simultaneous non-element demand.
- Grid battery charging is not used for arbitrage or the 99% target. It may
  store only the conservative shortfall required to carry ordinary house load
  to the next sustainable solar takeover while retaining the 7% morning buffer.
- Replans occur every five minutes and immediately on Amber, EV requirements,
  connection/SOC, control changes, or hot-water completion. Optimiser-owned
  charger, relay, and power edges are cached but never trigger another solve.
- A fast Amber plan inherits at least the last committed full plan's
  `protected_soc_pct`; it never substitutes the generic 7% morning target.
  Immediate discharge is limited to energy above that inherited reserve.
- Amber's separate FIT/import updates are coalesced for 250 ms before the fast
  decision, preventing a normal rollover from publishing a transient zero
  command. A genuinely partial, stale, or non-overlapping pair publishes an explicit
  non-actuating `safe_hold` commit with zero battery/site targets and null price
  metadata. It is deliberately published, rather than suppressed, so the
  guarded actuator can cancel any older forced mode immediately without the
  optimiser inventing a price window.
- For a valid rollover pair, the fast path preserves household
  self-consumption already selected by the full horizon when the live import
  revision remains inside the configured economic uncertainty margin. A
  material downward revision still holds and waits for the next full solve;
  export is always revalued separately against live FIT and retained value.

The optimiser currently uses a discrete dynamic programme with a 0.25 kWh
stored-energy grid. It is not a continuous LP/MILP and does not use HiGHS.
Therefore its plan is deterministic and tested, but is not a mathematical
certificate of a globally optimal continuous solution. Any future solver
migration needs constraint-parity tests, replay/performance evidence, and new
physical actuator acceptance before production.

Forecast learning schema v3 also maintains separate north- and south-roof
half-hour correction distributions. It accepts samples only while export is
allowed at non-negative FIT, so deliberate curtailment cannot teach a false
cloud/roof bias. Until a time bin has three observations its multiplier remains
1.0. Thereafter the median corrects the live POA potential, while observation
count, median bias and empirical 10th/90th-percentile ratios are published as
`roof_calibration` on `sensor.energy_optimizer_solar_potential`.

## Unified flexible-load safety

### Hot water

Home Assistant's single production actuator accepts only a fresh committed
schema-v2 plan. It models the element as a 3.7 kW binary load and tracks actual
confirmed element-on time from `sensor.hot_water_confirmed_runtime_today`
toward three hours, targeting 16:00 Brisbane time. The former relay-on timer is
not a service-completion input. Service also
completes when a confirmed-on relay has fresh sub-0.3 kW element evidence for
five minutes, which means the tank thermostat is satisfied. A fresh SAJ
whole-house load report after relay-on must contain the element's expected load
signature; that evidence drives
`sensor.energy_optimizer_hot_water_confirmed_power`, runtime, outcomes, and
notifications instead of the unreliable legacy phase-delta sensor.

`sensor.energy_optimizer_hot_water` remains `on`/`off` and publishes
`control_mode` as `off`, `solar_surplus`, or `service_rescue`; the plan also
publishes `hot_water_control_mode`.

- `solar_surplus` subtracts measured active element power from inclusive house
  load, requires 30 seconds of element-plus-0.5 kW headroom, and stops within
  15 seconds of insufficient solar. Stationary-battery support is prohibited.
- `service_rescue` is emitted when latest-start feasibility requires it. The
  committed battery target covers only simultaneous house/authorised EV demand;
  grid supplies the element. It continues after 16:00 when needed.
- A relay that is on while the element falls to zero is `thermostat_satisfied`,
  not a command mismatch. The relay is stopped once and its daily completion
  latch resets at midnight; the old one-minute-on/five-minute-off loop is gone.
- Normal dwell protection is 15 minutes on and 5 minutes off; stale sources,
  unsafe SOC, or other safety stops are immediate.
- Startup reconciliation and a 10-second watchdog prevent an orphaned element.

The former independent latest-start writer is disabled; service rescue is part
of this single guarded authority instead of a competing automation.

### EV

The source-aware Home Assistant actuator uses:

- `number.tesla_ble_039d9c_charging_amps`;
- `switch.tesla_ble_039d9c_charger`;
- `number.tesla_ble_039d9c_charging_limit` (editable on the dashboard); and
- `sensor.tesla_wall_connector_total_power` for physical confirmation.

`input_boolean.energy_optimizer_ev_allow_grid` is a native Home Assistant UI
helper and the explicit permission for deadline/grid charging. It restores
across Home Assistant restarts and defaults off when first created. When it is
off, the scheduler publishes only genuine
direct-solar EV blocks; a declared trip remains visibly unmet instead of
silently falling back to grid or unreserved house-battery energy. The actuator
uses the local BLE switch/current controls as primary. Tesla Fleet is disabled
unless the separate paid-fallback helper is explicitly enabled and recent
Fleet telemetry passes its health gate. Fresh
`sensor.tesla_wall_connector_total_power` remains physical truth. Every stop
reason can contain both command paths, so one unavailable integration cannot
leave charging orphaned.
Measured charging can reassert that stop after 45 seconds, while an already-off
car generates no Tesla API call. Sleeping-vehicle wakes are similarly limited
to one per 60 seconds so fast telemetry cannot trip Tesla's rate limiter.

It requires production expected/active gates, a fresh committed plan, fresh
core telemetry, one healthy local control backend, and a connected vehicle at home. Direct-solar
amps are calculated from net solar headroom as
`solar_kw * 1000 / (3 * 247)`, constrained to 6–16 A. Inclusive house load is
corrected for measured EV power so charging does not subtract itself twice.
Once a solar session is physically running, a conservative forecast dip below
6 A does not stop the car while the two-second site meter still proves at least
0.3 kW export and stationary-battery discharge remains inside its committed
allowance. The controller holds 6 A, uses forecast feed-forward for increases,
and retains live grid/battery feedback for reductions.

The single `No trip / opportunistic` option replaces the former `Unanswered`
and `No trip` states. The 40% departure reserve is mandatory whenever the
connected Tesla is below it and starts immediately. With grid charging disabled, the
optimiser may schedule the exact shortfall from the house battery above its
protected floor; live import trimming
ensures this never silently becomes grid charging. Energy above 40% remains
non-mandatory with no declared trip and may use exceptionally
low-opportunity-cost solar up to the configured Tesla limit. When charging is
scheduled with grid disabled, conservative direct solar is the only permitted
source above that mandatory reserve; live import trims or stops the car. Their 7am departure is advisory above 40%, so
later negative-FIT slots remain eligible if the car is still home and
connected. A declared trip can create an explicit departure-deadline fallback
and retains its departure as a hard boundary. Physical battery discharge is
compared with the target from the exact same committed plan: the battery may
continue covering house load or executing a planned high-FIT export, but more
than 0.3 kW above that allocation hard-stops the EV. A live FIT spike immediately pauses
non-mandatory charging so valuable solar/battery energy can export.

The actuator is serialized (`mode: single`) so rapid SAJ and plan events cannot
leave an older run's charger service call racing a newer decision. Normal starts
set current and request charge through local BLE. Fleet wake/control is used
only under the explicit paid last-resort fallback gate. Fresh
wall-connector power must confirm the physical result inside the timestamped
90-second start session. BLE remains the routine containment path; Fleet stop is
used only when the fallback gate is healthy and BLE cannot contain measured
charging.

On 2026-08-20 the BLE switch reported off while wall-connector power remained
about 11.6 kW. A BLE stop returned success but did not stop the car; the Tesla
Fleet switch did, with wall power falling to zero after the vehicle handshake.
That incident is why measured wall power is the proof and Fleet remains an
explicitly gated last-resort containment path.

## Dashboard

The operator dashboard is a native Home Assistant **Sections** dashboard at
`/energy-control/overview`. It is stored by Home Assistant, so cards and section
placement can be edited in the UI. The checked-in
`home-assistant/energy-optimizer-dashboard.yaml` is the version-controlled
export used for validation and repeatable deployment. The simplified view keeps
only current energy, prices/selling, flexible loads, the short forecast, and
the essential controls. Its 36-hour plan reports hot-water, Tesla and normal
house energy by solar/battery/grid source and lists upcoming export intervals
with solar-versus-battery export energy. Live grid feedback is taken from the
two-second `sensor.saj_meter_a_real_power_total` entity.

## Production arming and auto-resume

`input_boolean.energy_optimizer_production_expected` records operator intent
across Home Assistant restarts. Startup never blindly restores actuation:

1. battery, hot-water, EV, and rescue gates are forced off and mode is Shadow;
2. the automation waits for the SAJ contract, fresh core telemetry, a fresh
   committed plan, and current actuator state;
3. it restores the verified 28 kW discharge cap, enables subsystem gates, and
   selects Active last; and
4. it waits for a current accepted/feedback-confirmed command. Export and grid
   charge specifically require physical feedback confirmation.

Failure returns every gate to off and mode to Shadow before a later retry. A
missing SAJ contract entity additionally enables manual override and sends a
critical notification; restoration does not silently clear that override.
Manual override always wins over saved production intent.

At the Python contract boundary, any disarmed production gate also forces the
published battery mode to `hold` and every battery/site command target to zero.
The forecast interval array is retained for shadow economics, but a cached
`export` or `grid_charge` mode cannot survive as an actionable top-level field.
That zero command means “no forced arbitrage”; the actuator still restores
normal self-consumption and PV charging.

The sequence and templates are statically validated in the repository. A real
Home Assistant restart, inverter response, and physical load response remain
mandatory per-release acceptance; auto-resume is not considered physically
validated merely because YAML validation passes.

## State, journals, and acceptance reports

The data volume contains:

| Path | Purpose |
|---|---|
| `/data/latest-plan.json` | Latest complete plan snapshot. |
| `/data/plans/YYYY-MM-DD.jsonl.gz` | Immutable completed plan journal; the active day remains JSONL. |
| `/data/outcomes/YYYY-MM-DD.jsonl.gz` | One realized row per five-minute interval, with explicit gap rows; the active day remains JSONL. |
| `/data/outcome-state.json` | Outcome recorder checkpoint. |
| `/data/acceptance-summary.json` | Daily and rolling 7/30-day realized summaries. |
| `/data/learning-state.json` | Versioned, deduplicated learning state. |

Retention defaults to 90 days. Completed plan/outcome journals are gzip
compressed before retention pruning; data is not silently removed at day
rollover. The current realized report covers interval battery/grid/hot-water
evidence. EV SOC at departure, SOC exactly at both solar crossovers, and a
matched realized baseline cash delta are reported as unassessed rather than
fabricated.

Historical replay maintains one continuous optimiser SOC trajectory across the
full dataset and values terminal energy once. EV and hot-water consumption is
included in dispatch cashflow only when the exporter can supply separate
`base_load_kw`, `hot_water_kw`, and `ev_kw` interval series with complete
coverage. Legacy inclusive-only data fails explicitly rather than claiming a
valid comparison. Replay still uses actual future solar/load/prices, so it is a
perfect-hindsight upper-bound benchmark, not a forecast backtest or physical
acceptance test.

## Health and local validation

`/healthz` is process diagnostics. `/readyz` additionally requires a fresh,
unexpired committed plan, a connected Home Assistant state stream, and a
healthy immediate-price worker. Neither endpoint proves physical actuation.

```bash
uv run --extra test pytest
node --test node-red/guard.test.js
node node-red/build-flow.js
ruby home-assistant/validate-contract.rb
uv run --with PyYAML --with Jinja2 python home-assistant/validate-templates.py
docker compose -f ../../infra/energy-optimizer/docker-compose.yml config --quiet
git diff --check
```

## Releases, deployment, and rollback

Both operational scripts are dry-run by default.

```bash
deploy/scripts/energy-optimizer-sync
deploy/scripts/energy-optimizer-sync --apply
deploy/scripts/energy-optimizer-rollback
deploy/scripts/energy-optimizer-rollback --apply
```

The sync script derives an immutable release ID from the Git SHA and content
hash, stages it under
`/opt/jarvis-home-ai/releases/energy-optimizer/<release-id>`, builds a tagged
image, validates Compose, starts it, waits for `/readyz`, and only then updates
the `current-energy-optimizer` symlink. Release manifests under
`/opt/energy-optimizer/releases/` record hashes, image, previous release, and
staged/active status. Old images are retained for 720 hours after success.

The sync scope is only the dedicated app and infrastructure directories. It
does not install Home Assistant YAML or import the Node-RED flow; those require
their own reviewed rollout and backup.

Rollback selects the previous manifest (or an explicit release), enables
manual override, stops charge/discharge and flexible loads, restores safe SAJ
anti-reflux/export/grid limits, activates the selected immutable release, and
leaves manual override on for deliberate physical verification. Do not
re-enable a retired authority while the guarded Node-RED writer is active.

The 2026-08-24 remediation is deployed as immutable release
`f4c0d14d0d54-4432ef8f1f5b`. Its startup plan used the semantic no-op path:
confirmation advanced to the new plan ID without an equivalent SAJ register
rewrite, and actuation readiness remained confirmed.

## Secrets and container hardening

- The Home Assistant token originates in the protected
  `infra/secrets/home_assistant_token` source and is installed mode `0400` for
  service UID/GID 10003. Docker exposes it only as
  `/run/secrets/home_assistant_token`.
- Tokens, SSH passwords/private keys, and Influx credentials must never appear
  in source, plans, journals, or reports. Historical export reuses the existing
  `solar-monitor` container's scoped Influx access.
- The former plaintext Tesla SSH recovery path is inert/disabled. Local
  secret/key-backed control is required before any replacement is enabled.
- The container runs non-root, read-only, with all capabilities dropped,
  `no-new-privileges`, loopback-only API exposure, and only its data volume
  writable.
- Node-RED administration remains authenticated behind protected Home
  Assistant ingress.

## Physical acceptance still required

Staged physical acceptance on 2026-08-18 established a narrow but important
control result: writing a zero battery discharge-power limit stopped discharge
that had continued at roughly 4–5 kW despite a raised reserve and both forced
switches being off. A subsequent staged `self_consume` transaction held the
whole-percent reserve at 40%, restored the normal discharge limit, left both
forced modes off, and settled grid exchange around 20–30 W. This proves the
direct limit path, independent reserve handling, and passive-mode exclusivity
for that observation; it is not whole-system production acceptance.

The ordered write lock, semantic no-op path, asynchronous feedback, and
same-mode single-register export fast path have generated-flow, topology,
identity-correlation, queue, stale-feedback, and failure-path regression
coverage. The remediation rollout physically confirmed a serialized reserve
change, independent readback, safe hold, simultaneous solar hot water and BLE
EV charging, and zero stationary-battery draw. On 2026-08-24 a live
-$0.0073975/kWh FIT interval physically held the two-second SAJ meter near 4 W
of export while PV continued supplying roughly 1.14 kW of house load; the
actuator subsequently reached independent `feedback_confirmed` state. This
accepts the observed negative-FIT path. Profitable forced-export interval
latency still requires a condition-dependent observation.
The idempotent watchdog behaviour was added after the same staged observation
and likewise still requires live acceptance across at least one minute boundary
plus an intentional drift test.

Some price- and daylight-dependent acceptance remains pending. In particular,
the current release still needs observed profitable export, PV/grid charge
transitions, and an immediate profitable Amber interval change/expiry before
those paths are called physically accepted.

Before a release is called production-validated, observe real grid/battery/load
telemetry for all applicable cases: all five battery modes and signs, SOC
reserve protection, site-export translation, immediate five-minute Amber
response and expiry, exact negative-FIT zero export, EV direct-solar/FIT-spike
pause/departure fallback, hot-water solar/rescue/three-hour deadline, Home
Assistant restart auto-resume, contract loss, manual override, and rollback.
Store those observations with the immutable release ID. Unit tests, static
validators, replay, `/healthz`, and `/readyz` are necessary evidence but cannot
replace this physical checklist.

For a physically confirmed mandatory charge below 40% SOC, the EV governor
latches the running command across the brief retained-plan publication
transition. This latch is timestamp-bounded; genuine stale, disarmed,
disconnected, or unsafe states still stop charging immediately.
