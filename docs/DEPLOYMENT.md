# Debian 13 deployment

## Before connecting over SSH

Install native Debian 13 and connect only the USB microphone, USB DAC/speakers,
and optional dedicated Bluetooth adapter required by the room. Do not configure
the Intel GPU, HDMI audio, or motherboard HDA device during the office baseline.

Record the Debian VM's IP address, an SSH username with `sudo`, and either an SSH
key or temporary password. Prefer keys. The deployment never stores the SSH
credential in the repository.

## Controller preparation

```bash
cd deploy/ansible
cp inventory/hosts.example.yml inventory/hosts.yml
```

Edit `hosts.yml`, then verify access without changing the endpoint:

```bash
ansible -i inventory/hosts.yml pilot_endpoints -m ping
ansible-playbook -i inventory/hosts.yml site.yml --check --diff
```

The playbook's Debian 13 assertion intentionally stops deployment on any other
distribution or major release.

## Deploy

```bash
ansible-playbook -i inventory/hosts.yml site.yml --diff
```

The role installs:

- PipeWire, PipeWire Pulse compatibility, and PipeWire ALSA integration
- WirePlumber
- ALSA utilities
- BlueZ and the PipeWire Bluetooth plugin
- Avahi
- Git, curl, USB inventory tools, Python, and Python venv support
- the Pilot room-agent and its systemd unit
- the compatible WebSocket runtime used for outbound Pilot Core commands
- optional Open Home Foundation Linux Voice Assistant runtime
- optional Shairport Sync AirPlay receiver routed through PipeWire
- endpoint inventory, validation, and rollback commands

The room-agent is installed into its release-specific virtual environment. The
deployment requires PyPI access to install its bounded `websockets` dependency.
The active release and its dependencies remain self-contained for rollback.

BlueZ packages are installed in every case, but `bluetooth.service` is stopped
and disabled unless `room_endpoint_bluetooth_enabled: true` is set for the host.

## Configuration ownership

The generated room configuration lives at `/etc/pilot/room.toml`. It is owned
by root and readable by the `pilot` group. Store the Pilot Core device token in
Ansible Vault, not plaintext inventory. The role installs it separately with
mode `0600` when reporting or commands are enabled.

Pilot Core deployment and device registration are documented in
[PILOT_CORE.md](PILOT_CORE.md). Command activation is documented in
[COMMAND_TRANSPORT.md](COMMAND_TRANSPORT.md).

## Post-deployment checks

```bash
sudo pilot-hardware-inventory
sudo pilot-validate
systemctl status pilot-room-agent --no-pager
journalctl -u pilot-room-agent -b --no-pager
```

Only after silent checks pass should `sudo pilot-validate --audio-tests` be run.
