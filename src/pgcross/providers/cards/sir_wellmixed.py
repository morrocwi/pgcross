from .base import EngineCardProvider

def _epi(t): return any(k in t.lower() for k in ("threshold","epidemic","outbreak","r0","reproduction number","spread"))

# Network-structure keywords: if present in the query AND λmax is absent, the user
# is asking a network-SIS question. SIR (well-mixed) must stay silent so SIS issues CLARIFY.
_NETWORK_TERMS = frozenset(["network","spectral radius","eigenvalue","adjacency","λmax","λ_max","lambda_max"])

class SirWellMixedCard(EngineCardProvider):
    id="sir_wellmixed"; coq_checked=True; coq_law_ref="pgcross:coq/SIR_R0_WellMixed.v#SIR_threshold_correct"
    required_slots=["beta","gamma"]
    def symbolic_match(self,q): return set(self.required_slots)<=set(q.slots) or _epi(q.text)

    def produce(self,q):
        # When query explicitly references network structure but λmax is absent,
        # defer entirely — the user wants a network answer, not a well-mixed fallback.
        if "lambda_max" not in q.slots and any(kw in q.text.lower() for kw in _NETWORK_TERMS):
            return []
        return super().produce(q)
    def dense_score(self,q): return 0.3 if _epi(q.text) else 0.0  # lower than SIS (0.4) — less specific
    def validate(self,slots):
        if float(slots["gamma"])==0.0: raise ValueError("gamma must be nonzero")
    def compute(self,slots):
        b,g=float(slots["beta"]),float(slots["gamma"]); R0=b/g; return {"R0":R0,"above":R0>1.0,"beta":b,"gamma":g}
    def render(self,val,q):
        r0=val["R0"]; prec=8 if abs(r0-1.0)<0.01 else 6
        verdict="above" if val["above"] else "below"
        return (f"R0 = {r0:.{prec}g} -> {verdict} the epidemic threshold. "
                f"[well-mixed SIR: assumes homogeneous mixing, no network structure; "
                f"R0 = β/γ = {val['beta']:.6g}/{val['gamma']:.6g}]")
