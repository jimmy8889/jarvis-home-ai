# Pilot Bluetooth input

Pilot room endpoints can act as bounded Bluetooth A2DP receivers while
PipeWire remains the sole owner of the accepted room output.

```text
iPhone or guest device
        │ Bluetooth A2DP
        ▼
BlueZ + WirePlumber A2DP sink
        │ bluez_input source
        ▼
PilotBluetooth managed loopback
        │
        ▼
accepted room PipeWire sink
```

## Security boundary

Bluetooth is powered at boot when enabled, but the endpoint is neither
discoverable nor pairable by default. The `NoInputNoOutput` agent starts only
inside an operator-opened, 180-second pairing window and stops when the window
closes. A newly paired device is not trusted
automatically; the operator must compare its Bluetooth address and explicitly
trust it. Existing trusted devices may reconnect while the pairing window is
closed.

```bash
sudo pilot-bluetooth-pair open
sudo pilot-bluetooth-pair paired
sudo pilot-bluetooth-pair trust AA:BB:CC:DD:EE:FF
sudo pilot-bluetooth-pair close
```

Remove a device with:

```bash
sudo pilot-bluetooth-pair remove AA:BB:CC:DD:EE:FF
```

## Audio routing and focus

Room Agent 0.7 discovers connected `bluez_input` sources and creates only
Pilot-owned `module-loopback` routes into the configured `speaker_node`.
Loopbacks use the `PilotBluetooth` application identity and are removed when
the source disappears or Room Agent exits. Unrelated operator-created
loopbacks are never adopted or removed.

Bluetooth is reported to Pilot Core only while the remote A2DP source is
actually running. The focus order remains:

1. Critical announcement
2. Assistant response
3. Bluetooth
4. AirPlay
5. Music Assistant

An assistant response therefore ducks Bluetooth. Bluetooth suppresses AirPlay
and Music Assistant while it is active, and their accepted baseline gains are
restored when the Bluetooth source stops.

## Deployment and recovery

The Debian 13 Ansible role installs a bounded BlueZ policy, a transient pairing
agent, a WirePlumber A2DP-sink role and the operator command. Each deployment
backs up Pilot, BlueZ, WirePlumber and Bluetooth service configuration below
`/var/backups/pilot` before changing it.

Restore a selected archive with:

```bash
sudo pilot-endpoint-restore /var/backups/pilot/pre-RELEASE.tar.gz
```

The restore command creates a second emergency backup before extracting the
selected archive. Code-only rollback remains available through
`sudo pilot-rollback`.

## Acceptance

Silent acceptance requires:

```bash
sudo pilot-validate
```

This verifies the Bluetooth service, inactive pairing agent, powered controller,
closed default pairing state, PipeWire bridge readiness, voice, AirPlay, Sendspin,
Core commands and real capture/playback hardware.

Physical acceptance still requires a nearby operator:

1. Open the pairing window and pair one named phone.
2. Confirm and trust its address, then close the window.
3. Play audio and verify it reaches the accepted room output.
4. Invoke Pilot and verify Bluetooth ducks and restores.
5. Switch Bluetooth, AirPlay and Music Assistant in both directions.
6. Reboot and verify the trusted phone reconnects without making the endpoint
   discoverable or pairable.
