# Raspberry Pi Display Node

The first large-format Pilot display is a dedicated Raspberry Pi appliance,
not a general desktop.

## Deployed hardware

```text
Host: pilot-display-pi / 10.0.2.26
Computer: Raspberry Pi 4 Model B, 2 GB
Storage: 16 GB microSD
Display: 10-inch HDMI, 1024 x 600
Touch: ILITEK USB touchscreen
OS: 64-bit Debian 13 Trixie with Raspberry Pi kernel
Timezone: Australia/Brisbane
```

The display's EDID advertised only 800 x 600. The deployment therefore uses
the current Raspberry Pi KMS kernel argument:

```text
video=HDMI-A-1:1024x600M@60D
```

Ansible preserves the original `config.txt` and `cmdline.txt` before changing
the boot configuration. The argument is normalized token-by-token so repeated
deployments cannot duplicate it.

## Runtime

The node deliberately avoids a full desktop:

- Cage provides the single-application Wayland compositor.
- Chromium runs as the unprivileged `pilot-display` user in kiosk mode.
- The browser profile and its bounded caches live under
  `/var/lib/pilot-display`.
- `pilot-display-web.service` serves the local surface only on
  `127.0.0.1:8780`.
- `pilot-display-kiosk.service` owns `tty1` and launches the local surface.
- The page reads Pilot Core readiness plus an authenticated device-scoped,
  read-only surface. No Pilot administrator, Home Assistant, or Music
  Assistant credential is installed on the node or browser.
- SSH remains enabled for administration.

The touch surface provides:

- Brisbane time and date
- live solar, home load, grid direction, battery power/direction, and battery SOC
- now-playing title, artist, player, state, and volume for every active Music
  Assistant endpoint
- Pilot Core connection and registry state
- Room and player counts
- Node address, CPU temperature, and free storage
- large Home, Energy, Music, and System touch targets
- tap and horizontal-swipe navigation

The Pi is enrolled provisionally in the Office room with only the `display`
capability. This provides read access to the bounded surface and cannot send
Home Assistant or media-control commands.

## Storage controls

The 16 GB card is sufficient for the appliance:

- Chromium disk cache is capped at 50 MiB.
- Chromium media cache is capped at 10 MiB.
- Persistent journals are capped at 128 MiB and seven days.
- APT archives are cleaned after deployment.
- Automatic security updates are enabled without automatic reboot.
- Only the active and immediately previous application releases are retained.

The 2026-07-19 acceptance run left 7.8 GB free.

## Deployment

Configure the host under the `pilot_display_nodes` inventory group and run:

```bash
cd deploy/ansible
../../.venv/bin/ansible-playbook \
  -i inventory/hosts.yml \
  site.yml \
  --limit pilot-display-pi \
  --ask-become-pass
```

The role validates Debian 13, ARM64, Raspberry Pi hardware, and a private
mode-0600 controller copy of the device credential before making changes. A
pending display-mode reboot is recorded on disk, so an interrupted playbook
resumes safely.

## Operations

```bash
systemctl status pilot-display-web pilot-display-kiosk
curl http://127.0.0.1:8780/healthz
curl http://127.0.0.1:8780/api/status
journalctl -b -u pilot-display-web -u pilot-display-kiosk
```

Roll back to the prior immutable application release:

```bash
sudo pilot-display-rollback
```

The rollback command validates that the target remains inside the release
directory, atomically swaps the symlink, restarts both services, and requires
the local health endpoint to recover. Physical acceptance exercised it in both
directions successfully.

## Acceptance receipt

The deployed node passed:

- native 1024 x 600 KMS mode after reboot
- ILITEK touchscreen discovery on `seat0`, unprivileged input access, Chromium
  touch events, and native page navigation
- Cage and Chromium reboot persistence with zero kiosk restarts
- local web health and loopback-only binding
- Pilot Core readiness and registry retrieval
- Brisbane timezone and synchronized NTP
- automatic security-update timers
- 466 MiB active memory use with about 1.3 GiB available
- no current or historical thermal throttling
- two-way application rollback
