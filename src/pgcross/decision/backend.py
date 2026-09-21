"""DecisionBackend protocol — typed decisions with probabilities, distinct from LLMBackend.

`backends/base.py`'s `LLMBackend` protocol is transport-only (I7 structure-extraction: it may
never assert a fact or a number, see `LLMBackend.transport`'s docstring). `DecisionBackend` is a
different contract: it is only ever reached after the witness-before-model / resolution-gate
sequence in the project's architecture design notes (Toledo's `A3`, `witness_sound`/
`witness_complete`/`decide_reflect`, all `Th_coqc`) has already found no finite witness and no
resolved readout — at that point a `DecisionBackend` may PROPOSE a typed answer with a
probability, never authorize one. Per the project's internal architecture audit notes (Backends
section) and the architecture design notes §3/§6a: "a model may propose, never authorize" — every
`DecisionProposal` this protocol returns still must pass PGCross's own Verify/Authorize gate
(`authorization/policy.py`, a separate stream) before it can become an ADMIT/HOLD/REJECT/ESCALATE
outcome.

`decision/schema.py` (Phase 2, item 16 of the project's internal task-tracking notes) is the
reconciled owner of `DecisionQuestion`/`DecisionProposal` going forward, per the project's
internal task-tracking notes' Phase 0 item 1 maintainer resolution. This module checks for that file first and imports from
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
    # this module's reconciled schema (internal task-tracking notes, Phase 2, item 16), if it has landed.
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

        Per Toledo's `D/M.65.v1` (`neutral_distinct_from_bottom`, Th_coqc): `Sz <> Sbot` —
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

        Minimal stand-in only — `decision/schema.py` (once this module's design lands) is the reconciled
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


class OpenThaiSystemOneNotInstalledError(ImportError):
    """Raised by `OpenThaiSystemOneLocalBackend` when the `openthai_systemone` package cannot be
    imported. Same documented-failure discipline as `decision/computation_backend.py`'s
    `IDMNotInstalledError`: never silently no-op, never fabricate a proposal — raise a clear,
    actionable error instead."""

    def __init__(self, original: Exception | None = None) -> None:
        message = (
            "The 'openthai_systemone' package (OpenThai-SystemOne, iapp-technology, Apache-2.0) "
            "is not importable in this environment. OpenThaiSystemOneLocalBackend calls "
            "SystemOneClient(...).system_one(...) directly (same-machine Python call, no network "
            "hop) for lowest latency, matching this project's own 'code before model, local "
            "before network' preference. Install it with:\n"
            "    pip install openthai-systemone\n"
            "(or: pip install \"git+https://github.com/iapp-technology/openthai-systemone\"). "
            "Model weights (iapp/OpenThai-SystemOne, ~0.8B params, BF16) download from Hugging "
            "Face on first use via `transformers`. If local inference isn't feasible, use "
            "SystemOneHTTPBackend against a hosted or self-run OpenThai-SystemOne server instead."
        )
        super().__init__(message)
        self.__cause__ = original


def _validate_questions_before_any_heavy_work(questions: list["DecisionQuestion"]) -> None:
    """Pure-Python precondition check, no `openthai_systemone` import and no model/client
    involved -- deliberately called BEFORE `_get_client()` in `decide()` below so a malformed
    question fails fast (microseconds) rather than only after paying for a multi-GB model load
    (tens of seconds, real GPU/CPU memory) just to then reject the input. Found worth doing
    2026-09-21 after `_pgcross_questions_to_openthai`'s validation (below) turned out to run
    AFTER `_get_client()` in the original ordering, meaning even an instantly-rejectable bad
    question paid the full model-load cost first."""
    for q in questions:
        if q.kind == "choice" and not q.option_descriptions and not q.options:
            raise ValueError(
                f"DecisionQuestion {q.id!r} has kind='choice' but no options/"
                "option_descriptions -- OpenThai-SystemOne's Choice type requires at least "
                "one option. Set options=[...] or option_descriptions={...}, or use "
                "kind='noul' for a free-form yes/no/unresolved question instead."
            )


def _pgcross_questions_to_openthai(questions: list["DecisionQuestion"]) -> dict:
    """Map pgcross's `list[DecisionQuestion]` onto OpenThai-SystemOne's own typed-question dict
    shape (`{field_name: Choice(...) | Score(...) | Noul(...)}`) -- shared by both backends below
    so the local and HTTP transports build byte-identical requests from the same input.

    Import is local/lazy so this module has zero hard dependency on `openthai_systemone` just to
    be imported (matches `IDMBackend`'s pattern in `decision/computation_backend.py`) -- only
    actually calling a real OpenThai backend requires the package.
    """
    from openthai_systemone import Choice, Noul, Score  # type: ignore[import-not-found]

    out = {}
    for q in questions:
        if q.kind == "score":
            out[q.id] = Score(instructions=q.text, criteria=list(q.levels))
        elif q.kind == "noul":
            out[q.id] = Noul(instructions=q.text)
        else:  # "choice" (default) -- criteria is a dict; fall back to label==description
            criteria = q.option_descriptions or {opt: opt for opt in q.options}
            if not criteria:
                # Real bug caught by this module's own end-to-end verification 2026-09-21: an
                # empty-options "choice" DecisionQuestion reached OpenThai's `Choice` pydantic
                # model, which rejects it with an opaque upstream ValidationError. This is a
                # caller-side mistake (a choice question needs options), not something to paper
                # over -- but it deserves a clear, actionable pgcross-level error instead of a
                # confusing one from a dependency's internals.
                raise ValueError(
                    f"DecisionQuestion {q.id!r} has kind='choice' but no options/"
                    "option_descriptions -- OpenThai-SystemOne's Choice type requires at least "
                    "one option. Set options=[...] or option_descriptions={...}, or use "
                    "kind='noul' for a free-form yes/no/unresolved question instead."
                )
            out[q.id] = Choice(instructions=q.text, criteria=criteria)
    return out


def _openthai_response_to_proposal(resp, backend_id: str) -> "DecisionProposal":
    """Map an OpenThai-SystemOne response object back onto pgcross's `DecisionProposal`.

    Interpretation (documented here since OpenThai's raw output is a probability distribution,
    not an S4 four-value state -- this is the ONE place that interpretive mapping happens):
      - `resolution = S4.POS` whenever the model returned a determinate answer at all (a chosen
        option, a score, or a yes/no) -- OpenThai's single-forward-pass design means it always
        answers (never itself returns "I don't know"); `S4.BOT` is reserved for THIS backend
        failing to get an answer at all (network/model error), never for "low confidence" -- a
        low-probability determinate answer is still a real, honestly-labeled proposal, and it is
        `authorization/policy.py`'s job (not this backend's) to decide whether that confidence is
        high enough to matter, per this project's "a model may propose, never authorize" rule.
      - `noul` (yes/no): `label` is `"yes"`/`"no"` per which side of 0.5 the probability falls;
        `probability` is that probability (of "yes" specifically, matching OpenThai's own
        convention) -- never coerced into POS/NEG on the resolution field itself, since resolution
        only tracks "did the model answer," not "what it answered."
      - `score`: `label` is the fractional score as a string; `probability` is OpenThai's own
        `confidence` value; `probabilities` carries the full per-level distribution.
      - `choice`: `label` is the chosen option; `probability` is that option's own probability;
        `probabilities` carries the full per-option distribution (up to 255 entries).
    """
    answers = []
    for qid, ans in resp.answers.items():
        if hasattr(ans, "noul"):
            p_yes = float(ans.noul)
            answers.append(DecisionAnswer(
                question_id=qid, resolution=S4.POS, label=("yes" if p_yes >= 0.5 else "no"),
                probability=p_yes,
            ))
        elif hasattr(ans, "score"):
            dist = dict(getattr(ans, "probabilities", {}) or {})
            answers.append(DecisionAnswer(
                question_id=qid, resolution=S4.POS, label=str(ans.score),
                probability=float(getattr(ans, "confidence", 0.0)), probabilities=dist,
            ))
        else:  # choice
            dist = dict(getattr(ans, "probabilities", {}) or {})
            answers.append(DecisionAnswer(
                question_id=qid, resolution=S4.POS, label=str(ans.choice),
                probability=float(dist.get(str(ans.choice), 0.0)), probabilities=dist,
            ))
    return DecisionProposal(answers=answers, backend_id=backend_id, rationale="")


class OpenThaiSystemOneLocalBackend:
    """`DecisionBackend` calling OpenThai-SystemOne (iapp-technology, Apache-2.0) IN-PROCESS via
    `openthai_systemone.SystemOneClient` -- direct Python call, no network hop, matching this
    project's "code before model, local before network" preference (the same reasoning
    `decision/computation_backend.py`'s `IDMBackend` already uses for `information-discrete-math`).

    A real client call, not a stub -- exercised end-to-end against real weights 2026-09-21
    (`pip install openthai-systemone`, model auto-downloaded from the Hugging Face Hub,
    `client ready in 75.2s`, `decide() in 0.6s`, returned a real `DecisionProposal`:
    `resolution=POS probability=0.911...`), not just checked against source docs: base
    `Qwen3.5-0.8B-Base`, 0.8B params, BF16 safetensors, Apache-2.0 license,
    single-forward-pass typed-decision head (Choice/Score/Noul question types, up to 255 options,
    up to 64k context). Raises `OpenThaiSystemOneNotInstalledError` (never fabricates a proposal)
    if the `openthai_systemone` package/model isn't available in this environment -- FAILURE
    POLICY per this module's docstring: the CALLER defaults to HOLD, this class does not retry.
    """

    def __init__(self, model: str = "iapp/OpenThai-SystemOne", backend_id: str = "openthai-systemone-local") -> None:
        self.model = model
        self._backend_id = backend_id
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openthai_systemone import SystemOneClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OpenThaiSystemOneNotInstalledError(exc) from exc
        self._client = SystemOneClient(self.model)
        return self._client

    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
        _validate_questions_before_any_heavy_work(questions)  # fail fast, before any model load
        client = self._get_client()  # raises OpenThaiSystemOneNotInstalledError, never fakes a result
        ot_questions = _pgcross_questions_to_openthai(questions)
        resp = client.system_one(state=state, questions=ot_questions)
        return _openthai_response_to_proposal(resp, self._backend_id)


class SystemOneHTTPBackend:
    """`DecisionBackend` calling a TypeSafe-compatible `POST /v1/systemone` server -- the HTTP
    transport for OpenThai-SystemOne (or any other TypeSafe-System-One-compatible server), for
    when in-process/same-machine inference (`OpenThaiSystemOneLocalBackend`) isn't available --
    e.g. the model is hosted remotely, or this process shouldn't carry the `transformers`/model
    weight footprint itself. Per the letter's own Jev section: this stays provider-neutral (no
    TypeSafe-specific branding baked in beyond the wire contract itself), and never claims
    affiliation with TypeSafe or implies this is an official Jev/TypeSafe product.

    Request/response shape checked against the real OpenThai-SystemOne server source
    2026-09-21 (`openthai_systemone.server:app`, launched via `uvicorn`) -- a source-doc read,
    not a run against a live server; this class has not yet been exercised against one. Uses
    `httpx` (already a core pgcross dependency, see `pyproject.toml`) -- no new dependency for
    this transport.
    """

    def __init__(
        self, base_url: str, api_key: str | None = None, timeout: float = 30.0,
        backend_id: str = "openthai-systemone-http",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._backend_id = backend_id
        self._transport = None  # test-only injection point (httpx.MockTransport); None = real network

    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal:
        import httpx

        # Build the wire JSON directly from DecisionQuestion's own fields -- deliberately does
        # NOT import the `openthai_systemone` Python package (unlike the shared
        # `_pgcross_questions_to_openthai` helper `OpenThaiSystemOneLocalBackend` uses), since the
        # whole point of the HTTP transport is working when that package is NOT installed locally
        # (e.g. the model is hosted remotely). Field names match the server's documented contract.
        payload_questions = {}
        for q in questions:
            if q.kind == "score":
                payload_questions[q.id] = {"type": "score", "instructions": q.text, "criteria": list(q.levels)}
            elif q.kind == "noul":
                payload_questions[q.id] = {"type": "noul", "instructions": q.text}
            else:
                criteria = q.option_descriptions or {opt: opt for opt in q.options}
                payload_questions[q.id] = {"type": "choice", "instructions": q.text, "criteria": criteria}

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with httpx.Client(transport=self._transport, timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/v1/systemone",
                json={"state": state, "questions": payload_questions},
                headers=headers,
            )
        resp.raise_for_status()  # a non-2xx is a real failure -- let it raise, caller defaults to HOLD
        data = resp.json()

        answers = []
        for qid, ans in data.get("answers", {}).items():
            if "noul" in ans:
                p_yes = float(ans["noul"])
                answers.append(DecisionAnswer(
                    question_id=qid, resolution=S4.POS, label=("yes" if p_yes >= 0.5 else "no"),
                    probability=p_yes,
                ))
            elif "score" in ans:
                dist = dict(ans.get("probabilities", {}) or {})
                answers.append(DecisionAnswer(
                    question_id=qid, resolution=S4.POS, label=str(ans["score"]),
                    probability=float(ans.get("confidence", 0.0)), probabilities=dist,
                ))
            else:
                dist = dict(ans.get("probabilities", {}) or {})
                choice = str(ans.get("choice", ""))
                answers.append(DecisionAnswer(
                    question_id=qid, resolution=S4.POS, label=choice,
                    probability=float(dist.get(choice, 0.0)), probabilities=dist,
                ))
        return DecisionProposal(answers=answers, backend_id=self._backend_id, rationale="")
