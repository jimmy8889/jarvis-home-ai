# Pilot Core observability

Pilot Core 0.10 derives one bounded operational view from the same room,
provider, media, command, and event snapshot used by the dashboard.

## Interfaces

All operational interfaces require the administrator bearer token and return
`Cache-Control: no-store`.

- `GET /v1/operations` includes `observability` alongside the full dashboard
  snapshot.
- `GET /v1/observability` returns the smaller status, alert, and check model.
- `GET /v1/metrics` returns Prometheus text exposition.

The observability model reports one of:

- `healthy`: no active operational or safety condition;
- `guarded`: operational checks pass but audible actions remain fail-closed;
- `degraded`: one or more provider, endpoint, freshness, or player warnings;
- `critical`: reserved for conditions that make the control plane unsafe.

Checks cover configured integrations, explicitly enrolled `realtime-agent`
room endpoints, 90-second
telemetry freshness, normalized media-player resolution, and control-gate
visibility. Rooms with no endpoint are reported as `not_enrolled` rather than
being silently treated as connected. Polling and user-launched clients are
reported as `on_demand`; their lack of a permanent WebSocket is not an outage.

Metrics intentionally expose no credentials, unfiltered provider payloads,
media titles, device MAC addresses, or personal content. Current gauges cover
Core availability, room/device counts, connected endpoints, pending commands,
integration health, room audio activation, player resolution, and overall
observability status.

## Dashboard

The operations dashboard renders the derived status in its system posture and
lists active alerts under **Active attention**. A safely locked audio path is
informational; an offline/stale endpoint, unhealthy configured integration, or
unresolved player is a warning.

The dashboard remains an operator surface. It does not expose an unauthenticated
public status page.
