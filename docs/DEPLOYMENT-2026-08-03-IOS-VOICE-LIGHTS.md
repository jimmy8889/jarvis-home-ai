# Pilot iOS voice and governed lights deployment — 2026-08-03

## Result

- Pilot Core host: apps01 at `10.0.1.204`
- Public API: `https://pilot.jameshomeautomation.work`
- Source commit: `6ac8416298117d270954544d2a81c7c71f67b4d7`
- Pilot Core version: `0.31.1`
- Immutable image: `jarvis-home-ai/pilot-core:core-0.31.1-ios-voice-20260803.1`
- Container health: healthy with zero restarts after promotion
- Signed iPhone application: built, installed and launch-verified

Pilot now provides a complete device-authenticated iOS push-to-talk loop. It
captures bounded 16 kHz signed mono PCM, detects the end of speech, routes local
STT and contextual reasoning through Pilot Core, renders a microphone-reactive
listening/processing/speaking surface and plays the authenticated TTS response
on the requesting phone. Voice capture and meeting recording cannot own the
audio session simultaneously. Native Sendspin ownership is restored after the
voice interaction.

Assistant reply audio is exact-device-private. A different credential in the
same room cannot download it. Announcements remain a distinct same-room path
and require an audio-capable device. Unbound assistant assets fail closed.

## Governed Home Assistant light control

Pilot Core exposes a typed `control_light` tool for on, off, toggle, bounded
brightness, named colours and bounded RGB values. The target must be grounded
in the user's request or a successful immediately preceding light action and
must be included, authoritative, available, fresh, permissioned for the device
and compatible with the requested capability.

The production presentation policy explicitly maps these aggregate lights:

- `light.james_office` to `office`
- `light.master_bedroom` to `bedroom`
- `light.media_room` to `media-room`

Cross-room targets must be named in the original request. Whole-home,
hypothetical, negated and security-sensitive mutations fail closed. Pilot
permits at most one light mutation per assistant turn and never falls through
to a generic Home Assistant mutation after governed light routing.

## Verification

- Pilot Core tests: 213 passed
- iOS strict-concurrency tests: 33 passed
- Assistant evaluation harness tests: 9 passed
- Production read-only assistant evaluation: 10 passed, 0 failed
- Mutation evaluation cases: 13 skipped by the safe default; no live light
  action was issued during deployment
- Read-only latency: p50 4.48 seconds, p95 15.53 seconds, maximum 15.99 seconds
- Public health, readiness, Home Assistant, Music Assistant and TTS diagnostics
  passed after promotion

The production evaluation result is retained on apps01 at
`/opt/jarvis-home-ai/.artifacts/assistant-eval/read-only-0.31.1.json`.

Software deployment and signed-device launch do not constitute physical
acceptance. The microphone/end-of-speech path, audible TTS, Bluetooth routing,
native playback restoration and real light colour/state changes still require
in-person observation.

## Recovery

The guarded deployment created:

- Core archive:
  `/opt/jarvis-home-ai/infra/backups/pilot-core-20260803T133955Z-pre-deploy-core-0.31.1-ios-voice-20260803.1.tar.gz`
- Core archive SHA-256:
  `bb670eb7aa06b69574af23ec79e2bad9ecda5cd7fc40fa78118870172e44f7df`
- Home presentation backup:
  `/opt/jarvis-home-ai/infra/backups/home-presentation-before-0.31.0.json`

Use the repository's guarded `pilot-core-restore` procedure to restore the
archive and previous immutable image. Restore the presentation backup through
the authenticated presentation API if the curated light mappings must be
reverted. No provider, administrator, device or vLLM secret is recorded here.
