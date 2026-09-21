"""tests/test_systemone_endpoint.py — POST /v1/systemone, pgcross as a Jev/TypeSafe provider.

Full-circle proof this contract is real (not just internally self-consistent): this suite hits
the endpoint through FastAPI's TestClient directly, AND (see test_full_circle_via_real_backend_
client below) through pgcross's own SystemOneHTTPBackend client -- the exact class that talks to
a real OpenThai-SystemOne server -- confirming the two sides of this project's own wire contract
actually agree with each other.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from pgcross.core.provider import Registry
from pgcross.decision.backend import DecisionAnswer, S4, SystemOneHTTPBackend
from pgcross.decision.schema import DecisionQuestion
from pgcross.pipeline.run import Config, Ctx
from pgcross.server.app import create_app


def _client() -> TestClient:
    cfg = Config()
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda t: False)
    app = create_app(ctx, allow_unsafe_dev=True)
    return TestClient(app)


def test_noul_question_returns_a_probability_in_range() -> None:
    client = _client()
    resp = client.post("/v1/systemone", json={
        "state": {},
        "questions": {"q1": {"type": "noul", "instructions": "Is this admissible?"}},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "q1" in body["answers"]
    assert 0.0 <= body["answers"]["q1"]["noul"] <= 1.0


def test_choice_question_returns_one_of_the_given_options() -> None:
    client = _client()
    resp = client.post("/v1/systemone", json={
        "state": {},
        "questions": {"q1": {"type": "choice", "instructions": "Risk level?",
                              "criteria": {"low": "low risk", "high": "high risk"}}},
    })
    body = resp.json()
    assert body["answers"]["q1"]["choice"] in ("low", "high")


def test_score_question_returns_one_of_the_given_levels() -> None:
    client = _client()
    resp = client.post("/v1/systemone", json={
        "state": {},
        "questions": {"q1": {"type": "score", "instructions": "Rate confidence",
                              "criteria": ["poor", "fair", "good"]}},
    })
    body = resp.json()
    assert body["answers"]["q1"]["score"] in ("poor", "fair", "good")


def test_multiple_questions_all_answered() -> None:
    client = _client()
    resp = client.post("/v1/systemone", json={
        "state": {"query": "10*10"},
        "questions": {
            "a": {"type": "noul", "instructions": "Is 100 correct?"},
            "b": {"type": "choice", "instructions": "Domain?", "criteria": {"math": "math", "other": "other"}},
        },
    })
    body = resp.json()
    assert set(body["answers"].keys()) == {"a", "b"}


def test_empty_criteria_does_not_crash() -> None:
    client = _client()
    resp = client.post("/v1/systemone", json={
        "state": {},
        "questions": {"q1": {"type": "choice", "instructions": "Pick one", "criteria": {}}},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["answers"]["q1"]["choice"] is None


def test_full_circle_via_real_systemone_http_backend_client() -> None:
    """Proves the two halves of this project's own wire contract actually agree: pgcross's own
    SystemOneHTTPBackend client (the same class that talks to a real OpenThai-SystemOne server)
    is pointed at pgcross's own /v1/systemone endpoint via TestClient's transport."""
    client = _client()
    backend = SystemOneHTTPBackend(base_url="http://testserver")
    backend._transport = client._transport  # TestClient-only wiring; a real deployment uses a real URL

    proposal = backend.decide(
        state={"query": "10*10"},
        questions=[DecisionQuestion(id="admissible", text="Is 100 correct for 10*10?", kind="noul")],
    )
    assert len(proposal.answers) == 1
    answer = proposal.answers[0]
    assert isinstance(answer, DecisionAnswer)
    assert answer.question_id == "admissible"
    assert isinstance(answer.resolution, S4)
    assert 0.0 <= answer.probability <= 1.0
