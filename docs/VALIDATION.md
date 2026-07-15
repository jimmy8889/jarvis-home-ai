# Validation and acceptance tests

## Stage 1: device visibility

Run `sudo pilot-hardware-inventory`. Confirm that the microphone and output
device appear in `lsusb`, the microphone appears under `arecord -l`, and the DAC
or speakers appear under `aplay -l`. If a device is absent here, fix Proxmox USB
passthrough before changing PipeWire.

## Stage 2: service health

Run `sudo pilot-validate`. This silent test checks:

- the `pilot` account and lingering state
- PipeWire and WirePlumber user services
- room-agent system service and HTTP health
- presence of ALSA capture and playback devices
- Linux Voice Assistant service, configured API socket, and an established Home
  Assistant connection, when enabled
- Pilot AirPlay service and its configured RTSP socket, when enabled

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

## Stage 4: reboot persistence

Reboot the VM, wait for SSH, and rerun the silent and audible checks. Also run:

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

## Troubleshooting evidence

Collect these before changing configuration:

```bash
sudo pilot-hardware-inventory
journalctl -b -u pilot-room-agent --no-pager
journalctl -b _UID=$(id -u pilot) --no-pager
dmesg --level=err,warn
```
