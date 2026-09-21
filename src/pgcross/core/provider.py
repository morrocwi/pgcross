from __future__ import annotations
from typing import Protocol, runtime_checkable
from .models import QueryIR, EvidenceCandidate, CapabilityDescriptor

@runtime_checkable
class EvidenceProvider(Protocol):
    id: str
    def capability(self) -> CapabilityDescriptor: ...
    def can_serve(self, q: QueryIR) -> float: ...
    def routing_certainty(self, q: QueryIR): ...
    def produce(self, q: QueryIR) -> list[EvidenceCandidate]: ...
    def ground(self, claim: str, cands: list[EvidenceCandidate]) -> list[str] | None: ...

class Registry:
    def __init__(self): self._p = []
    def register(self, p) -> None:
        cap = p.capability()
        assert cap.verifiability_kind is not None, "provider must declare verifiability_kind"
        assert cap.static_ceiling is not None, "provider must declare static_ceiling"
        assert hasattr(p, "routing_certainty"), "provider must declare routing_certainty"
        self._p.append(p)
    def all(self): return list(self._p)
