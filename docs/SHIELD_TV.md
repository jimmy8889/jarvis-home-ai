# Pilot TV for NVIDIA Shield

Pilot TV is the television-facing Pilot client under `apps/shield-tv`. It is a
native Kotlin and Compose for TV application. The Shield remains the playback
engine for Dolby Vision, DRM and commercial streaming; Pilot TV supplies the
local media-room interface and sends only typed commands to Pilot Core.

## Implemented in the current source release

- One-time device pairing through `POST /v1/devices/bootstrap`.
- A narrowly scoped device credential encrypted with Android Keystore
  AES-GCM. The Core administrator token and Home Assistant/Music Assistant
  credentials are never entered into or stored by the app.
- Device-manifest discovery and device-authenticated product, media, energy
  and curated room projections.
- A D-pad-oriented ten-foot interface with now playing, artwork or a safe
  placeholder, progress, queue, room outputs, energy, curated room glance and
  diagnostics.
- Permission-aware play, pause, stop, previous, next, seek, mute, volume and
  room-transfer commands through `/v1/devices/{device_id}/media`.
- Launch buttons for the installed Jellyfin Android TV and Kodi applications.
- Explicit unpairing and device-credential rotation.
- Private-LAN address validation, redirect denial and stale/offline states.

Pilot TV does not receive arbitrary media URLs, filesystem access, shell
access, raw Home Assistant services or an unbounded Denon command surface.
Jellyfin and Kodi continue to own video playback. Launching an application is
not the same as a guaranteed title-level deep link; that remains provider and
application dependent.

## Authentication and network boundary

Pairing starts in the administrator dashboard. The administrator selects a
room and a limited TV profile, then creates a short-lived, single-use grant.
The dashboard renders the grant as a local QR for camera-equipped clients and
also exposes the raw code for Shield remote-keyboard entry.
Pilot TV redeems that grant once and stores only the returned device ID and
device token. Rotation invalidates the prior token; revocation by an
administrator immediately denies subsequent requests.

HTTPS is accepted for valid hosts. Cleartext HTTP is accepted only for
localhost, `.local` names and RFC1918 IPv4 addresses because the current Core
is private-LAN only. A trusted HTTPS reverse proxy is required before exposing
Pilot beyond that network.

## Product contract

The app uses the versioned Core contract rather than `/v1/operations`:

```text
GET  /v1/devices/{id}/manifest
GET  /v1/devices/{id}/events/snapshot?cursor=...
GET  /v1/devices/{id}/media
GET  /v1/devices/{id}/energy
GET  /v1/devices/{id}/home?room_id=...
POST /v1/devices/{id}/media
POST /v1/devices/{id}/credentials/rotate-self
```

The manifest advertises the permitted features and endpoints. Controls must
also respect the per-player `control_enabled` and action list returned by
Core; the UI does not infer authority from a visible player.

## Build and acceptance

The project pins its Gradle wrapper and Android toolchain. Build with:

```bash
cd apps/shield-tv
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The debug APK is written to
`apps/shield-tv/app/build/outputs/apk/debug/app-debug.apk`.

Source implementation and focused parser/address-policy tests are present.
The release is not physically accepted until the APK has been installed on the
actual Shield and the following have been observed:

1. pairing, process restart, rotation and revocation;
2. D-pad focus order and readable 10-foot layout at the installed TV mode;
3. accepted Denon/HEOS music control with safe volume behavior;
4. Jellyfin and Kodi launch and return-to-Pilot behavior;
5. stale/offline recovery after Core and network interruption;
6. continued Dolby Vision and commercial playback in the specialized Shield
   applications.

## Next Shield work

- consume the resumable event stream for immediate assistant and media
  overlays instead of relying only on refresh;
- add validated content-level Jellyfin/Kodi deep links where their installed
  versions expose a stable contract;
- add explicitly permissioned camera and alert cards;
- complete physical focus, overscan, HDR-mode and Denon handoff acceptance.
