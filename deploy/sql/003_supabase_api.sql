-- Supabase only. Lets clients that use the Supabase REST API (anon/authenticated JWTs) see just their
-- own tenant. Put a `tenant` claim in the JWT (app_metadata). Skip this file on plain Postgres.
revoke all on prompts, routing_signals, cache_events from anon;

drop policy if exists jwt_tenant on prompts;
create policy jwt_tenant on prompts for select to authenticated
    using (tenant = (auth.jwt() -> 'app_metadata' ->> 'tenant'));

drop policy if exists jwt_tenant on routing_signals;
create policy jwt_tenant on routing_signals for select to authenticated
    using (tenant = (auth.jwt() -> 'app_metadata' ->> 'tenant'));

drop policy if exists jwt_tenant on cache_events;
create policy jwt_tenant on cache_events for select to authenticated
    using (tenant = (auth.jwt() -> 'app_metadata' ->> 'tenant'));
-- Authenticated clients get read-only access; writes go through the gateway as chimera_app.
