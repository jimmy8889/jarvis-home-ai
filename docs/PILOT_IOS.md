# Pilot iOS

Pilot iOS is a native SwiftUI client for Pilot Core. The first release provides:

- room and current-player state;
- Music Assistant search and playback;
- play, pause, stop, and volume controls;
- room-selectable contextual Pilot conversations;
- Keychain-backed device authentication.

The app never connects directly to Home Assistant, Music Assistant, Ollama,
Denon, or room endpoints.

## Build

```bash
cd apps/pilot-ios
xcodegen generate
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild \
  -project Pilot.xcodeproj \
  -scheme Pilot \
  -sdk iphonesimulator \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

## Enrolment

Create a dedicated `pilot-ios-james` device in Pilot Core with:

```text
voice
media-control
portable-client
```

`portable-client` is required because the app may explicitly target any
registered room. The token belongs in the iOS Keychain and must not be committed
to source control.

## Current boundary

Pilot Core remains authoritative for rooms, players, conversation policy, and
Music Assistant access. The app is a thin presentation and control surface.
The initial app permits HTTP only to support the existing private-LAN Core
deployment; port 8770 must not be exposed outside that network. A trusted HTTPS
origin is required before remote access is enabled.
Background voice capture, meeting recording, artwork caching, transfer
gestures, and push notification delivery remain later milestones.
