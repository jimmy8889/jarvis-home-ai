# Media Room

The first Media Room milestone is deliberately read only. Pilot Core discovers,
normalizes, and displays the Denon and Shield state without changing receiver
power, input, volume, playback, grouping, or Home Assistant state.

## Verified discovery

Read-only discovery on 2026-07-17 established:

| Component | Provider identity | Local identity |
|---|---|---|
| Denon AVC-X8500H | Music Assistant player `1174905188`, provider `heos` | `10.0.1.150` |
| Denon Home Assistant entity | `media_player.media_room` | Media Room |
| NVIDIA Shield | Music Assistant player `upb0713734fca0742d2bf2125b59cbf3b1` | `10.0.1.101` |

Music Assistant reported the Denon as available and powered, with model,
firmware, playback, and volume state. Home Assistant independently exposed
volume, mute, source, supported features, and media metadata. No provider
command or Home Assistant service call was used during discovery.

## Registry model

Pilot Core registers:

- `media-room-heos` as the default Media Room music player;
- `media-room-assistant` as the future response route;
- `media-room-shield` as the licensed video surface.

The Denon entries join Music Assistant player `1174905188` with Home Assistant
HEOS entity `media_player.media_room`. The Shield is currently joined through
its unambiguous Music Assistant identity; ambiguous legacy Home Assistant
Shield entities are intentionally not guessed.

The accepted `media-room-heos` music route now has `control_enabled = true`.
The separate assistant-response and Shield routes remain read-only. This keeps
music transport and bounded Denon control available without yet authorizing
automatic announcements or third-party video-app control.

The separate Home Assistant Denon AVR integration is now installed and exposes
the receiver as `media_player.media_room_3`. Its native power, volume, and input
controls have been physically accepted. Pilot Core uses that entity as the
receiver's separate control endpoint:

```toml
endpoint = "media_player.media_room"
control_endpoint = "media_player.media_room_3"
```

The first entity remains the HEOS state/metadata view. The second is used only
for bounded receiver power and input selection. Music Assistant remains
authoritative for queues, playback, transfer, and music volume.

Pilot Core 0.18 retains its configuration-only, allowlisted Denon port-8080
adapter as a rollback option. It is no longer selected in production.

Both `/v1/media` and `/v1/rooms/media-room/media` enforce the per-player gate
before an integration request is made.

## Read-only APIs

- `GET /v1/media/state` returns normalized state for every configured player.
- `GET /v1/rooms/media-room/media-state` scopes the snapshot to Media Room.
- `GET /v1/players/media-room-heos/state` returns the Denon music view.
- `GET /v1/players/media-room-shield/state` returns the Shield view.
- `GET /v1/operations` includes the same state for the dashboard.

Provider-neutral effective state includes availability, power, playback state,
volume percentage, mute, source, and current media where available. Provider
sections retain the safe identifiers needed for diagnosis, plus model,
firmware, and IP address. Provider credentials, MAC addresses, unfiltered
identifier maps, and unfiltered provider payloads are not returned.

## Activation sequence

Media Room control stays locked until an in-person acceptance session:

1. Confirm the Denon and Shield identities still map to the intended room.
2. Confirm a safe starting receiver volume.
3. Exercise power and source selection explicitly.
4. Test play, pause, stop, and volume through Music Assistant.
5. Test HEOS recovery after receiver and Pilot Core restarts.
6. Set `control_enabled = true` only for the accepted player paths.
7. Add assistant speech and announcements separately after interruption
   behaviour is understood.

An N150-to-HDMI endpoint remains deferred. Native HEOS will be evaluated first.

Pilot Core supports `play`, `pause`, `stop`, `set_volume`, `play_media`, and
`transfer` through Music Assistant. It also supports bounded `power_on`,
`power_off`, and `select_source` commands through the configured native Home
Assistant `media_player` control entity. Arbitrary Home Assistant services,
entities, Denon commands, paths, and sources cannot be supplied by the caller.

## Acceptance harness

`deploy/scripts/pilot-media-room-acceptance` performs the discovery phase
without sending a receiver, Shield, playback, power, source, group, or volume
command. It checks Pilot Core readiness, central observability, Music Assistant
and Home Assistant state, the exact accepted Denon/Shield provider identities,
and the current control gate.

On the Pilot Core host:

```bash
deploy/scripts/pilot-media-room-acceptance \
  --token-file infra/secrets/pilot_core_admin_token
```

The legacy `discovery` phase requires both Media Room players to remain
read-only. `--phase control-ready` requires the Denon music route to be enabled
while the Shield remains fail-closed.
