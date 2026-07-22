# Pilot Android

Pilot Android is the native Jetpack Compose client for the permanently mounted
wall tablet. It is deliberately a Pilot Core client, not a Home Assistant or
Music Assistant client.

## Current surface

- Tablet-first adaptive navigation whose primary always-visible surface is the
  shared Flow, History, Daily and Climate dashboard.
- One-time pairing-grant enrolment, including `pilot://pair` deep-link input and
  an advanced existing-token recovery path.
- Device tokens encrypted at rest with an Android Keystore AES-GCM key.
- Device-manifest discovery and resumable cursor-based event polling with
  snapshot recovery.
- Live room state. Bedroom music and music navigation are intentionally absent
  because the mounted wall panel is not a playback endpoint.
- Curated room controls that render Core's presentation metadata and invoke
  only returned supported actions; confirmation-gated actions remain explicit.
- Text and push-to-talk assistant conversations scoped to the selected room,
  including 16 kHz mono capture, structured cards/sources, response audio and
  listening/processing/speaking states.
- Watt-scaled directional solar, grid, battery, Tesla, home and server-rack
  energy flow; a 100 W grid deadband; 24-hour power history; daily totals;
  Amber prices; weather; and five room temperatures.
- Night-friendly palette and optional keep-awake behavior. After 45 seconds of
  inactivity the window dims to 3%; the next touch restores it immediately.
  There is no separate ambient/screensaver page.
- Explicit loading, stale, offline, and error states.
- Preview fixtures, an instrumentation screenshot scaffold, accessibility
  semantics and protocol/security unit tests.

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

Use the dashboard's **Wall panel** profile. It creates a short-lived,
single-use grant and local scan-to-pair QR with:

```text
display
home-read
home-control
media-control
voice
```

That default identity is fixed to the selected room. If the wall tablet is
intentionally permitted to control multiple rooms, create a reviewed custom
grant that also includes `portable-client`; do not add it merely to work around
an incorrect room mapping. Redeem the grant directly in the app and never
store the resulting token in source control or a mobile deployment profile.

## Appliance boundary

The app is kiosk-ready but does not silently assume Android device-owner
privileges. Production hardening still requires physical acceptance on the
target tablet:

1. confirm touch targets, 45-second dim/tap wake, orientation, and every energy
   direction at real loads;
2. configure Android lock-task or the chosen managed-launcher policy;
3. validate boot-to-app and recovery access;
4. validate Wi-Fi loss, Pilot Core restart, and token revocation;
5. set display timeout and burn-in policy appropriate to the actual panel.

Also verify microphone permission denial/recovery, real response-audio
playback, event reconnect after Core restart, and rejection after credential
revocation. The source implementation and CI build are **not** substitutes for
these checks on the mounted tablet.

## Digital twin

The current room controls are the foundation for the shared Pilot Home Digital
Twin. The full interactive 3D house requires a versioned geometry and entity
mapping contract from Pilot Core so iOS/iPadOS and Android render the same
model and invoke the same typed actions. See
[HOME_DIGITAL_TWIN.md](HOME_DIGITAL_TWIN.md).

No production 3D house asset or geometry contract is claimed by this release.
The polished 2D room controls are the accepted product surface until the house
model, mappings, accessibility alternative and performance budget are real.
