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
- room-selectable typed and spoken Pilot conversations with structured cards,
  citations and action results. The voice surface includes a live
  microphone-responsive aura, speech-aware automatic submission, local
  STT/reasoning/TTS, authenticated reply audio, cancellation and retry;
- foreground auto-refresh and explicit loading, stale, offline, and error
  states;
- cached last-known media, home, energy and meeting state;
- an explicit-tap AAC meeting recorder whose retained upload queue survives a
  failed transfer and can be retried;
- a watchOS 10 meeting companion that records without taking out the iPhone,
  durably relays through the paired phone, and deletes neither client copy
  until Pilot Core accepts upload and processing;
- accessibility labels, Dynamic Type support, haptics, fixtures and previews.

The microphone path records 16 kHz signed 16-bit mono PCM and stops after 45
seconds (1,440,000 PCM bytes). Pilot Core accepts a strictly bounded
1,600,000-byte voice request so the longest valid utterance fits without
opening an unbounded upload path.

The next major application surface is the Pilot Home Digital Twin: an
interactive 3D representation of the house with live room state and bounded
lighting, scene, climate, blind, media, occupancy, environmental, and later
confirmation-gated security controls. It shares its model and Pilot Core
contracts with the native Android wall-tablet client. See
[HOME_DIGITAL_TWIN.md](HOME_DIGITAL_TWIN.md).

The app never receives Home Assistant, Music Assistant API, Ollama, Denon, or
room-endpoint credentials. Native phone audio makes one direct LAN WebSocket
connection to Music Assistant's Sendspin endpoint; every playback command and
queue mutation still travels through authenticated Pilot Core.

## Build

```bash
cd apps/pilot-ios
xcodegen generate
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  xcodebuild \
  -project Pilot.xcodeproj \
  -scheme Pilot \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Do not pass a global `-sdk iphonesimulator` override. The `Pilot` scheme embeds
the watchOS companion, and Xcode must select the iOS Simulator and watchOS
Simulator SDKs for their respective targets.

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

The paired identity also requires `voice` for `/voice` and reply-audio access,
and `home-control` for governed light or other entity mutations. Pilot sends
the selected room as `X-Pilot-Room-ID`; Core accepts that header only from a
portable device and continues to isolate fixed-room sessions and audio.

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
connect directly to Home Assistant. Pilot Core reads the standalone energy
manager directly: `/api/v1/snapshot` and `/api/v1/plan` supply live state and
planning, `/api/v1/daily` supplies authoritative Brisbane-day totals, and the
durable five-minute `/api/v1/series` journal supplies chart history. Home
Assistant can still contribute unrelated dashboard context, but it is not the
source for Pilot's energy values, daily totals, or history.

Live power mirrors the standalone dashboard's canonical `power_flow` graph:
`sources_kw`, `sinks_kw`, `site_load_kw`, `submeters_kw`, and graph edges own
the values, signs, and active paths. Raw inverter telemetry is used only when a
legacy manager snapshot has no flow graph. Today's three summary totals come
from the snapshot `daily_energy` object used by the standalone dashboard, with
the journal-backed `/api/v1/daily` row retained only as a fallback.

Pilot refreshes `/energy` and `/dashboard` every five seconds while its update
loop is connected. Core's resumable event stream remains responsible for
event-driven product changes, but energy correctness does not depend on an
energy event being emitted for every power sample.

The phone uses a dedicated bottom control
surface: the mini-player is a separate row above Pilot's navigation buttons,
so neither can overlap the other and both remain stable across screens. The
compact shell does not instantiate a system `TabView`; Pilot's own bar is the
only bottom navigation surface. The bundled Pilot mark is used in navigation
identity and the application icon.

`This iPhone` uses the official SendspinKit client. Its stable player identity
is derived from the paired Pilot device ID, while playback commands travel
through `/v1/devices/{device_id}/media/local`. Pilot Core derives the matching
Music Assistant output ID server-side, resolves any Universal Player wrapper
published for that Sendspin transport, and records the action; the app never
receives the Music Assistant token or chooses an arbitrary queue. The default endpoint is
`ws://10.0.2.72:8927/sendspin`; older installs that stored the port-8095 web UI
address are migrated automatically. Connection failures remain visible in the
Music screen with an explicit retry action.

When native phone audio has media, Pilot publishes title, artist, album,
artwork, duration, elapsed time and playback rate to iOS Now Playing. The lock
screen and Control Center expose play/pause, stop, previous, next and timeline
seeking. Those controls do not hold a Music Assistant credential or directly
control another room: they return through the paired device's authenticated
`/media/local` boundary. Pilot clears the system Now Playing session when the
Sendspin client disconnects.

Pilot iOS includes a device-scoped meeting recorder and review surface. It
records AAC only after an explicit tap, supports iOS background audio, uploads
directly to Pilot Core, queues local processing, and shows meeting status
without holding Home Assistant or inference credentials. Its watchOS 10
companion uses the same Core route through the paired iPhone: the Watch owns no
Core credential, both devices retain durable audio during delivery, and the
Watch deletes only after Core accepts upload and processing. Reusable device
authentication remains on the paired Core origin; an advertised off-origin
uploader receives only a short-lived ticket bound to that recording. See
[PILOT_WATCH_MEETINGS.md](PILOT_WATCH_MEETINGS.md) for the state contract and
physical acceptance plan.

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
6. Watch meeting capture with the display down, locked-phone background
   handoff, phone-out-of-range recovery, interruption handling, duplicate
   delivery, reinstall/resend, and a live `core_accepted` round trip;
7. phone voice capture in quiet and noisy rooms, automatic end-of-speech,
   cancellation, TTS playback and music-session restoration; then exercise
   light on/off, brightness and colour in each curated room and confirm the
   resulting Home Assistant state and Pilot audit entry.

Production meeting transcription on the planned RTX 3080 remains deferred
until that GPU is installed and a private Whisper-compatible endpoint passes
the acceptance route. Recording and upload may be tested before then; a
missing transcription backend must fail closed rather than fabricate output.

The next client milestones are participant renaming, approved action export,
background push-to-talk, robust artwork caching, richer transfer gestures and
push notification delivery.
