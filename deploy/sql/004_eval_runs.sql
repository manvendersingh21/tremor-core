-- One row per evaluated item and mode (bench/evallog.py EvalRow). Upsert key: (run_id, item_id, mode).
create table if not exists eval_runs (
    tenant        text not null default 'bench',
    run_id        text not null,
    ts            text,
    source_file   text,
    dataset       text not null,
    item_id       text not null,
    mode          text not null,
    tier          text,
    model         text,
    tokens_in     integer,
    tokens_out    integer,
    cached_tokens integer,
    dollars       double precision,
    latency_ms    double precision,
    passed        boolean,
    grader        text,
    notes         text,
    primary key (run_id, item_id, mode)
);
create index if not exists eval_runs_dataset_mode on eval_runs (dataset, mode);
alter table eval_runs enable row level security;
alter table eval_runs force row level security;
drop policy if exists tenant_isolation on eval_runs;
create policy tenant_isolation on eval_runs
    using      (tenant = current_setting('app.tenant', true))
    with check (tenant = current_setting('app.tenant', true));
grant select, insert, update, delete on eval_runs to chimera_app;
