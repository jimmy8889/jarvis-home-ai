# GPU speech deployment — 2026-08-04

Pilot voice speech is now local-first on the RTX 3080 at `10.0.1.43`.

## Runtime

- **STT:** `faster-whisper` `small.en`, CUDA `float16`, private API on `:8031`
- **TTS:** vLLM Omni Qwen3-TTS 1.7B, served as `tts` on `:8030`
- **Pilot Core:** prefers the GPU STT endpoint and falls back to Home Assistant STT if the GPU endpoint is unavailable
- **Transport:** the Core-to-GPU links are LAN-only; the phone still uses the public HTTPS Pilot endpoint
- **Authentication:** both GPU endpoints require bearer tokens stored as Docker/systemd secrets

The STT service is managed by `pilot-gpu-stt.service` and starts after reboot. Its model is stored under `/srv/models/faster-whisper`; the CUDA 12 compatibility libraries are isolated in `/opt/pilot-stt/venv` so the existing vLLM TTS environment is not modified.

## Verification

The following checks passed during deployment:

1. `pilot-gpu-stt.service` is enabled and active.
2. `GET /healthz` reports `faster-whisper`, `small.en`, CUDA, and `float16`.
3. A real WAV uploaded to `/v1/audio/transcriptions` returned the expected transcript.
4. Pilot Core reports `gpu_with_home_assistant_fallback` and the primary endpoint as configured.
5. Pilot Core reports OpenAI-compatible GPU TTS as its active provider.
6. A public phone voice request returned a transcript, local LLM answer, and downloadable WAV response.

Warm direct STT for a short command measured approximately 70 ms on the 3080. TTS generation depends on answer length; the current Qwen3-TTS service is retained for quality and can be optimized independently without changing the client contract.

## Operations

```bash
ssh -i ~/.ssh/id_ed25519 jameshazell@10.0.1.43 \
  'sudo systemctl status pilot-gpu-stt.service'
ssh -i ~/.ssh/id_ed25519 jameshazell@10.0.1.43 \
  'sudo journalctl -u pilot-gpu-stt.service -f'
```

The Core configuration uses `voice_stt_url`, `voice_stt_token_env`, `voice_stt_model`, and `voice_stt_timeout_seconds`. Removing `voice_stt_url` returns the room voice path to Home Assistant STT without changing the phone API.
