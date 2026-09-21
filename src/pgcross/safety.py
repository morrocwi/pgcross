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


class ToxicBertNotInstalledError(ImportError):
    """Raised by `ClassifierSafety` when `transformers`/`torch` aren't importable. Never falls
    back to a silent pass -- see this module's FAILURE POLICY convention (same pattern as
    `decision/backend.py`'s `OpenThaiSystemOneNotInstalledError`): an unavailable classifier is a
    loud error, not an unsafe silent no-op."""

    def __init__(self, cause: Exception) -> None:
        super().__init__(
            "The 'transformers'/'torch' packages are not importable in this environment. "
            "ClassifierSafety uses unitary/toxic-bert (Apache-2.0) via the standard "
            "transformers text-classification pipeline. Install with:\n"
            "    pip install pgcross[safety]\n"
            "Model weights (~440MB, BERT-base) download from the Hugging Face Hub on first use "
            "(standard huggingface_hub caching)."
        )
        self.__cause__ = cause


class ClassifierSafety:
    """A real trained toxicity classifier (`unitary/toxic-bert`, Apache-2.0), layered ON TOP OF
    `_KeywordSafetyStub`'s catastrophic-category fast-path, combined by OR: either one flagging
    is enough to refuse.

    This is a genuine improvement over the keyword stub alone -- a trained model catches
    paraphrases and obfuscation a fixed keyword list cannot -- but it is explicitly NOT a
    substitute for red-teaming, and not a full replacement for the keyword stub either:
    `toxic-bert` targets generic online toxicity (`toxic`/`severe_toxic`/`obscene`/`threat`/
    `insult`/`identity_hate`), a different and narrower category set than the catastrophic risks
    (CSAM, weapons synthesis, self-harm methods) the keyword list exists to catch. Hence OR, not
    replace. PROVE-IT still applies in full: this combination has not been red-teamed, and
    `assert_serving_ready()`'s fail-closed startup gate treats any configured safety layer the
    same regardless of which kind it is -- presence proves nothing about quality.
    """

    def __init__(self, threshold: float = 0.5, model: str = "unitary/toxic-bert") -> None:
        self.threshold = threshold
        self.model_name = model
        self._pipe = None
        self._keyword = _KeywordSafetyStub()

    def _get_pipe(self):
        if self._pipe is not None:
            return self._pipe
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise ToxicBertNotInstalledError(exc) from exc
        self._pipe = pipeline(
            "text-classification", model=self.model_name, top_k=None, truncation=True
        )
        return self._pipe

    def __call__(self, text: str) -> bool:
        if self._keyword(text):  # fast catastrophic-category path first, no model call needed
            return True
        pipe = self._get_pipe()  # raises ToxicBertNotInstalledError, never silently passes
        scores = pipe(text)[0]  # list[{"label": str, "score": float}] for every label
        return any(s["score"] >= self.threshold for s in scores)


def make_safety(cfg: dict | None = None):
    """Factory for safety classifier from config.

    `cfg.get("kind")`: "keyword" (default -- see module docstring's PROVE-IT caveat) or
    "classifier" (`ClassifierSafety`, real trained model layered on top of the keyword stub;
    see that class's own docstring for what it does and does not cover). Neither is proven safe
    for production without red-teaming -- `assert_serving_ready()` only checks that SOME safety
    layer is present, never that it works.
    """
    kind = (cfg or {}).get("kind", "keyword")
    if kind == "classifier":
        return ClassifierSafety(threshold=(cfg or {}).get("threshold", 0.5))
    return _KeywordSafetyStub()
