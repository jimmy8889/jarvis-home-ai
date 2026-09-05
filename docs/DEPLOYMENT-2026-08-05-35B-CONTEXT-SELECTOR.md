# 35B context selector — 2026-08-05

## Result

The production Qwen3.6 35B-A3B IQ4_NL MTP model now exposes five deliberate
context profiles through an authenticated OpenAI-compatible selector on
`ai3090`:

| Model ID | llama.cpp context |
| --- | ---: |
| `qwen35b-8k` | 8,192 (default) |
| `qwen35b-16k` | 16,384 |
| `qwen35b-32k` | 32,768 |
| `qwen35b-64k` | 65,536 |
| `qwen35b-128k` | 131,072 |

The selector listens at `http://10.0.1.20:8001/v1`, uses the same bearer
credential as the former port-8000 service, and retains `primary` as an 8k
compatibility alias. Port 8000 continues to serve the currently active
llama.cpp instance for existing Pilot clients.

## Client wiring

- Open WebUI on `10.0.1.86` now uses the selector as its existing RTX 3090
  OpenAI source, so all five IDs appear in its model chooser.
- Hermes on `10.0.1.86` has the same provider and IDs, with `qwen35b-8k` as
  its default. Hermes internally requires a 64k-capable model declaration, so
  its provider metadata describes the native Qwen model family as 64k capable;
  llama.cpp still enforces the selected profile's actual 8k/16k/32k/64k/128k
  limit.

## Operational behaviour

There is exactly one 35B server on the 24GB 3090. Selecting a different
context is therefore a deliberate, serialized context switch: the selector
finishes the current request, restarts `llama-35b@<context>.service`, waits for
health, then sends the requested completion. Switching to larger profiles can
take tens of seconds; 8k stays loaded by default.

## Rollback

To return to the original static 8k service:

```bash
sudo systemctl disable --now llama-context-gateway llama-35b@8192
sudo systemctl enable --now llama-35b
```

To restore vLLM instead:

```bash
sudo systemctl stop llama-context-gateway 'llama-35b@8192'
sudo systemctl start vllm
```
