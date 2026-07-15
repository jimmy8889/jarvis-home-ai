# Music Assistant player

The office endpoint uses the official Sendspin headless client as its native
Music Assistant player.

```text
Music Assistant add-on: 10.0.2.72
Sendspin server: ws://10.0.2.72:8927/sendspin
Client: Pilot Office Music
Client ID: pilot-office
Runtime: sendspin 7.5.0, pinned in a versioned Python environment
Audio output: ALSA `default` → PipeWire → FiiO K3
```

The client runs as the `pilot` user and keeps its configuration and cache under
`/var/lib/pilot/sendspin`. Hardware/system volume control is disabled so Music
Assistant changes the player stream rather than changing the shared K3 sink
used by AirPlay and assistant responses.

Validate with:

```bash
systemctl status pilot-sendspin
pilot-validate
ss -ntp | grep ':8927'
journalctl -u pilot-sendspin -b --no-pager
```

Music Assistant should show **Pilot Office Music** as a Sendspin player. Select
it and play both a TIDAL track and a local lossless track for audible acceptance.

Squeezelite deployment remains available as an opt-in fallback, but it is not
installed or enabled on the office endpoint.
