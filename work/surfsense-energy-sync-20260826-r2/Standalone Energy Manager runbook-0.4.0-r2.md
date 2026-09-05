# Standalone Energy Manager

This service is the independent control plane for the SAJ inverter, Tesla BLE charger and hot-water relay. Home Assistant, Pilot, MQTT, InfluxDB and Node-RED are not in the control loop; local planning and control continue if any of them is unavailable.

Release `0.4.0` makes the internal dashboard and Home Assistant Energy Manager dashboard one paired interface. Both display the manager's same live snapshot and schema-v3 plan, and both write the same authenticated REST settings. Every user-visible telemetry, forecast, planning or setting change therefore updates both dashboard definitions in the same release. Repository validation is not proof that a release has been deployed or physically accepted.

## Release 0.4.0

- The rolling 36-hour plan is schema v3. It includes a human-readable current summary and next actions, protected battery trajectory, flexible-load schedule, export windows, and solar/battery/grid allocation.
- Live and planned energy allocation use a conserved edge graph. Sources and sinks are explicit, meter residual and confidence remain visible, and clients do not silently reconstruct authoritative flows when a graph is available.
- Export reporting separates solar and battery energy, battery gross revenue, wear, retained-energy value, net benefit and total export revenue. Five-minute outcomes and daily totals record realised results separately from forecasts.
- The dashboard settings are unified: minimum battery sell price, opportunistic EV FIT ceiling, Tesla charge limit, EV grid permission, optimiser enable and an EV trip profile of `No trip`, `100 km`, `200 km`, `Charge to 80%`, or `Ensure 100%`. `ev_trip_profile` is canonical; `ev_trip_requirement` is accepted only as a compatibility alias.
- Read-only NUT telemetry adds server-and-desk power, daily energy, UPS state and confidence. The rack is included as an identified house sub-load in live flow, forecasts and reports.
- Pilot Core consumes a timestamp-ordered read-only cache of the standalone snapshot and plan. It polls live state every two seconds and the full plan every 20 seconds or on plan-identity change; it never actuates the manager.
- SQLite remains the durable source for settings, plans, leases, command evidence and the InfluxDB outbox. InfluxDB is write-through reporting, not a control dependency; a missing or unavailable scoped token only grows the replayable outbox.
- Daily reporting sums energy and money but duration-weights power, price and confidence averages. Startup rebuilds the current Brisbane day from the authoritative five-minute journal, preventing a prior release's roll-up arithmetic from contaminating dashboard totals.
- Native-API resets fully detach the failed ESPHome client and impose a ten-second reconnect backoff. EV and hot-water actuator failures are isolated from one another and from the already-applied SAJ command, so a BLE outage cannot suppress the day's hot-water command or create a two-second reconnect storm; readiness and per-actuator errors still report the degradation.

## Energy policy

1. Solar supplies ordinary house load.
2. Low-opportunity-cost solar supplies scheduled hot water and EV charging.
3. Remaining solar charges the house battery according to its protected trajectory.
4. The battery supplies ordinary house load and profitable export above the protected overnight reserve.
5. Grid is a last resort.

Live negative Amber FIT enables inverter anti-reflux and a zero-export limit while leaving PV available to the house, battery, EV and hot water. Cached advanced-price intervals are promoted at their exact five-minute boundary and replaced by the live interval when Amber publishes it. Positive FIT never applies zero export. Battery export also requires the live Amber FIT to exceed the configured minimum sell price, retained-energy value and reserve constraints. AEMO is recorded for comparison and cannot dispatch the system.

Amber's public API feed-in channel is normalized from retailer billing sign to
the customer-facing convention used everywhere else in this service: positive
FIT earns export revenue; negative FIT costs money to export.

Battery capacity is always `50 kWh × SOH`. The 5% reserve is a hard floor. SOC, SOH, measured power and two-second integration publish gross stored, usable and extractable AC energy.

Valuable morning FIT can defer PV battery charging. The five-minute rolling solve exports morning surplus while a confidence-adjusted later-solar budget (90% of the calibrated forecast plus a 5% energy margin) still reaches the configured evening SOC target and contains a genuinely cheaper charging block. The stricter 75% solar case continues to protect stored battery energy from export. As later headroom shrinks, charging starts automatically at the calculated latest safe point; stale Amber data releases the hold immediately.

Hot water receives 3.05 scheduled relay-hours so at least three physically confirmed element-hours complete by 4pm. Negative FIT improves scheduling priority but does not by itself permit battery-funded heating: normal service still requires sufficient measured or uncurtailed solar, while the latest-start rescue isolates the 3.7 kW element from house-battery discharge. The pinned custom hot-water firmware exposes the authenticated relay state, controller lease and outage fallback directly to this manager. EV control uses TeslaMate only for retained away-state telemetry and local ESPHome BLE for commands. Current moves by at most 1 A every 30 seconds, with BLE as the only control path.

The standalone manager is the sole live client of the Tesla BLE command API.
Home Assistant's former direct Tesla BLE and hot-water ESPHome config entries are
disabled after checkpointing because they are superseded by manager MQTT/REST
state. This avoids a single-client reconnect collision on the Tesla bridge and
removes the obsolete hot-water API reconnect loop. The Home Assistant Energy
Manager dashboard continues to show both devices from manager-owned telemetry.

## Processes

- `energy-manager.service`: direct polling, planning, actuation, SQLite, MQTT and InfluxDB. It binds to `127.0.0.1:8788`.
- `energy-manager-dashboard.service`: independent public dashboard/proxy on port `8787`. Its failure cannot stop control.

Persistent state lives at `/var/lib/energy-manager/energy-manager.sqlite3`. Secrets are one-value root-owned files in `/etc/energy-manager/secrets`; they are not accepted through MQTT and are not included in backups exported to source control.

Proxmox fencing prevents a second guest from running, and an exclusive
`controller.lock` in the persistent data directory prevents a second manager or
commissioning utility inside the active guest from becoming a concurrent SAJ
owner.

Physical commands carry an expiry. The core renews active EV and hot-water leases and persists their evidence in SQLite. A one-second watchdog contains an expired forced battery action or flexible-load lease by restoring safe SAJ self-consumption, stopping EV and hot water, clearing the expired leases and retrying containment if the first safe-state transaction fails. Safe state preserves battery support for ordinary house load and preserves negative-FIT anti-reflux only while the live negative price is still fresh.

## Safety and cutover

New deployments start with `ENERGY_MANAGER_CONTROL_ENABLED=false`. Production
control was enabled on 2026-08-25 after the legacy Node-RED tabs and Home
Assistant control automations were removed. The Home Assistant SAJ integration
remains enabled for native telemetry/UI at the operator's request; it must not
be used for manual control while this manager is enabled. Rollback checkpoints
are documented in the authoritative energy-automation runbook. The retired
Tesla BLE and hot-water ESPHome entries can be re-enabled only as part of a
deliberate rollback after the standalone manager has relinquished those devices.

The hot-water firmware is a pinned PlatformIO build with its exact ESPHome rollback binary and checksums stored root-only in LXC 103. Do not reflash it without live relay/element visibility and an operator present. The stepped 30 kW charge/discharge commissioning remains a separate physical procedure.

## API and dashboard

The dashboard is `http://10.0.1.205:8787/`. Its live house scene, plan and 36-hour timeline show expected solar, ordinary-house and server-rack energy, planned Tesla input, hot-water operation, battery-export energy and economics, predicted SOC range, solar peak, forecast coverage, future Amber FIT/import curves, the live hot-water relay state and grouped control decisions. EV demand below 40% is included
in the predicted SOC path and is limited to forecast solar plus stationary
battery energy above the protected reserve unless EV grid permission is on.
Read-only snapshot, plan, history, events and stream endpoints are exposed under
`/api/v1`. Settings and overrides require `Authorization: Bearer <api_token>`.

Mutable settings are minimum sell price, opportunistic EV FIT ceiling, EV grid permission, Tesla charge limit, EV trip profile and optimiser enable. The internal dashboard and Home Assistant use the same authenticated REST settings endpoint, and the manager remains their source of truth. Home Assistant polls the current settings every two seconds so a change made on either dashboard converges on both. MQTT is publish-only while the broker allows anonymous clients.

MQTT Discovery entities have individual availability. A missing future plan value is exposed as unavailable without sending invalid text through numeric power, energy or monetary sensors.

Every command envelope includes schema version, software/configuration revision, source timestamps, dispatch timestamps, expiry and a semantic command identity. Equivalent physical commands retain confirmation without unnecessary inverter writes.

Plan schema v3 publishes:

- `narrative.current_summary` and `narrative.next_actions` for the human-readable plan;
- interval points with authoritative conserved `flow.edges` between `solar`, `battery`, `grid`, `house`, `server_rack`, `hot_water`, `ev` and `unaccounted`;
- explicit meter-balance residual, conservation state and confidence instead of silently presenting inferred values as measured; and
- summary/export-window fields for solar and battery export kWh, battery gross revenue, wear cost, retained value, battery net benefit and total revenue.

Older clients may reconstruct a flow only when reading a legacy schema-v2 plan. New clients must consume the v3 graph when present. Display values use one decimal place for SOC and Amber prices, whole watts below 1 kW and one decimal kW at or above 1 kW; API values retain calculation precision.

SAJ PV1/PV2/PV3 remain separate as well as total PV. PV1 is the 11.8 kWp north array; PV2 is the 14 x 590 W (8.26 kWp) south string; PV3 is the 28 x 590 W (16.52 kWp) south input. Forecast monitoring compares PV1 with the north-roof forecast and splits the common south-roof forecast one-third/two-thirds for PV2/PV3. Curtailed intervals remain visible but are excluded from calibration. Because the entire house is on the backup output, `BackupTotalLoadPowerWatt` is the primary load signal; legacy `TotalLoadPower`, power-balance error and the dedicated `batteryPower` register remain published for diagnostics.

## Verification

```bash
uv sync --extra test
uv run pytest
curl -fsS http://10.0.1.205:8787/readyz
```

Production readiness requires physical acceptance of zero export, self-consumption, battery export tracking, EV current ramping, hot-water confirmation and controlled Proxmox HA migration. Host-failure/reboot testing is intentionally outside this rollout.

Home Assistant's `energy-control` Sections dashboard is an optional client of the standalone MQTT Discovery entities and authenticated REST API. It shows the live relay, conserved flow, export economics, server-rack energy, Amber curves and the manager's canonical plan/timeline embeds. Its native controls update the manager through authenticated REST, never MQTT commands, and contain no legacy SAJ, Tesla or hot-water writer. Home Assistant may be stopped without interrupting local control; the standalone manager remains the sole planning and actuation authority.
