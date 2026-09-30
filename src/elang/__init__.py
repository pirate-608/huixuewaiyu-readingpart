"""elang reading solver — installable distribution.

Layout note (important)
-----------------------
The implementation lives as flat modules (`elang_reader`, `elang_session`,
`elang_mcp`, `config`) rather than as submodules. That is deliberate: the same
files are used two ways —

  * **from this repo** — run directly as `python scripts/elang_reader.py`, which is
    what the skill documents and what development uses;
  * **installed as a tool** — `uv tool install` puts them inside this package,
    where `elang_reader` must still be importable **by its bare name**, because
    `elang_session` does `import elang_reader as er`.

Rather than maintain two layouts or rewrite every import, this module simply puts
its own directory on `sys.path`. Both environments then resolve the same flat
names and the module bodies need no changes at all.

Resources
---------
Non-Python data (`answers.json`) is referenced through `importlib.resources`, never
through a path relative to the current working directory — a tool's cwd is
whatever the host chose, so relative lookups would break unpredictably.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Make the flat modules importable by bare name (see the layout note above).
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

__version__ = "0.1.0"

__all__ = ["__version__"]
