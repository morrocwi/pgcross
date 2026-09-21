from .base import EngineCardProvider
def _herd(t): return any(k in t.lower() for k in ("herd immunity","herd-immunity","vaccin","immuniz","vaccine"))
class HerdImmunityCard(EngineCardProvider):
    id="herd_immunity"; coq_checked=True; coq_law_ref="pgcross:coq/HIT_Formula.v#HIT_in_unit_interval"
    required_slots=["R0"]
    def symbolic_match(self,q): return "R0" in q.slots or _herd(q.text)
    def dense_score(self,q): return 0.4 if _herd(q.text) else 0.0
    def validate(self,slots):
        r=float(slots["R0"])
        if r<=1.0: raise ValueError(
            f"R0 = {r:.6g} ≤ 1: disease is not self-sustaining; "
            "no herd immunity threshold exists (HIT = 1−1/R0 is undefined or non-positive)")
    def compute(self,slots):
        r=float(slots["R0"]); hit=1.0-1.0/r; return {"R0":r,"HIT":hit}
    def render(self,val,q):
        r,hit=val["R0"],val["HIT"]
        return (f"Herd immunity threshold: {hit:.4g} ({hit*100:.3g}% immune/vaccinated needed). "
                f"[R0={r:.5g}; HIT=1−1/R0]")
