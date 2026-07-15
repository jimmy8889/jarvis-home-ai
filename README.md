# Pilot Framework

Pilot OS is developed under the **Jarvis Home AI** project. The canonical,
living architecture reference is
[docs/PILOT_OS_BLUEPRINT.md](docs/PILOT_OS_BLUEPRINT.md).

Pilot is a local-first platform for voice, audio, and home automation. The
repository contains the deployed Debian room endpoint and the first Pilot Core
room/player registry.

The deployment deliberately does **not** configure Intel GPU or HDMI
passthrough.

## Quick start

1. Pass the required USB devices to the Debian VM in Proxmox.
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

Staged Music Assistant playback is documented in
[docs/MUSIC_ASSISTANT.md](docs/MUSIC_ASSISTANT.md).

The central room/player registry is documented in
[docs/PILOT_CORE.md](docs/PILOT_CORE.md).

The first office VM deployment is recorded in
[docs/DEPLOYMENT-2026-07-15.md](docs/DEPLOYMENT-2026-07-15.md).

## Repository layout

```text
apps/room-agent/       Local health/status API
apps/pilot-core/       Central room and player registry API
config/                Versioned example room configuration
deploy/ansible/        Reproducible Debian 13 deployment
deploy/scripts/        Inventory, validation, and rollback commands
docs/                  Architecture and operator runbooks
systemd/               Service definitions
```

## Safety boundaries

- The playbook changes only the Debian guest.
- It never edits Proxmox, VFIO, IOMMU, GPU, HDMI, or host USB configuration.
- Bluetooth is optional and remains disabled in configuration until requested.
- Device selection is explicit; the deployment does not guess which sound card
  should become the default.
- Each deployment is installed as a new release. `pilot-rollback` switches back
  to the preceding release and retains configuration backups.
