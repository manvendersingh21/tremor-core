"""Fail loudly on secrets, private hostnames or IPs, and key paths in changed files.

Modes: `--changed` (default; staged + unstaged + untracked files), `--staged` (git commit), `--tool` (PreToolUse event
on STDIN: scan only when the shell command is a `git commit`). Exit 2 blocks a PreToolUse; any non-zero is reported.
Findings print the file, line and rule name, never the matched text. Stdlib only, no network.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

from _common import ROOT, event

RULES = {
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "api key or token": r"\b(?:sk|pk|rk|ghp|gho|ghs|glpat|xox[abp])[-_][A-Za-z0-9_\-]{20,}",
    "aws key id": r"\bAKIA[0-9A-Z]{16}\b",
    "jwt": r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    "dsn with password": r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb|redis|neo4j(?:\+s)?|bolt(?:\+s)?)://[^\s'\"/:@<>$]+:[^\s'\"@<>$]+@",
    "supabase host": r"(?i)\b[a-z0-9]{12,}\.(?:supabase\.co|pooler\.supabase\.com)\b",
    "aura host": r"(?i)\b[a-z0-9]{6,}\.databases\.neo4j\.io\b",
    "ssh target host": r"\bssh\b[^\n]*\s[\w.-]+@(?![<$])[\w.-]+\.[a-z]{2,}",
    "non-loopback host in url": r"(?i)\bhttps?://(?!127\.0\.0\.1|0\.0\.0\.0)(?:\d{1,3}\.){3}\d{1,3}\b",
    "key path": r"(?:~|/Users/[^/\s]+|/home/[^/\s]+)/\.ssh/\S+|\bssh\b[^\n]*\s-i\s+(?![<$])\S+|[\w.~-]+/id_(?:rsa|ed25519|ecdsa)\b|[\w~/.-]+/[\w.-]+\.pem\b",
    "secret assignment": r"(?im)^\s*(?:export\s+)?[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|DSN)[A-Z0-9_]*\s*=\s*['\"]?(?![A-Z0-9_]+['\"]?(?:\s|$))(?!\$|\{|<|your|xxx|changeme|\s)[A-Za-z0-9/+_\-]{12,}",
}
COMPILED = {k: re.compile(v) for k, v in RULES.items()}
SKIP_PARTS = {".git", ".venv", "vendor", "__pycache__", ".scratch", "node_modules"}
SKIP_FILES = {".env", ".env.example", "secret_scan.py", "safety.py", "test_terminal.py", "test_memory.py"}
SKIP_SUFFIX = {".webp", ".png", ".jpg", ".gif", ".gguf", ".bin", ".safetensors", ".jsonl", ".csv", ".lock", ".svg"}


def git(*args: str) -> list[str]:
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return [x for x in r.stdout.splitlines() if x]


def files_for(mode: str) -> list[str]:
    if mode == "--staged":
        return git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    return sorted(set(git("diff", "--name-only", "--diff-filter=ACMR", "HEAD") + git("ls-files", "--others", "--exclude-standard")))


def scannable(rel: str) -> bool:
    p = pathlib.Path(rel)
    return not (SKIP_PARTS & set(p.parts) or p.name in SKIP_FILES or p.suffix in SKIP_SUFFIX or p.name.startswith(".env"))


def scan(rel: str) -> list[str]:
    try:
        text = (ROOT / rel).read_text(errors="ignore")
    except OSError:
        return []
    hits = []
    for rule, rx in COMPILED.items():
        for m in rx.finditer(text):
            hits.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: {rule}")
            break  # one hit per rule per file is enough to fail
    return hits


def main() -> int:
    mode = next((a for a in sys.argv[1:] if a.startswith("--")), "--changed")
    if mode == "--tool":
        cmd = str(event().get("tool_input", {}).get("command", ""))
        if not re.search(r"\bgit\s+(?:-\S+\s+)*commit\b", cmd):
            return 0
        mode = "--staged"
    hits = [h for f in files_for(mode) if scannable(f) for h in scan(f)]
    if not hits:
        print(f"secret scan ({mode[2:]}): clean")
        return 0
    print("SECRET SCAN FAILED. Remove these before committing (values are not shown):", file=sys.stderr)
    for h in hits:
        print("  " + h, file=sys.stderr)
    print("Rules: .kiro/steering/security.md. Move values to .env; write 'an SSH tunnel to your GPU box'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
