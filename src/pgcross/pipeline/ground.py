# ground.py — slot extraction with synonym mapping, percentage normalisation, and unicode support.
#
# Two-tier extraction (I7 compliant — never invents values, only reads from text):
#   Tier 1: exact keyword/symbol match  (beta, γ, lambda_max, ...)
#   Tier 2: natural-language synonym    ("infection rate 0.3", "recovery probability is 0.1", ...)
# Connector strategy: a single lazy flexible separator "[^0-9.\n]{0,50}?" between phrase and value.
#   This handles any connector in any language (is, =, :, เท่ากับ, คือ, comes out to, …)
#   without hard-coding them, and always latches to the FIRST number after the phrase.
# Percentage normalisation: "30%" → 0.30 (% suffix attached to number, or reverse pattern).
# Both lowercased and original text are searched so that unicode Greek/Thai stays intact.
import re
from ..core.models import QueryIR

# ── numeric primitives ───────────────────────────────────────────────────────
_N  = r"([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)"   # plain number
_NP = _N + r"(\s*%)?"                              # number with optional % suffix

# Lazy, language-agnostic separator: skip up to 50 non-digit/non-dot/non-newline chars.
# Never crosses a sentence boundary (no \n) and stops at the first digit (lazy ?)
_FLEX = r"[^0-9.\n]{0,50}?"

# Reverse-percentage anchor: "<number>% <synonym>" — e.g. "30% infection rate"
_RP_N = r"([0-9]*\.?[0-9]+)"                      # capture for reverse-% patterns

# ── hedge guard (I2 — never ground an explicitly uncertain value) ────────────
# Words that signal the speaker is estimating, not stating a literal value.
# If the full regex match contains any of these, skip extraction.
_HEDGES = frozenset([
    "presumably", "approximately", "roughly", "typically", "generally",
    "around", "about", "maybe", "perhaps", "probably", "suppose",
    "estimate", "guess", "typical", "general knowledge", "based on",
    "ish", "say ", "some", "would be", "could be",
])

def _is_hedged(match_text: str) -> bool:
    t = match_text.lower()
    return any(h in t for h in _HEDGES)

# ── synonym tables ───────────────────────────────────────────────────────────
# Format: (pattern, is_reverse_pct)
#   is_reverse_pct=True  → the number precedes the phrase and is already a %;
#                          divide by 100, group(1) is the raw integer/float.
#   is_reverse_pct=False → group(1)=number, group(2)="%"|None; apply pct if "%".
_SLOT_PATTERNS: dict[str, list[tuple[str, bool]]] = {
    # R0 must come first — HIT card reads it directly; also prevents beta/gamma patterns
    # from accidentally consuming a stated R0 value before the HIT card can use it.
    "R0": [
        (rf"R0\s*[=:]\s*{_NP}", False),
        (rf"R_?0\s*[=:]\s*{_NP}", False),
        (rf"(?:basic\s+)?reproduction\s+(?:number|ratio)\s*(?:is|=|:)?\s*{_NP}", False),
    ],
    "beta": [
        # exact symbol (β or beta)
        (rf"(?:beta|β){_FLEX}{_NP}", False),
        # reverse % BEFORE forward — "30% infection rate" wins over "infection rate ... 15%"
        # because the flexible separator can accidentally skip an "and" to grab the wrong number.
        (rf"{_RP_N}\s*%\s*(?:infection|transmission|contact|spreading)\s*(?:rate|probability)?", True),
        # forward synonym: "infection rate <connector> <num>%?"
        (rf"(?:infection|transmission|contact|spreading)\s*(?:rate|probability|chance|prob)?{_FLEX}{_NP}", False),
        # Thai forward
        (rf"(?:อัตราการติดเชื้อ|อัตราการแพร่เชื้อ)\s*(?:\(beta\))?{_FLEX}{_NP}", False),
    ],
    "gamma": [
        (rf"(?:gamma|γ){_FLEX}{_NP}", False),
        # reverse % before forward (same reason as beta)
        (rf"{_RP_N}\s*%\s*(?:recovery|removal)\s*(?:rate|probability)?", True),
        # "10% of infected people recover per day" — bare verb, flexible connector up to 30 chars
        (rf"{_RP_N}\s*%[^%\n]{{0,30}}?recov", True),
        # "recovery rate", "recover at rate", "people recover at" — bare "recover" included
        (rf"(?:recover[a-z]*|removal|cure)\s*(?:rate|probability|chance|prob|at)?{_FLEX}{_NP}", False),
        (rf"(?:อัตราการหายป่วย|อัตราการฟื้นตัว)\s*(?:\(gamma\))?{_FLEX}{_NP}", False),
    ],
    "lambda_max": [
        # exact symbols first
        (rf"(?:lambda_max|lambda\s+max|λmax|λ_max){_FLEX}{_NP}", False),
        # standalone λ (must come after λmax to avoid partial match eating λmax)
        (rf"λ{_FLEX}{_NP}", False),
        # spectral radius variants
        (rf"(?:network\s+)?spectral\s+radius(?:\s*\(dominant\s+eigenvalue\))?{_FLEX}{_NP}", False),
        # eigenvalue synonyms: "dominant", "biggest", "largest", "maximum", "principal"
        (rf"(?:dominant|biggest|largest|maximum|principal|leading)\s+eigenvalue{_FLEX}{_NP}", False),
        # adjacency matrix eigenvalue phrasing
        (rf"eigenvalue\s+of\s+(?:the\s+)?(?:\w+\s+){0,4}(?:matrix|graph|network){_FLEX}{_NP}", False),
    ],
}


def _to_float(m: re.Match, is_reverse_pct: bool) -> float | None:
    groups = [g for g in m.groups() if g is not None]
    if not groups:
        return None
    try:
        val = float(groups[0])
    except ValueError:
        return None
    if is_reverse_pct:
        val /= 100.0
    elif len(groups) > 1 and "%" in groups[1]:
        val /= 100.0
    return val


def content_terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z_]{3,}", text.lower())
            if w not in {"the", "and", "is", "above", "below", "what", "does", "this"}]


def ground(q: QueryIR, backend) -> QueryIR:
    # Search lowercased first (ASCII keywords), then original (Unicode β γ λ Thai).
    search_texts = [q.text.lower(), q.text]

    for slot, patterns in _SLOT_PATTERNS.items():
        if slot in q.slots:
            continue
        for rx, is_rev_pct in patterns:
            for text in search_texts:
                m = re.search(rx, text, re.IGNORECASE)
                if m:
                    if _is_hedged(m.group(0)):
                        continue  # hedge detected — speaker is estimating, not stating
                    val = _to_float(m, is_rev_pct)
                    if val is not None:
                        q.slots[slot] = val
                        q.grounding_map[slot] = m.group(0).strip()
                        break
            if slot in q.slots:
                break

    q.retrieval_terms = content_terms(q.text)
    return q
    # ▸ NOTE (I7): every value here was READ from q.text — the backend is never
    #   asked to propose or invent a slot value. Backend-suggested values must be
    #   marked UNGROUNDED so grounding_cap caps them at Open tier.
