# Debian 13 deployment

## Before connecting over SSH

In Proxmox, add only the individual USB microphone and USB DAC/speakers to the
VM. Add a dedicated USB Bluetooth adapter only if Bluetooth is part of the first
test. Do not add the Intel GPU, HDMI audio, motherboard HDA device, or complete
USB controller.

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
- optional Open Home Foundation Linux Voice Assistant runtime
- optional Shairport Sync AirPlay receiver routed through PipeWire
- endpoint inventory, validation, and rollback commands

The room-agent has no third-party Python dependencies, so deployment does not
need PyPI access. Its isolated virtual environment runs the versioned source
directly from the active release.

BlueZ packages are installed in every case, but `bluetooth.service` is stopped
and disabled unless `room_endpoint_bluetooth_enabled: true` is set for the host.

## Configuration ownership

The generated room configuration lives at `/etc/pilot/room.toml`. It is owned
by root and readable by the `pilot` group. Do not store passwords or long-lived
tokens in the inventory; use Ansible Vault when secrets are introduced later.

## Post-deployment checks

```bash
sudo pilot-hardware-inventory
sudo pilot-validate
systemctl status pilot-room-agent --no-pager
journalctl -u pilot-room-agent -b --no-pager
```

Only after silent checks pass should `sudo pilot-validate --audio-tests` be run.
