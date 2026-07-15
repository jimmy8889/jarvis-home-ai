# AirPlay receiver

Pilot uses Debian's Shairport Sync package as a classic AirPlay receiver. It is
run by the same unprivileged `pilot` account as PipeWire and the voice satellite.
The PulseAudio-compatible backend therefore appears as a normal stream in
Pilot's PipeWire graph and follows the configured default sink.

Office settings:

```text
Advertised name: Pilot Office
RTSP port: 5000
Output backend: PulseAudio compatibility → PipeWire → FiiO K3
Initial source volume when unspecified: -24 dB
Volume range: 40 dB
```

The distribution-provided `shairport-sync.service` is disabled. Pilot owns a
separate hardened `pilot-airplay.service`, configuration under `/etc/pilot`, and
a user-session D-Bus/MPRIS interface for later playback orchestration.

Validate with:

```bash
systemctl status pilot-airplay
pilot-validate
avahi-browse -rt _raop._tcp
```

Select **Pilot Office** from an iPhone or Mac AirPlay picker and start playback.
While playing, `wpctl status --name` should show the Shairport Sync stream linked
to the configured room sink.

This Debian package provides classic AirPlay audio. It does not provide AirPlay
video, and this milestone does not yet implement Pilot's source-priority or
ducking policy.
