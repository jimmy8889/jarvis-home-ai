# Pilot Core

Pilot Core 0.2 is the authenticated control-plane foundation for Pilot OS. It
persists the canonical room/player registry, registered room devices, source
state, and event history in SQLite.

## Security model

- An administrator bearer token protects room, player, device, media,
  assistant, and event-history APIs.
- A separate bootstrap token can register or rotate a room device.
- Registration returns a random device token exactly once; only its SHA-256
  digest is stored.
- A device may publish events only for its assigned room.
- Room agents connect outbound to Pilot Core. Their diagnostic API remains
  loopback-only.
- Secrets are environment variables or Ansible-provided files and never belong
  in repository configuration.

## API

Public health endpoints:

- `GET /healthz`
- `GET /readyz`

Administrator endpoints:

- `GET /v1/rooms` and `GET /v1/rooms/{room_id}`
- `GET /v1/players` and `GET /v1/players/{player_id}`
- `GET /v1/devices`
- `GET /v1/events`
- `WS /v1/events/ws`
- `GET /v1/media`
- `POST /v1/media` for play, pause, stop, volume, URI playback, and transfer
- `POST /v1/media/search`
- `POST /v1/assistant`

Provisioning and device endpoints:

- `POST /v1/devices/register` using the bootstrap token
- `POST /v1/events` using device ID and device bearer token

The event stream carries health and source-state changes. Source events produce
a deterministic focus decision using this priority:

1. Critical announcements
2. Assistant speech
3. Bluetooth
4. AirPlay
5. Music Assistant

The current release computes and publishes the desired gains. Applying those
gains to live PipeWire streams remains gated until the audible TIDAL/AirPlay
switching test establishes safe source identifiers and restoration behavior.

## Central deployment

Use `infra/docker-compose.yml`. Copy `infra/.env.example` to the ignored
`infra/.env`, generate strong admin/bootstrap tokens, and add long-lived Music
Assistant and Home Assistant API tokens. Persistent state is stored in the
`pilot-core-data` volume.

Register the office endpoint with:

```bash
PILOT_CORE_BOOTSTRAP_TOKEN=... \
  deploy/scripts/pilot-register-device \
  --core-url http://PILOT_CORE_HOST:8770 \
  --device-id pilot-office \
  --room-id office \
  --name "Office N150" \
  --capability audio --capability voice
```

Store the returned device token in Ansible Vault and enable the
`room_endpoint_core_reporting_*` variables. The role writes it to a `0600`
file owned by the `pilot` service account.
