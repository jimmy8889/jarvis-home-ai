# Pilot OS Blueprint

Version 1.3

Last updated: 2026-07-17

Status: Canonical architecture reference

## 1. Naming and executive vision

**Jarvis Home AI** is the project and repository. **Pilot OS** is the local-first
software platform delivered by that project.

Pilot OS unifies voice, automation, media, meetings, and personal AI into one
extensible system for homes and offices.

Core goals:

- Local by default
- Modular and hardware-agnostic
- Multi-room and context-aware
- High-quality audio
- Privacy-first
- Observable and recoverable
- Automation and API access for every capability

## 2. Product pillars

### Voice assistant

Local wake word, natural conversation, Home Assistant control, room context,
tool execution, and contextual memory.

### Multi-room audio

Music Assistant, TIDAL, local libraries, Bluetooth input, AirPlay, native
Sendspin playback, announcements, and room handoff.

### Meeting intelligence

Recording, transcription, speaker diarisation, structured summaries, actions,
and searchable meeting memory.

### Productivity

macOS dictation, AI rewriting, clipboard tools, meeting recall, and desktop
automation.

### Media

NVIDIA Shield interface, Jellyfin, Denon orchestration, Dolby Vision playback,
and room dashboards.

## 3. Target architecture

```text
                         Pilot Core
             room registry · policy · memory · APIs
                              │
        ┌──────────┬──────────┼──────────┬───────────┐
        │          │          │          │           │
   Room agents   macOS       iOS      Shield TV     Web UI
        │
        ├── Home Assistant Assist
        ├── Music Assistant
        ├── local AI services
        └── room audio and controls
```

Supporting services:

- Home Assistant
- Music Assistant
- Jellyfin
- PostgreSQL
- Redis where operationally justified
- Ollama or vLLM
- Whisper-family speech recognition
- Local text-to-speech

## 4. Current deployed topology

### Central services

```text
Home Assistant: 10.0.2.72
Music Assistant: Home Assistant add-on on 10.0.2.72
Music Assistant UI/API: TCP 8095
Music streams: TCP 8097
Sendspin server: TCP 8927
Pilot Core: 10.0.1.64:8770
Pilot Core host: debian-docker / Debian 12
Pilot Core image: jarvis-home-ai/pilot-core:wsruntime-20260717
```

The Home Assistant add-on is the preferred initial Music Assistant deployment.
It provides simple lifecycle management and close HA integration. A standalone
container remains an option if independent uptime or resource isolation later
becomes important.

Pilot Core 0.7 is deployed as a hardened, non-root Docker service with a
read-only root filesystem, all Linux capabilities dropped, file-backed secrets,
and persistent state in the `infra_pilot-core-data` volume. The service passed
LAN health/readiness, authenticated API, invalid-token, disabled legacy
bootstrap, container-restart persistence, backup-integrity, and log checks.
Dedicated Home Assistant and Music Assistant credentials are installed through
the root-owned file-backed secret store, and both read-only diagnostics are
healthy. TTS remains deliberately unconfigured until the local speech provider
is selected.

### Office room endpoint

```text
Host: officen150 / 10.0.1.53
Platform: native Intel N150 appliance
OS: Debian 13
Input: Stadium USB microphone
Output: FiiO K3 USB DAC
```

Active room services:

- PipeWire and WirePlumber under the lingering `pilot` account
- Pilot room-agent on loopback TCP 8765
- Open Home Foundation Linux Voice Assistant v1.1.12
- Home Assistant ESPHome API on TCP 6053
- Shairport Sync AirPlay receiver on TCP 5000
- Sendspin 7.5.0 client connected to Music Assistant on TCP 8927
- Boot-time restoration of stable Stadium/K3 PipeWire defaults
- Authenticated health and source-state reporting to Pilot Core
- Authenticated outbound command WebSocket with reconnect-safe results

Bluetooth support is installed but disabled until Bluetooth source arbitration
is implemented and accepted. The native host exposes its Intel Bluetooth
controller, so a dedicated adapter is no longer a prerequisite for discovery.

The permanent native deployment replaced the original Proxmox VM after music
playback on the VM exhibited skipping. Native Debian removes USB scheduling and
audio virtualization from the room playback path. The current release passes
all 19 silent endpoint checks, including Pilot Core command connectivity, while
the K3 audio activation gate remains explicitly unarmed until an in-person
acceptance test.

## 5. Hardware plan

### Core cluster

- Proxmox
- Home Assistant
- Music Assistant
- Jellyfin
- Pilot Core
- RTX 3080-class general AI inference
- Secondary GPU for speech services where useful

### Room endpoint standard

- Intel N150-class computer
- Native Debian for latency-sensitive room audio; virtualization is reserved
  for central services
- Far-field USB microphone array
- USB DAC, digital speakers, or HDMI/optical room output
- Dedicated USB Bluetooth adapter when Bluetooth input is required
- Ethernet preferred

### Media room

- Denon AVC-X8500H
- NVIDIA Shield for licensed Dolby Vision playback
- Optional HDMI-connected N150 for Pilot audio and dashboard output

## 6. Software components

### Pilot Core

Implemented foundation:

- Validated TOML room and player registry
- Deterministic response-player and default-music-player assignments
- SQLite persistence for rooms, players, devices, source state, and events
- Separate administrator, bootstrap, and per-device bearer credentials
- Authenticated REST APIs and realtime WebSocket event subscribers
- Music Assistant control/search adapter and Home Assistant conversation adapter
- Container deployment with persistent storage and health checks
- Deterministic registry revision for configuration change detection
- Room-bound audio asset storage with expiry, authenticated device downloads,
  and SHA-256/size manifests
- Deterministic assistant and announcement dispatch to a room's response
  endpoint
- Bounded Home Assistant/Piper and OpenAI-compatible local TTS adapters
- Optional spoken Home Assistant conversation responses routed to their
  originating room
- File-backed container secrets and hardened read-only central deployment
- Short-lived, device-bound, single-use bootstrap grants
- Read-only Home Assistant and Music Assistant integration diagnostics
- Integrity-manifested central backup and guarded restore tooling

Planned responsibilities:

- Command routing and tool execution
- Conversation and session state
- Media and display orchestration
- Memory and meeting search
- REST and realtime APIs

### Room agent

Current responsibilities:

- Audio device identity and readiness
- PipeWire default restoration
- Voice, AirPlay, and Music Assistant service health
- Home Assistant and Music Assistant connection status
- Playback state visibility through MPRIS where available
- Outbound authenticated health and source-state reporting to Pilot Core
- Authenticated outbound command socket with durable central queue, local
  idempotency journal, heartbeats, and reconnect backoff
- Loopback-only transport, volume, listening, assistant, announcement, and
  cancel controls
- Self-expiring transient focus state and deterministic priority decisions
- Authenticated, integrity-verified assistant and announcement downloads
- Single-slot PipeWire speech playback with completion cleanup and cancellation
- Reproducible deployment, validation, and rollback
- Fail-closed supervised playback activation tied to the accepted audio
  configuration

Planned responsibilities:

- Audible acceptance and activation of local PipeWire gain enforcement
- Logical echo-reference and dedicated announcement playback buses
- Bluetooth A2DP sink
- Hardware controls, LEDs, and privacy state
- Metrics and central event reporting

### Client applications

- macOS: dictation, push-to-talk, AI compose, and menu bar controls
- iOS: meeting recording, remote assistant, and notifications
- Shield TV: dashboard, media browser, assistant overlay, and home controls

## 7. Voice and AI pipeline

```text
Local wake word
      ↓
Home Assistant Assist pipeline
      ↓
Local STT → deterministic intents/tools → local LLM when needed
      ↓
Local TTS → originating room output
```

Current office wake model: `okay_nabu`.

Target custom phrase: **Hey Pilot**.

Candidate future components:

- Voice activity: Silero VAD or equivalent
- Speech recognition: faster-whisper, Distil-Whisper, or streaming ASR
- Reasoning: fast tool-capable local model, with larger-model fallback
- Speech: Kokoro-class voice with Piper fallback

## 8. Audio architecture

### Current physical graph

```text
Assistant response ─┐
AirPlay ────────────┼── PipeWire default sink ── FiiO K3
Music Assistant ────┘
```

Music Assistant uses its native Sendspin protocol. AirPlay uses Shairport Sync
through the PipeWire Pulse compatibility layer. Both services run as `pilot` so
the room has one audio ownership boundary.

### Target logical buses

- `music_bus`
- `bluetooth_bus`
- `airplay_bus`
- `assistant_bus`
- `announcement_bus`
- `echo_reference`
- `microphone`
- `speakers`

Target priority:

1. Critical alerts
2. Assistant responses
3. Bluetooth
4. AirPlay
5. Music

## 9. APIs and observability

Current room-agent endpoints:

- `GET /healthz`
- `GET /readyz`
- `GET /v1/status`
- `POST /v1/control`

The status model covers audio devices, PipeWire, transient control state,
Bluetooth policy, the Home Assistant voice connection, AirPlay
listener/playback, and Music Assistant Sendspin connectivity.

Target Pilot Core APIs:

- `/rooms`
- `/players`
- `/devices`
- `/meetings`
- `/memory`
- `/assistant`
- WebSockets for events and streaming transcripts

Pilot Core 0.6 now implements authenticated `/v1/rooms`, `/v1/players`,
`/v1/devices`, `/v1/media`, `/v1/assistant`, event ingestion/history, and a
realtime event WebSocket. It also persists device commands and delivers them
over authenticated outbound room-agent WebSockets. Meeting and memory APIs
remain future phases.

Pilot Core 0.5 added `/v1/rooms/{room_id}/audio-assets`,
`/v1/rooms/{room_id}/audio`, and the device-authenticated audio download path.
The room agent verifies each manifest and owns playback state through completion
or cancellation. Pilot Core 0.6 adds `/v1/tts` and
`/v1/rooms/{room_id}/speak`, with Home Assistant/Piper and OpenAI-compatible
local synthesis providers. `/v1/assistant` can optionally speak a Home
Assistant conversation response through the request's originating room.

Room-level state, media, and endpoint-control APIs resolve configured targets
deterministically. Connected capable devices are preferred with stable
tie-breaking, while offline commands remain queued for the selected room rather
than leaking to a different room.

## 10. Data and security

Planned PostgreSQL data includes users, rooms, devices, meetings,
conversations, and tasks. Semantic indexes provide meeting and memory search.

Security principles:

- Local authentication
- TLS between components where supported
- Role-based permissions
- Device identities and certificates
- Least-privilege system services
- No credentials committed to source control
- Offline operation for essential functions
- Private GitHub repository for infrastructure source by default

## 11. Deployment and recovery

Central services use Proxmox, Home Assistant add-ons, and containers as
appropriate. Room endpoints use Debian, systemd, PipeWire, and Ansible.

Every room-agent deployment creates a versioned release and records a previous
release pointer. `pilot-rollback` atomically returns to the prior room-agent
release. Configuration archives are retained separately.

GPU, HDMI, VFIO, IOMMU, and Proxmox host configuration remain outside the first
office endpoint milestone.

## 12. Repository layout

```text
pilot/
  apps/room-agent/
  config/
  deploy/ansible/
  deploy/scripts/
  docs/
  systemd/

Future:
  core/
  macos/
  ios/
  shield-tv/
  ai/
  api/
  infra/
  hardware/
```

This document must be updated whenever a material architecture decision,
deployed integration, hardware boundary, or milestone status changes.

## 13. Milestones

### Phase 1 — Office voice endpoint: operational

- [x] Native Debian 13 appliance
- [x] Stadium USB microphone
- [x] FiiO K3 output
- [x] Stable PipeWire defaults
- [x] Local wake word
- [x] Home Assistant connection
- [x] Reboot persistence and rollback

### Phase 2 — Network audio: in progress

- [x] AirPlay receiver
- [x] Native Music Assistant Sendspin connection
- [x] Sendspin reboot persistence and automatic reconnection
- [ ] Audible Music Assistant playback acceptance test
- [ ] TIDAL provider and local-library acceptance tests
- [x] Source-priority policy and local control/event foundation
- [ ] Audible assistant ducking and gain-restoration acceptance test
- [ ] Bluetooth A2DP sink

### Phase 3 — Media room

- [ ] Denon HEOS discovery and control
- [ ] Media-room player selection
- [ ] Shield application foundation
- [ ] N150 HDMI design and passthrough decision
- [ ] Multi-room sync and announcements

### Phase 4 — Productivity and meetings

- [ ] Meeting recorder
- [ ] Transcription and diarisation pipeline
- [ ] macOS dictation client
- [ ] iOS meeting client

### Phase 5 — Memory and advanced workflows

- [ ] Semantic meeting memory
- [ ] Conversation memory
- [ ] Energy-management tools
- [ ] User and action permissions

### Platform foundation

- [x] Validated Pilot Core room/player registry
- [x] Authenticated room-agent event transport
- [x] Device registration and registry persistence
- [x] Music Assistant and Home Assistant API adapters
- [x] Durable authenticated Core-to-room command delivery
- [x] Reconnect-safe local command result journal
- [x] Deterministic room/player/device target resolution
- [x] Joined room state and room-level media/control APIs
- [x] Secure room-bound audio delivery
- [x] Local TTS provider abstraction and room speech API
- [x] Hardened central deployment and file-backed secret handling
- [x] One-time device enrollment grants
- [x] Silent integration diagnostics and central backup/restore tooling
- [x] Supervised room playback activation gate
- [x] Deploy Pilot Core on the central Docker host at `10.0.1.64:8770`
- [x] Enable and verify the registered office room-agent reporter
- [x] Verify authenticated command delivery and restart reconnection

## 14. Immediate next steps

1. Select `Pilot Office Music` in Music Assistant and prove audible playback.
2. Validate TIDAL playback and a local lossless track.
3. Complete the supervised K3 acceptance receipt and explicitly arm room
   playback.
4. Validate assistant ducking and gain restoration at a safe listening volume.
5. Validate the native Intel Bluetooth controller; add a dedicated adapter only
   if its receiver behavior is inadequate.
6. Train and deploy the **Hey Pilot** wake model.

## 15. Decision log

- Use native Debian for latency-sensitive room endpoints and native services for
  hardware-facing audio.
- Pass individual USB devices, not the entire USB controller.
- Keep GPU and HDMI passthrough out of the office baseline.
- Run room audio services as the single lingering `pilot` user.
- Use Music Assistant as the authoritative music library, queue, and room
  orchestration layer.
- Start Music Assistant as a Home Assistant add-on; split it out only for a
  demonstrated uptime or isolation need.
- Prefer native Sendspin over Squeezelite now that an official headless client
  is released; retain Squeezelite as a fallback.
- Keep the Shield as the licensed Dolby Vision playback engine.

## 16. Version history

- **0.1** — Initial product vision and target architecture.
- **0.2** — Reconciled blueprint with the deployed office voice endpoint,
  AirPlay, Home Assistant integration, native Music Assistant Sendspin client,
  recovery model, and current milestone status.
- **0.3** — Verified the complete room stack and Sendspin reconnection across a
  controlled reboot, and added the first validated Pilot Core room/player
  registry and read-only API.
- **0.4** — Added authenticated device registration and outbound room events,
  persistent control-plane state, realtime event streaming, deterministic
  audio-focus decisions, HA/MA adapters, and a containerized Pilot Core
  deployment.
- **0.5** — Added the intelligence framework covering world state, planning,
  events, knowledge, identity, and consent-based preference learning.
- **0.6** — Added the room-agent control surface, expiring interaction state,
  and complete source-state reporting while retaining the audible safety gate.
- **0.7** — Added durable authenticated Core-to-room commands, reconnect-safe
  idempotency, command status APIs, and deployment validation.
- **0.8** — Added deterministic room-aware target resolution, joined room
  state, and room-level media and endpoint-control APIs.
- **0.9** — Added room-bound audio assets, authenticated same-room downloads,
  integrity manifests, and managed room-agent speech playback.
- **1.0** — Added bounded Home Assistant/Piper and OpenAI-compatible local TTS,
  deterministic room speech routing, and optional spoken conversation results.
- **1.1** — Added hardened file-backed central deployment, one-time enrollment,
  silent integration diagnostics, integrity-manifested backup/restore, and a
  fail-closed supervised room playback activation gate.
- **1.2** — Deployed Pilot Core 0.7 on the central Docker host at
  `10.0.1.64:8770`, verified authenticated and restart-safe operation, and kept
  HA/MA/TTS integrations disabled pending dedicated credentials.
- **1.3** — Provisioned dedicated Home Assistant and Music Assistant
  credentials, enrolled the Office N150, deployed Room Agent 0.5 reporting and
  commands, fixed the production WebSocket runtime, verified non-audible command
  delivery and restart reconnection, and retained the fail-closed K3 activation
  gate.
