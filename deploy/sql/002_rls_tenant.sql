-- Row Level Security per tenant. The client sets `app.tenant` for each transaction
-- (PgStore does: select set_config('app.tenant', <tenant>, true)).
-- RLS does not apply to the table owner or to roles with BYPASSRLS (Supabase `postgres` and
-- `service_role`). Connect as the restricted role below, or the policies protect nothing.
alter table prompts         enable row level security;
alter table routing_signals enable row level security;
alter table cache_events    enable row level security;
alter table prompts         force row level security;
alter table routing_signals force row level security;
alter table cache_events    force row level security;

drop policy if exists tenant_isolation on prompts;
create policy tenant_isolation on prompts
    using      (tenant = current_setting('app.tenant', true))
    with check (tenant = current_setting('app.tenant', true));

drop policy if exists tenant_isolation on routing_signals;
create policy tenant_isolation on routing_signals
    using      (tenant = current_setting('app.tenant', true))
    with check (tenant = current_setting('app.tenant', true));

drop policy if exists tenant_isolation on cache_events;
create policy tenant_isolation on cache_events
    using      (tenant = current_setting('app.tenant', true))
    with check (tenant = current_setting('app.tenant', true));

-- Restricted application role. Set its password in the dashboard or with ALTER ROLE, never in a file.
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'chimera_app') then
        create role chimera_app login;
    end if;
end $$;
grant usage on schema public to chimera_app;
grant select, insert, update, delete on prompts, routing_signals, cache_events to chimera_app;
grant usage, select on all sequences in schema public to chimera_app;
