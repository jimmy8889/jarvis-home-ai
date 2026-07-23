# Validation and acceptance tests

Validation is intentionally split into three evidence classes:

- **source tested**: automated contract, unit, lint and build checks pass;
- **deployed healthy**: the promoted release passes backup, readiness,
  authentication, persistence and rollback checks on its target host;
- **physically accepted**: a person has observed the actual microphone,
  speakers, touch/focus surfaces, display and media equipment.

A source build must not be reported as a deployed or physically accepted
capability.

## Stage 0: product-contract validation

Before deployment, run the same service checks as CI:

```bash
python -m unittest discover -s apps/pilot-core/tests -v
PYTHONPATH=apps/display-node \
  python -m unittest discover -s apps/display-node/tests -v
python -m unittest discover -s apps/room-agent/tests -v
node --check apps/display-node/pilot_display_node/static/app.js
for schema in packages/event-schema/*.json; do
  python -m json.tool "$schema" >/dev/null
done
```

The Core product-contract suite must cover:

- device-scoped manifest, snapshot, energy and feature gates;
- persistent presentation policy and inferred-room mutation rejection;
- resumable events and snapshot recovery;
- single-use pairing, credential rotation and revocation;
- typed media commands and structured assistant output.

Android wall, Shield TV and iOS test/build gates are defined in
`.github/workflows/ci.yml`. A successful simulator/emulator build proves source
compatibility only; it does not replace phone, tablet or Shield acceptance.

## Stage 1: device visibility

Run `sudo pilot-hardware-inventory`. Confirm that the microphone and output
device appear in `lsusb`, the microphone appears under `arecord -l`, and the DAC
or speakers appear under `aplay -l`. If a device is absent here, fix the native
USB connection before changing PipeWire.

## Stage 2: service health

Run `sudo pilot-validate`. This silent test checks:

- the `pilot` account and lingering state
- PipeWire and WirePlumber user services
- room-agent system service and HTTP health
- presence of ALSA capture and playback devices
- Linux Voice Assistant service, configured API socket, and an established Home
  Assistant connection, when enabled
- Pilot AirPlay service and its configured RTSP socket, when enabled
- Music Assistant Sendspin connectivity, when enabled
- the authenticated Pilot Core command connection, when enabled

## Stage 3: microphone and speaker

Set speakers to a safe level, then run:

```bash
sudo pilot-validate --audio-tests --duration 5
```

Use explicit ALSA device names if `default` is not the intended USB hardware:

```bash
sudo pilot-validate --audio-tests \
  --capture-device plughw:CARD=MicName,DEV=0 \
  --playback-device plughw:CARD=DACName,DEV=0
```

When stable `capture_alsa_device` and `playback_alsa_device` values exist in
`/etc/pilot/room.toml`, `pilot-validate --audio-tests` uses them automatically.
Command-line device arguments override the configured values.

The test records speech, plays it back, and then records while replaying the
same bounded sample. The last stage proves simultaneous input/output at the
device layer; it does not yet validate acoustic echo cancellation.

Before an audible voice test, validate the central local speech engines:

```bash
deploy/scripts/pilot-voice-acceptance \
  --core-url http://10.0.1.64:8770
```

This fixed-phrase check must report the configured Piper engine and voice,
Faster Whisper transcript, 16 kHz mono 16-bit PCM, and at least 0.8 word
coverage. It is silent and does not test the room microphone, speaker, wake
word, or acoustics.

This validates whichever private speech pipeline is currently configured. The
planned dedicated production Whisper deployment on the RTX 3080 remains
deferred until that GPU is installed. Do not point meeting processing at an
unverified endpoint and do not treat an Ollama text-model endpoint as Whisper.

For the supervised production acceptance, create the one-hour arming receipt:

```bash
sudo pilot-validate --audio-tests \
  --acceptance-receipt /var/lib/pilot/audio-acceptance.json
```

Follow [SUPERVISED_ACTIVATION.md](SUPERVISED_ACTIVATION.md) to arm the exact
validated output. Until then, Core-delivered audio fails closed before download.

## Stage 4: reboot persistence

Reboot the endpoint, wait for SSH, and rerun the silent and audible checks. Also run:

```bash
systemctl is-enabled pilot-room-agent
systemctl is-active pilot-room-agent
systemctl is-active pilot-audio-defaults
systemctl is-active pilot-linux-voice-assistant
sudo -u pilot XDG_RUNTIME_DIR=/run/user/$(id -u pilot) \
  systemctl --user --no-pager status pipewire wireplumber
```

Acceptance requires two consecutive clean reboots with the same devices, active
services, successful capture and playback, and no USB/audio errors in the boot
journal.

For a combined N150 media console, also verify that Cage and Room Agent share
the `pilot-display` identity and private Wayland session after each reboot:

```bash
uid=$(id -u pilot-display)
systemctl show pilot-display-kiosk pilot-room-agent \
  --property=User --property=Environment
sudo -u pilot-display env \
  XDG_RUNTIME_DIR=/run/user/$uid WAYLAND_DISPLAY=wayland-0 \
  test -S /run/user/$uid/wayland-0
```

The room endpoint inventory must set
`room_endpoint_video_wayland_display` to that socket. A successful source test
does not replace physical confirmation that mpv becomes visible through Cage,
uses the intended HDMI audio path, and returns cleanly to the Pilot shell.

## Stage 5: command transport

After Pilot Core reports the room device as connected, start with a state-only
command that cannot produce sound:

```bash
deploy/scripts/pilot-command \
  --core-url http://PILOT_CORE_HOST:8770 \
  --device-id pilot-office \
  --wait 10 \
  start_listening
```

Confirm it succeeds, then send `cancel`. Defer pause, playback, volume, and
announcement commands until someone can observe the physical room. Repeating a
completed command ID through reconnect testing must return the journaled result
without executing the action twice.

## Stage 6: client pairing and product acceptance

For each iOS, Android, Shield or Linux display identity:

1. create a room- and profile-bound single-use grant in the dashboard and
   verify its QR and copyable code are present;
2. redeem it once and confirm that a second redemption fails;
3. confirm the manifest exposes only the intended capabilities and endpoints;
4. restart the client and verify encrypted credential persistence;
5. exercise event reconnect, cursor recovery and stale-state presentation;
6. rotate the credential where the client supports self-rotation, then verify
   the old token fails;
7. revoke the device in Core and verify further requests fail;
8. repeat with the real input/output hardware and record physical acceptance.

Home controls require an additional check: an entity with an inferred room may
be displayed read-only, but its mutation must return `403`. Promote the mapping
through the Home Assistant registry or an explicit administrator presentation
override, then verify only its returned typed actions become usable.

## Stage 7: deployment promotion

Before promoting Core, create and verify the documented cold backup. After
deployment, check LAN readiness, authenticated manifest/snapshot access,
invalid-token rejection, event persistence across container restart, pairing
grant expiry/single use and the entity-presentation editor. Retain the previous
immutable image and restore procedure until the release has completed its
physical acceptance window.

## Troubleshooting evidence

Collect these before changing configuration:

```bash
sudo pilot-hardware-inventory
journalctl -b -u pilot-room-agent --no-pager
journalctl -b _UID=$(id -u pilot) --no-pager
dmesg --level=err,warn
```
