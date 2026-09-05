# Hot-water controller firmware

The production device at `10.0.2.237` was migrated from ESPHome 2026.8.1 to the custom image on 2026-08-26. The ESP8285 hardware and GPIO mapping are unchanged.

The original ESPHome YAML was recovered from the operator on 2026-08-26 and is preserved verbatim in `rollback/hotwater-esphome.template.yaml`. It confirms the ESP8285 target, GPIO12 active-high relay, GPIO0 inverted pull-up button, static address and unauthenticated ESPHome API/OTA. The custom image preserves that physical mapping and debounced button behaviour, and adds authenticated HTTP state/command/confirmation endpoints, a controller lease and local latest-start fallback. A local button press temporarily owns the relay during a controller outage; the next valid manager lease cleanly reclaims authority. Firmware 0.2.4 uses monotonic lease expiry, three clock sources and manager-supplied UTC, avoiding unsafe expiry when NTP is slow after boot. The staged 0.2.5 source also batches LittleFS persistence to meaningful changes and 15-minute on-cycle checkpoints rather than writing every minute. Authenticated Arduino OTA uses the protected API token and forces the relay off before an update.

Use the protected `espota.py` copy in LXC 103 without debug output for future OTA uploads. Set its callback address explicitly to `10.0.1.205`; the IoT policy permits the reverse transfer to the manager LXC but rejected callbacks to the build host. PlatformIO's default debug uploader prints the authentication value and may advertise `0.0.0.0`, so it is not an approved production upload path.

## Production and rollback artifacts

Root-only artifacts live in `/var/lib/energy-manager/firmware/hot-water/2026-08-26/` inside LXC 103:

- custom 0.2.4: `2329be0e9094df608f9c3d760c6702458ac7a74b3a25f223d4da6cbacd22f0df`;
- exact ESPHome rollback: `6b22cad3c723fbb57ba20cf069dbb8605ac1760ab1c8f2d8aa88151cb75ba7d0`.

Both binaries are mode 0600. Superseded custom binaries and build caches containing the rotated credential were removed. Before any future flash, disable production control, confirm relay-off and zero element power, verify both checksums, and keep an operator available for immediate rollback. The rollback ESPHome image restores the original unauthenticated API/OTA behaviour, so it is recovery-only and should not remain deployed.

For an offline validation build, copy `rollback/secrets.example.yaml` to a temporary `secrets.yaml`. A production build must instead source the real values from protected files and must not leave them in the checkout, shell history or build log.
