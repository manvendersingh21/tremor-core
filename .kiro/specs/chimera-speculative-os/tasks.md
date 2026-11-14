# Implementation Plan: CHIMERA

Ticked `[x]` only where evidence exists. Evidence is a test or a bench file. `.venv/bin/python -m pytest tests` was run on 2026-11-13: 26 passed, 2 failed (`test_exact_cache_survives_restart_and_telemetry_is_written`, `test_mcp_stdio_tools_list_and_call_round_trip` in `tests/test_chimera_app.py`, still being worked on).

## Wave 1: Core (`packages/chimera-core`)
- [x] 1. Exact and semantic cache (`cache/`)
  - Threshold is **0.97**, not 0.94. Evidence: `tests/test_router.py`; wrong answers at 0.94 in `bench/results_gpu.md`.
  - [ ] 1a. Retune thresholds on a larger prompt set and rerun.
  - _Requirements: 1.1, 1.2, 1.3_
- [x] 2. Local draft backend with logprob confidence gate (`inference/local_draft.py`)
  - Qwen2.5-3B q4_k_m on llama.cpp. Evidence: `tests/test_backends.py`, `bench/results.md` (14 of 30 answered locally).
  - [ ] 2a. Gemma 3 1B/4B on the phone (planned).
  - _Requirements: 2.1, 2.2, 2.3_
- [ ] 3. Speculative verifier with rejection sampling
  - Built: `bench/verify_server.py`, `bench/run_spec.py`, `bench/start_verifier.sh`. Not ticked: `bench/spec_results.md` does not exist, so acceptance rate and speedup are unmeasured.
  - [ ] 3a. Run `bench/run_spec.py` and write `bench/spec_results.md`.
  - _Requirements: 3.1, 3.2, 3.3_
- [x] 4. Risk firewall (`firewall/risk_scorer.py`)
  - Evidence: `chimera_risk_score` MCP tool; firewall tests in `tests/`. Rule list only.
  - _Requirements: 5.3_
- [x] 5. Telemetry (`inference/telemetry.py`)
  - JSONL with tier, tokens, latency, dollars. Evidence: `bench/results*.md`, `tests/test_hud.py`.

## Wave 1b: Added after the first benchmarks
- [x] 6. Ladder router (`ladder.py`, `config.py`): local -> GPU -> Crusoe top, escalate one tier on a failed check. Evidence: `tests/test_ladder.py`.
  - [ ] 6a. Measure the ladder with `bench/run_ladder.py` and write the result.
- [x] 7. GPU middle tier: Ollama `qwen3:30b-instruct` on a V100 over an SSH tunnel. Evidence: `bench/results_gpu.md`.
- [x] 8. Heavy-task handoff with no brief or brief <= 200 tokens (`inference/handoff.py`).
  - [ ] 8a. Measure token savings with the short brief. Not measured.
- [x] 9. Benchmarks: Mac cascade vs Crusoe only (`bench/results.md`) and vs GPU only (`bench/results_gpu.md`).
  - [ ] 9a. Rerun the GPU handoff tail (about 300 s for 4 handoffs, cause unknown).

## Wave 2: Surfaces
- [x] 10. Kiro CLI, MCP server and hook interceptor (`apps/kiro-trimmer/`). Evidence: `tests/test_chimera_app.py` (2 tests failing, see top).
  - [ ] 10a. Fix the 2 failing tests.
  - [ ] 10b. `github_autopatcher.py` (issue webhook -> Tavily -> patch -> PR). Planned.
  - _Requirements: 4.1, 4.2_
- [ ] 11. Phone modules: `unknown_caller`, `marketplace_bot`, `mobile_hotfix`, `ride_arbitrage`, `supervisor_graph.py`. Planned, not started.
  - _Requirements: 5.1, 5.2, 5.3_

## Wave 3: HUD and CI
- [x] 12. HUD: static HTML plus Python SSE server (`apps/phantom-phone/hud-web/`). Evidence: `tests/test_hud.py`.
  - [ ] 12a. Phone video, voice transcript and trace tabs. Planned.
  - _Requirements: 1.2, 3.2_
- [x] 13. CI: `.github/workflows/ci.yml` runs pytest on Python 3.11 and 3.12. Evidence: file exists; a green run is not yet confirmed.
  - [ ] 13a. Confirm a green run on `dev`.

## Next
- [ ] 14. Measure the ladder, the short brief, and speculative verify; update `bench/` and `.kiro/steering/product.md`.
