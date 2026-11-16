"""Strip secrets and PII-looking strings before anything is stored. Pattern list, so it can miss odd formats."""
from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s'\"]+"), "[URL]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S), "[KEY]"),
    (re.compile(r"\b(?:sk|pk|rk|gsk|ghp|gho|xox[abp])[-_][A-Za-z0-9_\-]{16,}"), "[KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[KEY]"),  # JWT
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer [KEY]"),
    (re.compile(r"(?i)\b((?:api[_-]?key|secret|token|passw(?:or)?d|pwd)\s*[:=]\s*)['\"]?[^\s'\",;]{6,}['\"]?"), r"\1[SECRET]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+"), "[EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"(?<![\w.])(?:\+?\d{1,2}[ .-])?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), "[PHONE]"),
]
# Long random-looking token: 32+ chars of [A-Za-z0-9_-] holding both a digit and a letter. Code rarely has these.
_LONG = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def _long(m: re.Match) -> str:
    s = m.group(0)
    return "[KEY]" if re.search(r"\d", s) and re.search(r"[A-Za-z]", s) else s


_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")  # lookarounds, not \b: a card glued to "_" or a letter is still caught


def _card(m: re.Match) -> str:
    d = [int(c) for c in m.group(0) if c.isdigit()]
    tot = sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2) for i, x in enumerate(reversed(d)))
    return "[CARD]" if tot % 10 == 0 else m.group(0)  # Luhn check keeps ordinary big numbers in code intact


def scrub(text: str) -> str:
    for rx, sub in _PATTERNS:
        text = rx.sub(sub, text)
    text = _CARD.sub(_card, text)
    return _LONG.sub(_long, text)
