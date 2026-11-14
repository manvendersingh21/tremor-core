# Design: N+1 memory and solved-problem bank

## Flow
```
big model answers + tests pass -> scrub -> Supabase teacher_pairs (pair + embedding)
                                        -> Aura graph: Problem -SOLVED_BY-> Solution -USES-> Concept
next prompt -> embed -> nearest problems (cosine) -> graph expand 1-2 hops -> rank -> render <= 800 tokens -> before the 30B call
```

## Components
| Part | File |
|---|---|
| Interface (`build`, `retrieve`, `store`, `stats`, `purge`) | `memory/memory.py` |
| `GraphStore` protocol, in-memory store | `memory/graph.py` |
| Aura store | `memory/neo4j_store.py` |
| Concept extraction (30B, then heuristic) | `memory/extract.py` |
| Scrubber | `memory/safety.py` |
| Supabase tables | `deploy/sql/005_memory.sql` |
| Harness | `bench/memory/run_memory.py`, `bench/memory/report.py` |

## Decisions
- Aura only: a single graph store, fewer failure paths (`docs/memory.md`).
- Never raise: memory is a bonus, not a dependency of an answer.
- Supabase keeps pairs and embeddings because they are training data for `lora-distill`.
- The bank is **planned**; its schema is not decided. Candidate: a `solved_bank` table beside `teacher_pairs`, keyed by prompt hash and embedding.

## Correctness properties
Property tests for router, cache and firewall belong to `.kiro/specs/chimera-speculative-os/`; these are the memory-specific ones.

| ID | Property | Requirement |
|---|---|---|
| P1 | `store` returns `None` for every input where verified is false. | R1.2 |
| P2 | `scrub(scrub(x)) == scrub(x)` and no email, key or card pattern survives `scrub`. | R2 |
| P3 | `retrieve(...).render()` never exceeds the token cap, for any stored data. | R3.2 |
| P4 | With the store raising on every call, `retrieve` returns an empty context and `store` returns without raising. | R4.3 |
| P5 | A query for tenant A never returns a node or pair of tenant B. | R5 |
| P6 | After `purge(A)`, tenant A has zero pairs, nodes and edges and tenant B is unchanged. | R5.2 |
| P7 | Results under `min_score` (0.30) are never rendered. | R3.2 |

Tests: `tests/test_memory.py` (fakes only). Bank tests will be `tests/test_bank.py`.
