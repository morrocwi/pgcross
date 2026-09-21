from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field, field_serializer
from .enums import Tier, CType, Verifiability, Grounding, Stakes

class Provenance(BaseModel):
    kind: str                                     # ENGINE_CARD|RAG_CHUNK|BOUNDARY_LOOKUP|CONTEXT_STORE|MODEL_PRIOR
    source_ref: str | None = None
    verifiability: Verifiability

class CapabilityDescriptor(BaseModel):
    provider_id: str
    readout_intents: set[str]
    verifiability_kind: Verifiability
    static_ceiling: Tier                          # BEST-CASE max, NOT the emitted tier (see §5 note)
    cost_class: str = "cheap"

class QueryIR(BaseModel):
    text: str
    readout_intent: str | None = None
    slots: dict[str, float | str] = Field(default_factory=dict)
    grounding_map: dict[str, str | None] = Field(default_factory=dict)
    composed_from: dict[str, str] = Field(default_factory=dict)  # slot -> producing provider_id
                                                                   # (composition layer, see pipeline/compose.py;
                                                                   #  distinct from grounding_map: a slot here was
                                                                   #  DERIVED by another card, never read from text)
    retrieval_terms: list[str] = Field(default_factory=list)
    stakes: Stakes = Stakes.LOW
    decision_question: Any | None = None  # optional decision.schema.DecisionQuestion, set by a
        # caller (e.g. server/systemone.py) that has a real typed noul/choice/score question to
        # ask -- typed `Any`, not the concrete DecisionQuestion type, to avoid the circular
        # import decision/schema.py already has on this module (it imports EvidenceCandidate/
        # Provenance FROM here). When set and the witness-before-model gate would otherwise ask
        # a synthetic "is the fallback candidate admissible" question, pipeline/authorize.py asks
        # THIS question directly instead -- see its own docstring for why that distinction is
        # real, not cosmetic (found live 2026-09-21: the synthetic question is nonsensical when
        # no other pipeline stage produced a real candidate to judge the admissibility of).
    model_config = {"arbitrary_types_allowed": True}
    def slots_partially_known(self) -> bool: return len(self.slots) > 0

class EvidenceCandidate(BaseModel):
    content: str
    ctype: CType
    provider_id: str
    provenance: Provenance
    declared_tier: Tier
    grounding: Grounding = Grounding.ALL          # per-candidate; set by the card (COMPUTED only)
    grounding_refs: list[str] = Field(default_factory=list)
    tier: Tier | None = None                      # filled at assembly (final_tier, POST-verify)
    floor_reason: str | None = None

    @field_serializer("tier")
    def _ser_tier(self, v: Tier | None) -> str | None:
        return v.name if v is not None else None

    @field_serializer("declared_tier")
    def _ser_declared_tier(self, v: Tier) -> str:
        return v.name

class Response(BaseModel):
    candidates: list[EvidenceCandidate]           # NON-EMPTY (I4)
    primary: int
    stakes: Stakes

class VerifierResult(BaseModel):
    ok: bool; verifiability: Verifiability; detail: str = ""
