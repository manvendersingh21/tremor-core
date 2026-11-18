"""The skeleton API: `Assistant(config).ask(prompt, context)`. See skeleton/README.md."""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import conftest  # noqa: E402,F401  (registers packages/chimera-core as `chimera_core`)

from .assistant import Answer, Assistant, Config  # noqa: E402

__all__ = ["Answer", "Assistant", "Config"]
