"""CHIMERA gateway: OpenAI-compatible HTTP front for the router. Importing this package registers `chimera_core`."""
import pathlib
import sys

_ROOT = str(pathlib.Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import conftest  # noqa: E402,F401  (registers the hyphenated package dir as chimera_core)
