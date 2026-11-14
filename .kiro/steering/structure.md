# Project Structure & Architectural Conventions

Built items are listed as they exist. Items marked **(planned)** are not built.

```text
/
├── .kiro/                          # Steering, specs, hooks
├── .github/workflows/ci.yml        # pytest on Python 3.11 and 3.12, pushes and PRs to dev
├── bin/chimera                     # CLI launcher
├── chimera.example.toml            # Settings template (no secrets). Copy to chimera.toml
├── conftest.py                     # Loads hyphenated packages/chimera-core as `chimera_core`
├── Makefile                        # setup, test, serve-local, bench, demo
├── pyproject.toml
├── README.md, LICENSE
├── docs/architecture.md            # Tiers, KV cache rule, brief vs verify, telemetry, firewall
├── packages/chimera-core/
│   ├── router.py                   # SpeculativeCascadeRouter (cache -> local -> cloud)
│   ├── ladder.py                   # LadderRouter: local -> GPU -> Crusoe top, escalate on failed check
│   ├── config.py                   # Loads chimera.toml
│   ├── cache/
│   │   ├── exact_cache.py          # SHA-256 normalized prompt cache
│   │   └── semantic_cache.py       # Cosine cache, threshold 0.97 from config
│   ├── inference/
│   │   ├── local_draft.py          # llama.cpp backend, logprob confidence gate
│   │   ├── cloud_verifier.py       # Crusoe / Ollama backends, verify call
│   │   ├── handoff.py              # Heavy-task handoff: no brief or brief <= 200 tokens
│   │   └── telemetry.py            # tier_used, tokens, latency, dollars (JSONL)
│   └── firewall/risk_scorer.py     # 0-100 action risk score, one-time token at >= 70
├── apps/
│   ├── kiro-trimmer/
│   │   ├── cli.py                  # ask, stats, doctor
│   │   ├── mcp_server.py           # Router as an MCP server
│   │   ├── hook_interceptor.py     # Kiro hook: diff on STDIN -> local review
│   │   ├── common.py
│   │   └── github_autopatcher.py   # (planned) issue webhook -> patch -> PR
│   └── phantom-phone/
│       ├── hud-web/                # index.html, server.py (SSE), demo.py
│       ├── supervisor_graph.py     # (planned)
│       └── modules/                # (planned) unknown_caller, marketplace_bot, mobile_hotfix, ride_arbitrage
├── bench/                          # Prompts, runners, results
│   ├── prompts.jsonl               # 30 prompts
│   ├── run_bench.py, results.md    # Mac cascade vs Crusoe only
│   ├── run_bench_gpu.py, results_gpu.md   # Mac cascade vs GPU only
│   ├── run_ladder.py               # Ladder run
│   ├── run_spec.py, verify_server.py, start_verifier.sh   # Speculative verify (results pending)
│   └── serve_local.sh              # Start the Mac llama-server
└── tests/                          # Offline pytest: router, backends, ladder, app, HUD
```

## Conventions
- The package directory is hyphenated. Import it as `chimera_core` (set up by `conftest.py`).
- Config goes in `chimera.toml`. Keys go in `.env`. Neither holds hostnames of private boxes in committed docs.
- Benchmarks write `bench/*.md` with the setup, the numbers and a verdict that names failures.
