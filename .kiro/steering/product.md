# Product Overview: CHIMERA (Speculative Edge-to-Cloud Router)

## Vision
Answer each LLM call at the cheapest tier that can do it. Order: shared Supabase cache, a self-hosted 30B on the user's GPU, optionally a 120B on a Modal H200, then the largest cloud model (Crusoe 763B). Big-model answers are stored as teacher data (N+1 memory) so the 30B can retrieve solved examples next time. The Mac 3B of the first benchmarks is an experiment tier, off. Log tier, tokens, latency and dollars for every call. Score risky actions (pay, delete, merge) from 0 to 100 and hold them for approval at 70 or more.

## Measured results (single runs, 30 prompts, no repeats)
The earlier "60-80% token savings" target is **mostly not met**: only the 763B top model in the ladder run reached it (65.6%). Real numbers:

| Comparison | Result | File |
|---|---|---|
| Mac 3B + cache + Crusoe 27B vs cloud only | 8 of 30 calls reached the cloud. Cost 29% lower at list price. Wall time 145 s vs 31.8 s. Small coding 5/6 vs 6/6. | `bench/results.md` |
| Mac 3B + cache + GPU 30B vs GPU only | GPU calls 30 -> 9. GPU tokens **+37%** (9,334 vs 6,809). Median latency 4.9 s -> 1.9 s. Passed 20/24 vs 24/24. | `bench/results_gpu.md` |
| Ladder vs top model only (gpt-oss-120b) | Top tokens -45.1%, top $ -40.8%. Median 2.2 s vs 0.9 s, p90 46 s vs 3.9 s. Code checks 6/6. | `bench/results_ladder.md` |
| Ladder vs top model only (763B DeepSeek-V4.1-Flash) | Top tokens -65.6%, top $ -67.3%. 4 of 30 reached the top. Median 1.9 s vs 0.7 s. | `bench/results_ladder.md` |
| Speculative verify over the internet (3B drafts, V100 30B verifies) | **4.5x to 7x slower** than plain Ollama. Round trip about 0.6 s, alpha 0.68 at K=4. | `bench/spec_results.md` |
| Spec+ vs best plain spec | 1.14x to 1.22x, against a stand-in target, not a real big model. Still below the big model alone. | `bench/results_specplus.md` |
| Shared Supabase cache, second machine | Hit rate 0.80, 48 of 60 GPU calls avoided, 0 false hits. Lookup 121 ms vs 8.9 ms local. | `docs/vector-store.md` |
| Learned router, 180 graded prompts | 70.0%, same as the confidence gate. Off. | `bench/results_research_router.md` |
| Modal H200 gpt-oss-120b vs 763B only | 763B calls 25 -> 0, asserts 24/24 both. But about $0.11 of H200 time vs $0.0058 of 763B tokens, median 1,352 ms vs 728 ms. Off by default. Qwen3.5-122B never served. | `bench/results_modal.md` |

What worked: cache hits cost $0 and answer in under 130 ms. 14 of 30 prompts were answered locally.
What failed: long briefs raised input tokens on heavy tasks. Cache threshold 0.94 served wrong answers. The ladder and plain spec are slower than calling the top model. The GPU handoff tail is unexplained, and the ladder's slow calls came from a shared GPU box.
Fixes in code: semantic threshold 0.97, heavy tasks skip the 3B, no brief by default. The ladder run measured the fixes: no wrong cached answer, and a 30B brief gave no dollar saving and was 4.4x slower.

## Surfaces
1. **Kiro (built):** CLI, MCP server and hook interceptor in `apps/kiro-trimmer/`.
2. **Web page (built):** one page on 127.0.0.1:8765 (`make web`): walk the castle with WASD, the live dashboard in the Observatory, evals in the Ledger, and a chat with the bat agent that shows each routing step (`site/`).
3. **Gateway (built):** OpenAI-compatible service for companies, keys per tenant.
4. **Android tier (written, not tested on a phone).**
5. **Phone agent (planned):** DND call handling, Marketplace, ride prices, mobile hotfix. Not built.

## Pillars
- **Honest token economics:** report tokens and dollars per tier, including the cases where the cascade costs more.
- **Same-family speculative verification:** only `[token_id, logprob]` arrays cross the network. Needs a llama.cpp verifier.
- **Deterministic safety gate:** rule-based score 0-100; one-time token at 70 or more. It is a rule list and can miss unusual phrasing.
