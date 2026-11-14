---
name: kiro-setup
description: Explain and use the tremor-core Kiro setup (steering, specs, hooks, custom agents, MCP). Use when asked how Kiro is configured in this repo or which agent or hook to use.
---

# Kiro setup in this repo

Full guide: `docs/handoff/kiro-setup.md`.

- Steering `.kiro/steering/`: product, tech, structure, testing, security (always); api (fileMatch `site/**`, `apps/**/server*.py`); ui (fileMatch `site/**`).
- Specs `.kiro/specs/`: cache-and-verify, n1-memory-and-bank, terminal-agent, castle-3d-ui, savings-replay, lora-distill. `chimera-speculative-os` holds the property tests and is edited only by the property-test owner.
- Hooks `.kiro/hooks/`: tests on save for `packages/**` and `site/**`, secret scan on stop and before `git commit`, an `api.md` reminder, and `speculative-shield`.
- Agents `.kiro/agents/`: backend-owner, frontend-owner, bench-runner, reviewer.
- MCP: the `chimera` router server and an optional read-only Neo4j Aura server (off until enabled).

Packaging note: a Power holds `plugin.json`, `mcp.json` and `skills/` only. Steering and hooks are not Power components, so this Power carries their key rules in skills and the repo keeps the real files.
