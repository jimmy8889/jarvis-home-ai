# Changelog

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
