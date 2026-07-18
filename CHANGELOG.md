# Changelog

## 2026-07-18

- Added Pilot Core 0.11's authenticated embedded-node snapshot, local Assist
  PCM streaming, bounded weather projection, and immutable firmware delivery
  APIs.
- Added Pilot Display Node 0.2.1 with QMI8658 motion wake, staged bedroom
  brightness, a touch weather page, push-to-talk, animated voice states,
  ES7210 microphone capture, ES8311 response playback, and rollback-safe OTA.
- Published the immutable 0.2.1 image through Pilot Core's authenticated
  firmware service for the Bedroom node's first USB acceptance flash.
- Made the embedded WAV decoder accept Home Assistant's bounded streaming WAV
  output, whose RIFF and data lengths are deliberately left unspecified.
- Enabled the deployed local Assist pipeline and Home Assistant Piper provider;
  synthesis explicitly requests 16 kHz, mono, 16-bit WAV for deterministic
  embedded playback.
- Added Pilot Display Node 0.1 firmware for the Waveshare
  ESP32-C6-Touch-AMOLED-2.16, with a burn-in-conscious 480 x 480 office clock,
  Brisbane timezone, Wi-Fi/NTP synchronization, RTC fallback, and native USB
  diagnostics.
- Added an OTA-ready 16 MB partition layout, pinned ESP-IDF component
  dependencies, reproducible build/flash scripts, third-party notices, and a
  complete factory-flash rollback procedure.
- Tuned the no-PSRAM display and Wi-Fi memory profiles so LVGL, Wi-Fi 6, NTP,
  and the clock can coexist; Wi-Fi failure now preserves an operational offline
  RTC clock instead of causing a reboot loop.
- Backed up the complete original factory flash before deployment, flashed the
  Pilot image with hash verification, then validated Wi-Fi, DHCP, NTP, RTC
  update, minute heartbeat, and reset recovery on the physical board.

## 2026-07-17

- Added Pilot Core 0.10 authenticated observability with derived endpoint
  freshness, provider/player checks, actionable alerts, and Prometheus-format
  metrics; the dashboard now renders the same attention model.
- Added a strictly read-only Media Room acceptance harness that verifies the
  accepted Denon/Shield identities and fail-closed control state without
  sending media or Home Assistant mutations.
- Added Pilot TV 0.1 as a buildable NVIDIA Shield application using Kotlin and
  Compose for TV, with process-memory credentials, private-LAN address policy,
  operations refresh, room/player state, and now-playing views.
- Added the local meeting-intelligence foundation: bounded atomic recording
  ingestion, integrity metadata, meeting lifecycle, timestamped transcripts,
  and evidence-linked decisions and action items.
- Added Pilot Core 0.7 production operations with file-backed Docker secrets,
  a read-only capability-free container, immutable image tags, bounded logs,
  and silent deployment diagnostics.
- Added room- and device-bound, short-lived bootstrap grants that can be
  redeemed exactly once; reusable bootstrap registration is disabled in the
  production configuration.
- Added read-only Home Assistant and Music Assistant connectivity diagnostics
  that never invoke conversation, TTS, playback, volume, or home actions.
- Added cold integrity-manifested central backups, guarded restores with archive
  traversal/integrity checks, and an automatic pre-restore safety backup.
- Added Room Agent 0.5 supervised activation receipts and a fail-closed playback
  gate tied to the accepted room, capture device, K3 route, and speaker node.
- Added secret, enrollment, deployment, diagnostic, backup, restore, validation,
  and activation operator tooling plus production runbooks and CI coverage.
- Pinned the production container to UID/GID `10001` and made root-run secret
  initialization grant that group read-only access without exposing host secret
  files to other users.
- Added Pilot Core 0.6 local TTS synthesis with Home Assistant/Piper and
  OpenAI-compatible providers.
- Added bounded response streaming, content-type normalization, audio signature
  validation, redirect denial, and same-origin Home Assistant proxy retrieval.
- Added deterministic `/v1/rooms/{room_id}/speak` orchestration and optional
  spoken Home Assistant conversation responses.
- Added provider status, configuration validation, the `pilot-speak` operator
  tool, tests, deployment examples, and the local TTS activation runbook.
- Added Pilot Core 0.5 room-bound audio assets for pre-rendered assistant speech
  and announcements, with bounded retention and file sizes.
- Added per-device, same-room download authorization and SHA-256/size manifests;
  room agents never receive arbitrary media URLs.
- Added room-agent verified downloads, private caching, single-slot `pw-play`
  lifecycle management, natural-completion cleanup, and cancellation.
- Connected real assistant/announcement playback state to the existing source
  reporting and audio-focus model while keeping live ducking disabled.
- Added the `pilot-audio` upload/dispatch operator tool, reproducible room cache
  configuration, tests, and the audio delivery activation runbook.
- Added Pilot Core 0.4 deterministic room, player, and capable-device target
  resolution without requiring callers or LLMs to select infrastructure IDs.
- Added joined room state containing sources, focus, health, connections,
  players, and resolved targets.
- Added a single all-room state endpoint for deterministic “what is happening
  where?” queries and future dashboards.
- Added room-level media and endpoint-control APIs with controlled explicit
  overrides and deterministic offline queuing.
- Added room-aware `pilot-command` routing and the `pilot-media` operator tool.
- Documented room orchestration and advanced the canonical blueprint to 0.8.
- Added Pilot Core 0.3 durable device commands with queued, delivered,
  succeeded, failed, and expired states.
- Added authenticated outbound room-agent WebSockets, heartbeat and reconnect
  handling, live connection visibility, and command-result event broadcasts.
- Added a persistent room command journal that prevents execution replay after
  reconnects or lost acknowledgements.
- Added the `pilot-command` operator client and Ansible configuration for
  command transport, dependency installation, credentials, and health checks.
- Documented the command security, delivery, activation, and rollback model and
  advanced the canonical blueprint to 0.7.
- Merged the Jarvis architecture and Pilot intelligence framework pull requests,
  including execution, memory, skill, inference, world-state, planning, event,
  knowledge, identity, and schema design documents.
- Added room-agent 0.2 with loopback transport, room/source volume,
  push-to-talk, assistant, announcement, and cancel controls.
- Added self-expiring transient focus state so failed clients cannot leave room
  audio permanently ducked.
- Connected listening, assistant speech, and critical announcements to the
  deterministic audio-focus policy without enabling live gain enforcement.
- Extended outbound room reporting to cover all five priority sources.
- Added control and focus tests and advanced the canonical blueprint to 0.6.
- Added pull-request CI for service tests, Ruff, compilation, event-schema JSON,
  deployment scripts, and Ansible syntax.

## 2026-07-16

- Migrated the Office N150 from a Proxmox VM to native Debian 13 at the
  permanent address `10.0.1.53` to remove virtualization from the audio path.
- Made the voice runtime derive its network interface from Ansible facts rather
  than assuming the VM-only `ens18` name.
- Changed audible validation to use the shared PipeWire route and fixed test
  directory ownership so it can coexist with the running voice service.
- Registered the native endpoint in Home Assistant, assigned it to Office, and
  configured the Full local assistant pipeline with Piper and Whisper.
- Verified all 15 health checks, microphone capture, K3 playback, simultaneous
  input/output, Music Assistant, AirPlay, voice, and rollback state after reboot.
- Published the baseline as the private `jimmy8889/jarvis-home-ai` repository.
- Upgraded Pilot Core to an authenticated FastAPI control plane with SQLite
  persistence, hashed per-device credentials, event history, and WebSockets.
- Added deterministic audio-focus decisions for critical, assistant, Bluetooth,
  AirPlay, and Music Assistant sources.
- Added Music Assistant playback/search/transfer controls and Home Assistant
  conversation routing adapters.
- Added outbound room-agent health and MPRIS source-state reporting while
  keeping its diagnostic API loopback-only.
- Added a local PipeWire stream focus enforcer with captured-volume restoration;
  deployment remains disabled until the audible source-switching gate passes.
- Added a central Docker Compose deployment, persistent volume, health check,
  device-registration helper, and Ansible-managed device credential.

## 2026-07-15

- Reconstructed the framework because the referenced `/mnt/data` archive was
  unavailable in the Codex workspace.
- Added a standard-library Python room-agent with `/healthz`, `/readyz`, and
  `/v1/status` endpoints.
- Added a Debian 13 Ansible role for PipeWire, WirePlumber, ALSA, BlueZ, Avahi,
  Git, Python, a virtual environment, user lingering, and systemd services.
- Added opt-in Bluetooth configuration; it is installed but not enabled by
  default.
- Added hardware inventory and staged audio validation tooling.
- Added release-based deployment and one-command rollback tooling.
- Documented Proxmox boundaries, deployment, validation, and rollback.
- Explicitly excluded Intel GPU/HDMI passthrough from this milestone.
- Made headless PipeWire activation independent of `sudo`, which is absent on a
  minimal root-administered Debian installation.
- Tightened first-deployment rollback detection so only a real active release
  can become the previous-release target.
- Made the release identifier use Ansible's once-per-play gathered timestamp;
  this prevents lazy template evaluation from producing mismatched release
  directory names during a longer deployment.
- Made `/etc/pilot` group-traversable by the `pilot` service account while
  retaining root ownership and a restrictive `0750` mode.
- Added the Pilot user's D-Bus address to diagnostics and the room-agent service.
- Prevented Bluetooth inventory from blocking when BlueZ is intentionally off.
- Treat empty ALSA device listings as not ready even though the ALSA utilities
  return a successful process exit code.
- Render the room-agent systemd environment with the resolved `pilot` UID;
  system-service `%U` resolves to the manager user and is not suitable here.
- Deployed to the first Debian 13 office VM and verified persistence across two
  consecutive reboots. Software health passes; USB audio validation is pending
  because no USB peripherals are yet visible to the guest.
- Added stable PipeWire node and ALSA device fields to the room configuration
  after validating the Stadium USB microphone and Focusrite Scarlett 8i6.
- Made audible validation use the room's configured stable ALSA device names by
  default, while retaining command-line overrides.
- Replaced the synthetic duplex test tone with bounded replay of the captured
  microphone sample.
- Replaced the office output with a FiiO K3 and added a boot-time service that
  resolves stable PipeWire node names to transient IDs before applying defaults.
- Updated PipeWire status parsing to accept the Unicode tree prefixes emitted by
  `wpctl status --name`.
- Added an opt-in, pinned bare-metal deployment for Open Home Foundation Linux
  Voice Assistant v1.1.12, staged disabled until device enumeration is complete.
- Passed Linux Voice Assistant compiler flags as one explicit argument so the
  upstream setup script receives them correctly.
- Configured the enumerated Stadium and K3 runtime device names and disabled the
  unnecessary Pulse cookie file for the same-user local socket.
- Derive the Linux Voice Assistant bind address from Ansible's default IPv4
  facts so its ESPHome mDNS record does not advertise the wildcard address.
- Restart Linux Voice Assistant when its generated systemd unit changes.
- Enabled the office voice satellite with the Stadium input, K3 output, and
  temporary `okay_nabu` wake model; verified TCP and ESPHome mDNS discovery
  after a full reboot.
- Extended `pilot-validate` to verify the enabled voice-satellite service and
  its configured API socket.
- Added voice-satellite service, listening socket, and Home Assistant connection
  state to the room-agent status model and readiness calculation.
- Added a reproducible Shairport Sync AirPlay receiver routed through Pilot's
  PipeWire session, with its own hardened systemd unit and D-Bus/MPRIS controls.
- Added AirPlay service/listener health to the room-agent and `pilot-validate`.
- Added staged Squeezelite deployment for Music Assistant, intentionally disabled
  until the server address and cross-VLAN port reachability are confirmed.
- Imported the user-provided blueprint as the canonical Pilot OS architecture
  reference and reconciled it with the live office deployment as version 0.2.
- Added and deployed the official Sendspin 7.5.0 headless client, connected to
  Music Assistant at `10.0.2.72:8927` as `Pilot Office Music`.
- Added Music Assistant service and transport state to room readiness and
  `pilot-validate`; Squeezelite remains an unused fallback.
- Verified Sendspin, voice, AirPlay, audio defaults, and room-agent persistence
  across a controlled VM reboot with all fifteen validation checks passing.
- Added the first dependency-free Pilot Core service with validated TOML room
  and player configuration, deterministic registry revisions, read-only REST
  endpoints, tests, and an office example registry.
