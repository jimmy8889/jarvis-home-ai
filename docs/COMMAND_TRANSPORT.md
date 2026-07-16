# Pilot Core command transport

Pilot Core 0.3 delivers room controls over an authenticated, outbound WebSocket.
Room endpoints do not expose their loopback control API to the LAN and do not
require inbound firewall rules.

```text
Administrator/client
        │ HTTPS admin command
        ▼
    Pilot Core ── SQLite command queue
        ▲
        │ authenticated outbound WebSocket
        ▼
   Room agent ── SQLite result journal ── local RoomController
```

## Delivery states

- `queued`: persisted by Pilot Core; the device may be offline.
- `delivered`: written to the connected device socket.
- `succeeded`: the room agent executed the local control and returned a result.
- `failed`: the room agent rejected the control or its local command failed.
- `expired`: no successful result arrived before the command expiry time.

Commands remain queued across Pilot Core restarts. Commands in `queued` or
`delivered` state are resent after device reconnection until a terminal result
arrives. The room agent records each result in
`/var/lib/pilot/commands.db` before sending it, and returns the cached result for
a repeated command ID. The journal retains the latest 1,000 results.

Command lifetime is bounded to 1–300 seconds. This is distinct from a transient
control's `ttl_seconds`, which bounds listening, assistant, or announcement
focus state on the room endpoint.

## Authentication

The same random per-device bearer credential is used for event reporting and
the command socket. Pilot Core stores only the token digest. A device can only
complete commands assigned to its own ID; rotating its registration rotates the
token.

Production deployments should put TLS in front of Pilot Core and use `https` in
the room's `core_url`, which automatically becomes `wss` for command transport.
Plain HTTP/WebSocket is suitable only on a trusted private network during the
initial deployment.

## API

Administrator endpoints:

- `POST /v1/devices/{device_id}/commands`
- `GET /v1/devices/{device_id}/commands`
- `GET /v1/commands/{command_id}`

Device endpoint:

- `WS /v1/devices/ws?device_id={device_id}`

Example command:

```json
{
  "action": "set_volume",
  "source": "room",
  "volume": 0.4,
  "expires_in_seconds": 30
}
```

The operator helper sends a command and optionally waits for its terminal
result:

```bash
export PILOT_CORE_ADMIN_TOKEN='...'
deploy/scripts/pilot-command \
  --core-url http://PILOT_CORE_HOST:8770 \
  --device-id pilot-office \
  --source music \
  --wait 10 \
  pause
```

## Safe activation

1. Deploy Pilot Core and create strong administrator/bootstrap tokens.
2. Register the room device and store its returned token in Ansible Vault.
3. Set `room_endpoint_core_url`, device ID, and device token.
4. Enable reporting and command transport.
5. Deploy the endpoint and run `pilot-validate`.
6. Confirm `/v1/devices` reports `connected: true`.
7. Send non-audible `start_listening` and `cancel` commands first.
8. Test pause and volume only when someone can verify the physical room.

Live PipeWire gain enforcement remains a separate opt-in acceptance gate.
