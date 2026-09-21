"""server/decision_schema.py — wire-format Pydantic models for `POST /v1/decision`.

Phase 4 (internal task-tracking notes, items 25-26, an internal implementation handoff note).
Kept in its own module, separate from `server/schema.py` (chat-only models), per that file's own
precedent note ("a new decision schema goes in its own module") and the project's internal
architecture audit notes' incident record on not hand-rolling a second divergent contract.

`AuthorizationStatus` is imported from `decision/schema.py`, never redefined as a new `Literal` —
this repo already found (per the project's internal architecture audit notes, contradiction #5)
that a silently
diverging second contract for the same concept is a real, previously-committed bug class. A FOURTH
divergent ADMIT/HOLD/REJECT/ESCALATE definition would repeat exactly that mistake.

`DecisionRequest` is deliberately permissive/minimal for v1 (a single free-text `query` is the
common case, matching `chat.py`/`responses_api.py`'s existing single-turn/free-text scope) —
`state`/`questions` are reserved fields for a future `DecisionBackend`-driven multi-question flow
(`decision/schema.py`'s `DecisionQuestion`/`DecisionProposal`) that is not wired into the live
pipeline yet (see `pipeline/authorize.py`'s `_authorize_status` docstring on that gap).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..decision.schema import AuthorizationStatus

__all__ = ["DecisionRequest", "DecisionResponse"]


class DecisionRequest(BaseModel):
    """`POST /v1/decision` request body.

    `state`/`questions` are accepted but NOT YET consumed by `server/decision.py` — the live
    pipeline (`run_pipeline()`) only reads free text today (see `pipeline/run.py`). They are kept
    here, typed but optional, so the wire shape does not need to change again once a
    `DecisionBackend` is wired in (Phase C, the project's architecture design notes §3/§6a).
    """

    query: str
    state: dict | None = None
    questions: dict | None = None


class DecisionResponse(BaseModel):
    """`POST /v1/decision` response body.

    Field-by-field honesty note (per this project's own `CLAIMS.md`/`NON_CLAIMS.md` discipline —
    see `server/decision.py`'s mapping function for the full commentary): `readout`, `route`,
    `proposal`, `sources`, `authorization`, and `provenance` are real pipeline output (read off the
    `AuthorizedResponse` `run_pipeline()` already returns). `verification` is a best-effort
    reconstruction from each candidate's `tier`/`floor_reason` — the real per-candidate
    `VerifierResult` detail is not threaded through past `pipeline/verify.py` today (the same gap
    `pipeline/authorize.py`'s `_witness_probe()` already documents for the witness proxy).
    """

    request_id: str
    readout: dict
    route: str | None
    proposal: dict | None
    sources: list[str]
    verification: list[dict]
    authorization: dict
    provenance: dict

    # Re-exported so a caller can import the canonical enum from this module too, without a
    # second import of `decision.schema` — does not change the response body shape.
    model_config = {"json_schema_extra": {"authorization_status_values": [s.value for s in AuthorizationStatus]}}
