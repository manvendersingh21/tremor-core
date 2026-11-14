# Tasks: N+1 memory and solved-problem bank

- [x] 1. `store` and `retrieve` interface with scrub and verified gate (R1, R2, R3) `memory/memory.py`, `memory/safety.py`
- [x] 2. In-memory graph store for tests (R5, R6) `memory/graph.py`, `tests/test_memory.py`
- [x] 3. Neo4j Aura store, Aura only, never-fail (R4) `memory/neo4j_store.py` (commit 4c3164d)
- [x] 4. Supabase `teacher_pairs`, `mem_nodes`, `mem_edges` with RLS (R1, R5) `deploy/sql/005_memory.sql`
- [x] 5. Concept extraction by the 30B with a heuristic fallback `memory/extract.py`
- [x] 6. Benchmark harness `bench/memory/run_memory.py`
- [ ] 7. Router hook (retrieve before the 30B, store after a checked big answer, R3): the `memory` step event is in `docs/api.md`; wiring in `router.py` not re-verified here
- [ ] 8. Run the harness and write `bench/results_memory.md` with wins and losses (R8): file does not exist
- [ ] 9. Solved-problem bank: schema, store, lookup, tests (R7): not built
- [ ] 10. Property tests P1 to P7 as `tests/test_props_memory.py`
