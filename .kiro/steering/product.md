# Product Overview: CHIMERA-OS (Speculative Edge-to-Cloud Router & DND Phone Agent)

## Vision & Purpose
CHIMERA-OS is a dual-surface AI inference and autonomous execution platform that eliminates 60–80% of data-center LLM token costs and latency. It stitches together a 3-Tier Edge-to-Cloud Cascade—combining a sub-5ms Semantic Answer Cache, an on-device small language model (Gemma 3 1B/4B on mobile or Qwen 3B on laptop) with persistent Prefix KV Caching, and Confidence-Gated Speculative Decoding that escalates only high-entropy tokens or complex reasoning to a remote 27B/30B verifier model (Gemma 3 27B / Qwen 30B).

## Target Tracks & Dual-Surface Architecture
Built as a universal foundational skeleton with two distinct production applications:
1. **Surface A — Desktop / Kiro Coding Engine (`apps/kiro-trimmer`):** Intercepts IDE file-save hooks, spec compliance checks, and GitHub Issue auto-patching locally. Deterministic queries (e.g., "What is the capital of France?" or standard syntax checks) resolve in <5ms from the Semantic Cache or locally via the 3B/4B model with zero cloud spend.
2. **Surface B — Mobile / Autonomous DND Phone Agent (`apps/phantom-phone`):** Runs while the user's phone is on Do Not Disturb. Uses on-device Gemma + PhoneUse MCP + ElevenLabs + Tavily to answer unknown callers, execute 2FA/intercom unlocks, haggle on Facebook Marketplace, compare Uber/Lyft prices, and trigger ChatGPT/GitHub mobile hotfixes—protected by a real-time Quarantine Risk Firewall.

## Core Product Pillars
- **Zero-Waste Token Economics:** Never send deterministic or repeated queries to data-center GPUs.
- **Lossless Speculative Verification:** Stream draft token IDs and log-probabilities from the local 1B–4B model to the 27B/30B verifier for single-pass parallel rejection sampling.
- **Cross-Device Autonomous Execution:** Everything is controllable and verifiable from a mobile phone HUD or Kiro CLI/IDE.
- **Deterministic Safety Gate:** Intercept high-risk GUI taps (`Pay`, `Delete`, `Merge PR`, `Send Wire`) with a 0–100 blast-radius score requiring voice/SMS confirmation.