# Pilot iOS energy backend deployment — 2026-08-31

## Authority

This moved Pilot project is the authoritative app and backend source. The
native app connects to `https://pilot.jameshomeautomation.work` and consumes
the authenticated `pilot.energy.v1` and `pilot.dashboard.v1` contracts.

Pilot Core reads the standalone energy manager at `10.0.1.205:8787` directly:

- `/api/v1/snapshot` supplies current power, SOC, tariff, flow and health;
- `/api/v1/plan` supplies the dispatch plan;
- `/api/v1/daily` supplies the current Brisbane-day totals; and
- `/api/v1/series` supplies durable five-minute chart history.

Home Assistant is not the source of truth for those energy fields. Pilot Core
remains a read-only energy-manager client and performs no energy actuation.

## App refresh diagnosis and repair

Pilot Core does not publish a client event for every energy-manager sample.
The iOS update loop previously refreshed `/energy` and `/dashboard` once at
startup and thereafter only when a matching event arrived. A connected app
could therefore keep showing cached power values indefinitely even though both
backend contracts were returning correct live data.

The iOS update loop now polls both authenticated contracts every five seconds
while it is connected. The polling task is cancelled with the update loop, and
event-driven refresh remains in place for immediate updates when an applicable
event is available.

## Production acceptance

A temporary personal-device identity was issued locally, paired through the
production HTTPS origin with a CFNetwork-style client, and then revoked.
Production returned:

- HTTP 201 from `/v1/devices/bootstrap`;
- HTTP 200 and `pilot.energy.v1` from `/energy`;
- HTTP 200 and `pilot.dashboard.v1` from `/dashboard`;
- `standalone_energy_manager` as the energy and dashboard source;
- `standalone_energy_manager_series` as the history source;
- 244 five-minute samples for solar, whole-house load, battery and Tesla; and
- manager and energy status `ok`.

The focused backend suite passed 31 tests. The full Pilot Core suite passed
256 tests; one unrelated fixed-date vehicle-maintenance test now expects
`due_soon` for a 2026-08-20 date that is correctly classified as `overdue` on
2026-08-31.

The native `Pilot` scheme builds successfully for the generic iOS Simulator
destination, including its embedded Watch target. The focused simulator test
`testLiveMonitoringRefreshesWithoutAnEnergyEvent` passed and proves that two
five-second polling cycles refresh without an energy event. The full iOS
`PilotTests` selection passed 79 tests with no failures. The build command must
not force `-sdk iphonesimulator` globally because that incorrectly applies the
iOS SDK to the Watch target.

A signed Debug build was then installed on the paired iPhone 16 Pro Max. The
installed `com.jameshazell.pilot` application launched successfully and was
observed as a running device process.

## Rollback

The production Core checkpoint remains:

- image `jarvis-home-ai/pilot-core:rollback-ios-energy-20260831T094925Z`;
- source `/root/pilot-core-rollbacks/20260831T094925Z/` on `apps01`.

The retired James House `solar-monitor` container remains stopped and retained;
it is not part of the Pilot iOS backend path.
