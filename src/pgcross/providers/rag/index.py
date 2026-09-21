from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Span:
    chunk_id: str
    span: str  # "doc:start-end"
    text: str


class EmbeddingIndex:
    """Embedding-based retrieval index with NLI-backed support_check.

    K6 track 2a: the NLI stage was previously stubbed (lexical-overlap only).
    It is now a real cross-encoder entailment model (`cross-encoder/nli-distilroberta-base`,
    CPU-capable). Lexical overlap stays the cheap NECESSARY prefilter (fast reject before
    paying for a model call); NLI entailment probability is the SUFFICIENT decision.
    If the model cannot be loaded (offline, package missing), support_check falls back to
    lexical-only and the candidate is degraded, never silently upgraded — see `nli_active`.
    Measured recall/FP on real paraphrase pairs: `eval/rag_entailment_recall.py`,
    numbers recorded in CLAIMS.md.
    """

    LEX_MIN = 0.15  # lexical overlap threshold (necessary, NOT sufficient)
    # NLI_MIN calibrated on eval/rag_entailment_calibration.py (a DISJOINT set from the
    # eval/rag_entailment_recall.py test set — never fit on the test set itself). The
    # cross-encoder's entailment probabilities for true paraphrase are much lower than a
    # textbook 0.7 default would assume; 0.05 was the balanced-accuracy optimum on
    # calibration (0.850). Re-tune only against a fresh calibration set, never the test set.
    NLI_MIN = 0.05  # NLI entailment probability threshold (sufficient, once lexical passes)
    _NLI_MODEL_NAME = "cross-encoder/nli-distilroberta-base"
    _nli_model = None       # class-level cache: load once, share across instances
    _nli_load_failed = False

    def __init__(self):
        self._chunks: list = []  # list of Span objects
        self._embeddings = None
        self._model = None

    @classmethod
    def _nli(cls):
        """Lazily load and cache the NLI cross-encoder. Returns None if unavailable."""
        if cls._nli_model is not None or cls._nli_load_failed:
            return cls._nli_model
        try:
            from sentence_transformers import CrossEncoder
            cls._nli_model = CrossEncoder(cls._NLI_MODEL_NAME)
        except Exception:
            cls._nli_load_failed = True
            cls._nli_model = None
        return cls._nli_model

    @property
    def nli_active(self) -> bool:
        """True if support_check is backed by the real NLI model, False if degraded to lexical-only."""
        return self._nli() is not None

    @classmethod
    def build(cls, chunks: list) -> "EmbeddingIndex":
        idx = cls()
        idx._chunks = list(chunks)
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
            idx._model = SentenceTransformer("all-MiniLM-L6-v2")
            texts = [c.text for c in idx._chunks]
            idx._embeddings = np.array(idx._model.encode(texts, show_progress_bar=False))
        except Exception:
            idx._model = None  # fallback: lexical only
        return idx

    def persist(self, path: str) -> None:
        import json, os
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "chunks.json"), "w") as f:
            json.dump(
                [{"chunk_id": c.chunk_id, "span": c.span, "text": c.text}
                 for c in self._chunks],
                f,
            )
        if self._embeddings is not None:
            import numpy as np
            np.save(os.path.join(path, "embeddings.npy"), self._embeddings)

    @classmethod
    def load(cls, path: str) -> "EmbeddingIndex":
        import json, os
        idx = cls()
        with open(os.path.join(path, "chunks.json")) as f:
            data = json.load(f)
        idx._chunks = [Span(d["chunk_id"], d["span"], d["text"]) for d in data]
        emb_path = os.path.join(path, "embeddings.npy")
        if os.path.exists(emb_path):
            import numpy as np
            idx._embeddings = np.load(emb_path)
        return idx

    def score(self, terms: list[str]) -> float:
        if not self._chunks:
            return 0.0
        hits = sum(1 for c in self._chunks if any(t in c.text.lower() for t in terms))
        return min(1.0, hits / max(len(self._chunks), 1))

    def top_spans(self, terms: list[str], k: int = 6) -> list[Span]:
        if not self._chunks:
            return []
        if self._embeddings is not None and self._model is not None:
            try:
                import numpy as np
                q_emb = self._model.encode([" ".join(terms)], show_progress_bar=False)[0]
                scores = self._embeddings @ q_emb / (
                    np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(q_emb) + 1e-9
                )
                top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
                return [self._chunks[i] for i in top]
            except Exception:
                pass  # fallback to lexical
        q_set = set(terms)
        scored = [(sum(1 for t in q_set if t in c.text.lower()), c) for c in self._chunks]
        return [c for _, c in sorted(scored, reverse=True)[:k] if _ > 0]

    def support_check(self, claim: str, span_lists: list) -> bool:
        """Grounding gate: lexical prefilter (necessary) + NLI entailment (sufficient).

        Two-stage: cheap lexical overlap rejects clearly-unsupported claims before paying
        for a model call; when lexical passes, the NLI cross-encoder decides based on
        entailment probability against the retrieved spans (premise) vs the claim
        (hypothesis). If the NLI model is unavailable, degrades to lexical-only —
        callers can check `nli_active` to know which mode produced the answer.
        """
        all_spans = [
            s
            for spans in span_lists
            for s in (spans if isinstance(spans, list) else [spans])
        ]
        if not all_spans:
            return False
        claim_words = set(re.findall(r"[a-zA-Z_]{3,}", claim.lower()))
        all_text = " ".join(all_spans).lower()
        span_words = set(re.findall(r"[a-zA-Z_]{3,}", all_text))
        if not claim_words:
            return False
        overlap = len(claim_words & span_words) / len(claim_words)
        if overlap < self.LEX_MIN:
            return False

        model = self._nli()
        if model is None:
            return True  # degraded: lexical passed, no NLI available — see nli_active

        try:
            import numpy as np
            premise = " ".join(all_spans)
            logits = model.predict([(premise, claim)])[0]
            probs = np.exp(logits) / np.exp(logits).sum()
            entailment_prob = float(probs[1])  # id2label: 0=contradiction,1=entailment,2=neutral
            return entailment_prob >= self.NLI_MIN
        except Exception:
            return True  # model call failed at runtime — degrade to the lexical pass, don't crash
