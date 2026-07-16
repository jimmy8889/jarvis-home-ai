# Jarvis Assistant Feature Review

Status: Proposed architecture additions  
Date: 2026-07-16

## Purpose

This review compares Pilot OS with established open-source personal-assistant and smart-speaker projects, including Leon, OpenVoiceOS, Willow, and the Open Home Foundation Linux Voice Assistant.

Pilot should not copy another assistant wholesale. It should retain its strengths: room-aware local voice, premium multi-room audio, Home Assistant and Music Assistant integration, meeting intelligence, macOS dictation, NVIDIA Shield integration, and local-first inference.

## Features to adopt

### Execution modes

Every request should run in one of three modes:

- **Controlled:** deterministic intents and approved actions only. Use for locks, alarms, HVAC, energy controls, media transport, and other safety-sensitive operations.
- **Smart:** Pilot selects deterministic intent handling, retrieval, or a bounded LLM tool workflow.
- **Agent:** Pilot may plan and execute a limited sequence of tools with explicit time, step, and permission limits.

### Layered memory

Pilot needs distinct memory scopes:

1. Turn memory
2. Session memory
3. Daily context
4. Durable user preferences
5. Environment and topology memory
6. Episodic meeting and assistant history

Every stored memory must include provenance, confidence, retention policy, sensitivity, and deletion support.

### Skill and plugin SDK

Use a stable hierarchy:

```text
Skill
  -> Action
      -> Tool
          -> Function / Adapter / Binary
```

Each skill declares schemas, permissions, execution modes, confirmation policy, required services, secrets, health checks, and tests.

### Capability registry

Pilot must maintain a machine-readable self-model containing:

- installed skills
- reachable services
- available models
- online room agents
- microphone, output, display, and player capabilities
- current permissions
- degraded or unavailable components

This prevents the assistant from promising actions it cannot perform.

### Ordered fallback pipeline

Requests should resolve through an explicit chain:

```text
stop/cancel
-> active conversation
-> room-native intent
-> Home Assistant intent
-> media intent
-> meetings/tasks retrieval
-> local QA
-> fast local LLM
-> larger local LLM
-> optional remote provider
-> graceful failure
```

### Bounded proactive pulse

Pilot may proactively surface useful events, but only under strict policy:

- quiet hours
- notification rate limits
- material-change requirement
- presence-aware routing
- criticality levels
- visible reason for every proactive event
- immediate suppress and snooze controls

### Multi-wake-word and continued conversation

Room agents should support:

- multiple wake words and languages
- per-purpose wake phrases
- a dedicated stop model
- versioned sensitivity settings
- follow-up requests without repeating the wake phrase
- explicit privacy timeout

Suggested phrases:

- `Hey Pilot` — normal assistant
- `Pilot dictate` — macOS dictation
- `Pilot meeting` — meeting capture
- `Stop` — immediate cancellation

### Distributed timers and alarms

Timers should be central, persistent objects with room affinity, local fallback, named timers, escalation, pause/resume/cancel, and reboot survival.

### Peripheral WebSocket API

Provide a local realtime API for:

- push-to-talk buttons
- hardware mute switches
- rotary encoders
- LED rings
- small displays
- presence sensors

A hardware mute indicator must reflect the physical microphone power/data state rather than a software flag alone.

### Unified inference gateway

Expose one service for STT, TTS, LLMs, embeddings, reranking, and diarisation. It should provide:

- GPU-aware scheduling
- priorities and queues
- model hot-loading and unloading
- streaming responses
- fallback routes
- latency and VRAM metrics
- offline CPU fallbacks

### Offline and degraded room mode

A room agent should retain wake/stop detection, volume, mute, Bluetooth, AirPlay, running timers, basic status, and a clear server-unavailable response when Pilot Core is offline.

### Explicit state machines

Voice states:

```text
IDLE -> WAKE_DETECTED -> LISTENING -> ENDPOINTING -> TRANSCRIBING
-> ROUTING -> CONFIRMING -> EXECUTING -> SPEAKING -> CONTINUING
```

Audio-focus states:

```text
BACKGROUND_MUSIC -> DUCKED_FOR_LISTENING -> DUCKED_FOR_RESPONSE
-> INTERRUPTED_BY_ALERT -> RESTORING
```

### Observability and replay

Trace each interaction from wake detection through audio capture, transcription, routing, tools, TTS, and playback. Record latency, failures, audio underruns, model capacity, and tool success. Provide an opt-in redacted replay harness.

### Privacy dashboard

Users must be able to inspect and delete:

- captured utterances
- transcripts
- tool calls
- stored memories
- meetings
- outbound remote-provider requests

### Signed deployment and provisioning

Add per-device identity, signed releases, provenance, one-time enrolment, staged updates, and rollback.

### Virtual room simulator

CI should simulate microphones, wake events, Home Assistant state, Bluetooth sources, Denon/Shield endpoints, and complete assistant journeys without physical hardware.

## Highest-priority framework additions

1. Skill/plugin manifest standard
2. Controlled, smart, and agent execution modes
3. Layered memory model
4. Capability registry
5. Voice and audio state machines
6. Ordered fallback chain
7. Continued conversation and stop-word support
8. Distributed timers
9. Unified inference gateway
10. Peripheral WebSocket API
11. Offline/degraded room mode
12. End-to-end tracing
13. Privacy/activity dashboard
14. Proactive pulse policy
15. Simulator and CI harness
