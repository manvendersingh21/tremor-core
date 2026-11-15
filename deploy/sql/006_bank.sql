-- Solved-problem bank: verified problem/solution pairs, looked up before any model call.
-- Same RLS pattern as 005. Needs 001 (pgvector). Touches only this table.
create extension if not exists vector;

create table if not exists solved_bank (
    id               bigint generated always as identity primary key,
    tenant           text        not null,
    prompt_hash      text        not null,            -- sha256 of the normalized, scrubbed problem
    prompt           text        not null,            -- secrets/PII already stripped
    prompt_embedding vector(384) not null,            -- all-MiniLM-L6-v2, L2-normalized
    answer           text        not null,
    tests            jsonb       not null default '{}', -- what the answer passed; re-run before it is served
    source           text        not null default '', -- humaneval, mbpp, suite, 763b, ...
    model            text        not null default '',
    tier             text        not null default '',
    tokens_in        integer     not null default 0,
    tokens_out       integer     not null default 0,
    hits             integer     not null default 0,
    created_at       timestamptz not null default now(),
    unique (tenant, prompt_hash)
);
create index if not exists solved_bank_emb on solved_bank using hnsw (prompt_embedding vector_cosine_ops);

alter table solved_bank enable row level security;
alter table solved_bank force row level security;
drop policy if exists tenant_isolation on solved_bank;
create policy tenant_isolation on solved_bank
    using (tenant = current_setting('app.tenant', true)) with check (tenant = current_setting('app.tenant', true));
grant select, insert, update, delete on solved_bank to chimera_app;
grant usage, select on all sequences in schema public to chimera_app;
