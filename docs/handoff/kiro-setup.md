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

## Extra MCP servers (added later)

All are in `powers/chimera/workspace-mcp.json` (copy to `.kiro/settings/mcp.json`; Kiro denied that write, see above). Versions are pinned. Commands were checked against each package's CLI or README. No server has write access to Supabase or Aura.

| Server | Entry | State | Credential | Given to |
|---|---|---|---|---|
| `playwright` | `npx -y @playwright/mcp@0.0.85 --isolated --allowed-origins http://127.0.0.1:8765` | on | none | `frontend-owner`, `reviewer` (also embedded in their agent files) |
| `context7` | `npx -y @upstash/context7-mcp@4.7.0` | on | none (an optional Context7 API key raises rate limits; not set) | all four agents |
| `huggingface` | `https://huggingface.co/mcp` | on | none: anonymous access to public search. A `HF_TOKEN` is needed only for private repos or Jobs; not configured | `bench-runner` |
| `github-readonly` | remote `https://api.githubcopilot.com/mcp/`, headers `X-MCP-Readonly: true`, `X-MCP-Toolsets: repos,pull_requests,actions` | **on** (in `workspace-mcp.json`) | `GITHUB_PERSONAL_ACCESS_TOKEN` in `.env`, by `${}` reference | nobody yet |
| `supabase-readonly` | remote `https://mcp.supabase.com/mcp?project_ref=${SUPABASE_PROJECT_REF}&read_only=true&features=database,docs` | **disabled** | `SUPABASE_ACCESS_TOKEN` (personal access token) and `SUPABASE_PROJECT_REF` | nobody yet |
| `neo4j-aura-readonly` | `uvx neo4j-mcp-server`, `NEO4J_MCP_READ_ONLY=true` | **disabled** | the `CHIMERA_GRAPH_*` variables, ideally a read-only Aura role | `backend-owner` (embedded, still needs the variables) |

Notes and limits:
- Playwright is limited to `http://127.0.0.1:8765` by `--allowed-origins`. This is a request filter, not a security boundary, and it may block external fonts. Start `make web` first.
- Supabase: the `@supabase/mcp-server-supabase@0.17.0` stdio build has no `--read-only` or `--project-ref` flag (its options are `--access-token`, `--api-url`, `--http`), so the hosted server with URL parameters is used. I did not confirm that Kiro expands `${SUPABASE_PROJECT_REF}` inside a URL; if it does not, write the project ref into the URL by hand when you enable it. `read_only=true` makes the Postgres role read-only. The access token itself can still manage the whole account, so use a token for an org that holds only this project.
- GitHub: read-only is enforced by the server header, not by the token. Use a token with read scopes only.
- Hugging Face anonymous mode was taken from the public endpoint description; I did not run a call.
- None of the new servers was started in a live Kiro session.

### GitHub MCP: token access (action for the user)
The token in `.env` is valid for user `manvendersingh21`, but a repository lookup for `manvendersingh21/tremor-core` returns 404, so the token cannot see the repo yet. Grant it access: GitHub, Settings, Developer settings, Personal access tokens. For a fine-grained token, set Repository access to include `tremor-core`, with read-only Contents, Pull requests and Actions. For a classic token, add the `repo` scope (that scope also allows writes; read-only then rests on the server header alone, so a fine-grained token is safer). Read-only mode uses the remote server's `X-MCP-Readonly` header, the remote equivalent of `GITHUB_READ_ONLY` / `--read-only` on the local server. Not tested against the repo until access is granted.
