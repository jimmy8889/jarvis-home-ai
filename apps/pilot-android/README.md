# Pilot Wall for Android

Pilot Wall is a native Kotlin/Jetpack Compose client for an always-powered,
permanently mounted Android tablet.

## Product capabilities

- Adaptive tablet/phone navigation and a spacious 1024×600 wall layout.
- Continuous Flow, History, Daily and Climate monitoring with the shared James
  House scene, directional solar/grid/battery/Tesla/server-rack paths, daily
  totals, 24-hour chart, Amber pricing, weather and five room temperatures.
- Bedroom music is intentionally hidden. The mounted tablet is a home monitor
  and controller, not a playback endpoint.
- Server-curated Home Assistant presentation with purpose-built lighting,
  climate, cover, fan, lock, scene, switch, sensor and contact tiles. Core's
  inclusion policy, canonical IDs, duplicate suppression, display names,
  sections, priorities and room trust are honored when supplied.
- Music Assistant search plus artwork, progress, queue, seek, transport,
  volume, mute, grouping and room-transfer presentation. Controls are shown
  only when the player advertises the corresponding capability, with the
  legacy play/pause/stop/volume/transfer contract retained.
- Contextual Pilot assistant chat and microphone capture. Talk to Pilot sends
  signed 16-bit 16 kHz mono PCM directly to the device-scoped Core voice API,
  renders structured cards/sources and plays Core-generated TTS locally.
- Loading, offline, stale, empty and API-error states with last-state retention.
- Single-use grant pairing via pasted codes or `pilot://pair` QR/deep links,
  with manual device-token entry retained behind an advanced disclosure.
- Secure device-token storage using Android Keystore AES-GCM.
- Reconnect-safe event snapshots and cursor-based long polling when advertised
  by Core, with periodic polling retained as a heartbeat/fallback.
- Automatic day/night palette, kiosk system-bar behavior and keep-awake control.
  After 45 seconds without interaction brightness drops to 3%; the first touch
  restores it immediately. The dashboard remains visible rather than entering
  an ambient screensaver.
- Accessible descriptions, large touch targets, adaptive 1024×600 layouts,
  canonical contract fixtures, Compose previews and screenshot-test scaffolding.

## Authority and security

The app speaks only to Pilot Core:

```text
Android tablet → Pilot Core → Home Assistant / Music Assistant
```

Every request carries the dedicated device token and `X-Pilot-Device-ID`.
Home Assistant and Music Assistant credentials are never accepted by the app.
Register the tablet with:

```json
["display", "media-control", "portable-client", "voice"]
```

`portable-client` permits selecting rooms other than the tablet's registered
room. The onboarding token is encrypted at rest and is not written to logs or
Gradle files.

Cleartext HTTP is accepted by the enforced client address policy only for
private/loopback addresses. Public Core endpoints must use HTTPS.

## Build and test

Requirements are JDK 17 and Android SDK 37.

```bash
cd apps/pilot-android
./gradlew testDebugUnitTest assembleDebug
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`. The
Gradle wrapper and dependency versions are included for reproducible CI builds.

## Pilot Core API used

| Feature | Device-scoped endpoint |
|---|---|
| Rooms and media state | `GET /v1/devices/{id}/media` |
| Shared monitoring | `GET /v1/devices/{id}/dashboard` |
| Tesla and Movie Mode | `POST /v1/devices/{id}/dashboard/actions` |
| Media control | `POST /v1/devices/{id}/media` |
| Music search | `POST /v1/devices/{id}/media/search` |
| Music item detail | `POST /v1/devices/{id}/media/browse` |
| Assistant chat | `POST /v1/devices/{id}/assistant` |
| Energy and now playing | `GET /v1/devices/{id}/surface` |
| Client manifest | `GET /v1/devices/{id}/manifest` |
| Reconnect snapshot | `GET /v1/devices/{id}/events/snapshot?cursor=` |
| Event long poll | `GET /v1/devices/{id}/events?cursor=&timeout_seconds=25` |
| Talk to Pilot | `POST /v1/devices/{id}/voice` |
| Single-use enrollment | `POST /v1/devices/bootstrap` |

The manifest advertises feature and endpoint availability. The client tolerates
older Core versions by decoding richer fields optionally and falling back to
the existing concurrent media/surface polling path.

## Physical acceptance still required

Compilation and JVM contract tests do not prove the mounted-tablet experience.
Before calling the wall appliance accepted, validate on the target hardware:

1. QR/deep-link pairing and credential rotation/revocation.
2. Kiosk recovery after reboot and Wi-Fi/Core outages.
3. Microphone permission, capture quality and TTS speaker routing.
4. Night brightness, ambient timeout and burn-in movement.
5. Touch targeting and layout on both the mounted panel and 1024×600 Pi-class
   display geometry.
6. Real Music Assistant artwork/queue/group capability payloads and authenticated
   artwork-proxy behavior.
