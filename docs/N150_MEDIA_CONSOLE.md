# N150 Media Console

The N150 Media Console is the display-capable room role for an N150 connected
to a television, monitor, Denon receiver, or other media-centre display. It
extends the existing room endpoint and does not create a separate source of
truth for rooms, queues, permissions, or media state.

## Product boundary

```text
iOS / TV remote / room microphone
                 |
                 v
             Pilot Core
       room, session, permission,
       queue and command authority
                 |
       authenticated device channel
                 |
                 v
        N150 Media Console
  +--------------------------------+
  | Pilot fullscreen shell         |
  | Music presentation             |
  | mpv local-video engine         |
  | Jellyfin/Kodi launcher bridge  |
  | Assistant visual overlay       |
  | Room Agent + audio focus       |
  | HDMI audio/video output        |
  +--------------------------------+
                 |
                 v
       Denon / display / speakers
```

The N150 owns local presentation, hardware acceleration, HDMI state, and
playback-process supervision. Pilot Core owns authentication, room selection,
media-session state, command authorization, audit history, and cross-room
orchestration. iOS clients control the room through Pilot Core and never need
direct SSH, mpv IPC, Denon, Music Assistant, or filesystem access.

## Display experience

When idle, the console shows time, room identity, energy, weather, alerts, and
assistant state. For music it shows artwork, metadata, progress, queue, volume,
grouping, and handoff state from Music Assistant. For video it provides a
ten-foot library, continue watching, full-screen playback, seeking, resume,
subtitles, audio tracks, and a clean return to the Pilot shell.

The shell returns automatically after playback exits or crashes. A failure
cannot leave a desktop, terminal, or administrator interface visible.

## Linux runtime

The target is native Debian with direct Intel graphics and HDMI access:

- a minimal multi-window Wayland session;
- a local HTML/CSS Pilot shell in fullscreen Chromium;
- mpv with hardware decoding and a private JSON IPC socket;
- Room Agent for audio focus, voice, source state, and device commands;
- Sendspin for Music Assistant playback;
- PipeWire/WirePlumber for music, assistant, announcements, Bluetooth,
  AirPlay, and HDMI audio;
- systemd supervision, immutable releases, health checks, and rollback.

A local media-agent service validates Pilot commands and translates them into
mpv, display, CEC, and launcher operations. The browser never receives a Pilot
administrator token or direct access to mpv IPC.

## Video boundary

The N150 is intended for local SDR/HDR10 video, dashboards, music presentation,
and general playback where the tested Intel/Linux HDMI path supports the
format. The NVIDIA Shield remains responsible for Dolby Vision, DRM,
commercial streaming, and specialized Android TV applications.

```text
Local/Jellyfin video suitable for N150 -> N150 mpv
Dolby Vision or commercial streaming  -> NVIDIA Shield
Music / AirPlay / Bluetooth           -> N150 audio stack
```

## Pilot Core interfaces

The milestone adds device-bound interfaces for:

- media-console capabilities and health;
- current room media session and selected playback engine;
- open, play, pause, stop, seek, skip, resume, and queue selection;
- subtitle and audio-track selection;
- display wake/sleep and visual-surface selection;
- assistant overlays and notifications;
- playback progress and terminal-state events;
- room handoff and N150/Shield engine handoff.

Commands are allow-listed, expire, and remain room-bound. Arbitrary URLs,
filesystem paths, shell commands, and unvalidated mpv properties are rejected.

## iOS control

The iOS Pilot client will provide:

- room and playback-engine selection;
- now playing, queue, seeking, play/pause/skip, and volume;
- Music Assistant search for TIDAL and local music;
- Jellyfin library, search, continue watching, and resume;
- N150 or Shield selection when more than one engine is appropriate;
- remote text entry, subtitles, and audio-track selection;
- assistant push-to-talk and visual responses;
- room handoff and multi-room music grouping.

The app uses device/user pairing with Pilot Core. It does not store the
administrator token or communicate directly with the N150.

## Delivery order

1. Build the media-console agent, capability, health model, and authenticated
   command contract. **Complete in Room Agent 0.6 / Core 0.22.**
2. Build the fullscreen shell with idle, music, assistant-overlay, offline, and
   recovery states.
3. Add Sendspin now-playing and queue presentation.
4. Add supervised mpv playback for a known-good local test library.
   **Software complete:** configured-root containment, extension allowlist,
   fixed mpv arguments, private JSON IPC, bounded seeking/track selection,
   process supervision and status are implemented. Hardware acceptance on a
   native-HDMI N150 remains pending.
5. Add Jellyfin browse, direct play, resume, subtitles, and audio tracks.
6. Add the iOS room remote using the same Pilot Core session APIs.
7. Add HDMI/CEC/Denon source and power coordination.
8. Test HDR10, HD-audio passthrough, suspend, reboot recovery, and rollback.
9. Add N150/Shield engine selection and handoff while retaining Shield for
   Dolby Vision and DRM services.

## Acceptance

The milestone is complete when:

- the N150 boots directly into Pilot without exposing a desktop;
- music presentation follows the authoritative Music Assistant queue;
- an iOS client controls the selected room through Pilot Core;
- a Jellyfin video starts, seeks, resumes, and exits back to the shell;
- assistant overlays preserve the current music or video session;
- Denon/display power and input recover after reboot;
- invalid, expired, cross-room, and arbitrary-path commands fail closed;
- the current and previous immutable releases can be selected remotely.
