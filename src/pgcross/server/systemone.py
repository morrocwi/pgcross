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
`server/decision.py` documents). `state` + `instructions` become the query text; the real
Verify/Authorize-stage `AuthorizationResult` determines the typed answer.

INTERPRETIVE MAPPING (the ONE place this happens, matching `decision/backend.py`'s own documented
precedent for the reverse direction): stated explicitly because `AuthorizationResult` carries no
numeric probability field (only `status`/`reason`/`stakes`, see `decision/schema.py`) — inventing
false precision here would violate this project's own readout-not-truth discipline.
  - ADMIT + tier `Th_coqc`/`finite_diagnostic` -> 1.0 (the tier ladder's own top two rungs:
    machine-verified / independently cross-checked)
  - ADMIT + tier `Dr` -> 0.85 (source-attributed, single-path computation)
  - ADMIT + tier `Wf` -> 0.65 (working-framework consistency only)
  - ADMIT + tier `Open`, or any HOLD/REJECT/ESCALATE -> 0.0 ("no" for `noul`; the request's own
    lowest-confidence choice/score option, since pgcross found nothing it will stand behind)
  This is a DECLARED, DOCUMENTED FLOOR MAPPING off the existing I1 tier ladder (README's "Tier
  ladder" section) — not a measured probability, and not the same thing as a real DecisionBackend's
  own probability (a genuinely measured model output, see `_openthai_response_to_proposal`). Never
  conflate the two; a caller reading this endpoint's probabilities should know they are reading a
  tier floor, not a model's confidence score.

`score`/`choice` answer selection is a best-effort substring match of the primary candidate's
content against the request's own criteria/levels — documented as a heuristic, not NLU, since
building real classification here would itself be exactly the un-grounded guessing this project's
I2 invariant exists to prevent.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..core.enums import Tier
from ..decision.schema import AuthorizationStatus
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
        try:
            resp = run_pipeline(query, ctx)
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
        answers[qid] = _answer_one(question, resp, resp.authorization.status)

    return {"answers": answers, "request_id": "systemone-" + uuid.uuid4().hex[:24]}
