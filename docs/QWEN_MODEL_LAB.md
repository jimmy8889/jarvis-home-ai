# Qwen Model Lab

Pilot's 3090 model lab is intentionally limited to Qwen3.5 and Qwen3.6. Qwen
Coder and unrelated model families are not part of the production comparison.

## Frontier-distilled candidates

These are the only community candidates currently in the Pilot shortlist:

- [DavidAU/Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF](https://huggingface.co/DavidAU/Qwen3.6-27B-Fable-Fusion-711-Uncensored-Heretic-NM-DAU-NEO-MAX-MTP-GGUF)
- [DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF](https://huggingface.co/DavidAU/Qwen3.5-9B-The-Defiant-Fable-Uncensored-Heretic-NEO-IMATRIX-MAX-MTP-GGUF)
- [unsloth/Qwen3.6-35B-A3B-MTP-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-MTP-GGUF), using only `IQ4_XS` and `IQ4_NL` on this host.

They are treated as experimental derivatives, not automatically trusted
production models. The names indicate GGUF/MTP artifacts, so they cannot be
assumed to run in the existing vLLM service. The lab must first inspect the
model metadata and then select an appropriate isolated runner. No GGUF model
is promoted into the production vLLM path without a validated conversion or
native vLLM-compatible artifact.

The first comparable quantisation is `Q4_K_M`: approximately 18.5 GB for the
Qwen3.6-27B file and 7.0 GB for the Qwen3.5-9B file. These sizes leave no safe
room to download or load the 27B candidate alongside the current production
model on the 24 GB GPU. Candidate trials therefore require an explicit
maintenance window and an isolated runner; they must never compete with the
live vLLM process.

The 35B-A3B model is a 35B-total/3B-active MoE, but total model and KV-cache
memory still matter. Its `Q4_K_M` file is approximately 22.7 GB and is excluded
from the 24 GB 3090. The `IQ4_XS` (about 18.2 GB) and `IQ4_NL` (about 18.5 GB)
files are the supported 35B trials, initially at 8,192 context tokens. CPU
offload is not an acceptable substitute for GPU-resident inference.

## Official baselines

The comparison must include the official Qwen3.5/Qwen3.6 releases that fit the
3090, including the smaller Qwen3.5 models, Qwen3.6-27B, and Qwen3.6-35B-A3B.
The official model should remain the safety and tool-calling baseline for every
derivative test.

## Test contract

Every candidate receives the same Pilot corpus:

- Home Assistant read and control requests.
- Room-aware follow-up requests.
- Energy, tariff, and Tesla explanations.
- Music Assistant and Denon routing.
- Meeting summary and action extraction.
- Long-context retrieval.
- Tool failure, retry, and prompt-injection cases.

Record time-to-first-token, tokens per second, end-to-end voice latency,
invalid-tool-call rate, hallucinated entity rate, context retention, VRAM,
startup time, and maximum stable context.

## Promotion rules

The production 3090 keeps one model loaded at a time. A derivative may become a
profile candidate only if it matches the official baseline on action safety and
tool correctness. Popularity is useful for choosing what to try, but it is not
an acceptance criterion.

## Runner decision and current trial

For these exact community GGUF files, `llama.cpp` is the correct native
runner. The CUDA/Vulkan `llama-server` OpenAI-compatible API preserves Pilot's
existing client contract and can expose `draft-mtp` when the model and build
support it. vLLM remains the preferred production runner for native
Hugging Face safetensors/GPTQ models, where it provides stronger batching and
serving controls. The two paths should remain separate rather than converting
or forcing a GGUF into vLLM.

The 3090 lab uses `llama-server` on loopback port 8081 and keeps the live vLLM
service on port 8000 untouched. Its launcher refuses to run while vLLM is
active or the GPU is already in use; it does not stop vLLM itself. The Qwen3.5 MTP-labelled Q4_K_M file has been
loaded successfully by llama.cpp; its extra MTP tensors are ignored when it is
used as a standalone base model, so the benchmark records both normal
generation and a separate speculative-decoding trial. GPU throughput tests
require a maintenance window because the production vLLM model already
consumes almost all 24 GB of VRAM.

MTP files are tested as draft/speculative models only when the installed
llama.cpp build and model metadata activate that path. They are not promoted
as standalone production assistants without tool-safety and determinism
checks.

The 35B profile is tested both normally and with `draft-mtp`, depth two,
Flash Attention, and one server slot. MTP trials are text-only: no vision
projector and no parallel slots greater than one. vLLM-GGUF may receive a
short compatibility trial with its out-of-tree GGUF plugin and the upstream
tokenizer, but it is not a deployment candidate while that path remains
experimental.
