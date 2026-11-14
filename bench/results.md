# Cascade vs cloud-only benchmark

30 prompts, one pass per mode, run on 2026-11-13. All numbers below come from `bench/results.csv` and `bench/summary.json` (written by `bench/run_bench.py`). Cloud token counts are the `usage` fields Crusoe returned.

## Setup

| Part | What |
|---|---|
| Hardware | MacBook, Apple M4, 16 GB RAM, about 2 GB disk free |
| Local model | `Qwen2.5-3B-Instruct`, GGUF `q4_k_m` (2.1 GB), llama.cpp build b12375 (`llama-server`, Metal), ctx 4096, `127.0.0.1:8080` only |
| Cloud model | `Qwen/Qwen3.8-27B` (bf16) on Crusoe serverless, `https://api.inference.crusoecloud.com/v1` |
| Cloud price | [Crusoe models list](https://api.inference.crusoecloud.com/v1/models): $0.25 / 1M input, $0.15 / 1M cached input, $2.00 / 1M output |
| Embedder | `sentence-transformers/all-MiniLM-L6-v2` (real, not ONNX), semantic threshold 0.94 |
| Router | `SpeculativeCascadeRouter.generate()`, defaults: heavy threshold 0.6, confidence gate 0.85, local max 512 tokens, cloud max 2500 |
| Cloud mode | Thinking off (`enable_thinking=false`) in both modes. See "Run 1" for why. |
| Brew | `brew install llama.cpp` failed (nested sandbox error), so the official release binary was used. |

Prompt set (`bench/prompts.jsonl`): 10 easy facts, 3 exact repeats, 5 paraphrases, 6 small coding tasks, 6 heavy coding tasks. Cloud-only (A) sends each prompt straight to Crusoe. Cascade (B) goes through the router with fresh, empty caches.

## Totals

| | A: cloud only | B: cascade |
|---|---|---|
| Calls that reached Crusoe | 30 | 8 |
| Cloud input tokens | 1,502 | 5,102 |
| Cloud output tokens | 7,229 | 4,599 |
| Cloud cached tokens | 0 | 0 |
| Cost (list price) | $0.01483 | $0.01047 |
| Median latency | 689 ms | 1,547 ms |
| p90 latency | 2,551 ms | 19,380 ms |
| Total wall time | 31.8 s | 145.0 s |
| Local tokens (B) | 0 | about 3,800 (estimate for handoff briefs) |

Cost of B is 29% lower than A. In dollars that is $0.004 on 30 prompts.

B tiers: local 14, cloud_handoff 8, semantic_cache 5, exact_cache 3.

## By prompt type

| Type | A cloud tokens | B cloud tokens | A cost | B cost | A median ms | B median ms | Quality A | Quality B |
|---|---|---|---|---|---|---|---|---|
| easy (10) | 1,992 | 841 | $0.00361 | $0.00071 | 682 | 715 | 10/10 | 10/10 |
| repeat (3) | 533 | 0 | $0.00095 | $0 | 730 | 0 | 3/3 | 3/3 |
| paraphrase (5) | 833 | 0 | $0.00147 | $0 | 654 | 6 | 5/5 | 5/5 |
| small code (6) | 911 | 0 | $0.00120 | $0 | 517 | 2,429 | 6/6 | 5/6 |
| heavy code (6) | 4,462 | 8,860 | $0.00760 | $0.00976 | 2,329 | 16,054 | 4.2 avg | 4.7 avg |

## Quality

- Easy, repeat, paraphrase: answer must contain the expected fact (keyword check). Both modes 18/18.
- Small coding: the code block was run against asserts in a subprocess. A passed 6/6. B passed 5/6. The miss is `c3` (`flatten`): the local 3B returned a generator, not a list.
- Heavy coding: Crusoe (Qwen3.8-27B, thinking off) graded both answers blind (random order, shown as Answer 1/2) on 1-5. A scores 4,5,3,4,5,4 (avg 4.2). B scores 5,4,5,5,5,4 (avg 4.7). One grader and one pass, so the 0.5 gap is noise, not proof B is better. The same model wrote the answers and graded them, which may favor it.
- All 6 heavy prompts in B were handed to Crusoe, so heavy quality is the 27B model's quality in both modes.
- B was worse on one prompt: `c3`.

## Verdict

**Money: small gain, from caches and easy facts only.**
- The 8 cache hits (3 exact, 5 paraphrase) cost $0 and answered in 0 to 126 ms. These are the clear win. They were placed in the set on purpose (27% of prompts). A real workload may repeat less.
- The 14 local answers cost $0 cloud and were correct on 13 of 14 (the miss is `c3`).
- Heavy tasks cost more in B ($0.00976 vs $0.00760). The local brief and the local draft add input tokens (8 handoffs sent 5,102 input tokens vs 1,502 for A overall) and the cloud answers came out longer.
- Total saving is $0.004 on this set. Savings scale with how many prompts are repeats or easy. The set is small.

**Speed: B is slower except on cache hits.**
- The 27B cloud model answered short prompts in about 0.5 to 0.7 s. The 3B on this Mac took 0.3 to 4 s for the same kind of prompt.
- Handoffs are the slowest path (9 to 29 s) because the 3B first writes a brief at 600 tokens max, then the cloud model answers.
- Total wall time: B 145 s vs A 32 s.

**Where the cascade does not help**
- Heavy coding: more cloud tokens, much more latency, no quality gain that this test can prove.
- Two easy prompts (`e5`, `e7`) fell below the 0.85 confidence gate and went to the cloud with a brief. They cost more than a direct call would have (229 and 328 input tokens vs 23 and 21).
- Any case where cloud latency is already low.

**Limits of this test**
- 30 prompts, one run each, no repeats of runs, so no error bars.
- Cloud cost is list price. Local power and hardware cost are not counted.
- `local_tokens` for handoffs is an estimate (`len(brief)//4`), because the router does not return the brief's real token count.
- Speculative token verification (`cloud_verified`) was not exercised. It needs same-family tokenizer plumbing that is not built.

## Run 1 (thinking on), kept for reference

The first pass left Qwen3.8 thinking on. The 6 heavy prompts used all 3,000 output tokens on reasoning in both modes, `content` came back empty, and the fallback returned the cut-off reasoning text. Those answers were not real answers, so the quality scores from that run are not used. Files: `bench/run1_thinking_on/`. Its totals: A $0.03812 (18,720 output tokens), B $0.03828 (18,454 output tokens). With thinking on there was no cost difference, because reasoning tokens dominate and both modes pay them.

Crusoe usage in this task was about 120k tokens across both runs and the graders.

## Reproduce

Start the local model (loopback only), run the bench, stop the model:

```
bench/serve_local.sh &        # needs ~/models/q3b.gguf and ~/llama.cpp-bin/llama-b12375/
HF_HOME=$KIROCREW_SCRATCH/hf .venv/bin/python bench/run_bench.py
pkill -f llama-server
```

No server is running now. `CRUSOE_API_KEY` is read from `/Users/manubaba/Documents/tremor-core/.env` (listed in `.gitignore`) and never printed or logged.

## Code changes

- `packages/chimera-core/inference/local_draft.py`: `LlamaCppBackend` now wraps prompts in ChatML (Qwen instruct needs it on `/completion`). The `completion_probabilities` parser already matched the current server output; a test now covers it.
- `packages/chimera-core/inference/cloud_verifier.py`: new `CrusoeBackend` (key from env, thinking off by default, falls back to `reasoning_content`, records real `usage`).
- `tests/test_backends.py`: 3 tests with a fake HTTP layer. Full suite: 12 passed.
