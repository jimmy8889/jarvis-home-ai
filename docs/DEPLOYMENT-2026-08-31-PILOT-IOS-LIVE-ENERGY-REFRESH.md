# Pilot iOS live energy refresh repair — 2026-08-31

## Incident

Pilot Core's authenticated `pilot.energy.v1` and `pilot.dashboard.v1`
responses contained correct live values from the standalone energy manager,
but a connected iOS client could continue displaying its cached startup
snapshot. The client waited for an energy event after its initial refresh,
while Core does not emit an event for every energy-manager sample.

## Repair

`PilotModel.runUpdateLoop()` now owns a cancellable monitoring task that
refreshes `/energy` and `/dashboard` every five seconds while the device remains
configured and connected. Existing event-driven refreshes remain available for
immediate changes. The app still receives only device-scoped Pilot Core
contracts and does not connect to Home Assistant or the energy manager itself.

Pilot Core's energy authority remains the standalone manager at
`10.0.1.205:8787`: snapshot and plan provide live state, daily provides
Brisbane-day totals, and series provides durable five-minute history.

## Acceptance

- The production HTTPS origin returned `pilot.energy.v1` and
  `pilot.dashboard.v1`, both sourced from `standalone_energy_manager`.
- Live Core fields reconciled with the manager snapshot, including solar,
  import/export, battery power, house load, SOC and rack load.
- The focused backend suite passed 31 tests.
- The native Pilot scheme built successfully for the generic iOS Simulator,
  including the embedded Watch target.
- The polling regression test passed on an iPhone simulator without an energy
  event.
- The full `PilotTests` selection passed 79 tests with no failures.
- A signed device build was installed on the paired iPhone 16 Pro Max and the
  installed `com.jameshazell.pilot` process launched successfully.

Do not pass `-sdk iphonesimulator` globally when building the Pilot scheme;
Xcode must select the iOS and watchOS Simulator SDKs per target.
