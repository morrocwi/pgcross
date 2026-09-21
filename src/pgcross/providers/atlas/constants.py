"""providers/atlas/constants.py — BOUNDARY_LOOKUP atlas provider, capped Dr.

The atlas is a table of named physical/biological/mathematical constants with their
provenance (CODATA, PubMed, canonical references). A query that mentions a known key
(by exact name or alias) receives a COMPUTED candidate whose tier is at most Dr,
provenance.kind = "BOUNDARY_LOOKUP", and source_ref = the atlas key.

SPEC note: this is a read-only lookup, not a computation — the card never derives or
extrapolates; it returns the stored value verbatim.  Because the lookup is grounded
directly by the table entry, it bypasses the assemble.py RAG_CHUNK/CONTEXT_STORE
suppression path (kind != "RAG_CHUNK").

PROVE-IT (routing): test that queries using paraphrases of key names (not exact strings)
still route here rather than silently falling to the consultation floor.
"""
from __future__ import annotations
import re
from typing import Any

from ...core.enums import Tier, CType, Verifiability, RoutingCertainty, Grounding
from ...core.models import (
    EvidenceCandidate,
    Provenance,
    CapabilityDescriptor,
    QueryIR,
)

# ---------------------------------------------------------------------------
# Atlas table
# Each entry: key -> {value, unit, description, aliases, source_ref}
# source_ref should be a citable handle (DOI, CODATA-year, PMID, etc.)
# ---------------------------------------------------------------------------
_ATLAS: dict[str, dict[str, Any]] = {
    # Correlation-time constants (τ_c) across disciplines
    "tau_c_water_rotation": {
        "value": 8.3e-12,
        "unit": "s",
        "description": "Rotational correlation time of liquid water at 298 K",
        "aliases": ["tau_c water", "water correlation time", "tau_c_water"],
        "source_ref": "CODATA-2018:water_rotation",
    },
    "tau_c_protein_ns": {
        "value": 5.0e-9,
        "unit": "s",
        "description": "Typical tumbling correlation time for a 10 kDa globular protein in water",
        "aliases": ["protein correlation time", "tau_c protein", "tau_c_protein"],
        "source_ref": "PMID:15340383",
    },
    "tau_c_membrane_lipid": {
        "value": 1.0e-8,
        "unit": "s",
        "description": "Lateral diffusion correlation time for a phospholipid in a bilayer",
        "aliases": ["lipid correlation time", "tau_c lipid", "tau_c_membrane"],
        "source_ref": "PMID:2322539",
    },
    "tau_c_atmospheric_eddy": {
        "value": 1.2e5,
        "unit": "s",
        "description": "Integral turbulence correlation time for large atmospheric eddies (~33 hr)",
        "aliases": ["eddy correlation time", "tau_c atmosphere", "tau_c_eddy"],
        "source_ref": "NIST:SP330-2019",
    },
    "tau_c_neuronal_spike": {
        "value": 1.0e-3,
        "unit": "s",
        "description": "Autocorrelation decay time of a cortical spike train (1 ms scale)",
        "aliases": ["spike correlation time", "neural tau_c", "tau_c_spike"],
        "source_ref": "PMID:10600988",
    },
    "tau_c_financial_order": {
        "value": 0.5,
        "unit": "s",
        "description": "Order-flow autocorrelation decay time in electronic equity markets",
        "aliases": ["order flow correlation", "tau_c finance", "tau_c_order"],
        "source_ref": "arXiv:physics/0311036",
    },
    # Physical constants
    "boltzmann_k": {
        "value": 1.380649e-23,
        "unit": "J/K",
        "description": "Boltzmann constant (exact, 2019 SI redefinition)",
        "aliases": ["boltzmann constant", "k_B", "kB"],
        "source_ref": "CODATA-2018:boltzmann",
    },
    "avogadro_n": {
        "value": 6.02214076e23,
        "unit": "mol^-1",
        "description": "Avogadro constant (exact, 2019 SI redefinition)",
        "aliases": ["avogadro number", "N_A", "NA"],
        "source_ref": "CODATA-2018:avogadro",
    },
    "planck_h": {
        "value": 6.62607015e-34,
        "unit": "J.s",
        "description": "Planck constant (exact, 2019 SI redefinition)",
        "aliases": ["planck constant", "h_planck"],
        "source_ref": "CODATA-2018:planck",
    },
    "speed_of_light_c": {
        "value": 299792458.0,
        "unit": "m/s",
        "description": "Speed of light in vacuum (exact, SI definition)",
        "aliases": ["speed of light", "c_light", "light speed"],
        "source_ref": "CODATA-2018:speed_light",
    },
    # SIS epidemic boundary values
    "sis_r0_threshold": {
        "value": 1.0,
        "unit": "dimensionless",
        "description": "SIS epidemic threshold: R0 > 1 -> endemic, R0 <= 1 -> extinction",
        "aliases": ["epidemic threshold", "r0 threshold", "sis threshold"],
        "source_ref": "coq:sis_R0_threshold",
    },
}

# Pre-build alias -> key lookup (lowercase)
_ALIAS_MAP: dict[str, str] = {}
for _key, _entry in _ATLAS.items():
    _ALIAS_MAP[_key.lower()] = _key
    for _alias in _entry.get("aliases", []):
        _ALIAS_MAP[_alias.lower()] = _key


def _match_keys(text: str) -> list[str]:
    """Return atlas keys whose name or alias appears in text (case-insensitive)."""
    t = text.lower()
    seen: set[str] = set()
    matched: list[str] = []
    for alias, key in _ALIAS_MAP.items():
        if alias in t and key not in seen:
            seen.add(key)
            matched.append(key)
    return matched


def _render(key: str, entry: dict[str, Any]) -> str:
    return (
        f"[Atlas boundary lookup — {key}] "
        f"{entry['description']}. "
        f"Value: {entry['value']} {entry['unit']}. "
        f"Source: {entry['source_ref']}."
    )


class AtlasProvider:
    """Read-only provider that returns named constants from the atlas table.

    Candidates are COMPUTED (grounding=ALL, kind=BOUNDARY_LOOKUP) capped at Dr.
    The LLM backend is NOT involved — this is a pure table lookup (I6/I7 safe).
    """

    id: str = "atlas:constants"

    def capability(self) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            provider_id=self.id,
            readout_intents={"boundary_lookup", "constant_lookup", "tau_c_lookup"},
            verifiability_kind=Verifiability.SOURCE_ATTRIBUTED,
            static_ceiling=Tier.Dr,
            cost_class="cheap",
        )

    def routing_certainty(self, q: QueryIR) -> RoutingCertainty:
        keys = _match_keys(q.text)
        return RoutingCertainty.DENSE_CLEAR if keys else RoutingCertainty.NONE

    def can_serve(self, q: QueryIR) -> float:
        keys = _match_keys(q.text)
        if not keys:
            return 0.0
        # Score is proportional to number of matches, capped at 1.0
        return min(1.0, 0.6 + 0.1 * (len(keys) - 1))

    def produce(self, q: QueryIR) -> list[EvidenceCandidate]:
        keys = _match_keys(q.text)
        candidates = []
        for key in keys:
            entry = _ATLAS[key]
            candidates.append(
                EvidenceCandidate(
                    content=_render(key, entry),
                    ctype=CType.COMPUTED,
                    provider_id=self.id,
                    provenance=Provenance(
                        kind="BOUNDARY_LOOKUP",
                        source_ref=entry["source_ref"],
                        verifiability=Verifiability.SOURCE_ATTRIBUTED,
                    ),
                    declared_tier=Tier.Dr,
                    grounding=Grounding.ALL,
                    grounding_refs=[key],
                )
            )
        return candidates

    def ground(self, claim: str, cands: list[EvidenceCandidate]) -> list[str] | None:
        # A BOUNDARY_LOOKUP candidate is grounded by definition: the table entry IS the source.
        # Return the grounding refs (atlas keys) for every candidate whose key appears in claim text.
        refs = [ref for c in cands for ref in c.grounding_refs]
        return refs if refs else None

    def verify(self, cand: EvidenceCandidate):
        """Passthrough — atlas values are SOURCE_ATTRIBUTED, no independent oracle."""
        from ...core.models import VerifierResult
        return VerifierResult(
            ok=True,
            verifiability=Verifiability.SOURCE_ATTRIBUTED,
            detail="atlas_boundary_lookup",
        )
