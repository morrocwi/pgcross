"""server/systemone.py — `POST /v1/systemone`, pgcross AS a TypeSafe/Jev-compatible System One
*provider*, not just a consumer.

`decision/backend.py`'s `SystemOneHTTPBackend` is the CLIENT side (pgcross calling out to an
OpenThai-SystemOne-compatible server). This module is the SERVER side: any Jev/TypeSafe-compatible
client — including `SystemOneHTTPBackend` pointed back at this same process — can call pgcross for
typed decisions. Wire contract matches `SystemOneHTTPBackend`'s request/response shape exactly
(checked against that module's own implementation 2026-09-21, the two are meant to be tested
against each other):

    request:  {"state": {...}, "questions": {"<qid>": {"type": "noul"|"score"|"choice",
                                                         "instructions": str, "criteria": ...}}}
    response: {"answers": {"<qid>": {"noul": float}
                                   | {"score": str, "confidence": float, "probabilities": {...}}
                                   | {"choice": str, "probabilities": {...}}}}

Every question is answered by running it through pgcross's OWN `run_pipeline()` — never a
separate, weaker code path (same "`run_pipeline()` is the single source of truth" invariant
`server/decision.py` documents). `state` + `instructions` become the query text passed to the
deterministic pipeline; the caller's REAL typed question is ALSO threaded through as
`QueryIR.decision_question` (see `core/models.py`) so that if no deterministic path resolves it,
`pipeline/authorize.py`'s witness-before-model gate asks the model THIS question directly, not a
synthetic "is the fallback candidate admissible" one.

**Real bug found and fixed live 2026-09-21**: before this fix, this endpoint discarded the
caller's typed question entirely once inside the pipeline, so a trivially-true factual question
("is the Eiffel Tower in Paris?") got back a confident "no" — the model was being asked whether
a generic CONSULTATION placeholder was an admissible answer, not the caller's real question. See
`pipeline/authorize.py::_authorize_status`'s own docstring for the full incident writeup.

TWO answer sources, used in this priority order (the ONE place both are documented):
  1. **`resp.authorization.model_proposal`** (real, when set) — a `decision_backend` answered the
     caller's REAL typed question directly (no deterministic path existed). Its `label`/
     `probability`/`probabilities` are used verbatim (converted to this endpoint's wire shape,
     see `_answer_from_model_proposal` below) — a genuinely measured model output, not invented.
  2. **The declared tier-floor mapping** (when `model_proposal` is `None` — a deterministic path
     DID resolve it, or the harm-net fired, or no `decision_backend` is configured at all):
     `AuthorizationResult` carries no numeric probability field in this case (only
     `status`/`reason`/`stakes`) — inventing false precision here would violate this project's
     own readout-not-truth discipline, so a DECLARED FLOOR off the existing I1 tier ladder is used
     instead: ADMIT + tier `Th_coqc`/`finite_diagnostic` -> 1.0, ADMIT + tier `Dr` -> 0.85, ADMIT
     + tier `Wf` -> 0.65, ADMIT + tier `Open` or any HOLD/REJECT/ESCALATE -> 0.0. Never conflate
     this floor with a real model probability; a caller reading this endpoint's probabilities in
     this branch should know they are reading a tier floor.

`score`/`choice` answer selection for the tier-floor branch ONLY is a best-effort substring match
of the primary candidate's content against the request's own criteria/levels — documented as a
heuristic, not NLU. The `model_proposal` branch never needs this heuristic; it uses the model's
own real answer.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..core.enums import Tier
from ..decision.schema import AuthorizationStatus, DecisionQuestion
from ..pipeline.run import HarmfulRequest, run_pipeline

router = APIRouter()

_TIER_FLOOR_PROBABILITY = {
    Tier.Th_coqc: 1.0,
    Tier.finite_diagnostic: 1.0,
    Tier.Dr: 0.85,
    Tier.Wf: 0.65,
    Tier.Open: 0.0,
}


class SystemOneRequest(BaseModel):
    state: dict = {}
    questions: dict[str, dict]


def _query_text(state: dict, instructions: str) -> str:
    if not state:
        return instructions
    return f"{instructions} (context: {state!r})"


def _to_decision_question(qid: str, question: dict) -> DecisionQuestion:
    """Wire-format question dict -> the real, typed `DecisionQuestion` a `decision_backend`
    can answer directly, threaded through `run_pipeline(..., decision_question=...)`."""
    kind = question.get("type", "choice")
    instructions = question.get("instructions", "")
    if kind == "noul":
        return DecisionQuestion(id=qid, text=instructions, kind="noul")
    if kind == "score":
        return DecisionQuestion(id=qid, text=instructions, kind="score",
                                 levels=list(question.get("criteria", [])))
    criteria = question.get("criteria", {})
    if isinstance(criteria, dict):
        return DecisionQuestion(id=qid, text=instructions, kind="choice", option_descriptions=criteria)
    return DecisionQuestion(id=qid, text=instructions, kind="choice", options=list(criteria))


def _score_index(label: str | None, n_levels: int) -> int:
    """A `kind="score"` `DecisionAnswer.label` is a float string -- a continuous weighted-average
    index into `levels`, not level text verbatim (confirmed live 2026-09-21 by a real `decide()`
    call before this was written, same finding as `eval/jev_public_benchmark_suite.py`'s own
    `_score_index` helper -- duplicated here rather than imported, since `eval/` is dev/benchmark
    tooling this server module must not depend on). Rounds to the nearest valid index, clamped.

    `DecisionBackend` is a `Protocol` (decision/backend.py), an open extensibility point -- every
    first-party backend always sets `label` to a real numeric string for `kind="score"`, but a
    non-conforming third-party implementation could return `label=None` or a non-numeric string.
    Caught by an independent review before this endpoint's first push: defaults to the middle
    level (the least-wrong single guess when the answer itself is malformed) rather than raising
    a 500 and crashing the request -- this is a defensive fallback for a backend violating its
    own documented contract, not a case this project's first-party backends can ever hit."""
    if label is None:
        return n_levels // 2
    try:
        idx = round(float(label))
    except (TypeError, ValueError):
        return n_levels // 2
    return max(0, min(n_levels - 1, idx))


def _answer_from_model_proposal(question: dict, answer) -> dict:
    """Convert a REAL `DecisionAnswer` (from `resp.authorization.model_proposal`) into this
    endpoint's wire shape. This is a real, measured model output -- see module docstring's
    priority-order note; never falls back to the tier-floor heuristic."""
    kind = question.get("type", "choice")
    if kind == "noul":
        return {"noul": answer.probability}
    if kind == "score":
        levels = list(question.get("criteria", []))
        if not levels:
            return {"score": None, "confidence": answer.probability, "probabilities": {}}
        idx = _score_index(answer.label, len(levels))
        picked = levels[idx]
        return {"score": picked, "confidence": answer.probability,
                "probabilities": {levels[int(k)]: v for k, v in answer.probabilities.items()
                                   if k.isdigit() and int(k) < len(levels)}}
    # "choice"
    return {"choice": answer.label, "probabilities": dict(answer.probabilities)}


def _floor_probability(status: AuthorizationStatus, tier) -> float:
    if status != AuthorizationStatus.ADMIT:
        return 0.0
    return _TIER_FLOOR_PROBABILITY.get(tier, 0.0)


def _best_match(content: str, options: list[str]) -> str | None:
    """Best-effort substring match, not NLU — see module docstring. Returns None (caller then
    picks the lowest-confidence/first option) rather than guessing when nothing matches."""
    content_lower = content.lower()
    for opt in options:
        if opt.lower() in content_lower:
            return opt
    return None


def _answer_one(question: dict, resp, status: AuthorizationStatus) -> dict:
    primary = resp.candidates[resp.primary]
    probability = _floor_probability(status, primary.tier)
    kind = question.get("type", "choice")

    if kind == "noul":
        return {"noul": probability}

    if kind == "score":
        levels = list(question.get("criteria", []))
        if not levels:
            return {"score": None, "confidence": 0.0, "probabilities": {}}
        picked = _best_match(primary.content, levels) if probability > 0.0 else None
        picked = picked or levels[0]
        confidence = probability if picked in levels else 0.0
        return {"score": picked, "confidence": confidence, "probabilities": {picked: confidence}}

    # "choice" (default)
    criteria = question.get("criteria", {})
    options = list(criteria.keys()) if isinstance(criteria, dict) else list(criteria)
    if not options:
        return {"choice": None, "probabilities": {}}
    picked = _best_match(primary.content, options) if probability > 0.0 else None
    picked = picked or options[0]
    confidence = probability if picked in options else 0.0
    return {"choice": picked, "probabilities": {picked: confidence}}


@router.post("/v1/systemone")
async def systemone(req: SystemOneRequest, request: Request) -> dict:
    ctx = request.app.state.ctx
    answers: dict[str, dict] = {}

    for qid, question in req.questions.items():
        instructions = question.get("instructions", "")
        query = _query_text(req.state, instructions)
        decision_question = _to_decision_question(qid, question)
        try:
            resp = run_pipeline(query, ctx, decision_question=decision_question, decision_state=req.state)
        except HarmfulRequest:
            # Refused before Verify/Authorize ever ran — report as "no"/lowest-confidence rather
            # than fabricating a resolved answer for a query the pipeline never actually assessed.
            kind = question.get("type", "choice")
            if kind == "noul":
                answers[qid] = {"noul": 0.0}
            elif kind == "score":
                levels = list(question.get("criteria", []))
                answers[qid] = {"score": levels[0] if levels else None, "confidence": 0.0, "probabilities": {}}
            else:
                criteria = question.get("criteria", {})
                options = list(criteria.keys()) if isinstance(criteria, dict) else list(criteria)
                answers[qid] = {"choice": options[0] if options else None, "probabilities": {}}
            continue
        model_proposal = resp.authorization.model_proposal
        if model_proposal is not None and model_proposal.answers:
            answers[qid] = _answer_from_model_proposal(question, model_proposal.answers[0])
        else:
            answers[qid] = _answer_one(question, resp, resp.authorization.status)

    return {"answers": answers, "request_id": "systemone-" + uuid.uuid4().hex[:24]}
