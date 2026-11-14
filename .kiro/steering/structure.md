# Project Structure & Architectural Conventions

## Repository Layout
```text
/
├── .kiro/                          # Steering, EARS Specs, and Event Hooks
├── packages/
│   └── chimera-core/               # THE SKELETON: Shared Speculative & Cache Engine
│       ├── cache/
│       │   ├── exact_cache.py      # SHA-256 prompt + normalized AST cache
│       │   └── semantic_cache.py   # sqlite-vec / Qdrant cosine similarity cache
│       ├── inference/
│       │   ├── local_draft.py      # Gemma 1B/4B & Qwen 3B local KV + entropy gate
│       │   ├── cloud_verifier.py   # 27B/30B parallel rejection sampling verifier
│       │   └── telemetry.py        # Token, latency, and data-center cost tracker
│       └── firewall/
│           └── risk_scorer.py      # 0-100 blast-radius interceptor for GUI/CLI actions
├── apps/
│   ├── kiro-trimmer/               # SHOWCASE APP 1 (Computer / Kiro IDE & GitHub)
│   │   ├── mcp_server.py           # Exposes Chimera Router as a Kiro MCP tool
│   │   ├── hook_interceptor.py     # Handles .kiro/hooks STDIN diffs locally on 3B/4B
│   │   └── github_autopatcher.py   # Webhook -> Tavily + Local Draft + Auto-PR
│   └── phantom-phone/              # SHOWCASE APP 2 (Phone / DND Multi-Agent OS)
│       ├── supervisor_graph.py     # LangGraph master router for DND tasks
│       ├── modules/
│       │   ├── unknown_caller.py   # Twilio + ElevenLabs + Tavily + PhoneUse 2FA/Lock
│       │   ├── marketplace_bot.py  # FB Marketplace OCR scraper + haggler + Venmo stager
│       │   ├── mobile_hotfix.py    # Drives GitHub & ChatGPT iOS apps via PhoneUse
│       │   └── ride_arbitrage.py   # Uber vs. Lyft vs. Waymo live screen price sniper
│       └── hud-web/                # Mobile-first Replit dashboard & live telemetry UI
└── tests/                          # Pytest suites for cache, speculative math, and firewall