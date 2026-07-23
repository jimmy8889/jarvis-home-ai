# Supervised room audio activation

Room Agent 0.5 refuses Core-delivered assistant and announcement playback until
a person in the room has completed and recorded the audible acceptance test.
The refusal occurs before the room agent downloads the audio asset.

This gate is independent of TTS configuration and audio-focus ducking. A room
may be connected, report state, accept silent commands, and run diagnostics
while remaining unable to play remote speech.

## Acceptance procedure

With someone physically present and the amplifier/K3 at a safe volume:

```bash
sudo pilot-validate
sudo pilot-validate \
  --audio-tests \
  --duration 5 \
  --acceptance-receipt /var/lib/pilot/audio-acceptance.json
```

The receipt is written only when every silent check, microphone capture,
speaker playback, and simultaneous input/output test succeeds. It records the
room, ALSA capture/output selections, configured speaker node, host, timestamp,
and successful checks. It contains no credentials.

Within one hour, consciously arm that exact configuration:

```bash
sudo pilot-activate arm \
  --receipt /var/lib/pilot/audio-acceptance.json \
  --observer "James" \
  --confirm-room office \
  --yes
```

Inspect the state at any time:

```bash
sudo pilot-activate status
```

Immediately disarm remote playback before changing speakers, cabling, routing,
or room ownership:

```bash
sudo pilot-activate disarm --observer "James" --yes
```

## Automatic invalidation

The activation marker is tied to a fingerprint of:

- room ID;
- capture ALSA device;
- playback ALSA device;
- stable PipeWire speaker node.
- Room Agent release version.

Changing any of these values makes the existing marker invalid. A fresh audible
receipt and explicit arm are then required. Missing, malformed, oversized,
symlinked, or group/world-writable activation files fail closed.

The repository and Ansible examples require this gate by default. It can be
disabled only through the explicit `audio_activation_required` development
setting; production room configurations must leave it enabled.
