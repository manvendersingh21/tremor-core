# Architecture

## Tiers

| Tier | What | Answers when |
|---|---|---|
Product ladder (tier pool, `use_pool = true` in `chimera.example.toml`):

| Tier | What | Answers when |
|---|---|---|
| 0 | Shared Supabase cache (Postgres + pgvector): exact hash, then cosine >= 0.97 (0.94 served wrong answers in [results_gpu.md](../bench/results_gpu.md)) | the prompt or a near copy was answered and verified before |
| 1 | GPU 30B, self-hosted: Ollama `qwen3:30b-instruct` on a V100 through an ssh tunnel | mean token probability >= 0.95 (Ollama logprobs), or its own self-check says OK when there are no logprobs |
| 2 | Optional Modal H200: `gpt-oss-120b` (off by default) | tier 1 is unsure, times out or fails |
| 3 | Crusoe DeepSeek-V4.1-Flash (763B, the largest on the key) | the task is heavy, or every tier below failed or was unsure |

Before the 30B call, N+1 memory retrieves solved examples as few-shot context. After a checked answer from a big tier (763B or 120B), the answer is stored as teacher data ([memory.md](memory.md)).

Experiment tiers, off: the Mac Qwen2.5-3B (it was tier 1 in the first benchmarks below and in the speculative-decoding benches) and a Qwen phone tier (written, not tested). The older `LadderRouter` (`ladder.py`: cache, Mac 3B, GPU 30B, Crusoe top) is what the ladder benchmark measured.

## Why KV caches stay local

A KV cache is large (megabytes per thousand tokens) and tied to the exact weights and layout of one model. Sending it would cost more than recomputing it, and it cannot be reused by a different model. So each side keeps its own prefix cache warm (llama.cpp prompt cache on the Mac, vLLM or SGLang prefix caching on the GPU). Only `[token_id, logprob]` pairs cross the network: a few bytes per token.

## Same-family tokenizer rule

Speculative verification compares the draft model's probability for a token id with the target's probability for the same id. That only means something if both models share one vocabulary. So draft and target must be the same family: Gemma 3 with Gemma 3, Qwen with Qwen. Mixed families can still cooperate by handoff, because handoff sends text.

## Brief handoff vs. token verification

| | Handoff with brief | Token verification |
|---|---|---|
| What is sent | text: the task plus a brief written by the small model | draft token ids and logprobs |
| Model pairing | any pair | same family only |
| Output | the big model's own answer | same distribution as the big model |
| Fits | heavy tasks the small model should not attempt | tasks the small model can mostly draft |
| Cost seen | brief and draft add input tokens: heavy tasks cost more ([results.md](../bench/results.md)). A 30B brief cost the same dollars and was 4.4x slower ([results_ladder.md](../bench/results_ladder.md)) | plain: 4.5x to 7x slower than no speculation over the internet ([spec_results.md](../bench/spec_results.md)) |

Use handoff when the families differ or the task is heavy. Use verification only when the round trip is short. Over the internet the round trip alone was about 0.6 s, which cancelled the gain. Heavy tasks now go up with no brief by default. Some hosted APIs (Crusoe) reject the `echo` parameter, so they cannot score draft tokens in one pass. Verification needs a server that can, such as the repo's verifier on the GPU box (`bench/verify_server.py`).

## Telemetry

Every call returns a `Telemetry` record (`packages/chimera-core/inference/telemetry.py`):

| Field | Meaning |
|---|---|
| `tier_used` | `exact_cache`, `semantic_cache`, `local`, `cloud_verified`, `cloud_handoff`, `gpu` or `top` |
| `tokens_saved` | tokens that did not go to the large model |
| `acceptance_rate_alpha` | share of draft tokens the verifier accepted (0 to 1), when verified |
| `latency_ms` | wall time of the call |
| `dollars_saved` | estimated list-price saving |
| `cloud_tokens`, `local_tokens`, `gpu_tokens` | tokens used on each side |

`TelemetryTracker` keeps totals and can write JSON lines for the HUD.

## Firewall

`firewall/risk_scorer.py` scores a proposed GUI tap or command from 0 to 100 with a rule list. A score of 70 or more needs approval by a one-time token sent back by voice or SMS.

## Tier pool

A company lists its hardware as `[[tiers]]` in `chimera.toml` (`packages/chimera-core/tiers.py`). Each entry has a device (`phone`, `laptop`, `gpu`, `cloud`), a backend, a model family, a `max_complexity` from 0 to 1, a price per 1k tokens (0 for owned hardware) and an `enabled` flag. Adding a tier is a config edit.

The pool picks the cheapest enabled, healthy tier whose `max_complexity` covers the task. It climbs one tier on low confidence, a timeout or an error. Health checks are cached, and a tier that keeps failing is skipped for a cooldown. Speculative verify is allowed only between tiers of the same `family`.

Small GPU versus large GPU: a small inference GPU (the 30B model on a V100) answers the light and medium work for the price of electricity. A large GPU, added later as `gpu-large`, takes the heavy work that would otherwise go to the cloud. Cloud tiers stay as the last step and the failover. Owned tiers cost 0 per token, so they sort by capability, small first. A cheap cloud model can sort ahead of a pricier one: `cloud-top` is cheaper per token than `cloud-mid`, so `cloud-mid` is only reached when `cloud-top` fails.

Set `use_pool = true` to have `SpeculativeCascadeRouter` route through the pool. Each result fills `Telemetry.per_tier` for the five fixed HUD keys; other tier names are left out of it. `bench/run_loop.py` (`make loop`) runs the prompt mix through the pool and prints tokens per tier. The Android phone tier is in `docs/android.md`.

## Spec+ (cross-device speculative decoding)

`packages/chimera-core/inference/specplus.py` cuts the network cost of draft-here, verify-there decoding. Each feature is a toggle: adaptive K (from alpha and RTT), token-tree drafts, pipelined next-block drafting, free drafts (prompt n-gram copy, cache neighbour), compact binary wire (varint ids, int8 logprobs), and an optional lossy mode (off). Lossless by default: rejection sampling with `min(1, p_t/p_d)` and residual resampling. Results and caveats: `bench/results_specplus.md`. Run: `.venv/bin/python bench/run_specplus.py`.

Measured against a stand-in target (the 3B with a sharpened distribution), not a real big model: 1.14x to 1.22x over the best plain spec at a simulated round trip of 0 to 300 ms, and still below the big model alone (13.36 against 19.27 tok/s at 150 ms) ([results_specplus.md](../bench/results_specplus.md)). No speedup over plain Ollama is claimed. Real plain spec was slower than plain Ollama ([spec_results.md](../bench/spec_results.md)).

## Gateway

`apps/gateway/` is an OpenAI-compatible HTTP service in front of `LadderRouter.generate()`. Apps change `base_url` and the key. Keys are stored as hashes, each tenant has its own cache namespace, and `/metrics` gives Prometheus text by tenant and tier. Streaming replays a finished answer, so first-byte latency equals full-answer latency. See [deploy/README.md](../deploy/README.md). No benchmark of gateway overhead exists.

## Shared cache (Supabase)

`cache/pgvector_cache.py` stores prompts, 384-number embeddings and answers in Postgres with pgvector, so a second machine reads what the first wrote. Only rows marked verified are served. A lookup that takes over 300 ms, or an error, falls back to local SQLite. Measured once: hit rate 0.80, 48 of 60 GPU calls avoided on a second machine, 0 false hits. A lookup took a median 121 ms against 8.9 ms local, and a 150 ms budget fell back on 59 of 60 lookups ([vector-store.md](vector-store.md)). The exact-hash cache in the router is still local.

## Cache guard and learned router (both off)

`cache/guard.py` rejects a cache hit when numbers, negation or entities differ. On 800 QQP pairs at 0.97 it cut wrong hits from 4 to 2 and recall from 10.1% to 9.1% ([results_research_cache.md](../bench/results_research_cache.md)). `learned_router.py` predicts whether the 3B will be right. On 180 graded prompts it reached 70.0%, the same as the confidence gate ([results_research_router.md](../bench/results_research_router.md)).

## Modal tier (`gpu-large`)

`deploy/modal/vllm_server.py` runs vLLM on a Modal H200 that scales to zero. Qwen3.5-122B never served a request. `gpt-oss-120b` served after a 376 s cold start: in one pair of runs it took all 25 calls off the 763B with the same 24/24 asserts, but cost about $0.11 of H200 time against $0.0058 of 763B tokens, and the median rose from 728 ms to 1,352 ms ([results_modal.md](../bench/results_modal.md)). It is off by default.

## Android tier

`phone-3b` runs a small Qwen model on the phone through Termux and reaches it over USB ([android.md](android.md)). Not tested on a phone yet. Gemma 3 is a possible stand-alone tier but cannot verify for a Qwen target.
