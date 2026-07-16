# Room-aware orchestration

Pilot Core 0.4 treats a room ID as the stable public routing boundary. Clients
do not need to know Music Assistant queue IDs, Sendspin IDs, or the device
currently acting as the room endpoint.

## Deterministic target policy

For media:

1. Validate the originating room.
2. Use an explicitly requested player only when it belongs to that room and is
   enabled.
3. Otherwise use the room's configured `default_music_player_id`.
4. For transfer, independently resolve the target room's default music player.
5. Translate registry player IDs to provider `external_id` values at the Music
   Assistant boundary.

For endpoint controls:

1. Validate the originating room.
2. Infer `voice` capability for listening and assistant lifecycle commands;
   infer `audio` for transport, volume, announcements, and cancel.
3. Restrict candidates to registered devices assigned to the room with that
   capability.
4. Honour an explicit device only if it passes those checks.
5. Prefer a currently connected candidate, then the room's configured
   `default_device_id`, then lexical device ID as the stable tie-breaker.
6. If no device is online, queue the command for the deterministic offline
   candidate rather than guessing a different room.

An LLM may turn language into a typed request, but it never selects raw
infrastructure identifiers.

## Room state

`GET /v1/rooms/{room_id}/state` returns one joined snapshot containing:

- room configuration and players
- resolved response and default music targets
- current source activity and update timestamps
- deterministic audio-focus state
- registered room devices and capabilities
- live command-socket connection state
- latest reported health for each device

This endpoint is the basis for answering “what is playing where?” and for
future room dashboards. It intentionally reports locally observed source state;
provider-specific track metadata remains owned by Music Assistant.

`GET /v1/state` returns the same joined snapshot for every configured room,
keyed by room ID, with the registry revision used to construct it.

## Room media API

`POST /v1/rooms/{room_id}/media` supports:

- `play`
- `pause`
- `stop`
- `set_volume`
- `play_media`
- `transfer`

Examples:

```json
{"action":"play"}
```

```json
{"action":"set_volume","volume":35}
```

```json
{"action":"transfer","target_room_id":"media-room"}
```

The optional `player_id` and `target_player_id` fields are controlled overrides,
not required routing inputs.

The operator helper uses the same API:

```bash
export PILOT_CORE_ADMIN_TOKEN='...'
deploy/scripts/pilot-media \
  --core-url http://PILOT_CORE_HOST:8770 \
  --room-id office \
  play
```

## Room endpoint-control API

`POST /v1/rooms/{room_id}/control` accepts the same actions as the direct device
command API, but resolves the device automatically.

```bash
deploy/scripts/pilot-command \
  --core-url http://PILOT_CORE_HOST:8770 \
  --room-id office \
  --wait 10 \
  cancel
```

The direct player and device APIs remain available for diagnostics and explicit
administrative overrides.
