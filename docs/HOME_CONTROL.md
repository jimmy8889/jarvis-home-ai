# Governed Home Control

Pilot Core 0.21 turns the read-only Home Assistant catalogue into a
device-scoped control plane without becoming an arbitrary service proxy.

## Trust boundary

- Home Assistant remains authoritative for entity state and service execution.
- A client receives only entities mapped to the selected Pilot room.
- A fixed-room device cannot name a different room. A portable client can,
  but only when enrolled with `portable-client`.
- Read access requires `home-read` or `home-control`; mutation requires
  `home-control`.
- Client apps never hold a Home Assistant token.

Room mappings are explicit in `config/core.container.toml`:

```toml
[[rooms]]
id = "office"
home_area_ids = ["office", "james_office"]
```

Unassigned entities and entities outside those areas are not controllable.

## Device API

```text
GET  /v1/devices/{device_id}/home/model
GET  /v1/devices/{device_id}/home?room_id=office
POST /v1/devices/{device_id}/home/actions
POST /v1/devices/{device_id}/home/actions/{action_id}/confirm
GET  /v1/devices/{device_id}/home/actions/{action_id}
```

The action body contains an entity, an advertised typed action, and at most
four bounded scalar parameters:

```json
{
  "room_id": "office",
  "entity_id": "light.office_lamp",
  "action": "set_brightness",
  "parameters": {"value": 35}
}
```

Pilot independently resolves the entity from its normalized catalogue and
does not trust client-supplied domain or service names.

## Risk and confirmation

Lights, switches, fans and climate are low-risk. Covers and scenes are
medium-risk. Locks, alarm panels and garage covers are high-risk.

A high-risk request returns HTTP 202 and a pending action. The same device
must confirm the action within 120 seconds. Confirmation claims the request
atomically, so retries cannot execute it twice. Expired, replayed or
cross-device confirmations fail closed.

## Reconciliation and audit

After Home Assistant accepts a command, Pilot reads the entity back up to
three times and records whether the authoritative state matched. A scene may
be `unverified` because activation does not have a universal terminal state.

Administrator endpoints expose the action history and append-only audit:

```text
GET /v1/home/actions
GET /v1/home/actions/{action_id}/audit
```

Audit entries cover request, approval, rejection/expiry, success, failure and
unverified completion. They contain bounded metadata and never store provider
credentials.

## Release and rollback

Deploy through `deploy/scripts/pilot-core-deploy`. The deploy script produces
a cold archive of the database and persistent assets before replacing the
container. Roll back with `deploy/scripts/pilot-core-rollback` and the archive
reported by the deployment.
