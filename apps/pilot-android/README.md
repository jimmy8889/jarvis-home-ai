# Pilot Wall for Android

Pilot Wall is a native Kotlin/Jetpack Compose client for an always-powered,
permanently mounted Android tablet.

## Included in v0.1

- Adaptive tablet/phone navigation and a spacious 1024×600 wall layout.
- Home overview with freshness, rooms, active media and an animated
  solar/grid/battery/home energy-flow diagram.
- Room-aware media state and playback context.
- Music Assistant search, play/pause and a persistent now-playing mini-player.
- Contextual Pilot assistant chat with conversation continuity.
- Loading, offline, stale, empty and API-error states with last-state retention.
- Secure onboarding and device-token storage using Android Keystore AES-GCM.
- Automatic polling, an automatic night palette, keep-awake control and small
  periodic content offsets to reduce static-image wear.
- Accessible energy descriptions, large targets, Material typography, fixtures,
  Compose preview and parser/security unit tests.

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
| Media control | `POST /v1/devices/{id}/media` |
| Music search | `POST /v1/devices/{id}/media/search` |
| Assistant chat | `POST /v1/devices/{id}/assistant` |
| Energy and now playing | `GET /v1/devices/{id}/surface` |

The state endpoints are polled concurrently. Core's current device WebSocket is
a command transport for endpoint agents, not a general state subscription.

## Backend gaps for the next release

The app does not bypass Core when an API is absent. The full Home
Assistant-first wall experience still needs these Pilot Core contracts:

1. Device-scoped floors, areas, devices, entities, capabilities and sanitized
   live states.
2. Typed, policy-checked actions for lights, climate, covers and scenes.
3. A device-authorized state event WebSocket or resumable event cursor.
4. Music queue, artwork proxy, seek, mute, grouping and transfer APIs with
   stable typed results.
5. Historical energy series with quality/freshness metadata.
6. Assistant tool citations and structured action-result payloads.
7. A digital-twin manifest with stable room/object bindings.
