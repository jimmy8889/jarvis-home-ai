# Pilot Framework

[![GitHub](https://img.shields.io/badge/GitHub-private_repository-181717)](https://github.com/jimmy8889/jarvis-home-ai)

Pilot OS is developed under the **Jarvis Home AI** project. The canonical,
living architecture reference is
[docs/PILOT_OS_BLUEPRINT.md](docs/PILOT_OS_BLUEPRINT.md).

Pilot is a local-first platform for voice, audio, home automation, media,
meetings, and personal intelligence. The repository contains the deployed
Debian room endpoint and the first secure Pilot Core orchestration service.

## Current release status

The current source release adds the first shared, versioned product contract
for Pilot clients:

- a device manifest (`pilot.client.v1`) that advertises the authenticated
  device identity, capabilities, feature gates and canonical endpoints;
- a recoverable product snapshot (`pilot.snapshot.v1`) plus cursor-based long
  polling and WebSocket event delivery;
- curated Home Assistant projections with explainable include/exclude policy,
  authoritative room trust, supported actions and duplicate identity metadata;
- single-use, room-bound pairing grants, a locally rendered scan-to-pair QR,
  and encrypted client-side device-token storage, with self-service rotation
  and administrator revocation;
- typed media, energy, home and assistant payloads shared by iOS, Android,
  Shield TV and the Linux display surface.

The Core contract and Python display service have automated test coverage.
Native mobile and TV builds are also CI-gated; installation, touch/focus tuning
and audiovisual acceptance on the actual phone, wall tablet and Shield remain
separate physical-device acceptance steps. Pilot Core 0.28.0 is deployed on the
Docker server as immutable image `core-0.28.0-20260723.1` from commit
`a1b9fc5c`; its cold rollback archive, readiness, authenticated APIs, Home
Assistant, Music Assistant and TTS checks all pass.

The deployment deliberately does **not** configure Intel GPU or HDMI
passthrough.

## Quick start

1. Install native Debian 13 on the room endpoint and connect the required USB
   audio devices.
2. Copy `deploy/ansible/inventory/hosts.example.yml` to `hosts.yml` and set the
   VM address and SSH user.
3. From a workstation with Ansible installed:

   ```bash
   ansible-playbook -i deploy/ansible/inventory/hosts.yml \
     deploy/ansible/site.yml
   ```

4. On the endpoint, inspect devices before selecting stable ALSA/PipeWire names:

   ```bash
   sudo pilot-hardware-inventory
   sudo -u pilot XDG_RUNTIME_DIR=/run/user/$(id -u pilot) wpctl status
   ```

5. Run non-destructive checks, then the audible validation tests:

   ```bash
   sudo pilot-validate
   sudo pilot-validate --audio-tests
   ```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and
[docs/VALIDATION.md](docs/VALIDATION.md) before deployment.

Production Pilot Core secrets, deployment, diagnostics, enrollment, backup,
and restore are documented in
[docs/PRODUCTION_OPERATIONS.md](docs/PRODUCTION_OPERATIONS.md).

After deployment, the private operations dashboard is available at
`http://PILOT_CORE_HOST:8770/dashboard`. Room state and controls remain
protected by the Pilot Core administrator token. The dashboard can now mint a
short-lived, single-use pairing grant for an explicitly selected device
profile and room, render that grant as a local QR, and review or override
entity presentation policy. It never shows provider credentials or an existing
device token.

The physical acceptance receipt and fail-closed room playback gate are
documented in [docs/SUPERVISED_ACTIVATION.md](docs/SUPERVISED_ACTIVATION.md).

Voice-satellite deployment is documented in
[docs/VOICE_SATELLITE.md](docs/VOICE_SATELLITE.md).

The room AirPlay receiver is documented in
[docs/AIRPLAY.md](docs/AIRPLAY.md).

Audio source priority and the safely gated ducking engine are documented in
[docs/AUDIO_FOCUS.md](docs/AUDIO_FOCUS.md).
The same document describes the room agent's loopback-only transport, volume,
push-to-talk, assistant, announcement, and cancel API.

Authenticated, durable Pilot Core-to-room command delivery is documented in
[docs/COMMAND_TRANSPORT.md](docs/COMMAND_TRANSPORT.md).

Deterministic room state and room-level player/device routing are documented in
[docs/ROOM_ORCHESTRATION.md](docs/ROOM_ORCHESTRATION.md).

Room-bound, authenticated assistant and announcement playback is documented in
[docs/AUDIO_DELIVERY.md](docs/AUDIO_DELIVERY.md).

Local Home Assistant/Piper and OpenAI-compatible speech synthesis is documented
in [docs/LOCAL_TTS.md](docs/LOCAL_TTS.md).
The same runbook includes the authenticated, silent Piper-to-Faster-Whisper
acceptance test used after voice-engine upgrades.

The ESP32-C6 AMOLED bedroom node firmware, including motion-aware dim/off,
weather, touch push-to-talk, local voice responses, authenticated OTA,
reproducible builds, and factory-image rollback, is documented in
[firmware/pilot-display-node/README.md](firmware/pilot-display-node/README.md).

The Raspberry Pi 4 large-format touch display appliance, minimal Wayland kiosk,
storage controls, shared energy/climate dashboard, interactive Music Assistant
surface, optional USB-DAC Sendspin endpoint, deployment, acceptance, and
rollback are documented in
[docs/RASPBERRY_PI_DISPLAY_NODE.md](docs/RASPBERRY_PI_DISPLAY_NODE.md).

The native-HDMI N150 Media Console, ten-foot music/video shell, supervised
mpv/Jellyfin playback, Shield boundary, and iOS remote contract are documented
in [docs/N150_MEDIA_CONSOLE.md](docs/N150_MEDIA_CONSOLE.md).

Pilot Core's room-scoped dialogue, deterministic Home Assistant fast path,
optional local model fallback, and typed tool boundary are documented in
[docs/CONTEXTUAL_ASSISTANT.md](docs/CONTEXTUAL_ASSISTANT.md).
The persistent Home Assistant entity catalogue, semantic discovery, coverage
reporting, bounded read tools, and dashboard controls are documented in
[docs/HOME_INTELLIGENCE.md](docs/HOME_INTELLIGENCE.md).
The Home Assistant conversation-agent installation and voice-pipeline rollback
path are documented in
[docs/HOME_ASSISTANT_CONVERSATION_BRIDGE.md](docs/HOME_ASSISTANT_CONVERSATION_BRIDGE.md).

The adaptive native iPhone and iPad room, media, and assistant client is
documented in
[docs/PILOT_IOS.md](docs/PILOT_IOS.md).

The native Android wall-tablet client, including secure enrolment, energy
visualisation, night operation, and kiosk-readiness boundaries, is documented
in [docs/PILOT_ANDROID.md](docs/PILOT_ANDROID.md).

The app-first interactive 3D home representation, shared iOS/Android digital
twin, Home Assistant projection, and wall-tablet roadmap are documented in
[docs/HOME_DIGITAL_TWIN.md](docs/HOME_DIGITAL_TWIN.md).

Read-only Denon HEOS and NVIDIA Shield discovery, Media Room registration, and
the fail-closed player control gate are documented in
[docs/MEDIA_ROOM.md](docs/MEDIA_ROOM.md).

The device-paired NVIDIA Shield media-room client is documented in
[docs/SHIELD_TV.md](docs/SHIELD_TV.md).

Central alerts and authenticated Prometheus metrics are documented in
[docs/OBSERVABILITY.md](docs/OBSERVABILITY.md).

The local meeting recording, transcript, decision, and action-item foundation
is documented in
[docs/MEETING_INTELLIGENCE.md](docs/MEETING_INTELLIGENCE.md).

Staged Music Assistant playback is documented in
[docs/MUSIC_ASSISTANT.md](docs/MUSIC_ASSISTANT.md).

The central room/player registry is documented in
[docs/PILOT_CORE.md](docs/PILOT_CORE.md).

Pilot Core can be started centrally with Docker Compose:

```bash
deploy/scripts/pilot-secrets init
cp infra/.env.example infra/.env
# Add HA/MA tokens through pilot-secrets, then deploy silently.
deploy/scripts/pilot-core-deploy
```

The original office VM deployment and permanent native migration are recorded
in [docs/DEPLOYMENT-2026-07-15.md](docs/DEPLOYMENT-2026-07-15.md) and
[docs/DEPLOYMENT-2026-07-16-NATIVE.md](docs/DEPLOYMENT-2026-07-16-NATIVE.md).

## Architecture research and decisions

The open-source assistant feature review is documented in
[docs/research/JARVIS_FEATURE_REVIEW.md](docs/research/JARVIS_FEATURE_REVIEW.md).

Material design decisions are recorded under
[docs/adr/](docs/adr/README.md). The initial ADRs cover execution modes,
layered memory, the skill runtime, the unified inference gateway, and the
separation of world state, knowledge, memory, planning, and execution.

A proposed skill package is shown in
[docs/schemas/skill-manifest.example.yaml](docs/schemas/skill-manifest.example.yaml).

## Pilot intelligence framework

The next architecture layer is described in
[docs/architecture/PILOT_INTELLIGENCE_FRAMEWORK.md](docs/architecture/PILOT_INTELLIGENCE_FRAMEWORK.md).
It defines:

- a live, provenance-aware world model
- a bounded planning and project engine
- a versioned internal event bus
- a knowledge graph and unified search service
- identity, permissions, and consent-based preference learning
- a shared event envelope schema under `packages/event-schema/`

## Repository layout

```text
apps/room-agent/       Local health/status API
apps/pilot-core/       Central room and player registry API
apps/pilot-ios/        Native iPhone and iPad home, media, and assistant client
apps/pilot-android/    Native Android wall-tablet Pilot client
apps/shield-tv/        Kotlin/Compose for TV media-room client
config/                Versioned example room configuration
deploy/ansible/        Reproducible Debian 13 deployment
deploy/scripts/        Inventory, validation, and rollback commands
docs/                  Architecture, ADRs, research, and operator runbooks
packages/              Shared schemas and future SDK packages
systemd/               Service definitions
infra/                 Central Pilot Core container deployment
firmware/              ESP32 room-node firmware and hardware support
integrations/          Home Assistant and other platform adapters
```

## Safety boundaries

- The playbook changes only the targeted Debian room endpoint.
- It never edits Proxmox, VFIO, IOMMU, GPU, HDMI, or host USB configuration.
- Bluetooth is optional and remains disabled in configuration until requested.
- Device selection is explicit; the deployment does not guess which sound card
  should become the default.
- Inferred room mappings are readable but are not authoritative enough for a
  Home Assistant mutation. An administrator must confirm the mapping or the HA
  registry must supply it.
- Pairing codes are short-lived and single-use. Clients receive their own
  capability-scoped device credential, never the Core administrator or
  provider credentials.
- Each deployment is installed as a new release. `pilot-rollback` switches back
  to the preceding release and retains configuration backups.
- LLMs may query filtered state and propose plans, but real actions always pass
  through execution policy and the skill runtime.
- Production Faster Whisper on the planned RTX 3080 remains deferred until
  that GPU is installed. Meeting transcription must continue to fail closed
  when no configured private Whisper-compatible endpoint is available.
