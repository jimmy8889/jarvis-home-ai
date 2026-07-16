# Secure room audio delivery

Pilot Core 0.6 can deliver pre-rendered assistant speech and announcements to a
deterministically selected room endpoint. This closes the transport and
playback part of the voice-response path without allowing room agents to fetch
arbitrary URLs.

```text
TTS/client ── admin upload ──► Pilot Core audio asset
                                     │
                         room/device resolution
                                     │ authenticated command
                                     ▼
                              Room agent manifest
                                     │ authenticated download
                                     ▼
                         SHA-256 + size verification
                                     │
                                     ▼
                          PipeWire transient playback
```

## Security and room boundaries

- Audio assets belong to exactly one configured room.
- Upload and playback requests require the Pilot Core administrator token.
- Downloads require a valid per-device bearer credential and the device must
  be registered to the asset's room.
- The room-agent command contains an asset ID, content type, byte count, and
  SHA-256 digest. It never contains a caller-controlled download URL.
- The room agent accepts WAV, FLAC, MP3, OGG, and AAC only, downloads into a
  private cache, verifies the complete manifest, and then invokes `pw-play` with
  an argument vector rather than a shell.
- Verified endpoint cache files older than 24 hours are removed automatically.
- Assets expire automatically. The default retention is one hour and may be
  configured from 60 seconds to 24 hours.
- The default maximum asset size is 20 MB on both Pilot Core and room agents.

Production Pilot Core deployments should be placed behind TLS. Device tokens
must remain in `/etc/pilot/device-token` with mode `0600` and must never be
included in commands, logs, or Git.

## API workflow

Upload raw audio bytes:

```http
POST /v1/rooms/{room_id}/audio-assets?kind=assistant&filename=reply.wav
Authorization: Bearer {admin-token}
Content-Type: audio/wav
```

Queue the resulting asset for its room:

```http
POST /v1/rooms/{room_id}/audio
Authorization: Bearer {admin-token}
Content-Type: application/json

{
  "asset_id": "32-character-hex-id",
  "volume": 0.8,
  "critical": false,
  "expires_in_seconds": 30
}
```

Pilot Core resolves a registered audio-capable endpoint and the room's response
player. The room agent reports command success after it has downloaded,
verified, and started the local playback process. Current source state remains
visible through room-agent reporting for the duration of playback.

Room agents use this authenticated endpoint internally:

```http
GET /v1/audio-assets/{asset_id}
Authorization: Bearer {device-token}
X-Pilot-Device-ID: {device-id}
```

Administrator inspection and deletion endpoints are:

- `GET /v1/rooms/{room_id}/audio-assets`
- `DELETE /v1/audio-assets/{asset_id}`

## Operator test

`pilot-audio` performs upload, dispatch, and optional command-result polling:

```bash
export PILOT_CORE_ADMIN_TOKEN='...'
deploy/scripts/pilot-audio \
  --core-url https://pilot-core.example \
  --room-id office \
  --kind assistant \
  --volume 0.7 \
  --wait 10 \
  reply.wav
```

For a critical alert, use `--kind announcement --critical`. Critical mode is
intentionally rejected for ordinary assistant speech.

## Playback lifecycle

Only one transient speech/announcement process is owned by a room agent at a
time. A new asset replaces the previous transient playback. `cancel` terminates
the active process and clears assistant and announcement focus state without
stopping the room's music queue. Natural process completion also clears its
state.

This design lets the audio-focus loop duck Music Assistant or AirPlay while
speech is active. Live gain enforcement remains independently disabled until an
audible acceptance test can be performed in the physical room.

## Safe activation order

1. Deploy Pilot Core 0.5 with persistent `/data/audio` storage.
2. Register the Office device and install its token.
3. Enable room reporting and commands, but leave audio focus enforcement off.
4. Confirm the endpoint command WebSocket is connected.
5. Send non-audible `start_listening` and `cancel` commands.
6. While someone is physically present, send a quiet WAV with `pilot-audio`.
7. Verify K3 output, completion state, cancellation, and reboot recovery.
8. Test speech while music plays before enabling the focus enforcer.

The live Office endpoint is intentionally not upgraded or activated until the
physical audible checks can be observed.

Pilot Core can now create these assets from text through the local provider
adapter described in [LOCAL_TTS.md](LOCAL_TTS.md).
