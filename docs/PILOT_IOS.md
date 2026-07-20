# Pilot iOS and iPadOS

Pilot is a native SwiftUI client for Pilot Core. The current application
provides:

- an adaptive iPhone tab layout and iPad split-view layout;
- secure onboarding and Keychain-backed device authentication;
- connection validation before a configuration is accepted;
- room-centric home, media, and assistant surfaces;
- grouped Music Assistant search, playback, transport, and volume control;
- compact and expanded now-playing presentation;
- room-selectable contextual Pilot conversations;
- foreground auto-refresh and explicit loading, stale, offline, and error
  states;
- accessibility labels, Dynamic Type support, haptics, fixtures, and previews.

The next major application surface is the Pilot Home Digital Twin: an
interactive 3D representation of the house with live room state and bounded
lighting, scene, climate, blind, media, occupancy, environmental, and later
confirmation-gated security controls. It shares its model and Pilot Core
contracts with the native Android wall-tablet client. See
[HOME_DIGITAL_TWIN.md](HOME_DIGITAL_TWIN.md).

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

The production `pilot-ios-james` identity is enrolled with exactly these three
capabilities. Its token is held in the central root-only secret store until the
app is installed on a physical device, at which point it must be transferred
directly into the app's Keychain-backed settings.

## Current boundary

Pilot Core remains authoritative for rooms, players, conversation policy, and
Music Assistant access. The app is a thin presentation and control surface.
The initial app permits HTTP only to support the existing private-LAN Core
deployment; port 8770 must not be exposed outside that network. A trusted HTTPS
origin is required before remote access is enabled.

The current energy presentation is deliberately readiness-oriented until a
portable-client energy contract is exposed by Pilot Core. The app does not
invent sensor values or connect directly to Home Assistant.

The next product milestones are the shared versioned house model and
interactive home controls, followed by background voice capture, meeting
recording, artwork caching, transfer gestures, and push notification delivery.
