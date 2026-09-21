from __future__ import annotations
from ..core.models import Response, QueryIR
from .verify import verify
from .authorize import authorize

def assemble(q: QueryIR, routed, registry, cfg) -> Response:
    """Thin wrapper: Propose+Verify (verify.py) then Authorize (authorize.py) — pure,
    behavior-preserving extraction. See the project's internal architecture audit notes and
    architecture design notes for why this seam exists; this module's design
    (this migration) does not add or change any decision logic."""
    cands = verify(q, routed, registry, cfg)
    return authorize(cands, q, cfg)
