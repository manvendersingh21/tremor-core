"""PostFileSave under site/**: the site tests plus the no-JS page freshness check. Offline."""
from __future__ import annotations

import sys

from _common import PYTHON, run


def main() -> int:
    bad = run([PYTHON, "-m", "pytest", "-q", "-x", "tests/test_world.py", "tests/test_hud.py"], timeout=100)
    bad |= run([sys.executable, "site/build.py", "--check"], timeout=30)
    if bad:
        print("site check failed: run `python3 site/build.py` if only index.html is stale", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
