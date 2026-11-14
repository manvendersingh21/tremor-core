# Implementation Plan: CHIMERA-OS

## Wave 1: Core Skeleton (`packages/chimera-core`) — Parallel Foundation
- [ ] 1. Implement Tier 1 Exact & Semantic Answer Cache (`packages/chimera-core/cache/`)
  - Build `exact_cache.py` (SHA-256 prompt normalization) and `semantic_cache.py` using `sqlite-vec` / `Qdrant` with `all-MiniLM-L6-v2` embeddings and a configurable `0.94` cosine similarity threshold.
  - Validate with deterministic test cases ("What is the capital of France?" -> "Paris" in <5ms across paraphrased prompts).
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 2. Implement Tier 2 Local Gemma/Qwen Draft Engine & KV Prefix Manager (`packages/chimera-core/inference/local_draft.py`)
  - Connect to local `llama.cpp` / Ollama / MediaPipe server running `gemma-3-1b-it` / `gemma-3-4b-it` (mobile) or `qwen2.5-3b-instruct` (desktop) with `cache_prompt=True` and `logprobs=True`.
  - Compute per-token Shannon entropy and confidence margin; return immediately on high confidence (`>= 0.85`).
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 3. Implement Tier 3 Speculative Verifier & Rejection Sampler (`packages/chimera-core/inference/cloud_verifier.py`)
  - Implement batched verification against the remote 27B/30B endpoint (`gemma-3-27b-it` or `Qwen3-30B-A3B`) using token-ID arrays and lossless rejection sampling `min(1, p_t / p_d)`.
  - Record live telemetry (`acceptance_rate_alpha`, `cloud_tokens_saved`, `latency_ms`) in `telemetry.py`.
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] 4. Build Quarantine Risk Firewall (`packages/chimera-core/firewall/risk_scorer.py`)
  - Score every proposed `PhoneUse` screen tap and CLI command from 0–100; block destructive/financial actions (`Pay`, `Send Money`, `Merge PR`, `Delete`) behind a voice/SMS verification token.
  - _Requirements: 5.3_

## Wave 2: Dual-Surface Applications (`apps/kiro-trimmer` & `apps/phantom-phone`)
- [ ] 5. Build Surface A: Kiro IDE Hook Interceptor & GitHub Auto-Patcher (`apps/kiro-trimmer/`)
  - Expose `chimera-core` as an MCP Server (`mcp_server.py`) and CLI STDIN handler (`hook_interceptor.py`) for `.kiro/hooks/`.
  - Build `github_autopatcher.py` to receive GitHub Issue webhooks, query Tavily for docs, synthesize fixes via the speculative router, and open a PR.
  - _Requirements: 4.1, 4.2_

- [ ] 6. Build Surface B Module 1: Unknown Caller DND Interceptor & 2FA/Intercom Executor (`apps/phantom-phone/modules/unknown_caller.py`)
  - Wire Twilio + ElevenLabs inbound voice webhook -> Tavily caller OSINT check -> local Gemma intent routing -> `PhoneUse` MCP execution (Google Authenticator readback, Calendar check, Intercom unlock).
  - _Requirements: 5.1_

- [ ] 7. Build Surface B Module 2: Facebook Marketplace Haggler & Ride Arbitrage Sniper (`apps/phantom-phone/modules/marketplace_bot.py`)
  - Drive Facebook Marketplace and Uber/Lyft iOS apps via `PhoneUse` OCR/screenshots, fetch eBay sold comps via Tavily, negotiate via Messenger/ElevenLabs outbound calls, and stage Venmo/Uber checkout up to the Quarantine Firewall gate.
  - _Requirements: 5.2, 5.3_

- [ ] 8. Build Surface B Module 3: Mobile ChatGPT + GitHub Bug Hotfixer (`apps/phantom-phone/modules/mobile_hotfix.py`)
  - Use `PhoneUse` MCP to visibly open the iOS GitHub and ChatGPT mobile apps on screen when a high-priority issue arrives during DND, stage the PR fix, and trigger an ElevenLabs voice approval call.
  - _Requirements: 4.2, 5.1, 5.3_

## Wave 3: Unified Replit Mobile & Desktop Command HUD (`apps/phantom-phone/hud-web`)
- [ ] 9. Build Real-Time God-View & Speculative Savings Dashboard
  - Create a 4-tab mobile/desktop web HUD showing: (1) Live PhoneUse iPhone video stream + Quarantine Firewall alerts, (2) Real-time Tier 1/2/3 Cache & Speculative Acceptance ($\alpha$) token-savings meter, (3) DND Voice Bouncer transcript, and (4) LangSmith trace feed.
  - _Requirements: 1.2, 3.2, 5.1, 5.3_