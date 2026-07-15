# Pilot OS Blueprint

Version 0.3

Last updated: 2026-07-15

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
```

The Home Assistant add-on is the preferred initial Music Assistant deployment.
It provides simple lifecycle management and close HA integration. A standalone
container remains an option if independent uptime or resource isolation later
becomes important.

### Office room endpoint

```text
Host: homeai / 10.0.1.228
Platform: Proxmox Q35 virtual machine
OS: Debian 13
CPU/RAM: 4 vCPU / 3.8 GiB
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

Bluetooth support is installed but disabled because no dedicated USB Bluetooth
adapter is currently passed through.

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
- Native Debian or Debian VM where USB audio is reliable
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
- Read-only REST endpoints for rooms, players, liveness, and readiness
- Deterministic registry revision for configuration change detection

Planned responsibilities:

- Authentication and authorization
- Room and device registry
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
- Reproducible deployment, validation, and rollback

Planned responsibilities:

- Logical audio buses and source arbitration
- Ducking and announcements
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

The status model covers audio devices, PipeWire, Bluetooth policy, the Home
Assistant voice connection, AirPlay listener/playback, and Music Assistant
Sendspin connectivity.

Target Pilot Core APIs:

- `/rooms`
- `/players`
- `/devices`
- `/meetings`
- `/memory`
- `/assistant`
- WebSockets for events and streaming transcripts

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

- [x] Debian 13 VM
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
- [ ] Source arbitration and assistant ducking
- [ ] Bluetooth A2DP sink after adapter passthrough

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
- [ ] Authenticated room-agent event transport
- [ ] Dynamic device discovery and registry persistence

## 14. Immediate next steps

1. Select `Pilot Office Music` in Music Assistant and prove audible playback.
2. Validate TIDAL playback and a local lossless track.
3. Implement authenticated room-agent events and deterministic ducking policy.
4. Add Music Assistant control/API integration to Pilot Core.
5. Add the dedicated Bluetooth adapter before enabling A2DP input.
6. Train and deploy the **Hey Pilot** wake model.

## 15. Decision log

- Use native Debian services for hardware-facing audio, even when Debian itself
  runs as a Proxmox VM.
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
