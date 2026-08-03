# Home Lab Monitoring Deployment — 2026-08-04

## Promoted release

- Pilot Core: `0.32.0`
- Immutable image: `core-0.32.0-homelab-20260804.2`
- Source commit: `6a99a81e3d6a3b0fdf9cc315a1b5cac814d4c390`
- Core host: apps01 at `10.0.1.204`
- Rollback archive:
  `infra/backups/pilot-core-20260803T171247Z-pre-deploy-core-0.32.0-homelab-20260804.2.tar.gz`
- Rollback SHA-256:
  `e74122ec850a133ca30b607eb99610ab4e83e531db56aaa8e57186f6ae0ac7a3`

The guarded deployment passed readiness, Home Assistant, Music Assistant and
TTS diagnostics. Audible actions remained gated.

## Live providers

Pilot uses `pilot-monitor@pve!pilot-core`, inherited from a user restricted to
`PVEAuditor` at `/`. The token secret is file-backed on apps01 and was never
written into Git or returned by a client API.

Production acceptance returned:

- Cluster `James-Home-Lab`, quorate, three of three nodes online.
- Nodes `pve3080`, `pvebackup` and `pvedell` with live CPU, memory, root storage
  and uptime.
- 24 discovered virtual workloads, 22 running at acceptance time.
- Live RTX 3080 and RTX 3090 agents with CPU, memory, disk, GPU utilization,
  VRAM, temperature and power telemetry.
- Pilot Core and its Docker health check both healthy after restart.

TrueNAS was discovered at `10.0.1.102`, but its dedicated Pilot API key has not
yet been created. Its panel deliberately reports `API key required`; the other
providers remain healthy and visible.

## Clients

The Pilot iOS Home Lab tab was simulator-built, then signed, installed and
launch-verified on the paired iPhone 16 Pro Max. It retains the last successful
snapshot for offline viewing and marks live agent data stale after 45 seconds.
The administrator dashboard on apps01 now exposes the same normalized node,
workload, GPU and storage sections.

The agent on `ai3080` has user lingering enabled and is reboot-persistent. The
agent on `ai3090` is live and enabled, but user lingering remains disabled
because the connected account does not currently have non-interactive sudo.
Enable it once with `sudo loginctl enable-linger jameshazell` on ai3090 to make
its user service start before the first login after reboot.
