"""DecisionBackend protocol — typed decisions with probabilities, distinct from LLMBackend.

`backends/base.py`'s `LLMBackend` protocol is transport-only (I7 structure-extraction: it may
never assert a fact or a number, see `LLMBackend.transport`'s docstring). `DecisionBackend` is a
different contract: it is only ever reached after the witness-before-model / resolution-gate
sequence in the project's architecture design notes (Toledo `A3`, `witness_sound`/
`witness_complete`/`decide_reflect`, all `Th_coqc`) has already found no finite witness and no
resolved readout — at that point a `DecisionBackend` may PROPOSE a typed answer with a
probability, never authorize one. Per the project's internal architecture audit notes (Backends
section) and the architecture design notes §3/§6a: "a model may propose, never authorize" — every
`DecisionProposal` this protocol returns still must pass PGCross's own Verify/Authorize gate
(`authorization/policy.py`, a separate stream) before it can become an ADMIT/HOLD/REJECT/ESCALATE
outcome.

`decision/schema.py` (Phase 2, item 16 of the project's internal task-tracking notes) is the
reconciled owner of `DecisionQuestion`/`DecisionProposal` going forward (Stream 3's design, per
Phase 0 item 1's maintainer resolution). This module checks for that file first and imports from
it; only if it has
not landed yet does it define minimal pydantic stand-in types locally, so this module never forks
a second, competing schema.

FAILURE POLICY (binding contract of this Protocol): if a `DecisionBackend.decide()` call fails,
times out, or otherwise cannot produce a `DecisionProposal`, it is the CALLER's responsibility —
not this module's — to default the outcome to HOLD. This module deliberately implements no
retry/fallback/timeout logic; that belongs in `authorization/policy.py` (a distinct stream, per
the project's architecture design notes §2.3's "Witness before Model" rule and the resolution-gate
design). A backend implementation here is free to raise on failure; it must not silently invent a
proposal.
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

try:
    # Stream 3's reconciled schema (internal task-tracking notes, Phase 2, item 16), if it has landed.
    # NOTE: schema.py's DecisionAnswer field is `resolution`, not `value` (see this module's
    # MockBackend.decide(), which constructs it accordingly) -- the two schemas were originally
    # drafted independently (Phase 0 item 1's three-way conflict) and this is the reconciliation.
    from .schema import (  # type: ignore[import-not-found]
        S4,
        DecisionAnswer,
        DecisionProposal,
        DecisionQuestion,
    )
except ImportError:
    from enum import Enum

    from pydantic import BaseModel, Field, field_serializer

    class S4(str, Enum):
        """Determinate-positive/negative/zero, plus the distinct unresolved state.

        Per Toledo `D/M.65.v1` (`neutral_distinct_from_bottom`, Th_coqc): `Sz <> Sbot` —
        "determinate zero" and "unresolved" are formally distinct constructors and must never be
        collapsed into each other (never coerce `BOT` into `None`/falsy/zero at a serialization
        boundary). See the project's architecture design notes §2.4.
        """

        POS = "POS"
        NEG = "NEG"
        ZERO = "ZERO"
        BOT = "BOT"  # unresolved — maps to HOLD, never to ZERO

    class DecisionQuestion(BaseModel):
        """A single typed question posed to a DecisionBackend.

        Minimal stand-in only — `decision/schema.py` (once Stream 3 lands) is the reconciled
        owner; this shape exists so `DecisionBackend` has something concrete to type against in
        the meantime, per the project's architecture design notes §3.
        """

        id: str
        text: str
        options: list[str] = Field(default_factory=list)  # empty = open/free-form answer

    class DecisionAnswer(BaseModel):
        """One answer to one `DecisionQuestion`, carrying an `S4` state and a probability."""

        question_id: str
        value: S4
        label: str | None = None  # free-form content when value is POS/NEG and options is empty
        probability: float = 0.0  # in [0, 1]; meaningless/ignored when value is BOT

        @field_serializer("value")
        def _ser_value(self, v: S4) -> str:
            return v.value

    class DecisionProposal(BaseModel):
        """A DecisionBackend's proposal for a batch of questions — NEVER an authorization.

        Per the project's architecture design notes §3: this always passes back through PGCross's
        Verify/Authorize gate before it can become ADMIT/HOLD/REJECT/ESCALATE; confidence here
        never bypasses a failed gate (F1).
        """

        answers: list[DecisionAnswer]
        backend_id: str
        rationale: str = ""


@runtime_checkable
class DecisionBackend(Protocol):
    """Typed-decision proposer: `decide(state, questions) -> DecisionProposal`.

    Distinct from `backends.base.LLMBackend` (transport-only, I7-constrained structure
    extraction). A `DecisionBackend` is allowed to propose values with probabilities that are not
    literally present in `state` — but, per the PGCross Next letter's rule ("a model may propose,
    never authorize"), a `DecisionProposal` is never itself an ADMIT/HOLD/REJECT/ESCALATE outcome;
    it is only ever an input to `authorization/policy.py`'s gate.

    FAILURE POLICY: on failure/timeout, the CALLER defaults to HOLD — see module docstring. This
    Protocol and its implementations below do not retry or fall back internally.
    """

    def decide(
        self, state: dict, questions: list[DecisionQuestion]
    ) -> DecisionProposal:
        """Propose typed answers to `questions` given `state`. May raise on failure — the caller,
        not this method, is responsible for defaulting to HOLD (see module docstring)."""
        ...


class MockBackend:
    """Returns a configurable, canned `DecisionProposal` — for tests and offline development.

    Construct with a fixed `proposal` (returned verbatim from every `decide()` call), or leave it
    unset to get an all-`BOT` (unresolved) proposal covering the given questions, which is the
    honest default when no canned answer was configured.
    """

    def __init__(self, proposal: DecisionProposal | None = None, backend_id: str = "mock") -> None:
        self._proposal = proposal
        self._backend_id = backend_id

    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
        if self._proposal is not None:
            return self._proposal
        return DecisionProposal(
            answers=[
                DecisionAnswer(question_id=q.id, resolution=S4.BOT, probability=0.0)
                for q in questions
            ],
            backend_id=self._backend_id,
            rationale="MockBackend: no canned proposal configured — returning BOT (unresolved) "
            "for every question, per D/M.65.v1 (BOT is never silently coerced to ZERO/False).",
        )


class DeterministicBackend:
    """Wraps a plain Python callable `(state, questions) -> DecisionProposal` — no model call.

    For gates that ARE resolvable by code (e.g. an `A3`-style finite witness check, per
    the project's architecture design notes §2.3) but still want to be called uniformly through the
    `DecisionBackend` interface, so callers do not need to special-case "this one is deterministic"
    at the call site.
    """

    def __init__(
        self,
        fn: Callable[[dict, list[DecisionQuestion]], DecisionProposal],
        backend_id: str = "deterministic",
    ) -> None:
        self._fn = fn
        self._backend_id = backend_id

    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
        return self._fn(state, questions)


class SystemOneHTTPBackend:
    """STUB — OpenThai-SystemOne HTTP integration is NOT implemented in this pass.

    Per Phase 0 item 2 of the project's internal task-tracking notes, OpenThai-SystemOne is confirmed as the production
    `DecisionBackend`, but wiring the real HTTP API contract is separate, real integration work
    (needs the actual request/response shape, auth, timeout/retry semantics) that this pass
    deliberately does not fake. This class documents the interface shape only — its constructor
    accepts the connection parameters a real implementation would need; `decide()` always raises.
    """

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url
        self.api_key = api_key

    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
        raise NotImplementedError(
            "SystemOneHTTPBackend: OpenThai-SystemOne HTTP integration not yet implemented -- "
            "see the project's internal task-tracking notes, item 31"
        )
