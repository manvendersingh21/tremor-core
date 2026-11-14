"""PostFileSave under packages/**: run the pytest files that cover the saved module. Offline, no keys.

Maps packages/chimera-core/<dir>/<stem>.py to tests/test_<stem>.py, then to any test file that mentions the stem.
"""
from __future__ import annotations

import re
import sys

from _common import PYTHON, ROOT, event, event_paths, run


def targets(rel: str) -> list[str]:
    stem = rel.rsplit("/", 1)[-1].removesuffix(".py")
    if rel.startswith("tests/") and stem.startswith("test_"):
        return [rel]
    direct = ROOT / "tests" / f"test_{stem}.py"
    if direct.exists():
        return [f"tests/test_{stem}.py"]
    word = re.compile(rf"\b{re.escape(stem)}\b")
    return sorted(f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py") if word.search(p.read_text(errors="ignore")))


def main() -> int:
    paths = [p for p in event_paths(event()) if p.endswith(".py") and p.startswith(("packages/", "tests/"))]
    files = sorted({t for p in paths for t in targets(p)})
    if not files:
        print("no test file maps to the saved module; nothing run")
        return 0
    return run([PYTHON, "-m", "pytest", "-q", "-x", *files], timeout=100)


if __name__ == "__main__":
    sys.exit(main())
