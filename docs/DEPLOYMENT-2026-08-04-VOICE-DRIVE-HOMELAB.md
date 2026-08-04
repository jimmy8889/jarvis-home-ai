# Phone Voice, Pilot Drive and Home Lab Display — 2026-08-04

## Scope

- Pilot iOS voice capture now accepts ordinary phone speech down to `-42 dB`,
  auto-submits after sustained silence and fails closed after 20 seconds with
  an explicit no-speech error. Pilot Core's synthetic TTS-to-STT acceptance
  already passed before this client change.
- Tesla climate control uses the HVAC modes actually advertised by
  `climate.jarvis_hvac_climate_system`: `heat_cool` to start and `off` to stop.
- Tesla navigation remains restricted to `SEND_GPS_TO_VEHICLE`; production
  requires the file-backed `tesla_vehicle_id` secret.
- Bedroom retains its display/assistant response endpoint but no longer
  publishes a nonexistent music player.
- Pilot Display `0.8.0` adds an authenticated Home Lab page with Proxmox node,
  workload, temperature and TrueNAS pool summaries. The display never receives
  infrastructure provider credentials.
- The Home Assistant Grafana iframe uses same-origin Supervisor ingress instead
  of the public hostname, avoiding the cross-origin frame refusal.
- Home Lab snapshots now normalise integral values such as TrueNAS uptime and
  memory to JSON integers, matching the strict Swift decoder. Core and display
  polling use a five-second cadence; the Pi renders CPU and each GPU's
  utilization independently.

## Rollback

Pilot Core deployment must use `deploy/scripts/pilot-core-deploy`, which takes a
database/config archive before replacing the immutable image. The Pi playbook
creates a timestamped release and changes only the `current` symlink after its
health check succeeds. The previous release remains available for an atomic
symlink rollback.

## Physical acceptance still required

- Speak a normal sentence into Pilot on the paired iPhone and confirm transcript,
  locally reasoned response and spoken audio.
- Send a saved destination to Jarvis and confirm it appears in Tesla navigation.
- Confirm climate start/stop while the vehicle is available.
- Visually inspect the Home Lab page on the 1024x600 Raspberry Pi.

## 2026-08-04: Home Lab contract and update cadence

Pilot Core `0.35.1` is deployed on apps01 as
`core-0.35.1-homelab-20260804.1`. The Home Lab API remains
`pilot.homelab.v1`, but provider-normalised integer fields are now guaranteed
to be JSON integers. This prevents the iOS `DecodingError.typeMismatch` failure
caused by TrueNAS returning uptime as a floating-point number.

The iOS Home Lab page refreshes while visible every five seconds. The
Raspberry Pi display refreshes the authenticated Home Lab projection every five
seconds and shows `CPU n%` plus `GPU1 n%`, `GPU2 n%`, etc. The Core cache is also
set to five seconds so the faster cadence is meaningful without making every
screen request a provider call.
