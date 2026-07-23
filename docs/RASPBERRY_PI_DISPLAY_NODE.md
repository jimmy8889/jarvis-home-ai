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
- The Pi resolves `display_node_performance_profile: auto` to `low-power`.
  This keeps the power-scaled travelling paths, directional battery motion and
  rack LEDs while pausing redundant SVG particles and removing repaint-heavy
  blur/drop-shadow effects. It uses solid flow strokes plus speed-optimized SVG
  rendering, and quantizes dash motion to at most 10 paint updates per second;
  all motion also pauses when the energy page is hidden or the user requests
  reduced motion. Pin `balanced` only after measuring adequate thermal headroom.
- The browser profile and its bounded caches live under
  `/var/lib/pilot-display`.
- `pilot-display-web.service` serves the local surface only on
  `127.0.0.1:8780`.
- `pilot-display-kiosk.service` owns `tty1` and launches the local surface.
- The page reads Pilot Core readiness plus an authenticated device-scoped,
  read-only surface. No Pilot administrator, Home Assistant, or Music
  Assistant credential is installed on the node or browser.
- SSH remains enabled for administration.

The deployed touch surface provides:

- Brisbane time and date
- live solar, home load, grid direction, battery power/direction, and battery SOC
- an animated power-flow diagram whose direction, speed, glow, and active
  paths follow the live Home Assistant values; an explicit hub-to-Home segment
  completes the Battery-to-Home discharge route. The balanced profile adds
  travelling particles, while the Pi profile uses the bounded moving dashes
  without continuously repainting SMIL particles
- now-playing title, artist, player, state, and volume for every active Music
  Assistant endpoint
- touch controls for room selection, play, pause, stop, and volume
- Music Assistant search with direct playback to the selected room
- Pilot Core connection and registry state
- Room and player counts
- Node address, CPU temperature, and free storage
- large Home, Energy, Music, and System touch targets
- tap and horizontal-swipe navigation
- a hidden mouse pointer in both the page styling and kiosk configuration

The Pi is enrolled in the Office room with `display` and `media-control`
capabilities. Its browser calls only the loopback display service. That service
holds the room-scoped device credential and proxies bounded media requests to
Pilot Core; neither the browser nor the Pi receives Home Assistant, Music
Assistant, or Pilot administrator credentials.

## Current source release

Pilot Linux Display 0.7.0 now also implements:

- a configurable `display` or `media-console` presentation mode;
- the shared Flow, History, Daily and Climate monitoring surfaces, including
  Tesla connection/charging, the server-rack load, Amber pricing, daily totals,
  five temperatures and seven-day weather;
- four local James House scenes selected from Home Assistant's day/night state
  and Tesla presence, with a 450 ms crossfade that never waits on the network;
  smooth watt-scaled directional paths, a visible battery charge/discharge
  direction, an explicit Home-load leg, and 100 W grid and vehicle animation
  deadbands;
- a high-resolution midnight-to-midnight power chart with timestamp-scaled
  positioning and gradient fills; home load is negative red and Tesla charging
  is negative magenta;
- a persistent selected room/output stored in browser-local presentation
  state, without persisting a credential in the browser;
- one sequenced media-state arbiter: the five-second legacy surface, full media
  poll and fast event snapshot no longer compete to rebuild the same cards;
- keyed now-playing cards and locally advancing progress, so provider polling
  cannot make the player flash, reset a volume slider, or jump backwards when
  an older response completes late;
- stale-state indication and visual de-emphasis rather than silently showing
  old data as live;
- now-playing progress and an up-next queue hint;
- a four-row US QWERTY touch keyboard with a number row; opening it shrinks the
  kiosk viewport instead of hiding the result pane, and closing it applies
  `hidden` plus `inert`, releases focus and restores the full 1024 x 600 layout;
- a loopback-only client-event snapshot proxy and assistant response overlay
  driven by `pilot.assistant.completed.v1` events.
- artwork-led Music Assistant search plus artist, album and playlist drill-down;
- device-room-bound output selection. The Office display now defaults only to
  `office-music`; it cannot silently select the alphabetically earlier Media
  Room player and then fail Pilot Core's fixed-room authorization check;
- a loopback artwork cache. TIDAL artwork is fetched only from explicitly
  allow-listed HTTPS hosts, validated as a bounded raster image and cached in
  `/var/lib/pilot-display/artwork`; the cache evicts by age, item count and a
  64 MB byte ceiling, while provider URLs and credentials never reach durable
  browser storage;
- an optional pinned Sendspin 7.5.0 player so the Pi can become a Music
  Assistant output through a USB DAC.

The production inventory installs the Pi's Sendspin runtime but intentionally
leaves it stopped and disabled because no USB DAC is connected yet. After the
DAC is attached, identify and accept its stable PipeWire sink, set
`display_node_audio_services_enabled`, `display_node_sendspin_install` and
`display_node_sendspin_enabled` to true, then set
`display_node_sendspin_audio_device`. Do not route it through an unverified
default sink. On a co-located N150, leave all three display audio settings false
because Room Agent owns that host's one audio graph and Sendspin process.

The updated Python service tests and JavaScript syntax check validate these
source paths. They have not yet replaced the physically accepted Pi release
described below. A new deployment requires the normal immutable-release,
health, touch and rollback acceptance before these additions can be called
operational on `pilot-display-pi`.

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
  display-node.yml \
  --limit pilot-display-pi \
  --ask-become-pass
```

The dedicated playbook changes only the display role. It is safe to use when
the same host is also a room endpoint and avoids needlessly replaying its audio
and voice role.

The role validates Debian 13, ARM64, Raspberry Pi hardware, and a private
mode-0600 controller copy of the device credential before making changes. A
pending display-mode reboot is recorded on disk, so an interrupted playbook
resumes safely.

Use the standard wall-display experience by leaving:

```yaml
display_node_mode: display
display_node_keyboard_layout: us
display_node_artwork_hosts:
  - resources.tidal.com
```

The same service can seed an N150 television shell with
`display_node_mode: media-console`; see [N150_MEDIA_CONSOLE.md](N150_MEDIA_CONSOLE.md).

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

The previously deployed Pi release passed:

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

The 0.7.0 service release is deployed on the Pi as immutable release
`20260723T183056`, with healthy web/kiosk services, Core connectivity and an
intact rollback pair. Repeat the reboot check and measure Chromium CPU and
temperature with several simultaneous
flows; the low-power profile now uses solid speed-optimized SVG strokes, caps
dash paint updates at 10 per second and pauses all motion off-page or under
reduced-motion preferences. Also verify the
touch keyboard, progress/queue updates, stale recovery, cached artwork and a
real assistant-completion overlay. Search for a known TIDAL artist, start a
track in Office, close the keyboard and confirm the content immediately regains
the entire display. USB-DAC playback and touch remain separate physical
acceptance gates.
