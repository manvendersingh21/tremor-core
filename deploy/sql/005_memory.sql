-- N+1 memory: teacher pairs (big-model answers that passed their checks) and a small knowledge graph.
-- Same RLS pattern as 002: the client sets `app.tenant` per transaction. Needs 001 (pgvector). Touches only these 3 tables.
create extension if not exists vector;

create table if not exists teacher_pairs (
    id               bigint generated always as identity primary key,
    tenant           text        not null,
    prompt           text        not null,           -- secrets/PII already stripped
    prompt_embedding vector(384) not null,            -- all-MiniLM-L6-v2, L2-normalized
    answer           text        not null,
    model            text        not null default '',
    tier             text        not null default '',
    verified         boolean     not null default true,
    tests_passed     boolean,                         -- null = graded by a blind grader instead
    tokens_in        integer     not null default 0,
    tokens_out       integer     not null default 0,
    created_at       timestamptz not null default now()
);
create index if not exists teacher_pairs_tenant on teacher_pairs (tenant, created_at);
create index if not exists teacher_pairs_emb on teacher_pairs using hnsw (prompt_embedding vector_cosine_ops);

create table if not exists mem_nodes (
    id         bigint generated always as identity primary key,
    tenant     text        not null,
    kind       text        not null check (kind in ('problem', 'solution', 'concept', 'pattern', 'error')),
    text       text        not null,
    embedding  vector(384) not null,
    created_at timestamptz not null default now()
);
create index if not exists mem_nodes_tenant_kind on mem_nodes (tenant, kind);
create index if not exists mem_nodes_emb on mem_nodes using hnsw (embedding vector_cosine_ops);

create table if not exists mem_edges (
    tenant     text   not null,                       -- repeated here so RLS works without a join
    src        bigint not null references mem_nodes(id) on delete cascade,
    dst        bigint not null references mem_nodes(id) on delete cascade,
    rel        text   not null check (rel in ('solves', 'uses', 'similar_to', 'fixes', 'part_of')),
    weight     real   not null default 1.0,
    created_at timestamptz not null default now(),
    primary key (src, dst, rel)
);
create index if not exists mem_edges_dst on mem_edges (dst);
create index if not exists mem_edges_tenant on mem_edges (tenant);

alter table teacher_pairs enable row level security;
alter table mem_nodes     enable row level security;
alter table mem_edges     enable row level security;
alter table teacher_pairs force row level security;
alter table mem_nodes     force row level security;
alter table mem_edges     force row level security;

drop policy if exists tenant_isolation on teacher_pairs;
create policy tenant_isolation on teacher_pairs
    using (tenant = current_setting('app.tenant', true)) with check (tenant = current_setting('app.tenant', true));
drop policy if exists tenant_isolation on mem_nodes;
create policy tenant_isolation on mem_nodes
    using (tenant = current_setting('app.tenant', true)) with check (tenant = current_setting('app.tenant', true));
drop policy if exists tenant_isolation on mem_edges;
create policy tenant_isolation on mem_edges
    using (tenant = current_setting('app.tenant', true)) with check (tenant = current_setting('app.tenant', true));

do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'chimera_app') then
        create role chimera_app login;
    end if;
end $$;
grant select, insert, update, delete on teacher_pairs, mem_nodes, mem_edges to chimera_app;
grant usage, select on all sequences in schema public to chimera_app;
