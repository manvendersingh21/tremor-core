## Live UI-backend check (scripts/check_ui_backend.py)

Run 2026-11-14 00:28 PST against the running web server (`make web` under `scripts/web_keep.sh`).

```
PASS  health ok  (True)
PASS  health ram.free_mb  (3244)
PASS  health gpu_tunnel.up  (True)
PASS  health supabase.up  (True)
PASS  health crusoe.up  (True)
PASS  health modal.state  (stopped)
      steps: embed -> cache_shared -> memory -> decide -> call -> draft -> memory -> final -> answer -> done  (35.2 s)
PASS  chat ends with answer, done
PASS  chat has cache_shared and final
PASS  miss path has memory, decide, call
PASS  session calls +1  (+1)
PASS  session tokens_today up (or a cache hit)  (+36, cache hit=False)
PASS  by_conversation has this call
PASS  recent[0] is this call
PASS  stats session.calls  (1)
PASS  stats session.tokens_today  (36)
PASS  stats session.tokens  (36)
PASS  stats session.hit_rate  (0.0)
PASS  stats session.cache.today.exact  (0)
PASS  stats session.cache.today.cosine  (0)
PASS  stats session.cache.today.false_hits  (0)
PASS  stats session.cache.all_time.exact  (0)
PASS  stats session.cache.all_time.cosine  (0)
PASS  stats session.cache.all_time.false_hits  (0)
PASS  stats session.by_task
PASS  stats session.by_conversation
PASS  stats session.series.hourly
PASS  stats session.series.daily
PASS  stats session.dollars_saved  (1.2e-05)
PASS  stats session.tokens_kept_off_big  (36)
PASS  stats global.calls  (99)
PASS  stats global.tokens_today  (1803)
PASS  stats global.series.daily
PASS  stats global.by_task
PASS  stats recent
PASS  stats storage.supabase.up  (True)
PASS  stats storage.supabase.tables.prompts.bytes  (3022848)
PASS  stats storage.supabase.tables.teacher_pairs.tenant_rows  (0)
PASS  stats storage.supabase.tables.mem_nodes.tenant_rows  (0)
PASS  stats storage.supabase.tables.mem_edges.tenant_rows  (0)
PASS  stats storage.neo4j.nodes  (0)
PASS  stats storage.neo4j.edges  (0)
RESULT: all checks passed
```
