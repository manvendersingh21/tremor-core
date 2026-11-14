# Backend end to end: production path, real stack

Date 2026-11-14. 60 prompts: 30 from `bench/prompts.jsonl` (easy, paraphrase, repeat, small and heavy code) and 30 from `bench/datasets/suite.jsonl` (10 MMLU, 10 GSM8K, 5 HumanEval, 5 MBPP). One run per pass, no repeats.

Path under test: `config.build_router` with `use_pool`, the same router object `/api/chat` and the gateway use. Ladder: Supabase cache (exact hash, then pgvector cosine >= 0.97, guard on; the only answer cache; app role under RLS) -> GPU Qwen3-30B (Ollama on a V100 reached through a tunnel to your GPU box; gate: mean token probability >= 0.95 from Ollama logprobs) -> Crusoe DeepSeek-V4.1-Flash 763B (thinking off). No Mac 3B. Modal H200 off. Heavy prompts (complexity >= 0.6) skip the 30B. Unit-test rows pass their tests as `check`: a failing answer is served but not cached. Dollars are Crusoe list price ($0.29/M in, $1.20/M out). The self-hosted 30B counts as $0.

Passes: **BASE** 763B only, no cache. **COLD** full ladder, empty Supabase namespace. **WARM** the same prompts again (every machine on the tenant sees the same rows). **GATE85** ladder with no cache and gate 0.85.

## Per pass

| pass | 763B calls | GPU 30B calls | cache hits | 763B tokens (in+out) | 763B $ | graded correct | p50 ms | p90 ms | errors |
|---|---|---|---|---|---|---|---|---|---|
| BASE | 60 | 0 | 0 | 13741 | $0.01280 | 45/48 | 896 | 2981 | 0 |
| COLD | 43 | 26 | 5 | 12063 | $0.01113 | 45/48 | 2340 | 91577 | 0 |
| WARM | 2 | 3 | 57 | 349 | $0.00023 | 46/48 | 138 | 164 | 0 |
| GATE85 | 1 | 2 | 0 | 22 | $0.00002 | 2/2 | 91370 | 91370 | 0 |

## Against the 763B-only baseline

| | COLD | WARM | COLD + WARM vs 2 x BASE |
|---|---|---|---|
| 763B tokens kept off | 12.2% | 97.5% | 54.8% |
| 763B $ saved | $0.00166 (13.0%) | $0.01257 (98.2%) | $0.01423 (55.6%) |
| 763B calls avoided (of 60) | 17 | 58 | 75 of 120 |
| GPU and 763B calls avoided by the cache | 5 | 57 | 62 |

## Cache (Supabase only; no machine keeps a local cache)

- Hit rate: COLD 0.08 (3 exact, 2 cosine), WARM 0.95 (55 exact, 2 cosine). Local hit rate is 0 by design.
- WARM misses: mbpp-228, mbpp-164, mbpp-301. These COLD answers were not cached: a failed unit test, or a 30B answer under the 0.95 cache bar.
- Lookup time (exact row and top-5 neighbours in one round trip): p50 122 ms, p90 145 ms over 120 lookups. Statuses: ok 119, unavailable 1.
- False hits: 0 of 50 graded cache answers were wrong.

## Guard and threshold: 500 labeled Quora pairs (180 duplicates)

Kaggle/GLUE QQP pairs from `bench/datasets/cache_eval.jsonl`, real MiniLM embedder, no model calls. A hit is cosine >= threshold and, with the guard on, the guard accepts.

| threshold | guard | hits | right | wrong |
|---|---|---|---|---|
| 0.97 | off | 28 | 26 | 2 |
| 0.97 | on | 23 | 22 | 1 |
| 0.94 | off | 56 | 48 | 8 |
| 0.94 | on | 43 | 39 | 4 |

At 0.97 the guard cut wrong hits 2 -> 1 and right hits 26 -> 22. Default: 0.97, guard on.

## Gate 0.85 vs 0.95 on the 30B's own answer

Same 55 prompts in both rows (COLD rows served from the cache are left out; GATE85 had no cache).

| gate | answered by 30B | 30B tried, then 763B | 763B calls | 763B $ | graded correct | p50 ms |
|---|---|---|---|---|---|---|
| 0.85 | 1 | 1 | 1 | $0.00002 | 2/2 | 91370 |
| 0.95 | 12 | 14 | 43 | $0.01113 | 40/43 | 2490 |

## Accuracy by source (graded rows)

| source | BASE | COLD | WARM | GATE85 |
|---|---|---|---|---|
| gsm8k | 9/10 | 10/10 | 10/10 | n/a |
| humaneval | 5/5 | 5/5 | 5/5 | n/a |
| mbpp | 3/5 | 2/5 | 3/5 | n/a |
| mmlu | 10/10 | 10/10 | 10/10 | n/a |
| prompts:easy | 10/10 | 10/10 | 10/10 | 2/2 |
| prompts:paraphrase | 5/5 | 5/5 | 5/5 | n/a |
| prompts:repeat | 3/3 | 3/3 | 3/3 | n/a |

## Latency by path (COLD, WARM, GATE85)

| path | calls | p50 ms | p90 ms |
|---|---|---|---|
| cache:shared | 62 | 136 | 161 |
| cloud-deepseek | 46 | 1977 | 91655 |
| gpu-small | 14 | 49580 | 82155 |

## Rerun

```
# .env: CHIMERA_GPU_URL, CRUSOE_API_KEY, CHIMERA_DB_URL (app role); the tunnel to your GPU box is open
BENCH_NS=bench-$(date +%s) .venv/bin/python bench/run_backend.py run
.venv/bin/python bench/run_backend.py pairs
.venv/bin/python bench/run_backend.py report
```
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

