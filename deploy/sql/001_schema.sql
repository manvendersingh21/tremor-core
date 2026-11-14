-- Shared prompt cache. Needs the pgvector extension (Supabase: Database > Extensions > vector).
create extension if not exists vector;

create table if not exists prompts (
    id           bigint generated always as identity primary key,
    tenant       text        not null,
    namespace    text        not null default '',
    prompt_hash  text        not null,                 -- sha256 of namespace + normalized prompt
    prompt_text  text,                                 -- null unless cache.store_text = true (opt-in)
    embedding    vector(384) not null,                 -- all-MiniLM-L6-v2, L2-normalized
    answer       text        not null,
    model        text        not null default '',
    tier         text        not null default '',
    tokens_in    integer     not null default 0,
    tokens_out   integer     not null default 0,
    verified     boolean     not null default true,    -- only verified rows are auto-served
    created_at   timestamptz not null default now(),
    hits         integer     not null default 0,
    last_hit_at  timestamptz,
    ttl_s        integer,                              -- null = never expires
    unique (tenant, namespace, prompt_hash)
);

create index if not exists prompts_embedding_hnsw
    on prompts using hnsw (embedding vector_cosine_ops);
create index if not exists prompts_tenant_ns on prompts (tenant, namespace);

create table if not exists routing_signals (
    id             bigint generated always as identity primary key,
    prompt_id      bigint references prompts(id) on delete cascade,
    tenant         text not null,
    tier_tried     text not null,
    confidence     real,
    escalated      boolean not null default false,
    passed_checks  boolean,
    latency_ms     real,
    cost           real,
    created_at     timestamptz not null default now()
);
create index if not exists routing_signals_prompt on routing_signals (prompt_id);

create table if not exists cache_events (
    id          bigint generated always as identity primary key,
    tenant      text not null,
    kind        text not null check (kind in ('hit', 'miss', 'false_hit')),
    prompt_id   bigint references prompts(id) on delete set null,
    similarity  real,
    lookup_ms   real,
    created_at  timestamptz not null default now()
);
create index if not exists cache_events_tenant_kind on cache_events (tenant, kind, created_at);
