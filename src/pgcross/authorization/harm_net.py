"""authorization/harm_net.py — independent, query-level harm-intent net + DANGER/ADVISORY/WEAKNESS
taxonomy, ported from the legacy `humane_gate.py` (Stream 3 step 5, internal task-tracking
notes, item 23).

**Split rationale (documented per the task's "your call on the cleanest split"):** the harm-pattern
regex set is a self-contained, N12/RAG-agnostic piece of `humane_gate.py` — it does not touch
`rag_solver`/`byo`/`answer_policy`/`bundle` at all (see `humane_gate.py`'s own docstring: "does NOT
rely on N12's keyword list"). Splitting it into its own sibling module keeps `authorization/policy.py`
focused on the witness-before-model / resolution-gate / forged-tier concerns (Stream 3 step 4) and
lets this module's regex-parity claim be tested in isolation, with its own dedicated diff test
against the source `humane_gate.py` lists.

**What was ported, and what was deliberately NOT ported:**
  - `_HARM_PATTERNS`, `_HARM_BROAD`, `_BENIGN_CONTEXT` (the independent harm-intent regex net) are
    ported with 100% pattern-string parity to `humane_gate.py` — see
    `tests/test_admit_hold_reject_escalate.py`'s programmatic diff against `humane_gate.py`'s own
    module-level tuples. Below, the patterns are grouped into `_SELF_HARM_PATTERNS` (self-harm/
    suicide ideation+intent+method, EN+TH) and `_OTHER_HARM_PATTERNS` (harm-to-others/weapons/
    dangerous-synthesis) instead of `humane_gate.py`'s single interleaved `_HARM_PATTERNS` tuple —
    this is a REGROUPING for `classify_danger_subtype()` below (§ REJECT-vs-ESCALATE), not a content
    change: `set(p.pattern for p in _HARM_PATTERNS)` is byte-identical to the source's set (order does
    not matter for the `any()` matching either module performs; only the pattern SET is claimed
    identical, and that is exactly what the parity test asserts).
  - `is_harmful()` is ported verbatim in logic (strong patterns always fire; the broad
    'suicid'/'overdose' stems fire unless `_BENIGN_CONTEXT` matches).
  - `_high_risk_domains()` / `pgcross_universal.config.HIGH_RISK_DOMAINS` is **NOT** ported — per the
    task spec, that is a fourth divergent stakes list referenced only by the original `humane_gate.py`
    and explicitly excluded from this migration. `classify_harm_taxonomy()` below reads stakes from
    `policy/stakes.py`'s `classify_stakes()` instead (the single canonical stakes source, per the
    project's internal task-tracking notes, Phase 3 item 20's reconciliation).
  - `_DANGER_MARKERS`/`_ADVISORY_MARKERS`/`WEAKNESS_MARKERS`/`SAFETY_MARKERS` (N12 guardrail
    *reason-string* substrings, e.g. `"harm_content_detected"`, `"turbulent_retrieval"`) are **NOT**
    ported — those markers only exist because the legacy `sol.reasons` came from N12's
    `rag_solver.solve()`, which does not exist on the live engine-card pipeline (Phase A audit,
    per the project's internal architecture audit notes: N12/N14 RAG-bundle is dead weight
    relative to the live path).
    `classify_harm_taxonomy()` below is a genuine rewrite against live inputs (free text / a
    `Candidate`/`EvidenceCandidate`-shaped object's `.content`), not a reason-string classifier.

Maintainer-confirmed mapping this module's taxonomy feeds into `authorization/policy.py`'s
`classify_and_authorize()` (project's internal task-tracking notes, Phase 0 item 5, RESOLVED
2026-09-21):
    DANGER   -> REJECT/ESCALATE (never self-authorized, always REFER_TO_HUMAN + crisis bridge)
    ADVISORY -> ADMIT-with-caution (opinion + explicit consult-a-human caveat, never blanket-refused)
    WEAKNESS -> HOLD (pending further evidence)
"""
from __future__ import annotations

import re

from ..core.enums import Stakes
from ..policy.stakes import classify_stakes

__all__ = [
    "is_harmful",
    "is_self_harm",
    "is_other_harm",
    "classify_harm_taxonomy",
    "classify_danger_subtype",
]

# ── self-harm / suicide (EN) — ideation, intent, AND method phrasings, verbatim from
# humane_gate.py's _HARM_PATTERNS lines 44-66 (the method verbs are the gap a code review caught
# there: N12 misses them and weak retrieval would otherwise author a harmful answer). ─────────────────
_SELF_HARM_PATTERNS_EN = (
    r"\bkill(ing)?\s+(my|your|him|her|them|one)\s*sel(f|ves)",
    r"\bend(ing)?\s+(my|your|his|her|their|one'?s)\s+life",
    r"\btak(e|ing)\s+(my|your|his|her|their)\s+(own\s+)?life",
    r"\b(want|wanna|going|how)\s+(to\s+)?die\b",
    r"\bhow\s+(can|do|should)\s+i\s+die\b",
    r"\bways?\s+to\s+(die|kill\s+myself|end\s+it)\b",
    r"\bpainless\s+(way|death|method|suicide)",
    r"\bself[\s-]?harm",
    r"\b(hurt|harm|cut)\s+(my|your)\s*sel(f|ves)",
    r"\bend\s+it\s+all\b",
    # method phrasings + common evasion ("unalive"); err toward catching (a false positive only
    # degrades to REFER_TO_HUMAN + options, never to a harmful answer).
    r"\bhang(ing)?\s+(my|your)\s*sel(f|ves)\b",
    r"\bshoot\s+(my|your)\s*sel(f|ves)\b",
    r"\b(slit|cut)\s+(my|your)\s+wrist",
    r"\bdrown\s+(my|your)\s*sel(f|ves)\b",
    r"\b(jump|leap)\s+(off|from)\b[^.\n]{0,30}\b(bridge|building|roof|window|cliff|die|death)\b",
    r"\bwant(ing)?\s+to\s+be\s+dead\b",
    r"\bwish\s+i\s+(was|were)\s+dead\b",
    r"\b(don'?t|do\s*not|dont)\s+want\s+to\s+(be\s+alive|live|exist)\b",
    r"\boff\s+myself\b",
    r"\bunalive\b",
    r"\bend\s+my\s+(own\s+)?existence\b",
)

# harm to others / weapons / dangerous synthesis — verbatim from humane_gate.py lines 67-74
# (defense-in-depth; N12 also covers some in the legacy system, but this net is independent of it).
_OTHER_HARM_PATTERNS_EN = (
    r"\bhow\s+(to|do\s+i|can\s+i)\s+(make|build|create)\s+(a\s+)?(bomb|explosive|weapon|poison|gun)",
    r"\bhow\s+(to|do\s+i|can\s+i)\s+(kill|murder|poison|harm)\s+(a\s+)?(person|people|someone|him|her|them)",
    r"\b(synthesi[sz]e|manufactur|cook)\s+(meth|fentanyl|explosive|nerve\s+agent)",
    # named chemical/bio agents + an action verb (intent-anchored so 'ricin is a toxin' stays benign)
    r"\b(make|build|create|extract|purify|synthesi[sz]e|produce|weaponi[sz]e|cook)\b[^.\n]{0,30}"
    r"\b(ricin|sarin|vx\s+nerve|nerve\s+agent|anthrax|mustard\s+gas|chlorine\s+gas|thermite|napalm|"
    r"bioweapon|chemical\s+weapon)\b",
)

# self-harm / suicide (TH) — verbatim from humane_gate.py lines 76-89.
_SELF_HARM_PATTERNS_TH = (
    r"ฆ่าตัวตาย",
    r"ฆ่าตัวเอง",
    r"อยากตาย",
    r"จบชีวิต(ตัวเอง)?",
    r"ทำร้ายตัวเอง",
    r"วิธี(การ)?ตาย",
    r"กินยา.{0,10}(ตาย|เกินขนาด)",            # take pills to die / overdose
    r"ยาเกินขนาด",
    r"ผูกคอ",                                  # hang
    r"กรีดข้อมือ",                              # cut wrist
    r"(โดด|กระโดด)(ตึก|สะพาน|น้ำ)",            # jump off building/bridge/into water
    r"ไม่อยาก(มีชีวิต|อยู่)",                    # don't want to live
    r"อยากหายไป",                              # want to disappear
    r"เบื่อชีวิต",                              # tired of life
)

_SELF_HARM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (_SELF_HARM_PATTERNS_EN + _SELF_HARM_PATTERNS_TH)
)
_OTHER_HARM_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in _OTHER_HARM_PATTERNS_EN)

# Full union, in humane_gate.py's ORIGINAL interleaved order (EN self-harm, other-harm, TH
# self-harm) — kept for the parity test's set-equality diff against humane_gate.py's own
# `_HARM_PATTERNS`. `is_harmful()` below does not depend on this tuple's order.
_HARM_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (_SELF_HARM_PATTERNS_EN + _OTHER_HARM_PATTERNS_EN + _SELF_HARM_PATTERNS_TH)
)

# Broad bare stems (self-harm-related): high-recall but also match academic/entertainment use
# ('suicide statistics', 'Suicide Squad', 'overdose deaths report'). Verbatim from humane_gate.py.
_HARM_BROAD = tuple(re.compile(p, re.IGNORECASE) for p in (r"\bsuicid", r"\boverdos(e|ing)\b"))
_BENIGN_CONTEXT = re.compile(
    r"\b(squad|prevention|hotline|helpline|awareness|campaign|statistic|statistics|rate|rates|"
    r"epidemiolog\w*|epidemic|movie|film|documentary|series|novel|song|lyric|book|history|memorial|"
    r"naloxone)\b",
    re.IGNORECASE,
)

# Residual evasions NOT covered (documented, not hidden, per humane_gate.py's own note): leetspeak
# (su1c1de), letter-spacing (s u i c i d e). These need input normalization — a follow-up.


def is_self_harm(query: str) -> bool:
    """True if `query` matches a self-harm/suicide pattern — strong intent/method patterns always
    fire; the broad 'suicid'/'overdose' stems fire unless a benign (academic/entertainment)
    context is present. Ported logic from `humane_gate.is_harmful()`, restricted to the self-harm
    pattern subset (this module's regrouping — see module docstring)."""
    q = query or ""
    if any(p.search(q) for p in _SELF_HARM_PATTERNS):
        return True
    if any(p.search(q) for p in _HARM_BROAD) and not _BENIGN_CONTEXT.search(q):
        return True
    return False


def is_other_harm(query: str) -> bool:
    """True if `query` matches a harm-to-others/weapons/dangerous-synthesis pattern."""
    q = query or ""
    return any(p.search(q) for p in _OTHER_HARM_PATTERNS)


def is_harmful(query: str) -> bool:
    """Independent, N12-agnostic harm-intent detector (EN+TH), ported verbatim in logic from
    `humane_gate.is_harmful()`: True ⇒ force DANGER regardless of any other classification.
    Equivalent to `is_self_harm(query) or is_other_harm(query)`."""
    return is_self_harm(query) or is_other_harm(query)


def classify_danger_subtype(query: str) -> str:
    """`"SELF_HARM"` | `"OTHER_HARM"` — only meaningful when `is_harmful(query)` is True.

    This is the concrete rule `authorization/policy.py`'s `classify_and_authorize()` uses to pick
    REJECT vs ESCALATE within the maintainer-confirmed DANGER -> REJECT/ESCALATE mapping (the mapping
    itself names both outcomes as acceptable for DANGER without further specifying which; this
    function supplies the missing discriminator, documented rather than left implicit):
    self-harm/suicide content ⇒ `ESCALATE` (a human + the crisis bridge, per `humane_gate.py`'s own
    `_CRISIS_OPTION` discipline, ported forward — this is a person in potential crisis, not merely a
    disallowed request); harm-to-others/weapons/dangerous-synthesis content ⇒ `REJECT` (the request
    itself must not be fulfilled; no crisis-bridge referral applies to e.g. "how do I make a bomb").
    If somehow neither sub-pattern matched (should not happen when `is_harmful()` was already True,
    since it is exactly `is_self_harm or is_other_harm`), this defaults to the more conservative
    `"SELF_HARM"` (⇒ ESCALATE) rather than silently under-reacting.
    """
    if is_self_harm(query):
        return "SELF_HARM"
    if is_other_harm(query):
        return "OTHER_HARM"
    return "SELF_HARM"


def classify_harm_taxonomy(text: str) -> str:
    """`"DANGER"` | `"ADVISORY"` | `"WEAKNESS"` — three-way taxonomy ported from
    `humane_gate.classify()`, rewritten against live inputs (free text, not N12 `sol.reasons`
    strings) and reading stakes from `policy/stakes.py`'s `classify_stakes()` (the single canonical
    stakes source per the project's internal task-tracking notes, Phase 3 item 20) instead of the
    original's
    `pgcross_universal.config.HIGH_RISK_DOMAINS` (a fourth divergent list, deliberately not ported —
    see module docstring).

    DANGER   — a harmful request (self-harm/weapons/violence/dangerous-synthesis). Must NOT be
               answered as a plain admit → refer (see `classify_danger_subtype()` for the
               REJECT-vs-ESCALATE split). Gated by the independent harm net FIRST, exactly as in
               `humane_gate.classify()`'s own default-DENY-for-harm ordering.
    ADVISORY — high-stakes content per `classify_stakes(text) == Stakes.HIGH` (medical/legal/
               financial/safety-critical/vulnerable-persons keywords, EN+TH — see
               `policy/stakes.py`). ANSWER it as the AI's opinion + point to a qualified human.
    WEAKNESS — everything else: benign content, or content whose evidence/resolution status is not
               yet settled. Pending further evidence, not a hard refusal.

    Unknown/unmatched content defaults to WEAKNESS, matching `humane_gate.classify()`'s own
    documented default (danger is already caught first by the harm net; ADVISORY only for explicit
    high-stakes content — so a benign unknown isn't wrongly labelled high-stakes either).
    """
    if is_harmful(text):
        return "DANGER"
    if classify_stakes(text) == Stakes.HIGH:
        return "ADVISORY"
    return "WEAKNESS"
