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

## Current implementation status

The reusable software pieces are present, but an N150 media console has not
yet completed native-HDMI physical acceptance:

- the Linux display service supports `PILOT_DISPLAY_MODE=media-console`, opens
  on a dedicated ten-foot media home and presents artwork-led now-playing,
  progress, queue, music, house, local-video and Shield entry points;
- selected room/output state is retained locally without putting a Core or
  provider credential in browser storage;
- the loopback service proxies authenticated product snapshots and client
  events, including assistant-completion overlays;
- Room Agent has an allow-listed, supervised local mpv adapter for configured
  library roots with play, pause, resume, stop, bounded seek and audio/subtitle
  track selection;
- the Core video route resolves a room-bound video-capable endpoint and queues
  an expiring typed device command.

Those statements are source/test status, not proof of Intel video decode,
HDMI audio, CEC, HDR10, Denon switching or couch-distance usability on the
target hardware.

## Target display experience

The complete target shows time, room identity, energy, weather, alerts and
assistant state when idle. For music it shows artwork, metadata, progress,
queue, volume, grouping and handoff state from Music Assistant. For video it
provides a ten-foot library, continue watching, full-screen playback, seeking,
resume, subtitles, audio tracks and a clean return to the Pilot shell.

The current reusable shell implements the ten-foot media home, matching house
Flow/History/Daily/Climate pages, a TIDAL-inspired search/detail experience,
typed local-video controls, stale/offline state and assistant overlays.
Weather/alert composition is present through the shared dashboard contract; a
ten-foot Jellyfin library and unified video-session presentation remain target
work.

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

For this role the display-node Ansible variable is:

```yaml
display_node_mode: media-console
```

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

The implemented foundation exposes:

- media-console capabilities and health;
- room media state and typed Music Assistant controls;
- room-bound, expiring local-video commands for play, pause, resume, stop,
  bounded seek, subtitle track and audio track;
- local video process status through Room Agent;
- product/event snapshots for music progress, queue and assistant overlays.

Still required are a first-class selected playback-engine session, display
wake/sleep, richer video progress/terminal events, queue selection and
N150/Shield engine handoff.

Commands are allow-listed, expire, and remain room-bound. Arbitrary URLs,
filesystem paths, shell commands, and unvalidated mpv properties are rejected.

## Target iOS control

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
   command contract. **Source complete.**
2. Build the fullscreen shell with music, assistant-overlay, stale/offline, and
   recovery states. **Source complete in the reusable Linux display shell.**
3. Add Music Assistant now-playing, progress and queue presentation.
   **Source complete**, including artist/album/playlist drill-down; target
   display acceptance pending.
4. Add supervised mpv playback for a known-good local test library.
   **Software complete:** configured-root containment, extension allowlist,
   fixed mpv arguments, private JSON IPC, bounded seeking/track selection,
   process supervision and status are implemented. Hardware acceptance on a
   native-HDMI N150 remains pending.
5. Add Jellyfin browse, direct play, resume, subtitles, and audio tracks.
6. Add the iOS room remote using the same Pilot Core product and media APIs.
   **Core and client control paths are implemented; physical iOS acceptance is
   pending.**
7. Add HDMI/CEC/Denon source and power coordination.
   **Denon control contract exists; native-HDMI recovery remains pending.**
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

Until all of these checks pass on the selected N150, this role must be reported
as **built but awaiting hardware acceptance**, not deployed or operational.
Intel GPU/HDMI passthrough is not part of this design: the media-console target
is native Debian with direct hardware access.
