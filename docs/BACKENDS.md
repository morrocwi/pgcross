# PGCross Next — Backends Reference

**Status:** one of the six required docs from the PGCross Next engineering letter (Phase 6, item
34 of `the project's internal engineering decision log`). Written 2026-09-21, grounded directly in the real source under
`src/pgcross/backends/`, `src/pgcross/decision/backend.py`, `src/pgcross/decision/
computation_backend.py`, and their test files. No claim below is taken from a docstring or a
design doc without also being checked against the actual code; where a claim was independently
verified this session (e.g. whether `idm` is installed), that is said explicitly.

---

## 1. Why three protocols, not one

PGCross has **three separate backend protocols** because they answer three structurally different
questions, and collapsing them into one interface would hide a safety property each one depends
on. Concretely:

| Protocol | File | Question it answers | May it invent a value not in its input? | Is its output ever an authorization? |
|---|---|---|---|---|
| `LLMBackend` | `src/pgcross/backends/base.py` | "What structure is in this text?" | No, for its required method (`transport`) — I7-constrained | No |
| `DecisionBackend` | `src/pgcross/decision/backend.py` | "What's your best typed guess, with a probability?" | Yes, explicitly — that's its purpose | No, never |
| `ComputationBackend` | `src/pgcross/decision/computation_backend.py` | "What does the calculator say?" | No — it routes to an already-verified external solver | Not itself, but its `CERTIFIED` results can satisfy Verify without further probabilistic input |

### 1.1 `LLMBackend` — transport-only, I7-constrained structure extraction

`src/pgcross/backends/base.py:LLMBackend` (`@runtime_checkable` `Protocol`):

```python
class LLMBackend(Protocol):
    def transport(self, p: TransportPrompt) -> TransportOut: ...   # REQUIRED
    def info(self) -> BackendInfo: ...                              # REQUIRED
    def propose_bridge(self, p: TransportPrompt) -> TransportOut: ...  # OPTIONAL
    def general_chat(self, text: str) -> str: ...                      # OPTIONAL
```

`transport()`'s own docstring is explicit about the constraint (I7 discipline, the pipeline-wide
"never invent a value" rule): *"Structure/extract only. NEVER assert a fact, NEVER produce a
numeric answer, NEVER add info not in the input."* `TransportOut.json` is typed as `dict` with the
comment `# STRUCTURE ONLY — never a fact or number (I7)`. This is a **transport** call: given raw
text, extract what's already there into structured JSON. It is not allowed to answer a question —
only to reformat an answer that's already present in the input.

The two optional methods (`propose_bridge`, `general_chat`) are a different invocation mode on the
*same* wrapped weights, not a second model — see §3 for the real gotcha this creates.

### 1.2 `DecisionBackend` — typed decisions with probabilities, reached only after witness-before-model fails

`src/pgcross/decision/backend.py:DecisionBackend`:

```python
class DecisionBackend(Protocol):
    def decide(self, state: dict, questions: list[DecisionQuestion]) -> DecisionProposal: ...
```

Per the module docstring, this protocol is **only ever reached after** the witness-before-model /
resolution-gate sequence described in the project's architecture design notes (Toledo's `A3`:
`witness_sound`/`witness_complete`/`decide_reflect`, all `Th_coqc`) has already found no finite
witness and no resolved readout. At that point a `DecisionBackend` may **propose** a typed answer
with a probability — it may never authorize one. `DecisionProposal` (the return type) structurally
cannot express an authorization outcome: it has no `authorization`/`outcome` field at all
(`test_decide_never_asserts_authorization_only_proposes` in `tests/test_backend_contracts.py`
asserts exactly this). Every `DecisionProposal` must still pass PGCross's own Verify/Authorize gate
(`authorization/policy.py`, a separate, not-yet-built stream) before it can become an
ADMIT/HOLD/REJECT/ESCALATE outcome.

`DecisionAnswer.resolution` is typed as `S4` (`POS`/`NEG`/`ZERO`/`BOT`), not a bare boolean or
`None` — per Toledo `D/M.65.v1` (`Sz <> Sbot`, `Th_coqc`), "determinate zero" and "unresolved" are
formally distinct and must never collapse into each other at a serialization boundary.

**Failure policy (binding contract, stated in the module docstring):** if `decide()` fails, times
out, or otherwise cannot produce a proposal, it is the **caller's** responsibility (not this
module's) to default to `HOLD`. `DecisionBackend` implementations deliberately implement no
retry/fallback/timeout logic themselves — a backend is free to raise on failure; it must never
silently invent a proposal.

### 1.3 `ComputationBackend` — exact/certified computation, a calculator, not a proposer

`src/pgcross/decision/computation_backend.py:ComputationBackend`:

```python
class ComputationBackend(Protocol):
    def solve(self, request: dict[str, Any]) -> ComputationResult: ...
```

Per the module docstring: *"a calculator is not a proposer."* Where `DecisionBackend.decide()`
returns a probabilistic proposal that must still pass Verify/Authorize, `ComputationBackend.solve()`
routes to an existing, **separately-owned, separately-verified** calculator
(`information-discrete-math` for finite/exact math, `research_universal_solver` for cross-domain
structural/spine dynamics) and returns an already-certified-or-estimated result — no probabilistic
model call involved at all. `ComputationResult` carries `status` (e.g. `CERTIFIED` / `ESTIMATED` /
`HOLD`), `tier`, `value`, `bound`, `method` — deliberately kept in the same shape
`idm.solve()` already returns, per `the project's architecture design notes` §6a's observation that
this shape is "already shaped like a PGCross `VerificationResult`."

Per the project's architecture design notes §6a's end-to-end routing order, `ComputationBackend` sits
**before** `DecisionBackend` in the kernel:

```
1. deterministic engine card (providers/cards/, A3 witness-style)
2. A3 finite witness check
3. ComputationBackend route (IDM / UniversalSolver) — still no probabilistic model call
4. if still ⊥ after (1)-(3): DecisionBackend (System-One-style)
5. Verify/Authorize gate over whichever of (1)-(4) produced the candidate
```

---

## 2. Concrete implementations

### 2.1 `LLMBackend` implementations

**`LlamaCppBackend`** (`src/pgcross/backends/llamacpp.py`) — wraps a local GGUF model via
`llama_cpp.Llama`, lazy-loaded on first call (`_load()`). Implements **all four** protocol members:
- `transport()` — uses `_SYSTEM_PROMPT` ("You are a transporter... Never assert a fact"), JSON-mode
  chat completion, falls back to `{"raw": <text>}` if the model's output doesn't parse as JSON.
- `propose_bridge()` — uses a deliberately different `_BRIDGE_SYSTEM_PROMPT` that explicitly *asks*
  for a speculative guess (`{"guess": ..., "rationale": ...}`); the code comment is explicit that
  the honesty guarantee here is **not** "the model won't invent anything" — it's enforced
  downstream, by `pipeline/imagine.py` hard-tagging every resulting candidate `CType.GUESS`, which
  `tiering.py` caps at `Tier.Open` regardless of what the prompt returns.
- `general_chat()` — open-ended assistant mode, `_GENERAL_CHAT_SYSTEM_PROMPT`, same downstream
  `CType.GUESS`/`Tier.Open` cap.
- `info()` — returns `BackendInfo(model_id=<weights path>, quantization="gguf", ...)`.

**`OpenAIBackend`** (`src/pgcross/backends/openai.py`) — talks to any OpenAI-compatible
`/v1/chat/completions` HTTP endpoint via `httpx`. Implements **only** the two required members:
- `transport()` — same `_SYSTEM_PROMPT` discipline as `LlamaCppBackend.transport()`, POSTs with
  `response_format: {"type": "json_object"}`, same raw-JSON-fallback behavior.
- `info()` — returns `BackendInfo(model_id=<model>, quantization=None, license_tag=
  "openai-compatible", ...)`.
- It does **not** implement `propose_bridge()` or `general_chat()` — see §3 for why this is not a
  bug and what it means for `isinstance()` checks.

### 2.2 `DecisionBackend` implementations

- **`MockBackend`** (`src/pgcross/decision/backend.py:MockBackend`) — returns a configurable,
  canned `DecisionProposal` verbatim, or, if none was configured, an all-`BOT` (unresolved)
  proposal covering every given question. For tests and offline development only.
- **`DeterministicBackend`** — wraps a plain Python callable `(state, questions) ->
  DecisionProposal`. No model call at all; exists so a gate that *is* resolvable by code (an
  `A3`-style finite witness check) can still be called uniformly through the `DecisionBackend`
  interface, so callers don't need to special-case "this one is deterministic."
- **`SystemOneHTTPBackend`** — **STUB. Not wired up.** Its constructor accepts `base_url`/`api_key`
  (documenting the shape a real implementation would need), but `decide()` **always raises**
  `NotImplementedError("SystemOneHTTPBackend: OpenThai-SystemOne HTTP integration not yet
  implemented -- see item 31 of the project's internal engineering decision log")`. `isinstance(backend, DecisionBackend)` still
  returns `True` for it — Python Protocol `isinstance` checks structure (does it have a `decide`
  method?), not behavior (does calling it actually work?) — see
  `tests/test_backend_contracts.py:TestSystemOneHTTPBackendStub` and
  `tests/test_decision_backend.py:TestSystemOneHTTPBackend`, both of which test the stub's
  documented-raise behavior explicitly rather than looping it into the shared contract test class
  that runs against real backends.

### 2.3 `ComputationBackend` implementations

- **`IDMBackend`** (`src/pgcross/decision/computation_backend.py:IDMBackend`) — a **real**
  implementation. `solve()` does a local `import idm` and calls `idm.solve(request)` directly (a
  same-machine Python call, not REST — per §6a's deployment note that same-machine calls should
  avoid HTTP/serialization overhead), then normalizes the result into `ComputationResult`.

  **Confirmed this session (2026-09-21) by direct check in this dev environment:**
  ```
  $ python3 -c "import idm"
  ModuleNotFoundError: No module named 'idm'
  ```
  `idm` (the `information-discrete-math` library) is **not installed** into pgcross's own
  environment right now. This is not a silent gap: `IDMBackend.solve()` is written to raise a
  documented `IDMNotInstalledError` (an `ImportError` subclass) in exactly this state — it never
  fabricates a result. The error message names the fix directly: `pip install -e
  <path-to-information-discrete-math>` (brings in `mpmath`, `sympy`). The test suite
  (`tests/test_computation_backend.py`) is written to match this reality: `test_solves_trivial_
  integral` is `skipif(not _idm_importable())`, and `test_raises_documented_error_when_idm_not_
  installed` is `skipif(_idm_importable())` — so in the *current* environment, only the
  not-installed path actually runs, and it does.

- **`UniversalSolverBackend`** — **STUB.** `solve()` always raises `NotImplementedError`, pointing
  at a private sibling repo's MCP tools (`universe_read`/`universe_step`/`universe_domain`/
  `universe_cascade`/`operator_*`) as what a real implementation would call. This is a separate,
  **private** repo not included here — per the project's architecture design notes §6a, this is flagged
  as a dependency-availability risk, not a blocker to defining the protocol itself. The protocol shape
  is satisfied (`isinstance(UniversalSolverBackend(), ComputationBackend)` is `True`), the behavior
  is not implemented.

---

## 3. A real Python-Protocol gotcha: `@runtime_checkable` `isinstance()` is purely structural

Found and documented this session in `tests/test_backend_contracts.py:TestLLMBackendContract`.
`LLMBackend` is `@runtime_checkable`, which lets you write `isinstance(backend, LLMBackend)`. But
Python's runtime Protocol check is **purely structural** — for each method the Protocol declares,
it does a `hasattr` check. It has **no concept of "optional" vs "required" members** at the
language level; that distinction exists only in the docstrings and in how call sites choose to use
`hasattr()` themselves.

Concretely:

- `LlamaCppBackend` implements all four declared members (`transport`, `info`, `propose_bridge`,
  `general_chat`) → `isinstance(LlamaCppBackend(...), LLMBackend)` is `True`.
- `OpenAIBackend` implements only the two members documented as REQUIRED (`transport`, `info`) →
  `isinstance(OpenAIBackend(...), LLMBackend)` is **`False`**.

This is expected, correct behavior — **not a bug in `OpenAIBackend`**. `propose_bridge`/
`general_chat` are documented as optional in `LLMBackend`'s own docstrings, and the real call sites
(`pipeline/imagine.py`, `pipeline/run.py`) check for them with `hasattr(backend, "propose_bridge")`
/ `hasattr(backend, "general_chat")` rather than relying on `isinstance(backend, LLMBackend)` to
mean "has everything." If a future backend author writes `if isinstance(backend, LLMBackend): ...`
expecting that to mean "this backend supports all four methods," they will get a `False` for any
backend that only implements the two required ones — even a fully correct, working backend like
`OpenAIBackend`. **The lesson for anyone adding a new backend or a new caller:** use
`isinstance(backend, LLMBackend)` only to check "does this look like an `LLMBackend` at all"
(i.e., has the required members), and use explicit `hasattr()` checks — matching the existing
call-site pattern — to test for the optional members. Do not treat `isinstance` against this
Protocol as a completeness gate.

The test suite encodes this explicitly:
- `test_full_protocol_isinstance_when_all_members_present` — asserts `isinstance` holds for
  `LlamaCppBackend`.
- `test_partial_backend_fails_full_protocol_isinstance` — asserts `isinstance` does **not** hold
  for `OpenAIBackend`, with a comment that this is "documented, expected Python Protocol
  semantics — NOT an assertion that `OpenAIBackend` is broken."

---

## 4. `backends/registry.py`'s `build_backend()` factory

`src/pgcross/backends/registry.py:build_backend(cfg: dict)` dispatches on `cfg["kind"]`:

| `kind` | Status | Notes |
|---|---|---|
| `"llamacpp"` | Implemented | Requires `cfg["weights"]` (path to `.gguf`); `context_length` defaults to 8192. |
| `"openai"` | **Implemented — fixed this session** | Requires `cfg["url"]` and `cfg["model"]`; `api_key` defaults to `"sk-placeholder"`. |
| `"vllm"` | Not implemented | Raises `NotImplementedError(f"backend kind {kind!r} is not yet implemented. Contribute backends/vllm.py / ollama.py to add it.")` |
| `"ollama"` | Not implemented | Same as `vllm`. |
| anything else | Rejected | `ValueError(f"unknown backend kind: {kind!r}. Supported: llamacpp, openai, vllm, ollama")` |

**Prior state, now fixed:** per the project's internal architecture audit (2026-09-20),
`registry.py` previously raised `NotImplementedError` for `kind="openai"` **even though**
`backends/openai.py` already fully implemented `OpenAIBackend` — a pure wiring bug (Phase A audit
called it "the same class as the server's duplicate route [bug]"). The project's internal
engineering decision log, Phase 1 item 12, tracked this fix (*"Fix `backends/registry.py`'s
`openai`-kind wiring bug"*). The current
`registry.py` (read directly for this doc) confirms the fix landed — the `if kind == "openai":`
branch now correctly imports and constructs `OpenAIBackend`. `vllm`/`ollama` remain genuinely
unimplemented, not a wiring bug — there is no corresponding `backends/vllm.py` /
`backends/ollama.py` file to wire in yet.

---

## 5. Honest status section

- **OpenThai-SystemOne is the confirmed, intended production `DecisionBackend`.** Per
  `the project's internal engineering decision log` Phase 0, item 2: *"RESOLVED. OpenThai-SystemOne confirmed as the intended
  production `DecisionBackend`. `SystemOneHTTPBackend` can target it directly, not stay
  provider-agnostic indefinitely."*
- **`SystemOneHTTPBackend`'s real HTTP integration is NOT built.** Its `decide()` method
  unconditionally raises `NotImplementedError`. Its own class docstring states this directly:
  *"STUB — OpenThai-SystemOne HTTP integration is NOT implemented in this pass... wiring the real
  HTTP API contract is separate, real integration work (needs the actual request/response shape,
  auth, timeout/retry semantics) that this pass deliberately does not fake."* The tracking item is
  `the project's internal engineering decision log` Phase 5, item 31 ("Offline-fallback tests" — the raised error's own message
  points there: `"see item 31 of the project's internal engineering decision log"`). Until that work lands, any code path that needs
  a live `DecisionBackend` must use `MockBackend` or `DeterministicBackend`, and per the
  failure-policy contract in §1.2, any caller that does invoke `SystemOneHTTPBackend.decide()`
  today will get an exception it must convert to `HOLD` — it will not get a proposal.
- **`IDMBackend` is real code but `idm` is not installed in this dev environment**, confirmed by
  direct check this session (§2.3). `IDMBackend.solve()` is correctly written to fail loudly
  (`IDMNotInstalledError`) rather than silently, so this is a deployment/dependency gap, not a code
  defect — but it means `IDMBackend` cannot actually be exercised end-to-end in this environment
  right now without first running `pip install -e <path-to-information-discrete-math>`.
- **`UniversalSolverBackend` is a stub by design**, blocked on a separate, private sibling repo not
  included here being available as an installable dependency — not scheduled to be implemented in
  this phase.

---

## 6. Quick reference — which protocol for which job

- Need to turn free text into structured JSON, with a hard guarantee against inventing facts? →
  `LLMBackend.transport()`.
- Need a speculative, explicitly-labeled guess for a missing value (opt-in, capped at
  `Tier.Open`)? → `LLMBackend.propose_bridge()` (optional method — check with `hasattr`, not
  `isinstance`).
- Need a plain conversational fallback for a low-stakes, no-structured-signal query? →
  `LLMBackend.general_chat()` (optional method, same caveat).
- Have a finite/exact math problem (integral, shortest-path, optimization, CAS) that a dedicated
  solver can answer with a certificate or a bound? → `ComputationBackend` via `IDMBackend`
  (requires `idm` to be installed — see §5).
- Need cross-domain structural/spine computation (`L_R` spectrum, evolution)? →
  `ComputationBackend` via `UniversalSolverBackend` (not implemented yet).
- Exhausted witness checks and computation routes, still `⊥`, need a probabilistic proposal that
  will still pass through Verify/Authorize? → `DecisionBackend` via `MockBackend`/
  `DeterministicBackend` today; `SystemOneHTTPBackend` once Phase 5 item 31 lands.
