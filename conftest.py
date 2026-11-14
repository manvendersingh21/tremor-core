"""Expose `packages/chimera-core` (hyphenated dir) as the importable package `chimera_core`."""
import importlib.util
import pathlib
import sys

_pkg = pathlib.Path(__file__).parent / "packages" / "chimera-core"
if "chimera_core" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "chimera_core", _pkg / "__init__.py", submodule_search_locations=[str(_pkg)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["chimera_core"] = mod
    spec.loader.exec_module(mod)
