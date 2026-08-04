# Kokoro-82M local TTS deployment

Pilot now has two local speech engines on the RTX 3080 (`10.0.1.43`):

- Qwen3-TTS on port `8030` remains the default (`serena` and the other Qwen voices).
- Kokoro-82M runs as `pilot-kokoro-tts.service` on port `8032`.

Kokoro is exposed through the same OpenAI-compatible `/v1/audio/speech` shape.
Pilot Core routes a Kokoro voice ID to the sidecar automatically, so the client
does not need to know which GPU service is handling the request.

The sidecar is installed under `/opt/pilot-kokoro`, uses the existing vLLM Python
3.12 runtime, and stores Hugging Face files under
`/srv/models/huggingface/kokoro`. The service starts with the British English
pipeline warmed and loads the American pipeline lazily when needed.

Useful checks on the 3080:

```bash
systemctl status pilot-kokoro-tts.service
curl http://127.0.0.1:8032/healthz
curl -X POST http://127.0.0.1:8032/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"Kokoro-82M","voice":"bm_george","input":"Gday from Pilot","response_format":"wav"}' \
  -o /tmp/kokoro.wav
file /tmp/kokoro.wav
```

The bundled `bm_*` voices are British male voices and are the closest stock
baseline to the requested Australian male delivery. Kokoro-82M does not provide
Australian accent control or voice cloning. A genuine Australian voice should
be added later through a consented reference recording and a separate, explicitly
configured cloning engine; it must not be inferred from a person’s voice.

## Rollback

Set `tts_kokoro_url = ""` in `config/core.container.toml` and redeploy Pilot
Core. Qwen remains the configured default and the Kokoro systemd service can be
stopped independently:

```bash
sudo systemctl disable --now pilot-kokoro-tts.service
```
