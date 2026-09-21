# PGCross — Decision Model

**Scope:** this document explains how PGCross represents a decision question, how it gets a
proposed answer (from a witness-check, a computation backend, or a decision backend), and what
that proposal looks like. It does **not** cover the gate that turns a proposal into a served
answer — that is `authorization/policy.py`'s `classify_and_authorize()`/F1-invariant logic,
documented in `AUTHORIZATION_MODEL.md`. Where the two meet, this doc cross-references that one
rather than duplicating it.

Grounded in the real code as of 2026-09-21 (`the project's internal architecture audit notes`,
`the project's architecture design notes`, `the project's internal engineering decision log`). File:function citations below are
exact, not aspirational.

---

## 1. The core principle: a model may propose, never authorize

Structurally, this shows up as two facts that hold everywhere in the code:

- **`DecisionProposal` (`src/pgcross/decision/schema.py`) is never itself an
  `AuthorizationResult`.** They are two different Pydantic models with no subclass or union
  relationship. Nothing in the codebase constructs an `AuthorizationResult` directly from a
  `DecisionProposal`'s fields — a proposal is always an *input* that still has to pass through
  `authorization/policy.py`.
- **Every `DecisionBackend.decide()` call returns a `DecisionProposal`, and `DecisionProposal`'s
  own docstring says so explicitly:**

  > "A `DecisionBackend`'s proposal for a batch of questions — NEVER an authorization
  > ... a proposal's confidence never bypasses a failed gate (F1)."
  > (`decision/schema.py`, class `DecisionProposal`)

The same rule is stated from the backend side in `decision/backend.py`'s module docstring: a
`DecisionBackend` "may PROPOSE a typed answer with a probability, never authorize one," and every
`DecisionProposal` it returns "still must pass PGCross's own Verify/Authorize gate
(`authorization/policy.py` ... ) before it can become an ADMIT/HOLD/REJECT/ESCALATE outcome."

Concretely, in the live pipeline (`pipeline/authorize.py::_authorize_status`), a candidate that
cannot be resolved by any witness reaches a fixed default of `AuthorizationStatus.HOLD` — never a
model-produced confidence value promoted directly into a served status. See §6 for why: no
`DecisionBackend` is actually wired in yet, so this path is currently forced rather than merely
disciplined, but the *shape* of the rule (proposal ≠ authorization) is enforced by the type
system regardless of whether a real backend exists behind it.

---

## 2. The S4 four-value resolution state

`src/pgcross/core/s4.py` defines:

```python
class S4(str, Enum):
    POS = "POS"
    NEG = "NEG"
    ZERO = "ZERO"
    BOT = "BOT"
```

Four values, not three and not two: a determinate positive, a determinate negative, a determinate
**zero** ("checked, found nothing"), and a fourth, formally distinct **bottom/unresolved** state
("could not check"). The module docstring is explicit about why `ZERO` and `BOT` cannot be merged
or represented as `None`/falsy:

> Toledo `D/M.65.v1` (`neutral_distinct_from_bottom`, **Th_coqc**), statement as registered:
> `Sz <> Sbot` — "the four-value algebra's 'determinate zero' and 'unresolved' are formally
> distinct constructors, never conflatable."
> "checked, found nothing" (`ZERO`) and "could not check" (`BOT`) must never collapse into each
> other, and must never collapse into `None`/falsy/`0`/`""` at any serialization boundary.
> (`core/s4.py`)

This is why `decision/schema.py`'s `Candidate.resolution` and `DecisionAnswer.resolution` are
typed `S4` with **no default** — constructing either without an explicit `resolution=` raises
`pydantic.ValidationError` rather than silently defaulting to something that reads as "no" or
"nothing" (`decision/schema.py`, `Candidate`/`DecisionAnswer` docstrings). A `None` shortcut would
reintroduce exactly the collapse `D/M.65.v1` forbids.

A second, related grounding is `D/M.77.v1` (`bot_monotone_in_floor`, **Th_coqc**):
`0<=f1 -> f1<=f2 -> classify f1 v = Sbot -> classify f2 v = Sbot` — coarsening a resolution floor
can only ever *grow* the unresolved region, never shrink it. This is what licenses
`authorization/policy.py::resolution_gate`'s cheap-check-then-refine early exit as *sound*, not
merely fast: if a coarse check already resolves (anything other than `BOT`), no finer check could
have made that result unresolved, so stopping immediately is safe (`authorization/policy.py`,
`resolution_gate` docstring; see §3 below).

Both citations are taken verbatim from the code's own docstrings, which state they were read
directly from Toledo's canonical equation registry, not paraphrased. This document adds
no new Toledo claim beyond what `core/s4.py` and `authorization/policy.py` already cite.

`BOT` maps directly to `HOLD` in the Authorize stage — never to `ZERO`, never to a fabricated
`POS`/`NEG` guess.

---

## 3. Witness before Model

`authorization/policy.py` implements the gating order that decides whether a `DecisionBackend`
should even be considered, ahead of any actual call:

**`has_finite_witness(gate, candidate) -> bool`** — recognizes the `A3` witness-check pattern
(`P(X) <=> exists w finite: check(X,w)=top`) as it already exists in two providers, without
rewriting either:

1. `providers/cards/base.py`'s `EngineCardProvider.verify()` — a card with `coq_checked=True` or
   `independent_oracle=True` performed a real deterministic check; a `SELF_CONSISTENT`-only card
   (`detail="self_consistent_NA"`) never had a witness checked at all, so `has_finite_witness`
   returns `False` for it even though `ok=True`.
2. `providers/oracle/execution_oracle.py`'s `run_candidate()` — a pass/fail from actually running
   code against a test suite is a literal executed witness; a timed-out run counts as no witness
   regardless of `passed`.

**`resolution_gate(coarse_check, refine_fn, budget) -> (S4, list[TraceEntry])`** — runs the
cheapest check first, stops immediately if it resolves, otherwise calls `refine_fn` up to
`budget` times at successively finer resolution. If still `S4.BOT` when the budget is exhausted,
it returns `S4.BOT` and **never raises, never guesses** — the exhaustion itself is recorded as a
`TraceEntry(action="exhausted")` so a caller can see that budget, not a real classification, is
why the answer stayed `⊥`.

**`needs_decision_backend(gate, candidate, s4_result) -> bool`** — the actual gate:

```python
return (not has_finite_witness(gate, candidate)) and s4_result == S4.BOT
```

`True` only when *both* legs agree there is genuinely nothing else to try: no finite witness
resolves the candidate, **and** the resolution gate (already run by the caller) still reports
`S4.BOT` after its refine budget. Only then would a `DecisionBackend` call be considered.

The order of operations, as documented in `the project's architecture design notes` §2 and
implemented across these three functions:

```
deterministic engine card / A3 witness check  →  resolution gate (coarse → refine)  →
  still ⊥ after both?  →  only then: DecisionBackend.decide()  →  proposal (never authorization)
```

`classify_and_authorize()`, in the same file, is a separate leg (harm/stakes taxonomy →
`AuthorizationStatus`) and is `AUTHORIZATION_MODEL.md`'s territory, not this document's — it is
mentioned here only to note that it runs independently of, and prior to, the witness/resolution
gate in `pipeline/authorize.py::_authorize_status` (see §6).

---

## 4. `DecisionBackend` vs `LLMBackend`

Two distinct Protocols exist in the codebase and are not interchangeable:

**`LLMBackend` (`src/pgcross/backends/base.py`)** — transport-only, I7-constrained structure
extraction:

```python
class LLMBackend(Protocol):
    def transport(self, p: TransportPrompt) -> TransportOut: ...   # structure only, never a fact
    def info(self) -> BackendInfo: ...
    def propose_bridge(self, p: TransportPrompt) -> TransportOut: ...   # optional, GUESS-tagged
    def general_chat(self, text: str) -> str: ...                       # optional, GUESS-tagged
```

`transport()` must never assert a fact or a number, only extract/structure what is already in the
input (I7). Its two optional methods (`propose_bridge`, `general_chat`) *are* allowed to produce
values not literally present in the input, but the pipeline never trusts their framing: every
candidate either one produces is hard-tagged `CType.GUESS`, which `core/tiering.py` caps at
`Tier.Open` unconditionally (`backends/base.py` docstrings). Implementations:
`LlamaCppBackend`, `OpenAIBackend` (`backends/llamacpp.py`, `backends/openai.py`).

**`DecisionBackend` (`src/pgcross/decision/backend.py`)** — typed decisions with probabilities:

```python
class DecisionBackend(Protocol):
    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal: ...
```

Per the module docstring, `DecisionBackend` "is a different contract" from `LLMBackend`: it is
only ever reached *after* the witness-before-model / resolution-gate sequence (§3) has already
found nothing, and at that point it may propose a typed answer with a probability — never
authorize one. Its **failure policy is a binding contract of the Protocol**: if `decide()` fails,
times out, or otherwise cannot produce a `DecisionProposal`, defaulting to `HOLD` is the
*caller's* responsibility, not this module's — `DecisionBackend` implementations deliberately
implement no retry/fallback/timeout logic themselves; they may raise, and must never silently
invent a proposal.

Implementations in `decision/backend.py`:

- **`MockBackend`** — returns a configured canned `DecisionProposal`, or, with none configured,
  an honest all-`S4.BOT` proposal for every question (never a fabricated guess).
- **`DeterministicBackend`** — wraps a plain Python callable `(state, questions) ->
  DecisionProposal`; for gates that ARE resolvable by code but still want to be called uniformly
  through the `DecisionBackend` interface.
- **`SystemOneHTTPBackend`** — **stub**. See §6.

Why two protocols instead of one: `LLMBackend` is a general-purpose, potentially multi-mode wrap
around one set of model weights (structure-transport plus two optional, hard-capped speculative
modes); `DecisionBackend` is a narrower, purpose-built contract for the specific
"propose-a-typed-answer-with-a-probability" step that only fires after the witness/resolution
gate has already been exhausted. Conflating them was an identified risk in
`the project's internal architecture audit notes` ("[`LLMBackend`] needs a new layer, not just reuse") and
`decision/backend.py`'s docstring repeats the same non-conflation instruction explicitly.

---

## 5. `ComputationBackend`: a sibling protocol, not a proposer

`src/pgcross/decision/computation_backend.py` defines a second, distinct protocol for *exact or
certified* computation, positioned in the routing order **before** any `DecisionBackend` call:

```python
class ComputationBackend(Protocol):
    def solve(self, request: dict[str, Any]) -> ComputationResult: ...

class ComputationResult(BaseModel):
    value: Any = None
    tier: str = "Open"
    bound: dict[str, Any] | None = None
    status: str = "ESTIMATED"   # e.g. "CERTIFIED" / "ESTIMATED" / "HOLD"
    method: str = ""
```

The module docstring states the distinction directly: "`DecisionBackend` ... produces a
*probabilistic proposal* that must still pass Verify/Authorize. `ComputationBackend` routes to an
existing, separately-owned, separately-verified calculator ... and returns an already-certified-
or-estimated result — no probabilistic model call involved at all." A calculator is not a
proposer.

Two implementations exist:

- **`IDMBackend`** — a real implementation. Calls `idm.solve(request)` directly as a same-machine
  Python import (not REST), against the `information-discrete-math` package. Raises
  `IDMNotInstalledError` if `idm` is not importable — it never silently no-ops or fabricates a
  result.
- **`UniversalSolverBackend`** — a **stub**. `solve()` always raises `NotImplementedError`; it
  exists only to satisfy the protocol shape and document that `research_universal_solver` (a
  separate private repo) is a dependency-availability risk, not yet wired.

`ComputationBackend` and `DecisionBackend` are sibling protocols in the same routing order
(`the project's architecture design notes` §6a): deterministic engine card → `A3` witness check →
`ComputationBackend` route (still no probabilistic call) → only if still `⊥`: `DecisionBackend`.
Neither is currently invoked from the live pipeline — see §6.

---

## 6. Honest status: nothing above is wired into the live pipeline yet

This section exists because this project's discipline (`CLAIMS.md`, `NON_CLAIMS.md`) requires
every doc to state plainly what does and does not actually run, not just what has been designed.

**What is real, tested, and imported by live code:**

- `core/s4.py`'s `S4` enum and `core/fold.py`'s fold primitives.
- `decision/schema.py`'s Pydantic models (`Candidate`, `DecisionQuestion`, `DecisionAnswer`,
  `DecisionProposal`, `VerificationResult`, `AuthorizationResult`) — imported and used by
  `pipeline/authorize.py` for `AuthorizationResult`/`AuthorizationStatus`.
- `authorization/policy.py`'s `has_finite_witness`, `resolution_gate`, `needs_decision_backend`,
  `classify_and_authorize` — all called live from `pipeline/authorize.py::_authorize_status`.
- `decision/backend.py`'s `DecisionBackend` protocol, `MockBackend`, `DeterministicBackend`.
- `decision/computation_backend.py`'s `ComputationBackend` protocol, `IDMBackend` (real, requires
  the separate `idm` package to be installed), `UniversalSolverBackend` (stub).

**What is NOT real yet — do not present as a working, end-to-end decision-proposal system:**

- **No real `DecisionBackend` is wired into the live pipeline.** `SystemOneHTTPBackend`
  (`decision/backend.py`) is a documented interface stub whose `decide()` **always raises
  `NotImplementedError`**:

  > "STUB — OpenThai-SystemOne HTTP integration is NOT implemented in this pass ... `decide()`
  > always raises." (`decision/backend.py`, class `SystemOneHTTPBackend`)

  OpenThai-SystemOne is confirmed as the intended production backend (`the project's internal engineering decision log` Phase 0
  item 2, resolved 2026-09-21), but the actual HTTP integration — request/response shape, auth,
  timeout/retry semantics — has not been built.

- **`needs_decision_backend() == True` currently just defaults to `HOLD`, unconditionally.** In
  `pipeline/authorize.py::_authorize_status`, when the witness/resolution gate reports that a
  `DecisionBackend` call *would* be needed, the code does not call one — it returns
  `AuthorizationStatus.HOLD` directly, with the in-code comment marked as temporary:

  > "*** TEMPORARY BEHAVIOR — Phase C dependency, per the project's architecture design notes §3/§6a ***
  > There is NO DecisionBackend wired into the live pipeline yet ... THIS WILL CHANGE once a real
  > DecisionBackend is wired into the live pipeline — at that point the ⊥ case should route to
  > `DecisionBackend.decide()` per §3's diagram instead of defaulting to HOLD unconditionally."
  > (`pipeline/authorize.py`, `_authorize_status`)

- **The witness probe feeding this gate is itself a documented, temporary proxy.**
  `pipeline/authorize.py::_witness_probe` reconstructs an approximate `VerifierResult` from
  `provenance.verifiability` because `pipeline/verify.py` does not persist the original raw
  `VerifierResult` through to `authorize()` yet — flagged in its own docstring as "a documented,
  temporary proxy" to be replaced "once `verify()` threads the real `VerifierResult` through to
  `authorize()` (a future stream)."

- **`decision.schema.Candidate`/`S4` are not threaded through the live serve path end-to-end.**
  Per the project's internal status notes' "what remains open" list: "currently only
  `core.models.EvidenceCandidate` flows through the served pipeline — the S4 machinery is real but
  not yet wired end-to-end."

- **`ComputationBackend` is not called from `pipeline/verify.py` or `authorize.py` at all** — its
  protocol and `IDMBackend` implementation exist and are (per `the project's internal engineering decision log` item 19) built,
  but nothing in the live request path routes to either backend yet.

Tracked open items (the project's internal engineering decision log, Phase 2/3):

- Item 18 — "design `DecisionBackend` protocol; implement `MockBackend`/`DeterministicBackend`
  now; design (don't implement) `SystemOneHTTPBackend` pending Phase 0 item 2" — protocol/mocks
  done, `SystemOneHTTPBackend` still a stub by design.
- Item 19 — "design `ComputationBackend` protocol ... implement `IDMBackend` ... stub
  `UniversalSolverBackend`" — done as designed; not yet routed from the pipeline.
- the project's internal status notes' "what remains open" list — wiring a real
  `DecisionBackend` into the live pipeline, threading `decision.schema.Candidate`/`S4` through
  `verify()`→`authorize()`, and adding an integration-level regression test for the F1 gate — all
  explicitly still open, not silently dropped.

**Bottom line:** the decision-proposal *machinery* — schema, S4 algebra, witness-before-model
gate, two backend protocols, two working mock/deterministic implementations, one real
`ComputationBackend` (`IDMBackend`) — is real and unit-tested. What does not exist yet is a real
`DecisionBackend` implementation reachable from a live request, or a live request that actually
reaches the `⊥`-then-call-a-backend branch instead of stopping at the temporary `HOLD` default.
