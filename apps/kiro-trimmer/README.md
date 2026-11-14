# kiro-trimmer

Chimera router as a CLI, an MCP server and a Kiro save hook. Config: `chimera.toml` at the repo root
(copy `chimera.example.toml`). Only `CRUSOE_API_KEY` is a secret; put it in `.env` or the environment.

## CLI

```sh
bin/chimera ask "What is the capital of France?"   # answer + one telemetry line
bin/chimera stats                                   # totals from ~/.chimera/telemetry.jsonl
bin/chimera doctor                                  # ✅/❌ per tier
```

Same thing: `python apps/kiro-trimmer/cli.py ask "..."`. (`python -m` cannot reach a hyphenated directory.)
Telemetry goes to `~/.chimera/telemetry.jsonl`; set `CHIMERA_TELEMETRY` to move it. The GPU tier needs
`ssh -N -L LOCAL_PORT:127.0.0.1:11434 <gpu-host>`.

## MCP server

Tools: `chimera_generate(prompt, context?)`, `chimera_stats()`, `chimera_risk_score(action)`.
Needs the `mcp` package in `.venv` (2.x API: `mcp.server.mcpserver`).

Sample workspace `.kiro/settings/mcp.json` (adjust the path):

```json
{
  "mcpServers": {
    "chimera": {
      "command": "/Users/manubaba/Documents/tremor-core/.venv/bin/python",
      "args": ["/Users/manubaba/Documents/tremor-core/apps/kiro-trimmer/mcp_server.py"],
      "env": { "CHIMERA_CONFIG": "/Users/manubaba/Documents/tremor-core/chimera.toml" }
    }
  }
}
```

## Save hook

`.kiro/hooks/speculative-shield.json` runs `python3 apps/kiro-trimmer/hook_interceptor.py --mode=post-save
--prefer-local-kv` on save. The script reads a diff on stdin, prints a one-paragraph review, and always exits 0.
It re-launches itself under `.venv` if started with another Python.
