# Office endpoint deployment — 2026-07-15

## Target

- Host: `homeai` (`10.0.1.228`)
- Platform: QEMU Q35/KVM virtual machine
- Operating system: Debian GNU/Linux 13.6 (trixie)
- Kernel: `6.12.95+deb13-amd64`
- Resources: 4 vCPUs, 3.8 GiB RAM, 30 GB disk
- Deployment account: root over SSH; no credential is stored in the repository

Only individual USB audio devices are passed through. GPU, HDMI, HDA, VFIO,
IOMMU, and Proxmox host configuration were not changed.

## Current hardware and routing

```text
Input:  3212:1a01 Stadium USB microphone
Output: 2972:0047 FiiO K3

Capture ALSA:  plughw:CARD=microphone,DEV=0
Playback ALSA: plughw:CARD=K3,DEV=0
```

Stable ALSA and PipeWire selections are stored in `/etc/pilot/room.toml`.
`pilot-audio-defaults.service` resolves the stable PipeWire names to their
transient numeric IDs on every boot and applies them as the defaults. The K3
PipeWire volume is currently `0.40`.

The K3 test tones were heard through the intended physical output. Microphone
capture, speaker playback, and simultaneous input/output completed without an
ALSA error before the voice satellite was enabled.

## Installed services

The Ansible role installed PipeWire, WirePlumber, ALSA tools, BlueZ, Avahi, Git,
curl, USB tools, Python/venv, and the versioned Pilot room-agent. It created the
unprivileged `pilot` account and enabled systemd user lingering for its headless
audio session.

- `pilot-room-agent.service`: active; loopback API on `127.0.0.1:8765`
- `pilot-audio-defaults.service`: enabled; restores Stadium/K3 defaults at boot
- `pilot-linux-voice-assistant.service`: active; ESPHome API on
  `10.0.1.228:6053`
- `pilot-airplay.service`: active; classic AirPlay receiver on TCP 5000
- `pilot-sendspin.service`: active; native Music Assistant client connected to
  `10.0.2.72:8927`
- `avahi-daemon.service`: active
- `bluetooth.service`: installed but intentionally disabled/inactive

The voice runtime is Open Home Foundation Linux Voice Assistant `v1.1.12`,
pinned under `/opt/pilot/vendor`. It continuously captures the Stadium mono
source and sends responses to the K3. The temporary local wake model is
`okay_nabu`; a custom `Hey Pilot` model is a later milestone.

The satellite completed its Home Assistant configuration handshake and retains
one live connection to the Home Assistant host. AirPlay advertises as
`Pilot Office`, enters PipeWire through its PulseAudio-compatible interface, and
exposes playback/volume state over the `pilot` user D-Bus through MPRIS.
Sendspin 7.5.0 advertises as `Pilot Office Music`, exposes its own MPRIS state,
and shares the same PipeWire default sink. It automatically retries when Music
Assistant is not yet reachable during boot.

## Release and rollback state

- Active release: `/opt/pilot/releases/20260715T233241`
- Previous release: `/opt/pilot/releases/20260715T230005`
- Active link: `/opt/pilot/current`
- Previous pointer: `/var/lib/pilot/previous_release`
- Configuration archives: `/var/backups/pilot/`

Use `pilot-rollback` to atomically swap the active and previous room-agent
releases. The pinned voice runtime and persistent state are kept outside the
room-agent release tree.

## Final validation

After the Sendspin deployment and a controlled full VM reboot at
`2026-07-15 23:38 AEST`:

- all fifteen silent `pilot-validate` checks passed
- `/readyz` returned HTTP 200
- Stadium and K3 reappeared and were restored as the default source/sink
- K3 volume restored to `0.40`
- the Linux Voice Assistant microphone stream was active
- TCP `10.0.1.228:6053` was listening
- ESPHome mDNS advertised `lva-02439f365e93.local` at `10.0.1.228:6053`
- Home Assistant reconnected automatically
- AirPlay mDNS advertised `Pilot Office` at `10.0.1.228:5000`
- an AirPlay client connected and its stereo stream linked actively to the K3
- AirPlay playback state reported `Playing` through MPRIS during the test
- Sendspin started at boot, retried while Music Assistant was briefly
  unavailable, then completed its server handshake at `23:38:53 AEST`
- an established TCP connection from the Sendspin process to
  `10.0.2.72:8927` was present after reboot
- the room-agent, audio defaults, voice satellite, AirPlay, Sendspin, and Avahi
  were active
- Bluetooth remained inactive as configured

## Next action

Select **Pilot Office Music** in Music Assistant and confirm a TIDAL track and a
local lossless track are physically audible through the K3. Then test the
connected Assist pipeline with **“Okay Nabu.”** Squeezelite is retained only as
an unused fallback.

## 2026-07-16 control-plane update

- Deployed room-agent release `/opt/pilot/releases/20260716T050408` with
  Sendspin and AirPlay MPRIS playback-state reporting.
- Preserved `/opt/pilot/releases/20260716T045157` as the rollback target.
- All fifteen endpoint validation checks continued to pass.
- Built and started Pilot Core 0.2 in a disposable container, registered the
  real Office N150, and enabled outbound reporting temporarily.
- Pilot Core received authenticated health events plus `airplay=true` and
  `music=false`, then selected AirPlay as the foreground source.
- Restarted Pilot Core and verified that the device and event history persisted
  in SQLite.
- Disabled temporary reporting, removed the temporary device credential from
  the endpoint, and destroyed the disposable container volume.
- Installed the audio-focus engine in its explicit disabled state with a
  conservative `0.2` ducking gain ready for the audible acceptance test.

The office endpoint is therefore back in its production-safe configuration:
voice, AirPlay, and Sendspin remain active, while central reporting and live
gain enforcement remain disabled until a permanent Pilot Core host and the
audible switching test are complete.
