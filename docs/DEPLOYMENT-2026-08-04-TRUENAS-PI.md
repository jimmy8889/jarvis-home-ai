# TrueNAS and Raspberry Pi Update — 2026-08-04

## Pilot Core

- The TrueNAS credential is stored only in the apps01 file-backed secret with
  mode `0640`, owned by root and the Pilot service group.
- Pilot Core now establishes a TrueNAS WebSocket session with
  `auth.login_with_api_key` before requesting system, pool, disk, temperature,
  and alert inventory.
- Core image `core-0.33.1-truenas-wss-20260804.4` passed Docker health plus
  Home Assistant, Music Assistant, and TTS diagnostics.
- The first key was revoked by TrueNAS after an insecure transport attempt.
  Core now refuses to transmit TrueNAS credentials over plain WebSockets and
  uses encrypted `wss://10.0.1.102/api/current` transport exclusively.
- The appliance presents a self-signed certificate issued to `localhost`, so
  the encrypted LAN connection cannot yet pass CA or hostname verification.
  Verification is disabled only for this provider until a LAN-valid TrueNAS
  certificate is installed.
- The renewed key passed secure authentication. Pilot reports TrueNAS 25.10.4,
  three healthy online pools, nine disks, free/allocated capacity, drive
  temperatures and three informational alerts. Overall Home Lab status is
  healthy.
- Latest pre-deployment backup:
  `infra/backups/pilot-core-20260803T230006Z-pre-deploy-core-0.33.1-truenas-wss-20260804.4.tar.gz`.

## Raspberry Pi display

- Host `pilot-display-pi` at `10.0.2.26` was upgraded through the dedicated
  Ansible display playbook to immutable release `20260804T084804`.
- Its stale Core route through `10.0.1.64` was replaced by the current Pilot
  API configuration, and authenticated Core/surface requests now succeed.
- Display 0.7.2, Cage, Chromium, PipeWire, WirePlumber, and the loopback web
  service survived a full reboot with zero service restarts.
- The prior release `20260723T224400` remains available through
  `pilot-display-rollback`.
- Sendspin remains installed but disabled until a specific USB DAC sink is
  physically attached and accepted.
