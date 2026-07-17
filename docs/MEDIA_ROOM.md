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
entity `media_player.media_room`. The Shield is currently joined through its
unambiguous Music Assistant identity; ambiguous legacy Home Assistant Shield
entities are intentionally not guessed.

All three players have `control_enabled = false`. This is distinct from
`enabled`: discovery and state remain available while mutation is rejected.
Both `/v1/media` and `/v1/rooms/media-room/media` enforce the gate before an
integration request is made.

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
