from __future__ import annotations
from ..core.enums import Tier, CType, Verifiability, Grounding, RoutingCertainty
from ..core.models import EvidenceCandidate, Provenance

def clarify_candidate(pid, msg, q) -> EvidenceCandidate:
    return EvidenceCandidate(content=f"To answer, I need: {msg}", ctype=CType.CLARIFY, provider_id=pid,
        provenance=Provenance(kind="MODEL_PRIOR", verifiability=Verifiability.NONE),
        declared_tier=Tier.Open, tier=Tier.Open, floor_reason="meta")       # tier set (fix R_d)

def consultation_candidate(q) -> EvidenceCandidate:
    return EvidenceCandidate(content=("I don't have a grounded candidate strong enough to assert here. "
        "For a decision this consequential, consult a qualified human or source."),
        ctype=CType.CONSULTATION, provider_id="core",
        provenance=Provenance(kind="MODEL_PRIOR", verifiability=Verifiability.NONE),
        declared_tier=Tier.Open, tier=Tier.Open, floor_reason="meta")

def clarify_or_consultation(q) -> EvidenceCandidate:
    return clarify_candidate("core", "more specific parameters", q) if q.slots_partially_known() \
           else consultation_candidate(q)

def pick_primary(cands) -> int:
    order = {CType.COMPUTED:5, CType.RETRIEVED:4, CType.LENS:3, CType.GUESS:2, CType.CLARIFY:1, CType.CONSULTATION:0}
    # fix R_a: explicit None handling (Tier.Open==0 is falsy, so `x or Tier.Open` is fragile)
    def tval(c): return int(c.tier) if c.tier is not None else int(Tier.Open)
    return max(range(len(cands)), key=lambda i: (tval(cands[i]), order[cands[i].ctype]))

def propose_lens(q, cfg) -> EvidenceCandidate | None:
    sources = getattr(cfg, "lens_sources", [])
    if not sources: return None
    if getattr(cfg, "backend", None) is None: return None  # no backend → skip lens (graceful)
    src = sources[0]                        # ▸ SPEC: replace with best-fit-domain selection
    try:
        from ..backends.base import TransportPrompt
        out = cfg.backend.transport(TransportPrompt(task="structure_lens", text=q.text))
        framing = out.json
    except Exception:
        framing = {}
    content = (f"A way to see this, borrowing {src}'s structure: "
               f"{framing.get('reframe','(structural analogy)')} — this is a lens, not an answer.")
    return EvidenceCandidate(content=content, ctype=CType.LENS, provider_id=f"lens:{src}",
        provenance=Provenance(kind="MODEL_PRIOR", source_ref=None, verifiability=Verifiability.NONE),
        declared_tier=Tier.Wf, grounding=Grounding.ALL, grounding_refs=[])
