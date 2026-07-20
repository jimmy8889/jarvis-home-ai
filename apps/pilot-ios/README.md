# Pilot iOS

Pilot iOS is a thin native client for Pilot Core. It never connects directly to
Home Assistant, Music Assistant, Ollama, Denon, or a room endpoint.

The initial application provides:

- room and now-playing state;
- Music Assistant search and playback through Pilot Core;
- play, pause, stop, and volume controls;
- room-selectable Pilot conversations with retained session continuity;
- a Keychain-backed device credential.

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
