# Technology Stack & Constraints

Describes what is built and measured. Planned items are marked **(planned)**.

## Inference ladder
Cheapest tier first. Code: `packages/chimera-core/ladder.py`, `router.py`, `config.py`. Settings: `chimera.toml` (copy of `chimera.example.toml`).

| Tier | What | Notes |
|---|---|---|
| 0 | Exact + semantic cache | SQLite by default, or the shared Supabase cache (below). Semantic threshold **0.97**. 0.94 served wrong answers (`r2`, `p4` in `bench/results_gpu.md`); at 0.97 the ladder run served none (`bench/results_ladder.md`). |
| 1 | Mac draft: `Qwen2.5-3B-Instruct` q4_k_m on `llama.cpp` (`llama-server`) | Prompt cache on. Per-token logprobs. Answers locally when mean token probability >= 0.85. |
| 2 | GPU: Ollama `qwen3:30b-instruct` on a V100 | Reached over an SSH tunnel to your GPU box. Optional (`gpu.enabled`); Crusoe mid model replaces it when off. |
| 3 | Crusoe serverless: `openai/gpt-oss-120b`, and `deepseek-ai/DeepSeek-V4.1-Flash` (763B, the largest on the key) as the top. `Qwen/Qwen3.8-27B` was the first benchmark's cloud model and the grader | OpenAI-style API. `CRUSOE_API_KEY` from env or `.env` only. Ladder vs top only: gpt-oss-120b tokens -45.1%, 763B tokens -65.6%, median latency higher (`bench/results_ladder.md`). |
| Modal | `gpu-large`: vLLM on an H200 (`deploy/modal/vllm_server.py`), scales to zero | Never served a request in two cold starts. Retry pending (`bench/results_modal.md`). No numbers. |

- **Thinking stays OFF** on every tier (`think=false`; no reasoning mode on the Qwen models). The top tier uses low reasoning effort only where its template needs it.
- Heavy tasks skip the 3B. A failed check escalates one tier.
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
- Store: SQLite file at the path in `chimera.toml`, or Postgres + pgvector on Supabase (`cache/pgvector_cache.py`, `docs/vector-store.md`). Shared cache: 0.80 hit rate and 48 of 60 GPU calls avoided on a second machine, 0 false hits. Lookup median 121 ms vs 8.9 ms local; budget 300 ms, then SQLite.
- Order: exact hash match, then cosine similarity >= 0.97.
- Guard (`cache/guard.py`, off): wrong hits 4 -> 2 at 0.97 on 800 QQP pairs, recall 10.1% -> 9.1% (`bench/results_research_cache.md`).
- Learned router (off): 70.0% on 180 graded prompts, the same as the confidence gate (`bench/results_research_router.md`).

## Surfaces
- **Kiro (built):** `apps/kiro-trimmer/` with `cli.py` (`bin/chimera ask|stats|doctor`), `mcp_server.py` (tools `chimera_generate`, `chimera_stats`, `chimera_risk_score`), `hook_interceptor.py` (reads a diff on STDIN).
- **HUD (built):** static HTML plus a small Python server with Server-Sent Events (`apps/phantom-phone/hud-web/`). Not Next.js, because of limited Mac disk space.
- **Gateway (built):** `apps/gateway/`, OpenAI-compatible, keys per tenant, `/metrics` (`deploy/README.md`).
- **Android tier (written, not tested on a phone):** Qwen2.5 3B or 1.5B through Termux over USB (`docs/android.md`).
- **Phone agent (planned):** LangGraph supervisor, `PhoneUse` over WebDriverAgent, ElevenLabs + Twilio voice, Tavily lookups, Gemma 3 1B/4B on the phone. None of this is built.

## Coding Standards
- Python 3.11+ (CI runs 3.11 and 3.12). Pydantic v2 for config and router types.
- Tests are offline: `make test` needs no models or keys.
- Secrets live only in `.env` (git-ignored). `.env.example` has the variable names with no values. Never put keys, hostnames or key paths in docs or `.kiro` files.
- Every LLM call MUST pass through `SpeculativeCascadeRouter.generate()` (or `LadderRouter.generate()`) and emit structured telemetry: `tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms`, `dollars_saved`.
