from __future__ import annotations
from .enums import Tier, Verifiability, RoutingCertainty, Grounding, CType
from .models import EvidenceCandidate

def verifiability_ceiling(v: Verifiability, authority_ceiling: Tier = Tier.Dr) -> Tier:
    table = {Verifiability.COQ_CHECKED: Tier.Th_coqc, Verifiability.INDEPENDENT_ORACLE: Tier.finite_diagnostic,
             Verifiability.SOURCE_ATTRIBUTED: Tier.Dr, Verifiability.SELF_CONSISTENT: Tier.Dr,
             Verifiability.NONE: Tier.Open}
    ceil = table[v]
    if v == Verifiability.SOURCE_ATTRIBUTED:
        ceil = min(ceil, authority_ceiling)          # web corpus -> Wf/Open
    return ceil

def routing_cap(rc: RoutingCertainty) -> Tier:
    return {RoutingCertainty.SYMBOLIC: Tier.Th_coqc, RoutingCertainty.DENSE_CLEAR: Tier.finite_diagnostic,
            RoutingCertainty.DENSE_WEAK: Tier.Wf, RoutingCertainty.NONE: Tier.Open}[rc]

def grounding_cap(g: Grounding) -> Tier:
    return {Grounding.ALL: Tier.Th_coqc, Grounding.PARTIAL: Tier.Wf, Grounding.NONE: Tier.Open}[g]

# CTYPE-AWARE. RETRIEVED deliberately does NOT take routing_cap/grounding_cap (that was v1's bug —
# it kept RAG below Dr forever). Span-support for RETRIEVED is handled by the §4 downgrade BEFORE this.
#
# This is a live instance of information-discrete-math's A2 fold (I_⊕[f](N) = ⨁_{k<N} f[k]) with
# ⊕ = min: the weakest-link ceiling over {declared, verifiability, routing, grounding, ctype/meta}
# caps. Naming/documentation only — see the project's architecture design notes §2.1/§4 item 3. Future
# gates that need a different fold (Σ for evidence-weight sums, max for worst-case risk, AND/OR for
# requirement/red-flag checks) are other instances of the same A2 root, not a new mechanism.
def final_tier(cand: EvidenceCandidate, *, rc: RoutingCertainty, authority_ceiling: Tier = Tier.Dr) -> tuple[Tier, str]:
    caps: dict[str, Tier] = {"declared": cand.declared_tier}
    v = cand.provenance.verifiability
    if cand.ctype == CType.COMPUTED:
        caps["verifiability"] = verifiability_ceiling(v, authority_ceiling)
        caps["routing"]       = routing_cap(rc)
        caps["grounding"]     = grounding_cap(cand.grounding)
    elif cand.ctype == CType.RETRIEVED:
        caps["verifiability"] = verifiability_ceiling(v, authority_ceiling)
    elif cand.ctype == CType.LENS:
        caps["ctype"] = Tier.Wf
    elif cand.ctype == CType.GUESS:
        caps["ctype"] = Tier.Open
    else:
        caps["meta"] = Tier.Open
    t = min(caps.values()); reason = min(caps, key=lambda k: caps[k])
    return t, reason
