# Design: cache and verify

## Flow
```
prompt -> embed -> Supabase exact hash -> cosine >= 0.97 -> guard -> [30B yes/no check, planned]
       -> hit: answer ($0)
       -> miss: tier pool: gpu-small 30B -> (gpu-large 120B, off) -> cloud-deepseek 763B
                each answer: confidence gate (>= 0.95) or self-check; fail = next tier
```

## Components
| Part | File |
|---|---|
| Shared cache (pgvector) | `packages/chimera-core/cache/pgvector_cache.py` |
| Exact hash | `cache/exact_cache.py` |
| Guard | `cache/guard.py` |
| Router and step events | `router.py`, `service.py` |
| Tier pool, health, timeouts | `tiers.py` |
| Telemetry | `inference/telemetry.py` |
| Spec verify (experiment) | `inference/specplus.py`, `bench/verify_server.py` |
| SQL | `deploy/sql/001_schema.sql`, `002_rls_tenant.sql` |

## Decisions
- Threshold 0.97: 0.94 served wrong answers (`bench/results_gpu.md`); at 0.97 the ladder run served none (`bench/results_ladder.md`).
- Guard on: wrong hits 4 -> 2 on 800 QQP pairs, recall 10.1% -> 9.1% (`bench/results_research_cache.md`).
- Shared cache: hit rate 0.80, 48 of 60 GPU calls avoided, 0 false hits, lookup median 121 ms (`docs/vector-store.md`).
- Failure mode is always "no cache": the call still gets an answer.

## Correctness properties
The formal property tests for the router, cache and firewall are owned by `.kiro/specs/chimera-speculative-os/` (not edited from here). The properties below link to requirements.

| ID | Property | Requirement |
|---|---|---|
| P1 | An exact-hash hit returns the stored answer unchanged. | R2.1 |
| P2 | A semantic hit is returned only when score >= 0.97, for any threshold value in config. | R2.2 |
| P3 | A cache failure or timeout never raises and never makes the answer source "cache". | R3 |
| P4 | The guard rejects a candidate whose numbers differ from the prompt's numbers. | R4.1 |
| P5 | The router never writes a cache file outside the configured store. | R1.2 |
| P6 | Escalation is monotonic: a failed check moves to a strictly higher tier. | R6.3 |
| P7 | Every `generate()` result carries the five telemetry fields. | R7 |
| P8 | Accept rule `min(1, p_target/p_draft)` keeps the target distribution (statistical). | R8 |

Tests: `tests/test_router.py`, `tests/test_pgvector_cache.py`, `tests/test_cache_guard.py`, `tests/test_tiers.py`, `tests/test_no_local_cache.py`, `tests/test_specplus.py`.

## Open
- R5 needs a prompt, a timeout and a measured false-hit rate before it is turned on.
