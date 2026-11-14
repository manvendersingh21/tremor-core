# Technology Stack & Constraints

Describes what is built and measured. Planned items are marked **(planned)**.

## Inference ladder
Cheapest tier first. Code: `packages/chimera-core/ladder.py`, `router.py`, `config.py`. Settings: `chimera.toml` (copy of `chimera.example.toml`).

| Tier | What | Notes |
|---|---|---|
| 0 | Exact + semantic cache | Persistent SQLite. Semantic threshold **0.97**. 0.94 served wrong answers (`r2`, `p4` in `bench/results_gpu.md`). |
| 1 | Mac draft: `Qwen2.5-3B-Instruct` q4_k_m on `llama.cpp` (`llama-server`) | Prompt cache on. Per-token logprobs. Answers locally when mean token probability >= 0.85. |
| 2 | GPU: Ollama `qwen3:30b-instruct` on a V100 | Reached over an SSH tunnel to your GPU box. Optional (`gpu.enabled`); Crusoe mid model replaces it when off. |
| 3 | Crusoe serverless: `Qwen/Qwen3.8-27B`, `openai/gpt-oss-120b`, the largest model on the key | OpenAI-style API. `CRUSOE_API_KEY` from env or `.env` only. |

- **Thinking stays OFF** on every tier (`think=false`; no reasoning mode on the Qwen models). The top tier uses low reasoning effort only where its template needs it.
- Heavy tasks skip the 3B. A failed check escalates one tier.
- **Heavy-task handoff:** no brief, or a brief of at most 200 tokens (`use_brief=False` to disable). A long brief plus draft raised GPU tokens by 37% (`bench/results_gpu.md`).

## Speculative verification
- Draft and target must be the same model family (Qwen -> Qwen). Same vocabulary indices.
- The verifier must be a `llama.cpp`-based server (`bench/verify_server.py`, `bench/start_verifier.sh`). **Ollama returns no prompt logprobs**, and Crusoe rejects `echo`, so neither can score draft tokens in one pass.
- Send only `[token_id, logprob]` arrays. Never send KV tensors. Each side keeps its own prefix cache.
- Accept rule: `min(1, p_target / p_draft)`; resample from the residual at the first rejection.
- Status: runner is `bench/run_spec.py`. Results file `bench/spec_results.md` does not exist yet, so no speedup is claimed.

## Semantic cache
- Embeddings: `all-MiniLM-L6-v2` (optional `embed` extra). Exact-only mode works without it.
- Store: SQLite file at the path in `chimera.toml`.
- Order: exact hash match, then cosine similarity >= 0.97.

## Surfaces
- **Kiro (built):** `apps/kiro-trimmer/` with `cli.py` (`bin/chimera ask|stats|doctor`), `mcp_server.py` (tools `chimera_generate`, `chimera_stats`, `chimera_risk_score`), `hook_interceptor.py` (reads a diff on STDIN).
- **HUD (built):** static HTML plus a small Python server with Server-Sent Events (`apps/phantom-phone/hud-web/`). Not Next.js, because of limited Mac disk space.
- **Phone agent (planned):** LangGraph supervisor, `PhoneUse` over WebDriverAgent, ElevenLabs + Twilio voice, Tavily lookups, Gemma 3 1B/4B on the phone. None of this is built.

## Coding Standards
- Python 3.11+ (CI runs 3.11 and 3.12). Pydantic v2 for config and router types.
- Tests are offline: `make test` needs no models or keys.
- Secrets live only in `.env` (git-ignored). `.env.example` has the variable names with no values. Never put keys, hostnames or key paths in docs or `.kiro` files.
- Every LLM call MUST pass through `SpeculativeCascadeRouter.generate()` (or `LadderRouter.generate()`) and emit structured telemetry: `tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms`, `dollars_saved`.
