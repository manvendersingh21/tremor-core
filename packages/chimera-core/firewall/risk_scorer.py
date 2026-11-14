"""Quarantine firewall: 0-100 blast-radius score for GUI taps and CLI commands."""
from __future__ import annotations

import re
import secrets

from pydantic import BaseModel

APPROVAL_THRESHOLD = 70

_RULES: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"\b(pay|send money|send wire|wire transfer|purchase|buy now|confirm order)\b", re.I), 90, "financial"),
    (re.compile(r"\b(merge( pr| pull request)?|force[- ]push|deploy|publish)\b", re.I), 80, "irreversible code change"),
    (re.compile(r"\b(delete|remove account|erase|factory reset|drop (table|database))\b", re.I), 85, "destructive"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f?\b|\bmkfs\b|\bdd\s+if=", re.I), 95, "destructive shell"),
    (re.compile(r"\bgit\s+push\b|\bgit\s+reset\s+--hard\b", re.I), 75, "git history"),
    (re.compile(r"\b(unlock|open door|grant access|share|post|send)\b", re.I), 55, "external effect"),
    (re.compile(r"\b(type|enter)\b.*\b(password|otp|2fa|code)\b", re.I), 60, "credential"),
]


class RiskVerdict(BaseModel):
    score: int
    reasons: list[str]
    needs_approval: bool
    approval_token: str | None = None


def score_action(action: str) -> RiskVerdict:
    """Score a proposed action description (button label, tap target, or shell command)."""
    score, reasons = 5, []
    for pattern, points, reason in _RULES:
        if pattern.search(action):
            score = max(score, points)
            reasons.append(reason)
    needs = score >= APPROVAL_THRESHOLD
    return RiskVerdict(
        score=score, reasons=reasons, needs_approval=needs,
        approval_token=secrets.token_hex(3) if needs else None,
    )


def verify_approval(verdict: RiskVerdict, reply: str) -> bool:
    """True when the voice/SMS reply contains the one-time token issued for this verdict."""
    return bool(verdict.approval_token) and verdict.approval_token in reply.lower()
