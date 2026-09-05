# 35B llama.cpp production promotion — 2026-08-05

## Result

- `ai3090` now serves `primary` on `10.0.1.20:8000/v1` through
  `llama-35b.service`.
- Model: Qwen3.6 35B-A3B `IQ4_NL` with `draft-mtp`, 8,192 context and one
  request slot.
- The OpenAI-compatible endpoint retained the existing vLLM bearer token and
  `primary` model alias; Pilot Core required no configuration or secret change.
- Local authenticated health/models/chat checks and an authenticated request
  from the live Pilot Core container on `apps01` passed.

## Service layout

The service uses system-owned runtime and model paths because SELinux blocks a
system unit from executing files in a login user's private home:

- Runtime: `/opt/llama-35b/bin`
- Model: `/srv/models/llama-35b/Qwen3.6-35B-A3B-UD-IQ4_NL.gguf`
- Service: `/etc/systemd/system/llama-35b.service`

`vllm.service` remains installed and stopped as the rollback target.

## Rollback

```bash
sudo systemctl stop llama-35b
sudo systemctl start vllm
```

Verify with `systemctl is-active vllm` and `curl --fail
http://127.0.0.1:8000/health` on `ai3090`.
