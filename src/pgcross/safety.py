"""safety.py — Fail-closed safety placeholder.

SPEC §9: The shipped module is a PLACEHOLDER that raises NotImplementedError.
assert_serving_ready() (pipeline/run.py) refuses to serve when ctx.safety is None
unless allow_unsafe_dev=True.

A keyword list is NOT a safety layer and cannot catch child-safety or other serious harms.
PROVE-IT safety: red-team the refusal path before any external distribution.
"""
from __future__ import annotations


class _KeywordSafetyStub:
    """Keyword-based stub. Catches obvious cases ONLY.
    REQUIRED: replace with a real classifier before external distribution.
    PROVE-IT: red-team this before any production use.
    """
    _KEYWORDS = [
        "bomb", "explosive", "weapon of mass", "child pornography",
        "cp ", "csam", "how to kill", "suicide method", "self-harm method",
        "synthesize meth", "make fentanyl", "synthesize nerve agent",
    ]

    def __call__(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self._KEYWORDS)


def make_dev_safety() -> _KeywordSafetyStub:
    """Returns keyword-only stub. For dev/internal use only.
    PROVE-IT: this is NOT a production safety layer.
    """
    return _KeywordSafetyStub()


def make_safety(cfg: dict | None = None):
    """Factory for safety classifier from config.
    Currently returns the keyword stub — replace with a real classifier.
    """
    return _KeywordSafetyStub()
