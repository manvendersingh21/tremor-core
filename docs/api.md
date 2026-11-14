# Web API (single server, `127.0.0.1:8765`)

Owner: backend (`packages/chimera-core/service.py`). The UI only calls these. Shapes are fixed; new fields may be added, none removed.
Errors before a stream starts are JSON: `{"error": {"code": "...", "message": "..."}}`, with `Retry-After` on 429/503.
No response ever contains a key, a DSN or a host name.

## POST /api/chat

Request, `Content-Type: application/json`, body at most 16 KB:

```json
{"prompt": "What is the capital of France?"}
```

- `prompt`: 1 to 2000 characters. Longer: `413 prompt_too_long`.
- `conversation_id` (optional): 1-64 characters of letters, digits, `.`, `_`, `:`, `-`. Groups calls in `/api/stats` `by_conversation`.
- `task` (optional, same characters): task kind, e.g. `chat`, `code`, `lookup`. Default `chat`. Groups calls in `by_task`.
- `action` (optional string): text of a tool-like action. The firewall scores it first. At 70 or more the call is refused: `403 approval_required` (nothing runs).
- Rate limit: 5 burst, then 20 per minute per client IP. Over it: `429 rate_limited` with `Retry-After`.
- More than 32 calls running: `503 busy`.

Response: `200 text/event-stream`. Each message is `event: <step>` and `data: <json>`. Order for a miss:
`embed`, `cache_shared`, `memory` (retrieve), then per tier tried `decide`, `call`, `draft`, then `memory` (store), `final`, `answer`, `done`.
A cache hit is `embed`, `cache_shared`, `final`, `answer`, `done`. The only cache is Supabase: there is no `cache_local` step.
`embed` and `cache_shared` are absent when no cache is configured (no `CHIMERA_DB_URL`).

Ladder: Supabase cache, then GPU 30B (self-hosted, `gpu-small`), then optionally Modal H200 120B (`gpu-large`), then Crusoe DeepSeek-V4.1-Flash 763B (`cloud-deepseek`).

```
event: embed
data: {"ms": 11.2, "dim": 384}

event: cache_shared
data: {"hit": false, "status": "ok", "threshold": 0.97, "kind": null, "score": 0.83, "guard": null, "ms": 118.0}

event: memory
data: {"op": "retrieve", "chars": 0, "ms": 0.01}

event: decide
data: {"tier": "gpu-small", "reason": "cheapest healthy tier that covers complexity 0.01"}

event: call
data: {"tier": "gpu-small", "model": "qwen3:30b-instruct", "ok": true, "ms": 640.2, "tokens_in": 15, "tokens_out": 2, "cached_tokens": 3}

event: draft
data: {"tier": "gpu-small", "model": "qwen3:30b-instruct", "confidence": 0.9999, "gate": 0.95}

event: memory
data: {"op": "store", "stored": false, "tier": "gpu-small", "tests_passed": null}

event: final
data: {"tier": "gpu-small", "model": "qwen3:30b-instruct", "tokens_in": 15, "tokens_out": 2, "cached_tokens": 3, "dollars": 0.0, "dollars_saved": 0.00001, "ms": 790.5, "tokens_kept_off_big": 17, "cache": null}

event: answer
data: {"text": "Paris"}

event: done
data: {}
```

Field notes:
- `cache_shared.kind`: `"exact"` (hash match), `"semantic"` (cosine) or `null`. `score` is the best cosine seen, also on a miss (1.0 on an exact hit). `guard`: `"pass"`, `"rejected"`, `"off"` or `null` (no candidate reached the threshold).
- `cache_shared.status`: `ok`, or `unavailable` (Supabase down or over the 300 ms budget: the call skips the cache; nothing is cached locally).
- `memory`: `op: "retrieve"` with `chars` of solved examples given to the 30B as few-shot context (0 = none). `op: "store"` with `stored: true` when this answer was saved as teacher data (only checked answers from a big tier: `cloud-deepseek` or `gpu-large`), and `tests_passed` (`true`/`false`/`null` when no tests ran).
- `draft`: the answering tier's confidence (mean token probability from Ollama logprobs; 1.0/0.0 from the 30B's self-check when no logprobs). Below `gate` the call climbs.
- `decide.reason` is a sentence for display. `call.ok=false` carries `error` (an exception class name).
- `final.cache`: `null` or `"shared"`. `final.tier` is the answering tier name. `dollars` is what the call cost; `dollars_saved` is what it did not cost against the biggest tier. `tokens_kept_off_big` is the tokens that never reached the biggest tier.
- Failure after the stream started: `event: error` with `{"code": "all_tiers_failed" | "timeout" | "internal", "message": "..."}`, then `done`.

## GET /api/health

Cached about 2 s (Modal state 60 s). A part that is not configured is absent: `llama` appears only when the Mac 3B experiment tier is enabled (it is off in the product ladder). `gpu_tunnel` is the GPU 30B. `supabase.lookup_ms` is one real lookup round trip.

```json
{
  "ok": true, "ts": 1794700000,
  "llama": {"up": true, "ms": 4.1, "tokens_per_s": 62.5},
  "ram": {"free_mb": 3100, "total_mb": 16384},
  "gpu_tunnel": {"up": true, "ms": 9.0},
  "supabase": {"up": true, "lookup_ms": 118.4},
  "crusoe": {"up": true, "ms": 240.0},
  "gmi": {"up": false, "ms": 3001.2},
  "modal": {"state": "stopped"}
}
```

`modal.state`: `stopped`, `deployed`, `ephemeral`, `not_deployed`, `unknown` (from read-only `modal app list`). Probing never wakes Modal.

## GET /api/stats

Cached 2 s, but a finished `/api/chat` call shows at once. `storage` is cached 60 s.

```json
{
  "session": {
    "calls": 12, "calls_today": 12, "tokens": 640, "tokens_today": 640,
    "cache_hits": {"exact": 0, "local": 0, "shared": 6}, "hit_rate": 0.5,
    "cache": {"today":    {"exact": 4, "cosine": 2, "false_hits": 0},
              "all_time": {"exact": 4, "cosine": 2, "false_hits": 0}},
    "gpu_calls_avoided": 6, "big_calls_avoided": 11, "dollars_saved": 0.0031, "dollars_spent": 0.0004,
    "tokens_kept_off_big": 5400, "false_hits": 0, "by_tier": {"gpu": 5, "exact_cache": 4, "semantic_cache": 2, "top": 1},
    "by_task": {"chat": {"calls": 9, "tokens": 400, "cache_hits": 5, "tokens_saved": 3000, "dollars_saved": 0.002, "last_ts": 1794700000.1},
                "code": {"calls": 3, "tokens": 240, "cache_hits": 1, "tokens_saved": 2400, "dollars_saved": 0.0011, "last_ts": 1794699000.0}},
    "by_conversation": {"conv-1": {"calls": 4, "tokens": 120, "cache_hits": 2, "tokens_saved": 900, "dollars_saved": 0.0005, "last_ts": 1794700000.1}},
    "series": {"hourly": [{"t": "2026-11-14T00:00", "calls": 12, "tokens": 640, "tokens_saved": 5400, "dollars_saved": 0.0031, "dollars_spent": 0.0004}],
               "daily":  [{"t": "2026-11-14", "calls": 12, "tokens": 640, "tokens_saved": 5400, "dollars_saved": 0.0031, "dollars_spent": 0.0004}]}
  },
  "global": {"calls": 4120, "...": "same keys, from the telemetry log of every process on this machine"},
  "recent": [
    {"ts": 1794700000.1, "prompt": "What is the capital of France?", "task": "chat", "conversation_id": "conv-1",
     "tier": "exact_cache", "model": "cache", "cache": "shared", "score": 1.0, "tokens_in": 0, "tokens_out": 0,
     "ms": 131.2, "dollars": 0.0, "dollars_saved": 0.00001,
     "steps": [{"step": "embed", "ms": 9.1, "dim": 384}, {"step": "cache_shared", "hit": true, "...": "as in /api/chat"},
               {"step": "final", "...": "as in /api/chat"}]}
  ],
  "storage": {
    "ts": 1794700000,
    "supabase": {"up": true, "tenant": "default", "bytes_total": 4718592,
                 "tables": {"prompts": {"tenant_rows": 34, "bytes": 3006464, "rows_estimate": 40},
                            "cache_events": {"...": "same keys"}, "routing_signals": {}, "eval_runs": {},
                            "teacher_pairs": {}, "mem_nodes": {}, "mem_edges": {}}},
    "neo4j": {"up": true, "nodes": 120, "edges": 340}
  }
}
```

- `tokens`: input + output tokens the model tiers used (a cache hit uses 0). `tokens_today`/`calls_today`: since local midnight.
- `cache.*.exact`: Supabase hash matches. `cosine`: pgvector matches at >= 0.97 that the guard passed. `false_hits`: cache answers later reported wrong.
- `by_task` keys are the `task` sent to `/api/chat` (`other` for callers that sent none). `by_conversation` holds the 50 newest conversations; calls without `conversation_id` are not in it.
- `series.hourly`: last 48 h; `series.daily`: last 30 days; local time, oldest first, empty buckets left out. Rows logged before this field existed have no time and are not in the series.
- `recent`: the last 20 calls on this machine, newest first. `prompt` is the first 80 characters with emails, keys, tokens and card numbers removed. `steps` are the `/api/chat` events of that call in order.
- `storage`: counts only, never text or host. `tenant_rows` is what this tenant sees under Row Level Security; `rows_estimate` is the whole table (Postgres planner estimate). A part that cannot be reached is `{"up": false, "error": "<exception class>"}` and its counts are absent.
- `session` counts this server process. `cache_hits` is kept for old readers (`shared` = Supabase hits). `global` reads the telemetry JSONL (last 20 MB).

## Already served by the HUD server

`GET /events` (SSE of telemetry lines), `GET /api/bench`, `GET /api/evals`. Unchanged.

## Wiring (server owner)

```python
from chimera_core.service import handle_http
# in do_GET:  if handle_http(self, "GET"): return
# in do_POST: if handle_http(self, "POST"): return
```

## Requested by the frontend (served)

All five requests are served inside `GET /api/stats` (no separate `/api/db` or `/api/traces`):
`tokens_today` -> `session|global.tokens_today`; `by_task` -> `session|global.by_task` (and `by_conversation`);
`series` -> `session|global.series.daily` (`t` is the day) and `.hourly`; `/api/db` -> `storage`; `/api/traces` -> `recent`.
