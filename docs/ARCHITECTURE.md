# Deployed platform architecture

The first Pilot endpoint runs native Debian 13 to keep latency-sensitive USB
audio outside a virtualization path:

```text
Office N150
├── K3 combined USB Audio/HID microphone
├── K3 combined USB Audio/HID stereo output
├── PipeWire + WirePlumber user session
├── Linux Voice Assistant → Home Assistant Assist
├── Shairport Sync → PipeWire → K3
├── Sendspin → Music Assistant → PipeWire → K3
├── BlueZ A2DP sink → PilotBluetooth loopback → K3
├── Pilot Display 0.7.2 media-console shell
└── Pilot room-agent
    ├── loopback health and control API
    ├── outbound health/source reporting
    ├── outbound authenticated command WebSocket
    ├── command result journal
    └── safely gated audio-focus enforcement
```

The `pilot` account has systemd lingering enabled. PipeWire, Pulse
compatibility, and WirePlumber therefore start at boot without an interactive
login. Room audio services share that user and one audio graph.

```text
Home Assistant response ─┐
AirPlay stream ──────────┼─→ PipeWire default sink ─→ K3 USB Audio/HID
Sendspin music ──────────┘
Bluetooth A2DP ──────────┘
```

The room-agent binds only to loopback. Pilot Core does not connect inbound to
it; the endpoint opens authenticated outbound reporting and command channels.
This keeps room firewall policy simple and makes offline command delivery
durable.

## Central orchestration

```text
Client / future LLM
        │ typed request with originating room
        ▼
Pilot Core
├── room/player/device registry
├── deterministic target resolver
├── current room state and focus
├── authenticated command queue and events
├── Music Assistant adapter
└── Home Assistant conversation adapter
        │
        ├── room media → configured MA player
        └── room control → capable room device
```

Room IDs are the stable public routing boundary. Player external IDs, device
IDs, connection preference, capability checks, and fallback choices stay inside
Pilot Core. An LLM may produce a typed intent but does not select infrastructure
identifiers.

## Current safety boundaries

- No Intel GPU, HDMI, VFIO, or IOMMU work in the office baseline.
- Bluetooth A2DP input is enabled through the internal Intel controller. The
  endpoint is not discoverable or pairable outside an operator-opened bounded
  window, and newly paired devices require explicit trust.
- Live PipeWire gain enforcement is enabled for the accepted Office Sendspin
  and AirPlay paths. Bluetooth uses the same priority model, but its physical
  pairing, playback, duck and restoration acceptance remains pending.
- Core-delivered room audio remains guarded by a configuration-specific
  supervised activation receipt. Correcting the K3 node identity invalidated
  the previous fingerprint, so re-arming requires a new audible receipt.
- Endpoint controls are loopback-only or delivered over authenticated outbound
  command transport.
- Music actions pass through Music Assistant; home actions pass through Home
  Assistant.
- Every room-agent release is versioned and reversible, while the command
  journal persists to prevent replay after rollback.

The canonical product-level architecture is
[PILOT_OS_BLUEPRINT.md](PILOT_OS_BLUEPRINT.md). Detailed command and routing
contracts are in [COMMAND_TRANSPORT.md](COMMAND_TRANSPORT.md) and
[ROOM_ORCHESTRATION.md](ROOM_ORCHESTRATION.md).
