# Office N150 deployment receipt — 2026-08-04

## Scope

- Host: `officen150` at `10.0.2.53`
- OS: native Debian 13
- Room Agent: 0.7.0
- Pilot Display: 0.7.2 in `media-console` mode
- Audio: observed K3 combined USB Audio/HID mono source and stereo sink
- HDMI, GPU, VFIO and IOMMU: unchanged and out of scope

## Promoted releases and rollback

```text
Room Agent current:  /opt/pilot/releases/20260804T004124
Room Agent previous: /opt/pilot/releases/20260804T003209
Display current:     /opt/pilot-display/releases/20260804T004252
Display previous:    /opt/pilot-display/releases/20260804T003337
Configuration backup: /var/backups/pilot/pre-20260804T004124.tar.gz
```

Code-only rollback remains `pilot-rollback`. A selected configuration archive
can be restored with `pilot-endpoint-restore`; the restore command validates the
archive and creates an emergency pre-restore backup first.

## Evidence

- Ansible completed with zero failed or unreachable tasks.
- All 65 Room Agent unit tests and all 15 Pilot Display tests passed.
- `pilot-validate` passed all 24 silent checks before and after reboot.
- PipeWire restored the observed K3 source and sink as defaults.
- Linux Voice Assistant reconnected to Home Assistant.
- AirPlay listened on TCP 5000 and Sendspin reconnected to Music Assistant.
- Room Agent reconnected its authenticated Pilot Core command WebSocket.
- Bluetooth remained powered but non-discoverable and non-pairable after boot.
- A three-second test pairing window started its transient agent and then
  automatically closed pairing, discovery and the agent.
- Pilot Display reported Core online through the public liveness boundary and
  returned healthy energy and now-playing projections.
- Music Assistant played uniquely indexed local `Toto — Africa` FLAC through
  Sendspin at 20 percent, the K3 PipeWire stream became active, and playback was
  then stopped. This is transport evidence, not an audible human receipt.
- The controlled reboot returned every required service with zero restart
  failures and no failed system units.

## Open physical gates

1. Run a supervised K3 audible check and record a new audio-activation receipt.
2. Pair one named phone during `pilot-bluetooth-pair open`, confirm its address,
   explicitly trust it, and close the window.
3. Accept Bluetooth playback, ducking, restoration and switching against
   AirPlay and Sendspin.
4. Repair placeholder `PMEDIA` ISRC tags in affected third-party FLAC files and
   rescan Music Assistant; these tags currently merge unrelated tracks.

The prior unclean-shutdown journal and the earlier restart storm are retained as
diagnostic evidence. This deployment repaired the stale audio identity and no
post-reboot service restart loop remains.
