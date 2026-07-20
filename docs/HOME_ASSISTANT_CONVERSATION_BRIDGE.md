# Home Assistant Conversation Bridge

`Pilot Core Conversation` routes a Home Assistant voice pipeline through Pilot
Core without exposing a Pilot administrator token, Music Assistant token, or
Ollama endpoint to Home Assistant.

## Request path

```text
Office microphone
  -> Home Assistant wake word and Faster Whisper STT
  -> Pilot Core Conversation entity
  -> device-authenticated /v1/devices/{id}/assistant
  -> deterministic Home Assistant conversation attempt
  -> local Ollama tools when required
  -> response text
  -> Home Assistant Piper TTS
  -> Office endpoint
```

The integration uses a dedicated `voice` device credential fixed to the
Office. It cannot select another room or access media-control APIs.

## Install

Copy the integration into Home Assistant:

```text
/config/custom_components/pilot_conversation/
```

Restart Home Assistant, then add **Pilot Core Conversation** under
**Settings -> Devices & services -> Add integration**.

Configure:

```text
Name: Pilot Core
Core URL: http://10.0.1.64:8770
Device ID: pilot-ha-office
Device token: dedicated token created by Pilot Core
Room ID: office
```

The room ID is descriptive. Pilot Core derives the authoritative room from the
registered device, so changing the form value cannot cross the room boundary.

In **Settings -> Voice assistants**, edit the Office pipeline:

- STT: the existing local Faster Whisper provider
- Conversation agent: `Pilot Core Conversation`
- TTS: the existing local Piper provider

Retain the previous pipeline until a real microphone request, deterministic
Home Assistant action, general Ollama answer, follow-up question, and spoken
reply have all passed.

## Accepted deployment

The `Pilot Contextual` pipeline is now assigned to `Pilot Core Conversation`.
Its existing Faster Whisper STT and Piper Amy TTS providers were retained.
Home Assistant accepted a two-turn text test through the integration:

1. `What is two plus two?`
2. `Multiply that by three.`

Pilot Core returned four and then twelve, proving that the Home Assistant
conversation ID remains linked to the room-scoped Pilot session. The prior
`Full local assistant` pipeline remains available as the one-selection
rollback.

## Rollback

Select the previous Home Assistant conversation agent in the voice pipeline.
The custom integration can remain installed while inactive. To remove it,
delete its config entry, remove the custom-component directory, and restart
Home Assistant.
