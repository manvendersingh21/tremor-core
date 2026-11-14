# Requirements Specification: CHIMERA-OS

## Requirement 1: Tier 1 Semantic & Exact Answer Caching
**User Story:** As a developer or mobile user, I want repeated or semantically equivalent questions (such as "What is the capital of France?" or repeated UI tap lookups) answered instantaneously from a local cache so that zero local GPU compute or data-center tokens are wasted.

### Acceptance Criteria
1. WHEN a prompt or UI state query arrives at the router THE SYSTEM SHALL compute an exact normalized hash and a local vector embedding within 10 milliseconds.
2. IF the cosine similarity against an existing cached entry is greater than or equal to 0.97 (0.94 returned wrong answers in `bench/results_gpu.md`) THEN THE SYSTEM SHALL return the cached response immediately with `tier_used="SEMANTIC_CACHE"` and `cloud_tokens=0`.
3. WHEN a new deterministic factual query or code check is verified by Tier 2 or Tier 3 THE SYSTEM SHALL persist the prompt embedding, response, and TTL metadata into the local vector store.
4. WHERE a shared cache is configured THE SYSTEM SHALL serve only verified rows and fall back to the local store when a lookup exceeds 300 ms. Measured once: 48 of 60 GPU calls avoided on a second machine, 0 false hits (`docs/vector-store.md`).

5. WHEN two tenants or namespaces use the same prompt THE SYSTEM SHALL never serve one tenant's cached answer to the other.
6. WHERE the false-hit guard is on THE SYSTEM SHALL turn a cosine hit into a miss when the two prompts differ in a number, a negation or a named entity.

## Requirement 2: Tier 2 On-Device Gemma/Qwen KV Cache & Confidence Gate
**User Story:** As an operator running Gemma locally on a phone or Qwen 3B on a laptop, I want the local model to maintain a warm prefix KV cache and answer routine requests locally, escalating to the GPU 30B tier, then the Crusoe tier, only when token uncertainty spikes.

### Acceptance Criteria
1. WHILE a coding session or DND phone session is active THE SYSTEM SHALL pin system instructions, `.kiro/steering/` context, and recent UI accessibility trees inside the local draft model's Prefix KV Cache.
2. WHEN a Tier 1 cache miss occurs THE SYSTEM SHALL generate candidate tokens using the local 1B–4B draft model and compute per-token log-probability margin and Shannon entropy.
3. IF the mean token confidence across the generated sequence remains above 0.85 THEN THE SYSTEM SHALL return the local model's response directly without contacting the remote 27B/30B server.

## Requirement 3: Tier 3 Edge-to-Cloud Speculative Decoding
**User Story:** As an engineer handling complex code architecture or multi-turn negotiations, I want low-confidence local draft tokens verified in parallel by a 27B/30B model so I get frontier-grade accuracy at a fraction of standard autoregressive latency and cost.

### Acceptance Criteria
1. IF local draft token confidence drops below 0.85 during generation THEN THE SYSTEM SHALL stream the block of K=5 to 8 draft token IDs and their draft probabilities `p_d(x)` to the remote verifier endpoint. The verifier must be a llama.cpp server of the same model family; Ollama and Crusoe cannot score draft tokens.
2. WHEN the remote 27B/30B verifier receives K draft tokens THE SYSTEM SHALL evaluate all K tokens in a single parallel forward pass against its own warm prefix KV cache and apply lossless rejection sampling `min(1, p_t(x) / p_d(x))`.
3. IF any draft token is rejected at index `j` THEN THE SYSTEM SHALL resample token `j` from the adjusted residual distribution `norm(max(0, p_t(x) - p_d(x)))` and return the corrected token plus updated prefix offset to the edge node.
4. Status: built, not a speedup over the internet. Plain spec was 4.5x to 7x slower than plain Ollama with a round trip of about 0.6 s (`bench/spec_results.md`). Spec+ was 1.14x to 1.22x over plain spec against a stand-in target only (`bench/results_specplus.md`). The requirement text above is the design goal, not a measured result.

## Requirement 4: Kiro IDE Hook Shield & GitHub Issue Auto-Patcher (Desktop App)
**User Story:** As a developer coding in Kiro, I want file saves and incoming GitHub issues triaged locally first and patched automatically so that minor edits do not burn cloud credits and production bugs are fixed while I am away.

### Acceptance Criteria
1. WHEN Kiro triggers a `PostFileSave` or `PreToolUse` event hook THE SYSTEM SHALL pipe the file diff to the local draft model to verify spec compliance against `.kiro/specs/` before allowing any cloud LLM escalation.
2. WHEN a GitHub Issue webhook is received THE SYSTEM SHALL retrieve library documentation via Tavily, generate a candidate patch using the Speculative Cascade Router, open a Pull Request, and notify the user on mobile.

## Requirement 5: Autonomous DND Phone Agent & Quarantine Firewall (Mobile App)
**User Story:** As a user whose phone is on Do Not Disturb, I want my agent to intercept unknown callers, haggle on Facebook Marketplace, and operate mobile-only apps via PhoneUse while blocking unauthorized financial or destructive taps.

### Acceptance Criteria
1. WHILE the phone is in Do Not Disturb mode WHEN an unknown caller is forwarded to the agent THE SYSTEM SHALL answer via ElevenLabs voice, run a live Tavily OSINT lookup on the caller, and execute authorized mobile app actions (Calendar check, 2FA readback, or intercom unlock) via PhoneUse MCP.
2. WHEN a user dispatches a Facebook Marketplace or Ride Arbitrage task THE SYSTEM SHALL use PhoneUse OCR/screenshots and local Gemma to navigate listings, verify fair market comps via Tavily, negotiate via in-app chat or outbound ElevenLabs voice call, and stage checkout in Venmo/Uber.
3. IF any PhoneUse MCP action targets a screen coordinate associated with high-risk labels (`Pay`, `Confirm Purchase`, `Delete`, `Merge PR`) THEN THE SYSTEM SHALL freeze execution and require explicit voice passphrase or SMS confirmation before tapping.

## Requirement 6: Routing, Telemetry and Check Gating
**User Story:** As an operator, I want every call measured and every unchecked answer kept out of the caches and memory, so the savings numbers are honest and wrong answers are not replayed.

### Acceptance Criteria
1. WHEN any call finishes THE SYSTEM SHALL emit exactly one telemetry event carrying `tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms` and `dollars_saved`.
2. THE SYSTEM SHALL report `tokens_saved`, `dollars_saved`, `dollars_spent` and `latency_ms` as values of 0 or more, and `acceptance_rate_alpha` as null or within 0 to 1.
3. WHEN a tier fails or is not confident THE SYSTEM SHALL climb to a more expensive tier only, call each tier at most once, and stop at the top tier.
4. IF a check on an answer fails THEN THE SYSTEM SHALL NOT write that answer to any cache or to memory.

## Requirement 7: Secret Scrubbing and Action Firewall
**User Story:** As a security owner, I want secrets removed before anything is stored and risky actions held, so a cache or memory dump leaks nothing and nothing destructive runs unapproved.

### Acceptance Criteria
1. WHEN text is stored in the cache or memory THE SYSTEM SHALL first remove emails, API keys, JWTs, database URLs and Luhn-valid card numbers, and scrubbing a second time SHALL change nothing.
2. THE SYSTEM SHALL score every action from 0 to 100, and for a score of 70 or more SHALL issue a one-time approval token and hold the action.
3. WHEN a risky verb is added to an action text THE SYSTEM SHALL NOT lower its score.

## Requirement 8: N+1 Memory
**User Story:** As a developer, I want only verified solved problems kept as teacher data, and one tenant's data removable without touching another's.

### Acceptance Criteria
1. THE SYSTEM SHALL store a teacher pair only when its tests passed, or a blind grader gave 4 of 5 or more, and the prompt and answer are not blank.
2. WHEN a tenant is purged THE SYSTEM SHALL remove all of that tenant's rows and none of any other tenant's.
3. THE SYSTEM SHALL store only scrubbed prompts and answers.

## Requirement 9: Web API Contract
**User Story:** As the UI owner, I want the documented event and stats shapes to hold for any input (`docs/api.md`).

### Acceptance Criteria
1. WHEN `/api/stats` summarizes telemetry rows THE SYSTEM SHALL return every documented key with non-negative values.
2. IF a chat `action` scores 70 or more THEN THE SYSTEM SHALL refuse with `403 approval_required` before any model is called.
3. WHEN `/api/chat` streams THE SYSTEM SHALL emit only documented steps, each with its documented fields, in the documented order, ending with `answer` then `done`.
