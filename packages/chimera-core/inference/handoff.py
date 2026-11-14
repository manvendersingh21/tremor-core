"""Handoff: the small local model writes a complete brief so a big cloud model can take over.

This is the "small model gathers context, big model does the heavy work" path. It works with
ANY local/cloud pair (no shared tokenizer needed), and sends text only.
"""
from __future__ import annotations

from .local_draft import DraftBackend

BRIEF_SYSTEM = (
    "You are a task-briefing assistant. You do NOT solve the task. You write a brief for a "
    "stronger model that will solve it. Use these sections exactly:\n"
    "## Goal\n## Context (facts from the user request and files)\n## Constraints\n"
    "## Steps already considered\n## Open questions / risks\n## Expected output format\n"
    "Be specific. Copy code, paths, error messages verbatim. Do not invent facts."
)


def build_brief(local: DraftBackend, task: str, context: str = "", max_tokens: int = 600) -> str:
    """Ask the local model to write the brief. Falls back to a template if it fails."""
    prompt = f"TASK:\n{task}\n\nCONTEXT:\n{context or '(none)'}\n\nWrite the brief now."
    try:
        brief = local.complete(prompt, max_tokens=max_tokens, system=BRIEF_SYSTEM).text.strip()
    except Exception:  # local model down: still hand off something usable
        brief = ""
    return brief or template_brief(task, context)


def template_brief(task: str, context: str = "") -> str:
    return (
        f"## Goal\n{task}\n\n## Context\n{context or '(none)'}\n\n## Constraints\n"
        "Follow existing project conventions. Do not make unrequested changes.\n\n"
        "## Expected output format\nComplete, runnable code with a short explanation."
    )


def cloud_prompt(task: str, brief: str, local_draft: str = "") -> str:
    """Final prompt sent to the big model."""
    parts = [
        "You are the senior engineer. A smaller local model prepared this brief. "
        "Treat it as helpful context, verify it, and do the work completely.",
        f"# Brief\n{brief}",
        f"# Original request\n{task}",
    ]
    if local_draft:
        parts.append(f"# Local model's draft (may be wrong, improve or replace)\n{local_draft}")
    return "\n\n".join(parts)
