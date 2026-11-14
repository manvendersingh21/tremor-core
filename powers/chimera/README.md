# Chimera Kiro Power

Powers are supported (Kiro docs: [Powers](https://kiro.dev/docs/powers/), [Create powers](https://kiro.dev/docs/powers/create/)). A power is a folder with `plugin.json` (required), `mcp.json` and `skills/`.

| File | What |
|---|---|
| `plugin.json` | Name, version, activation keywords (`chimera`, `router`, `ladder`, `cache`, `tier`, `tokens saved`, `risk score`, `castle`). |
| `mcp.json` | The `chimera` MCP server (`apps/kiro-trimmer/mcp_server.py`): `chimera_generate`, `chimera_stats`, `chimera_risk_score`. Credentials are `${ENV}` references only. |
| `skills/router-ladder` | How to use the three tools and the ladder order. |
| `skills/castle-ui` | UI rules: one URL, animation always on, minimap, API contract. |
| `skills/kiro-setup` | Map of the repo's Kiro setup. |
| `workspace-mcp.json` | The workspace MCP config (chimera plus read-only Neo4j Aura, off). Copy it to `.kiro/settings/mcp.json`. |

## Install
Kiro, Powers panel, Add Custom Power, Import power from a folder, choose `powers/chimera`. Run it from the repo root: the server command `.venv/bin/python` is relative to it (`make setup` creates the venv).

Set the variables in `.env` (names in `.env.example`): `CRUSOE_API_KEY`, `CHIMERA_DB_URL`, `CHIMERA_GRAPH_URL`, `CHIMERA_GRAPH_USER`, `CHIMERA_GRAPH_PASSWORD`, `CHIMERA_GRAPH_DATABASE`. Kiro asks you to approve each variable it expands.

## Not in the Power
Steering and hooks are not Power components in the current docs. They stay in `.kiro/steering/` and `.kiro/hooks/`.
