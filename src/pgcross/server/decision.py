"""server/decision.py — `POST /v1/decision`, the Decision Forge's own structured endpoint.

Phase 4 (internal task-tracking notes, items 25-26). Follows `responses_api.py`'s precedent: a
thin `APIRouter()`, reads `request.app.state.ctx`, calls `run_pipeline()` — never duplicates
pipeline logic (per the project's internal architecture audit notes' invariant:
"`run_pipeline()` is the single source of truth — no endpoint duplicates pipeline logic").

**Design choice, documented per the task spec's "your call, document the choice":** this endpoint
calls `run_pipeline()` (the same call `chat.py`/`responses_api.py` already make) rather than
calling `verify()`/`authorize()` more directly. Reason: `run_pipeline()` is what actually wires
`ground()`/`compose()`/`route()`/`assemble()` (which itself calls `verify()` then `authorize()`,
see `pipeline/assemble.py`) plus the F1-gated `imagine_bridge`/`_general_chat_fallback` post-steps
together with `_reassert_f1_gate()` — reconstructing that sequence here to call `verify()`/
`authorize()` "more directly" would itself be exactly the kind of pipeline-logic duplication the
architecture map's invariant forbids, for a v1 endpoint that has no other reason to bypass any of
those steps. `run_pipeline()`'s return type is annotated `Response` but the live pipeline always
constructs it via `assemble() -> authorize()`, which returns `AuthorizedResponse` (a `Response`
subclass carrying `.authorization`, see `pipeline/authorize.py`) — this endpoint reads
`.authorization` directly off the returned object rather than re-deriving it.

**Honesty note on field provenance (per `CLAIMS.md`/`NON_CLAIMS.md`'s discipline — do not overclaim
completeness this endpoint does not have):**
  - `readout`: `run_pipeline()`'s return contract is `Response`/`AuthorizedResponse` only — it does
    NOT hand back the internal `QueryIR` (`q`), so `q.slots` is not reachable from this endpoint
    without re-running `ground()` ourselves, which would duplicate pipeline logic (see above). This
    field is therefore always the raw query text today, never `q.slots` — the docstring in
    `server/decision_schema.py`'s `DecisionResponse` states this as a known v1 gap, not a silent
    omission. A future stream could thread `q` through `run_pipeline()`'s return value (e.g. as an
    attribute on `AuthorizedResponse`) to close this honestly, without this endpoint reaching around
    it in the meantime.
  - `route`: no explicit "route" field exists anywhere in `Response`/`EvidenceCandidate` today
    (per the project's internal architecture audit notes' own finding) — the primary candidate's
    `provider_id` is the closest existing signal and is used as a proxy, not a real route field.
  - `proposal`: the primary candidate's `content` + `declared_tier` — Phase A's own finding is that
    today's `pgcross.candidates` block IS already proposal-like data; this is that same data
    reshaped for this endpoint, not a new Propose-stage computation.
  - `sources`: `grounding_refs` off the primary candidate only (not every candidate) — matches
    "sources" reading as "what backs the thing we are proposing", i.e. the primary.
  - `verification`: built from each candidate's `tier`/`floor_reason` — the closest existing
    signal. The real per-candidate `VerifierResult` (`ok`/`detail`) that `verify()` computes is not
    persisted onto the candidate and so is not threaded through to this endpoint either — this is
    the exact same gap `pipeline/authorize.py`'s `_witness_probe()` already documents for its own
    proxy reconstruction. Do not read `verification` here as "the real verifier output"; read it as
    "the tier/floor-reason readout that survived to this point."
  - `authorization`/`provenance`: real pipeline output, read directly off
    `resp.authorization`/the primary candidate's `provenance`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from .decision_schema import DecisionRequest, DecisionResponse
from ..pipeline.run import run_pipeline, HarmfulRequest

router = APIRouter()


def _map_to_decision_response(resp, request_id: str, query: str) -> DecisionResponse:
    """The one explicit `AuthorizedResponse` -> `DecisionResponse` adapter (see this module's
    docstring for the honesty notes on each field's real-vs-best-effort provenance)."""
    primary = resp.candidates[resp.primary]
    auth = resp.authorization  # AuthorizationResult (decision/schema.py) — see docstring above

    proposal = {
        "content": primary.content,
        "declared_tier": primary.declared_tier.name,
    }
    verification = [
        {
            "provider_id": c.provider_id,
            "tier": c.tier.name if c.tier is not None else None,
            "floor_reason": c.floor_reason,
        }
        for c in resp.candidates
    ]
    authorization = {
        "status": auth.status.value,
        "reasons": [auth.reason],
    }
    provenance = primary.provenance.model_dump()

    return DecisionResponse(
        request_id=request_id,
        readout={"query": query},  # see docstring: q.slots is not reachable from run_pipeline()
        route=primary.provider_id,
        proposal=proposal,
        sources=list(primary.grounding_refs),
        verification=verification,
        authorization=authorization,
        provenance=provenance,
    )


@router.post("/v1/decision", response_model=DecisionResponse)
async def decision(req: DecisionRequest, request: Request) -> DecisionResponse:
    ctx = request.app.state.ctx
    request_id = "decision-" + uuid.uuid4().hex[:24]

    try:
        resp = run_pipeline(req.query, ctx)
    except HarmfulRequest:
        # No AuthorizedResponse was produced at all (ctx.safety fired before assemble()/authorize()
        # ever ran) — report the refusal honestly as ESCALATE rather than fabricating candidate/
        # proposal fields that were never computed.
        return DecisionResponse(
            request_id=request_id,
            readout={"query": req.query},
            route=None,
            proposal=None,
            sources=[],
            verification=[],
            authorization={
                "status": "ESCALATE",
                "reasons": ["ctx.safety pre-pipeline gate fired before the Verify/Authorize stage ran"],
            },
            provenance={},
        )

    return _map_to_decision_response(resp, request_id, req.query)
