"""policy/stakes.py — stakes classifier.

SPEC §10: classify_stakes(text) -> Stakes. Domain-keyword heuristic.
PROVE-IT: measure mis-classification on domain-evading queries before any production use.
"""
from __future__ import annotations
from ..core.enums import Stakes

_HIGH_STAKES_KEYWORDS = frozenset([
    # medicine / health — explicit advice or clinical framing
    "diagnosis", "diagnose", "treatment", "drug", "medication", "dose", "dosage",
    "symptom", "surgery", "emergency", "overdose", "poison",
    # medical context words — patient-setting indicators (no advice required)
    "patient", "hospital", "icu", "ward", "clinic", "clinician",
    "doctor", "physician", "disease", "outbreak", "containment",
    "public health", "epidem",
    # law / liability
    "legal", "lawsuit", "contract", "liability", "liable", "criminal",
    "court", "legislation", "attorney", "compliance",
    # finance / insurance / actuarial
    "invest", "investment", "stock", "bond", "derivative", "portfolio",
    "insurance", "underwriting", "underwriter", "actuarial", "premium",
    # safety-critical
    "safety", "hazard", "explosion", "structural", "nuclear", "chemical plant",
    # vulnerable persons
    "child", "minor", "abuse", "domestic violence", "self-harm", "suicide",
    # Thai medical terms (same keyword-match logic, no case in Thai)
    "คนไข้", "ผู้ป่วย", "โรงพยาบาล", "แพทย์", "การรักษา", "โรคระบาด",
])


def classify_stakes(text: str) -> Stakes:
    """Keyword-heuristic stakes classifier.

    Returns Stakes.HIGH if the text contains any high-stakes domain keyword,
    Stakes.LOW otherwise.

    PROVE-IT: this is a first-pass heuristic, not a calibrated classifier.
    Measure miss-rate on domain-evading queries.
    """
    t = text.lower()
    if any(k in t for k in _HIGH_STAKES_KEYWORDS):
        return Stakes.HIGH
    return Stakes.LOW
