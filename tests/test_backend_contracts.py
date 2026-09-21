"""Backend-contract / pluggability tests.

Proves that every concrete implementation of the two distinct backend Protocols
(`pgcross.backends.base.LLMBackend`, transport-only/I7-constrained, and
`pgcross.decision.backend.DecisionBackend`, typed-decision-proposing) satisfies the SAME
behavioral contract its Protocol declares, so callers can swap implementations without
special-casing any one of them (the whole point of the "Decision Forge" model-agnostic
design). No real model weights are ever invoked here: `LlamaCppBackend` has its `_load()`/
`_llm` monkeypatched to a stub, and `OpenAIBackend` needs no local weights at all (it would
only reach the network inside `transport()`, which the LLMBackend contract tests below do not
call for that backend — see the class docstring for why).

Read-only with respect to `src/pgcross/backends/base.py`, `backends/llamacpp.py`,
`backends/openai.py`, and `decision/backend.py` — this file only adds tests.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from pgcross.backends.base import BackendInfo, LLMBackend, TransportOut, TransportPrompt
from pgcross.backends.llamacpp import LlamaCppBackend
from pgcross.backends.openai import OpenAIBackend
from pgcross.decision.backend import (
    DecisionAnswer,
    DecisionBackend,
    DecisionProposal,
    DecisionQuestion,
    DeterministicBackend,
    MockBackend,
    S4,
    SystemOneHTTPBackend,
)


class _StubLlama:
    """Stand-in for `llama_cpp.Llama` — records calls, returns a canned chat-completion shape.

    Matches the exact response shape `LlamaCppBackend` reads (`resp["choices"][0]["message"]
    ["content"]`), so `transport()`/`propose_bridge()`/`general_chat()` exercise their real
    parsing logic without ever touching real weights or the `llama_cpp` package.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self._content}}]}


def _llamacpp_backend(content: str = '{"field": "value"}') -> LlamaCppBackend:
    """A `LlamaCppBackend` with `_load()`/`_llm` stubbed out — no real weights are loaded."""
    backend = LlamaCppBackend(weights="fake-weights.gguf", context_length=4096)
    backend._llm = _StubLlama(content)
    backend._load = lambda: None  # type: ignore[method-assign]  # already "loaded"
    return backend


def _openai_backend() -> OpenAIBackend:
    # A deliberately unroutable host: these contract tests never call transport() on this
    # backend (see TestLLMBackendContract's docstring) so no network I/O ever happens here.
    return OpenAIBackend(url="https://example.invalid", model="test-model")


# ---------------------------------------------------------------------------------------------
# LLMBackend contract
# ---------------------------------------------------------------------------------------------


class TestLLMBackendContract:
    """Shared contract for every concrete `LLMBackend` implementation.

    `LLMBackend` is `@runtime_checkable`, but Python's runtime Protocol check is purely
    structural (`hasattr` per declared member) — it does not know that `propose_bridge`/
    `general_chat` are documented as OPTIONAL (checked via `hasattr` at the call sites in
    `pipeline/imagine.py`/`pipeline/run.py`, per `LLMBackend`'s own docstrings). Concretely:
    `LlamaCppBackend` implements all four methods and satisfies `isinstance(..., LLMBackend)`;
    `OpenAIBackend` implements only `transport`/`info` (the two REQUIRED members) and therefore
    does NOT satisfy a full structural `isinstance` check — that is expected, documented Python
    Protocol behavior, not a bug in `OpenAIBackend`. So:

    - `test_info_returns_backend_info_shape` and `test_transport_returns_transport_out_shape`
      run against every concrete backend (`_ALL_BACKENDS`) — both only ever exercise the two
      REQUIRED protocol members.
    - `test_full_protocol_isinstance_when_all_members_present` runs only against backends that
      implement every declared member (`LlamaCppBackend`) and asserts `isinstance` holds.
    - `test_partial_backend_fails_full_protocol_isinstance` documents, explicitly, that a
      backend implementing only the required members (`OpenAIBackend`) is NOT an `isinstance`
      match for the full Protocol — this is the load-bearing fact any caller relying on
      `isinstance(backend, LLMBackend)` as a completeness gate needs to know.
    """

    @pytest.fixture(params=["llamacpp", "openai"])
    def backend(self, request: pytest.FixtureRequest) -> LLMBackend:
        if request.param == "llamacpp":
            return _llamacpp_backend()
        return _openai_backend()

    def test_has_required_members(self, backend: LLMBackend) -> None:
        assert callable(backend.transport)
        assert callable(backend.info)

    def test_info_returns_backend_info_shape(self, backend: LLMBackend) -> None:
        info = backend.info()

        assert isinstance(info, BackendInfo)
        assert isinstance(info.model_id, str) and info.model_id
        assert info.quantization is None or isinstance(info.quantization, str)
        assert isinstance(info.context_length, int) and info.context_length > 0
        assert isinstance(info.license_tag, str) and info.license_tag

    def test_transport_returns_transport_out_shape(self, backend: LLMBackend) -> None:
        if isinstance(backend, OpenAIBackend):
            pytest.skip(
                "OpenAIBackend.transport() makes a real httpx call with no local stub point -- "
                "covered by test_openai_transport_parses_response_without_network below instead."
            )
        prompt = TransportPrompt(task="extract", text="the sky is blue", schema_hint={})
        out = backend.transport(prompt)

        assert isinstance(out, TransportOut)
        assert isinstance(out.json, dict)

    def test_full_protocol_isinstance_when_all_members_present(self) -> None:
        backend = _llamacpp_backend()
        assert hasattr(backend, "propose_bridge")
        assert hasattr(backend, "general_chat")
        assert isinstance(backend, LLMBackend)

    def test_partial_backend_fails_full_protocol_isinstance(self) -> None:
        backend = _openai_backend()
        assert not hasattr(backend, "propose_bridge")
        assert not hasattr(backend, "general_chat")
        # Documented, expected Python Protocol semantics -- NOT an assertion that OpenAIBackend
        # is broken. See this class's docstring.
        assert not isinstance(backend, LLMBackend)


class TestLlamaCppBackendTransportContract:
    """`LlamaCppBackend`-specific I/O contract, exercised without real weights."""

    def test_transport_parses_json_content(self) -> None:
        backend = _llamacpp_backend('{"a": 1, "b": "two"}')
        out = backend.transport(TransportPrompt(task="t", text="x"))

        assert out.json == {"a": 1, "b": "two"}
        assert isinstance(backend._llm, _StubLlama)
        assert len(backend._llm.calls) == 1

    def test_transport_falls_back_to_raw_on_invalid_json(self) -> None:
        backend = _llamacpp_backend("not json")
        out = backend.transport(TransportPrompt(task="t", text="x"))

        assert out.json == {"raw": "not json"}

    def test_propose_bridge_returns_guess_shape(self) -> None:
        backend = _llamacpp_backend(json.dumps({"guess": "42", "rationale": "because"}))
        out = backend.propose_bridge(
            TransportPrompt(task="t", text="x", schema_hint={"missing_slot": "count"})
        )

        assert out.json == {"guess": "42", "rationale": "because"}

    def test_propose_bridge_falls_back_to_none_guess_on_invalid_json(self) -> None:
        backend = _llamacpp_backend("garbled")
        out = backend.propose_bridge(TransportPrompt(task="t", text="x"))

        assert out.json == {"guess": None, "rationale": ""}

    def test_general_chat_returns_stripped_string(self) -> None:
        backend = _llamacpp_backend()
        backend._llm = _StubLlama("")  # unused by general_chat's own stub below
        backend._llm.create_chat_completion = lambda **kwargs: {  # type: ignore[method-assign]
            "choices": [{"message": {"content": "  hello there  "}}]
        }
        assert backend.general_chat("hi") == "hello there"


class TestOpenAIBackendTransportContract:
    """`OpenAIBackend`-specific I/O contract, exercised without real network calls."""

    def test_transport_parses_response_without_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        captured: dict[str, Any] = {}

        class _StubResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"choices": [{"message": {"content": '{"ok": true}'}}]}

        def _stub_post(url: str, json: dict[str, Any], headers: dict[str, Any], timeout: int) -> _StubResponse:  # noqa: A002
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _StubResponse()

        monkeypatch.setattr(httpx, "post", _stub_post)

        backend = _openai_backend()
        out = backend.transport(TransportPrompt(task="extract", text="hello"))

        assert isinstance(out, TransportOut)
        assert out.json == {"ok": True}
        assert captured["url"] == "https://example.invalid/v1/chat/completions"
        assert captured["json"]["model"] == "test-model"

    def test_transport_falls_back_to_raw_on_invalid_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        class _StubResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"choices": [{"message": {"content": "not json"}}]}

        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _StubResponse())

        backend = _openai_backend()
        out = backend.transport(TransportPrompt(task="extract", text="hello"))
        assert out.json == {"raw": "not json"}


# ---------------------------------------------------------------------------------------------
# DecisionBackend contract
# ---------------------------------------------------------------------------------------------


def _decision_questions() -> list[DecisionQuestion]:
    return [
        DecisionQuestion(id="q1", text="Is the applicant eligible?"),
        DecisionQuestion(id="q2", text="Risk level?", options=["low", "high"]),
    ]


def _mock_backend() -> MockBackend:
    return MockBackend()


def _deterministic_backend() -> DeterministicBackend:
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
            backend_id="deterministic-contract",
        )

    return DeterministicBackend(fn, backend_id="deterministic-contract")


class TestDecisionBackendContract:
    """Shared contract for every real (non-stub) `DecisionBackend` implementation.

    `MockBackend`/`DeterministicBackend` need no external dependency and are run for real
    (Mock*/Deterministic* both operate in-process on the given `state`/`questions`, per their
    own docstrings). `SystemOneHTTPBackend` and `OpenThaiSystemOneLocalBackend` are real
    implementations too, but each needs an external dependency this contract-loop fixture
    doesn't provide (a live HTTP server / the `openthai_systemone` package + model weights) --
    they get their own explicit test classes below (see tests/test_decision_backend.py) instead
    of being looped into this one.
    """

    @pytest.fixture(params=["mock", "deterministic"])
    def backend(self, request: pytest.FixtureRequest) -> DecisionBackend:
        if request.param == "mock":
            return _mock_backend()
        return _deterministic_backend()

    def test_is_runtime_checkable_decision_backend(self, backend: DecisionBackend) -> None:
        assert isinstance(backend, DecisionBackend)

    def test_decide_returns_decision_proposal_shape(self, backend: DecisionBackend) -> None:
        proposal = backend.decide(state={"eligible": True}, questions=_decision_questions())

        assert isinstance(proposal, DecisionProposal)
        assert isinstance(proposal.backend_id, str) and proposal.backend_id
        assert isinstance(proposal.rationale, str)
        assert isinstance(proposal.answers, list)
        for answer in proposal.answers:
            assert isinstance(answer, DecisionAnswer)
            assert isinstance(answer.question_id, str) and answer.question_id
            assert isinstance(answer.resolution, S4)
            assert 0.0 <= answer.probability <= 1.0

    def test_decide_never_asserts_authorization_only_proposes(self, backend: DecisionBackend) -> None:
        # Per decision/backend.py's own module docstring ("a model may propose, never
        # authorize"): DecisionProposal carries no ADMIT/HOLD/REJECT/ESCALATE field at all --
        # the contract is that this type cannot even express an authorization outcome.
        proposal = backend.decide(state={}, questions=_decision_questions())
        assert not hasattr(proposal, "authorization")
        assert not hasattr(proposal, "outcome")

    def test_decide_covers_every_given_question(self, backend: DecisionBackend) -> None:
        questions = _decision_questions()
        proposal = backend.decide(state={}, questions=questions)
        answered_ids = {a.question_id for a in proposal.answers}
        assert answered_ids == {q.id for q in questions}


class TestSystemOneHTTPBackendStub:
    """`SystemOneHTTPBackend` is now a REAL implementation (upgraded 2026-09-21, wired to the
    real OpenThai-SystemOne HTTP contract, verified against its Hugging Face/GitHub docs) -- this
    class name/comment is kept for history but the tests below reflect real behavior. Full
    contract coverage (request/response mapping, error handling) lives in
    tests/test_decision_backend.py::TestSystemOneHTTPBackend; this class keeps only the
    isinstance/Protocol-shape check that belongs alongside the other backend-contract tests."""

    def test_is_runtime_checkable_decision_backend(self) -> None:
        backend = SystemOneHTTPBackend(base_url="https://example.invalid")
        assert isinstance(backend, DecisionBackend)
