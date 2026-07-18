# Local text-to-speech synthesis

Pilot Core 0.6 converts text into bounded, validated audio and routes it through
the secure room-audio delivery path. Speech synthesis and room playback remain
separate stages: the provider never receives device credentials, and the room
agent never contacts the provider.

```text
Text / HA response
        │
        ▼
Pilot Core local TTS adapter
        │ validated audio bytes
        ▼
Room-bound audio asset
        │ authenticated command + manifest
        ▼
Originating room agent → PipeWire output
```

## Supported providers

### Home Assistant Piper

The first provider reuses a configured Home Assistant TTS entity such as
`tts.piper`. Pilot Core calls Home Assistant's documented
[`POST /api/tts_get_url`](https://www.home-assistant.io/integrations/tts/#rest-api)
endpoint and requests a preferred local audio format.

Pilot Core deliberately ignores the absolute URL in Home Assistant's response.
It accepts only a relative path beginning with `/api/tts_proxy/` and resolves it
against the configured Home Assistant origin. This prevents a compromised or
misconfigured response from making Pilot Core fetch an arbitrary URL.

Configuration:

```toml
[integrations]
home_assistant_url = "http://10.0.2.72:8123"
home_assistant_token_env = "HOME_ASSISTANT_TOKEN"
tts_provider = "home_assistant"
tts_engine_id = "tts.piper"
tts_voice = "default"
tts_format = "wav"
tts_language = "en"
tts_sample_rate = 16000
tts_sample_channels = 1
tts_sample_bytes = 2
tts_timeout_seconds = 60
```

The production deployment uses `tts.piper` with the local Amy voice. Pilot Core
requests all four preferred audio properties because a format-only request may
fall back to MP3. The 16 kHz, mono, 16-bit WAV response is compatible with the
bedroom ESP32 node and remains suitable for the room-agent playback path. The
long-lived Home Assistant token remains a file-backed container secret.

### OpenAI-compatible local speech

The second provider supports a local `/v1/audio/speech`-compatible service. It
is intended for future Kokoro-class voices, Speaches, LocalAI, or another local
server hosted on the RTX machine.

```toml
[integrations]
tts_provider = "openai"
tts_url = "http://tts-host:8000/v1/audio/speech"
tts_token_env = "PILOT_TTS_TOKEN"
tts_model = "kokoro"
tts_voice = "af_heart"
tts_format = "wav"
tts_language = "en"
tts_timeout_seconds = 60
```

The token is optional for a trusted local server but remains recommended when
the endpoint is reachable by other hosts.

## Validation and safety

- Supported output formats are WAV, FLAC, MP3, OGG, and AAC.
- Provider responses are streamed into a bounded in-memory buffer using Pilot
  Core's configured audio-asset size limit.
- Declared and observed sizes are checked.
- Content types are normalized and audio magic bytes are validated.
- Redirects are disabled.
- TTS text is not added to audio-asset metadata or filenames.
- Home Assistant caching is disabled; Pilot owns the asset lifetime.
- Synthesis occurs only after a valid room and audio-capable endpoint have been
  resolved.
- Critical playback is permitted only for announcement requests.
- Provider errors do not create assets or queue endpoint commands.

## API

Provider status without credentials or provider URLs:

```http
GET /v1/tts
Authorization: Bearer {admin-token}
```

Synthesize and route speech to a room:

```http
POST /v1/rooms/{room_id}/speak
Authorization: Bearer {admin-token}
Content-Type: application/json

{
  "text": "The office light is now on.",
  "language": "en-AU",
  "voice": "default",
  "kind": "assistant",
  "volume": 0.75,
  "critical": false
}
```

The response contains synthesis metadata, the room-bound asset manifest, the
resolved endpoint and response player, and the durable room command.

`POST /v1/assistant` also accepts `"speak": true`. Pilot Core sends the input
to Home Assistant's conversation API, extracts the returned plain speech, then
synthesizes and routes that response to the request's room.

## Operator command

```bash
export PILOT_CORE_ADMIN_TOKEN='...'
deploy/scripts/pilot-speak \
  --core-url https://pilot-core.example \
  --room-id office \
  --language en-AU \
  --volume 0.7 \
  --wait 10 \
  "The local speech path is ready."
```

Omit the text to read it from standard input. Use
`--kind announcement --critical` only for a genuine critical announcement.

## Current activation state

The provider remains disabled in the generic example configuration. It is
enabled in the production container configuration and has passed a silent
format check against Home Assistant Piper. Audible acceptance remains
room-specific:

1. Verify `/v1/tts` and synthesize without enabling live audio focus.
2. With someone in the room, play a quiet test through the intended endpoint.
3. Verify cancellation, source-state reporting, and volume restoration.
4. Enable live ducking only after that room's physical acceptance passes.
