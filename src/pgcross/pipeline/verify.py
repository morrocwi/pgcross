from __future__ import annotations
import logging
from ..core.enums import Tier, Verifiability, RoutingCertainty
from ..core.models import VerifierResult
from ..core.tiering import final_tier
from .lens import propose_lens
log = logging.getLogger("pgcross")

def verify_candidate(cand, provider):
    if hasattr(provider, "verify"): return provider.verify(cand)
    return VerifierResult(ok=True, verifiability=cand.provenance.verifiability, detail="passthrough")

def verify(q, routed, registry, cfg) -> list:
    """Propose+Verify stage (pure, behavior-preserving extraction from the former fused
    pipeline/assemble.py): calls provider.produce()/provider.verify(), applies
    core.tiering.final_tier() (the A2-with-min weakest-link fold, per the project's architecture
    design notes §2.1) and attaches tier/floor_reason to every
    candidate, including the lens candidate. This function has NO knowledge of Stakes/
    HIGH-stakes policy, I2/I4/I5 authorization filtering, or primary selection — all of that
    lives in authorize() (pipeline/authorize.py) instead. Returns the raw candidate list for
    authorize() to filter/select over.
    """
    cands = []
    prov = {p.id: p for p in registry.all()}
    for r in routed:
        p = prov[r.provider_id]
        try:
            raw = p.produce(q)                                   # provider isolation
        except Exception as e:
            log.warning("provider %s failed: %s", p.id, e); continue   # skip, never crash the request
        authority = getattr(p, "authority_ceiling", Tier.Dr)
        for c in raw:
            if c.provenance.kind in ("RAG_CHUNK", "CONTEXT_STORE"):
                if not p.ground(c.content, [c]):                 # I3 + suppress ungrounded retrieval
                    continue
            vr = verify_candidate(c, p)
            if not vr.ok:
                c.provenance = c.provenance.model_copy(update={"verifiability": Verifiability.NONE})
            t, reason = final_tier(c, rc=r.certainty, authority_ceiling=authority)
            c.tier, c.floor_reason = t, reason
            cands.append(c)
    lens = propose_lens(q, cfg)
    if lens:
        lens.tier, lens.floor_reason = final_tier(lens, rc=RoutingCertainty.NONE); cands.append(lens)
    return cands
