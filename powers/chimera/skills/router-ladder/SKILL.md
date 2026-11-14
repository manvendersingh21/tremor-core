---
name: router-ladder
description: Send an LLM call through the Chimera ladder, read routing stats, or score a risky action. Use when asked to answer cheaply, check tokens or dollars saved, or approve a pay, delete or merge action.
---

# Chimera ladder

The `chimera` MCP server has three tools.

| Tool | Use |
|---|---|
| `chimera_generate(prompt, context="")` | Answer through the ladder. Returns the text and a telemetry line (tier, latency, tokens and dollars saved). |
| `chimera_stats()` | Totals from the telemetry JSONL: calls, per-tier counts, tokens saved, dollars saved. |
| `chimera_risk_score(action)` | Scores an action 0 to 100. 70 or more needs approval. |

## Ladder order
Supabase cache (exact hash, then cosine 0.97) -> self-hosted 30B (Ollama `qwen3:30b-instruct`) -> optional Modal 120B (off) -> Crusoe 763B. A failed check climbs one tier. There is no answer cache on the Mac and the Mac 3B is off.

## Steps
1. For a self-contained question, call `chimera_generate`. Give code or files in `context`.
2. Show the telemetry line to the user. Do not claim savings the line does not show.
3. Before a pay, delete, merge or send, call `chimera_risk_score`. At 70 or more, stop and ask the user.
4. Never print keys, DSNs or hosts. They come from the environment.

Measured results and their sources: `bench/results_ladder.md`, `bench/results_gpu.md`, `docs/vector-store.md`. Several runs lost on speed or tokens; read the source before quoting a number.
