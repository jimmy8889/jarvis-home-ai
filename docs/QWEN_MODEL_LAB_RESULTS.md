# Qwen model lab results

Date: 2026-08-05

## Environment

- Host: `ai3090` (`10.0.1.20`)
- GPU: NVIDIA RTX 3090, 24 GB
- Runner: `llama.cpp` `b10273`, Vulkan backend
- Candidate format: Q4_K_M GGUF, MTP-labelled files
- Production vLLM was left running on port 8000 throughout these checks.

## Load and functional checks

Both candidates loaded successfully as standalone base models in
`llama-server`:

- Qwen3.5 9B: MTP tensors were detected as unused and ignored; base model
  loaded and served on an isolated port.
- Qwen3.6 27B: MTP tensors were detected as unused and ignored; base model
  loaded and served on an isolated port.

The OpenAI-compatible API returned valid responses from both models. With
`chat_template_kwargs.enable_thinking=false`, the Qwen3.6 27B CPU check
returned `4` to `What is 2+2?` in 1.5 seconds and generated the energy-balance
answer at about 3.45 tokens/second on CPU. This validates the model artifact
and chat template, not production throughput.

The Qwen3.5 9B CPU benchmark completed the five Pilot prompts. It averaged
roughly 15–28 seconds per request at the tested output length and produced
usable answers. The model correctly declined to invent live Home Assistant
state when no tools were supplied, which is desirable for the tool-routed
assistant path.

## GPU benchmark status

The maintenance window completed successfully. The live vLLM process was
stopped, each candidate was tested on the RTX 3090, and vLLM was restarted and
returned HTTP 200 on `/health` afterward. The benchmark used 16,384 context
tokens, one request at a time, Q4_K_M, and disabled hidden thinking so the
comparison measured the serving path rather than unbounded reasoning.

### Qwen3.5 9B

- Normal GPU mode: approximately 100 tokens/second at generation peak.
- Five-case Pilot benchmark: zero request failures, roughly 1.7–3.1 seconds
  per case at the tested output lengths.
- MTP mode activated successfully. Draft acceptance was approximately 0.43–
  0.53 in the observed cases and performance was mixed, so it is not an
  automatic win.

### Qwen3.6 27B

- Normal GPU mode: approximately 40 tokens/second at generation peak.
- Five-case Pilot benchmark: zero request failures, roughly 1.2–6.7 seconds
  per case at the tested output lengths.
- MTP mode activated successfully with draft acceptance ranging roughly from
  0.58 to 0.76 in the observed cases. It improved some long responses, but
  should still be validated against deterministic tool-call prompts.

The service was restored with:

```bash
sudo systemctl start vllm
```

The production health endpoint returned HTTP 200 after restart. Do not run
both model servers against the 3090 at the same time.

## Initial recommendation

Use the official/native vLLM model as Pilot's production fast path and keep
these GGUF derivatives as explicitly selected experimental profiles until the
GPU benchmark and tool-safety corpus are complete. For the GGUF artifacts,
llama.cpp is the correct serving stack; converting them solely to force vLLM
would add risk without improving the first test.
