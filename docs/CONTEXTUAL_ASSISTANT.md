# Contextual Assistant

Pilot Core owns the assistant conversation lifecycle. Home Assistant still
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

Pilot forces the corresponding read-only tool for clear requests about current
temperature, weather, forecast, and now-playing state. This guards the voice
experience against a small model returning a plausible sensor value from its
language prior instead of consulting the live home. Mutating tools are never
forced by keyword; real-world actions still pass through Home Assistant or
Music Assistant and their existing control gates.

## Configuration

Pilot supports a local OpenAI-compatible endpoint, including an Ollama `/v1`
endpoint:

```toml
[integrations]
llm_provider = "openai"
llm_url = "http://RTX_HOST:11434/v1"
llm_token_env = "PILOT_LLM_TOKEN"
llm_model = "LOCAL_TOOL_CAPABLE_MODEL"
llm_reasoning_effort = "none"
llm_timeout_seconds = 60
llm_max_tool_rounds = 4
llm_context_turns = 12
```

The token is optional for a private unauthenticated Ollama listener. Never
expose that listener outside trusted infrastructure. The deployed production
configuration uses `qwen3.5:9b` at `10.0.1.20:11434/v1`. Its native tool call
selected the inside-temperature tool with schema-correct arguments.
`reasoning_effort = "none"` is deliberate for voice latency: the same warm
model answered a short factual question in about one second rather than
spending many seconds generating hidden reasoning tokens.

The `Pilot Core Conversation` custom integration makes Pilot Core a selectable
Home Assistant conversation agent. The Office pipeline retains Faster Whisper
for STT and Piper for TTS, while recognized text passes through a dedicated,
room-bound Pilot device credential. Pilot then tries Home Assistant's
deterministic agent first and uses the local RTX/Ollama tool loop only where
needed.

This converges the Office satellite, embedded displays, Raspberry Pi surfaces,
and iOS clients on the same retained Pilot sessions and bounded tool policy.
`Full local assistant` remains available in the device's pipeline selector as
the immediate rollback.

Installation and pipeline selection are documented in
`HOME_ASSISTANT_CONVERSATION_BRIDGE.md`.

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
