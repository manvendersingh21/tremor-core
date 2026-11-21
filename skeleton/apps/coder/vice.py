"""Vice City colours for the coder's terminal output: hot pink and electric blue, plus a small neon banner.

Colour is on only for a terminal. NO_COLOR (any value) turns it off; FORCE_COLOR turns it on for pipes.
The text itself never changes, so piped output and tests see plain text.
"""
from __future__ import annotations

import os
import re
import sys

PINK, BLUE, DIM, RESET = "\x1b[38;2;255;45;149m", "\x1b[38;2;0;194;255m", "\x1b[2m", "\x1b[0m"
BANNER = ("  ╔═════════════════════════════╗\n"
          "  ║  C H I M E R A   C O D E R  ║\n"
          "  ╚═════════════════════════════╝")


def use_color(stream=None) -> bool:
    if "NO_COLOR" in os.environ:  # https://no-color.org: set to anything, even empty
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool((stream or sys.stdout).isatty())


def banner() -> str:
    return f"{PINK}{BANNER.splitlines()[0]}\n{BLUE}{BANNER.splitlines()[1]}\n{PINK}{BANNER.splitlines()[2]}{RESET}"


def paint(text: str) -> str:
    """Colour one report: step lines pink, diff add blue, diff remove pink, the final line bold-pink/blue."""
    out = []
    for ln in text.split("\n"):
        if ln.startswith("step "):
            ln = re.sub(r"(tests )(PASS)", lambda m: m.group(1) + BLUE + m.group(2) + PINK, ln)
            ln = re.sub(r"(tests )(FAIL)", lambda m: m.group(1) + RESET + "\x1b[1m" + m.group(2) + PINK, ln)
            ln = PINK + ln + RESET
        elif ln.startswith(("+++", "---")):
            ln = DIM + ln + RESET
        elif ln.startswith("+"):
            ln = BLUE + ln + RESET
        elif ln.startswith("-"):
            ln = PINK + ln + RESET
        elif ln.startswith("@@"):
            ln = BLUE + DIM + ln + RESET
        elif ln.startswith("answered by"):
            ln = "\x1b[1m" + PINK + ln + RESET
        out.append(ln)
    return "\n".join(out)
