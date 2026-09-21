"""authorization/policy.py — Witness-before-Model rule + resolution gate.

Stream 3 step 4 (project's internal task-tracking notes, item 17, Phase 2). **PURE FUNCTIONS ONLY — no interaction
with the live pipeline yet.** Nothing here is wired into `pipeline/*.py`, `server/*.py`, or any
`DecisionBackend` call; that wiring is later Phase 2/3 work.

Toledo-verified primitives this module is grounded in (looked up, not assumed — per
`EPIS-TOLEDO-FIRST`/`EPIS-REUSE-PIPELINE`; statements as registered, also quoted in the
project's architecture design notes §1/§2.3/§2.4/§2.5, which was read in full before writing
this file):

    A3          `P(X) <=> exists w finite: check(X,w)=top` (untagged root) — existence-as-
                decision: no witness ⇒ HOLD, never a guess.
    A3/M.01.v1  `witness_sound`   (Th_coqc) `decide check bound = true -> exists w, w<bound /\\
                                              check w = true`
    A3/M.02.v1  `witness_complete`(Th_coqc) `w<bound -> check w=true -> decide check bound = true`
    A3/M.06.v1  `decide_reflect`  (Th_coqc) soundness+completeness combined
    D/M.65.v1   `neutral_distinct_from_bottom` (Th_coqc) `Sz <> Sbot` — already enforced as the
                real, non-collapsible `core/s4.py::S4` algebra this module imports and returns.
    D/M.77.v1   `bot_monotone_in_floor` (Th_coqc)
                `0<=f1 -> f1<=f2 -> classify f1 v = Sbot -> classify f2 v = Sbot`
                "coarsening the resolution floor can only ever GROW the unresolved region, never
                shrink it" — this is what licenses `resolution_gate`'s cheap-check → refine →
                HOLD-if-still-⊥ early exit as SOUND, not merely fast (§2.5 of the same doc).

This is the concrete "Witness before Model" gate from the project's architecture design notes
§2.3/§4 item 1: a gate only reaches a `DecisionBackend` call if (a) no finite witness/check
resolves it AND (b) the resolution gate still classifies it `S4.BOT` after its refine budget is
exhausted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..core.enums import Tier, Verifiability
from ..core.s4 import S4
from ..core.tiering import verifiability_ceiling
from ..decision.schema import AuthorizationStatus
from .harm_net import classify_danger_subtype, classify_harm_taxonomy

__all__ = [
    "TraceEntry",
    "has_finite_witness",
    "resolution_gate",
    "needs_decision_backend",
    "classify_and_authorize",
    "forged_tier_guard",
]


# ---------------------------------------------------------------------------
# has_finite_witness — A3 dispatcher over the two EXISTING witness-check
# instances (providers/cards/base.py, providers/oracle/execution_oracle.py).
# ---------------------------------------------------------------------------

def has_finite_witness(gate: Any, candidate: Any) -> bool:
    """Dispatcher recognizing the `A3` witness-check pattern already present in this repo.

    `A3` (untagged root, Toledo): `P(X) <=> exists w finite: check(X,w)=top`. Returns `True` when
    a deterministic check/witness already resolves the question for `candidate` — meaning no
    `DecisionBackend` call should happen for it. This is a **documented adapter** over the two
    witness-check instances the project's architecture design notes §2.3/§4 item 4 names as
    already existing and already `keep`-verdicted by the Phase A audit — it does not rewrite
    either file's logic, only recognizes their result shapes:

    1. `providers/cards/base.py`'s `EngineCardProvider.verify(cand) -> VerifierResult`. A card
       with `coq_checked=True` or `independent_oracle=True` performs a real deterministic
       check/witness (`v_struct_ok`/`v_answer_ok`) and reports it via `VerifierResult.ok`, with
       `detail` naming which path ran (`"coq"`, `"oracle"`). A `SELF_CONSISTENT`-only card never
       had a witness checked at all — `EngineCardProvider.verify()` always returns
       `ok=True, detail="self_consistent_NA"` for that path (see `providers/cards/base.py`
       `verify()`'s final `return` line) — that is **not** a witness (no `check` ran), so this
       dispatcher returns `False` for it even though `ok` is `True`.
    2. `providers/oracle/execution_oracle.py`'s `run_candidate() -> OracleVerdict`. `passed` is a
       literal executed pass/fail witness — "did this code pass this test" IS
       `exists w: check(X,w)=top` with `w` the execution trace itself, per that module's own
       docstring ("running generated code against a real test suite and reading pass/fail is
       asserting a fact from EXECUTION, not from the LLM"). A timed-out run (`timed_out=True`)
       produced no witness either way, so this dispatcher returns `False` for it regardless of
       `passed`.

    A plain `dict` mirroring either shape (fixtures, JSON-decoded payloads, a future serialized
    trace) is accepted the same way, so callers outside this process boundary do not need the
    original dataclass/pydantic types.

    `gate` is accepted but not consulted by the two recognized shapes above — the parameter exists
    so a future caller-supplied gate object can carry extra witness-recognition context without
    changing this function's signature; it is deliberately unused here (Stream 3 step 4 scope is
    pure functions only, no gate-specific dispatch yet).
    """
    del gate  # not consulted by the two currently-recognized witness shapes (see docstring)

    ok = _get(candidate, "ok")
    detail = _get(candidate, "detail")
    if ok is not None and detail is not None:
        return bool(ok) and detail != "self_consistent_NA"

    passed = _get(candidate, "passed")
    timed_out = _get(candidate, "timed_out")
    if passed is not None and timed_out is not None:
        return bool(passed) and not bool(timed_out)

    return False


def _get(obj: Any, name: str) -> Any:
    """Read `name` off `obj` whether it is an attribute-bearing object (dataclass, pydantic
    BaseModel) or a plain `dict` — keeps `has_finite_witness` shape-agnostic per its docstring."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ---------------------------------------------------------------------------
# resolution_gate — cheap-check -> refine -> HOLD-if-still-BOT, licensed by
# D/M.77.v1.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceEntry:
    """One audit-trail step of a `resolution_gate` run. `action` is one of
    `"coarse"` (the initial cheap check), `"refine"` (a subsequent, finer check), or
    `"exhausted"` (the refine budget ran out while still `S4.BOT` — a synthetic final entry,
    never a real check call, so the exhaustion event itself is visible in the trace)."""

    step: int
    action: str
    result: S4


def resolution_gate(
    coarse_check: Callable[[], S4],
    refine_fn: Callable[[int], S4],
    budget: int,
) -> tuple[S4, list[TraceEntry]]:
    """Cheap-check → refine → HOLD-if-still-⊥-after-budget (the project's architecture design
    notes §2.5).

    Toledo `D/M.77.v1` (`bot_monotone_in_floor`, **Th_coqc**), statement as registered:

        0<=f1 -> f1<=f2 -> classify f1 v = Sbot -> classify f2 v = Sbot

    i.e. "coarsening the resolution floor can only ever GROW the unresolved region, never shrink
    it." This is what licenses the early-exit below as **sound**, not merely fast: `coarse_check`
    runs at the cheapest/coarsest resolution floor first. Per `D/M.77.v1`'s contrapositive, if
    that coarse floor already resolved (returned anything other than `S4.BOT`), no finer floor
    could have wrongly caused that same value to become unresolved — coarsening can only grow the
    `⊥` region, so a resolved answer at a coarse floor is never at risk of being an artifact that a
    finer check would overturn into `⊥`. Only a genuine `S4.BOT` result needs the refine loop at
    all; stopping the instant `coarse_check` resolves is therefore safe, not just an optimization.

    `refine_fn(step)` is called for `step` in `1..budget` (each call expected to use a strictly
    finer resolution floor than the previous one — the caller owns what "finer" means in its own
    domain, e.g. a smaller epsilon or a wider evidence window) until either a non-`S4.BOT` result
    appears or `budget` is exhausted. Exhaustion returns `S4.BOT` and **never raises, never
    guesses** — the exhaustion event is itself recorded as a final `TraceEntry(action="exhausted")`
    so the caller (and any future audit) can see that budget, not a real classification, is why the
    answer stayed `⊥` — this is the producer side of the project's architecture design notes
    §2.4's
    rule that `⊥` (`S4.BOT`) must never silently collapse into `None`/falsy/a guessed value.
    """
    trace: list[TraceEntry] = []

    result = coarse_check()
    trace.append(TraceEntry(step=0, action="coarse", result=result))
    if result != S4.BOT:
        return result, trace

    for step in range(1, budget + 1):
        result = refine_fn(step)
        trace.append(TraceEntry(step=step, action="refine", result=result))
        if result != S4.BOT:
            return result, trace

    trace.append(TraceEntry(step=budget, action="exhausted", result=S4.BOT))
    return S4.BOT, trace


# ---------------------------------------------------------------------------
# needs_decision_backend — the concrete "Witness before Model" gate.
# ---------------------------------------------------------------------------

def needs_decision_backend(gate: Any, candidate: Any, s4_result: S4) -> bool:
    """`True` only when `has_finite_witness(gate, candidate)` is `False` **and** `s4_result` (the
    `S4` value `resolution_gate` returned after exhausting its budget) is still `S4.BOT`.

    This is the concrete "Witness before Model" gate named in the project's architecture design
    notes §2.3/§4 item 1: nothing reaches a `DecisionBackend`
    unless both `A3` (no finite witness exists) and the `D/M.77.v1`-licensed resolution gate
    (still `⊥` after refinement) agree there is genuinely nothing else to try. `s4_result` is
    taken as a parameter rather than recomputed here — the caller is expected to have already run
    `resolution_gate` (this function does not call it, keeping the three functions independently
    testable and composable, per Stream 3 step 4's "pure functions, no pipeline wiring" scope).
    """
    return (not has_finite_witness(gate, candidate)) and s4_result == S4.BOT


# ---------------------------------------------------------------------------
# classify_and_authorize — Stream 3 step 5 (internal task-tracking notes, item 23): the
# DANGER/ADVISORY/WEAKNESS taxonomy (harm_net.py) ported to the maintainer-
# confirmed ADMIT/HOLD/REJECT/ESCALATE mapping.
# ---------------------------------------------------------------------------

def _extract_text(candidate_or_query: Any) -> str:
    """Read the text to classify off either a bare `str` query or a `Candidate`/
    `EvidenceCandidate`-shaped object's `.content` field (both carry `content: str`, per
    `decision/schema.py`'s docstring: `Candidate` is the "same content/provenance/tier shape" as
    `core.models.EvidenceCandidate`). Falls back to `""` (never `None`) for an object without a
    usable `content`, so `classify_harm_taxonomy`/`classify_danger_subtype` always receive a `str`.
    """
    if isinstance(candidate_or_query, str):
        return candidate_or_query
    content = _get(candidate_or_query, "content")
    return content if isinstance(content, str) else ""


def classify_and_authorize(candidate_or_query: Any) -> AuthorizationStatus:
    """The maintainer-confirmed DANGER/ADVISORY/WEAKNESS -> ADMIT/HOLD/REJECT/ESCALATE mapping
    (project's internal task-tracking notes, Phase 0 item 5, RESOLVED 2026-09-21; also stated
    in the project's architecture design notes' maintainer-confirmed mapping):

        DANGER   -> REJECT   (harm-to-others/weapons/dangerous-synthesis: the request itself must
                               not be fulfilled — `harm_net.classify_danger_subtype() ==
                               "OTHER_HARM"`)
                 -> ESCALATE (self-harm/suicide content: never self-authorized, always
                               REFER_TO_HUMAN + crisis bridge, ported from `humane_gate.py`'s own
                               `_CRISIS_OPTION` discipline — `classify_danger_subtype() ==
                               "SELF_HARM"`)
        ADVISORY -> ADMIT    (answered as the AI's opinion + explicit consult-a-human caveat,
                               never blanket-refused — per `policy/stakes.py`'s
                               `classify_stakes() == Stakes.HIGH`)
        WEAKNESS -> HOLD     (pending further evidence, not a hard refusal — the default when
                               neither DANGER nor ADVISORY applies)

    `candidate_or_query` is either a bare query string or any `Candidate`/`EvidenceCandidate`-
    shaped object (dataclass, pydantic `BaseModel`, or plain `dict`) carrying a `content: str`
    field — see `_extract_text()`. This function does not itself call a `DecisionBackend`; it is
    the harm/stakes-taxonomy leg of Authorize, orthogonal to `needs_decision_backend()`'s
    witness/resolution-gate leg above (both live in this module per Stream 3's `authorization/
    policy.py` ownership, project's internal task-tracking notes, Phase 0 item 1).
    """
    text = _extract_text(candidate_or_query)
    category = classify_harm_taxonomy(text)
    if category == "DANGER":
        subtype = classify_danger_subtype(text)
        return AuthorizationStatus.REJECT if subtype == "OTHER_HARM" else AuthorizationStatus.ESCALATE
    if category == "ADVISORY":
        return AuthorizationStatus.ADMIT
    return AuthorizationStatus.HOLD


# ---------------------------------------------------------------------------
# forged_tier_guard — Stream 3 step 5 (internal task-tracking notes, item 23): the
# easm.py FORGED_TIER guard, generalized against core/tiering.py's existing
# verifiability_ceiling() discipline instead of duplicating it.
# ---------------------------------------------------------------------------

def forged_tier_guard(
    candidate: Any, verified_kernel: frozenset[str] = frozenset()
) -> tuple[Tier, str]:
    """Caps a candidate DECLARING `Th_coqc`/`COQ_CHECKED` whose `provenance.source_ref` is not in
    `verified_kernel` down below `Th_coqc`, rather than trusting the declaration — the live-types
    generalization of a legacy module's FORGED_TIER guard ("a `Th_coqc` structure tier is only
    honest if the cited Coq law is ACTUALLY machine-checked").

    This function CALLS `core.tiering.verifiability_ceiling()` for the normal ceiling computation
    (per the task's own instruction: reuse, do not duplicate that table) and only adds the
    additional forged-declaration check on top of it — it never recomputes the
    `Verifiability -> Tier` table itself.

    `verified_kernel` is the set of `source_ref` values this caller trusts as actually
    machine-checked (the live-pipeline analog of the legacy module's law sets, but caller-supplied
    rather than loaded from a private, separately-verified Coq-kernel source — that
    source-specific loading logic belongs to that legacy module and, per the project's private/
    public split, is not something this live-types generalization should couple to). An empty/
    default `verified_kernel` means "trust nothing" — every
    `Th_coqc`/`COQ_CHECKED`
    declaration is capped unless the caller explicitly supplies the `source_ref`s it has verified.

    `candidate` is any `Candidate`/`EvidenceCandidate`-shaped object (or `dict`) carrying
    `provenance.verifiability`, `provenance.source_ref`, and `declared_tier` — see `_get()`.
    Raises `ValueError` if `candidate` carries no `provenance.verifiability` at all (there is no
    honest ceiling to compute without it — this function does not guess a default tier).

    Returns `(tier, reason)`: `reason == ""` when the normal ceiling applies unmodified; otherwise
    a non-empty string naming the FORGED_TIER guard as the cause (mirroring the legacy module's
    own analogous message shape, adapted to this module's `source_ref` vocabulary).
    """
    provenance = _get(candidate, "provenance")
    verifiability = _get(provenance, "verifiability") if provenance is not None else None
    if verifiability is None:
        raise ValueError(
            "forged_tier_guard: candidate has no provenance.verifiability — cannot compute an "
            "honest ceiling without it"
        )
    source_ref = _get(provenance, "source_ref") if provenance is not None else None
    declared_tier = _get(candidate, "declared_tier")

    ceiling = verifiability_ceiling(verifiability)

    declares_coq = verifiability == Verifiability.COQ_CHECKED or declared_tier == Tier.Th_coqc
    if declares_coq and ceiling == Tier.Th_coqc and (not source_ref or source_ref not in verified_kernel):
        return Tier.finite_diagnostic, (
            f"FORGED_TIER guard: declared Th_coqc/COQ_CHECKED but source_ref={source_ref!r} is "
            "not in the verified-kernel set — capped below Th_coqc, not trusted on declaration "
            "alone"
        )
    return ceiling, ""
