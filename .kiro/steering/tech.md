---
inclusion: always
---

# Technology Stack & Constraints

Describes what is built and measured. Planned items are marked **(planned)**.

## Inference ladder
Cheapest tier first. Product path: the tier pool (`use_pool = true`). Order: Supabase cache (exact, then cosine 0.97) -> optional 30B yes/no check on a cosine hit -> self-hosted 30B -> optional Modal 120B -> Crusoe 763B. Code: `packages/chimera-core/tiers.py`, `router.py`, `config.py`, `memory/`. Settings: `chimera.toml` (copy of `chimera.example.toml`).

| Tier | What | Notes |
|---|---|---|
| 0 | Shared Supabase cache (Postgres + pgvector, `cache/pgvector_cache.py`) | Exact hash, then cosine **0.97**. 0.94 served wrong answers (`r2`, `p4` in `bench/results_gpu.md`); at 0.97 the ladder run served none (`bench/results_ladder.md`). Only verified answers are served. This is the only answer cache: nothing is cached on the Mac. |
| 0b | Optional 30B yes/no check on a cosine hit **(planned: not in the code tree yet)** | The self-hosted 30B is asked whether the cached answer fits the new prompt. Exact-hash hits skip it. Not measured. |
| 1 | GPU 30B, self-hosted: Ollama `qwen3:30b-instruct` on a V100 | The smallest product tier. Reached over an SSH tunnel to your GPU box. Answers when mean token probability >= 0.95 (Ollama logprobs), else its own self-check decides. |
| 2 | Modal `gpu-large`: vLLM `gpt-oss-120b` on an H200 (`deploy/modal/vllm_server.py`), optional, off | One pair of runs: took all calls off the 763B, same 24/24 asserts, but about $0.11 of H200 time vs $0.0058 of 763B tokens, median 1,352 ms vs 728 ms (`bench/results_modal.md`). |
| 3 | Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (763B, the largest on the key) | OpenAI-style API. `CRUSOE_API_KEY` from env or `.env` only. Ladder vs top only: 763B tokens -65.6% (`bench/results_ladder.md`). |
| N+1 memory | `memory/` | Before the 30B call: retrieve solved examples as few-shot context. After a checked answer from the 763B or 120B: store prompt, answer, tests passed, tier and model as teacher data in Supabase `teacher_pairs`. The concept graph lives only in hosted Neo4j Aura (`memory/neo4j_store.py`); there is no Postgres graph fallback and no Neo4j on the GPU box. If Aura is down, retrieve returns nothing and store skips the graph, never raising (`docs/memory.md`). Not measured end to end yet (`bench/memory/run_memory.py` is the harness). |
| Solved-problem bank | **(planned: not in the code tree yet)** | Verified problem/solution pairs kept for lookup before any model call. Fed by the same checked answers as N+1 memory. |
| Experiment, off | Mac `Qwen2.5-3B-Instruct` q4_k_m on `llama.cpp` | The Mac 3B llama-server is off. Used only by the first benchmarks (gate 0.85), the speculative benches (draft model) and the Android tier. Not in the product ladder. Restart for a one-off test with `bench/serve_local.sh`. |

`LadderRouter` (`ladder.py`: cache, Mac 3B, GPU 30B, Crusoe top) is the path the ladder benchmark measured, so its 3B step belongs to that old run, not to the product path. `bench/run_suite.py` POOL runs cache, 30B, 763B (commit c90c1f0). `Qwen/Qwen3.8-27B` was the first benchmark's cloud model and the grader.

- **Thinking stays OFF** on every tier (`think=false`; no reasoning mode on the Qwen models). The top tier uses low reasoning effort only where its template needs it.
- Heavy tasks go straight to the top. A failed check escalates one tier.
- **Heavy-task handoff:** no brief by default (`use_brief=False`); a brief is at most 200 tokens. A long brief plus draft raised GPU tokens by 37% (`bench/results_gpu.md`). A 30B brief cost the same dollars and was 4.4x slower (`bench/results_ladder.md`). Every GPU call has a 90 s timeout, then the prompt climbs.
- **Tier pool:** hardware is listed as `[[tiers]]` in `chimera.toml` (`packages/chimera-core/tiers.py`, `use_pool`). Picks the cheapest healthy tier that covers the task.

## Speculative verification
- Draft and target must be the same model family (Qwen -> Qwen). Same vocabulary indices.
- The verifier must be a `llama.cpp`-based server (`bench/verify_server.py`, `bench/start_verifier.sh`). **Ollama returns no prompt logprobs**, and Crusoe rejects `echo`, so neither can score draft tokens in one pass.
- Send only `[token_id, logprob]` arrays. Never send KV tensors. Each side keeps its own prefix cache.
- Accept rule: `min(1, p_target / p_draft)`; resample from the residual at the first rejection.
- Measured (`bench/spec_results.md`): over the internet, plain spec was 4.5x to 7x slower than plain Ollama. Round trip about 0.6 s, alpha 0.68 at K=4, 0.52 at K=8. Works only with a short round trip and a verifier fully on GPU.
- **Spec+** (`inference/specplus.py`): adaptive K, token tree, pipelining, free drafts, compact wire. 1.14x to 1.22x over the best plain spec, measured against a stand-in target (the 3B, sharpened), not a real big model, with modelled network and server time. Below the big model alone (`bench/results_specplus.md`). No speedup over plain Ollama is claimed.

## Semantic cache
- Embeddings: `all-MiniLM-L6-v2` (optional `embed` extra). Exact-only mode works without it.
- Store: Postgres + pgvector on Supabase (`cache/pgvector_cache.py`, `docs/vector-store.md`). `[cache] backend = "supabase"` is the only answer cache. `sqlite` exists for offline tests only; no cache file is kept on the Mac. Shared cache: 0.80 hit rate and 48 of 60 GPU calls avoided on a second machine, 0 false hits. Lookup median 121 ms vs 8.9 ms for the old local cache, since removed; budget 300 ms, then the call goes straight to the tiers.
- Order: exact hash match, then cosine similarity >= 0.97.
- Guard (`cache/guard.py`, off): wrong hits 4 -> 2 at 0.97 on 800 QQP pairs, recall 10.1% -> 9.1% (`bench/results_research_cache.md`).
- Learned router (off): 70.0% on 180 graded prompts, the same as the confidence gate (`bench/results_research_router.md`).

## Surfaces
- **Kiro (built):** `apps/kiro-trimmer/` with `cli.py` (`bin/chimera ask|stats|doctor`), `mcp_server.py` (tools `chimera_generate`, `chimera_stats`, `chimera_risk_score`; registered in `.kiro/settings/mcp.json`), `hook_interceptor.py` (reads a diff on STDIN). Kiro setup (steering, specs, hooks, agents, MCP, Power): `docs/handoff/kiro-setup.md`.
- **Terminal agent (`chimera code`, written, in review):** `apps/terminal/`, an Aider-style coding agent. Every model call goes through `SpeculativeCascadeRouter.generate()`; a failed test run climbs a tier (`apps/terminal/README.md`, `bench/run_terminal_agent.py`). No results file yet.
- **Web page (built):** one page on one port (`make web`, 127.0.0.1:8765): a 3D castle (`site/castle/`, three.js vendored in `site/vendor/`, shapes built from primitives, no downloaded assets). Gate, Great Hall with the guide desk (chat over `/api/chat`) and savings board, stairs, three doors (Dashboard, Chat, Evals). 58 to 60 fps measured headless on this Mac. Plain HTML when WebGL is missing.
- **Gateway (built):** `apps/gateway/`, OpenAI-compatible, keys per tenant, `/metrics` (`deploy/README.md`).
- **Android tier (written, not tested on a phone):** Qwen2.5 3B or 1.5B through Termux over USB (`docs/android.md`).
- **Phone agent (planned):** LangGraph supervisor, `PhoneUse` over WebDriverAgent, ElevenLabs + Twilio voice, Tavily lookups, Gemma 3 1B/4B on the phone. None of this is built.

## Coding Standards
- Python 3.11+ (CI runs 3.11 and 3.12). Pydantic v2 for config and router types.
- Tests are offline: `make test` needs no models or keys (see `testing.md`). Property tests use Hypothesis (`tests/_props.py`).
- Secrets live only in `.env` (git-ignored). `.env.example` has the variable names with no values. Never put keys, hostnames or key paths in docs or `.kiro` files (see `security.md`).
- Every LLM call MUST pass through `SpeculativeCascadeRouter.generate()` (or `LadderRouter.generate()`) and emit structured telemetry: `tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms`, `dollars_saved`.
