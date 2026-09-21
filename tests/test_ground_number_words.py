"""tests/test_ground_number_words.py — English/Thai spelled-out number recognition in ground().

Real bug found and fixed 2026-09-21 by an adversarial red-team of a claim made about this
project's own Decision Forge ("a deterministically-resolvable query never reaches the model").
`ground.py`'s number regex only recognized digit numerals; a spelled-out equivalent (e.g. "R0
equals three") failed to ground any slot, so the engine card fell back to a witness-less CLARIFY
candidate, which then genuinely reached the DecisionBackend for a query that was, in fact, fully
deterministic once the words were recognized. See `ground.py`'s own module docstring and
`_normalize_number_words()` for the fix.
"""
from __future__ import annotations

from pgcross.core.models import QueryIR
from pgcross.pipeline.ground import ground


def test_r0_word_number_english() -> None:
    q = QueryIR(text="R0 equals three, what is the herd immunity threshold?")
    ground(q, None)
    assert q.slots.get("R0") == 3.0


def test_beta_gamma_lambda_max_word_fractions_english() -> None:
    q = QueryIR(text="beta is three tenths and gamma is one tenth and lambda_max is three, epidemic status?")
    ground(q, None)
    assert q.slots.get("beta") == 0.3
    assert q.slots.get("gamma") == 0.1
    assert q.slots.get("lambda_max") == 3.0


def test_digit_input_still_works_unaffected() -> None:
    """The fix must not change grounding for the common case (plain digits)."""
    q = QueryIR(text="R0 = 3")
    ground(q, None)
    assert q.slots.get("R0") == 3.0

    q2 = QueryIR(text="epidemic beta=0.3 gamma=0.1 lambda_max=3?")
    ground(q2, None)
    assert q2.slots.get("beta") == 0.3
    assert q2.slots.get("gamma") == 0.1
    assert q2.slots.get("lambda_max") == 3.0


def test_r0_word_number_thai() -> None:
    q = QueryIR(text="ค่า R0 เท่ากับ สาม")
    ground(q, None)
    assert q.slots.get("R0") == 3.0


def test_beta_gamma_thai_decimal_point_reading() -> None:
    q = QueryIR(text="อัตราการติดเชื้อ เท่ากับ ศูนย์จุดสาม และอัตราการหายป่วย เท่ากับ ศูนย์จุดหนึ่ง")
    ground(q, None)
    assert q.slots.get("beta") == 0.3
    assert q.slots.get("gamma") == 0.1


def test_english_teens_and_twenties() -> None:
    q = QueryIR(text="R0 equals fourteen")
    ground(q, None)
    assert q.slots.get("R0") == 14.0

    q2 = QueryIR(text="R0 equals twenty one")
    ground(q2, None)
    assert q2.slots.get("R0") == 21.0


def test_thai_teens_and_twenties() -> None:
    q = QueryIR(text="R0 เท่ากับ สิบเอ็ด")
    ground(q, None)
    assert q.slots.get("R0") == 11.0

    q2 = QueryIR(text="R0 เท่ากับ ยี่สิบสาม")
    ground(q2, None)
    assert q2.slots.get("R0") == 23.0


def test_english_half() -> None:
    q = QueryIR(text="beta is half")
    ground(q, None)
    assert q.slots.get("beta") == 0.5


def test_end_to_end_model_bypassed_with_word_numbers() -> None:
    """The full point of this fix: a query that used to reach the DecisionBackend (because
    grounding failed on word-form numbers) must now resolve deterministically -- 0 model calls,
    same pattern as eval/decision_forge_benchmark.py's own _CountingDecisionBackend."""
    from pgcross.core.provider import Registry
    from pgcross.decision.backend import MockBackend
    from pgcross.pipeline.run import Config, Ctx, run_pipeline
    from pgcross.providers.cards.sis_threshold import SisThresholdCard

    class _CountingBackend:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, state, questions):
            self.calls += 1
            return MockBackend().decide(state, questions)

    registry = Registry()
    registry.register(SisThresholdCard())
    backend = _CountingBackend()
    cfg = Config(decision_backend=backend)
    ctx = Ctx(backend=None, registry=registry, cfg=cfg, safety=lambda text: False)

    resp = run_pipeline(
        "beta is three tenths and gamma is one tenth and lambda_max is three, epidemic status?",
        ctx,
    )
    assert backend.calls == 0
    primary = resp.candidates[resp.primary]
    assert primary.ctype.name == "COMPUTED"
