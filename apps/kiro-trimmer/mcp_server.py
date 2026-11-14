"""Stdio MCP server exposing the Chimera router. Run: python apps/kiro-trimmer/mcp_server.py"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from common import build_router, load_config, read_stats, telemetry_line
from chimera_core.firewall.risk_scorer import score_action

mcp = MCPServer("chimera")
_router = None


def _get_router():
    global _router
    _router = _router or build_router(load_config())
    return _router


@mcp.tool()
def chimera_generate(prompt: str, context: str = "") -> str:
    """Answer a prompt via the cache -> local -> GPU -> cloud ladder. Returns text plus a telemetry line."""
    out = _get_router().generate(prompt, context)
    return f"{out.text}\n\n{telemetry_line(out.telemetry)}"


@mcp.tool()
def chimera_stats() -> dict:
    """Totals from the telemetry JSONL: calls, per-tier counts, tokens and dollars saved."""
    return read_stats(load_config().telemetry_path)


@mcp.tool()
def chimera_risk_score(action: str) -> dict:
    """Score a GUI/CLI action 0-100. Scores >= 70 need approval."""
    return score_action(action).model_dump()


if __name__ == "__main__":
    mcp.run("stdio")
