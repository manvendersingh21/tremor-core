# Deploying the CHIMERA gateway

The gateway is an OpenAI-compatible HTTP service in front of the CHIMERA router. Your apps keep their OpenAI SDK and change only `base_url` and the API key.

## Architecture

```
your apps ──HTTPS──> reverse proxy ──> gateway (:8088) ──> router.generate()
                                          │                   │
                                          │                   ├─ 0 cache (exact, optional semantic), one namespace per tenant
                                          │                   ├─ 1 local llama.cpp (Qwen2.5-3B)   optional
                                          │                   ├─ 2 GPU Ollama (qwen3:30b)         optional
                                          │                   └─ 3 Crusoe serverless (top model)
                                          ├─ SQLite: API key hashes + audit log
                                          └─ telemetry.jsonl ──> HUD (read-only)
```

Every request goes through `LadderRouter.generate()`. The cheapest tier that can answer does so. Bad answers climb one tier.

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | Chat. `stream=true` returns SSE chunks. |
| `GET /v1/models` | `chimera-auto` and one id per tier. |
| `GET /healthz` | Process is up. |
| `GET /readyz` | 200 if at least one tier answers its probe, else 503. Same probes as `chimera doctor`. |
| `GET /metrics` | Prometheus text, by tenant and tier. |
| `POST /v1/actions/score` | Risk score 0-100 for an action text. Off unless `gateway.actions = true`. |

Response headers on every chat call: `x-chimera-tier`, `x-chimera-tokens-saved`, `x-chimera-latency-ms`, `x-request-id`. The body has a `chimera` field with the full telemetry.

Limits to know:
- `model` is accepted as `chimera-auto` or a tier id, but the router always picks the tier. A tier id does not pin it.
- `temperature`, `max_tokens` and other sampling fields are accepted and ignored.
- Streaming replays the finished answer in chunks. First-byte latency equals full-answer latency.
- `usage` token counts are estimates (characters / 4), the same estimate the router uses.

## Quick start (Docker Compose)

```sh
cd deploy
cp .env.example .env             # set CRUSOE_API_KEY
docker compose up -d --build
docker compose --profile local up -d    # optional: also run llama.cpp (put model.gguf in MODELS_DIR)
```

The gateway is published on `127.0.0.1:8088` and the HUD on `127.0.0.1:8765`. Inside the container the gateway binds `0.0.0.0`; the port is only exposed on the host loopback. Reach it from other machines through a TLS proxy (below).

Without Docker, see `chimera-gateway.service` (systemd) and run `python -m apps.gateway --config /etc/chimera/chimera.toml`. It binds `127.0.0.1:8088` by default.

## Set the tiers

Edit `deploy/chimera.docker.toml` (mounted read-only at `/etc/chimera/chimera.toml`). Local runs use `chimera.toml` in the repo root (copy `chimera.example.toml`).

- **Tier 1, local:** `[local] url`. Compose service name is `llama`.
- **Tier 2, GPU:** `[gpu] enabled = true`, `url`, `model`. When `false`, the Crusoe mid model takes this tier.
- **Tier 3, Crusoe:** `[crusoe] mid_model, top_model`. The key is `CRUSOE_API_KEY` in `deploy/.env` or the environment. Never put it in the toml.
- **Thresholds:** `[thresholds] confidence` (local answers at or above this mean token probability), `heavy`, `semantic` (0.97).
- **Gateway:** `[gateway] rate_per_min, burst, max_body_bytes, timeout_s, log_prompts, actions, db`.

If a cloud call returns 429/5xx or a network error, the gateway retries once after `retry_backoff_s`, then answers from one tier down (top to GPU/mid, mid to local). The reported tier is the one that answered, and the `chimera.fallback_from` field names the tier that failed. A degraded answer is cached like any other answer.

Check what is reachable: `bin/chimera doctor` on the host, or `GET /readyz`.

## Create API keys

Keys belong to a tenant. Run the commands where the gateway database is. In Docker, replace `bin/chimera` with `docker compose exec gateway python apps/kiro-trimmer/cli.py`.

```sh
bin/chimera keys create --tenant acme      # prints the key once; only its SHA-256 is stored
bin/chimera keys list                      # id, tenant, first 8 chars, created, active/revoked
bin/chimera keys revoke --tenant acme      # revokes every active key of the tenant
bin/chimera keys revoke --id 3             # revokes one key
```

Tenant names match `[a-z0-9][a-z0-9_.-]{0,62}`. Revoking takes effect on the next request. Rotate by creating the new key first, switching the app, then revoking the old id.

## Point an OpenAI SDK at it

```python
from openai import OpenAI

client = OpenAI(base_url="https://chimera.example.com/v1", api_key="chm_...")
raw = client.chat.completions.with_raw_response.create(
    model="chimera-auto",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
)
print(raw.parse().choices[0].message.content)
print(raw.headers["x-chimera-tier"], raw.headers["x-chimera-tokens-saved"])
```

Errors use the OpenAI shape: `{"error": {"message", "type", "code"}}`. Codes: 401 `invalid_api_key`, 429 `rate_limit_exceeded` (with `Retry-After`), 413 `request_too_large`, 400 `invalid_request`, 404 `model_not_found`, 502 `upstream_error`, 504 `timeout`.

## TLS through a reverse proxy

The gateway speaks plain HTTP. Terminate TLS in front of it. Caddy example:

```
chimera.example.com {
    request_body { max_size 1MB }
    @metrics path /metrics
    respond @metrics 403          # scrape /metrics from inside your network instead
    reverse_proxy 127.0.0.1:8088 {
        flush_interval -1         # keep SSE chunks flowing
    }
}
```

nginx: `proxy_pass http://127.0.0.1:8088; proxy_buffering off; proxy_read_timeout 200s;` and `client_max_body_size 1m;`. Keep `proxy_read_timeout` above `2 x timeout_s`.

## Data handling

What is stored, and where:

| Data | Where | Contents |
|---|---|---|
| API keys | `gateway.db`, table `keys` | tenant, SHA-256 of the key, first 8 chars, timestamps. Never the key. |
| Audit log | `gateway.db`, table `audit` | time, request id, tenant, tier, tokens saved, cloud tokens, dollars saved, latency. No prompt or answer text. |
| Cache | `cache.db` | Prompts and answers in plain text, keyed by tenant namespace. Semantic cache also stores prompt embeddings. |
| Telemetry | `telemetry.jsonl` | Tier, tokens, latency, dollars per call. No tenant, no text. Read by the HUD. |
| Request logs | stdout, JSON lines | request id, tenant, path, status, tier, ms. Prompt text only with `--log-prompts` or `gateway.log_prompts = true`. |
| Metrics | memory | Counters by tenant and tier. Reset on restart. |

Isolation: each tenant has its own cache namespace in both caches, so one tenant never gets another's cached answer. Tenants share the same model backends.

Cache TTL: there is none. An entry stays until purged. Exact entries also sit in a 4096-entry in-memory LRU.

Purge a tenant's cached answers:

```sh
bin/chimera cache purge --tenant acme     # in Docker: see the exec form above
docker compose restart gateway            # clears the in-memory copy
```

Purging does not delete audit rows. To remove those, delete from `audit` where `tenant = 'acme'` with the `sqlite3` CLI. Prompts sent to tiers 2 and 3 are handled by those providers under their own terms; the cache holds answers that came back from them.

## Security checklist

- [ ] TLS in front of the gateway; no plain-HTTP exposure beyond localhost.
- [ ] Gateway published on loopback or a private network only (the compose file already uses `127.0.0.1`).
- [ ] `deploy/.env` is mode 600 and not committed. `CRUSOE_API_KEY` is only in the environment.
- [ ] One key per app, one tenant per customer. Rotate by create-then-revoke. Treat a leaked key as revoked now.
- [ ] `/metrics` blocked at the proxy, or `CHIMERA_METRICS_TOKEN` set.
- [ ] `--log-prompts` stays off unless you have a reason and a retention rule for the logs.
- [ ] Rate limit and body cap fit your traffic (`rate_per_min`, `burst`, `max_body_bytes`). The limit is per key and kept in memory, so it is per gateway instance.
- [ ] Run one gateway instance per database file. SQLite is fine for one host; use a shared database before scaling out.
- [ ] Container runs as UID 10001 with a read-only root and no capabilities (compose sets this). The systemd unit sets `NoNewPrivileges` and `ProtectSystem=strict`.
- [ ] Back up `gateway.db`. Without it all keys are lost.
- [ ] `POST /v1/actions/score` is a rule list and can miss unusual phrasing. Do not use it as the only gate for payments or deletes.
- [ ] Rebuild the image regularly to pick up base-image fixes.
