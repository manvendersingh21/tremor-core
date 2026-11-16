# CHIMERA: Kiroween 2026 submission

Hackathon: [Kiroween 2026](https://kiroween.devpost.com/). Deadline: Friday, December 4, 2026, 2:00 PM Pacific.
Category: **Frankenstein**. Second choice: **Costume Contest**.
Repo: [github.com/manvendersingh21/tremor-core](https://github.com/manvendersingh21/tremor-core) (public, MIT, branch `dev`).
Static view: [manvendersingh21.github.io/tremor-core](https://manvendersingh21.github.io/tremor-core/). The live app runs at `127.0.0.1:8765` with `make web`.

Every number below names the file it comes from. Almost every test ran once. Losses sit next to wins.

## One-sentence pitch

Stop paying a frontier model for FizzBuzz. We prove it with tests.

## Why Frankenstein

CHIMERA is one body stitched from many parts. It joins a Supabase cache, a bank of solved problems, a self-hosted 30B model, an optional 120B on Modal (off by default) and a 763B cloud model into one ladder. Each part was a separate model or service. The router makes them act as one. The Halloween castle is the face it wears, which is why Costume Contest is the second choice.

---

## Devpost text description

### The problem

Companies send every coding call to one big paid model. That includes easy work like FizzBuzz.

A self-hosted 30B got 99 of 101 trivial coding tasks right (`bench/results_company_cost.md`: 2 of 101 failed). GPT-5.5 costs $4.02 per 1,000 coding calls. A busy H200 running the 30B costs $0.070 per 1,000 (`bench/results_company_cost.md`).

So most companies pay a top price for work a cheaper model can do. Nobody shows them the bill per call.

### What it does

CHIMERA answers each call at the cheapest place that gets it right. It climbs only as far as it must:

1. **Shared cache** (Supabase, Postgres + pgvector). Exact match first, then a near match at cosine 0.97. Cost: $0 in tokens.
2. **Solved-problem bank.** A stored solution is served only if it passes the new problem's tests right now.
3. **Self-hosted 30B** (Qwen3-30B). It keeps its answer if its mean token probability is 0.95 or more.
4. **Big model** (DeepSeek-V4.1-Flash, 763B, on Crusoe). It gets hard work and every failed check.

Every call logs the tier, the tokens, the time and the dollars. Answers that pass their tests are stored for next time. Everything stored is scrubbed of keys, emails and card numbers first.

You see it in four places:

- **The castle.** One web page at `127.0.0.1:8765`. Hold W to walk in. Doors open rooms with live numbers. The Observatory is a Halloween dashboard. Count Cuspid answers chat through the router.
- **`chimera code`.** A terminal coding agent. It checks the bank first, edits files, runs tests and climbs a tier when a test fails.
- **A gateway.** An OpenAI-style API with one key per tenant.
- **Kiro.** An MCP server, a CLI, a hook and a Kiro Power.

### How we built it

- Python 3.11+, Pydantic v2, FastAPI. Tests run offline with fakes (`tests/`, 263 collected).
- Supabase with pgvector for the cache, the bank and `teacher_pairs`. Row level security per tenant (`docs/vector-store.md`).
- Neo4j Aura for a graph of solved problems (`docs/memory.md`).
- Ollama on a V100 and vLLM on a Modal H200 for the 30B. Crusoe for the 763B.
- three.js (vendored, no CDN) and painted art for the castle (`site/`).
- Kiro for the whole build: 7 steering files, 7 specs, 6 hooks, 4 custom agents, MCP, a Power, property tests. Kiro Crew ran the work as a conductor with worker chats. Two `kiro-cli` juniors wrote 5 merged pull requests. Details are in the Kiro section below.

### Results, wins and losses

| Test | Number | Win or loss | File |
|---|---|---|---|
| Same question asked again | 58 to 59 of 60 from the cache in 3 repeats, median 112 ms, 0 wrong | win | `bench/results_company_cost.md` |
| Cache, second client | 49 of 60 hits in all 3 repeats, 0 wrong, 0 near-miss hits | win | `bench/results_company_cost.md` |
| Bank, same problems | 75 of 80 served in all 3 repeats, 0 wrong served | win | `bench/results_company_cost.md` |
| Bank, reworded problems | 24 of 80 served | mixed | `bench/results_company_cost.md` |
| New prompts, empty cache | 763B tokens cut 56.2% ± 4.6% | win on cost | `bench/results_company_cost.md` |
| Same, time | median 6.7 s vs 1.3 s for the 763B alone | loss | `bench/results_company_cost.md` |
| Monthly cost vs GPT-5.5 | 57% to 87% saved at 100k to 10M calls a day | win | `bench/results_company_cost.md` |
| Monthly cost vs the 763B | no saving at 100k a day (7.1x the cost); saves only with 30% repeats at 1M a day or more | loss | `bench/results_company_cost.md` |
| 30B on 301 coding tasks | 31 wrong (about 10%) vs 15 wrong for the 763B | loss | `bench/results_company_cost.md` |
| `chimera code`, 15 tasks | 15/15 both; $0.00102 vs $0.00415; median 92 s vs 5.5 s | mixed | `bench/results_terminal_agent.md` |
| `chimera code` repeat task | served from the bank: 0 tokens, $0 | win | `bench/results_backend_v2.md` |
| Spec decoding, same box | EAGLE-3 162.2 tok/s vs 89.8 alone: 1.80x | win | `bench/results_spec_modal.md` |
| Spec decoding, two boxes | 7.3 to 24.4 tok/s: 0.09x to 0.27x | loss | `bench/results_spec_modal.md` |
| Memory hints for the 30B | 68 to 70 of 80; 3 random examples also gave 70 | loss (no gain) | `bench/results_memory.md` |
| LoRA on 763B answers | pass fell from 92.2% to 88.3% | loss | `bench/results_distill.md` |
| Open chat replay | 30B answered 18 of 300; 763B tokens +9.8% | loss | `bench/results_replay.md` |

The plain lesson: the saving is real against a frontier price like GPT-5.5. Against a cheap big model like the 763B ($0.158 per 1,000 calls), there is little to save. The 30B is wrong about 1 time in 10, so tests must catch it.

### What is next

1. A public app URL with a demo tenant and no private hosts.
2. A test gate in front of every coding answer.
3. Send open chat straight to the big model with a cheap pre-check (`bench/results_replay.md`).
4. Use same-box EAGLE-3 for any big model we host (`bench/results_spec_modal.md`).
5. A 30B yes/no check on near cache hits (planned, not built).
6. Repeat the single-run tests 3 times on an idle GPU.

---

## How we used Kiro

Every claim below points to a file in this repo.

### Kiro IDE, CLI, Web and Crew: what we used and how they differ

| Surface | What it is | How we used it | Evidence |
|---|---|---|---|
| Kiro Crew | A dashboard that runs many agent chats: a conductor splits the goal into items, one worker chat per item | The conductor gave each worker one item with an acceptance file. Workers reported done with commits. A backend owner and a frontend owner split the code. | `docs/handoff/*.md` (each worker's closing note), `bench/results_backend_v2.md` ("Who did what") |
| Kiro CLI (`kiro-cli`) | Kiro in a terminal, good for boxes with no screen | Two juniors, k1 and k2, ran `kiro-cli` 3.3.0 on small Linux boxes with no GPU and no keys. They wrote code and offline tests and opened pull requests only. A senior chat reviewed and merged. | `bench/results_backend_v2.md`, PRs #1 to #5 |
| Kiro IDE | Kiro in an editor, where hooks fire on file save | The `.kiro/` files use the IDE formats (steering front matter, PostFileSave hooks, specs). The hook scripts were run by hand. They were not yet tested inside the IDE. | `docs/handoff/kiro-setup.md` ("Verified", "Skipped") |
| Kiro Web | Kiro in a browser | Not used. | none |

The difference in one line each: Crew runs many chats at once and tracks each item. The CLI runs one agent on any box over SSH. The IDE ties hooks to saves in an editor.

### Custom agents

Four agents live in `.kiro/agents/` with prompts in `.kiro/agents/prompts/`:

| Agent | May write | Note |
|---|---|---|
| `backend-owner` | `packages/`, `apps/` (not site), `tests/`, `bench/`, `deploy/`, `docs/` | Owns `docs/api.md`. MCP: chimera, read-only Aura, context7. |
| `frontend-owner` | `site/`, `apps/phantom-phone/hud-web/`, `README.md` | Cannot edit `docs/api.md` or `packages/`. |
| `bench-runner` | `bench/`, `docs/handoff/` | May run long jobs. Product code is write-denied. |
| `reviewer` | nothing | Runs tests and hook scripts, then reports. |

All four load the steering files, deny `.env` reads and writes, and deny destructive shell commands (`docs/handoff/kiro-setup.md`). The two-owner split matches how the team worked: one backend owner, one frontend owner, and the UI codes only against `docs/api.md`.

### Hooks

Six hooks in five files in `.kiro/hooks/` (`secret-scan.json` holds two), scripts in `.kiro/hooks/scripts/` (stdlib only):

| Hook | Trigger | Does |
|---|---|---|
| `test-on-save-packages.json` | save in `packages/` or `tests/` | runs the matching `tests/test_<module>.py` |
| `test-on-save-site.json` | save in `site/` | runs the site tests and `site/build.py --check` |
| `secret-scan.json` | agent stop, and before a `git commit` | blocks keys, tokens, JWTs, DSNs, private hosts and key paths; prints the rule, never the value |
| `api-contract-reminder.json` | save of `docs/api.md` | asks the agent to update the UI or report the break |
| `speculative-shield.json` | save | sends the diff to the ladder for a review |

The secret scan earned its place. It flagged a GPU host, a port and a key path in other chats' uncommitted edits, so those were kept out of git (`docs/handoff/kiro-setup.md`, "Findings the secret scan raised"). Every commit in this pack was scanned with `secret_scan.py --staged`.

### Spec-driven development vs vibe coding

We did both and can show where each won.

**Spec-driven.** Seven specs in `.kiro/specs/`, each with `requirements.md` (EARS: WHEN ... THE SYSTEM SHALL), `design.md` and `tasks.md`. The core spec, `chimera-speculative-os`, turns requirements into 19 correctness properties (P1 to P19 in `design.md`, section 5). Each property maps to a test. Example: requirement 1.5 says one tenant never reads another's cached answer. Property P3 states it. `tests/test_props_cache.py::test_exact_cache_namespaces_are_isolated` tries to break it. This is how 4 real bugs were found (next section).

**Vibe coding.** The castle UI grew by talking with the owner and looking at screenshots. A plain 3D castle (commit 6139068) and a 2.5D game (commit 011cb6b) were rejected. The painted art from commit 9495aa2 came back as a walk-in movie. For look and feel, fast tries beat a spec. The castle spec (`.kiro/specs/castle-3d-ui/`) was written to fix the rules after the look was chosen.

**What we learned.** Specs paid off where a wrong answer costs money or leaks data: the cache, tenants, scrub and the accept rule. Vibe coding paid off for the look. Specs drift if nobody ticks them: `savings-replay` and `lora-distill` are built and measured, but their `tasks.md` boxes are not ticked yet.

### Steering

Seven files in `.kiro/steering/`:

| File | Mode | Keeps the agent on |
|---|---|---|
| `product.md` | always | the goal and the real measured numbers, losses included |
| `tech.md` | always | the ladder, the 0.97 cosine rule, thinking off, every call through the router |
| `structure.md` | always | where code lives; the hyphenated package imported as `chimera_core` |
| `testing.md` | always | offline tests, fakes only, Hypothesis rules, a failing property kept as xfail |
| `security.md` | always | keys only in `.env`, no hosts or key paths in committed files |
| `api.md` | when editing `site/**` or a server | `docs/api.md` is the contract |
| `ui.md` | when editing `site/**` | one URL, animation always on, keep the minimap |

Steering fixed real mistakes. A 0.94 cosine cut-off served wrong answers (`bench/results_gpu.md`). `tech.md` now pins 0.97, so no agent lowers it again. `product.md` keeps a table of losses, so the agents write them next to wins.

### MCP

- **Our own MCP server**, `apps/kiro-trimmer/mcp_server.py`, puts the router inside Kiro. Tools: `chimera_generate`, `chimera_stats`, `chimera_risk_score`.
- **Workspace config.** `powers/chimera/workspace-mcp.json` registers it plus `playwright` (locked to `127.0.0.1:8765`), `context7`, `huggingface`, a read-only GitHub server, and read-only Supabase and Aura servers that start disabled. Every credential is a `${VAR}` name, never a value (`docs/handoff/kiro-setup.md`, "Extra MCP servers").
- Each custom agent embeds the servers it needs, so it works without the workspace file.
- No MCP server has write access to Supabase or Aura (`.kiro/steering/security.md`).

### Property-based testing

Kiro's spec flow, then Hypothesis:

1. EARS requirements in `.kiro/specs/chimera-speculative-os/requirements.md`.
2. 19 correctness properties in `design.md`, section 5.
3. Hypothesis tests in `tests/test_props_*.py` (cache, router, spec, safety, api), up to 200 examples each (`tests/_props.py`).

The first run had 39 property tests (commit 456b1b2). **35 held and 4 broke.** Each break was kept as a strict xfail with its shrunk counterexample (`docs/handoff/property-tests.md`):

| Bug | Shrunk counterexample | Fix |
|---|---|---|
| Exact-cache keys could collide | namespace `a`, prompt `b\x00c` vs namespace `a\x00b`, prompt `c` | refuse NUL in a namespace (PR #4) |
| The old ladder cached a top answer that failed its check | `check=lambda t: False`, prompt `a#` | run the check, cache only on a pass (PR #5) |
| The guard rejected a prompt against itself | `What is Python's GIL` | one apostrophe rule for both word sets (PR #3) |
| A card number next to `_` was not scrubbed | 15 zeros, then `_` | digit lookarounds instead of `\b` (PR #2) |

All 4 are fixed. Today there are 41 property tests and all pass (`tests/test_props_*.py`). One more fix came with this pack: two cache tests failed at random because the test made namespaces with a lone surrogate (`\ud800`), which SQLite cannot store. No real tenant name holds one, so the test was fixed, not the code (commit 3bae16a).

The accept rule of speculative decoding, `min(1, p_target / p_draft)`, is checked with a seeded chi-square test (`tests/test_props_spec.py`, `docs/handoff/property-tests.md`).

### Kiro Powers

`powers/chimera/` is a Kiro Power: `plugin.json`, `mcp.json` and three skills (`router-ladder`, `castle-ui`, `kiro-setup`). It packs the MCP server and the key rules so another project can install CHIMERA from the Powers panel ("Add Custom Power", then "Import from a folder"). The Power format has no steering or hooks, so the rules are written into the skills (`docs/handoff/kiro-setup.md`).

### Kiro Crew: conductor, workers and juniors

- **Two owners.** One backend chat and one frontend chat. The UI codes only against `docs/api.md` (`.kiro/agents/`, `.kiro/steering/api.md`).
- **One item per worker.** Each worker gets a title and an acceptance file, and reports done with commits. When a worker closes, it leaves a note in `docs/handoff/` (for example `ci-green.md`, `property-tests.md`, `kiro-setup.md`, `replay.md`).
- **Senior and juniors.** The backend chat drove two `kiro-cli` juniors on boxes with no GPU and no keys. They opened 5 pull requests, all merged after review: the bank in `chimera code` (#1) and the 4 property-bug fixes (#2 to #5). Every junior PR was right within 2 review rounds (`bench/results_backend_v2.md`).
- **Tests went from 239 passed and 4 xfailed to 257 passed and 0 xfailed** in that round (`bench/results_backend_v2.md`).
- **Costs stayed visible.** Workers recorded every Modal app and stopped it after its job. Speculative decoding on Modal cost $64.57 across three accounts (`bench/results_spec_modal.md`, "Cost and shutdown").

### Limits we state plainly

- The hooks were run by hand. They were not tested inside the Kiro IDE (`docs/handoff/kiro-setup.md`).
- `.kiro/settings/mcp.json` is not committed. The same content is in `powers/chimera/workspace-mcp.json`.
- Kiro Crew chat logs are not in the repo. The handoff notes and commits are the record.
