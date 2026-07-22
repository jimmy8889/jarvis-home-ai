# Pilot iOS and iPadOS

Pilot is a native SwiftUI client for Pilot Core. The current application
provides:

- an adaptive iPhone tab layout and iPad split-view layout;
- single-use pairing-grant onboarding and Keychain-backed device
  authentication, with manual existing-token setup retained as an advanced
  recovery path;
- connection validation before a configuration is accepted;
- the versioned device manifest, recoverable product snapshot and cursor-based
  event stream, with snapshot recovery after a cursor reset;
- room-centric curated home, energy, media, meeting and assistant surfaces;
- matching Flow, History, Daily and Climate monitoring with dynamic James House
  energy paths, Tesla and server-rack loads, daily totals, Amber tariffs,
  weather and five temperatures;
- typed Home Assistant controls, including explicit confirmation handling for
  actions that Core marks as sensitive;
- artwork-led Music Assistant search, artist/album/playlist drill-down,
  playback, previous/next, seek, mute, room transfer and volume control;
- Grid/Solar Tesla charging mode, Movie Mode On/Off and a `This iPhone`
  native Sendspin destination that continues playing while navigating the app
  or while the app is in the background;
- a compact generated Pilot identity and room selector, bundled energy artwork,
  animated power/rack presentation, and drag-selectable power, tariff and
  temperature history charts with exact timestamp/value inspection;
- compact and expanded now-playing presentation;
- room-selectable contextual Pilot conversations with structured cards,
  citations and action results;
- foreground auto-refresh and explicit loading, stale, offline, and error
  states;
- cached last-known media, home, energy and meeting state;
- an explicit-tap AAC meeting recorder whose retained upload queue survives a
  failed transfer and can be retried;
- accessibility labels, Dynamic Type support, haptics, fixtures and previews.

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

Use the dashboard's **Personal device** pairing profile. It creates a
short-lived, single-use grant and local QR with:

```text
home-read
home-control
meetings
voice
media-control
portable-client
```

`portable-client` is required because the app may explicitly target any
registered room. Redeem the pairing grant in the app; the resulting token is
written to the iOS Keychain and must not be committed to source control.

Legacy manually enrolled identities remain supported, but they do not gain new
capabilities automatically. Review their manifest or pair a fresh personal
identity instead of reusing the administrator token.

## Current boundary

Pilot Core remains authoritative for rooms, players, conversation policy, and
Music Assistant access. The app is a thin presentation and control surface.
The initial app permits HTTP only to support the existing private-LAN Core
deployment; port 8770 must not be exposed outside that network. A trusted HTTPS
origin is required before remote access is enabled.

Energy and monitoring are supplied by the device-scoped `pilot.energy.v1` and
`pilot.dashboard.v1` contracts. The app does not invent sensor values or
connect directly to Home Assistant. The mini-player is inset once above the
phone tab bar so it cannot obscure navigation and remains stable across tabs.

`This iPhone` uses the official SendspinKit client. Its stable player identity
is derived from the paired Pilot device ID, while playback commands travel
through `/v1/devices/{device_id}/media/local`. Pilot Core derives the matching
Music Assistant queue ID server-side and records the action; the app never
receives the Music Assistant token.

Pilot iOS now includes the first device-scoped meeting recorder and review
surface. It records AAC only after an explicit tap, supports iOS background
audio, uploads directly to Pilot Core, queues local processing, and shows
meeting status without holding Home Assistant or inference credentials.
Real-device long-recording acceptance is still required.

## Acceptance boundary

Source implementation and simulator tests/builds do not establish physical
product acceptance. Before calling this release operational on an iPhone or
iPad, verify:

1. one-time pairing, Keychain persistence, token rotation/revocation and app
   reinstall behavior;
2. actual iPhone and iPad layouts, Dynamic Type, VoiceOver and orientation;
3. media transfer, seeking, mute and confirmation-gated home actions against
   the production rooms, plus native `This iPhone` playback, background audio,
   interruption recovery and movement between phone and room outputs;
4. background/foreground event recovery and stale-cache behavior across a Core
   restart and Wi-Fi loss;
5. a long real meeting recording, retained failed upload, retry, processing and
   evidence review without data loss.

Production meeting transcription on the planned RTX 3080 remains deferred
until that GPU is installed and a private Whisper-compatible endpoint passes
the acceptance route. Recording and upload may be tested before then; a
missing transcription backend must fail closed rather than fabricate output.

The next client milestones are participant renaming, approved action export,
background push-to-talk, robust artwork caching, richer transfer gestures and
push notification delivery.
