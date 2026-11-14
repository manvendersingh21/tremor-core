# Technology Stack & Constraints

## Inference & Speculative Decoding Stack
- **Edge Draft Models (Tier 2):**
  - **Mobile (iOS / Android):** `google/gemma-3-1b-it` or `google/gemma-3-4b-it` (4-bit GGUF/LiteRT via MediaPipe LLM Inference API or local `llama.cpp` HTTP server) with pinned local Prefix KV Cache.
  - **Desktop / Kiro Local Daemon:** `Qwen2.5-3B-Instruct` or `google/gemma-3-4b-it` running via `llama.cpp` / Ollama / vLLM with `logprobs=True` and persistent prompt prefix caching.
- **Cloud Target / Verifier Models (Tier 3):**
  - `google/gemma-3-27b-it` (paired with Gemma 3 1B/4B draft) or `Qwen3-30B-A3B` / `Qwen2.5-32B-Instruct` (paired with Qwen 3B draft) served via vLLM or SGLang with Automatic Prefix Caching (APC) enabled.
- **Tokenizer Alignment Constraint:** Draft and target models MUST belong to the exact same model family (Gemma-3 -> Gemma-3, or Qwen -> Qwen) to guarantee identical vocabulary indices during speculative token verification. Do NOT transmit raw KV tensors across the network; transmit compact `[token_id, logprob]` draft arrays and maintain warm prefix KV caches independently on both nodes.

## Semantic Answer & Prompt Cache (Tier 1)
- **Embedding Model:** Local `all-MiniLM-L6-v2` or `nomic-embed-text` (ONNX/quantized).
- **Vector Store:** Embedded `sqlite-vec` or `Qdrant` in-memory/local disk store.
- **Thresholds:** Exact hash match (`0.0ms`) -> Cosine similarity `>= 0.94` returns cached response immediately without invoking Tier 2 or Tier 3.

## Autonomous Phone & Multi-Agent Stack
- **Orchestration:** Python 3.11+, `LangGraph` state machines, traced end-to-end with `LangSmith`.
- **Mobile GUI Automation:** `PhoneUse` (`phoneuse-official/phoneuse`) over WebDriverAgent (WDA) + MCP Server (`tap`, `type`, `screenshots`, `on-screen elements`, `apps`).
- **Voice & Telephony:** `ElevenLabs` Conversational AI + Twilio Programmable Voice (Conditional Call Forwarding on DND/Unknown Caller + `transfer_to_number` warm handoff).
- **Live Web Grounding:** `Tavily` Search API for caller OSINT, eBay sold-price comps, and library documentation lookups.
- **Frontend Command HUD:** Next.js 14 / React Tailwind CSS dark-mode mobile dashboard (deployable on Replit) with WebSocket live telemetry.

## Coding Standards
- Strict TypeScript for UI and Node bridges; Python with Pydantic v2 type validation for router and LangGraph nodes.
- Every LLM call MUST pass through `SpeculativeCascadeRouter.generate()` and emit structured telemetry (`tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms`, `dollars_saved`).