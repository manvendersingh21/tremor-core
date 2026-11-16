# Implementation Plan: CHIMERA

Ticked `[x]` only where evidence exists. Evidence is a test or a bench file. `.venv/bin/python -m pytest -q tests` was run on 2026-11-14: 86 passed, 1 deselected, with other workers' uncommitted changes in the tree.

## Wave 1: Core (`packages/chimera-core`)
- [x] 1. Exact and semantic cache (`cache/`)
  - Threshold is **0.97**, not 0.94. Evidence: `tests/test_router.py`; wrong answers at 0.94 in `bench/results_gpu.md`.
  - [ ] 1a. Retune thresholds on a larger prompt set and rerun.
  - _Requirements: 1.1, 1.2, 1.3_
- [x] 2. Local draft backend with logprob confidence gate (`inference/local_draft.py`)
  - Qwen2.5-3B q4_k_m on llama.cpp. Evidence: `tests/test_backends.py`, `bench/results.md` (14 of 30 answered locally).
  - [ ] 2a. Gemma 3 1B/4B on the phone (planned).
  - _Requirements: 2.1, 2.2, 2.3_
- [x] 3. Speculative verifier with rejection sampling
  - Built: `bench/verify_server.py`, `bench/run_spec.py`, `bench/start_verifier.sh`. Evidence: `bench/spec_results.md`. Measured result is a loss: 4.5x to 7x slower than plain Ollama over the internet, round trip about 0.6 s, alpha 0.68 at K=4.
  - [x] 3a. Ran `bench/run_spec.py`; result in `bench/spec_results.md`.
  - [ ] 3b. Run again with a verifier fully on GPU and a round trip under about 50 ms.
  - _Requirements: 3.1, 3.2, 3.3_
- [x] 4. Risk firewall (`firewall/risk_scorer.py`)
  - Evidence: `chimera_risk_score` MCP tool; firewall tests in `tests/`. Rule list only.
  - _Requirements: 5.3_
- [x] 5. Telemetry (`inference/telemetry.py`)
  - JSONL with tier, tokens, latency, dollars. Evidence: `bench/results*.md`, `tests/test_hud.py`.

## Wave 1b: Added after the first benchmarks
- [x] 6. Ladder router (`ladder.py`, `config.py`): local -> GPU -> Crusoe top, escalate one tier on a failed check. Evidence: `tests/test_ladder.py`.
  - [x] 6a. Measured with `bench/run_ladder.py`. Evidence: `bench/results_ladder.md` (top tokens -45.1% for gpt-oss-120b, -65.6% for the 763B model; median latency higher; one pass).
- [x] 7. GPU middle tier: Ollama `qwen3:30b-instruct` on a V100 over an SSH tunnel. Evidence: `bench/results_gpu.md`.
- [x] 8. Heavy-task handoff with no brief or brief <= 200 tokens (`inference/handoff.py`).
  - [x] 8a. Short brief measured on 4 heavy prompts. Evidence: `bench/results_ladder.md` (brief added 827 input tokens, cut 402 output tokens, same dollars, 4.4x slower). The brief is now off by default.
- [x] 9. Benchmarks: Mac cascade vs Crusoe only (`bench/results.md`) and vs GPU only (`bench/results_gpu.md`).
  - [ ] 9a. Rerun the GPU handoff tail (about 300 s for 4 handoffs). `bench/results_ladder.md` places the stall inside the 30B call, not the Mac or Crusoe. It was blamed on a shared box; the real cause was CPU threads (4-CPU quota, 149 Ollama threads, `bench/results_akash_tuning.md`). Not rerun on the tuned box.

## Wave 2: Surfaces
- [x] 10. Kiro CLI, MCP server and hook interceptor (`apps/kiro-trimmer/`). Evidence: `tests/test_chimera_app.py`.
  - [x] 10a. The 2 failing tests pass. Evidence: pytest run in the header (86 passed).
  - [ ] 10b. `github_autopatcher.py` (issue webhook -> Tavily -> patch -> PR). Planned.
  - _Requirements: 4.1, 4.2_
- [ ] 11. Phone modules: `unknown_caller`, `marketplace_bot`, `mobile_hotfix`, `ride_arbitrage`, `supervisor_graph.py`. Planned, not started.
  - _Requirements: 5.1, 5.2, 5.3_

## Wave 3: HUD and CI
- [x] 12. HUD: static HTML plus Python SSE server (`apps/phantom-phone/hud-web/`). Evidence: `tests/test_hud.py`.
  - [ ] 12a. Phone video, voice transcript and trace tabs. Planned.
  - _Requirements: 1.2, 3.2_
- [x] 13. CI: `.github/workflows/ci.yml` runs pytest on Python 3.11 and 3.12. Evidence: file exists, and `gh run list --branch dev` showed two successful `ci` runs on 2026-11-14 (ids 43567996930, 43567920967).
  - [x] 13a. Green run on `dev` confirmed by those two runs. Recheck after each push.

## Research (docs/research.md)
- [x] 15. Paper sweep and feasibility table. Evidence: `docs/research.md`.
- [x] 16. Semantic-cache false-hit guard (`cache/guard.py`, config `cache.guard`, off). Evidence: `tests/test_cache_guard.py`, `bench/results_research_cache.md` (wrong hits 4 -> 2 of 34 at 0.97, 800 QQP pairs).
- [x] 17. Learned router (`learned_router.py`, `bench/train_router.py`, config `thresholds.learned_router`, off). Evidence: `tests/test_learned_router.py`, `bench/results_research_router.md`. Measured: no gain over the confidence gate, stays off.
  - [ ] 17a. Retrain on 1,000+ graded real calls including the GPU tier.
  - [ ] 17b. Measure `thresholds.confidence` 0.95 on the full ladder.

## Added 2026-11-14
- [x] 18. Tier pool (`tiers.py`, `[[tiers]]` in `chimera.toml`). Evidence: `tests/test_tiers.py`. No benchmark.
- [x] 19. Gateway (`apps/gateway/`, `deploy/`). Evidence: `tests/test_gateway.py`. Gateway overhead not measured.
- [x] 20. Shared Supabase cache (`cache/pgvector_cache.py`, `deploy/sql/`). Evidence: `tests/test_pgvector_cache.py`, `docs/vector-store.md` (hit rate 0.80, 48 of 60 GPU calls avoided, 0 false hits, lookup 121 ms vs 8.9 ms local; one run, 6 near-miss prompts).
- [x] 21. Spec+ (`inference/specplus.py`). Evidence: `tests/test_specplus.py`, `bench/results_specplus.md` (1.14x to 1.22x over best plain spec, against a stand-in target only).
  - [ ] 21a. Measure Spec+ against a real Qwen-family verifier with a short round trip.
- [x] 22. Modal H200 tier (`deploy/modal/vllm_server.py`). Evidence: `bench/results_modal.md` (gpt-oss-120b served; pair runs A and D; the H200 lost on cost and speed, so it is off by default. Qwen3.5-122B never served).
- [ ] 23. Android phone tier (`docs/android.md`, `scripts/`). Setup written. No phone run yet, so no evidence.
- [ ] 24. Real-data suite (`bench/run_suite.py`, `bench/results_suite.md`). `bench/results_suite.md` does not exist yet.

## Next
- [ ] 14. Repeat the benchmarks, retry the Modal tier, and keep `.kiro/steering/product.md` in line with `bench/*.md`.

## Property-based tests (Kiro correctness; `design.md` section 5)
- [x] 25. PBT: caches and guard (P1-P6). `tests/test_props_cache.py`.
  - _Requirements: 1.1, 1.2, 1.5, 1.6_
  - [ ] 25a. PBT fix: `cache/exact_cache.py` `prompt_hash` NUL collision (xfail test). Owner: cache.
  - [ ] 25b. PBT fix: `cache/guard.py` `consistent(a, a)` false for apostrophe entities (xfail test). Owner: cache.
- [x] 26. PBT: router, ladder, pool (P7-P9). `tests/test_props_router.py`.
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ] 26a. PBT fix: `ladder.py` caches a top answer that failed `check` (xfail test). Owner: router.
- [x] 27. PBT: speculative accept rule incl. chi-square on a 4-token vocab (P10, P11). `tests/test_props_spec.py`.
  - _Requirements: 3.2, 3.3_
- [x] 28. PBT: scrub, risk scorer, memory, stats shape, chat firewall (P12-P17). `tests/test_props_safety.py`.
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 9.1, 9.2_
  - [ ] 28a. PBT fix: `memory/safety.py` card glued to `_` or a letter is not scrubbed (xfail test). Owner: memory.
- [x] 29. PBT: `/api/chat` event shapes (P18). `tests/test_props_api.py`.
  - _Requirements: 9.3_
- [ ] 30. PBT: bank lookup never serves without passing tests (P19). Write when the bank exists.
