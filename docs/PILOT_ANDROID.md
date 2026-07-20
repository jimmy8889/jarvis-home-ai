# Pilot Android

Pilot Android is the native Jetpack Compose client for the permanently mounted
wall tablet. It is deliberately a Pilot Core client, not a Home Assistant or
Music Assistant client.

## Current surface

- Tablet-first adaptive navigation with room, energy, music, and assistant
  views.
- Secure enrolment against Pilot Core.
- Device tokens encrypted at rest with an Android Keystore AES-GCM key.
- Live room and now-playing state.
- Music Assistant search, playback, transport, and volume control through
  Pilot Core.
- Contextual assistant conversations scoped to the selected room.
- Animated solar, grid, battery, and home energy flow.
- Night-friendly palette, optional keep-awake behavior, and subtle burn-in
  offset movement.
- Explicit loading, stale, offline, and error states.
- Preview fixtures, accessibility semantics, and protocol/security unit tests.

The client never receives Home Assistant, Music Assistant, Ollama, Denon, or
room-agent credentials.

## Build

The local machine needs Android Studio or an Android SDK with
`ANDROID_HOME`/`sdk.dir` configured:

```bash
cd apps/pilot-android
./gradlew testDebugUnitTest lintDebug assembleDebug
```

The repository CI installs a known Android SDK and runs the same compile,
test, lint, and assembly gates.

## Enrolment

Create a dedicated tablet device with:

```text
display
media-control
portable-client
voice
```

Use `portable-client` while the wall tablet is intended to control multiple
rooms. A future fixed-room deployment may remove that capability and rely on a
room-bound identity. Transfer the one-time token directly into the enrolment
screen; never store it in source control or a mobile deployment profile.

## Appliance boundary

The app is kiosk-ready but does not silently assume Android device-owner
privileges. Production hardening still requires physical acceptance on the
target tablet:

1. confirm touch targets, brightness, orientation, and energy animation;
2. configure Android lock-task or the chosen managed-launcher policy;
3. validate boot-to-app and recovery access;
4. validate Wi-Fi loss, Pilot Core restart, and token revocation;
5. set display timeout and burn-in policy appropriate to the actual panel.

## Digital twin

The current room controls are the foundation for the shared Pilot Home Digital
Twin. The full interactive 3D house requires a versioned geometry and entity
mapping contract from Pilot Core so iOS/iPadOS and Android render the same
model and invoke the same typed actions. See
[HOME_DIGITAL_TWIN.md](HOME_DIGITAL_TWIN.md).
