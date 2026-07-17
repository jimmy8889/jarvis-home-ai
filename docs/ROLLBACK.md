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

The command result journal is stored at `/var/lib/pilot/commands.db`, outside the
release tree. It intentionally survives rollback so a command already executed
by a newer release is not replayed by an older one after reconnect. Delete this
journal only during a deliberate full device reset, never as a routine rollback
step.

The automation does not alter firmware, GPU, HDMI, or host USB configuration.
Those hardware changes remain separate from a Pilot release rollback.

Central Pilot Core has a separate data recovery path. Use
`pilot-core-backup` for a cold integrity-manifested archive and
`pilot-core-restore --yes` for a guarded restore. Restore automatically creates
a pre-restore backup first. See
[PRODUCTION_OPERATIONS.md](PRODUCTION_OPERATIONS.md).
