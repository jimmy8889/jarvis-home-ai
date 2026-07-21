# Pilot iOS

Pilot iOS is a thin native client for Pilot Core. It never connects directly to
Home Assistant, Music Assistant, Ollama, Denon, or a room endpoint.

The polished v1 application provides:

- an adaptive phone `TabView` and iPad `NavigationSplitView`;
- a premium home surface with explainable Core-curated room controls, live energy,
  explicit offline/stale handling, and cached last-known state;
- a persistent mini-player and full now-playing surface with normalized artwork,
  queue/progress, seek, previous/next, mute, volume, and room transfer controls;
- grouped Music Assistant search for tracks, albums, artists, playlists, radio,
  and other results, with artwork support where Pilot Core supplies it;
- a contextual Pilot conversation surface with rich result cards, tool outcomes,
  citations, room selection, continued sessions, errors, and new-session actions;
- transactional onboarding: manually entered credentials are not activated or
  persisted until Core authenticates them, while single-use bootstrap grants can
  be pasted or scanned as QR codes;
- Keychain-backed credentials, cached product state, pull-to-refresh, and
  resumable long-poll events with cursor-based snapshot recovery;
- durable meeting recording handoff: files live in Application Support and are
  only removed after Core accepts both upload and processing, with persisted
  retry state for every failure path;
- Dynamic Type-compatible layouts, VoiceOver labels, large touch targets,
  haptics, empty states, skeleton loading, mocks, and iPhone/iPad previews.

All media, assistant, room, and future home-state requests continue to flow
through device-scoped Pilot Core APIs. The app does not call Home Assistant or
Music Assistant directly.

The deployment target is iOS 17 so the same client can run on the currently
available iPad as well as newer iPhone and iPad devices.

Generate the Xcode project reproducibly:

```bash
cd apps/pilot-ios
xcodegen generate
```

Register `pilot-ios-james` with the `voice`, `media-control`, and
`portable-client` capabilities before configuring the application.

The current build permits clear-text transport because the deployed Pilot Core
address is a trusted private-LAN IP. Do not expose port 8770 outside the trusted
network. Replace this allowance with a pinned HTTPS origin before supporting
remote access.

## Pilot Core contract

The client consumes the device-scoped `pilot.client.v1` product contract:

- `/manifest` for features and authorized endpoint discovery;
- `/events/snapshot` plus resumable `/events` long polling;
- `/energy`, `/home`, `/media`, `/assistant`, and `/meetings` projections;
- explainable entity presentation metadata and normalized media state.

The app retains bounded compatibility fallbacks while updated Core is deployed.
Physical iPhone/iPad acceptance is still required for camera pairing, background
recording interruptions, retained-upload retry, Dynamic Type, VoiceOver, and
LAN reconnect behavior.
