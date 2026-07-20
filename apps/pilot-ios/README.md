# Pilot iOS

Pilot iOS is a thin native client for Pilot Core. It never connects directly to
Home Assistant, Music Assistant, Ollama, Denon, or a room endpoint.

The polished v1 application provides:

- an adaptive phone `TabView` and iPad `NavigationSplitView`;
- a premium home surface with room availability, playback state, quick actions,
  explicit offline/stale handling, and a model-ready energy card;
- a persistent mini-player and full now-playing surface with room transfer,
  volume, play, pause, and stop controls;
- grouped Music Assistant search for tracks, albums, artists, playlists, radio,
  and other results, with artwork support where Pilot Core supplies it;
- a contextual Pilot conversation surface with room selection, continued
  sessions, suggestions, errors, loading feedback, and a new-session action;
- secure onboarding, Keychain-backed device credentials, connection testing,
  pull-to-refresh, and 20-second foreground refresh;
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

## Pending Pilot Core contracts

The UI intentionally identifies these as unavailable rather than bypassing
Pilot Core:

- a portable-client energy snapshot endpoint (the existing `/surface` contract
  requires a display-capable fixed device);
- queue, seek/progress, skip, favourites, and artwork-normalisation fields;
- a client-safe Home Assistant catalogue/room summary contract for generated
  controls and the future digital twin;
- a WebSocket/SSE client stream so foreground polling can become event-driven.
