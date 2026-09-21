# ground.py — slot extraction with synonym mapping, percentage normalisation, unicode support,
# and English/Thai spelled-out number recognition.
#
# Real bug found live 2026-09-21 by an adversarial red-team of a claim made about this project's
# own Decision Forge ("a deterministically-resolvable query never reaches the model"): this
# module's number regex (`_N` below) only ever recognized digit numerals ("3", "0.3") — a
# spelled-out equivalent ("three", "R0 equals three", "three tenths") failed to ground any slot,
# so the engine card fell back to a witness-less CLARIFY candidate, which then genuinely reached
# the DecisionBackend for a question that was, in fact, fully deterministic once the words were
# recognized. `_normalize_number_words()` below is a literal, deterministic text substitution
# (word span -> the digit string it spells) run BEFORE the existing digit-based patterns, so every
# existing pattern in `_SLOT_PATTERNS` keeps working unchanged -- this is still I7-compliant
# (reading a value already present in the text, in a different surface form, never inventing one).
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

# ── spelled-out number recognition (English + Thai) ──────────────────────────
# Longest-match-first word lists so e.g. "twenty" isn't eaten by a bare digit-word rule before
# the compound "twenty-one" pattern gets a chance, and so Thai's irregular "เอ็ด"/"ยี่สิบ" forms
# (not "หนึ่ง"/"สองสิบ") are matched instead of silently falling through.

_EN_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_EN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

_TH_DIGITS = {  # 0-9, used both standalone and after จุด (decimal point)
    "ศูนย์": 0, "หนึ่ง": 1, "สอง": 2, "สาม": 3, "สี่": 4, "ห้า": 5,
    "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9,
}
_TH_TENS = {  # standalone tens, 10-90 (สิบ alone = 10; ยี่สิบ is irregular for 20, not สองสิบ)
    "สิบ": 10, "ยี่สิบ": 20, "สามสิบ": 30, "สี่สิบ": 40, "ห้าสิบ": 50,
    "หกสิบ": 60, "เจ็ดสิบ": 70, "แปดสิบ": 80, "เก้าสิบ": 90,
}


def _en_compound_to_int(span: str) -> int | None:
    """'twenty one' / 'twenty-one' -> 21; a bare ones/teens/tens word -> its value."""
    words = re.split(r"[\s-]+", span.strip().lower())
    words = [w for w in words if w]
    if len(words) == 1:
        if words[0] in _EN_ONES:
            return _EN_ONES[words[0]]
        if words[0] in _EN_TENS:
            return _EN_TENS[words[0]]
        return None
    if len(words) == 2 and words[0] in _EN_TENS and words[1] in _EN_ONES and _EN_ONES[words[1]] < 10:
        return _EN_TENS[words[0]] + _EN_ONES[words[1]]
    return None


def _th_compound_to_int(span: str) -> int | None:
    """สิบเอ็ด -> 11; ยี่สิบสาม -> 23; a bare tens/digit word -> its value. No spaces in Thai
    compounds -- matched as a single token, split by known-prefix lookup instead of whitespace."""
    span = span.strip()
    if span in _TH_TENS:
        return _TH_TENS[span]
    if span in _TH_DIGITS:
        return _TH_DIGITS[span]
    for tens_word, tens_val in sorted(_TH_TENS.items(), key=lambda kv: -len(kv[0])):
        if span.startswith(tens_word):
            rest = span[len(tens_word):]
            if not rest:
                return tens_val
            if rest == "เอ็ด":  # irregular: "one" in a compound reads เอ็ด, never หนึ่ง
                return tens_val + 1
            if rest in _TH_DIGITS and _TH_DIGITS[rest] not in (0, 1):
                return tens_val + _TH_DIGITS[rest]
    return None


# Longest-first so "twenty-one"/"ยี่สิบเอ็ด" style compounds match before their shorter parts do.
_EN_NUMBER_WORD = "|".join(sorted(
    list(_EN_ONES) + list(_EN_TENS) + [f"{t}[\\s-]{o}" for t in _EN_TENS for o in _EN_ONES if _EN_ONES[o] < 10],
    key=len, reverse=True,
))
_TH_NUMBER_WORD = "|".join(sorted(
    list(_TH_DIGITS) + list(_TH_TENS)
    + [t + "เอ็ด" for t in _TH_TENS] + [t + d for t in _TH_TENS for d in _TH_DIGITS],
    key=len, reverse=True,
))

# "three tenths" / "one tenth" -> a decimal fraction; "half" -> 0.5. Common in this domain
# (beta/gamma are usually expressed as fractions in [0, 1]).
_EN_FRACTION_RE = re.compile(
    rf"\b(?:a\s+)?half\b|\b({_EN_NUMBER_WORD})\s+(tenths?|hundredths?)\b", re.IGNORECASE
)
_EN_INTEGER_RE = re.compile(rf"\b({_EN_NUMBER_WORD})\b", re.IGNORECASE)

# Thai decimal point reading: "ศูนย์จุดสาม" -> "0.3" (digits after จุด read one at a time, the
# standard Thai convention for reading a decimal, not as a compound number).
_TH_DECIMAL_RE = re.compile(
    rf"({_TH_NUMBER_WORD})จุด((?:{'|'.join(_TH_DIGITS)})+)"
)
_TH_INTEGER_RE = re.compile(rf"({_TH_NUMBER_WORD})")


def _normalize_number_words(text: str) -> str:
    """Replace recognized English/Thai spelled-out numbers with their digit-string equivalent.
    Order matters: fractions/decimals (longer, more specific spans) before bare integers, so
    "three tenths" becomes "0.3" rather than "3 tenths" (which no downstream pattern reads)."""

    def _en_fraction_sub(m: re.Match) -> str:
        if m.group(1) is None:  # matched bare "half"/"a half"
            return "0.5"
        n = _en_compound_to_int(m.group(1))
        unit = m.group(2).lower()
        if n is None:
            return m.group(0)
        denom = 100.0 if unit.startswith("hundredth") else 10.0
        return str(n / denom)

    text = _EN_FRACTION_RE.sub(_en_fraction_sub, text)

    def _en_integer_sub(m: re.Match) -> str:
        n = _en_compound_to_int(m.group(1))
        return str(n) if n is not None else m.group(0)

    text = _EN_INTEGER_RE.sub(_en_integer_sub, text)

    def _th_decimal_sub(m: re.Match) -> str:
        whole = _th_compound_to_int(m.group(1))
        frac_digits = [str(_TH_DIGITS[d]) for d in re.findall("|".join(_TH_DIGITS), m.group(2))]
        if whole is None or not frac_digits:
            return m.group(0)
        return f"{whole}.{''.join(frac_digits)}"

    text = _TH_DECIMAL_RE.sub(_th_decimal_sub, text)

    def _th_integer_sub(m: re.Match) -> str:
        n = _th_compound_to_int(m.group(1))
        return str(n) if n is not None else m.group(0)

    text = _TH_INTEGER_RE.sub(_th_integer_sub, text)
    return text


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
        # Real bug found and fixed live 2026-09-21 (adversarial red-team counterexample): the
        # three patterns above only accept a symbolic "="/":" connector, so "R0 equals 3" (or
        # any other word-connector phrasing) never matched even after _normalize_number_words()
        # converts "three" -> "3" -- a flexible connector, matching beta/gamma/lambda_max's own
        # convention, is needed for R0 too.
        (rf"R_?0{_FLEX}{_NP}", False),
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
    # Search lowercased first (ASCII keywords), then original (Unicode β γ λ Thai), then both of
    # those again with spelled-out English/Thai numbers converted to digits -- appended last so
    # digit input (the common case) is matched exactly as before this fix, unaffected.
    search_texts = [q.text.lower(), q.text]
    normalized = [_normalize_number_words(t) for t in search_texts]
    search_texts = search_texts + [t for t in normalized if t not in search_texts]

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
