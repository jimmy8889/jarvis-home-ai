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

## Client experience

Pilot Core remains the credential and command boundary. Its scoped media APIs
provide normalized now-playing/queue state, search, playback and a
`pilot.media-browse.v1` detail projection. An artist URI resolves to albums and
songs; album and playlist URIs resolve to their tracks. iOS and Linux displays
use those projections for artwork-led discovery without storing the Music
Assistant token.

On iPhone, **This iPhone** is a native Sendspin player inside Pilot. It appears
beside room outputs, shares the artwork-led browse/search interface, survives
tab changes and supports background audio. Pilot Core derives the player's
`pilot-native-{device_id}` Music Assistant queue server-side and proxies local
commands through the paired device identity, so neither an administrator token
nor the Music Assistant token is embedded in the app.

The client currently uses Music Assistant's configured trusted LAN Sendspin
origin for the audio socket. Remote playback must wait for a trusted TLS route;
the existing private-LAN HTTP exception is not an internet exposure policy.

The Raspberry Pi 10-inch node has an optional pinned Sendspin player in the
display Ansible role. Production installs the runtime but leaves it disabled
until a USB DAC is physically attached, assigned a stable PipeWire sink and
audibly accepted. The bedroom display has `music_enabled = false` and does not
present a music destination.

Squeezelite deployment remains available as an opt-in fallback, but it is not
installed or enabled on the office endpoint.
