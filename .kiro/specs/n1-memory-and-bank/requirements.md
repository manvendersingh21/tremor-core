# Requirements: N+1 memory and solved-problem bank

Scope: teacher data in Supabase `teacher_pairs`, the concept graph in hosted Neo4j Aura, retrieval before the 30B call, and the planned solved-problem bank. Code: `packages/chimera-core/memory/`. Doc: `docs/memory.md`. SQL: `deploy/sql/005_memory.sql`.

## Requirements

### R1 Store only verified answers
1. WHEN a 763B or 120B answer passes its tests, THE memory SHALL store prompt, answer, model, tier, token counts and `tests_passed`.
2. IF `verified` is false, or `tests` is not true and the blind score is below 4, THEN `store` SHALL refuse and return `None`.

### R2 Scrub before storing
1. THE memory SHALL scrub emails, API keys, JWTs, DB URLs, `password=` values, SSNs, Luhn-valid card numbers and phone numbers from prompt and answer before any write.

### R3 Retrieve before the 30B call
1. WHEN the 30B is about to be called, THE router SHALL call `retrieve(prompt, k=3)` and put the rendered examples before the prompt.
2. THE rendered context SHALL be at most 800 tokens (chars/4 estimate) and SHALL be empty when nothing scores >= 0.30.
3. THE router SHALL log the context tokens as extra input tokens.

### R4 Graph lives only in Aura
1. THE graph store SHALL be hosted Neo4j Aura, configured by `CHIMERA_GRAPH_URL`, `CHIMERA_GRAPH_USER`, `CHIMERA_GRAPH_PASSWORD`, `CHIMERA_GRAPH_DATABASE`.
2. THERE SHALL be no Postgres graph fallback and no Neo4j on the GPU box.
3. IF Aura is unreachable, THEN `retrieve` SHALL return an empty context and `store` SHALL skip the graph part. Neither SHALL raise.

### R5 Tenant isolation
1. EVERY node, edge and pair SHALL carry a tenant and EVERY query SHALL filter on it.
2. `purge` SHALL delete only the calling tenant's data.

### R6 Ranking
1. Rank SHALL be similarity x (0.5 + 0.5 x edge weight) x recency (30-day half-life, floor 0.5). A 2-hop result SHALL get half weight.

### R7 Solved-problem bank (planned)
1. THE bank SHALL hold verified problem and solution pairs fed by the same checked answers as R1.
2. WHEN a new prompt matches a bank entry, THE router SHALL offer it as context before any model call.
3. THE bank SHALL be separate from the answer cache and SHALL NOT be served as a final answer without a check.

### R8 Honest measurement
1. THE benchmark SHALL report tokens and dollars with and without memory, including cases where memory costs more (`bench/memory/run_memory.py`). Not measured yet.
