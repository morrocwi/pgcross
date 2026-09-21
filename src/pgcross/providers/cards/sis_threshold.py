from .base import EngineCardProvider
def _epi(t): return any(k in t.lower() for k in ("threshold","epidemic","outbreak","r0","reproduction number"))
class SisThresholdCard(EngineCardProvider):
    id="sis_threshold"; coq_checked=True; coq_law_ref="pgcross:coq/SIS_R0_Threshold.v#SIS_threshold_correct"
    required_slots=["beta","gamma","lambda_max"]
    produces=["R0"]   # composition layer: SIS's computed R0 may feed another card (e.g. HerdImmunityCard)
    readout_family="R2"   # spectrum readout — InterpretationCards: "bio (SIS): epidemic threshold
                           # β_c/γ = 1/λmax(adjacency) | R2" (a private sibling repo's design notes)
    def symbolic_match(self,q): return set(self.required_slots)<=set(q.slots) or _epi(q.text)
    def dense_score(self,q): return 0.4 if _epi(q.text) else 0.0
    def validate(self,slots):
        if float(slots["gamma"])==0.0: raise ValueError("gamma must be nonzero")
    def compute(self,slots):
        b,g,l=float(slots["beta"]),float(slots["gamma"]),float(slots["lambda_max"])
        R0=b*l/g; return {"R0":R0,"above":R0>1.0,"lambda_max":l}
    def render(self,val,q):
        r0=val["R0"]
        # 8 sig figs when near threshold OR near any integer (else 6g rounds 1.9999999 → "2")
        prec=8 if abs(r0-1.0)<0.01 or abs(r0-round(r0))<5e-5 else 6
        verdict="above" if val["above"] else "below"
        return (f"R0 = {r0:.{prec}g} -> {verdict} the epidemic threshold. "
                f"[network-structured SIS: R0 = β·λmax/γ, λmax={val['lambda_max']:.8g}]")
