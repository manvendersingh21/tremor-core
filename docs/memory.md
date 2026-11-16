# N+1 memory

Every problem the big model solves (and that passes its tests) is stored. The next time the 30B gets a similar
problem, it gets the stored solutions and their key ideas as context.

Code: `packages/chimera-core/memory/`. Tests: `tests/test_memory.py` (fakes only). SQL: `deploy/sql/005_memory.sql`.

## Interface (for the router owner)

```python
from chimera_core.memory import build
mem = build(embedder, tenant="acme", extractor=...)            # embedder: .embed(text) -> 384 floats (MiniLM)

ctx = mem.retrieve(prompt, k=3)       # MemoryContext(examples=[Example(problem, solution, why, score)], concepts=[...])
text = ctx.render()                   # "" when memory has nothing; capped at 800 tokens (chars/4 estimate)
prompt30 = (text + "\n\n" + prompt) if text else prompt      # put it BEFORE the 30B call

mem.store(prompt, answer, model="deepseek-ai/DeepSeek-V4.1-Flash", tier="top",
          verified=True, tests=True, tokens={"in": 812, "out": 340})   # AFTER a verified big-model answer
mem.stats(); mem.purge()              # purge = delete this tenant's pairs, nodes and edges
```

`store` returns the pair id, or `None` if refused. It refuses unless `verified` is true AND (`tests is True` OR
`tests is None and score >= 4`, a blind grader score out of 5). Prompt and answer pass through `scrub()` first
(emails, API keys, JWTs, DB URLs, `password=` values, SSN, Luhn-valid card numbers, phone numbers).

## Where it goes in `SpeculativeCascadeRouter.generate()`

1. Before the 30B (tier 2) call: `ctx = mem.retrieve(prompt)`; send `ctx.render() + prompt` when non-empty.
2. After the big model (tier 3) answers and the check passes: `mem.store(...)`.
3. Log `ctx.tokens` as extra input tokens so the telemetry stays honest.

## Retrieval (three signals)

1. **Nearest problems** by cosine on the prompt embedding.
2. **Graph expansion**, 1 to 2 hops: problem -> solution -> concept -> other solutions that use that concept
   -> their problems. A 2-hop problem gets half the weight.
3. **Rank** = similarity x (0.5 + 0.5 x edge weight) x recency (30-day half-life, floor 0.5). Items under `min_score`
   (0.30) are dropped. The top `k` are rendered; the text is cut to fit the token cap.

## Schema (Supabase, `deploy/sql/005_memory.sql`)

```
teacher_pairs  (tenant, prompt, prompt_embedding vector(384), answer, model, tier, verified, tests_passed,
                tokens_in, tokens_out, created_at)                    -- training data for fine-tune / distillation
mem_nodes      (id, tenant, kind: problem|solution|concept|pattern|error, text, embedding vector(384), created_at)
mem_edges      (tenant, src, dst, rel: solves|uses|similar_to|fixes|part_of, weight)
```

```
 problem <--solves-- solution --uses--> concept
    |  \                 ^                  ^
 similar_to         pattern --part_of-      (shared by many solutions)
    v
 problem          pattern = one line "why it works"
```

RLS: same pattern as 002 (`app.tenant`). Every query also filters on tenant.

## Graph store (adapter)

`GraphStore` is a Protocol (`memory/graph.py`): `add_node, find_node, add_edge, nearest, neighbors, add_pair, stats,
purge`. Implementations: `InMemoryStore` (tests and the benchmark curve), `PgGraphStore` (Supabase tables from
`005_memory.sql`, kept as an adapter, not used as a fallback) and `Neo4jGraphStore` (`memory/neo4j_store.py`).

**The graph is hosted Neo4j Aura only.** `default_store()` / `build(embedder, tenant)` read `CHIMERA_GRAPH_URL`,
`CHIMERA_GRAPH_USER`, `CHIMERA_GRAPH_PASSWORD`, `CHIMERA_GRAPH_DATABASE` from `.env` (names in `.env.example`, never
values). There is no Akash Neo4j and no Postgres graph fallback. If Aura is unreachable, `retrieve` returns an empty
context for that call and `store` skips the graph part; both log `chimera.memory` warnings and never raise.
Supabase keeps `teacher_pairs` (training data), embeddings and the answer cache. Install the driver with
`pip install .[graph]` (the `neo4j` package).

Graph model in Aura: `(:Problem)-[:SOLVED_BY]->(:Solution)-[:USES]->(:Concept)`,
`(:Problem)-[:SIMILAR_TO {score}]->(:Problem)`, `(:Solution)-[:FIXES]->(:Error)`, and `(:Pattern)-[:PART_OF]->(:Solution)`
for the one-line "why it works". Every node also has the label `:Mem` and `id, tenant, text, embedding, created_at`.
Embeddings use Neo4j vector indexes (cosine, 384 dims), one per label. Tenants are separated by the `tenant` property
on every node and edge, and every query filters on it.

Concept extraction on `store`: the 30B itself (`llm_extractor`), falling back to a code-pattern heuristic. No GMI call.

Tests use fakes only (`tests/test_memory.py`); the Aura round trip (write, read, purge in a test tenant) was checked by hand once.

## Solved-problem bank (`memory/bank.py`, `deploy/sql/006_bank.sql`)

Verified problem/solution pairs, looked up before any model call. Supabase `solved_bank` holds the text, the 384-d
embedding (pgvector, cosine), the answer and the tests it passed. Each banked pair is also written through
`Memory.store`, so the same problem and solution land in the Aura graph and in `teacher_pairs`.

```
problem -> bank.lookup(problem, tests) -> served   exact hash or cosine >= 0.90, answer passed the tests just now
                                       -> hint     cosine 0.70-0.90, or a close one whose tests failed: give it to the 30B
                                       -> miss     go down the ladder (30B, then 763B)
passing answer from the ladder -> bank.add(problem, answer, tests, source, model, tier)
```

Call it from `chimera code` (or any caller that has tests):

```python
from chimera_core.memory import Bank, PgBankStore
bank = Bank(PgBankStore(os.environ["CHIMERA_DB_URL"]), embedder, tenant, verify)   # verify(answer, tests) -> bool
hit = bank.lookup(problem, tests)          # tests: a JSON-able dict, the new problem's own tests
if hit.kind == "served":  answer = hit.answer
else:                     prompt = hit.hint_text() + problem   # empty on a miss
...                                          # ladder call, then run the tests
bank.add(problem, answer, tests, source="humaneval", model="763b", tier="top")   # refused unless the tests pass again
```

Rules: a cosine match with no tests to run is never served, only offered as a hint. An exact match without new tests
re-runs the tests stored with it. `add` re-runs the tests itself and ignores the caller's flag. Problem, answer and
tests pass through `scrub()` before storing. Everything is per tenant (RLS plus a tenant filter) and `bank.purge()`
removes a tenant. `lookup` and `add` never raise: a store failure is a miss or a skipped write. Pass `memory=Memory(...)`
to link the pairs into the graph. Numbers: `bench/results_bank.md`. Test: `tests/test_bank.py`.

**chimera code:** looked up before any model call, when a test command is set and `CHIMERA_DB_URL` is in the env
(`--no-bank` turns it off; tenant `<cache.tenant>:terminal`). The problem is the request plus the context file
blocks; the tests are the test command plus the context files as they are at the start of the task.
`Session.verify` copies the project to a temp dir, restores those files, applies the stored edits and runs the
tests there; the project itself is never touched. A served answer is still shown as a diff for approval, written,
and tested again in the project. If that fails, it is undone and the model answers. The status line reads
`-> bank (exact) · 0 tok · $0 · ...`, and `/cost` has a `bank` row. When a model answer passes the tests, the
changed files go back to the bank as `FILE:` blocks, after `add` runs the tests once more. Hints are not put into
the prompt yet. Tests: `tests/test_terminal.py`.
