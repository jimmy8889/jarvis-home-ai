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
- `control_light` through Pilot's curated, typed and audited Home Actions layer
- `search_music` through Music Assistant
- `play_music` and `control_media` through a configured room player

Arguments are schema-constrained, tool rounds are capped, provider responses
are bounded, secret-like keys are removed, and disabled players remain
fail-closed. Context and tool output are explicitly treated as untrusted data
in the system prompt.

Pilot forces the corresponding read-only tool for clear requests about current
temperature, weather, forecast, and now-playing state. This guards the voice
experience against a small model returning a plausible sensor value from its
language prior instead of consulting the live home.

Explicit light mutations are a separate governed route. When the local model
is available, phrases such as “turn the office lamp off”, “dim the bedroom
light to 30 percent”, or “make the media-room lights blue” force the
`control_light` schema before Home Assistant's natural-language agent. The
tool accepts only on/off/toggle, brightness and bounded colour arguments. It
then resolves the user's target against the curated catalogue, enforces the
originating device and room permissions, sends one allowlisted Home Assistant
service call, reads the entity back, and records an audit.

The model cannot supply a Home Assistant service name or use a catalogue result
to authorize an action in the same request. Governed light requests fail closed
if local inference is unavailable and never fall through to the free-form Home
Assistant conversation boundary. If a light mutation succeeds but the model
cannot compose the final sentence, Core produces a deterministic response from
the audited tool result instead of retrying the action. Negated, hypothetical,
how-to, broad whole-home, ambiguous, and model-invented cross-room requests do
nothing. Other low-risk real-world actions continue through Home Assistant or
Music Assistant and their existing control gates; secured-entry and alarm
requests are intercepted for explicit Pilot confirmation.

Pilot retains one successful governed light target as short-lived working
context inside the same device-scoped conversation. A follow-up such as “now
make them 60 percent” can therefore reuse the exact audited entity and room.
This is not free-form memory: pronouns are accepted only when the immediately
preceding exchange contains a successful `control_light` result, and the tool
must repeat that exact entity and room through the normal authorization path.
An unrelated turn, expired session, different device or different target drops
the referent and requires the user to name the light again.

## Configuration

Pilot supports authenticated vLLM/OpenAI-compatible endpoints. A single-model
server can use `llm_model = "auto"`; production uses an explicit multi-GPU
pool so routing and fallback remain deterministic:

```toml
[integrations]
llm_provider = "vllm"
llm_url = "http://VLLM_HOST:8000/v1"
llm_token_env = "PILOT_LLM_TOKEN"
llm_model = "auto"
llm_timeout_seconds = 60
llm_max_output_tokens = 1024
llm_max_tool_rounds = 4
llm_context_turns = 12
llm_fast_context_tokens = 8192
llm_standard_context_tokens = 16384
llm_deep_context_tokens = 65536
llm_hermes_context_tokens = 65536
llm_experimental_context_tokens = 131072
llm_fast_output_tokens = 512
llm_standard_output_tokens = 1024
llm_deep_output_tokens = 2048
llm_hermes_output_tokens = 4096

[[integrations.llm_backends]]
id = "ai3090-primary"
url = "http://ai3090:8000/v1"
token_env = "PILOT_LLM_3090_TOKEN"
model = "primary"
roles = ["assistant", "reasoning", "meeting"]
priority = 10

[[integrations.llm_backends]]
id = "ai3080-verifier"
url = "http://ai3080:8000/v1"
token_env = "PILOT_LLM_3080_TOKEN"
model = "verifier"
roles = ["assistant", "verification"]
priority = 100
```

Tokens are supplied through Docker secrets and are never returned by the
dashboard or client APIs. Pilot tries matching routes in priority order and
records the active backend. The RTX 3080 is mode-switched: its verifier and
vision routes are available only when that GPU mode is active; while it runs
STT/TTS those LLM routes correctly report unavailable. The always-on RTX 3090
route remains the normal assistant and meeting-analysis path.

Assistant requests support explicit `fast`, `standard`, `deep`, `hermes`, and
`experimental-128k` modes. Device voice requests default to `fast`; the
administrator assistant endpoint defaults to `standard`. The mode controls
history retention, the bounded prompt envelope, output budget, and tool-round
limit without bypassing deterministic Home Assistant routing.

The approved frontier-distilled model experiments are DavidAU's Qwen3.6 Fable
Fusion 27B and Qwen3.5 Defiant Fable 9B. Both are GGUF/MTP artifacts and remain
isolated until a vLLM-compatible serving path is verified. See
`docs/QWEN_MODEL_LAB.md` for the promotion and safety rules.

The `Pilot Core Conversation` custom integration makes Pilot Core a selectable
Home Assistant conversation agent. The Office pipeline retains Faster Whisper
for STT and Piper for TTS, while recognized text passes through a dedicated,
room-bound Pilot device credential. Pilot then tries Home Assistant's
deterministic agent first and uses the local vLLM tool loop only where
needed.

This converges the Office satellite, embedded displays, Raspberry Pi surfaces,
and iOS clients on the same retained Pilot sessions and bounded tool policy.
`Full local assistant` remains available in the device's pipeline selector as
the immediate rollback.

Installation and pipeline selection are documented in
`HOME_ASSISTANT_CONVERSATION_BRIDGE.md`.

## Administration

- `GET /v1/assistant/status`
- `GET /v1/assistant/models` (live per-backend availability and served models)
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
