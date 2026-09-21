"""F2 tests — "missing evidence produces HOLD, never fabrication" (`docs/TODOLIST.md` Phase 5
item 29).

Companion to `tests/test_f1_gate_bypass.py`/`tests/test_f1_gate_bypass_integration.py` (F1: a
dangerous candidate can never become primary) and `tests/test_authorization_policy.py` (unit
coverage of `authorization/policy.py`'s pure functions). F2 is the dual honesty invariant on the
*non*-dangerous path: when nothing — no finite witness, no resolved `S4` classification, no
`DecisionBackend` — can actually resolve a query, `pgcross` must degrade to `HOLD` (or a
CLARIFY/CONSULTATION-led response), never fabricate a confident `ADMIT`/COMPUTED/RETRIEVED answer
out of thin air. Grounded in the same Toledo primitives `authorization/policy.py` cites
(`A3` witness-before-model, `D/M.77.v1` bot-monotone-in-floor, `D/M.65.v1` `Sz <> Sbot`) plus
`pipeline/authorize.py::_authorize_status`'s documented TEMPORARY default (no `DecisionBackend`
wired into the live pipeline yet ⇒ `⊥` defaults to `HOLD`, never a guess).

Three levels, per the task spec:
  1. `resolution_gate()` — a coarse_check/refine_fn that never resolves must return `S4.BOT` after
     the budget is exhausted: never raise, never guess `POS`/`NEG`/`ZERO`.
  2. `needs_decision_backend()` + `pipeline/authorize.py::_authorize_status()` — no witness + still
     `S4.BOT` ⇒ `needs_decision_backend()` is `True`, and in the live pipeline (no `DecisionBackend`
     wired) that resolves to `AuthorizationStatus.HOLD`, not `ADMIT` and not an exception.
  3. `run_pipeline()` end-to-end with a genuinely empty `Registry()` and a benign query — the
     response is `HOLD` and primary is a CLARIFY/CONSULTATION candidate, never a fabricated
     COMPUTED/RETRIEVED one.

Targeted test file only — run directly (`pytest tests/test_f2_missing_evidence_hold.py -v`), not
the full conformance suite (`WF-NO-REAUDIT`: that full-arc pass happens once, later, in a separate
final regression step).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from pgcross.authorization.policy import (
    TraceEntry,
    has_finite_witness,
    needs_decision_backend,
    resolution_gate,
)
from pgcross.core.enums import CType, Grounding, Stakes, Tier, Verifiability
from pgcross.core.models import EvidenceCandidate, Provenance, VerifierResult
from pgcross.core.provider import Registry
from pgcross.core.s4 import S4
from pgcross.decision.schema import AuthorizationStatus
from pgcross.pipeline.authorize import _authorize_status
from pgcross.pipeline.run import Config, Ctx, run_pipeline

# A benign, LOW-stakes query: no self-harm/other-harm pattern (authorization/harm_net.py) and no
# high-stakes keyword (policy/stakes.py) — classify_harm_taxonomy() must return "WEAKNESS", which
# authorization/policy.py::classify_and_authorize() maps to AuthorizationStatus.HOLD by default
# (never DANGER->REJECT/ESCALATE, never ADVISORY->ADMIT).
_BENIGN_QUERY = "What is the population of Bangkok?"


@dataclass
class _FakeQuery:
    """Minimal QueryIR-shaped stand-in, same convention as tests/test_f1_gate_bypass.py."""

    text: str
    stakes: Stakes = Stakes.LOW
    slots: dict = field(default_factory=dict)

    def slots_partially_known(self) -> bool:
        return len(self.slots) > 0


# ── 1. resolution_gate() — never resolves, never raises, never guesses ─────────────────────────


def test_resolution_gate_never_resolving_returns_bot_after_budget_exhausted():
    """coarse_check and every refine step stay S4.BOT (the "genuinely nothing can resolve this"
    case) -> resolution_gate must return exactly S4.BOT, never raise, and never substitute a
    guessed POS/NEG/ZERO to make the budget exhaustion look like a real answer."""
    refine_calls: list[int] = []

    def coarse_check() -> S4:
        return S4.BOT

    def refine_fn(step: int) -> S4:
        refine_calls.append(step)
        return S4.BOT

    result, trace = resolution_gate(coarse_check, refine_fn, budget=4)

    assert result is S4.BOT
    assert result not in (S4.POS, S4.NEG, S4.ZERO)
    assert refine_calls == [1, 2, 3, 4]  # every refine step genuinely ran, none skipped/guessed
    assert trace[-1] == TraceEntry(step=4, action="exhausted", result=S4.BOT)
    assert all(t.result is S4.BOT for t in trace)  # not one step silently resolved


def test_resolution_gate_never_resolving_never_raises():
    """Explicit 'never raises' check (mirrors test_authorization_policy.py's own exhaustion
    test): exhaustion on a never-resolving coarse/refine pair is a normal return, not an
    exception path, at any budget size."""
    try:
        result, trace = resolution_gate(lambda: S4.BOT, lambda step: S4.BOT, budget=7)
    except Exception as exc:  # pragma: no cover - this must never happen
        pytest.fail(f"resolution_gate raised on a never-resolving pair instead of returning "
                    f"S4.BOT: {exc!r}")
    assert result is S4.BOT
    assert trace[-1].action == "exhausted"


# ── 2. needs_decision_backend() + _authorize_status() — HOLD, not ADMIT, not an exception ──────


def test_needs_decision_backend_true_when_witness_missing_and_bot_after_exhaustion():
    """Compose resolution_gate's honest exhaustion result with needs_decision_backend(): no
    finite witness AND still S4.BOT after the budget is exhausted -> "this needs external
    resolution" is True."""
    s4_result, trace = resolution_gate(lambda: S4.BOT, lambda step: S4.BOT, budget=3)
    assert s4_result is S4.BOT
    assert trace[-1].action == "exhausted"

    no_witness = VerifierResult(ok=False, verifiability=Verifiability.NONE, detail="no_witness")
    assert has_finite_witness(None, no_witness) is False
    assert needs_decision_backend(gate=None, candidate=no_witness, s4_result=s4_result) is True


def test_authorize_status_holds_when_no_witness_and_no_decision_backend_wired():
    """The live-pipeline consequence of the above: pipeline/authorize.py::_authorize_status(),
    given a single benign, unwitnessed candidate (SELF_CONSISTENT verifiability — no coq/oracle
    check ever ran, so has_finite_witness() is False per that function's own contract), must
    default to AuthorizationStatus.HOLD — never AuthorizationStatus.ADMIT, and never raise —
    because no DecisionBackend is wired into the live pipeline yet
    (pipeline/authorize.py's own documented TEMPORARY behavior, §3/§6a)."""
    q = _FakeQuery(text=_BENIGN_QUERY, stakes=Stakes.LOW)
    unwitnessed_cand = EvidenceCandidate(
        content="A plausible-sounding but never deterministically checked answer.",
        ctype=CType.COMPUTED,
        provider_id="unverified_card",
        provenance=Provenance(kind="ENGINE_CARD", source_ref=None, verifiability=Verifiability.SELF_CONSISTENT),
        declared_tier=Tier.Wf,
        grounding=Grounding.ALL,
        tier=Tier.Wf,
        floor_reason="",
    )

    try:
        status, reason, danger_source, model_proposal = _authorize_status([unwitnessed_cand], q)
    except Exception as exc:  # pragma: no cover - this must never happen
        pytest.fail(f"_authorize_status raised instead of defaulting to HOLD: {exc!r}")

    assert status is AuthorizationStatus.HOLD
    assert status is not AuthorizationStatus.ADMIT
    assert danger_source is None
    assert model_proposal is None  # no q.decision_question was set on this fixture
    assert "no finite witness" in reason and "DecisionBackend" in reason


# ── 3. run_pipeline() end-to-end — empty Registry, benign query -> HOLD, never fabricated ──────


def test_empty_registry_benign_query_holds_and_never_fabricates():
    """Genuinely nothing can resolve this query: an empty Registry() means route() finds zero
    providers, verify() produces zero candidates, and assemble()'s I4 fallback appends a
    CLARIFY/CONSULTATION candidate (pipeline/lens.py::clarify_or_consultation) rather than
    inventing a COMPUTED/RETRIEVED answer. The witness-before-model gate then holds the whole
    response at AuthorizationStatus.HOLD (the documented default when no DecisionBackend is wired).
    No backend feature (general_chat_fallback / imagine_bridge) is enabled here — this test is
    about the bare "nothing resolved it" case, not about a fallback layer that could itself
    inject an unguarded guess (that is tests/test_f1_gate_bypass_integration.py's job)."""
    cfg = Config(backend=None)  # both enable_* fallbacks default False (see pipeline/run.py)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=None)

    resp = run_pipeline(_BENIGN_QUERY, ctx)

    assert resp.candidates, "Response.candidates must be non-empty (I4)"
    assert resp.authorization.status is AuthorizationStatus.HOLD
    assert resp.authorization.status is not AuthorizationStatus.ADMIT

    primary_cand = resp.candidates[resp.primary]
    assert primary_cand.ctype in (CType.CLARIFY, CType.CONSULTATION), (
        "F2 violated: with nothing able to resolve the query, primary must be a CLARIFY/"
        f"CONSULTATION candidate, never a fabricated answer — got {primary_cand.ctype}"
    )
    assert primary_cand.ctype not in (CType.COMPUTED, CType.RETRIEVED), (
        "F2 violated: an empty registry must never produce a fabricated COMPUTED/RETRIEVED "
        "primary candidate"
    )
    # The CONSULTATION/CLARIFY content itself must not read as a confident, invented answer to
    # the actual question (a crude but concrete no-fabrication check): it must not contain a
    # bare population-sounding number, i.e. no digit run anywhere in the content.
    assert not any(ch.isdigit() for ch in primary_cand.content), (
        "F2 violated: the HOLD-path candidate's content contains a digit — looks like a "
        f"fabricated numeric answer rather than a clarify/consult message: {primary_cand.content!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
