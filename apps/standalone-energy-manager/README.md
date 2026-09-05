# Standalone Energy Manager

This service is the independent control plane for the SAJ inverter, Tesla BLE charger and hot-water relay. Home Assistant, Pilot, MQTT, InfluxDB and Node-RED are not in the control loop; local planning and control continue if any of them is unavailable.

Release `0.5.5` adds a fused resilience model. Fresh SAJ three-phase
voltage/frequency is authoritative for utility state; fresh NUT input and
`OL`/`OB` status independently describe the protected supply and provide a
lower-confidence fallback when SAJ is stale. The published states are
`healthy`, `degraded`, `lost` and `unknown`, and source disagreement remains
visible rather than being converted into a false outage. A confirmed outage
cancels battery export and grid charging, stops Tesla and hot-water loads, and
leaves the inverter in self-consumption so the house battery can continue
supporting ordinary demand. Flexible loads remain inhibited until five
continuous healthy minutes have elapsed.

The UPS tab labels the main outlet **Server rack** and PowerShare 1 **Office**.
PowerShare 2 remains in raw MQTT/Influx telemetry but is intentionally absent
from the dashboard. Rack, office, protected output, conversion loss and wall
input are conserved; rack/office are submeters of the whole-house load and are
never added to it again. SQLite and `/api/v1/outages` retain outage epochs,
duration, minimum UPS charge/runtime, highest stage and recovery result.
Home Assistant receives typed MQTT entities and phone notifications from the
manager's publish-only event stream.

The whole-site scene shows both instantaneous power and actual Brisbane-day
energy at each node: solar generated, normal-house consumption, grid import
and export, battery charge/discharge, Tesla charge, hot-water service and rack
output. Home-battery and Tesla SOC remain visible beside animated gauges;
Tesla SOC uses retained TeslaMate telemetry even while the car is away. The
home gauge indicates live charge/discharge, the Tesla gauge indicates active
charging, and lightweight CSS effects show rack activity and a heating
hot-water cylinder. Reduced-motion preferences disable these animations.

The staged physical-node shutdown path is installed but
`ENERGY_MANAGER_RESILIENCE_SHUTDOWN_ENABLED` defaults to false and is false in
production. It can only send an orderly Proxmox node `shutdown` request, in the
order `pvebackup`, `pvedell`, `pve3080`, after first arming the signed recovery
companion. There is no guest-specific, NUT outlet, UPS output or hard-power-cut
method. Enabling this path and performing a shutdown test requires a separately
approved maintenance window.

The unprivileged recovery companion on `10.0.1.206` reads local NUT state,
accepts only a fresh HMAC-signed outage epoch, waits for five continuous mains
minutes, then sends allowlisted Wake-on-LAN packets to `pvedell`, `pvebackup`
and `pve3080`. It has no Proxmox credentials and exposes no UPS command. WOL is
persistently enabled on each node's active `nic0`; live packet verification was
performed while all nodes remained powered on.

Release `0.5.4` makes the manager the direct read-only owner of the Eaton UPS
telemetry exposed by NUT at `10.0.1.206:3493`. One persistent connection reads
all 97 `nutdev1` variables once per second, matching the Pi's configured
`usbhid-ups` one-second poll interval. The retained `energy-manager/server-rack`
frame includes raw values, sample sequence, poll duration and freshness. MQTT
Discovery creates typed Home Assistant entities for every variable, while
dynamic electrical fields are also written to `energy_nut` in InfluxDB. The
calculated Server + desk wall input uses `ups.realpower / ups.efficiency`; the
old fixed 80% calculation remains diagnostic only. The Pi, its credentials and
its NUT configuration are not modified by this integration.

The standalone portal includes a dedicated UPS and server-rack tab for live
power, resilience, power quality, controlled outlets and hardware health. Its
graphs use a bounded six-hour in-memory ring and return no more than 720
downsampled points, so the browser view remains independent of InfluxDB and
does not add polling load to the Raspberry Pi.

Release `0.5.2` makes the manager the sole SAJ Modbus TCP owner. It reads the
coherent PV/flow block and the dedicated three-phase meter once per second,
publishes the resulting frame at `energy-manager/saj/realtime`, decodes
inverter faults and derives debounced grid/phase availability. Slower battery,
identity, control and lifetime-energy registers are cached at appropriate
cadences so one-second power telemetry does not flood the inverter. Home
Assistant receives read-only MQTT Discovery entities and no longer polls or
writes the SAJ directly. The manager explicitly replaces a failed pymodbus
transport before reconnecting, preventing abandoned concurrent sockets.
The MQTT compatibility entities that retain historic SAJ Home Assistant IDs
publish power in watts, matching the retired integration and the existing
InfluxDB/Grafana history. Manager-native JSON remains in kilowatts. This avoids
a 1,000x discontinuity at cutover while preserving one-second source precision.

Release `0.4.20` adds two prominent persisted master switches shared by both
dashboards. **Energy automation** enables full forecast control. Turning it off
first performs one complete SAJ self-consumption handover, then prohibits every
further inverter write; EV and all other optimiser actions remain disabled.
While disabled, the independent hot-water governor ignores economic settings
and requests the relay continuously from 11:00 until 14:00 Brisbane. **Hot
water enabled** is the higher-priority Away switch: off always commands the
relay off, including during the timer window.
The clock-only relay governor runs independently of SAJ dispatch, Amber,
forecasting, MQTT, InfluxDB and Home Assistant. If SAJ telemetry is unavailable,
the timer still guarantees the relay window but records source control as
unavailable because battery/grid isolation cannot be proven without Modbus.

Release `0.4.0` makes the internal dashboard and Home Assistant Energy Manager dashboard one paired interface. Both display the manager's same live snapshot and schema-v3 plan, and both write the same authenticated REST settings. Every user-visible telemetry, forecast, planning or setting change therefore updates both dashboard definitions in the same release. Repository validation is not proof that a release has been deployed or physically accepted.

The hot-water scheduler includes the currently active five-minute settlement
interval when replanning a few seconds after an Amber boundary. Once the element
has started, that interval remains committed so a revised price or forecast
cannot repeatedly move the service into the next block. The measured-solar and
4pm service guards remain authoritative. On process start or HA migration, the
manager establishes a five-second relay-off baseline before resuming a due
block, ensuring the physical 3.7 kW load step can be confirmed and credited.

## Release 0.4.0

- The rolling 36-hour plan is schema v3. It includes a human-readable current summary and next actions, protected battery trajectory, flexible-load schedule, export windows, and solar/battery/grid allocation.
- Live and planned energy allocation use a conserved edge graph. Sources and sinks are explicit, meter residual and confidence remain visible, and clients do not silently reconstruct authoritative flows when a graph is available.
- Export reporting separates solar and battery energy, battery gross revenue, wear, retained-energy value, net benefit and total export revenue. Five-minute outcomes and daily totals record realised results separately from forecasts.
- The dashboard settings are unified: minimum battery sell price, opportunistic EV FIT ceiling, Tesla charge limit, EV grid permission, optimiser enable and an EV trip profile of `No trip`, `100 km`, `200 km`, `Charge to 80%`, or `Ensure 100%`. `ev_trip_profile` is canonical; `ev_trip_requirement` is accepted only as a compatibility alias.
- Read-only NUT telemetry adds server-and-desk power, daily energy, UPS state and confidence. The rack is included as an identified house sub-load in live flow, forecasts and reports.
- NUT telemetry includes battery charge/capacity/runtime and thresholds;
  charger/protection state; input, bypass and output electrical measurements;
  UPS load, power, efficiency and temperature; main and both PowerShare outlet
  measurements/states; transfer limits; timers; self-test state; nominal
  ratings; identity, firmware and driver diagnostics. These are observations,
  not command entities: the manager never sends `SET`, `INSTCMD` or shutdown
  commands to NUT.
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

Live negative Amber FIT enables inverter anti-reflux and a zero-export limit while leaving PV available to the house, battery, EV and hot water. Cached advanced-price intervals are promoted at their exact five-minute boundary and replaced by the live interval when Amber publishes it. Positive FIT never applies zero export. Battery export requires the live Amber FIT to meet the configured minimum sell price, clear direct wear plus uncertainty, and remain above the forecast protected-SOC trajectory. Because that trajectory has already allocated future house energy, the live import price is not charged against the same surplus tranche a second time. AEMO is recorded for comparison and cannot dispatch the system.

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
Assistant control automations were removed. Release 0.5.2 retires the Home
Assistant SAJ config entry and the local Meter A poller after exporting their
configuration. Read-only MQTT entities retain the familiar IDs used by cards
and historical dashboards. Rollback checkpoints
are documented in the authoritative energy-automation runbook. The retired
Tesla BLE and hot-water ESPHome entries can be re-enabled only as part of a
deliberate rollback after the standalone manager has relinquished those devices.

The hot-water firmware is a pinned PlatformIO build with its exact ESPHome rollback binary and checksums stored root-only in LXC 103. Do not reflash it without live relay/element visibility and an operator present. The stepped 30 kW charge/discharge commissioning remains a separate physical procedure.

## API and dashboard

The dashboard is `http://10.0.1.205:8787/`. **Normal house total** is the complete
SAJ `TotalLoad` demand, including Tesla, hot water and the Server + desk
submeter. Tesla, hot water and the rack remain visible as non-additive detail;
they are not added to the whole-house total a second time. Typed dashboard
settings are writable without a bearer token from the trusted local network.
Manual actuator overrides remain token-protected. The live house scene and
energy timeline provide separate **Dispatch plan** and **What happened** tabs. The
planner and live Tesla governor share the configured three-phase power-per-amp
conversion, so a planned 6 A / 4.14 kW block cannot be rounded down and rejected.
During negative FIT, fresh Ecowitt expected uncurtailed generation is the Tesla
feed-forward budget with non-EV loads subtracted directly; no opportunity-cost
attenuation is applied. During positive low FIT the configured attenuation is
retained. The rolling plan cannot veto a live solar opportunity. Grid and
stationary-battery feedback retain a 0.3 kW meter-noise
deadband and then reduce current using the same calibrated kW-per-amp
conversion. An active session steps down by at most 1 A per 30 seconds and
holds the physical 6 A minimum for one interval before stopping.
Each local stop sends both the custom lease cancellation and an idempotent
direct BLE charger-switch-off command; an accepted firmware service call alone
is not treated as proof that charging stopped.
The downward ramp keeps its own commanded-current state, so BLE feedback
flickering between adjacent amp values cannot restart the 30-second timer or
prevent the final stop.
Once the local charger switch reports off, the dormant configured-amps value is
ignored for semantic confirmation, preventing redundant stops from resetting
the physical-stability timer used by hot water.
planned view covers the next 36 hours; the actual view reads completed
five-minute outcomes only while selected. Both show solar, ordinary house,
Tesla, hot water, battery and grid power. Hot-water bars are physically bounded
to the 3.7 kW element instead of filling the chart height. EV demand below 40% is included
in the predicted SOC path and is limited to forecast solar plus stationary
battery energy above the protected reserve unless EV grid permission is on.
Read-only snapshot, plan, history, events and stream endpoints are exposed under
`/api/v1`. Settings and overrides require `Authorization: Bearer <api_token>`.

Mutable settings are minimum sell price, opportunistic EV FIT ceiling, EV grid permission, Tesla charge limit, EV trip profile and optimiser enable. The internal dashboard and Home Assistant use the same authenticated REST settings endpoint, and the manager remains their source of truth. Home Assistant polls the current settings every two seconds so a change made on either dashboard converges on both. MQTT is publish-only while the broker allows anonymous clients.

MQTT Discovery entities have individual availability. A missing future plan value is exposed as unavailable without sending invalid text through numeric power, energy or monetary sensors.

The SAJ relay publishes one retained JSON frame per second. Power fields are
captured in one `0x406E..0x40AD` read followed immediately by the Meter A block;
`sample_skew_ms`, `cycle_duration_ms`, `sample_sequence`, read errors and
reconnect count make coherence visible. The relay exposes total and per-array
PV, whole-house and diagnostic backup load, battery/inverter/grid power, each
meter phase, SOC/SOH/voltage/temperature/cycles, energy counters, inverter
status, decoded active/last faults, and grid online/partial/offline state.
The old Home Assistant config entry has been removed and MQTT Discovery is now
enabled. Legacy entity IDs therefore continue as read-only MQTT entities
without a second Modbus client.

The target network contract is a dedicated SAJ VLAN 90 (`10.0.90.0/24`), with
the inverter logger fixed at `10.0.90.24`. Only energy manager
`10.0.1.205 -> 10.0.90.24:502/tcp` is allowed from the trusted LAN. The logger
may reach WAN for SAJ Cloud plus gateway DHCP/DNS/NTP, but cannot initiate any
connection to internal networks under the DMZ zone policy. UniFi applies a
client network override for MAC `ac:15:18:b1:7d:7f`, while `Energy Manager to
SAJ Modbus` is the sole narrow allow rule. Do not add a broad DMZ-to-Internal
block above that stateful rule: it also catches the Modbus return stream. The
obsolete `SAJ to HA` rule is paused. Rollback returns the client
override and manager host to DMZ `10.0.6.24` only after the standalone manager
has relinquished the Modbus lease.

Grafana dashboards read the standalone manager's `energy_manager` Influx
bucket directly. Instantaneous total-house demand is
`energy_power.load_total_kw`; daily whole-house energy is
`energy_daily.whole_house_load_kwh`. Raw backup-load fields and retired Home
Assistant `saj_*` entity history are diagnostic/rollback data only and must not
be used by live dashboards. Normal house already includes hot water, Tesla and
rack loads, so those submeters are visual detail rather than additive demand.

The 2026-08-31 Grafana audit migrated all eight energy dashboards and scanned
all twelve installed dashboards for retired energy references. Direct query
validation passed 87/87 targets, datasource smoke tests returned data for all
nine manager measurement groups, and the two main inverter dashboards rendered
without query errors or empty panels. Historical power graphs use the
manager-produced `energy_power_1m` measurement; they never aggregate the
one-second `energy_power` series at page-load time. Live cards use a bounded
two-minute `last()` window. Daily cards use a two-day lookup and
forecast-versus-actual panels use seven days so Brisbane midnight rollups remain
visible. All energy dashboards refresh no faster than once per minute. Series
colours are consistent: solar gold, house blue, battery purple, grid red, Tesla
cyan, hot water orange and rack grey, with distinct PV-array colours.

The local Tesla BLE bridge also publishes retained device telemetry at
`energy-manager/tesla-ble`: the physical `James Car Home` presence state and
the ultrasonic `Garage Preset`. Individual retained topics are available at
`energy-manager/tesla-ble/james-car-home` and
`energy-manager/tesla-ble/garage-preset`, with matching Home Assistant MQTT
Discovery entities. These values come directly from the BLE controller rather
than TeslaMate geofence inference.

The manager remains the sole ESPHome native-API client but exposes a local
vehicle proxy for Home Assistant. Read-only state is available from
`GET /api/v1/vehicle`; authenticated callers and the configured Home Assistant
host may use `POST /api/v1/vehicle/control`. The companion Home Assistant
custom integration provides a native climate entity, vehicle lock, explicit
car-unlock and charge-port-unlock buttons, charge-port door and window covers,
steering-wheel heat, defrost, wake, flash and horn controls. Each command is
executed over local BLE and recorded in the manager event journal. Charging
current and charger switching remain exclusively owned by the optimiser.

Heated/cooled seats are not exposed: neither the pinned Tesla BLE firmware nor
the current upstream package implements seat commands. A seat entity must not
be added until the local BLE component supports and physically confirms it.

Every command envelope includes schema version, software/configuration revision, source timestamps, dispatch timestamps, expiry and a semantic command identity. Equivalent physical commands retain confirmation without unnecessary inverter writes.

For profitable discharge, the SAJ schedule power is driven by
`site_export_target_kw`. Physical commissioning showed that the inverter adds
backup-house demand separately, so writing the calculated battery-terminal
target would over-export by approximately the live house load. The separate
`battery_target_kw` remains the expected total battery output for planning and
display. Zero-site-target load-segregation modes retain their explicitly
bounded battery-power target.

Hot-water physical confirmation holds the pre-start site controls steady while
measuring the 3.7 kW element step. Ordinary price, plan, PV and EV recalculation
no longer toggles an already-on relay during that window. A genuine telemetry
fault, confirmed actuator mismatch or battery-funded element still stops it.
The relay cannot start until the physical Tesla state and current have matched
their command continuously for 30 seconds, preventing an EV ramp from being
misclassified as part of the element's load step.
When an already-charging Tesla has at least 4.2 kW of proven PV/export
headroom, the coordinator pins the requested current to the physical BLE value
for that window instead of chasing a moving optimiser target.

Plan schema v3 publishes:

- `narrative.current_summary` and `narrative.next_actions` for the human-readable plan;
- interval points with authoritative conserved `flow.edges` between `solar`, `battery`, `grid`, `house`, `server_rack`, `hot_water`, `ev` and `unaccounted`;
- explicit meter-balance residual, conservation state and confidence instead of silently presenting inferred values as measured; and
- summary/export-window fields for solar and battery export kWh, battery gross revenue, wear cost, retained value, battery net benefit and total revenue.

Older clients may reconstruct a flow only when reading a legacy schema-v2 plan. New clients must consume the v3 graph when present. Display values use one decimal place for SOC and Amber prices, whole watts below 1 kW and one decimal kW at or above 1 kW; API values retain calculation precision.

SAJ PV1/PV2/PV3 remain separate as well as total PV. PV1 is the 11.8 kWp north array; PV2 is the 14 x 590 W (8.26 kWp) south string; PV3 is the 28 x 590 W (16.52 kWp) south input. Forecast monitoring compares PV1 with the north-roof forecast and splits the common south-roof forecast one-third/two-thirds for PV2/PV3. Curtailed intervals remain visible but are excluded from calibration. Following the site rewiring, signed `TotalLoadPower` is the primary whole-house load signal. `BackupTotalLoadPowerWatt` (`0x40AB`) is retained only as a diagnostic and is expected to be near zero. Ordinary-house reporting subtracts measured Tesla and hot-water power once; it does not double-count flexible loads. Power-balance error and the dedicated `batteryPower` register remain published for diagnostics.

The browser receives lightweight two-second state through one event stream. It
rebuilds the forecast charts only when the semantic plan ID changes, loads
actual history only on demand, rate-limits actual refresh to 60 seconds, and
closes its event stream while the page is hidden. This keeps dashboard work out
of the controller loop and substantially reduces idle browser rendering.

## Verification

```bash
uv sync --extra test
uv run pytest
curl -fsS http://10.0.1.205:8787/readyz
mosquitto_sub -h 10.0.1.64 -t energy-manager/saj/realtime -C 2
```

Production readiness requires physical acceptance of zero export, self-consumption, battery export tracking, EV current ramping, hot-water confirmation and controlled Proxmox HA migration. Host-failure/reboot testing is intentionally outside this rollout.

Home Assistant's `energy-control` Sections dashboard is an optional client of the standalone MQTT Discovery entities and authenticated REST API. It shows the live relay, conserved flow, export economics, server-rack energy, Amber curves and the manager's canonical plan/timeline embeds. Its native controls update the manager through authenticated REST, never MQTT commands, and contain no legacy SAJ, Tesla or hot-water writer. Home Assistant may be stopped without interrupting local control; the standalone manager remains the sole planning and actuation authority.
