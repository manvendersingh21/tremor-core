# Tasks: cache and verify

- [x] 1. Supabase pgvector cache with exact hash and cosine (R1, R2) `cache/pgvector_cache.py`
- [x] 2. Threshold 0.97 from config (R2.2) `chimera.example.toml`
- [x] 3. Lookup budget and no-cache fallback (R3) `tests/test_pgvector_cache.py`
- [x] 4. No local answer cache (R1.2) `tests/test_no_local_cache.py`
- [x] 5. Guard for numbers, negation, entities (R4) `cache/guard.py`, `tests/test_cache_guard.py`
- [x] 6. 30B confidence gate 0.95 with self-check fallback (R6) `router.py`
- [x] 7. Tier pool with timeouts and escalation (R6.3, R6.4) `tiers.py`, `tests/test_tiers.py`
- [x] 8. Telemetry fields on every call (R7) `inference/telemetry.py`
- [x] 9. Speculative verify and Spec+ benches (R8) `bench/results_specplus.md`, `bench/spec_results.md` (4.5x to 7x slower than plain Ollama; not a product tier)
- [ ] 10. 30B yes/no check on cosine hits (R5): not built
- [ ] 11. Property tests P1 to P8 as `tests/test_props_*.py`: owned by `.kiro/specs/chimera-speculative-os/tasks.md`
- [ ] 12. Repeat the cache eval on 1,000 Quora pairs with all 4 Supabase configs: only 1 of 4 ran (`docs/handoff/real-datasets-suite.md`)
