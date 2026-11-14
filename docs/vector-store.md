# Shared prompt cache (Postgres + pgvector)

Status: built and unit-tested against a fake store. **Not yet measured on a live database.** The numbers section at the end is empty until `CHIMERA_DB_URL` is set and the benchmark has run.

## Why a shared cache

The SQLite cache lives on one machine. Each laptop, phone and gateway relearns the same answers. GPUs are scarce, so every call that one machine already answered should skip the GPU on all the others. One Postgres table with a vector index gives every client the same memory.

```
laptop ─┐
phone  ─┼─> PgVectorCache ──> Postgres + pgvector   (exact hash, then nearest neighbour)
gateway─┘        │
                 └─ DB down or over 150 ms ──> local SQLite cache ──> normal ladder
```

Code: `packages/chimera-core/cache/pgvector_cache.py`. Same interface as `SemanticCache` (`get`, `put`, `purge`), plus `get_hit`, `report_false_hit`, `mark_verified`, `record_signal`, `summary`.

## Lookup rules

1. Exact: sha256 of `namespace + normalized prompt`. A verified, unexpired row is served.
2. Else nearest neighbour: cosine distance over `vector(384)` (all-MiniLM-L6-v2), top `top_k` rows of this tenant and namespace. The best row with similarity >= `thresholds.semantic` (0.97) **and `verified = true`** is served.
3. Unverified rows are stored but never auto-served. Pass `put(..., verified=False)` for answers no check has passed. `mark_verified(id)` promotes one.
4. `report_false_hit(hit)` sets `verified = false` on the row and writes a `false_hit` event. The row stops being served at once.
5. Never block on the DB. Each lookup gets `budget_ms` (150). On timeout or error the local SQLite cache answers and the DB is skipped for 30 s (circuit breaker). Writes run on a background thread and never delay the caller.

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
backend = "postgres"        # "sqlite" is the default
dsn_env = "CHIMERA_DB_URL"  # name of the env var; the value goes in .env
tenant = "team-a"
store_text = false
# ttl_s = 2592000
top_k = 5
budget_ms = 150
```

`.env`: `CHIMERA_DB_URL=postgresql://chimera_app:<password>@<host>:5432/<db>`. If `backend = "postgres"` but the variable is empty, the router logs a warning and uses SQLite. Install the driver with `pip install -e ".[postgres]"` (psycopg 3 with a small pool).

## Supabase setup

1. Create a project. Database > Extensions > enable `vector`.
2. Open the SQL editor and run `001_schema.sql`, `002_rls_tenant.sql`, then `003_supabase_api.sql`.
3. Database > Roles: set a password for `chimera_app`. Do not use the `postgres` role in clients. It bypasses RLS.
4. Copy the connection string (Database > Connect > Session pooler, port 5432) into `.env` with the `chimera_app` user. The transaction pooler (6543) also works because each operation sets `app.tenant` inside its own transaction.
5. Set `[cache] backend = "postgres"` and a `tenant` per team or device group.
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
- The 150 ms budget is shorter than a cross-region round trip. A far DB will fall back most of the time. Put the DB near the clients.
- The exact-hash cache in the router (`ExactCache`) is still local. Only the semantic cache is shared.

## Measured results

None yet. Pending: live database credentials.
