# Changelog

## 0.28.1 — 2026-07-23

- Fixed native iPhone playback against Music Assistant's Universal Player
  provider. Pilot Core now resolves the authenticated phone's derived Sendspin
  output ID through `output_protocols` and targets the published controllable
  queue, with bounded registration retries and no client-supplied player ID.
- Removed the residual system `TabView` from the compact iPhone shell. Pilot's
  single custom navigation bar is now the only bottom navigation surface.
- Integrated the generated Pilot mark into the navigation title and added a
  reproducible, opaque 1024-pixel branded application icon.

## 0.28.0 — 2026-07-23

- Corrected native iPhone playback to use Music Assistant's Sendspin port 8927
  instead of deriving a WebSocket on the port-8095 web UI. Added legacy-setting
  migration, registration readiness, reconnect recovery, visible failure/retry
  state and endpoint tests.
- Replaced the system tab-bar inset with dedicated Pilot bottom chrome. The
  mini-player now occupies its own row above navigation, never covers a tab,
  and remains hidden when there is no meaningful now-playing state.
- Replaced the embedded Music Assistant browser handoff on iPhone with an
  in-app, background-capable Sendspin player. `This iPhone` is now a normal
  destination in Pilot's music interface, keeps playing across tabs and uses a
  Core-derived device queue instead of exposing Music Assistant credentials.
- Added the authenticated device-local media command route and audit event so
  play, pause, stop, seek, volume, mute and media selection remain within the
  same scoped Pilot Core control boundary as room playback.
- Rebuilt the iPhone energy surface with bundled day/night/Tesla assets,
  power-scaled travelling pulses, a brighter generated server rack and animated
  LEDs. Added a generated Pilot product mark and compressed the home header and
  room selector to reclaim vertical space.
- Added drag-selectable 24-hour power, Amber feed-in and room-temperature
  charts with exact timestamp/value readouts. Pilot Core now includes bounded
  temperature histories and accepts the Home Assistant Amber forecast shapes
  used by the production sensor.
- Fixed the Xcode project resource phase so all dashboard artwork is compiled
  into the app. Added a simulator regression test that loads every required
  house, rack and logo asset from the built bundle.
- Made the iOS CI matrix compile SendspinKit 1.0.1 in its supported Swift 5
  language mode, avoiding Xcode 16.4/iOS 18.5 actor-isolation errors while
  retaining successful Xcode 26 builds and the same runtime binary contract.
- Promoted commit `a1b9fc5c` as immutable Pilot Core image
  `core-0.28.0-20260723.1` after creating a cold integrity-manifested backup.
  Readiness plus Home Assistant, Music Assistant and TTS diagnostics passed;
  real iPhone playback and chart interaction remain physical acceptance items.

## 0.27.1 — 2026-07-22

- Fixed Home Assistant `minimal_response` history parsing so all states in each
  requested series retain their entity identity. The 24-hour Home, Battery and
  Solar graphs now receive their complete bounded series instead of a single
  first point; malformed or cross-entity responses fail closed.
- Added the missing Linux junction-to-Home flow leg, making Battery-to-Home
  discharge explicit on the Pi and N150 as it already was on Android and iOS.
- Added a Raspberry Pi rendering profile that keeps directional power motion,
  battery state and rack LEDs while using solid SVG strokes, a bounded 10 Hz
  dash repaint rate, and no hidden-page or reduced-motion animation.
- Fixed Android display policy so the selected idle timeout is authoritative,
  added a persisted 5–100 percent brightness control with first-touch wake, and
  disabled continuous visual loops when system animations are off.

## 0.27.0 — 2026-07-22

- Rebuilt the shared energy scene around four bundled day/night and
  Tesla-present/absent house states. Pilot Core now projects an optional,
  bounded `sun.sun` scene signal so displays do not mistake an overcast day for
  night; clients retain a solar-production fallback while older Core versions
  remain in service.
- Standardized Tesla presentation across clients: connection controls whether
  the car is parked in the scene, while charging power and animation remain
  suppressed below 100 W. A plugged-in idle vehicle therefore never appears as
  a misleading `1.6 W` load.
- Replaced mechanical dashed motion with rounded, power-scaled travelling glow
  pulses, added the missing directional home-battery route and truthful SOC
  animation, and introduced a shared transparent server-rack illustration with
  independently animated native status LEDs.
- Advanced the Android wall dashboard to 0.3 with entirely local scene assets
  and motion-aware animation. Advanced Pilot Linux Display with fixed-room
  output resolution, stable now-playing arbitration, QWERTY touch input and a
  dedicated N150 media-console presentation.
- Added threshold, scene, asset, output-routing and stale-update regression
  coverage. Physical Pi touch/audio and N150 HDMI/video acceptance remain
  separate from source completion.

## 0.26.0 — 2026-07-22

- Added the shared `pilot.dashboard.v1` monitoring contract for iOS, Android
  wall tablets and Linux displays. It projects live solar, grid, battery,
  whole-home, Tesla and server-rack power; daily energy totals; 24-hour chart
  series; Amber prices; weather and five room temperatures without exposing a
  Home Assistant credential to any client.
- Added scalable, directional energy animation with a 100 W grid-flow deadband,
  explicit battery charge/discharge motion, Tesla connected/charging state and
  a dedicated server-rack branch. The supplied James House artwork is packaged
  locally so every display retains the same visual identity when offline.
- Added typed dashboard actions for Grid/Solar Tesla charging mode and Movie
  Mode On/Off. Successful actions invalidate the ten-second dashboard cache;
  concurrent displays otherwise share one bounded Home Assistant projection.
- Rebuilt Pilot Wall around continuous Flow, History, Daily and Climate pages,
  removed bedroom music, and added touch-to-wake dimming without an ambient
  screensaver.
- Added matching native iPhone/iPad monitoring surfaces, fixed the phone
  mini-player safe-area overlap, added a phone-output Music Assistant web-player
  handoff, Media Room mode, Amber price presentation, Tesla controls, weather
  and room temperatures.
- Expanded Music Assistant discovery into artwork-led artist, album, playlist
  and song surfaces. Artist pages expose albums and songs; album and playlist
  pages expose their tracks through device-scoped Pilot Core APIs.
- Upgraded the 10-inch Raspberry Pi surface with the shared monitoring pages,
  touch keyboard and optional pinned Sendspin player for a future USB DAC. The
  player is installed but remains disabled until the physical DAC is attached
  and its stable PipeWire sink is accepted.
- Added the N150 media-console ten-foot home, music, local-video and Shield
  launch surface plus reproducible Debian 13 x86-64 provisioning. Native HDMI,
  Denon input recovery, video decode and couch-distance usability remain
  hardware acceptance items.
- Promoted Pilot Core 0.26.0 as immutable image
  `core-0.26.0-20260722.2` at commit `795cb7a8` after two verified cold backups.
  The guarded diagnostic caught and corrected a disabled-Bedroom read-path
  regression before acceptance; the final image passed whole-home state,
  provider diagnostics and the live dashboard contract with no missing
  entities. Pilot Linux Display 0.5 was deployed as a rollback-paired release;
  its staged Sendspin service remains disabled pending the USB DAC.

## 0.25.0 — 2026-07-22

- Added the versioned Pilot client product contract: the device-scoped
  `pilot.client.v1` manifest, recoverable `pilot.snapshot.v1` product snapshot,
  `pilot.*.v1` client events, cursor-based long polling and an authenticated
  resumable WebSocket stream. Added JSON Schemas and representative fixtures.
- Added persistent, explainable Home Assistant presentation policy. Automatic,
  include and exclude decisions now carry reasons, category, priority, section,
  semantic control, supported actions, canonical/duplicate identity and room
  trust. Registry and explicit room mappings may authorize typed actions;
  inferred mappings remain read-only and fail closed for mutations.
- Added administrator presentation review/editing and pairing profiles to the
  Core dashboard. Pairing grants are short-lived, room/profile-bound and
  single-use, with a locally generated scan-to-pair QR; the dashboard never
  reveals an existing device or provider credential.
- Added device credential revision, self-rotation, administrator rotation and
  revocation. Rotation invalidates the old token and closes the corresponding
  live device channel.
- Expanded device-scoped media with normalized artwork, progress, queue and
  grouping state plus permissioned previous, next, seek, mute, group, ungroup
  and transfer commands. Expanded assistant responses with a stable
  `pilot.assistant.v1` envelope, cards, citations and action results.
- Reworked Pilot TV from an administrator operations viewer into a scoped
  media-room client with Android-Keystore credentials, one-time pairing,
  now-playing/progress/queue, room outputs, energy, curated home glance, typed
  media controls, credential rotation and Jellyfin/Kodi launch actions.
- Polished the iOS/iPadOS client around one-time pairing, manifest/snapshot and
  resumable events, curated home and energy state, richer media control,
  structured assistant results, durable last-known state and retained meeting
  upload retry behavior.
- Polished the Android wall client with one-time pairing, Keystore credentials,
  resumable event refresh, curated typed room controls, push-to-talk and local
  response-audio playback, richer media controls, ambient mode, previews and a
  screenshot-test scaffold.
- Added a reusable Linux `media-console` display mode, selected-output
  persistence, stale-state presentation, progress/queue hints, a touch search
  keyboard and assistant-completion overlays through the loopback event proxy.
- Extended CI to test the display service, validate display JavaScript and all
  product schema JSON, and run the iOS test target on an available simulator.
- Updated product and operations documentation to separate source-tested,
  deployed-healthy and physically accepted capabilities. Pilot Core 0.25.0 was
  promoted as immutable image `core-0.25.0-20260722.1` after a verified cold
  backup and passed readiness, authenticated API, Home Assistant, Music
  Assistant, TTS and Office reconnect checks. Real phone/tablet/Shield/Pi/N150
  acceptance remains outstanding. Dedicated production Whisper deployment
  remains deferred until the RTX 3080 is installed.

## 2026-07-20

- Added Pilot Core 0.20's persistent Home Assistant intelligence catalogue.
  It synchronizes bounded state and registry metadata, records coverage and
  staleness, supports ranked entity discovery, rejects ambiguous matches, and
  exposes four read-only assistant tools without leaking Home Assistant
  credentials to clients.
- Added Home Intelligence controls and telemetry to the administrator
  dashboard, including manual synchronization, entity search, domain coverage,
  and the current bounded energy projection.
- Rebuilt Pilot iOS as a polished adaptive iPhone/iPad client with onboarding,
  connection validation, room-centric navigation, richer music search and
  now-playing surfaces, contextual chat, accessibility, foreground refresh,
  and explicit offline and stale-data handling.
- Added the native Pilot Android wall-tablet application with encrypted
  device-token storage, adaptive room and media controls, contextual assistant,
  animated energy flow, night-friendly presentation, burn-in mitigation,
  fixtures, previews, and focused protocol/security tests.
- Added Android and iOS CI gates. Android builds, unit tests, lint, and APK
  assembly run in GitHub Actions; iOS performs a signing-free simulator build.
- Added the Pilot Home Digital Twin roadmap for an app-first interactive 3D
  house shared by iOS/iPadOS and a native Android wall-tablet client. Pilot
  Core projects live state and typed actions while Home Assistant remains the
  authoritative control boundary and its credentials stay server-side.
- Added Pilot Core 0.19's device-authenticated text-assistant, media-state,
  Music Assistant search, and media-control APIs. Fixed room devices remain
  room-bound while explicitly enrolled portable clients may select a room.
- Hardened Pilot Core 0.19.1 so fixed-room media clients cannot bypass their
  room boundary by naming another room's player or transfer target; enrolled
  `portable-client` devices retain intentional multi-room control.
- Added an administrator-only capability update that preserves an existing
  device credential, allowing deployed nodes to gain narrowly scoped features
  without an unnecessary token rotation.
- Added the `Pilot Core Conversation` Home Assistant custom integration so an
  Assist pipeline can retain local STT/TTS while routing recognized text,
  contextual reasoning, and bounded tools through Pilot Core.
- Deployed `Pilot Core Conversation` 0.1.4 to Home Assistant, assigned it to
  `Pilot Contextual`, retained Faster Whisper and Piper Amy, and accepted a
  two-turn contextual conversation through the Home Assistant Assist UI.
- Added Pilot Linux Display 0.4 with touch-first Music Assistant room
  selection, search, playback, transport, and volume controls. The browser
  remains loopback-only and never receives a central service credential.
- Added the first native Pilot iOS SwiftUI application with Keychain-backed
  device authentication, room and now-playing state, Music Assistant search
  and playback, transport/volume controls, and contextual Pilot chat.
- Lowered the Pilot iOS deployment target to iOS 17 so the client also supports
  the currently available iPad while retaining the same SwiftUI architecture.
- Enrolled the production `pilot-ios-james` identity with only `voice`,
  `media-control`, and `portable-client`; the credential remains in the
  central root-only secret store pending physical-device installation.
- Added and deployed Pilot Core 0.16 contextual reasoning through the local
  Ollama server at `10.0.1.20:11434/v1`, using the installed tool-capable
  `qwen3.5:9b` model. Home Assistant deterministic intents remain first; only
  unmatched requests fall through to the bounded model and typed Pilot tools.
- Added configurable OpenAI-compatible `reasoning_effort` and set production
  to `none`. This prevents Qwen's hidden thinking mode from adding tens of
  seconds to spoken requests while retaining correct native tool calls.
- Added deterministic read-tool enforcement for current temperature, weather,
  forecast, and now-playing questions. The model must fetch fresh state before
  answering these requests and cannot substitute a plausible invented value.
- Created the Home Assistant `Pilot Contextual` pipeline with Faster Whisper,
  Piper Amy, local-intent preference, and the existing RTX Ollama conversation
  agent, then assigned the Office satellite to it. `Full local assistant`
  remains the one-selection rollback.
- Added Pilot Core 0.15's authenticated, non-audible local voice acceptance
  route and operator command. It generates a fixed phrase using Home Assistant
  Piper, validates streaming-length WAV safely, passes the bounded 16 kHz mono
  PCM through the configured Faster Whisper pipeline, and requires at least
  80% expected-word coverage without invoking conversation or room playback.
- Audited the deployed `Full local assistant` pipeline and confirmed it is
  explicitly bound to `stt.faster_whisper`, `tts.piper`, English STT, and the
  `en_US-amy-low` voice. Both add-ons report running and current.
- Revalidated Office satellite delivery through the K3 with a brief
  low-volume Piper request and restoration of the prior satellite volume.
- Added a guarded central-host source sync command that preserves the ignored
  bind configuration, root-owned secrets, backups, and deployment marker.
  This prevents a release mirror update from silently reverting Pilot Core to
  its loopback-only fail-safe binding.

## 2026-07-19

- Added the N150 Media Console architecture and delivery plan. A
  display-capable native-Debian N150 will provide the fullscreen Pilot shell,
  Music Assistant presentation, supervised mpv/Jellyfin local video, HDMI
  output, assistant overlays, and iOS control through Pilot Core. The Shield
  remains the Dolby Vision, DRM, and commercial-streaming engine.
- Added Pilot Linux Display 0.3.1 with a fully hidden kiosk pointer and bright
  moving SVG particles that make source-to-home direction explicit. Battery
  discharge now visibly travels Battery to Home; charging and grid export use
  dedicated reverse paths.
- Added Pilot Linux Display 0.3's animated energy-flow view. Solar, Grid,
  Battery, and Home are joined by live directional paths; animation speed and
  intensity scale with power, grid import/export and battery
  charge/discharge reverse the appropriate path, and inactive paths remain
  subdued.
- Added Pilot Core 0.14's device-authenticated display surface with a bounded
  five-sensor Home Assistant energy projection and safe whole-network Music
  Assistant now-playing metadata. Provider URLs, raw attributes, media URIs,
  and central credentials remain server-side.
- Added Pilot Linux Display 0.2 with touch-native Home, Energy, Music, and
  System pages, large tap targets, horizontal swipe navigation, live energy
  directions and battery state of charge, and active music from every Music
  Assistant player rather than only configured Pilot registry players.
- Added and deployed the first large-format Pilot Linux display on a 2 GB
  Raspberry Pi 4 with a 16 GB card and 1024 x 600 ILITEK touch panel. The
  minimal Cage/Chromium appliance includes a local Pilot status surface,
  loopback-only web service, native KMS mode, bounded storage, unattended
  security updates, immutable releases, and verified two-way rollback.
- Added Pilot Core 0.13's room- and device-scoped conversation sessions,
  retained turn history, linked Home Assistant conversation continuity, fast
  deterministic routing, and an optional local OpenAI-compatible reasoning
  path with seven typed Home Assistant/Music Assistant tools.
- Added administrator conversation/status APIs and dashboard visibility for
  the assistant engine without exposing transcripts in the operational
  snapshot.
- Added Pilot Display Node 0.2.8 conversation continuity. The node retains the
  opaque Pilot session ID in RAM for 15 minutes and supplies it on follow-up
  voice requests without writing dialogue state to flash.
- Corrected the deterministic Home Assistant selector to the accepted
  `conversation.home_assistant` agent ID after live API acceptance testing.
- Fixed Pilot Display Node 0.2.7 microphone capture after live speech exposed
  a TDM channel-filtering regression. ESP-IDF already packs the selected
  ES7210 slot as mono; removing a second, erroneous four-to-one decimation
  restores true 16 kHz speech for Home Assistant STT. The node installed the
  immutable release over OTA and reconnected on 0.2.7.
- Added Pilot Core 0.12 display telemetry: read-only Home Assistant history for
  configured indoor and outdoor temperature sensors, rolling 24-hour
  min/max values, and a fixed 24-point downsampled series that bounds the
  embedded payload regardless of recorder density.
- Added and physically flashed Pilot Display Node 0.2.6 with a richer forecast
  page plus dedicated Outside and Bedroom pages containing current
  temperature, rolling minimum/maximum, and automatically scaled line graphs.
  The new image completed Wi-Fi, NTP, authenticated snapshot, dim, and
  screen-off checks without resetting and is published through Pilot Core.
- Added and physically flashed Pilot Display Node 0.2.5 after Talk to Pilot
  exposed a voice-task stack overflow. The response buffer now lives on the
  heap, the voice task has measured stack headroom, task creation is checked,
  and bounded Pilot Core error details are visible over USB diagnostics.
- Corrected ES7210 capture from four-channel interleaved TDM to true 16 kHz
  mono before streaming. Physical testing now reaches Home Assistant STT and
  produces an intent response without resetting the display.
- Aligned the embedded request language with the configured
  `en_US-amy-low` Piper voice after reproducing Home Assistant's 500 response
  for the generic `en` language and a successful response for `en_US`.

## 2026-07-18

- Added Pilot Display Node 0.2.3/0.2.4 and Pilot Core downgrade protection
  after the first physical OTA exercise exposed equality-only release
  comparison. Both sides now require a semantic-version upgrade, the OTA
  transfer buffer lives on the heap, and the network task has additional stack
  headroom. Version 0.2.4 is the immutable acceptance image used to prove the
  repaired dual-slot update, reboot, and rollback-cancellation path.
- Added Pilot Display Node 0.2.2 after physical 0.2.1 acceptance exposed
  stationary IMU noise keeping the bedroom display awake. Motion detection now
  initializes a complete sensor baseline, compares both acceleration and gyro
  deltas, filters noise, and requires two consecutive movement samples.
- Added Pilot Core 0.11's authenticated embedded-node snapshot, local Assist
  PCM streaming, bounded weather projection, and immutable firmware delivery
  APIs.
- Added Pilot Display Node 0.2.1 with QMI8658 motion wake, staged bedroom
  brightness, a touch weather page, push-to-talk, animated voice states,
  ES7210 microphone capture, ES8311 response playback, and rollback-safe OTA.
- Published the immutable 0.2.1 image through Pilot Core's authenticated
  firmware service for the Bedroom node's first USB acceptance flash.
- Made the embedded WAV decoder accept Home Assistant's bounded streaming WAV
  output, whose RIFF and data lengths are deliberately left unspecified.
- Enabled the deployed local Assist pipeline and Home Assistant Piper provider;
  synthesis explicitly requests 16 kHz, mono, 16-bit WAV for deterministic
  embedded playback.
- Added Pilot Display Node 0.1 firmware for the Waveshare
  ESP32-C6-Touch-AMOLED-2.16, with a burn-in-conscious 480 x 480 office clock,
  Brisbane timezone, Wi-Fi/NTP synchronization, RTC fallback, and native USB
  diagnostics.
- Added an OTA-ready 16 MB partition layout, pinned ESP-IDF component
  dependencies, reproducible build/flash scripts, third-party notices, and a
  complete factory-flash rollback procedure.
- Tuned the no-PSRAM display and Wi-Fi memory profiles so LVGL, Wi-Fi 6, NTP,
  and the clock can coexist; Wi-Fi failure now preserves an operational offline
  RTC clock instead of causing a reboot loop.
- Backed up the complete original factory flash before deployment, flashed the
  Pilot image with hash verification, then validated Wi-Fi, DHCP, NTP, RTC
  update, minute heartbeat, and reset recovery on the physical board.

## 2026-07-17

- Added Pilot Core 0.10 authenticated observability with derived endpoint
  freshness, provider/player checks, actionable alerts, and Prometheus-format
  metrics; the dashboard now renders the same attention model.
- Added a strictly read-only Media Room acceptance harness that verifies the
  accepted Denon/Shield identities and fail-closed control state without
  sending media or Home Assistant mutations.
- Added Pilot TV 0.1 as a buildable NVIDIA Shield application using Kotlin and
  Compose for TV, with process-memory credentials, private-LAN address policy,
  operations refresh, room/player state, and now-playing views.
- Added the local meeting-intelligence foundation: bounded atomic recording
  ingestion, integrity metadata, meeting lifecycle, timestamped transcripts,
  and evidence-linked decisions and action items.
- Added Pilot Core 0.7 production operations with file-backed Docker secrets,
  a read-only capability-free container, immutable image tags, bounded logs,
  and silent deployment diagnostics.
- Added room- and device-bound, short-lived bootstrap grants that can be
  redeemed exactly once; reusable bootstrap registration is disabled in the
  production configuration.
- Added read-only Home Assistant and Music Assistant connectivity diagnostics
  that never invoke conversation, TTS, playback, volume, or home actions.
- Added cold integrity-manifested central backups, guarded restores with archive
  traversal/integrity checks, and an automatic pre-restore safety backup.
- Added Room Agent 0.5 supervised activation receipts and a fail-closed playback
  gate tied to the accepted room, capture device, K3 route, and speaker node.
- Added secret, enrollment, deployment, diagnostic, backup, restore, validation,
  and activation operator tooling plus production runbooks and CI coverage.
- Pinned the production container to UID/GID `10001` and made root-run secret
  initialization grant that group read-only access without exposing host secret
  files to other users.
- Added Pilot Core 0.6 local TTS synthesis with Home Assistant/Piper and
  OpenAI-compatible providers.
- Added bounded response streaming, content-type normalization, audio signature
  validation, redirect denial, and same-origin Home Assistant proxy retrieval.
- Added deterministic `/v1/rooms/{room_id}/speak` orchestration and optional
  spoken Home Assistant conversation responses.
- Added provider status, configuration validation, the `pilot-speak` operator
  tool, tests, deployment examples, and the local TTS activation runbook.
- Added Pilot Core 0.5 room-bound audio assets for pre-rendered assistant speech
  and announcements, with bounded retention and file sizes.
- Added per-device, same-room download authorization and SHA-256/size manifests;
  room agents never receive arbitrary media URLs.
- Added room-agent verified downloads, private caching, single-slot `pw-play`
  lifecycle management, natural-completion cleanup, and cancellation.
- Connected real assistant/announcement playback state to the existing source
  reporting and audio-focus model while keeping live ducking disabled.
- Added the `pilot-audio` upload/dispatch operator tool, reproducible room cache
  configuration, tests, and the audio delivery activation runbook.
- Added Pilot Core 0.4 deterministic room, player, and capable-device target
  resolution without requiring callers or LLMs to select infrastructure IDs.
- Added joined room state containing sources, focus, health, connections,
  players, and resolved targets.
- Added a single all-room state endpoint for deterministic “what is happening
  where?” queries and future dashboards.
- Added room-level media and endpoint-control APIs with controlled explicit
  overrides and deterministic offline queuing.
- Added room-aware `pilot-command` routing and the `pilot-media` operator tool.
- Documented room orchestration and advanced the canonical blueprint to 0.8.
- Added Pilot Core 0.3 durable device commands with queued, delivered,
  succeeded, failed, and expired states.
- Added authenticated outbound room-agent WebSockets, heartbeat and reconnect
  handling, live connection visibility, and command-result event broadcasts.
- Added a persistent room command journal that prevents execution replay after
  reconnects or lost acknowledgements.
- Added the `pilot-command` operator client and Ansible configuration for
  command transport, dependency installation, credentials, and health checks.
- Documented the command security, delivery, activation, and rollback model and
  advanced the canonical blueprint to 0.7.
- Merged the Jarvis architecture and Pilot intelligence framework pull requests,
  including execution, memory, skill, inference, world-state, planning, event,
  knowledge, identity, and schema design documents.
- Added room-agent 0.2 with loopback transport, room/source volume,
  push-to-talk, assistant, announcement, and cancel controls.
- Added self-expiring transient focus state so failed clients cannot leave room
  audio permanently ducked.
- Connected listening, assistant speech, and critical announcements to the
  deterministic audio-focus policy without enabling live gain enforcement.
- Extended outbound room reporting to cover all five priority sources.
- Added control and focus tests and advanced the canonical blueprint to 0.6.
- Added pull-request CI for service tests, Ruff, compilation, event-schema JSON,
  deployment scripts, and Ansible syntax.

## 2026-07-16

- Migrated the Office N150 from a Proxmox VM to native Debian 13 at the
  permanent address `10.0.1.53` to remove virtualization from the audio path.
- Made the voice runtime derive its network interface from Ansible facts rather
  than assuming the VM-only `ens18` name.
- Changed audible validation to use the shared PipeWire route and fixed test
  directory ownership so it can coexist with the running voice service.
- Registered the native endpoint in Home Assistant, assigned it to Office, and
  configured the Full local assistant pipeline with Piper and Whisper.
- Verified all 15 health checks, microphone capture, K3 playback, simultaneous
  input/output, Music Assistant, AirPlay, voice, and rollback state after reboot.
- Published the baseline as the private `jimmy8889/jarvis-home-ai` repository.
- Upgraded Pilot Core to an authenticated FastAPI control plane with SQLite
  persistence, hashed per-device credentials, event history, and WebSockets.
- Added deterministic audio-focus decisions for critical, assistant, Bluetooth,
  AirPlay, and Music Assistant sources.
- Added Music Assistant playback/search/transfer controls and Home Assistant
  conversation routing adapters.
- Added outbound room-agent health and MPRIS source-state reporting while
  keeping its diagnostic API loopback-only.
- Added a local PipeWire stream focus enforcer with captured-volume restoration;
  deployment remains disabled until the audible source-switching gate passes.
- Added a central Docker Compose deployment, persistent volume, health check,
  device-registration helper, and Ansible-managed device credential.

## 2026-07-15

- Reconstructed the framework because the referenced `/mnt/data` archive was
  unavailable in the Codex workspace.
- Added a standard-library Python room-agent with `/healthz`, `/readyz`, and
  `/v1/status` endpoints.
- Added a Debian 13 Ansible role for PipeWire, WirePlumber, ALSA, BlueZ, Avahi,
  Git, Python, a virtual environment, user lingering, and systemd services.
- Added opt-in Bluetooth configuration; it is installed but not enabled by
  default.
- Added hardware inventory and staged audio validation tooling.
- Added release-based deployment and one-command rollback tooling.
- Documented Proxmox boundaries, deployment, validation, and rollback.
- Explicitly excluded Intel GPU/HDMI passthrough from this milestone.
- Made headless PipeWire activation independent of `sudo`, which is absent on a
  minimal root-administered Debian installation.
- Tightened first-deployment rollback detection so only a real active release
  can become the previous-release target.
- Made the release identifier use Ansible's once-per-play gathered timestamp;
  this prevents lazy template evaluation from producing mismatched release
  directory names during a longer deployment.
- Made `/etc/pilot` group-traversable by the `pilot` service account while
  retaining root ownership and a restrictive `0750` mode.
- Added the Pilot user's D-Bus address to diagnostics and the room-agent service.
- Prevented Bluetooth inventory from blocking when BlueZ is intentionally off.
- Treat empty ALSA device listings as not ready even though the ALSA utilities
  return a successful process exit code.
- Render the room-agent systemd environment with the resolved `pilot` UID;
  system-service `%U` resolves to the manager user and is not suitable here.
- Deployed to the first Debian 13 office VM and verified persistence across two
  consecutive reboots. Software health passes; USB audio validation is pending
  because no USB peripherals are yet visible to the guest.
- Added stable PipeWire node and ALSA device fields to the room configuration
  after validating the Stadium USB microphone and Focusrite Scarlett 8i6.
- Made audible validation use the room's configured stable ALSA device names by
  default, while retaining command-line overrides.
- Replaced the synthetic duplex test tone with bounded replay of the captured
  microphone sample.
- Replaced the office output with a FiiO K3 and added a boot-time service that
  resolves stable PipeWire node names to transient IDs before applying defaults.
- Updated PipeWire status parsing to accept the Unicode tree prefixes emitted by
  `wpctl status --name`.
- Added an opt-in, pinned bare-metal deployment for Open Home Foundation Linux
  Voice Assistant v1.1.12, staged disabled until device enumeration is complete.
- Passed Linux Voice Assistant compiler flags as one explicit argument so the
  upstream setup script receives them correctly.
- Configured the enumerated Stadium and K3 runtime device names and disabled the
  unnecessary Pulse cookie file for the same-user local socket.
- Derive the Linux Voice Assistant bind address from Ansible's default IPv4
  facts so its ESPHome mDNS record does not advertise the wildcard address.
- Restart Linux Voice Assistant when its generated systemd unit changes.
- Enabled the office voice satellite with the Stadium input, K3 output, and
  temporary `okay_nabu` wake model; verified TCP and ESPHome mDNS discovery
  after a full reboot.
- Extended `pilot-validate` to verify the enabled voice-satellite service and
  its configured API socket.
- Added voice-satellite service, listening socket, and Home Assistant connection
  state to the room-agent status model and readiness calculation.
- Added a reproducible Shairport Sync AirPlay receiver routed through Pilot's
  PipeWire session, with its own hardened systemd unit and D-Bus/MPRIS controls.
- Added AirPlay service/listener health to the room-agent and `pilot-validate`.
- Added staged Squeezelite deployment for Music Assistant, intentionally disabled
  until the server address and cross-VLAN port reachability are confirmed.
- Imported the user-provided blueprint as the canonical Pilot OS architecture
  reference and reconciled it with the live office deployment as version 0.2.
- Added and deployed the official Sendspin 7.5.0 headless client, connected to
  Music Assistant at `10.0.2.72:8927` as `Pilot Office Music`.
- Added Music Assistant service and transport state to room readiness and
  `pilot-validate`; Squeezelite remains an unused fallback.
- Verified Sendspin, voice, AirPlay, audio defaults, and room-agent persistence
  across a controlled VM reboot with all fifteen validation checks passing.
- Added the first dependency-free Pilot Core service with validated TOML room
  and player configuration, deterministic registry revisions, read-only REST
  endpoints, tests, and an office example registry.
