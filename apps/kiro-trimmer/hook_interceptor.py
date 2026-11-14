"""Kiro PostFileSave hook (.kiro/hooks/speculative-shield.json): file diff on stdin -> one-paragraph review.

Never fails the save: any error goes to stderr and the exit code stays 0.
"""
from __future__ import annotations

import argparse
import sys

from common import build_router, load_config

MAX_DIFF_CHARS = 12000  # shortcut: truncates long diffs, chunk them if reviews need the tail

PROMPT = ("Review this diff in one short paragraph: bugs, spec or style problems, risky changes. "
          "If it looks fine, say so in one sentence.\n\n{diff}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="post-save")
    ap.add_argument("--prefer-local-kv", action="store_true")  # accepted for the hook contract; the local tier already keeps its prompt cache
    args = ap.parse_args()
    diff = sys.stdin.read().strip()
    if not diff:
        return 0
    try:
        out = build_router(load_config()).generate(PROMPT.format(diff=diff[:MAX_DIFF_CHARS]))
        print(out.text.strip())
    except Exception as e:  # noqa: BLE001
        print(f"chimera hook ({args.mode}): {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
