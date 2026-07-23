# Office native endpoint deployment — 2026-07-16

## Target

- Host: `officen150` (`10.0.1.53`)
- Platform: native Intel N150 appliance
- Operating system: Debian GNU/Linux 13.6 (trixie)
- Network interface: `enp2s0`
- Deployment account: root over SSH; no credential is stored in the repository

The native installation replaces the original Proxmox VM after music playback
on the virtualized endpoint exhibited skipping. The permanent endpoint keeps
the existing room identity while removing USB passthrough and VM scheduling
from the production audio path.

## Hardware and routing

```text
Input:  3212:1a01 Stadium USB microphone
Output: 2972:0047 FiiO K3

PipeWire source: alsa_input.usb-Stadium_USB_microphone_Stadium_USB_microphone_201907-00.mono-fallback
PipeWire sink:   alsa_output.usb-FiiO_K3-00.analog-stereo
Validation I/O:  pipewire
```

The host also exposes a CSCTEK USB Audio/HID device, JetKVM USB emulation,
onboard Intel Bluetooth, and Intel HDMI audio. Pilot leaves those outputs
untouched and restores the Stadium/K3 pair as the configured defaults.

## Deployment

The Ansible room-endpoint role installed PipeWire, WirePlumber, ALSA utilities,
BlueZ, Avahi, Git, Python/venv, Shairport Sync, Sendspin 7.5.0, Linux Voice
Assistant v1.1.12, and the Pilot room-agent. It created the unprivileged
`pilot` service user with systemd lingering.

Native deployment exposed one VM-specific assumption: the voice service used
the hard-coded interface `ens18`. The role now derives the default interface
from Ansible IPv4 facts and rendered `enp2s0` on this host.

The first audible validation also exposed two harness issues. Raw `plughw`
capture conflicted with the continuously running voice service, and the root
created temporary directory was not writable by `pilot`. Validation now uses
the shared PipeWire route and explicitly assigns the temporary directory to the
service account.

## Home Assistant

Home Assistant discovered the native endpoint as `lva-e051d81d452f`. It was
registered in the **Office** area and configured with:

- wake word: **Okay Nabu**
- assistant: **Full local assistant**
- speech-to-text: local Whisper
- text-to-speech: local Piper (`amy (low)` at setup time)

The original VM entities remain unavailable in Home Assistant and are retained
temporarily as migration history. The new native entities are live.

## Validation and rollback

- Active release: `/opt/pilot/releases/20260716T061242`
- Previous release: `/opt/pilot/releases/20260716T060859`
- Configuration archives: `/var/backups/pilot/pre-*.tar.gz`
- Central Pilot Core reporting: disabled
- Live audio-focus enforcement: disabled
- Bluetooth receiver: disabled

Before reboot, microphone capture, K3 playback, and simultaneous input/output
all completed successfully through PipeWire. After a controlled reboot at
`2026-07-16 06:34 AEST`, all 15 silent `pilot-validate` checks passed:

- PipeWire and WirePlumber
- Pilot room-agent and health API
- ALSA capture and playback hardware
- Linux Voice Assistant service/API and Home Assistant connection
- AirPlay receiver service/listener
- Sendspin service and Music Assistant connection

Software-directed K3 playback is verified. Final physical audibility and
skip-free TIDAL/local-FLAC listening remain user-observed acceptance checks.

## Next acceptance gate

1. Play a TIDAL track through **Pilot Office Music** for at least 15 minutes.
2. Play a local lossless file for at least 15 minutes.
3. Confirm no skipping or service intervention is required.
4. Invoke **Okay Nabu** during playback and verify transcription, an Office
   Home Assistant action, and a spoken response through the K3.
5. Switch to AirPlay and back to Sendspin, then confirm both recover cleanly.
