# Pilot Home Lab Monitoring

## Drill-down and guarded migration

Pilot clients can drill into each Proxmox node and workload. The workload view
includes CPU, memory, uptime, cumulative disk and network I/O, tags, and its
owning node. Host agents add CPU/package temperatures that Proxmox does not
expose consistently.

Migration is separate from monitoring. The existing monitoring token remains
read-only. Enabling it requires a second token through
`proxmox_migration_token_id` and `PROXMOX_MIGRATION_TOKEN_SECRET`. Pilot rejects
offline destinations, locked guests, and node-local storage, then requires a
single-use 120-second confirmation before submitting the operation.

TrueNAS uses a dedicated API key and reports system identity, pool health,
allocated/free capacity, disks, SMART state, disk temperature and active
alerts. Store the key only in the `TRUENAS_API_KEY_FILE` deployment secret.

Pilot Core 0.32 introduces one normalized, read-only contract for home-lab
health. Clients consume Pilot rather than retaining Proxmox or TrueNAS secrets.

## Sources

- Proxmox VE supplies cluster quorum, node CPU/RAM/root storage, VM/container
  state and storage utilization through a dedicated `PVEAuditor` API token.
- TrueNAS supplies system, pool, disk, SMART temperature and active alert data
  through an API key and its JSON-RPC WebSocket API.
- `pilot-homelab-agent` supplies host-only CPU temperature and NVIDIA telemetry
  over an outbound HTTPS connection to Pilot Core. It performs no control.

## API

Administrator operations use `GET /v1/homelab?force=false`. Paired Pilot
clients use `GET /v1/devices/{device_id}/homelab?force=false` and require
`home-read`, `display`, `portable-client`, or `homelab-read`.

Telemetry devices publish to
`POST /v1/devices/{device_id}/homelab/telemetry` and require the explicit
`homelab-agent` capability. The response schema is `pilot.homelab.v1`. Core
caches successful polls for 15 seconds and returns a clearly marked stale
snapshot if every configured upstream becomes unavailable.

## Secrets and permissions

The Proxmox principal is `pilot-monitor@pve!pilot-core` with only `PVEAuditor`
at `/`. Store its secret in `infra/secrets/proxmox_token_secret` on the Core
host. Create a TrueNAS API key dedicated to Pilot and store it in
`infra/secrets/truenas_api_key`. Neither credential is returned to clients.

Host agents use an independently revocable Pilot device token stored at
`/etc/pilot-homelab-agent/device-token`. The supplied systemd sandbox removes
privileges and makes the host filesystem read-only to the process.

## Acceptance

1. All expected Proxmox nodes appear and cluster quorum is correct.
2. CPU, RAM, root storage and running workload totals match the Proxmox UI.
3. TrueNAS pools, disks, SMART state and temperatures match the storage UI.
4. GPU telemetry becomes stale within 45 seconds when an agent stops.
5. Revoking any provider or device token affects only that provider.
6. Restart Pilot Core and verify the dashboard recovers without client repair.

TrueNAS remains intentionally marked “API key required” until its dedicated
key is installed. Do not substitute root SSH credentials for the API key.
