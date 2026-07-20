# Pilot OS Blueprint

Version 2.3

Last updated: 2026-07-20

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
Pilot Core image: jarvis-home-ai/pilot-core:core-0.18.0-20260720.1
```

The Home Assistant add-on is the preferred initial Music Assistant deployment.
It provides simple lifecycle management and close HA integration. A standalone
container remains an option if independent uptime or resource isolation later
becomes important.

Pilot Core is deployed as a hardened, non-root Docker service with a
read-only root filesystem, all Linux capabilities dropped, file-backed secrets,
and persistent state in the `infra_pilot-core-data` volume. The service passed
LAN health/readiness, authenticated API, invalid-token, disabled legacy
bootstrap, container-restart persistence, backup-integrity, and log checks.
Dedicated Home Assistant and Music Assistant credentials are installed through
the root-owned file-backed secret store, and both read-only diagnostics are
healthy. Pilot Core 0.13 enables the local Home Assistant Assist pipeline,
Piper TTS, the Geebung weather entity, and authenticated embedded-node voice,
weather, rolling temperature-history, and firmware APIs. Piper has been
validated to return 16 kHz, mono,
16-bit WAV when all preferred audio properties are requested. A same-origin
operations dashboard is available at `/dashboard`;
its room, device, integration, safety, command, event, and deployment data
remain protected by the existing administrator bearer token.

Pilot Core 0.15 adds a safe speech-engine acceptance route. It synthesizes a
fixed phrase through `tts.piper`, validates the streaming WAV, feeds its PCM to
the pinned `stt.faster_whisper` pipeline, and requires at least 80% word
coverage. The deployed acceptance returned all five expected words with 100%
coverage. Home Assistant reports Piper 2.3.1 and Whisper 3.5.0 running.

Pilot Core 0.17 retains its bounded contextual reasoning path against Ollama
0.32.1 at `10.0.1.20:11434/v1`, using `qwen3.5:9b`. Home Assistant's built-in
agent remains the deterministic first pass. Unmatched requests receive bounded
room/media context and may invoke only Pilot's typed tools. Reasoning effort is
disabled for the voice path after live tests showed an approximately one-second
warm factual response while preserving native tool selection.
Clear temperature, weather, forecast, and now-playing questions additionally
force their read-only tool so current home state cannot be improvised.

Home Assistant now has a separate `Pilot Contextual` Assist pipeline with
Faster Whisper, Piper Amy, preferred local intents, and its RTX Ollama
conversation agent. The Office satellite is assigned to it; `Full local
assistant` remains available as a deterministic-only rollback.

Pilot Core now owns short-lived, room- and device-scoped conversation sessions.
Voice audio uses Home Assistant for STT only, then Pilot tries the built-in
Home Assistant agent as a fast deterministic path. Unmatched contextual
requests fall back to the accepted local OpenAI-compatible model with bounded
room/media context and typed Pilot tools; Home Assistant and Music Assistant
remain the action boundaries.

The Media Room is registered with staged control. Music Assistant identifies the
Denon AVC-X8500H as HEOS player `1174905188` at `10.0.1.150`; Home Assistant
exposes the same receiver's HEOS state as `media_player.media_room`. Pilot Core
uses the receiver's allowlisted port-8080 command endpoint for power and named
input selection because Home Assistant's separate Denon AVR discovery failed
against the receiver's redirected legacy API. The NVIDIA Shield is registered
through Music Assistant player
`upb0713734fca0742d2bf2125b59cbf3b1` at `10.0.1.101`. Pilot Core normalizes
their live provider state. The accepted Denon HEOS music route permits bounded
music, volume, power, and source commands. Raw receiver commands and unlisted
sources are rejected. The separate assistant-response route and Shield remain
read-only.

Office audio focus is active. Pilot Core subscribes to the configured Home
Assistant Assist-satellite state and forwards expiring listening/responding
focus commands to the authenticated room endpoint. The deployed enforcer
resolved the real Sendspin PipeWire node and measured gain `1.00 -> 0.20 ->
1.00` without changing the K3 sink volume.

The 0.10 deployment adds derived observability and Prometheus-format metrics,
the read-only Media Room acceptance harness, and the first durable
meeting-ingestion/review schema. Its post-deployment diagnostics and Media Room
discovery checks passed without an audible or provider mutation, and every
existing room/player control gate remains in place.

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

### Bedroom display node

```text
Hardware: Waveshare ESP32-C6-Touch-AMOLED-2.16
Deployed firmware: Pilot Display Node 0.2.8
Published firmware: Pilot Display Node 0.2.8
Display: 480 x 480 AMOLED
Time: Australia/Brisbane via NTP with PCF85063 RTC fallback
Network: Hazell IoT VLAN over 2.4 GHz Wi-Fi
```

The deployed display node presents a burn-in-conscious clock, reconnects to
Wi-Fi, synchronizes time using Cloudflare NTP, refreshes the hardware RTC, and
continues as an offline clock if networking is unavailable. It adds QMI8658
motion wake, 20-second dimming, a dark display after 30 seconds,
touch-scrollable clock, detailed forecast, Outside temperature, and Bedroom
temperature pages, touch and GPIO push-to-talk, animated
listening/processing/responding states, ES7210 microphone streaming to Pilot
Core, ES8311 Piper response playback, and authenticated device snapshots.
Native USB diagnostics, pinned dependencies, reproducible scripts, and a
preserved full factory flash provide the operations and rollback model.

Physical acceptance used USB to install 0.2.3 and then Pilot Core's private
firmware service to upgrade it to immutable release 0.2.4. The test verified
Wi-Fi, NTP/RTC, weather, the stationary IMU dim/off sequence, authenticated
download and SHA-256 validation, alternate-slot boot, and the healthy-image
mark that cancels automatic rollback. Pilot Core and the embedded client now
both enforce semantic-version upgrades, so an older published release cannot
cause a downgrade loop.

Hands-on Talk to Pilot testing then exposed and repaired two embedded voice
faults. Version 0.2.5 moves the HTTP response buffer off the voice-task stack,
increases the task allocation from 7 KiB to 12 KiB, and logs measured stack
headroom and bounded server failures. Two consecutive requests completed with
more than 8 KiB of stack remaining and no reset. The embedded TTS locale now
matches the installed
`en_US-amy-low` Piper voice.

Version 0.2.6 adds rain amount, wind, and tomorrow's outlook to the forecast.
Pilot Core reads `sensor.gw1100c_outdoor_temperature` and
`sensor.temp3_temperature`, calculates rolling 24-hour current/minimum/maximum
values, and downsamples each recorder history to 24 bounded graph points.
The USB rollout verified image integrity, boot, Wi-Fi, NTP, authenticated data
refresh, dimming, and panel-off behavior without a reset. The identical
immutable image is now published through Pilot Core; visual page navigation and
onboard response playback remain hands-on acceptance items.

Natural-speech testing then revealed that 0.2.6 consistently reached Assist but
produced its generic misunderstanding response. A known-good 16 kHz sample sent
through the same authenticated Pilot Core endpoint transcribed correctly,
isolating the fault to embedded capture. ESP-IDF already packs the selected
ES7210 TDM slot into contiguous mono PCM; firmware had incorrectly selected
every fourth sample a second time, producing an effective 4 kHz stream labelled
as 16 kHz. Version 0.2.7 removes that second decimation. Its immutable image is
published and the node installed it over OTA, rebooted, refreshed its
authenticated snapshot, and reported `current_version=0.2.7`.

Version 0.2.8 retains Pilot Core's opaque conversation ID in RAM for up to 15
minutes and sends it with follow-up voice requests. It never writes dialogue
state to flash. The release was published through Pilot Core, installed over
OTA, rebooted successfully, and reported `current_version=0.2.8`.

### Large-format Raspberry Pi display node

```text
Host: pilot-display-pi / 10.0.2.26
Hardware: Raspberry Pi 4 Model B, 2 GB / 16 GB microSD
Display: 10-inch 1024 x 600 HDMI with ILITEK USB touch
OS: 64-bit Debian 13 Trixie
Runtime: Cage Wayland compositor + Chromium kiosk
Surface: Pilot Linux Display 0.3.1
```

This node is deployed as a minimal appliance rather than a full desktop. A
loopback-only Python service renders Brisbane time, Pilot Core readiness,
registry counts, bounded local health, whole-network now-playing state, and the
SAJ energy system. A device-only credential stays in the local service; the
browser receives no credential and the Pi receives no Home Assistant, Music
Assistant, or administrator token. Touch-native Home, Energy, Music, and System
pages support large tap targets and horizontal swipes. The Energy page uses a
live flow diagram whose path direction represents grid import/export and
battery charge/discharge, while animation speed and intensity scale with
watts. Chromium caches, system journals, release count, and APT archives are
bounded for the 16 GB card; automatic security updates do not reboot the node.
The display's incomplete EDID is overridden through a reversible KMS
`video=HDMI-A-1:1024x600M@60D` argument.

Physical acceptance verified native mode, ILITEK input on `seat0`, Pilot Core
connectivity, zero kiosk restarts, 7.8 GB free storage, no throttling, and
two-way application rollback. Pilot Core 0.14 adds a bounded, authenticated
display surface. The Pi is provisionally room-bound to Office with only the
non-mutating `display` capability.

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
- HDMI-connected N150 Media Console for Pilot audio, local video, dashboards,
  assistant overlays, and iOS-controlled room sessions
- Shield retained as the licensed Dolby Vision, DRM, and commercial-streaming
  engine

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
- Authenticated embedded-node snapshot, weather, voice-stream, response-audio,
  firmware-manifest, and firmware-image endpoints
- Bounded PCM forwarding to Home Assistant's local Assist WebSocket pipeline
- Immutable checksum-verified firmware release storage and private delivery
- File-backed container secrets and hardened read-only central deployment
- Short-lived, device-bound, single-use bootstrap grants
- Read-only Home Assistant and Music Assistant integration diagnostics
- Integrity-manifested central backup and guarded restore tooling
- Authenticated operations snapshot and responsive central dashboard
- Provider-neutral Music Assistant/Home Assistant player state
- Per-player read-only discovery and fail-closed control policy

Planned responsibilities:

- Command routing and tool execution
- Conversation and session state
- Media and display orchestration
- Memory and meeting search
- REST and realtime APIs

New 0.10 foundations:

- authenticated health, freshness, alert, and metrics surfaces
- bounded local meeting recording ingestion
- timestamped transcripts and evidence-linked decisions/actions

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
- iOS: meeting recording, remote assistant, notifications, and secure
  room/media-console control
- Shield TV: dashboard, media browser, assistant overlay, and home controls

Pilot TV 0.1 now exists as a buildable Kotlin/Compose for TV application. It
reads the authenticated operations snapshot, renders rooms, integrations,
safety, endpoints, players, and now-playing state, and stores its administrator
credential only in process memory. Media and Home Assistant mutations remain
absent until in-person acceptance.

### N150 Media Console

The display-capable N150 role combines Room Agent and the audio stack with a
ten-foot Pilot shell and supervised local-video engine. Native Debian owns
Intel graphics, HDMI, PipeWire, Sendspin, a lightweight Wayland session, and
mpv. Pilot Core remains authoritative for rooms, queues, playback sessions,
engine selection, permissions, and audit history.

Music remains under Music Assistant. Local/Jellyfin video suitable for the
tested Linux path uses mpv. The Shield remains the engine for Dolby Vision,
DRM, and commercial services. iOS controls both through device/user-bound
Pilot Core APIs instead of connecting directly to the N150, Denon, Shield, or
mpv socket. The full plan is in `docs/N150_MEDIA_CONSOLE.md`.

### Embedded display nodes

Pilot Display Node 0.2 is the first complete ESP32 room client. It owns local
time/offline behavior, motion and touch UX, short push-to-talk capture, response
playback, weather and temperature-graph rendering, and rollback-safe updates.
Pilot Core owns Home Assistant credentials, Assist/STT orchestration, TTS
synthesis, weather normalization, bounded history projection, and release
authorization. The node stores only Wi-Fi credentials and its revocable
per-device token.

The bedroom node deliberately keeps the ESP32 awake with the panel fully dark
so the QMI8658 can wake the screen immediately. Deep sleep is deferred until an
interrupt-driven IMU path is accepted on the physical board.

Large-format Linux displays use the same thin-client principle at a different
scale. The Raspberry Pi owns only local presentation, touch, offline status,
and kiosk recovery; Pilot Core remains authoritative for rooms, home state,
assistant context, and future control authorization.

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

Target Pilot Core APIs not yet implemented:

- `/meetings`
- `/memory`
- WebSockets for streaming meeting transcripts

Pilot Core 0.9 implements authenticated `/v1/rooms`, `/v1/players`,
`/v1/devices`, `/v1/media`, `/v1/assistant`, `/v1/operations`, event
ingestion/history, provider-neutral media state, a realtime event WebSocket,
and the operations dashboard. It also persists device commands and delivers
them over authenticated outbound room-agent WebSockets. Meeting and memory APIs
remain future phases.

Pilot Core 0.5 added `/v1/rooms/{room_id}/audio-assets`,
`/v1/rooms/{room_id}/audio`, and the device-authenticated audio download path.
The room agent verifies each manifest and owns playback state through completion
or cancellation. Pilot Core 0.6 adds `/v1/tts` and
`/v1/rooms/{room_id}/speak`, with Home Assistant/Piper and OpenAI-compatible
local synthesis providers. `/v1/assistant` can optionally speak a Home
Assistant conversation response through the request's originating room.

Pilot Core 0.11 adds device-authenticated
`/v1/devices/{device_id}/snapshot`,
`/v1/devices/{device_id}/voice`,
`/v1/devices/{device_id}/firmware`, and the corresponding private firmware
image route. Raw little-endian 16-bit mono PCM is size-bounded before it is
forwarded to the selected local Assist pipeline. Weather responses expose only
the small display-safe schema, and every release image is checked against its
immutable manifest before serving.

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
  firmware/pilot-display-node/
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
- [x] Local Faster Whisper STT and Piper TTS engine round-trip
- [x] Home Assistant-to-K3 TTS delivery at a bounded test volume
- [x] Office contextual Ollama pipeline with deterministic-intent preference
- [x] Reboot persistence and rollback

### Phase 2 — Network audio: in progress

- [x] AirPlay receiver
- [x] Native Music Assistant Sendspin connection
- [x] Sendspin reboot persistence and automatic reconnection
- [x] Audible Music Assistant playback acceptance test
- [x] TIDAL provider and playback acceptance test
- [ ] Local lossless-library acceptance test
- [x] Source-priority policy and local control/event foundation
- [ ] Audible assistant ducking and gain-restoration acceptance test
- [ ] Bluetooth A2DP sink

### Embedded nodes

- [x] ESP32-C6 display hardware identified and factory image preserved
- [x] Pilot clock UI, Wi-Fi, NTP, RTC fallback, and reboot persistence
- [x] Reproducible firmware build, flash, and rollback documentation
- [x] Authenticated Pilot Core weather, voice, reply-audio, and OTA transport
- [x] Touch weather navigation and push-to-talk control
- [x] Detailed forecast and rolling indoor/outdoor min/max graph pages
- [x] Motion-aware bedroom dim/off and immediate wake behavior
- [x] Authenticated, checksum-verified OTA update workflow
- [x] Physical USB boot, stationary IMU dim/off, alternate-slot OTA, and healthy-image mark
- [ ] Physical touch, motion wake, microphone, speaker, and forced-rollback acceptance

### Phase 3 — Media room

- [x] Read-only Denon HEOS discovery
- [x] Media-room player registration and deterministic selection
- [x] Provider-neutral Denon and Shield state
- [x] Fail-closed Media Room control gate
- [x] Enable the accepted Denon HEOS music route
- [ ] In-person Denon audible playback and source-switch acceptance
- [x] Shield application foundation
- [ ] Shield device pairing and physical deployment
- [x] N150 Media Console architecture and native-HDMI boundary
- [ ] Media-console agent and authenticated session commands
- [ ] Fullscreen N150 idle/music/assistant shell
- [ ] Supervised mpv local-video playback
- [ ] Jellyfin browse, resume, subtitle, and audio-track integration
- [ ] iOS room/media remote
- [x] Bounded Home Assistant Denon power and source commands
- [ ] HDMI/CEC source coordination for a future media-room N150
- [ ] N150 HDR10 and HD-audio acceptance
- [ ] N150/Shield playback-engine selection and handoff
- [ ] Multi-room sync and announcements

### Phase 4 — Productivity and meetings

- [ ] Meeting recorder
- [ ] Transcription and diarisation pipeline
- [ ] macOS dictation client
- [ ] iOS meeting client

### Phase 5 — Memory and advanced workflows

- [ ] Semantic meeting memory
- [x] Short-lived room/device conversation sessions and retained turns
- [ ] Explicit long-term conversation-memory retention
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
- [x] Authenticated silent Piper-to-Faster-Whisper acceptance test
- [x] Hardened central deployment and file-backed secret handling
- [x] One-time device enrollment grants
- [x] Silent integration diagnostics and central backup/restore tooling
- [x] Supervised room playback activation gate
- [x] Deploy Pilot Core on the central Docker host at `10.0.1.64:8770`
- [x] Enable and verify the registered office room-agent reporter
- [x] Verify authenticated command delivery and restart reconnection
- [x] Deploy the authenticated Pilot Core operations dashboard
- [x] Register Media Room, Denon HEOS, and Shield with per-player control gates
- [x] Add normalized live player state to Pilot Core and its dashboard
- [x] Add Pilot-owned conversation continuity and administrator session APIs
- [x] Add deterministic Home Assistant routing with local-model fallback
- [x] Deploy the RTX Ollama model and low-latency reasoning configuration
- [x] Add bounded typed tools for home state/control, weather, and music
- [x] Deploy the first Raspberry Pi large-format Pilot display appliance

## 14. Immediate next steps

1. Assign the 10-inch Raspberry Pi panel to its physical room and define its
   room-specific pages and controls.
2. Confirm a display follow-up request reuses the same Pilot conversation
   session through speech and local TTS.
3. Run contextual acceptance prompts for pronouns, follow-ups, room-relative
   language, live weather, and typed home/music tools.
4. Confirm wake-word-triggered ducking and restoration by ear on the Office K3.
5. Validate a local lossless Music Assistant track.
6. Complete the supervised K3 acceptance receipt and explicitly arm Core speech
   playback.
7. Validate the native Intel Bluetooth controller; add a dedicated adapter only
   if its receiver behavior is inadequate.
8. Train and deploy the **Hey Pilot** wake model.
9. Complete the audible Denon playback/source acceptance at a safe volume.
10. Converge the Office wake-word path onto Pilot Core so it uses the same
    retained sessions and typed tools as Pilot clients.

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
- Separate player discovery from mutation; new room players start with
  `control_enabled = false`.
- Treat ESP32 displays as thin room surfaces; keep audio, orchestration, and
  durable state on the N150 endpoints and Pilot Core.
- Inject display-node Wi-Fi credentials only during local builds and keep the
  complete pre-Pilot factory flash outside source control.

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
- **1.4** — Added Pilot Core 0.8's authenticated operations snapshot and
  responsive dashboard for rooms, devices, integrations, source focus, safety,
  commands, events, and release state without enabling audible controls.
- **1.5** — Added Pilot Core 0.9's read-only Media Room model, verified Denon
  HEOS and Shield identities, normalized Music Assistant/Home Assistant player
  state, and enforced a fail-closed per-player control gate.
- **1.6** — Added Pilot Core 0.10 observability, actionable alerts, Prometheus
  metrics, the read-only Media Room acceptance harness, Pilot TV 0.1, and the
  bounded meeting-ingestion and evidence-review foundation.
- **1.7** — Added and physically deployed Pilot Display Node 0.1 on the
  ESP32-C6 AMOLED hardware, including Wi-Fi/NTP, RTC fallback, a low-memory
  display profile, OTA-ready partitions, reproducible firmware tooling, and a
  full factory-flash rollback path.
- **1.8** — Added Pilot Core 0.11 embedded-node APIs and Pilot Display Node 0.2.1
  with motion-aware bedroom power behavior, weather, touch push-to-talk, local
  Assist/Piper audio, animated voice states, authenticated OTA, and automatic
  rollback. The firmware is compiled and awaits its first physical acceptance
  flash.
- **1.9** — Physically flashed the Bedroom node, corrected stationary IMU
  filtering, deployed semantic-version downgrade protection in Pilot Core and
  the embedded client, moved OTA transfer storage off the network task stack,
  and verified the complete 0.2.3-to-0.2.4 alternate-slot update and
  healthy-image confirmation path.
- **2.0** — Repaired the Bedroom node's Talk to Pilot stack exhaustion,
  converted ES7210 four-channel TDM capture to true 16 kHz mono, physically
  verified Home Assistant transcription and intent processing without a
  reset, and aligned the device locale with the installed Piper voice.
- **2.1** — Deployed Pilot Core 0.12 and Pilot Display Node 0.2.6 with bounded
  rolling histories for the outdoor weather-station and bedroom sensors,
  richer today/tomorrow forecast data, current/min/max temperature pages, and
  24-point line graphs. The release passed server tests, physical USB boot,
  authenticated refresh, dim/off, and immutable OTA publication checks.
- **2.2** — Reproduced Bedroom voice routing with known-good audio, isolated
  natural-speech failure to erroneous four-to-one decimation after ESP-IDF's
  TDM slot filter, and deployed Pilot Display Node 0.2.7 over OTA with
  contiguous 16 kHz mono capture restored.
- **2.3** — Added Pilot Core 0.13 room/device conversation persistence,
  Home Assistant provider continuity, deterministic-first routing, a bounded
  local-model tool loop, administrator session visibility, and Pilot Display
  Node 0.2.8 in-memory follow-up continuity.
- **2.4** — Added and deployed the first large-format Pilot Linux display on a
  2 GB Raspberry Pi 4 with a 16 GB card, native 1024 x 600 touch output, a
  minimal Cage/Chromium appliance, bounded storage, reproducible Ansible
  deployment, and verified two-way rollback.
- **2.5** — Added Pilot Core 0.14's bounded energy/now-playing display surface,
  enrolled the Raspberry Pi with a display-only device credential, and added
  touch-native Home, Energy, Music, and System pages with tap and swipe
  navigation.
- **2.6** — Added Pilot Linux Display 0.3's animated power-flow diagram with
  magnitude-scaled motion, source glow, grid import/export direction, battery
  charge/discharge direction, and retained live SOC telemetry.
- **2.7** — Added Pilot Linux Display 0.3.1 with a hidden kiosk pointer and
  explicit moving energy particles, including dedicated Battery-to-Home
  discharge and reversed charging/export paths.
- **2.8** — Added the N150 Media Console architecture: a native-HDMI Debian
  room role with a fullscreen Pilot shell, Music Assistant presentation,
  supervised mpv/Jellyfin local video, iOS control through Pilot Core, and a
  strict Shield boundary for Dolby Vision, DRM, and commercial streaming.
- **2.9** — Activated measured Office Sendspin ducking, added the Home Assistant
  satellite-state focus bridge, enabled the accepted Denon HEOS music route,
  and added entity-scoped Denon power and source commands.
- **3.0** — Added Pilot Core 0.18's split Denon transport: Music Assistant and
  HEOS remain authoritative for playback/state while a configuration-only,
  allowlisted port-8080 adapter handles receiver power and named input
  selection after native Home Assistant AVR discovery failed.
