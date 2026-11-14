# Shared prompt cache (Postgres + pgvector)

Status: built, migrated on a Supabase project (Postgres 17, pgvector) and measured once with `bench/run_cache.py`. Single run, 18 gradable prompts. See "Measured results".

**Since 2026-11-14 this is the ONLY answer cache.** No machine keeps an answer cache of its own (no SQLite exact or semantic cache, no SQLite fallback). `[cache] backend = "supabase"` is the default. `backend = "sqlite"` remains for offline tests only. The four rows that were in `~/.chimera/cache.db` were moved here as `verified = false` (tier `migrated-local`) and the file was deleted. llama.cpp's in-memory prompt KV reuse (`cache_prompt`) is not an answer cache and stays.

## Why a shared cache

A per-machine cache lives on one machine. Each laptop, phone and gateway relearns the same answers. GPUs are scarce, so every call that one machine already answered should skip the GPU on all the others. One Postgres table with a vector index gives every client the same memory.

```
laptop ─┐
phone  ─┼─> PgVectorCache ──> Postgres + pgvector   (exact hash, then nearest neighbour)
gateway─┘        │
                 └─ DB down or over the budget (300 ms) ──> no cache for this call ──> normal ladder (event cache_shared: unavailable)
```

Code: `packages/chimera-core/cache/pgvector_cache.py`. Same interface as `SemanticCache` (`get`, `put`, `purge`), plus `get_hit`, `report_false_hit`, `mark_verified`, `record_signal`, `summary`.

## Lookup rules

1. Exact: sha256 of `namespace + normalized prompt`. A verified, unexpired row is served.
2. Else nearest neighbour: cosine distance over `vector(384)` (all-MiniLM-L6-v2), top `top_k` rows of this tenant and namespace. The best row with similarity >= `thresholds.semantic` (0.97) **and `verified = true`** is served.
3. Unverified rows are stored but never auto-served. Pass `put(..., verified=False)` for answers no check has passed. `mark_verified(id)` promotes one.
4. `report_false_hit(hit)` sets `verified = false` on the row and writes a `false_hit` event. The row stops being served at once.
5. Guard (`cache/guard.py`, on by default): a cosine hit is served only if the two prompts agree on numbers, negation and named entities. It needs `store_text = true` (the default now) because it compares against the stored prompt text.
6. Never block on the DB. Each lookup gets `budget_ms` (300; see results for why not 150). On timeout or error the call skips the cache and goes to the model tiers; the step event says `cache_shared` status `unavailable`. Nothing is written locally instead. After 3 failures in a row the DB is skipped for 30 s (circuit breaker). A lookup is one round trip (exact row and top-k in one pipelined transaction). Writes run on a background thread and never delay the caller.

## Schema

SQL is in `deploy/sql/`. Run the files in order.

```
prompts                          routing_signals              cache_events
-------------------------        --------------------         ------------------
id  PK                    <──┐   id  PK                       id  PK
tenant, namespace            ├── prompt_id  FK                tenant
prompt_hash  (unique with    │   tenant                       kind  hit|miss|false_hit
   tenant+namespace)         │   tier_tried                   prompt_id  FK (nullable)
prompt_text  (null by        │   confidence                   similarity, lookup_ms
   default, opt-in)          │   escalated                    created_at
embedding  vector(384) HNSW  │   passed_checks
answer, model, tier          │   latency_ms, cost
tokens_in, tokens_out        └── created_at
verified, created_at
hits, last_hit_at, ttl_s
```

`routing_signals` feeds the learned router: call `cache.record_signal(prompt_id, tier, confidence=..., escalated=..., passed_checks=..., latency_ms=..., cost=...)`.

| File | What it does |
|---|---|
| `001_schema.sql` | `vector` extension, three tables, HNSW index (`vector_cosine_ops`) |
| `002_rls_tenant.sql` | Row Level Security on all three tables, policy on `app.tenant`, role `chimera_app` |
| `003_supabase_api.sql` | Supabase only. Read-only policies for REST clients, keyed on a JWT `tenant` claim |

## Config

`chimera.toml` (the DSN is never in this file):

```toml
[cache]
backend = "supabase"        # the default; "postgres" is the same; "sqlite" = offline tests only
dsn_env = "CHIMERA_DB_URL"  # name of the env var; the value goes in .env
tenant = "team-a"
store_text = true           # the guard and N+1 memory need the prompt text
guard = true
# ttl_s = 2592000
top_k = 5
budget_ms = 300
```

`.env`: `CHIMERA_DB_URL=postgresql://chimera_app:<password>@<host>:5432/<db>`. If the variable is empty, the router logs a warning and runs with no answer cache at all. Install the driver with `pip install -e ".[postgres]"` (psycopg 3 with a small pool).

## Supabase setup

1. Create a project. Database > Extensions > enable `vector`.
2. Open the SQL editor and run `001_schema.sql`, `002_rls_tenant.sql`, then `003_supabase_api.sql`.
3. Database > Roles: set a password for `chimera_app`. Do not use the `postgres` role in clients. It bypasses RLS.
4. Use the **session pooler** (`aws-0-us-west-2.pooler.supabase.com:5432`, user `postgres.<project-ref>`), not the direct `db.<ref>.supabase.co` host. The direct host is IPv6-only and many networks (including the Mac used here) cannot reach it. Put the string in `.env` as `CHIMERA_DB_URL`. Later switch the user to `chimera_app.<project-ref>` once you set its password. The transaction pooler (6543) also works because each operation sets `app.tenant` inside its own transaction.
5. Keep `[cache] backend = "supabase"` (default) and set a `tenant` per team or device group.
6. Optional: for the Supabase REST API, add `{"tenant": "team-a"}` to `app_metadata` of each user. `003` then lets that user read only that tenant's rows.

## Plain Postgres setup

1. Install pgvector (version 0.5 or newer for HNSW). Ubuntu: `apt install postgresql-16-pgvector`. Managed services: enable the `vector` extension.
2. As a superuser, run `psql "$ADMIN_URL" -f deploy/sql/001_schema.sql -f deploy/sql/002_rls_tenant.sql`. Skip `003`.
3. `ALTER ROLE chimera_app PASSWORD '...'` and put the DSN in `.env`.

## Row Level Security

Each operation runs `select set_config('app.tenant', <tenant>, true)` and then its SQL. Policy: `tenant = current_setting('app.tenant', true)`, for reads and writes. `FORCE ROW LEVEL SECURITY` is on. A client that forgets to set the tenant sees nothing.
RLS does not apply to the table owner or to roles with `BYPASSRLS` (`postgres`, `service_role`). Clients must connect as `chimera_app`.

## Privacy

- Prompt text is **not stored** unless `store_text = true`. Without it a row holds the hash, the embedding and the answer. An embedding is not readable text, but it can leak some meaning, and the answer may quote the prompt. Treat the table as sensitive.
- `ttl_s` expires rows. Expired rows are not served. Delete them with `delete from prompts where ttl_s is not null and created_at + ttl_s * interval '1 second' < now();`. Run it from cron.
- Purge a tenant: `PgVectorCache(...).purge()` deletes all of the tenant's rows, `purge("namespace")` one namespace. In SQL: `delete from prompts where tenant = 'team-a';`. Signals go with them (cascade). Events keep a null `prompt_id`.
- Keep different customers in different tenants. Do not share a tenant across trust boundaries.

## Metrics

- `Telemetry` has three optional fields: `gpu_calls_avoided` (set to 1 when a cache answered), `false_hit`, `cache_lookup_ms`. `TelemetryTracker.totals()` adds `gpu_calls_avoided`, `cache_hits`, `hit_rate`, `false_hits`, `false_hit_rate`. Old events and readers are unaffected.
- Gateway `/metrics`: `chimera_gpu_calls_avoided_total`, `chimera_cache_false_hits_total`, `chimera_cache_hit_rate`, `chimera_cache_false_hit_rate`, per tenant.
- `PgVectorCache.summary()` returns lookups, hit rate, false-hit rate, fallbacks, lookup p50 and p90 in ms.
- A false hit is only counted when something reports it (`report_false_hit`, or `Telemetry.false_hit`). Nothing detects it on its own.

## How to measure

Run the same prompt set twice, once per backend, from a clean cache each time:

1. `[cache] backend = "sqlite"`, then the suite. 2. `[cache] backend = "postgres"` with a fresh tenant, then the suite.
3. Compare hit rate, GPU calls avoided, lookup p50 and p90, and graded false hits. The second run of the same set should show the shared-memory effect only if a second client, or a second process, reads what the first wrote.

## Known limits

- With HNSW and a tenant filter, a tenant with few rows in a big table can get fewer than `top_k` rows back. On pgvector 0.8 set `hnsw.iterative_scan = relaxed_order`. Below about 100k rows, this does not matter.
- Embeddings are sent to the DB as text (`'[..]'::vector`), so the `pgvector` Python package is not needed.
- Measured from a Mac to us-west-2 over the pooler: a connection round trip is about 30 ms and one cache lookup about 105-135 ms. A 150 ms budget therefore fell back to SQLite for 59 of 60 lookups after a few slow ones. The default is 300 ms. Put the DB near the clients, or raise `budget_ms`.
- The benchmark connected as the `postgres` role, which bypasses RLS. RLS itself was checked separately (below).
- The exact-hash cache in the router (`ExactCache`) is still local. Only the semantic cache is shared.

## Measured results

Date 2026-11-13. Script: `bench/run_cache.py` (cache only, no model or GPU, MiniLM embeddings, threshold 0.97). Single run, no repeats. Client A answers the 18 prompts in `bench/prompts.jsonl` that have a known answer (13 GPU calls; 5 were served from A's own cache). Client B is a second machine with an empty local SQLite and asks 60 prompts: 18 same text, 18 changed case and spacing, 18 with "Quick question:" added, 6 near-misses (similar words, different answer). "GPU calls avoided" is the number of B prompts answered from a cache.

| Mode | Budget | Hit rate | GPU calls avoided (of 60) | Lookup p50 / p90 | False hits | DB fallbacks |
|---|---|---|---|---|---|---|
| SQLite, B reuses A's file (one machine) | n/a | 0.80 | 48 | 10.0 / 11.2 ms | 0 | n/a |
| SQLite, B has its own file (two machines) | n/a | 0.00 | 0 | 8.9 / 10.4 ms | 0 | n/a |
| Postgres, shared | 300 ms | 0.80 | 48 | 121 / 135 ms | 0 | 0 |
| Postgres, shared | 150 ms | 0.017 | 1 | 18 / 22 ms | 0 | 59 of 60 |

By set (Postgres at 300 ms): same text 18/18, case and spacing 18/18, paraphrase 12/18, near-miss 0/6. All 6 near-misses were correctly not served.

Read this as: a second machine gets the same hit rate as a single machine only when the cache is shared, and the shared lookup costs about 100 ms more than a local one. A GPU call costs seconds (median 1.9 s on the local 30B in `bench/results_gpu.md`), so a hit still wins. At 150 ms the cache did not help from this Mac.
Not measured: more than one run, real traffic, many tenants, rows above a few hundred, the ladder with a live GPU, and the gap to a user who sits near the database. Paraphrases are one fixed template, so the 0.67 paraphrase hit rate does not generalise. Only 6 near-miss prompts: 0 false hits here does not bound the false-hit rate.

RLS check (as role `chimera_app`, run in a transaction and rolled back): tenant `a` saw only its own row, and inserting a row for tenant `b` was refused (`InsufficientPrivilege`). Migrations ran as `postgres`; `grant chimera_app to current_user` was needed so that role could `SET ROLE` for the test.
