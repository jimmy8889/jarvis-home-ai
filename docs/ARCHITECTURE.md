# Room endpoint architecture

The first Pilot endpoint is intentionally narrow:

```text
Proxmox host
  └── Debian 13 VM
      ├── USB microphone (individual USB passthrough)
      ├── USB DAC/speakers (individual USB passthrough)
      ├── optional USB Bluetooth adapter (individual passthrough)
      ├── PipeWire + WirePlumber user session
      ├── Linux Voice Assistant → Home Assistant Assist
      ├── Shairport Sync → PipeWire → room output
      ├── Sendspin → Music Assistant → PipeWire → room output
      └── Pilot room-agent and validation services
```

The `pilot` account has systemd lingering enabled. Its PipeWire, Pulse
compatibility, and WirePlumber services therefore start at boot without an
interactive login. The room-agent runs as the same user and receives that
user's `XDG_RUNTIME_DIR`, allowing it to inspect the audio graph.

The room-agent binds only to loopback. It reports liveness separately
from readiness: `/healthz` confirms the process is alive, while `/readyz` and
`/v1/status` inspect PipeWire, ALSA capture/playback, optional Bluetooth, the
voice satellite's Home Assistant connection, and the AirPlay listener.

All application audio enters the same PipeWire session owned by `pilot`:

```text
Home Assistant response ─┐
AirPlay stream ──────────┼─→ PipeWire default sink ─→ FiiO K3
Sendspin music ──────────┘
```

This preserves a single output-selection boundary and allows future focus,
ducking, and announcement policy to operate on named PipeWire streams.

## Explicitly out of scope

- Intel GPU or HDMI passthrough
- VFIO/IOMMU changes
- passing an entire USB controller to the guest
- modifying the Proxmox host
- Bluetooth A2DP input without a dedicated passed-through adapter
- production audio focus/ducking between simultaneous sources

AirPlay, Home Assistant voice, and native Music Assistant Sendspin playback are
implemented. Pilot Core now provides the first validated room/player registry;
its network authentication and event transport are the next control-plane
boundary.
