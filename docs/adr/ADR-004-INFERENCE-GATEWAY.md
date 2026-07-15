# ADR-004: Unified Inference Gateway

Status: Proposed

## Context

Pilot will run live STT, meeting transcription, diarisation, TTS, embeddings, and several LLM routes across CPUs, a GTX 1060, and an RTX 3080. Letting each application load models independently would waste VRAM and produce inconsistent fallback behaviour.

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
    primary: rtx3080-qwen-small
  meeting_summary:
    primary: rtx3080-qwen-medium
  tts:
    primary: cpu-kokoro
    fallback: cpu-piper
```

Live voice requests take priority over meeting batch jobs.

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
