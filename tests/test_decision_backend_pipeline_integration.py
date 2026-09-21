"""Integration test: a real DecisionBackend actually reached through the live pipeline.

Closes the gap `pipeline/authorize.py`'s own prior "TEMPORARY BEHAVIOR" comment named: before this
wiring, `needs_decision_backend()==True` always defaulted straight to HOLD, because no
DecisionBackend was ever configured/called from the live pipeline -- decision/backend.py's
concrete backends (OpenThaiSystemOneLocalBackend, SystemOneHTTPBackend, MockBackend) existed but
were never reached by `run_pipeline()`. This test proves the wiring itself, using MockBackend
(since `openthai_systemone` genuinely isn't installed in this dev environment -- see
tests/test_decision_backend.py's TestOpenThaiSystemOneLocalBackend for that honest not-installed
path) -- the wiring code in pipeline/authorize.py is backend-agnostic, so proving it against
MockBackend proves it for OpenThaiSystemOneLocalBackend/SystemOneHTTPBackend too.

Governing invariant under test: "the model proposed, PGCross authorized" -- a DecisionBackend is
only ever reached AFTER the deterministic harm-net check and the A3 witness-before-model gate both
find nothing, and its proposal can only ever result in ADMIT or HOLD, never REJECT/ESCALATE
(authorization/policy.py::authorize_decision_proposal's own documented restriction).
"""
from __future__ import annotations

from pgcross.core.provider import Registry
from pgcross.decision.backend import MockBackend
from pgcross.decision.schema import AuthorizationStatus, DecisionAnswer, DecisionProposal
from pgcross.core.s4 import S4
from pgcross.pipeline.run import Ctx, Config, run_pipeline


def _backend_that_always_says(question_id_prefix: str, resolution: S4, probability: float, label: str) -> MockBackend:
    """A MockBackend whose canned proposal answers ANY question id with the given resolution --
    built as a DeterministicBackend-style callable wrapped in MockBackend's canned-proposal mode
    is awkward since the question id is dynamic (pipeline/authorize.py generates it), so this
    constructs the proposal lazily via a tiny subclass instead."""

    class _Backend:
        def decide(self, state, questions):
            return DecisionProposal(
                answers=[
                    DecisionAnswer(question_id=q.id, resolution=resolution, label=label, probability=probability)
                    for q in questions
                ],
                backend_id="test-mock",
            )

    return _Backend()


def test_no_decision_backend_configured_still_holds_exactly_as_before() -> None:
    """Regression guard: Config() with no decision_backend set must behave identically to before
    this wiring existed -- HOLD, never an error, never a guess."""
    cfg = Config()
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    resp = run_pipeline("What is the population of Bangkok?", ctx)
    assert resp.authorization.status is AuthorizationStatus.HOLD


def test_confident_model_proposal_admits() -> None:
    """A DecisionBackend that confidently answers 'yes' (probability above the admit threshold)
    is actually reached and actually flips the outcome from HOLD to ADMIT -- proves the backend is
    really being called, not just configured and ignored."""
    backend = _backend_that_always_says("q", S4.POS, probability=0.95, label="yes")
    cfg = Config(decision_backend=backend)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    resp = run_pipeline("What is the population of Bangkok?", ctx)
    assert resp.authorization.status is AuthorizationStatus.ADMIT
    assert "PGCross admits the proposal" in resp.authorization.reason
    assert "test-mock" in resp.authorization.reason


def test_unconfident_model_proposal_still_holds() -> None:
    """A DecisionBackend that answers but with LOW confidence must still HOLD -- the admit
    threshold is real, not decorative."""
    backend = _backend_that_always_says("q", S4.POS, probability=0.2, label="yes")
    cfg = Config(decision_backend=backend)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    resp = run_pipeline("What is the population of Bangkok?", ctx)
    assert resp.authorization.status is AuthorizationStatus.HOLD
    assert "not confident enough" in resp.authorization.reason


def test_backend_that_raises_defaults_to_hold_not_an_unhandled_exception() -> None:
    """FAILURE POLICY (decision/backend.py's own documented contract): a DecisionBackend failure
    must default to HOLD, never propagate as an unhandled exception out of run_pipeline()."""

    class _BoomBackend:
        def decide(self, state, questions):
            raise RuntimeError("network down")

    cfg = Config(decision_backend=_BoomBackend())
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    resp = run_pipeline("What is the population of Bangkok?", ctx)  # must not raise
    assert resp.authorization.status is AuthorizationStatus.HOLD
    assert "RuntimeError" in resp.authorization.reason


def test_model_proposal_can_never_escalate_or_reject_even_if_it_tries() -> None:
    """F1-adjacent invariant: authorize_decision_proposal structurally cannot return
    REJECT/ESCALATE (see its own docstring) -- confirmed here at the pipeline level with a backend
    that would (if this restriction didn't exist) look like it's answering a dangerous question.
    A benign, non-harm-net-triggering query is used deliberately, since harm-net-triggering
    queries are already covered by tests/test_f1_gate_bypass_integration.py -- this test isolates
    the SEPARATE guarantee that authorize_decision_proposal's own return-value contract holds even
    when a backend answers with maximum confidence."""
    backend = _backend_that_always_says("q", S4.POS, probability=1.0, label="yes")
    cfg = Config(decision_backend=backend)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    resp = run_pipeline("What is the boiling point of water?", ctx)
    assert resp.authorization.status in (AuthorizationStatus.ADMIT, AuthorizationStatus.HOLD)
    assert resp.authorization.status not in (AuthorizationStatus.REJECT, AuthorizationStatus.ESCALATE)
