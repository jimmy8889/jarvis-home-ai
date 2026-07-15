# Rollback

Every deployment creates a timestamped directory under `/opt/pilot/releases`
and atomically points `/opt/pilot/current` at it. Before switching, the prior
target is stored in `/var/lib/pilot/previous_release`.

To switch back:

```bash
sudo pilot-rollback
sudo pilot-validate
```

The rollback command swaps current and previous targets, reloads systemd, and
restarts the room-agent. Running it again swaps forward to the release that was
just replaced.

Configuration and service snapshots are kept under `/var/backups/pilot`. A
release rollback does not automatically overwrite `/etc/pilot/room.toml`, since
doing so could discard deliberate room-device selections. Restore a configuration
archive manually only when the release rollback does not address the issue.

The automation does not alter the Proxmox host or its passthrough configuration,
so removing an individually passed-through USB device remains a separate,
reversible Proxmox action.
