---
inclusion: always
---

# Project Structure & Architectural Conventions

Built items are listed as they exist. Items marked **(planned)** are not built.

```text
/
├── .kiro/                          # steering/, specs/, hooks/ (+ scripts/), agents/, settings/mcp.json (docs/handoff/kiro-setup.md)
├── powers/chimera/                 # Kiro Power: plugin.json, mcp.json, skills/
├── .github/workflows/ci.yml        # pytest on Python 3.11 and 3.12, pushes and PRs to dev
├── bin/chimera                     # CLI launcher
├── chimera.example.toml            # Settings template (no secrets). Copy to chimera.toml
├── conftest.py                     # Loads hyphenated packages/chimera-core as `chimera_core`
├── Makefile                        # setup, test, serve-local, bench, demo
├── pyproject.toml
├── README.md, LICENSE
├── docs/research.md                # Papers, feasibility table, measured builds
├── docs/architecture.md            # Tiers, KV cache rule, brief vs verify, telemetry, firewall, pool, Spec+, gateway, shared cache
├── docs/vector-store.md            # Shared Supabase cache: setup and measured results
├── docs/android.md                 # Android phone tier (not tested on a phone)
├── packages/chimera-core/
│   ├── router.py                   # SpeculativeCascadeRouter (cache -> local -> cloud)
│   ├── learned_router.py           # Logistic router (prompt + 3B token stats); off by default, not better than the confidence gate
│   ├── ladder.py                   # LadderRouter: local -> GPU -> Crusoe top, escalate on failed check
│   ├── memory/                     # N+1 memory: memory.py, graph.py, neo4j_store.py (Aura only), extract.py, safety.py
│   ├── tiers.py                    # Tier pool: [[tiers]] from chimera.toml
│   ├── config.py                   # Loads chimera.toml
│   ├── cache/
│   │   ├── exact_cache.py          # SHA-256 normalized prompt cache
│   │   ├── semantic_cache.py       # Cosine cache, threshold 0.97 from config
│   │   ├── pgvector_cache.py       # Shared Supabase cache (Postgres + pgvector); the only answer cache
│   │   └── guard.py                # False-hit guard (numbers, negation, entities); off by default
│   ├── inference/
│   │   ├── local_draft.py          # llama.cpp backend, logprob confidence gate
│   │   ├── cloud_verifier.py       # Crusoe / Ollama backends, verify call
│   │   ├── handoff.py              # Heavy-task handoff: no brief or brief <= 200 tokens
│   │   ├── specplus.py             # Spec+ (adaptive K, tree, pipelining, free drafts, compact wire)
│   │   └── telemetry.py            # tier_used, tokens, latency, dollars (JSONL)
│   └── firewall/risk_scorer.py     # 0-100 action risk score, one-time token at >= 70
├── apps/
│   ├── gateway/                    # OpenAI-compatible gateway, keys per tenant, /metrics
│   ├── terminal/                   # `chimera code` terminal agent: agent.py, edits.py, routing.py, safety.py, cli.py
│   ├── kiro-trimmer/
│   │   ├── cli.py                  # ask, stats, doctor
│   │   ├── mcp_server.py           # Router as an MCP server
│   │   ├── hook_interceptor.py     # Kiro hook: diff on STDIN -> local review
│   │   ├── common.py
│   │   └── github_autopatcher.py   # (planned) issue webhook -> patch -> PR
│   └── phantom-phone/
│       ├── hud-web/                # server.py (the one server: site/, SSE, /api/*), demo.py; index.html redirects
│       ├── supervisor_graph.py     # (planned)
│       └── modules/                # (planned) unknown_caller, marketplace_bot, mobile_hotfix, ride_arbitrage
├── deploy/                         # Gateway Docker files, sql/ (shared cache), modal/ (H200 app)
├── site/                           # The web page: world/ (walkable castle, bat chat), castle/ + vendor/ (3D castle in progress), dashboard.js, rooms.js posters, build.py (no-JS page)
├── scripts/                        # android_setup.sh, phone_check.sh
├── bench/                          # Prompts, runners, results
│   ├── prompts.jsonl               # 30 prompts
│   ├── run_bench.py, results.md    # Mac cascade vs Crusoe only
│   ├── run_bench_gpu.py, results_gpu.md   # Mac cascade vs GPU only
│   ├── run_ladder.py, results_ladder.md   # Ladder run
│   ├── run_specplus.py, results_specplus.md   # Spec+ vs plain spec (stand-in target)
│   ├── results_modal.md            # Modal H200: gpt-oss-120b pair run (lost on cost and speed); Qwen3.5-122B never served
│   ├── run_research_collect.py, train_router.py, run_research_cache.py   # research measurements (docs/research.md)
│   ├── run_spec.py, verify_server.py, start_verifier.sh, spec_results.md   # Plain speculative verify (4.5x to 7x slower)
│   └── serve_local.sh              # Start the Mac llama-server
└── tests/                          # Offline pytest: router, backends, ladder, memory, terminal, world, app, HUD; Hypothesis helpers in _props.py
```

## Conventions
- The package directory is hyphenated. Import it as `chimera_core` (set up by `conftest.py`).
- Config goes in `chimera.toml`. Keys go in `.env`. Neither holds hostnames of private boxes in committed docs.
- Benchmarks write `bench/*.md` with the setup, the numbers and a verdict that names failures.
