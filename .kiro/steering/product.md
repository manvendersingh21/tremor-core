# Product Overview: CHIMERA (Speculative Edge-to-Cloud Router)

## Vision
Answer each LLM call at the cheapest tier that can do it. Order: cache, small model on the user's machine, 30B model on a GPU box, large cloud model. Log tier, tokens, latency and dollars for every call. Score risky actions (pay, delete, merge) from 0 to 100 and hold them for approval at 70 or more.

## Measured results (single runs, 30 prompts, no repeats)
The earlier "60-80% token savings" target is **not met**. Real numbers:

| Comparison | Result | File |
|---|---|---|
| Mac 3B + cache + Crusoe 27B vs cloud only | 8 of 30 calls reached the cloud. Cost 29% lower at list price. Wall time 145 s vs 31.8 s. Small coding 5/6 vs 6/6. | `bench/results.md` |
| Mac 3B + cache + GPU 30B vs GPU only | GPU calls 30 -> 9. GPU tokens **+37%** (9,334 vs 6,809). Median latency 4.9 s -> 1.9 s. Passed 20/24 vs 24/24. | `bench/results_gpu.md` |
| Speculative verify (3B drafts, 30B verifies) | Not measured yet. | `bench/spec_results.md` (not created) |

What worked: cache hits cost $0 and answer in under 130 ms. 14 of 30 prompts were answered locally.
What failed: long briefs raised input tokens on heavy tasks. Cache threshold 0.94 served wrong answers. Handoff latency tail is unexplained.
Fixes in code: semantic threshold 0.97, heavy tasks skip the 3B, brief at most 200 tokens or none. These are not yet measured.

## Surfaces
1. **Kiro (built):** CLI, MCP server and hook interceptor in `apps/kiro-trimmer/`.
2. **HUD (built):** live telemetry page in `apps/phantom-phone/hud-web/`.
3. **Phone agent (planned):** DND call handling, Marketplace, ride prices, mobile hotfix. Not built.

## Pillars
- **Honest token economics:** report tokens and dollars per tier, including the cases where the cascade costs more.
- **Same-family speculative verification:** only `[token_id, logprob]` arrays cross the network. Needs a llama.cpp verifier.
- **Deterministic safety gate:** rule-based score 0-100; one-time token at 70 or more. It is a rule list and can miss unusual phrasing.
