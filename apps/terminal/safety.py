"""Secrets, ignored files and the risk gate. Nothing here talks to a model."""
from __future__ import annotations

import fnmatch
import os
import pathlib
import re
import subprocess
import sys
from typing import Callable

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (registers packages/chimera-core as `chimera_core`)

from chimera_core.firewall.risk_scorer import APPROVAL_THRESHOLD, RiskVerdict, score_action, verify_approval  # noqa: E402

SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|DSN|DB_URL)", re.I)
_BLOCKED_FILE = re.compile(
    r"^(\.env(\..*)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|\.netrc|\.pypirc|\.npmrc|credentials(\..*)?|"
    r"secrets?\.(json|ya?ml|toml|txt)|.*\.(pem|key|p12|pfx|keystore))$", re.I)
_BLOCKED_DIRS = {".ssh", ".aws", ".gnupg", ".kube", ".docker"}
_ALLOWED_ENV = {".env.example", ".env.sample", ".env.template"}

_SECRET_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[redacted]"),
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghs|glpat|xox[abp])[-_][A-Za-z0-9_\-]{16,}"), "[redacted]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{20,}"), r"\1[redacted]"),
    (re.compile(r"(?i)(postgres(?:ql)?|mysql|mongodb|redis)://[^\s'\"/:@]+:[^\s'\"@]+@"), r"\1://[redacted]@"),
    (re.compile(r"(?im)^(\s*(?:export\s+)?[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|DSN)[A-Z0-9_]*\s*[=:]\s*)(['\"]?)[^\s'\"#]{6,}\2"),
     r"\1[redacted]"),
]


def redact(text: str) -> str:
    """Mask keys, tokens, DSNs and any secret value found in the environment. Applied to every model prompt."""
    for rx, rep in _SECRET_RES:
        text = rx.sub(rep, text)
    for k, v in os.environ.items():
        if SECRET_NAME.search(k) and len(v) >= 8:
            text = text.replace(v, "[redacted]")
    return text


def clean_env() -> dict[str, str]:
    """Environment for child processes: no variable that looks like a credential."""
    env = {k: v for k, v in os.environ.items() if not SECRET_NAME.search(k)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # a stale .pyc (same mtime second, same size) would hide an edit
    return env


def blocked_reason(path: pathlib.Path) -> str | None:
    """Why a file must never be read or written by the agent, else None."""
    p = path.expanduser()
    name = p.name
    if name in _ALLOWED_ENV:
        return None
    if _BLOCKED_FILE.match(name):
        return "looks like a credential file"
    if any(part in _BLOCKED_DIRS for part in p.parts):
        return "inside a credentials directory"
    return None


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def is_git(root: pathlib.Path) -> bool:
    r = _git(root, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


def ignored(root: pathlib.Path, rel: str) -> bool:
    """True when .gitignore (via git when available, else a simple fnmatch read) excludes rel."""
    if is_git(root):
        r = _git(root, "check-ignore", "-q", "--", rel)
        return bool(r and r.returncode == 0)
    gi = root / ".gitignore"
    if not gi.exists():
        return False
    parts = pathlib.PurePosixPath(rel).parts
    for line in gi.read_text(errors="replace").splitlines():
        pat = line.strip()
        if not pat or pat.startswith(("#", "!")):
            continue
        pat = pat.rstrip("/")
        # shortcut: no negation, no anchored-path rules; upgrade by using git when it is installed.
        if fnmatch.fnmatch(rel, pat) or any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def risk(action: str, *, outside_cwd: bool = False) -> RiskVerdict:
    """The firewall score for a shell command or a write. A write outside the working directory is never below the gate."""
    v = score_action(action)
    if outside_cwd and v.score < APPROVAL_THRESHOLD:
        import secrets
        return RiskVerdict(score=APPROVAL_THRESHOLD, reasons=[*v.reasons, "outside working directory"],
                           needs_approval=True, approval_token=secrets.token_hex(3))
    return v


def approved(v: RiskVerdict, what: str, ask: Callable[[str], str], say: Callable[[str], None]) -> bool:
    """A score of 70 or more needs the typed one-time token. --yes never skips this."""
    if not v.needs_approval:
        return True
    say(f"risk {v.score}/100 ({', '.join(v.reasons) or 'rule match'}): {what}")
    try:
        reply = ask(f"type {v.approval_token} to allow, anything else to refuse: ")
    except EOFError:
        reply = ""
    return verify_approval(v, reply.strip().lower())
