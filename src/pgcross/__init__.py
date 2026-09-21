"""pgcross — PGcross Mini: the universal, self-installable, offline AI bundle (N14).

Thin wrapper over the N12 `product_universal_rag` engine (imported, never re-implemented). It wires the
N12 BYO surface to the BUNDLED universal corpus (`pgcross.db`) and the wrapped Typhoon-1b composer, with
an offline-first default. readout-not-truth.

    from pgcross import ask
    print(ask("What is Bayes' theorem?")["answer"])
"""
from __future__ import annotations
import os

# The legacy N14 bundled surface (bundle.py / humane_gate.py / sona.py) is not part of the
# public-core file set (docs/PUBLIC_CORE_BOUNDARY.md classifies it `obsolete`, not staged).
# Import it lazily/optionally so `import pgcross` and the Decision Forge CLI/server entry
# points (`pgcross.cli`, `pgcross.server.app`) still work in a tree where those legacy files
# are absent (e.g. the public-core staged copy) — the top-level package must not require them
# just to be importable.
__all__ = ["__version__"]
try:
    from .bundle import bundle_db_path, ask, build_rag  # noqa: F401
    from .humane_gate import answer as humane_answer, present as humane_present  # noqa: F401
    from .sona import render as sona_render  # noqa: F401
    __all__ += ["ask", "build_rag", "bundle_db_path", "humane_answer", "humane_present",
                "sona_render"]
except ImportError:
    pass

__version__ = "0.0.0.dev0"  # GATE_A5 not passed — no release version claimed
