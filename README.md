# Pilot Framework

[![GitHub](https://img.shields.io/badge/GitHub-private_repository-181717)](https://github.com/jimmy8889/jarvis-home-ai)

Pilot OS is developed under the **Jarvis Home AI** project. The canonical,
living architecture reference is
[docs/PILOT_OS_BLUEPRINT.md](docs/PILOT_OS_BLUEPRINT.md).

Pilot is a local-first platform for voice, audio, home automation, media,
meetings, and personal intelligence. The repository contains the deployed
Debian room endpoint and the first secure Pilot Core orchestration service.

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

Staged Music Assistant playback is documented in
[docs/MUSIC_ASSISTANT.md](docs/MUSIC_ASSISTANT.md).

The central room/player registry is documented in
[docs/PILOT_CORE.md](docs/PILOT_CORE.md).

Pilot Core can be started centrally with Docker Compose:

```bash
cp infra/.env.example infra/.env
# Generate and insert strong tokens, then add HA/MA long-lived tokens.
docker compose -f infra/docker-compose.yml up -d --build
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
config/                Versioned example room configuration
deploy/ansible/        Reproducible Debian 13 deployment
deploy/scripts/        Inventory, validation, and rollback commands
docs/                  Architecture, ADRs, research, and operator runbooks
packages/              Shared schemas and future SDK packages
systemd/               Service definitions
infra/                 Central Pilot Core container deployment
```

## Safety boundaries

- The playbook changes only the targeted Debian room endpoint.
- It never edits Proxmox, VFIO, IOMMU, GPU, HDMI, or host USB configuration.
- Bluetooth is optional and remains disabled in configuration until requested.
- Device selection is explicit; the deployment does not guess which sound card
  should become the default.
- Each deployment is installed as a new release. `pilot-rollback` switches back
  to the preceding release and retains configuration backups.
- LLMs may query filtered state and propose plans, but real actions always pass
  through execution policy and the skill runtime.
