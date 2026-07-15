# Pilot Core

Pilot Core begins as a deliberately small, dependency-free room and player
registry. It gives every client one authoritative answer to these questions:

- Which rooms exist?
- Which players belong to each room?
- Where should assistant responses play?
- Which player receives an unqualified music request from that room?

The registry is validated at startup. Duplicate identifiers, missing player
references, cross-room default players, and players assigned to unknown rooms
prevent the process from starting.

## Run locally

```bash
cd apps/pilot-core
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pilot-core --config ../../config/core.example.toml
```

The initial read-only API listens on loopback TCP 8770:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/rooms`
- `GET /v1/rooms/{room_id}`
- `GET /v1/rooms/{room_id}/players`
- `GET /v1/players`
- `GET /v1/players/{player_id}`

The `/readyz` response includes a deterministic registry revision so clients can
detect configuration changes.

## Security boundary

Pilot Core and the room-agent both remain loopback-only at this stage. Before
central health polling is enabled, Pilot will add device identity,
authentication, and encrypted transport rather than exposing the existing
diagnostic endpoint directly across the home network.
