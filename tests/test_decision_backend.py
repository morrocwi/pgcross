from __future__ import annotations

import pytest

from pgcross.decision.backend import (
    DecisionAnswer,
    DecisionProposal,
    DecisionQuestion,
    DeterministicBackend,
    MockBackend,
    OpenThaiSystemOneLocalBackend,
    OpenThaiSystemOneNotInstalledError,
    S4,
    SystemOneHTTPBackend,
)


def _questions() -> list[DecisionQuestion]:
    return [
        DecisionQuestion(id="q1", text="Is the applicant eligible?"),
        DecisionQuestion(id="q2", text="Risk level?", options=["low", "high"]),
    ]


def _openthai_installed() -> bool:
    try:
        import openthai_systemone  # noqa: F401
    except ImportError:
        return False
    return True


def _noul_questions() -> list[DecisionQuestion]:
    """OpenThai's `Choice` type rejects an empty-options question (see
    `_pgcross_questions_to_openthai`'s own guard) -- `_questions()` above has one (`q1`), by
    design, for backends that never validate Choice shape (Mock/Deterministic). Real OpenThai
    calls need well-formed questions; `kind='noul'` (free-form yes/no/unresolved, no options
    needed) matches how `pipeline/authorize.py` actually calls this backend in production."""
    return [DecisionQuestion(id="admissible", text="Is 100 the correct answer for 10*10?", kind="noul")]


class TestMockBackend:
    def test_default_returns_bot_for_every_question(self) -> None:
        backend = MockBackend()
        proposal = backend.decide(state={}, questions=_questions())

        assert isinstance(proposal, DecisionProposal)
        assert proposal.backend_id == "mock"
        assert len(proposal.answers) == 2
        for answer in proposal.answers:
            assert isinstance(answer, DecisionAnswer)
            assert answer.resolution == S4.BOT
            assert answer.probability == 0.0
        assert {a.question_id for a in proposal.answers} == {"q1", "q2"}

    def test_configured_canned_proposal_returned_verbatim(self) -> None:
        canned = DecisionProposal(
            answers=[DecisionAnswer(question_id="q1", resolution=S4.POS, probability=0.9)],
            backend_id="mock-canned",
            rationale="test fixture",
        )
        backend = MockBackend(proposal=canned)

        result = backend.decide(state={"anything": True}, questions=_questions())

        assert result is canned
        assert result.answers[0].resolution == S4.POS
        assert result.answers[0].probability == 0.9

    def test_custom_backend_id_used_by_default_proposal(self) -> None:
        backend = MockBackend(backend_id="mock-alt")
        proposal = backend.decide(state={}, questions=_questions())
        assert proposal.backend_id == "mock-alt"

    def test_is_runtime_checkable_decision_backend(self) -> None:
        from pgcross.decision.backend import DecisionBackend

        assert isinstance(MockBackend(), DecisionBackend)


class TestDeterministicBackend:
    def test_wraps_plain_callable(self) -> None:
        def fn(state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
            return DecisionProposal(
                answers=[
                    DecisionAnswer(
                        question_id=q.id,
                        resolution=S4.POS if state.get("eligible") else S4.NEG,
                        probability=1.0,
                    )
                    for q in questions
                ],
                backend_id="deterministic-test",
            )

        backend = DeterministicBackend(fn)
        proposal = backend.decide(state={"eligible": True}, questions=_questions())

        assert isinstance(proposal, DecisionProposal)
        assert proposal.backend_id == "deterministic-test"
        assert all(a.resolution == S4.POS for a in proposal.answers)

    def test_no_model_call_is_pure_function_of_inputs(self) -> None:
        calls: list[tuple[dict, list[DecisionQuestion]]] = []

        def fn(state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
            calls.append((state, questions))
            return DecisionProposal(answers=[], backend_id="det")

        backend = DeterministicBackend(fn, backend_id="det")
        qs = _questions()
        backend.decide(state={"x": 1}, questions=qs)

        assert len(calls) == 1
        assert calls[0][0] == {"x": 1}
        assert calls[0][1] == qs

    def test_default_backend_id(self) -> None:
        backend = DeterministicBackend(lambda s, q: DecisionProposal(answers=[], backend_id="d"))
        assert backend._backend_id == "deterministic"


class TestSystemOneHTTPBackend:
    """Real HTTP transport (no longer a stub) -- tested against httpx.MockTransport, no real
    network call, no dependency on the openthai_systemone package (the whole point of this
    transport is working without it installed locally)."""

    def test_constructs_with_base_url_and_api_key(self) -> None:
        backend = SystemOneHTTPBackend(base_url="https://example.invalid", api_key="k")
        assert backend.base_url == "https://example.invalid"
        assert backend.api_key == "k"

    def test_constructs_without_api_key(self) -> None:
        backend = SystemOneHTTPBackend(base_url="https://example.invalid")
        assert backend.api_key is None

    def test_decide_posts_v1_systemone_and_parses_choice_noul_score(self) -> None:
        import json as _json

        import httpx

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = _json.loads(request.content)
            return httpx.Response(200, json={
                "answers": {
                    "eligible": {"noul": 0.83},
                    "risk": {"choice": "high", "probabilities": {"low": 0.1, "high": 0.9}},
                    "severity": {"score": 2.7, "confidence": 0.6, "probabilities": {"0": 0.1, "1": 0.2, "2": 0.3, "3": 0.4}},
                }
            })

        backend = SystemOneHTTPBackend(base_url="https://example.invalid", api_key="secret")
        backend._transport = httpx.MockTransport(handler)  # test-only injection point, see decide()

        questions = [
            DecisionQuestion(id="eligible", text="Is the applicant eligible?", kind="noul"),
            DecisionQuestion(id="risk", text="Risk level?", kind="choice", options=["low", "high"]),
            DecisionQuestion(id="severity", text="Severity?", kind="score", levels=["none", "mild", "moderate", "severe"]),
        ]
        proposal = backend.decide(state={"x": 1}, questions=questions)

        assert isinstance(proposal, DecisionProposal)
        by_id = {a.question_id: a for a in proposal.answers}
        assert by_id["eligible"].resolution == S4.POS
        assert by_id["eligible"].label == "yes"
        assert by_id["eligible"].probability == pytest.approx(0.83)
        assert by_id["risk"].label == "high"
        assert by_id["risk"].probabilities == {"low": 0.1, "high": 0.9}
        assert by_id["severity"].label == "2.7"
        assert by_id["severity"].probability == pytest.approx(0.6)
        assert captured["auth"] == "Bearer secret"
        assert captured["url"] == "https://example.invalid/v1/systemone"

    def test_decide_raises_on_http_error_never_fabricates(self) -> None:
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "backend down"})

        backend = SystemOneHTTPBackend(base_url="https://example.invalid")
        backend._transport = httpx.MockTransport(handler)

        with pytest.raises(httpx.HTTPStatusError):
            backend.decide(state={}, questions=_questions())


class TestOpenThaiSystemOneLocalBackend:
    """Covers both environments honestly rather than assuming one: when `openthai_systemone`
    isn't installed, exercises the real not-installed path (matching `IDMBackend`'s precedent in
    `decision/computation_backend.py` -- never silently no-op, never fabricate a result); when it
    IS installed, `TestOpenThaiSystemOneLocalBackendRealWeights` below runs a real end-to-end
    call against real model weights instead."""

    def test_constructs_with_default_model(self) -> None:
        backend = OpenThaiSystemOneLocalBackend()
        assert backend.model == "iapp/OpenThai-SystemOne"

    @pytest.mark.skipif(_openthai_installed(), reason="openthai_systemone IS installed here -- see TestOpenThaiSystemOneLocalBackendRealWeights")
    def test_decide_raises_documented_error_when_package_not_installed(self) -> None:
        backend = OpenThaiSystemOneLocalBackend()
        with pytest.raises(OpenThaiSystemOneNotInstalledError) as exc_info:
            backend.decide(state={}, questions=_questions())
        message = str(exc_info.value)
        assert "openthai_systemone" in message
        assert "pip install openthai-systemone" in message
        assert "OpenThai-SystemOne" in message

    def test_not_installed_error_is_an_import_error(self) -> None:
        assert issubclass(OpenThaiSystemOneNotInstalledError, ImportError)

    def test_empty_options_choice_question_raises_clear_error_not_opaque_upstream_one(self) -> None:
        """Real bug found by this project's own end-to-end verification 2026-09-21: a
        kind='choice' DecisionQuestion with no options/option_descriptions used to reach
        OpenThai's `Choice` pydantic model and fail with an opaque upstream ValidationError --
        AFTER paying for a full model load, since validation ran after `_get_client()`.
        `_validate_questions_before_any_heavy_work` now runs FIRST (pure Python, no
        `openthai_systemone` import, no model/client involved), so this is testable regardless
        of whether the package is installed and without loading anything heavy."""
        backend = OpenThaiSystemOneLocalBackend()
        with pytest.raises(ValueError, match="has kind='choice' but no options"):
            backend.decide(state={}, questions=_questions())


@pytest.mark.real_weights
@pytest.mark.skipif(not _openthai_installed(), reason="openthai_systemone not installed -- see TestOpenThaiSystemOneLocalBackend for the honest not-installed path instead")
class TestOpenThaiSystemOneLocalBackendRealWeights:
    """Runs ONLY when `openthai_systemone` is actually installed -- a real end-to-end call
    against real downloaded model weights (not a mock, not a source-doc check). First run
    downloads ~1.6GB of BF16 weights from the Hugging Face Hub and takes ~60-90s to load the
    model; `decide()` itself is sub-second once loaded. Proves the full real chain: pgcross
    DecisionQuestion -> openthai_systemone's Noul -> a real forward pass -> DecisionProposal.

    Marked `real_weights` and excluded from the default `pytest` run (see pyproject.toml) --
    found by a real failure 2026-09-21 that this machine's 4GB GPU cannot hold this model
    alongside the RAG suite's sentence-transformers model in the same process. Run explicitly
    with `pytest -m real_weights` when you have GPU/CPU headroom."""

    def test_decide_returns_a_real_proposal_from_real_weights(self) -> None:
        backend = OpenThaiSystemOneLocalBackend()
        proposal = backend.decide(
            state={"query": "10*10", "candidate_content": "100"},
            questions=_noul_questions(),
        )
        assert isinstance(proposal, DecisionProposal)
        assert proposal.backend_id == "openthai-systemone-local"
        assert len(proposal.answers) == 1
        answer = proposal.answers[0]
        assert answer.question_id == "admissible"
        assert isinstance(answer.resolution, S4)
        assert 0.0 <= answer.probability <= 1.0
