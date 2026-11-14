# GPU benchmark results

Measured by `bench/run_bench_gpu.py` on 30 prompts (`bench/prompts.jsonl`). Raw rows: `bench/results_gpu.csv`.

## Setup
- GPU tier: Ollama `qwen3:30b-instruct` (Q4_K_M) on a Tesla V100 32 GB, reached through an ssh tunnel on 127.0.0.1:11435. `think=false`, `num_predict`=2500.
- G = every prompt goes to the GPU. H = `SpeculativeCascadeRouter`: exact + semantic cache, local Qwen2.5-3B (llama.cpp, Mac), GPU as the cloud tier with a local-written brief.
- Model load on first call (not in the numbers below): G first call 545 ms (load 1 ms); H first call 691 ms (load 2 ms).
- Quality = `expect` keyword match or unit tests (24 graded prompts). No LLM grader.

## G vs H
| | G: GPU only | H: Mac cascade + GPU |
|---|---|---|
| GPU calls | 30 | 9 |
| GPU prompt tokens | 1352 | 5646 |
| GPU completion tokens | 5457 | 3688 |
| GPU tokens total | 6809 | 9334 |
| Local (Mac) tokens | 0 | 4660 |
| Median latency ms | 4929 | 1892 |
| p90 latency ms | 28000 | 304983 |
| Total wall time s | 306 | 1206 |
| Passed | 24/24 | 20/24 |

GPU tokens saved by H: **-2525** (-37.1%). GPU calls saved: 21.

H tier breakdown: cloud_handoff: 9, exact_cache: 3, local: 13, semantic_cache: 5

## GPU time
Wall time is a latency sum, not a GPU-busy time. At an assumed $/hr R, G costs about 0.085*R and H at most 0.335*R (H wall time includes local-model time, so its GPU share is lower). No $/hr was given, so no dollar figure is stated.

## Rerun
```
ssh -f -N -L 127.0.0.1:11435:127.0.0.1:11434 -i ~/akash-key2/id_rsa -o IdentitiesOnly=yes -p 30803 root@provider.zencloud.eu
.venv/bin/python bench/run_bench_gpu.py G
.venv/bin/python bench/run_bench_gpu.py H     # needs bench/serve_local.sh running
.venv/bin/python bench/run_bench_gpu.py report
pkill -f "ssh -f -N -L 127.0.0.1:11435"       # close the tunnel
```

## Verdict
- GPU calls fell from 30 to 9 (21 saved: 3 exact-cache, 5 semantic-cache, 13 answered by the local 3B). Median latency fell from 4.9 s to 1.9 s.
- GPU **tokens** did not fall. H used 9334 vs 6809 for G (+37%). Cause: the 9 handed-off prompts carry the local brief plus the local draft (prompt tokens 1352 -> 5646), and that extra input outweighs the completion tokens saved (5457 -> 3688). The six heavy prompts had the largest outputs in both modes, so skipping the easy ones saves little GPU output.
- Quality dropped: 20/24 vs 24/24 graded. Misses in H: r2 (exact cache), p4 (semantic cache), c3 (local 3B). The cache served a wrong answer for p4 and r2 at the current thresholds.
- Latency tail is worse in H: p90 and total wall time are far higher, because 4 handoffs took about 300 s each (G took 27 to 45 s for the same prompts with similar output size, about 500 tokens). Cause not found. The box runs other services and may have been busy; not checked. Treat H's tail latency as unreliable until rerun.
- First-call load time shows about 0.5 s because the model was already resident in Ollama. No cold-load figure was measured.
- Verdict: on this prompt set the cascade saves GPU calls and easy-prompt latency, but not GPU tokens, and it loses some quality. To save tokens, send the heavy prompt without the brief and draft (or a short brief), and raise the cache thresholds. Single run, 30 prompts, no repeats.
