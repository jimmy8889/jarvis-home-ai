# Audio focus and ducking

Pilot uses one explicit source priority in both Pilot Core and the room agent:

1. Critical announcements
2. Assistant speech
3. Bluetooth
4. AirPlay
5. Music Assistant

Pilot Core calculates the desired foreground source and gains whenever a room
publishes a `source_state` event. The room agent contains a local enforcement
loop that discovers stable application streams from `wpctl status --name`,
captures their existing per-stream volume, applies the requested gain, and
restores the captured volume when focus returns.

## Local control API

Room-agent 0.2 adds `POST /v1/control` on the existing loopback-only listener.
It is deliberately not exposed to the LAN. Pilot integrations running on the
endpoint can use it to coordinate transport, volume, listening, speech, and
announcement state without manipulating PipeWire directly.

Supported actions:

| Action | Important fields | Effect |
|---|---|---|
| `play`, `pause`, `stop` | `source`: `music`, `airplay`, or `all` | MPRIS transport control |
| `set_volume` | `source`, `volume` from 0 to 1 | PipeWire room or MPRIS source volume |
| `start_listening`, `stop_listening` | optional `ttl_seconds` | Push-to-talk/listening focus state |
| `assistant_start`, `assistant_end` | optional `ttl_seconds` | Assistant speech focus state |
| `announcement_start`, `announcement_end` | `critical`, optional `ttl_seconds` | Announcement focus state |
| `cancel` | none | Clears transient focus state without stopping music |

Example:

```bash
curl -sS http://127.0.0.1:8765/v1/control \
  -H 'Content-Type: application/json' \
  -d '{"action":"start_listening","ttl_seconds":30}'
```

Every active transient state expires after at most five minutes. Default
timeouts are 30 seconds for listening and 120 seconds for speech or an
announcement. This prevents a failed caller from leaving lower-priority audio
permanently ducked. `GET /v1/status` includes the current control state and its
monotonic revision.

The core reporter publishes all five source states: critical, assistant,
Bluetooth, AirPlay, and music. Bluetooth remains false until the A2DP sink is
implemented.

The gain enforcer is disabled by default with `audio_focus_enabled = false`.
This is intentional: source detection and gain restoration are implemented and
tested, but live activation requires the audible switching acceptance test.
Enabling it before that test could leave a source unexpectedly quiet if an
upstream player changes its PipeWire node behavior.

Before enabling in a room:

1. Confirm Music Assistant and AirPlay are each audible independently.
2. Record `wpctl status --name` while each source plays.
3. Invoke the assistant while music plays and confirm its playback stream name.
4. Enable focus with a conservative `audio_focus_duck_gain = 0.2`.
5. Confirm the original stream volume is restored after the assistant response.
6. Reboot and repeat the test.

The policy never changes the K3 hardware/default-sink volume. It adjusts only
application streams, preserving the user's room volume setting.
