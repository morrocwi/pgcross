from __future__ import annotations
from ...core.enums import Tier, CType, Verifiability, Grounding, RoutingCertainty
from ...core.models import EvidenceCandidate, Provenance, CapabilityDescriptor, VerifierResult
from ...core.tiering import verifiability_ceiling
from ...pipeline.lens import clarify_candidate

class EngineCardProvider:
    id="card"; coq_checked=False; independent_oracle=False
    required_slots: list[str] = []; slot_patterns: dict[str,str] = {}; coq_law_ref=None
    produces: list[str] = []   # composition layer (pipeline/compose.py): explicit opt-in allow-list
                                # of compute()-output keys this card will let OTHER cards consume as
                                # a slot. Default empty — a card must deliberately declare this, it is
                                # never inferred from compute()'s dict keys.
    readout_family: str | None = None   # e.g. "R2" — the shared-readout family this card's math
                                # instantiates, per research_universal_solver's InterpretationCards
                                # philosophy (one operator, many domains as readout cards; see
                                # a private sibling repo, internal docs not included here).
                                # Default None. Two cards
                                # in the SAME non-None family may exchange a produced value for a
                                # DIFFERENTLY-named required slot via slot_aliases (pipeline/compose.py)
                                # — this is what lets composition generalize across vocabulary, not
                                # just within one hardcoded pair of cards.
    slot_aliases: dict[str, str] = {}   # own required_slot name -> canonical cross-family quantity
                                # name (defaults to itself if absent). Only consulted for
                                # readout_family-based matching; exact-name matching (the original,
                                # simpler mechanism) is always tried first and never needs this.
    def _verifiability(self):
        return (Verifiability.COQ_CHECKED if self.coq_checked else
                Verifiability.INDEPENDENT_ORACLE if self.independent_oracle else Verifiability.SELF_CONSISTENT)
    def capability(self):
        v=self._verifiability()
        return CapabilityDescriptor(provider_id=self.id, readout_intents={"value_verdict"},
                                    verifiability_kind=v, static_ceiling=verifiability_ceiling(v))
    def routing_certainty(self, q):
        return RoutingCertainty.SYMBOLIC if self.symbolic_match(q) else RoutingCertainty.DENSE_WEAK
    def can_serve(self, q): return 1.0 if self.symbolic_match(q) else self.dense_score(q)
    # concrete cards implement: symbolic_match, dense_score, compute, render, validate, v_struct_ok, v_answer_ok
    def dense_score(self,q): return 0.0
    def validate(self,slots): return None
    def v_struct_ok(self): return True
    def v_answer_ok(self,cand): return True
    def _grounding_status(self, q):
        used=[q.grounding_map.get(s) for s in self.required_slots]
        return Grounding.PARTIAL if any(x is None for x in used) else Grounding.ALL
    def produce(self, q):
        missing=[s for s in self.required_slots if s not in q.slots]
        if missing: return [clarify_candidate(self.id, f"need: {', '.join(missing)}", q)]
        grounding=self._grounding_status(q)
        try:
            self.validate(q.slots); val=self.compute(q.slots)
        except (ValueError, ZeroDivisionError) as e:
            return [clarify_candidate(self.id, f"invalid input: {e}", q)]         # never a 500
        v=self._verifiability()
        refs=[q.grounding_map.get(s) for s in self.required_slots if q.grounding_map.get(s)]
        content=self.render(val,q)
        if grounding == Grounding.PARTIAL:                        # D1 disclosure (required by spec)
            ungrounded=[s for s in self.required_slots if not q.grounding_map.get(s)]
            composed=[s for s in ungrounded if s in q.composed_from]
            assumed=[s for s in ungrounded if s not in q.composed_from]
            parts=[]
            if composed:
                parts.append(", ".join(f"{s} (derived from {q.composed_from[s]})" for s in composed))
            if assumed:
                parts.append(", ".join(assumed) + " assumed from context")
            content += (f" ({'; '.join(parts)};"
                        " provide explicit values for a firmer answer)")
        return [EvidenceCandidate(content=content, ctype=CType.COMPUTED, provider_id=self.id,
            provenance=Provenance(kind="ENGINE_CARD", source_ref=self.coq_law_ref, verifiability=v),
            declared_tier=self.capability().static_ceiling, grounding=grounding, grounding_refs=refs)]
    def verify(self, cand):
        if self.coq_checked and not self.v_struct_ok(): return VerifierResult(ok=False, verifiability=Verifiability.NONE, detail="coq")
        if self.independent_oracle: return VerifierResult(ok=self.v_answer_ok(cand), verifiability=self._verifiability(), detail="oracle")
        return VerifierResult(ok=True, verifiability=self._verifiability(), detail="self_consistent_NA")
    def ground(self, claim, cands): return list(cands[0].grounding_refs)
