# Handoff: Kiro setup

Formats follow the current Kiro docs: [steering](https://kiro.dev/docs/steering/), [specs](https://kiro.dev/docs/specs/), [hooks](https://kiro.dev/docs/hooks/), [MCP configuration](https://kiro.dev/docs/mcp/configuration/), [custom agents](https://kiro.dev/docs/custom-agents/configuration-reference/), [powers](https://kiro.dev/docs/powers/create/).

## What was added

### Steering (`.kiro/steering/`)
| File | Mode | Content |
|---|---|---|
| `product.md`, `tech.md`, `structure.md` | `always` | Updated to the current ladder: Supabase cache (exact, cosine 0.97) -> optional 30B yes/no check (planned) -> Akash 30B -> Crusoe 763B. Mac 3B off, no Mac answer cache, N+1 memory (Supabase `teacher_pairs` + Aura graph), bank planned, `chimera code`, one URL, `.kiro` and Power in the tree. Measured numbers unchanged and still point to `bench/*.md`. |
| `testing.md` | `always` | Offline `make test`, Hypothesis in `tests/_props.py`, fakes only. |
| `security.md` | `always` | Secrets only in `.env`, no hosts or key paths in committed files, Supabase tables we did not create stay untouched. |
| `api.md` | `fileMatch` `site/**`, `apps/**/server*.py` | `docs/api.md` is the backend's contract (linked with `#[[file:docs/api.md]]`). |
| `ui.md` | `fileMatch` `site/**` | One URL, animation always on, keep the minimap. |

### Specs (`.kiro/specs/<feature>/{requirements,design,tasks}.md`)
`cache-and-verify`, `n1-memory-and-bank`, `terminal-agent`, `castle-3d-ui`, `savings-replay`, `lora-distill`. Requirements use EARS. Each `design.md` has a "Correctness properties" table linked to requirement numbers. `tasks.md` ticks only what exists in the tree. `chimera-speculative-os` was not edited; each design links to it for the formal property tests.

### Hooks (`.kiro/hooks/`, scripts in `.kiro/hooks/scripts/`, stdlib only, no network)
| File | Trigger | Does |
|---|---|---|
| `test-on-save-packages.json` | PostFileSave `packages/**`, `tests/**` | Runs the mapped `tests/test_<module>.py` (`test_module.py`). |
| `test-on-save-site.json` | PostFileSave `site/**` | `tests/test_world.py`, `tests/test_hud.py`, `site/build.py --check` (`test_site.py`). |
| `secret-scan.json` | Stop, and PreToolUse on shell | `secret_scan.py`: private keys, tokens, JWTs, DSNs with passwords, Supabase and Aura hosts, ssh targets, key paths, secret assignments. Prints file, line and rule, never the value. Exit 2 blocks a `git commit` tool call. |
| `api-contract-reminder.json` | PostFileSave `docs/api.md` | Agent prompt: update `site/` consumers or report the break. |
| `speculative-shield.json` | PostFileSave (unchanged except a 30 s timeout and a description) | Sends the saved diff to the ladder. It needs the GPU tunnel or network, so it is the one slow hook. It never blocks a save. |

Run by hand: `python3 .kiro/hooks/scripts/secret_scan.py --changed` (or `--staged`).

### Custom agents (`.kiro/agents/*.json`, prompts in `.kiro/agents/prompts/`)
| Agent | Can write | Notes |
|---|---|---|
| `backend-owner` | `packages/`, `apps/` (not site), `tests/`, `bench/`, `deploy/`, `docs/` | MCP: chimera + read-only Aura. Owns `docs/api.md`. |
| `frontend-owner` | `site/`, `apps/phantom-phone/hud-web/`, `README.md`, site tests | Cannot edit `docs/api.md` or `packages/`. |
| `bench-runner` | `bench/`, `docs/handoff/` | May run long jobs (tmux, `bench/*`). Product code is write-denied. |
| `reviewer` | nothing | Runs `make test` and hook scripts, reports. |

All load the steering files by `resources`, deny `.env` reads and writes, and deny destructive shell commands. MCP servers are defined inside each agent (`includeMcpJson: false`), so the agents work without the workspace `mcp.json`. Use: `kiro-cli --agent backend-owner`.

### MCP
- **`.kiro/settings/mcp.json` was NOT written.** The session's permission rule (`kiro-scope`) denies writes to `.kiro/settings/`. The same content is in `powers/chimera/workspace-mcp.json`. To activate: `cp powers/chimera/workspace-mcp.json .kiro/settings/mcp.json`.
- It registers `chimera` (`apps/kiro-trimmer/mcp_server.py`: `chimera_generate`, `chimera_stats`, `chimera_risk_score`) and `neo4j-aura-readonly` (`uvx neo4j-mcp-server`, `NEO4J_MCP_READ_ONLY=true`, `"disabled": true` until you enable it and a read-only Aura role exists). All credentials are `${VAR}` references to names in `.env.example`. No Supabase MCP.

### Kiro Power (`powers/chimera/`)
Powers are supported. Folder: `plugin.json`, `mcp.json`, `skills/{router-ladder,castle-ui,kiro-setup}`, `README.md`. The Power format has no steering or hook components, so their key rules are in skills. Install: Powers panel, Add Custom Power, Import from a folder.

## Verified
- All JSON files parse (`python3 -m json.tool`).
- Hooks run by hand: `test_module.py` (35 passed, 2 xfailed), `test_site.py` (10 passed), `secret_scan.py`.
- MCP server imports and lists `chimera_generate`, `chimera_stats`, `chimera_risk_score`. A live stdio session from Kiro was not run.
- `make test`: 184 passed, 1 deselected, 4 xfailed.

## Findings the secret scan raised (not mine, not changed)
Uncommitted edits by other chats contain a GPU host, a port and a key path: `bench/run_ladder.py:284`, `bench/start_verifier.sh:5`, `bench/run_terminal_agent.py:101`. Do not commit them as they are; use placeholders. The Stop and commit hooks will fail until they are fixed.

## Skipped and why
- `.kiro/settings/mcp.json`: write denied (above).
- The 30B yes/no check, the solved-problem bank, savings replay, LoRA and the 3D castle are not in the code tree. Their specs mark them planned. Scope of `savings-replay` and `lora-distill` is my reading of the brief; check it.
- n1 spec task "router hook" is unticked because I did not re-verify `router.py`.
- Kiro's file-save event field names for the file path are not documented. `_common.py` takes any path-like string in the event. Not tested inside Kiro.
- `speculative-shield` was kept as is; it calls the network on every save, against the "fast, no network" goal. Disable it with `"enabled": false` if it is too slow.
- No Hypothesis tests were written here; the property-test chat owns them.
