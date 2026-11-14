# Architecture

## Tiers

| Tier | What | Answers when |
|---|---|---|
| 0 | Exact cache (hash of the prompt) and semantic cache (embedding, cosine >= 0.94) | the prompt or a near copy was seen before |
| 1 | Small local model: Qwen2.5-3B on a Mac, Gemma 3 1B/4B planned for the phone | the task is not heavy and mean token logprob confidence is >= 0.85 |
| 2 | GPU box: Qwen3-30B | tier 1 is unsure, a check fails, or the task is heavy |
| 3 | Large Crusoe model | the task is heavy, or tier 2 says ESCALATE, or a check fails |

Tier choice goes in this order: rules first (`complexity_score`, heavy threshold 0.6), then local logprob confidence, then a failed check that moves up one tier. The code is in `packages/chimera-core/router.py` and `ladder.py`.

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
| Cost seen | brief and draft add input tokens: heavy tasks cost more ([results.md](../bench/results.md)) | not yet measured |

Use handoff when the families differ or the task is heavy. Use verification when the small model drafts well and the target is its family. Some hosted APIs (Crusoe) reject the `echo` parameter, so they cannot score draft tokens in one pass. Verification needs a server that can, such as the repo's verifier on the GPU box (`bench/verify_server.py`).

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
