import os
import pathlib
import sys

_root = pathlib.Path(__file__).resolve().parents[2]
_py = _root / ".venv" / "bin" / "python"
if _py.exists() and pathlib.Path(sys.prefix).resolve() != (_root / ".venv").resolve():
    os.execv(str(_py), [str(_py), "-m", "apps.terminal", *sys.argv[1:]])  # needs the repo venv (pydantic)
sys.path.insert(0, str(_root))

from apps.terminal.cli import main  # noqa: E402

sys.exit(main())
