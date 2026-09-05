# Pilot iOS direct standalone flow repair — 2026-08-31

## Root cause

Pilot Core fetched the standalone energy manager but rebuilt the iOS power
contract from raw `telemetry` and `devices` fields. The standalone dashboard
does not do that when a conserved flow graph is present. It derives live values
from `power_flow.sources_kw`, `sinks_kw`, `site_load_kw`, `submeters_kw`, and
the directed edge list. Pilot and the manager could therefore display
different interpretations of the same snapshot.

## Repair

Pilot Core now mirrors the standalone dashboard's `graphFlow` semantics:

- solar is `sources_kw.solar`;
- signed battery power is battery source minus battery sink;
- signed grid power is grid source minus grid sink;
- normal-house total is `site_load_kw`, with the same sink-sum fallback;
- Tesla and hot water are their graph sinks;
- server plus desk is the graph's `server_rack` submeter; and
- active paths come from manager flow edges rather than independently inferred
  thresholds.

Raw telemetry remains only as compatibility for manager snapshots without an
edge-bearing flow graph. Today's generated, used, and exported values prefer
the same snapshot `daily_energy` object rendered by the standalone dashboard.

The iOS scene uses the manager's activity conventions: 20 W for an active flow
edge, 30 W for a visible flexible load, and 50 W for import/export or battery
direction. Grid exchange below the direction deadband is labelled idle rather
than import.

## Production acceptance

Production Pilot Core image
`core-0.35.3-energy-flow-direct-20260831.1` is healthy on `apps01`. Through
`https://pilot.jameshomeautomation.work`, a temporary CFNetwork-style client
received `pilot.dashboard.v1` and `pilot.energy.v1` from
`standalone_energy_manager`. Every projected power value exactly equalled a
fresh recomputation from the manager flow graph embedded in that same response.

At the acceptance sample, both calculations returned 0 W solar, -31 W grid,
1,161 W battery discharge, 1,161 W normal-house total, 755.3 W server plus
desk, 0 W Tesla and 0 W hot water. The temporary identity was revoked.

The backend suite ran 258 tests: 257 passed and the one existing fixed-date
vehicle-maintenance assertion failed because its 2026-08-20 due date is now
overdue. All 79 iOS tests passed. A signed app build was installed and launched
on the paired iPhone 16 Pro Max; production logs confirmed repeated HTTP 200
requests from `pilot-ios-james` to both `/energy` and `/dashboard`.

## Rollback

- Image: `jarvis-home-ai/pilot-core:rollback-pre-flow-direct-20260831T123000Z`
- Source/config checkpoint:
  `/root/pilot-core-rollbacks/20260831T123000Z-flow-direct/`
