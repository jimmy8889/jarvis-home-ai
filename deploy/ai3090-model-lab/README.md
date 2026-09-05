# ai3090 llama.cpp model lab

These scripts expose the explicit `fast`, `quality`, `agent-iq4-xs`, and
`agent-iq4-nl` profiles on loopback port 8081. They never stop production
vLLM; `llama-profile` refuses to run while vLLM is active or the GPU is busy.

Deploy the directory to `~/pilot-model-lab/scripts`, then run:

```bash
~/pilot-model-lab/scripts/download-35b
~/pilot-model-lab/scripts/check-models
```

During an approved maintenance window, stop vLLM with an administrator account,
then launch one profile in the foreground:

```bash
~/pilot-model-lab/scripts/benchmark-profile agent-iq4-nl --mtp
```

Each run waits for the endpoint, records GPU telemetry before and after, saves
the eight-case result JSON under `~/pilot-model-lab/results`, and stops its
temporary server. Restart `vllm` before ending the maintenance window. The
profile is text-only while MTP is enabled and serves exactly one request slot.

`run-35b-after-download` is a root-only deferred runner. It keeps vLLM active
while the two 35B files download, verifies their exact sizes, then runs both
IQ4 profiles in normal and MTP mode before restoring vLLM.

`promote-35b-production` installs `llama-35b.service`, exposes the tested
IQ4_NL MTP profile on the existing authenticated port 8000 under model alias
`primary`, and retains `vllm.service` as the rollback target.

`benchmark-35b-context-windows` is a root-only maintenance-window runner for
the production IQ4_NL MTP model. It tests 8k, 16k, 32k, 64k and 128k with a
75%-filled retrieval prompt, records actual API token usage and GPU telemetry,
and restores `llama-35b.service` regardless of individual-window failures.

`enable-context-selector` promotes the static 8k production unit to the
`llama-35b@<context>` template and installs an authenticated OpenAI-compatible
selector on port 8001. It publishes `qwen35b-8k`, `qwen35b-16k`,
`qwen35b-32k`, `qwen35b-64k`, and `qwen35b-128k`; `primary` remains an alias
for 8k. Only one profile can be resident on the 3090. Selecting another model
ID waits for that request, then reloads llama.cpp at the requested context.
