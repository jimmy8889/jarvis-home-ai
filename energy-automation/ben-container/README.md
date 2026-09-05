# Ben's Forecast-Aware Energy Optimizer

This directory is the operator record for the separate optimiser deployed to Ben's container at `100.71.190.99`. Every material change to Ben's energy control must update this file.

## Control model

- Home Assistant is the state and dashboard hub.
- `ben-energy-optimizer` reads Amber's exact live five-minute interval and 36-hour forecast and publishes a retained, expiring plan.
- Node-RED is the only Sigenergy actuator. It validates freshness, SOC, bounds, alarms, mode exclusivity and plan expiry before using the native Sigenergy Home Assistant integration.
- Manual Import or Export overrides all economic dispatch until Stop, but never overrides hard safety.
- Battery power is positive for discharge and negative for charge. Site-grid power is positive for import and negative for export.

## Economics

Automatic charging requires import at or below the editable buy ceiling and a later value that clears 90% charge efficiency, 90% discharge efficiency, $0.08/kWh discharged wear and a $0.02/kWh uncertainty margin. Automatic selling requires FIT at or above the editable sell floor. Energy is retained for stronger forecast intervals when that is worth more than selling now.

The reserve is never below 5%. With at least seven valid historical load samples it is the learned 90th-percentile demand until the next cheap-buy or solar-recovery window plus 0.5 kWh; otherwise it falls back to 14%.

Negative FIT sets the Sigenergy grid export limit to zero. Solar is learned from the site's small historical PV time bands and primarily offsets grid charging.

## Manual test controls

`Manual grid rate` is a site-meter target from 0.1 to 25 kW. Start Import and Start Export persist through price changes and restarts. Stop is immediate and idempotent, returns Sigenergy to maximum self-consumption, restores the normal export limit and resumes automatic planning.

The production dashboard is `http://100.71.190.99:8123/ben-energy-optimizer/energy`. Its only routine editable controls are Buy at or below, Sell at or above, Manual grid rate, Start Import, Start Export and Stop. It also shows live power, SOC, the current reason/targets, dynamic reserve, forecast horizon, next eligible buy/sell windows and expected interval economics.

## Safety and rollback

- Battery floor: 5%.
- Site limit: 25 kW until independently verified.
- Inverter label: 30 kW Sigenergy; site limit remains separate.
- Plans expire at the exact Amber interval boundary.
- A missing/stale sensor, invalid command, alarm or failed feedback forces safe self-consumption.
- The working five-register Node-RED Modbus telemetry bridge is retained until native plant telemetry parity is physically proven.
- The native Sigenergy plant connection uses `192.168.1.101:502`, Modbus unit 247. Remote EMS is enabled and the 5% discharge cut-off is reasserted with every command.
- Slowly-changing SOC is validated numerically while the same inverter's fresh battery-power register is its liveness heartbeat. PV, load and grid each retain independent freshness checks.
- Encrypted pre-change rollback: `/root/ben-energy-optimizer-rollback/20260818T040328Z/rollback.tar.gz.enc` on Ben's host; key is root-only and stored beside it.

## Change log

- 2026-08-18: Initial standalone optimiser, economic guardrails, dynamic reserve, manual persistent import/export design and guarded Sigenergy production migration prepared.
- 2026-08-18: Deployed the isolated read-only `ben-energy-optimizer` container, least-privilege HA service identity, two-tab Node-RED telemetry/actuator flow and production dashboard. Removed the old Node-RED decision tabs and plaintext discovery/admin environment exposure; disabled the legacy SAJ/NEM decision automations.
- 2026-08-18: Corrected the Sigenergy endpoint from the unreachable `.100` host to `.101`, unit 247, then physically proved a 1 kW manual export (battery about +1.33 kW, grid about -0.99 kW), idempotent Stop, and a 1 kW manual import (battery about -0.88 kW, grid about +1.20 kW). Automatic negative-FIT zero export was also physically observed at approximately 0 kW grid flow.
- 2026-08-18: Hardened manual closed-loop correction, command supersession, direction locks, SOC heartbeat handling and null-safe retained plan attributes after live tests exposed edge cases. Validation finished with 12 Python tests, 18 Node tests, Compose/config/JSON checks, healthy containers and the automatic optimiser enabled in production.
- 2026-08-18: Removed the obsolete `ForceDischarge` and `Reset charging` script definitions. Their restored Home Assistant records are unavailable and non-callable; all legacy SAJ/NEM decision automations remain disabled. A Home Assistant restart fails safe with automatic control disarmed, after which the operator can re-enable it from the dashboard; the final deployed state is enabled.
