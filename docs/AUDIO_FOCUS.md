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

The enforcer is disabled by default with `audio_focus_enabled = false`. This is
intentional: source detection and gain restoration are implemented and tested,
but live activation requires the audible switching acceptance test. Enabling it
before that test could leave a source unexpectedly quiet if an upstream player
changes its PipeWire node behavior.

Before enabling in a room:

1. Confirm Music Assistant and AirPlay are each audible independently.
2. Record `wpctl status --name` while each source plays.
3. Invoke the assistant while music plays and confirm its playback stream name.
4. Enable focus with a conservative `audio_focus_duck_gain = 0.2`.
5. Confirm the original stream volume is restored after the assistant response.
6. Reboot and repeat the test.

The policy never changes the K3 hardware/default-sink volume. It adjusts only
application streams, preserving the user's room volume setting.
