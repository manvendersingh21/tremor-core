# Requirements: cache and verify

Scope: the Supabase answer cache, the false-hit guard, the optional 30B yes/no check on cosine hits, and the confidence check that decides whether a tier's answer is kept. Code: `packages/chimera-core/cache/`, `router.py`, `tiers.py`. Measured: `bench/results_gpu.md`, `bench/results_ladder.md`, `docs/vector-store.md`, `bench/results_research_cache.md`.

## Requirements

### R1 Supabase is the only answer cache
**User story:** As an operator, I want one shared cache, so that a second machine reuses answers and nothing is cached on the Mac.
1. WHEN a prompt arrives and `CHIMERA_DB_URL` is set, THE router SHALL look it up in Supabase before any model call.
2. THE router SHALL NOT write an answer cache file on the local machine.
3. IF `CHIMERA_DB_URL` is unset, THEN THE router SHALL skip the cache and go to the tiers.

### R2 Exact hash first, then cosine 0.97
1. THE cache SHALL try a SHA-256 hash of the normalized prompt first.
2. WHEN no exact hit exists, THE cache SHALL return the best neighbour only if cosine similarity >= 0.97 (`[thresholds] semantic`).
3. THE cache SHALL serve only verified answers.

### R3 Lookup budget
1. WHEN a lookup takes longer than `budget_ms` (300) or the database is down, THE router SHALL continue to the tiers without a cache result.
2. THE router SHALL NOT raise an error to the caller because of a cache failure.

### R4 False-hit guard
1. WHERE `guard = true`, WHEN a cosine hit differs from the prompt in numbers, negation or entities, THE cache SHALL reject the hit.
2. THE step event `cache_shared` SHALL report `guard` as `pass`, `rejected`, `off` or `null`.

### R5 Optional 30B yes/no check (planned)
1. WHERE the check is enabled, WHEN a cosine (not exact) hit passes the guard, THE router SHALL ask the self-hosted 30B whether the cached answer fits the new prompt.
2. IF the 30B answers no or times out, THEN THE router SHALL treat the lookup as a miss.
3. WHEN the hit is exact, THE router SHALL skip the check.

### R6 Confidence gate and escalation
1. WHEN the 30B answers with mean token probability >= 0.95 (Ollama logprobs), THE router SHALL keep the answer.
2. IF logprobs are absent, THEN THE 30B's own self-check SHALL decide.
3. IF a check fails or a GPU call exceeds 90 s, THEN THE router SHALL escalate one tier.
4. Heavy tasks (complexity >= 0.6) SHALL go straight to the top tier.

### R7 Telemetry
1. EVERY call SHALL emit `tier_used`, `tokens_saved`, `acceptance_rate_alpha`, `latency_ms` and `dollars_saved`.

### R8 Speculative verification (experiment)
1. WHERE speculative verify is used, THE draft and target SHALL be the same model family and THE wire SHALL carry only `[token_id, logprob]` arrays.
2. THE verifier SHALL be a llama.cpp server. No speedup over plain Ollama is claimed.

Related: the formal properties for R2, R4, R7 and R8 are in `.kiro/specs/chimera-speculative-os/`.
