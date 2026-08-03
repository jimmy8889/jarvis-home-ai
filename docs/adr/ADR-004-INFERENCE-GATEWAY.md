# ADR-004: Unified Inference Gateway

Status: Accepted (initial LLM routing implemented)

## Context

Pilot runs live STT, meeting transcription, diarisation, TTS, embeddings, and
several LLM routes across CPUs, an RTX 3080, and an RTX 3090. Letting each
application load models independently would waste VRAM and produce inconsistent
fallback behaviour.

## Decision

Create a central inference gateway with APIs for:

- streaming and batch STT
- TTS
- LLM completion and tool planning
- embeddings and reranking
- diarisation
- health and capacity

The gateway owns model lifecycle, GPU-aware queues, priorities, timeouts, and fallbacks.

Example routing:

```yaml
routes:
  live_stt:
    primary: gtx1060-whisper-small-en
    fallback: cpu-whisper-base-en
  meeting_stt:
    primary: gtx1060-distil-whisper
  assistant_fast:
    primary: rtx3090-primary
    fallback: rtx3080-verifier
  meeting_summary:
    primary: rtx3090-primary
  tts:
    primary: cpu-kokoro
    fallback: cpu-piper
```

Pilot Core now implements authenticated, role-based LLM routes and bounded
failover. The RTX 3080 currently uses mutually exclusive verifier, vision, and
speech modes; Core discovers live availability but does not silently switch GPU
modes because doing so would interrupt STT/TTS. Live voice requests take
priority over meeting batch jobs.

## Consequences

- Better GPU utilisation and predictable latency.
- One integration surface for all Pilot clients.
- The gateway becomes critical infrastructure and needs robust degraded modes.

## Alternatives considered

- Model servers embedded in each app: rejected due to duplicated memory and configuration.
- One permanently loaded large model: rejected due to latency and VRAM constraints.

## Security and privacy impact

Routes must explicitly declare whether remote providers are allowed. Local-only must remain the default.

## Operational impact

Expose queue depth, model load state, latency, VRAM use, failures, and active fallback route.
