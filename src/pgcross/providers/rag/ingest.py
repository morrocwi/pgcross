from __future__ import annotations
import os
import uuid
import re
from dataclasses import dataclass

from .index import EmbeddingIndex, Span
from .corpus import RagCorpusProvider
from ...core.enums import Tier


@dataclass
class Chunk:
    corpus_id: str
    chunk_id: str
    span: str
    text: str
    source_name: str


def _load_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            return " ".join(p.extract_text() or "" for p in reader.pages)
        except ImportError:
            raise ImportError("pypdf required for PDF ingestion: pip install pgcross[rag]")
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _load_dir(path: str) -> list[tuple[str, str]]:
    """Return list of (name, text) for all supported files under path."""
    SUPPORTED = {".txt", ".md", ".pdf", ".html", ".htm"}
    results = []
    if os.path.isfile(path):
        results.append((os.path.basename(path), _load_file(path)))
        return results
    for root, _dirs, files in os.walk(path):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED:
                fpath = os.path.join(root, fname)
                try:
                    results.append((fname, _load_file(fpath)))
                except Exception as e:
                    import logging
                    logging.getLogger("pgcross.ingest").warning("skip %s: %s", fpath, e)
    return results


def _sliding_window(
    text: str, chunk_tokens: int = 400, overlap: int = 40
) -> list[tuple[int, int, str]]:
    """Yield (start_word_idx, end_word_idx, text) windows."""
    words = text.split()
    chunks = []
    step = max(1, chunk_tokens - overlap)
    for start in range(0, len(words), step):
        window = words[start : start + chunk_tokens]
        if len(window) < 20:
            continue  # skip tiny trailing chunks
        chunks.append((start, start + len(window), " ".join(window)))
    return chunks


def _corpus_dir(corpus_id: str) -> str:
    """Return the default on-disk path for a corpus."""
    base = os.environ.get("PGCROSS_CORPORA_DIR", os.path.expanduser("~/.pgcross/corpora"))
    return os.path.join(base, corpus_id)


# Authority label -> Tier mapping (mirrors tiers.yaml)
_AUTHORITY_MAP: dict[str, Tier] = {
    "peer_reviewed": Tier.Dr,
    "curated": Tier.Wf,
    "web": Tier.Open,
}


def authority_ceiling_from_label(label: str) -> Tier:
    """Convert a human authority label to a Tier ceiling.

    Accepts 'peer_reviewed', 'curated', or 'web' (mirrors policy/defaults/tiers.yaml).
    """
    label = label.lower().strip()
    if label not in _AUTHORITY_MAP:
        raise ValueError(
            f"Unknown authority label '{label}'. "
            f"Valid choices: {list(_AUTHORITY_MAP)}"
        )
    return _AUTHORITY_MAP[label]


def ingest(
    path: str,
    corpus_id: str,
    authority_ceiling: Tier | str,
    chunk_tokens: int = 400,
    overlap: int = 40,
    persist_dir: str | None = None,
) -> RagCorpusProvider:
    """Load files from path, chunk, embed, persist, and return a RagCorpusProvider.

    Parameters
    ----------
    path:
        File or directory. Supported extensions: .txt .md .pdf .html/.htm
    corpus_id:
        Unique identifier for this corpus (used as storage key and provider id).
    authority_ceiling:
        Tier or label string ('peer_reviewed'/'curated'/'web') bounding how high
        a retrieved chunk can be tiered regardless of verifiability.
    chunk_tokens:
        Target window size in whitespace-split tokens.
    overlap:
        Token overlap between adjacent windows (prevents boundary-split misses).
    persist_dir:
        Override the on-disk location (defaults to ~/.pgcross/corpora/<corpus_id>).

    Returns
    -------
    RagCorpusProvider ready to register with the pipeline Registry.
    """
    if isinstance(authority_ceiling, str):
        authority_ceiling = authority_ceiling_from_label(authority_ceiling)

    docs = _load_dir(path)
    if not docs:
        raise ValueError(f"No supported files found under '{path}'")

    chunks: list[Chunk] = []
    for source_name, text in docs:
        for start, end, window_text in _sliding_window(text, chunk_tokens, overlap):
            chunk_id = str(uuid.uuid4())
            span = f"{source_name}:{start}-{end}"
            chunks.append(Chunk(corpus_id, chunk_id, span, window_text, source_name))

    # Build embedding index from Span objects (EmbeddingIndex only needs .chunk_id/.span/.text)
    spans = [Span(c.chunk_id, c.span, c.text) for c in chunks]
    index = EmbeddingIndex.build(spans)

    out_dir = persist_dir or _corpus_dir(corpus_id)
    index.persist(out_dir)

    return RagCorpusProvider(corpus_id, index, authority_ceiling)


def load_persisted(
    corpus_id: str,
    authority_ceiling: Tier | str,
    persist_dir: str | None = None,
) -> RagCorpusProvider:
    """Reload a previously persisted corpus without re-ingesting."""
    if isinstance(authority_ceiling, str):
        authority_ceiling = authority_ceiling_from_label(authority_ceiling)
    in_dir = persist_dir or _corpus_dir(corpus_id)
    index = EmbeddingIndex.load(in_dir)
    return RagCorpusProvider(corpus_id, index, authority_ceiling)
