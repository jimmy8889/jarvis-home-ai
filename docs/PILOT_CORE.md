# Pilot Core

Pilot Core 0.6 is the authenticated control-plane foundation for Pilot OS. It
persists the canonical room/player registry, registered room devices, source
state, event history, and durable device command queue in SQLite.

## Security model

- An administrator bearer token protects room, player, device, media,
  assistant, and event-history APIs.
- A separate bootstrap token can register or rotate a room device.
- Registration returns a random device token exactly once; only its SHA-256
  digest is stored.
- A device may publish events only for its assigned room.
- Room agents connect outbound to Pilot Core. Their diagnostic API remains
  loopback-only.
- Device commands use the same per-device identity and can only be completed by
  the device to which they were assigned.
- Secrets are environment variables or Ansible-provided files and never belong
  in repository configuration.

## API

Public health endpoints:

- `GET /healthz`
- `GET /readyz`

Administrator endpoints:

- `GET /v1/state` for a joined all-room snapshot
- `GET /v1/rooms` and `GET /v1/rooms/{room_id}`
- `GET /v1/rooms/{room_id}/state`
- `POST /v1/rooms/{room_id}/media`
- `POST /v1/rooms/{room_id}/control`
- `GET /v1/players` and `GET /v1/players/{player_id}`
- `GET /v1/devices`
- `GET /v1/events`
- `WS /v1/events/ws`
- `GET /v1/media`
- `POST /v1/media` for play, pause, stop, volume, URI playback, and transfer
- `POST /v1/media/search`
- `POST /v1/assistant`
- `GET /v1/tts`
- `POST /v1/rooms/{room_id}/speak`
- `POST /v1/rooms/{room_id}/audio-assets`
- `POST /v1/rooms/{room_id}/audio`
- `POST /v1/devices/{device_id}/commands`
- `GET /v1/devices/{device_id}/commands`
- `GET /v1/commands/{command_id}`

Provisioning and device endpoints:

- `POST /v1/devices/register` using the bootstrap token
- `POST /v1/events` using device ID and device bearer token
- `WS /v1/devices/ws?device_id=...` using device ID and device bearer token

The command transport and its queued, delivered, terminal, expiry, reconnect,
and idempotency behavior are documented in
[COMMAND_TRANSPORT.md](COMMAND_TRANSPORT.md).

Local speech synthesis and secure room playback are documented in
[LOCAL_TTS.md](LOCAL_TTS.md) and [AUDIO_DELIVERY.md](AUDIO_DELIVERY.md).

Room target resolution and room-level state, media, and control contracts are
documented in [ROOM_ORCHESTRATION.md](ROOM_ORCHESTRATION.md).

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
`room_endpoint_core_reporting_*` and `room_endpoint_core_commands_*` variables.
The role writes it to a `0600` file owned by the `pilot` service account.
