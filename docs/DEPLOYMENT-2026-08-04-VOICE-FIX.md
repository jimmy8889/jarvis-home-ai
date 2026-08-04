# Voice path repair — 2026-08-04

## Cause

Pilot Core was receiving iPhone audio and Home Assistant Whisper was
transcribing it correctly. The subsequent Home Assistant Piper request failed
with HTTP 500 because the phone supplied the regional locale `en-AU`, while
the configured Piper voice is loaded as `en_US`.

## Fix

The Home Assistant TTS adapter now retries a failed provider request once with
the configured `tts_language` when the client locale differs. The client/UI
locale is retained in the returned synthesis metadata; only the provider
request locale is corrected.

## Verification

- Pilot Core TTS/STT and API tests: 45 passed.
- Live Core image: `core-0.35.1-voice-20260804.1` on apps01.
- Live request with `en-AU`: HTTP 200.
- Transcript: `What is the weather like today?`
- Local LLM response returned and synthesized by Piper.
- Audio asset download: HTTP 200, WAV, 16-bit mono PCM, 16 kHz.

## Operational note

Home Assistant and Core must both be ready before testing voice. If HA is
restarting, Core correctly reports a temporary integration/voice failure rather
than silently accepting the request.
