# Pilot Core

Pilot Core 0.13 is the authenticated control-plane foundation for Pilot OS. It
persists the canonical room/player registry, registered room devices, source
state, event history, and durable device command queue in SQLite.

## Security model

- An administrator bearer token protects room, player, device, media,
  assistant, and event-history APIs.
- An administrator issues short-lived bootstrap grants bound to one room and
  device. Each grant can be redeemed once.
- Registration returns a random device token exactly once; only its SHA-256
  digest is stored.
- A device may publish events only for its assigned room.
- Room agents connect outbound to Pilot Core. Their diagnostic API remains
  loopback-only.
- Device commands use the same per-device identity and can only be completed by
  the device to which they were assigned.
- Production secrets are mounted as individual files and never appear in
  Compose environment values or repository configuration.

## API

Public health endpoints:

- `GET /healthz`
- `GET /readyz`
- `GET /dashboard` for the operations dashboard shell

Administrator endpoints:

- `GET /v1/operations` for the dashboard's joined operational snapshot
- `GET /v1/state` for a joined all-room snapshot
- `GET /v1/rooms` and `GET /v1/rooms/{room_id}`
- `GET /v1/rooms/{room_id}/state`
- `GET /v1/rooms/{room_id}/media-state`
- `POST /v1/rooms/{room_id}/media`
- `POST /v1/rooms/{room_id}/control`
- `GET /v1/players` and `GET /v1/players/{player_id}`
- `GET /v1/players/{player_id}/state`
- `GET /v1/devices`
- `POST /v1/bootstrap-grants`
- `GET /v1/integrations/diagnostics`
- `GET /v1/events`
- `WS /v1/events/ws`
- `GET /v1/media`
- `GET /v1/media/state`
- `POST /v1/media` for play, pause, stop, volume, URI playback, and transfer
- `POST /v1/media/search`
- `POST /v1/assistant`
- `GET /v1/assistant/status`
- `GET /v1/conversations`
- `GET /v1/conversations/{conversation_id}`
- `DELETE /v1/conversations/{conversation_id}`
- `GET /v1/tts`
- `POST /v1/rooms/{room_id}/speak`
- `POST /v1/rooms/{room_id}/audio-assets`
- `POST /v1/rooms/{room_id}/audio`
- `POST /v1/devices/{device_id}/commands`
- `GET /v1/devices/{device_id}/commands`
- `GET /v1/commands`
- `GET /v1/commands/{command_id}`

Provisioning and device endpoints:

- `POST /v1/devices/bootstrap` using a one-time bootstrap grant
- `POST /v1/devices/register` is legacy-only and disabled in production
- `POST /v1/events` using device ID and device bearer token
- `WS /v1/devices/ws?device_id=...` using device ID and device bearer token
- `GET /v1/devices/{device_id}/snapshot` for bounded weather, rolling
  temperature history, and service state
- `GET /v1/devices/{device_id}/surface` for bounded energy and whole-network
  now-playing state
- `POST /v1/devices/{device_id}/voice` for bounded 16-bit mono PCM
- `GET /v1/devices/{device_id}/firmware` for the validated OTA manifest
- `GET /v1/devices/{device_id}/firmware/image` for the private OTA image

The embedded-node routes require both the matching `X-Pilot-Device-ID` header
and that device's bearer token. Voice and OTA additionally require the matching
device capability. Home Assistant credentials, raw provider weather payloads,
and filesystem paths are never returned to the node.

Version 0.14 reads only the configured indoor and outdoor Home Assistant
temperature sensors for the requested rolling window. It computes current,
minimum, and maximum values and projects each history to exactly 24
display-safe points. Raw recorder history and unrelated attributes never reach
the embedded node.

The authenticated surface additionally normalizes five configured energy
sensors to watts/percent and projects only active Music Assistant players.
Positive grid power means importing and negative means exporting; positive
battery power means discharging and negative means charging for the deployed
SAJ sensors. Raw Home Assistant attributes, Music Assistant media URIs, image
proxy URLs, and central credentials are not returned.

The shared dashboard energy contract uses `home_timezone` to expose a fixed
local calendar-day window through `history.started_at`, `history.ended_at`, and
`history.window = "calendar_day"`. It retains up to 288 display-safe points for
solar, battery, home load, and Tesla charging. Consumption series are
normalized below zero (`home_load` in red and `tesla` in magenta), so iOS,
Android, Raspberry Pi, and N150 displays all render the same sign convention.
Temperature histories remain separate rolling windows and retain their lower
point cap.

The command transport and its queued, delivered, terminal, expiry, reconnect,
and idempotency behavior are documented in
[COMMAND_TRANSPORT.md](COMMAND_TRANSPORT.md).

Local speech synthesis and secure room playback are documented in
[LOCAL_TTS.md](LOCAL_TTS.md) and [AUDIO_DELIVERY.md](AUDIO_DELIVERY.md).
Room-scoped conversation persistence, deterministic routing, local model
fallback, and the typed tool boundary are documented in
[CONTEXTUAL_ASSISTANT.md](CONTEXTUAL_ASSISTANT.md).

Room target resolution and room-level state, media, and control contracts are
documented in [ROOM_ORCHESTRATION.md](ROOM_ORCHESTRATION.md).

## Operations dashboard

Open `http://PILOT_CORE_HOST:8770/dashboard` from the trusted LAN and enter the
Pilot Core administrator token. The token is held only in the browser tab's
`sessionStorage`; it is not written to cookies, durable browser storage, the
server, or the repository.

The dashboard polls the authenticated `/v1/operations` endpoint every 15
seconds and shows:

- connected room endpoints and their latest health;
- deterministic source/focus state per room;
- Home Assistant, Music Assistant, and local TTS readiness;
- contextual-assistant configuration and recent session metadata;
- the supervised audio-activation gate;
- recent device commands and events;
- Pilot Core release, version, uptime, and registry revision.

The only command exposed by this first operations surface is `cancel`, which
clears transient listening, assistant, announcement, and source state. Audible
playback, volume, speech, and home-control actions remain intentionally absent.
Static dashboard responses are served with a same-origin content-security
policy, no-store caching, referrer suppression, MIME sniffing protection, and
framing disabled.

Pilot Core 0.9 adds provider-neutral media state. Configured Music Assistant
players are matched by their stable external ID, with a name fallback recorded
explicitly when required. A configured `media_player.*` endpoint is joined with
read-only Home Assistant state. The normalized result exposes availability,
power, playback, volume, mute, source, media metadata, and a bounded device
description without returning raw provider payloads.

Player discovery and player control are independent. A player with
`control_enabled = false` remains visible in the registry, state APIs, and
dashboard, while every media mutation is rejected before an integration call.
The verified Media Room model is documented in
[MEDIA_ROOM.md](MEDIA_ROOM.md).

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

Use `deploy/scripts/pilot-secrets init`, add long-lived integration tokens over
standard input, then run `deploy/scripts/pilot-core-deploy`. Persistent state is
stored in the `pilot-core-data` volume. Full operating and recovery procedures
are in [PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md).

Issue and redeem a one-time Office grant:

```bash
deploy/scripts/pilot-bootstrap-device \
  --core-url http://PILOT_CORE_HOST:8770 \
  --device-id pilot-office \
  --room-id office \
  --name "Office N150" \
  --capability audio --capability voice \
  --output /secure/path/office-bootstrap.json

deploy/scripts/pilot-register-device \
  --core-url http://PILOT_CORE_HOST:8770 \
  --grant-file /secure/path/office-bootstrap.json \
  --device-token-file /secure/path/office-device-token
```

Store the returned device token in Ansible Vault and enable the
`room_endpoint_core_reporting_*` and `room_endpoint_core_commands_*` variables.
The role writes it to a `0600` file owned by the `pilot` service account.
For a one-time local deployment, set
`room_endpoint_core_device_token_source_file` to the mode-`0600` token file on
the Ansible controller; the token remains out of inventory, process arguments,
and command output. Ansible Vault remains the durable production option.
After enrollment, subsequent role runs preserve an existing endpoint token when
neither token input is supplied. A fresh or rebuilt endpoint still fails closed
until a new credential is provided.
