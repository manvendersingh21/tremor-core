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
- `action` (optional string): text of a tool-like action. The firewall scores it first. At 70 or more the call is refused: `403 approval_required` (nothing runs).
- Rate limit: 5 burst, then 20 per minute per client IP. Over it: `429 rate_limited` with `Retry-After`.
- More than 16 calls running: `503 busy`.

Response: `200 text/event-stream`. Each message is `event: <step>` and `data: <json>`. Order for a miss:
`embed`, `cache_local`, `cache_shared`, `decide`, `call`, `draft`, (`decide`, `call` again for each climb), `final`, `answer`, `done`.
A cache hit skips `decide`, `call`, `draft`. `cache_shared` is absent when no shared cache is configured.

```
event: embed
data: {"ms": 11.2, "dim": 384}

event: cache_local
data: {"hit": false, "kind": null, "score": 0.81, "guard": null, "threshold": 0.97, "ms": 1.4}

event: cache_shared
data: {"hit": false, "status": "ok", "score": 0.83, "guard": null, "threshold": 0.97, "ms": 118.0}

event: decide
data: {"tier": "mac-3b", "reason": "cheapest healthy tier that covers complexity 0.01"}

event: call
data: {"tier": "mac-3b", "model": "Qwen2.5-3B-Instruct-q4_k_m", "ok": true, "ms": 640.2, "tokens_in": 12, "tokens_out": 8, "cached_tokens": 0}

event: draft
data: {"tier": "mac-3b", "model": "Qwen2.5-3B-Instruct-q4_k_m", "confidence": 0.9731, "gate": 0.95}

event: decide
data: {"tier": "cloud-top", "reason": "climb: mac-3b confidence 0.810 < gate 0.95"}

event: final
data: {"tier": "mac-3b", "model": "Qwen2.5-3B-Instruct-q4_k_m", "tokens_in": 12, "tokens_out": 8, "cached_tokens": 0, "dollars": 0.0, "dollars_saved": 0.00001, "ms": 790.5, "tokens_kept_off_big": 20, "cache": null}

event: answer
data: {"text": "Paris."}

event: done
data: {}
```

Field notes:
- `cache_local.kind`: `"exact"`, `"semantic"` or `null`. `score` is the best cosine seen (also on a miss). `guard`: `"pass"`, `"rejected"`, `"off"` or `null` (no candidate reached the threshold).
- `cache_shared.status`: `ok`, `timeout`, `down` (SQLite answered instead), `skipped` (the local cache already hit).
- `draft` appears only for tiers that report token confidence (the Mac 3B). Below `gate` the call climbs.
- `decide.reason` is a sentence for display. `call.ok=false` carries `error` (an exception class name).
- `final.cache`: `null`, `"exact"`, `"local"` or `"shared"`. `final.tier` is the answering tier name. `dollars` is what the call cost; `dollars_saved` is what it did not cost against the biggest tier. `tokens_kept_off_big` is the tokens that never reached the biggest tier.
- Failure after the stream started: `event: error` with `{"code": "all_tiers_failed" | "timeout" | "internal", "message": "..."}`, then `done`.

## GET /api/health

Cached about 2 s (Modal state 60 s). A part that is not configured is absent.

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

```json
{
  "session": {"calls": 12, "cache_hits": {"exact": 3, "local": 1, "shared": 2}, "hit_rate": 0.5,
              "gpu_calls_avoided": 6, "big_calls_avoided": 11, "dollars_saved": 0.0031, "dollars_spent": 0.0004,
              "tokens_kept_off_big": 5400, "false_hits": 0, "by_tier": {"local": 4, "exact_cache": 3, "top": 1}},
  "global":  {"calls": 4120, "...": "same keys, from the telemetry log of every process on this machine"}
}
```

`session` counts this server process. `global` reads the telemetry JSONL (last 20 MB).

## Already served by the HUD server

`GET /events` (SSE of telemetry lines), `GET /api/bench`, `GET /api/evals`. Unchanged.

## Wiring (server owner)

```python
from chimera_core.service import handle_http
# in do_GET:  if handle_http(self, "GET"): return
# in do_POST: if handle_http(self, "POST"): return
```
