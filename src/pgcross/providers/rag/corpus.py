from __future__ import annotations
from ...core.enums import Tier, CType, Verifiability, RoutingCertainty
from ...core.models import EvidenceCandidate, Provenance, CapabilityDescriptor

class RagCorpusProvider:
    def __init__(self, corpus_id, index, authority_ceiling: Tier):
        self.id=f"rag:{corpus_id}"; self.index=index; self.authority_ceiling=authority_ceiling
    def capability(self):
        return CapabilityDescriptor(provider_id=self.id, readout_intents={"passage_backed_claim"},
            verifiability_kind=Verifiability.SOURCE_ATTRIBUTED, static_ceiling=self.authority_ceiling)
    def routing_certainty(self, q): return RoutingCertainty.DENSE_WEAK
    def can_serve(self, q): return self.index.score(q.retrieval_terms)
    def produce(self, q):
        return [EvidenceCandidate(content=s.text, ctype=CType.RETRIEVED, provider_id=self.id,
            provenance=Provenance(kind="RAG_CHUNK", source_ref=f"{self.id}:{s.chunk_id}:{s.span}",
                                  verifiability=Verifiability.SOURCE_ATTRIBUTED),
            declared_tier=self.authority_ceiling, grounding_refs=[s.span]) for s in self.index.top_spans(q.retrieval_terms)]
    def ground(self, claim, cands):
        ok=self.index.support_check(claim, [c.grounding_refs for c in cands])
        return [c.grounding_refs[0] for c in cands] if ok else None      # None -> assemble suppresses
