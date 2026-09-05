# Qwen3.6 35B IQ4_NL MTP context benchmark

Date: 2026-08-05  
Host: `ai3090`, RTX 3090 24 GB  
Runner: llama.cpp b10273, Vulkan, one slot, Flash Attention, MTP depth two

Each configured window used an approximately 75%-filled retrieval probe. The
API-reported prompt token count below is authoritative; every probe returned
the embedded marker exactly.

| Configured window | Prompt tokens | Retrieval | TTFT | Generation |
| ---: | ---: | --- | ---: | ---: |
| 8,192 | 6,196 | pass | 2.09 s | 172.2 tok/s |
| 16,384 | 12,341 | pass | 3.94 s | 178.4 tok/s |
| 32,768 | 24,629 | pass | 7.84 s | 162.5 tok/s |
| 65,536 | 49,205 | pass | 16.75 s | 145.9 tok/s |
| 131,072 | 98,358 | pass | 39.72 s | 127.2 tok/s |

The 128k configuration successfully loaded and completed its 98k-token probe;
the test does not claim a full 128k input was exercised. The benchmark is
single-user/single-slot. It does not establish multi-user concurrency capacity.

## Operational recommendation

Keep 8k for ordinary short interactions. Use 32k as the practical coding and
Hermes default when repository context matters. Use 64k for deliberately large
documents. Reserve 128k for explicit long-context work, since its prefill
latency is about 40 seconds and it leaves less VRAM headroom.
