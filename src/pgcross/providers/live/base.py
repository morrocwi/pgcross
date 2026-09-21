"""providers/live/base.py — LIVE_LOOKUP provider kind (K6 track 2b).

`providers/atlas/constants.py` is a real gap this closes: every value there is a
hardcoded Python dict baked at code-write time — there was no provider kind in this
repo that reads from an external source at query time. This is that kind.

Shape mirrors AtlasProvider exactly (capability/routing_certainty/can_serve/produce/
ground/verify) so it slots into the existing Registry with zero core/pipeline changes.
Differences from Atlas, both deliberate:
  - provenance.kind = "LIVE_LOOKUP", not "BOUNDARY_LOOKUP" — a live value is NOT the same
    epistemic object as a citable constant; downstream code that treats BOUNDARY_LOOKUP
    as static must not silently accept a live-fetched value under that name.
  - staleness is declared IN source_ref (e.g. "live:usd_thb@2026-07-01T19:00:00+07:00")
    rather than as a new Provenance field — `core/models.py` is not touched.

Per README's existing policy ("cloud adapters stay opt-in optional, never required"):
a LiveDataProvider is opt-in — the CLI/server does not register one by default. It must
be constructed and registered explicitly by whoever wants a live source. If the fetch
fails (offline, endpoint down), `produce()` returns nothing rather than raising — I8
fail-closed, matching every other provider's error handling in this codebase.
"""
from __future__ import annotations
import time
from typing import Any, Optional

from ...core.enums import Tier, CType, Verifiability, RoutingCertainty, Grounding
from ...core.models import EvidenceCandidate, Provenance, CapabilityDescriptor, QueryIR


class LiveDataProvider:
    """Base for a provider that fetches a small set of named live values at query time.

    Subclasses implement `_keys()` (name -> aliases, for routing) and `_fetch(key)`
    (the actual network call -> {"value":..., "unit":..., "description":..., "url":...}).
    A short TTL cache avoids re-fetching on every query in a burst.
    """

    id: str = "live:base"
    ttl_seconds: float = 300.0  # re-fetch at most every 5 minutes per key

    def __init__(self):
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # ---- subclasses implement these two -----------------------------------
    def _keys(self) -> dict[str, list[str]]:
        """key -> list of aliases/keywords that should route to this key."""
        raise NotImplementedError

    def _fetch(self, key: str) -> Optional[dict[str, Any]]:
        """Real network call. Return None on failure (never raise past this method)."""
        raise NotImplementedError

    # ---- shared machinery ----------------------------------------------------
    def _get(self, key: str) -> Optional[dict[str, Any]]:
        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and (now - cached[0]) < self.ttl_seconds:
            return cached[1]
        try:
            entry = self._fetch(key)
        except Exception:
            entry = None
        if entry is None:
            return cached[1] if cached is not None else None  # serve stale over nothing
        self._cache[key] = (now, entry)
        return entry

    def _match_keys(self, text: str) -> list[str]:
        t = text.lower()
        out = []
        for key, aliases in self._keys().items():
            if any(a.lower() in t for a in aliases + [key]):
                out.append(key)
        return out

    def capability(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            provider_id=self.id,
            readout_intents={"live_lookup"},
            verifiability_kind=Verifiability.SOURCE_ATTRIBUTED,
            static_ceiling=Tier.Dr,
            cost_class="network",
        )

    def routing_certainty(self, q: QueryIR) -> RoutingCertainty:
        return RoutingCertainty.DENSE_CLEAR if self._match_keys(q.text) else RoutingCertainty.NONE

    def can_serve(self, q: QueryIR) -> float:
        keys = self._match_keys(q.text)
        return min(1.0, 0.6 + 0.1 * (len(keys) - 1)) if keys else 0.0

    def produce(self, q: QueryIR) -> list[EvidenceCandidate]:
        candidates = []
        for key in self._match_keys(q.text):
            entry = self._get(key)
            if entry is None:
                continue  # I8 fail-closed: no value, no candidate — never a guess
            retrieved_at = entry.get("retrieved_at", "unknown-time")
            source_ref = f"live:{key}@{retrieved_at}"
            content = (
                f"[Live lookup — {key}] {entry.get('description', key)}. "
                f"Value: {entry['value']} {entry.get('unit', '')}. "
                f"Retrieved: {retrieved_at}. Source: {entry.get('url', self.id)}."
            )
            candidates.append(EvidenceCandidate(
                content=content, ctype=CType.COMPUTED, provider_id=self.id,
                provenance=Provenance(kind="LIVE_LOOKUP", source_ref=source_ref,
                                       verifiability=Verifiability.SOURCE_ATTRIBUTED),
                declared_tier=Tier.Dr, grounding=Grounding.ALL, grounding_refs=[key],
            ))
        return candidates

    def ground(self, claim: str, cands: list[EvidenceCandidate]):
        refs = [ref for c in cands for ref in c.grounding_refs]
        return refs if refs else None

    def verify(self, cand: EvidenceCandidate):
        from ...core.models import VerifierResult
        return VerifierResult(ok=True, verifiability=Verifiability.SOURCE_ATTRIBUTED,
                               detail="live_lookup_no_independent_oracle")
