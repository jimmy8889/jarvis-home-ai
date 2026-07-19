# Contextual Assistant

Pilot Core 0.13 owns the assistant conversation lifecycle. Home Assistant still
provides speech recognition and deterministic home control, but it no longer
owns the only copy of the conversation.

## Request path

```text
Room microphone
  -> Home Assistant STT only
  -> Pilot Core conversation session
     -> Home Assistant built-in agent (fast deterministic attempt)
     -> local LLM (only when the deterministic attempt does not match)
        -> bounded Pilot tools
  -> local Piper TTS
  -> originating room
```

Each Pilot conversation is scoped to a room and, when present, a device and
user. The active session expires after 15 minutes by default. Pilot stores the
retained dialogue in SQLite and separately tracks Home Assistant's provider
conversation ID. A stale, unknown, cross-room, or cross-device session ID
starts a new session instead of exposing another session.

The ESP32 bedroom display keeps the Pilot conversation ID in memory and sends
it on later voice requests for up to 15 minutes. It is deliberately not written
to flash.

## Routing policy

Pilot first calls Home Assistant's built-in `home_assistant` conversation agent.
A successful deterministic action or query returns immediately. An unmatched
intent is offered to the configured local model with:

- the current room and its configured targets;
- deterministic source focus;
- normalized Music Assistant and Home Assistant player state;
- the bounded recent user/assistant history;
- typed tool definitions.

If the model is unavailable or returns an invalid response, Pilot returns the
Home Assistant fallback. Ordinary home commands therefore remain operational
without the model.

## Tool boundary

The local model cannot call arbitrary URLs, Home Assistant services, shell
commands, or entity IDs. Pilot currently exposes:

- `get_room_status`
- `get_weather`
- `get_temperature` for the two configured sensor aliases
- `control_home` through Home Assistant's restricted Assist agent
- `search_music` through Music Assistant
- `play_music` and `control_media` through a configured room player

Arguments are schema-constrained, tool rounds are capped, provider responses
are bounded, secret-like keys are removed, and disabled players remain
fail-closed. Context and tool output are explicitly treated as untrusted data
in the system prompt.

## Configuration

Pilot supports a local OpenAI-compatible endpoint, including an Ollama `/v1`
endpoint:

```toml
[integrations]
llm_provider = "openai"
llm_url = "http://RTX_HOST:11434/v1"
llm_token_env = "PILOT_LLM_TOKEN"
llm_model = "LOCAL_TOOL_CAPABLE_MODEL"
llm_timeout_seconds = 60
llm_max_tool_rounds = 4
llm_context_turns = 12
```

The token is optional for a private unauthenticated Ollama listener. Never
expose that listener outside trusted infrastructure. The deployed production
configuration keeps `llm_provider` empty until the RTX endpoint and model have
passed tool-use and latency acceptance.

## Administration

- `GET /v1/assistant/status`
- `GET /v1/conversations`
- `GET /v1/conversations/{conversation_id}`
- `DELETE /v1/conversations/{conversation_id}`

These endpoints require the Pilot Core administrator token. The dashboard
shows whether contextual reasoning is configured and lists only conversation
metadata. Full retained turns are available only through the individual
administrator endpoint.

Long-term personal memory is intentionally separate. Version 0.13 retains
short, room-scoped dialogue only; no transcript is promoted into durable
personal memory without a future explicit retention policy.
