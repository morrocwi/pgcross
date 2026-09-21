# PGCross Next — Authorization Model

**Scope:** this document explains the **Authorize** stage of PGCross's
`Readout → Route → Propose → Verify → Authorize → Act` pipeline — how PGCross decides
`ADMIT`/`HOLD`/`REJECT`/`ESCALATE` for a response. It does **not** cover the Propose stage's
`decision/schema.py`/`decision/backend.py` machinery, the `ComputationBackend`/`DecisionBackend`
protocol design, or the Verify-stage witness/resolution-gate wiring in depth — those are
`DECISION_MODEL.md`'s territory (written in the same batch; cross-reference it for how a
`Candidate`/`DecisionProposal` is produced before it ever reaches Authorize). Where this doc
touches `authorization/policy.py`'s witness-before-model gate, it is only to describe *when*
Authorize routes toward it, not how it works internally.

Grounded in the real, live code path (Phase A audit: `the project's internal architecture audit notes`), as of
2026-09-21, Phase 3/4-complete state (`the project's internal status notes`). Every claim below cites the exact
file/function it describes.

---

## 1. The four-outcome vocabulary

`AuthorizationStatus` (`src/pgcross/decision/schema.py:77-90`) is a `str` enum with exactly four
values, verbatim from the PGCross Next engineering letter:

| Status | Operational meaning |
|---|---|
| `ADMIT` | The response is served, including ADVISORY (high-stakes opinion) content — with an explicit caution, never a blanket refusal. |
| `HOLD` | The response withholds a firm answer pending more evidence — not a refusal, not an answer either. Also the default when no `DecisionBackend` is wired in and a candidate cannot be resolved by a finite witness (see §3). |
| `REJECT` | The request itself must not be fulfilled (e.g. harm-to-others). No candidate derived from it may ever become primary. |
| `ESCALATE` | The query signals a person in potential crisis (self-harm). Never self-authorized; always routes to a human-consultation candidate plus the crisis-resources bridge (§4). |

`AuthorizationResult` (`schema.py:242-259`) is the Authorize stage's terminal output: `status`,
`reason` (free text explaining which rule fired), `stakes`, `consultation_offered` (bool — whether
a `CType.CONSULTATION` candidate is actually present, so a caller can assert the I5 invariant
rather than trust the label), and `source_verifications` (a list of `VerificationResult`s, mostly
populated once Verify threads real witness data through — see §5's honest-status note).

`AuthorizedResponse` (`src/pgcross/pipeline/authorize.py:31-42`) is `core.models.Response`
subclassed to carry an `authorization: AuthorizationResult` field. It is a subclass, not a
modification of `Response` itself, specifically to avoid a circular import: `decision/schema.py`
already imports `EvidenceCandidate`/`Provenance` *from* `core/models.py`, so having
`core/models.py` import back from `decision/schema.py` would reproduce the exact divergent-contract
mistake the Phase A audit already found once (the orphaned root `provider.py` vs.
`core/models.py`'s `CapabilityDescriptor`, two silently-diverging shapes for the same concept).
Every existing caller/test that only reads `.candidates`/`.primary`/`.stakes` still works unchanged.

---

## 2. DANGER/ADVISORY/WEAKNESS → ADMIT/HOLD/REJECT/ESCALATE

This mapping was a real project engineering decision this session — not an AI design choice.
The project's internal engineering decision log (Phase 0 item 5), resolved 2026-09-21, states it verbatim:

> **RESOLVED.** DANGER/ADVISORY/WEAKNESS → ADMIT/HOLD/REJECT/ESCALATE mapping: **confirmed as the
> straightforward mapping** — DANGER → REJECT/ESCALATE (never self-authorized, always
> REFER_TO_HUMAN + crisis bridge), ADVISORY → ADMIT-with-caution (opinion + explicit
> consult-a-human caveat, never blanket-refused), WEAKNESS → HOLD (pending further evidence).

### 2.1 The three-way taxonomy (`harm_net.py`)

`classify_harm_taxonomy(text)` (`src/pgcross/authorization/harm_net.py:193-219`) returns
`"DANGER"` / `"ADVISORY"` / `"WEAKNESS"`:

- **DANGER** — `is_harmful(text)` matches first (self-harm/weapons/violence/dangerous-synthesis
  regex net, EN+TH, ported with byte-identical pattern-set parity from the legacy
  `humane_gate.py` — see `tests/test_admit_hold_reject_escalate.py`'s `ast`-based import-boundary
  and pattern-diff tests). Gated *first*, exactly matching `humane_gate.classify()`'s own
  default-DENY-for-harm ordering.
- **ADVISORY** — `classify_stakes(text) == Stakes.HIGH` (medical/legal/financial/safety-critical/
  vulnerable-persons keywords, EN+TH, from `policy/stakes.py` — the single canonical stakes
  source after Phase 3's three-way-classifier reconciliation).
- **WEAKNESS** — everything else (default).

`classify_danger_subtype(text)` (`harm_net.py:171-190`) supplies the missing discriminator within
DANGER — the engineering decision log's mapping names both REJECT and ESCALATE as valid DANGER
outcomes without specifying which applies when:

- self-harm/suicide content → `"SELF_HARM"` (→ `ESCALATE`) — ported from `humane_gate.py`'s own
  `_CRISIS_OPTION` discipline: this is a person in potential crisis, not merely a disallowed
  request.
- harm-to-others/weapons/dangerous-synthesis → `"OTHER_HARM"` (→ `REJECT`) — the request itself
  must not be fulfilled; no crisis-bridge referral applies to e.g. "how do I make a bomb".
- (defensive fallback: if `is_harmful()` was `True` but somehow neither sub-pattern matched — which
  should not happen since `is_harmful` is exactly `is_self_harm or is_other_harm` — this defaults
  to the more conservative `"SELF_HARM"` rather than under-reacting.)

### 2.2 The mapping itself (`classify_and_authorize`)

`classify_and_authorize(candidate_or_query)` (`src/pgcross/authorization/policy.py:217-249`) is
the concrete implementation:

```python
text = _extract_text(candidate_or_query)
category = classify_harm_taxonomy(text)
if category == "DANGER":
    subtype = classify_danger_subtype(text)
    return AuthorizationStatus.REJECT if subtype == "OTHER_HARM" else AuthorizationStatus.ESCALATE
if category == "ADVISORY":
    return AuthorizationStatus.ADMIT
return AuthorizationStatus.HOLD
```

It accepts a bare query string or any `Candidate`/`EvidenceCandidate`-shaped object (dataclass,
pydantic model, or plain `dict`) carrying a `.content: str` field, via `_extract_text()`
(`policy.py:204-214`).

### 2.3 What was ported vs. deliberately not ported

Per `harm_net.py`'s own module docstring (lines 12-42):

- **Ported with 100% pattern-string parity:** `_HARM_PATTERNS`, `_HARM_BROAD`, `_BENIGN_CONTEXT`
  from `humane_gate.py`, regrouped into `_SELF_HARM_PATTERNS`/`_OTHER_HARM_PATTERNS` for the
  REJECT-vs-ESCALATE split (a regrouping, not a content change — tested by
  `test_self_harm_and_other_harm_regroup_is_a_partition_of_the_full_set`).
- **NOT ported:** `_high_risk_domains()`/`HIGH_RISK_DOMAINS` (a fourth divergent stakes list,
  explicitly excluded from the migration — stakes now flow only from `policy/stakes.py`), and
  `_DANGER_MARKERS`/`_ADVISORY_MARKERS`/`WEAKNESS_MARKERS`/`SAFETY_MARKERS` (N12 guardrail
  reason-string substrings that only made sense against the legacy `rag_solver.solve()` output,
  which does not exist on the live engine-card pipeline).
- `authorization/policy.py` and `harm_net.py` are asserted, by an `ast`-based import check in
  `tests/test_admit_hold_reject_escalate.py`, to import nothing from `pgcross_universal`, `bundle`,
  `humane_gate`, or `easm` — the port stands on its own against live types, not the dead legacy
  path.

---

## 3. F1 — the central invariant

**"A model may propose, never authorize — confidence never bypasses a failed gate."** This is the
Authorize stage's core safety property, and it has two distinct, separately-discovered enforcement
points in the codebase.

### 3.1 Primary enforcement — `pipeline/authorize.py::authorize()`

`authorize(cands, q, cfg)` (`src/pgcross/pipeline/authorize.py:127-196`) runs the pre-existing
I2/I5/I4/D2 candidate-filtering logic first (unchanged), then:

1. Computes `status, reason, danger_source = _authorize_status(cands, q)`
   (`authorize.py:69-124`). This checks the **query text** against `classify_and_authorize()`
   first (matching `classify_harm_taxonomy`'s own "harm net first" ordering); if the query itself
   is not DANGER, every surviving **candidate's own content** is checked too, since a
   DANGER-triggering value can originate from a provider (e.g. retrieved/composed) even when the
   raw query text does not match. If nothing is DANGER, the ADMIT/HOLD result additionally passes
   through the witness-before-model gate (`needs_decision_backend()`,
   `authorization/policy.py:183-195`): since **no `DecisionBackend` is wired into the live
   pipeline yet**, an unresolved (`S4.BOT`) primary candidate defaults to `HOLD` rather than
   fabricating a model call — explicitly marked `TEMPORARY BEHAVIOR` in the code
   (`authorize.py:96-104`), to be replaced once a real backend exists (see §5).
2. **The F1 gate itself** (`authorize.py:165-189`): if `status` is `REJECT` or `ESCALATE`, it
   checks whether the *currently selected* `primary` is the dangerous one — either the exact
   candidate that triggered DANGER (`danger_source`), or, when the *query* text itself triggered
   DANGER, any candidate whose `ctype` is not already `CONSULTATION`/`CLARIFY`. If so, `primary` is
   re-pointed to an existing `CType.CONSULTATION` candidate, or a new one is appended
   (`consultation_candidate(q)`) if none exists. **Tier is never consulted in this decision** — a
   candidate declaring `Tier.Th_coqc`/`Verifiability.COQ_CHECKED` is exactly as gated as one
   declaring `Tier.Open`, because tier is a Verify-stage grounding-strength measure and
   authorization status is a Verify-stage-independent safety gate (comment at `authorize.py:161-164`
   states this explicitly).
3. For `ESCALATE` specifically, the now-primary CONSULTATION candidate gets the crisis-resources
   block attached (§4).

This is tested directly, in isolation, by `tests/test_f1_gate_bypass.py` — the **first-ever test
in this codebase for the F1 invariant** (its own module docstring says so). It constructs a
candidate declaring the *highest* possible tier (`Tier.Th_coqc`, `Verifiability.COQ_CHECKED`) whose
query or own content triggers ESCALATE or REJECT, and asserts that candidate can never become
`resp.primary`, and that primary always lands on `CType.CONSULTATION`/`CLARIFY` — proving tier
alone cannot rescue a gated candidate.

### 3.2 Second enforcement point — `pipeline/run.py::_reassert_f1_gate()` — found by adversarial review, not by design foresight

**This enforcement point exists only because the first one, alone, had a real, live bypass.** Say
this plainly rather than smoothing it over, per this project's own `CLAIMS.md` discipline: it was
found by an adversarial review pass this session (the Phase 2 verify agent, reported honestly as
`f1_invariant_holds: false`, `overall_verdict: needs_fixes` — not rubber-stamped), *after*
`authorize()`'s gate above was already built and believed complete — not anticipated in the
original design.

The bug (`src/pgcross/pipeline/run.py:104-124`, `run_pipeline()`): two opt-in, off-by-default
extensions — `imagine_bridge` (`enable_imagine_bridge`) and `_general_chat_fallback`
(`enable_general_chat_fallback`, defined at `run.py:33-72`) — each run *after* `assemble()`/
`authorize()` has already produced a safe `resp`. Both append a new `CType.GUESS` candidate and
then recompute `resp.primary` with a bare call to `pipeline.lens.pick_primary()`
(`run.py:115-116`, `120-122`). `pick_primary()` (`src/pgcross/pipeline/lens.py:21-25`) ranks
candidates purely by `(tier, ctype-order)` — its `order` table ranks `CType.GUESS` (2) *above*
`CType.CONSULTATION` (0) at equal tier (both commonly `Tier.Open`). `pick_primary()` has **no
knowledge of `AuthorizationResult` at all** — it is a pure Propose-stage ranking function.

Consequence: an ESCALATE-classified query whose `authorize()` call had already correctly pinned
`primary` to a safe CONSULTATION candidate could have that decision **silently overwritten** by the
newly-appended, completely unguarded GUESS candidate the moment `imagine_bridge` or
`_general_chat_fallback` fired — because `run_pipeline()`'s own post-append `pick_primary()` call
re-derives `primary` from scratch, discarding `authorize()`'s gate decision entirely.

Both flags are `False` by default (`Config.enable_imagine_bridge`, `Config.enable_general_chat_fallback`,
`run.py:21-22`), so **no current deployment was exposed** — but the gap was real, reproducible, and
would have fired for the exact production use case these fallbacks exist for (making PGCross usable
as a general chat backend when no structured signal exists).

The fix, `_reassert_f1_gate(resp, q)` (`run.py:75-101`), is called immediately after every
post-`assemble()` `resp.primary` recomputation (`run.py:117`, `123`): if `resp.authorization.status`
is `REJECT`/`ESCALATE` and the current primary is not already `CONSULTATION`/`CLARIFY`, it re-pins
primary to an existing CONSULTATION candidate, or defensively creates one — re-asserting exactly the
invariant `authorize()` established, after any code downstream is allowed to touch `resp.primary`.

**Both bypass shapes are covered by `tests/test_f1_gate_bypass_integration.py`**, an
integration-level test added specifically to catch a regression of this bug class (not just the
unit-level `authorize()` test from §3.1):

- `test_general_chat_fallback_cannot_bypass_escalate_end_to_end` and
  `test_imagine_bridge_cannot_bypass_escalate_end_to_end` drive the real `run_pipeline()` end-to-end
  with fake backends that return deliberately unguarded replies, and assert the GUESS candidate is
  genuinely appended (proving the fallback actually fired) yet never becomes primary.
- `test_proves_the_guard_matters_general_chat_fallback` and
  `test_proves_the_guard_matters_imagine_bridge` monkeypatch `_reassert_f1_gate` to a no-op
  (`run.py`'s pre-fix behavior, without editing the source) and assert the **old unsafe behavior
  actually reproduces** — the unguarded GUESS candidate does become primary — proving the two tests
  above are real regression guards, not vacuously-passing assertions.

---

## 4. `crisis_resources.py` wiring

`src/pgcross/crisis_resources.py` is a small, static, **offline** directory of crisis resources
(Thailand-specific numbers — police/emergency 191, medical emergency 1669, mental-health hotline
1323, Samaritans Thailand, etc. — plus an international fallback pointing to
`findahelpline.com` and "call your local emergency number"). `render(lang, region)` produces an
EN/TH text block with an explicit honesty disclaimer ("I am not an emergency service ... please
verify"). No network call is made.

**Wiring is scoped narrowly to the ESCALATE (self-harm) path only.** In `authorize()`
(`pipeline/authorize.py:186-188`):

```python
if status is AuthorizationStatus.ESCALATE:
    _attach_crisis_resources(cands[primary])
```

`_attach_crisis_resources()` (`authorize.py:20-28`) appends `crisis_resources.render()`'s text
onto the now-primary CONSULTATION candidate's `.content`, guarded by a `_CRISIS_MARKER` substring
check (`"findahelpline.com"`) so repeated calls against the same candidate never double-append.

This is deliberately **never** fired for:
- `REJECT` (harm-to-others, e.g. weapons/dangerous-synthesis) — "how do I make a bomb" has no
  crisis-bridge referral to offer; the module's own docstring states over-triggering a crisis
  resource on a non-self-harm case would be its own kind of harm.
- Plain `ADVISORY`/`HOLD` paths — no harm signal fired at all.

This scoping is verified explicitly by the Phase 3/4 adversarial review
(`the project's internal status notes`: "`crisis_resources.py` wired into `pipeline/authorize.py`'s ESCALATE
(self-harm) path only — narrowly scoped, idempotent, verified NOT to fire on REJECT (harm-to-others)
or ADMIT/HOLD").

---

## 5. Honest status — what is and is not done

**Tested, both at unit and integration level:**
- `tests/test_f1_gate_bypass.py` — F1 in isolation, against `authorize()` directly (4 tests: the
  precondition check, ESCALATE-via-query, ESCALATE-via-candidate-content, REJECT, plus a
  non-adversarial control that the ordinary I2/I5/I4/D2 path is undisturbed).
- `tests/test_f1_gate_bypass_integration.py` — F1 end-to-end through `run_pipeline()`, covering
  both bypass surfaces (`_general_chat_fallback`, `imagine_bridge`) that motivated
  `_reassert_f1_gate()`, plus two "proves the guard matters" tests that monkeypatch the guard to a
  no-op and confirm the old unsafe behavior actually reproduces (not a vacuous pass).
- `tests/test_admit_hold_reject_escalate.py` — the DANGER/ADVISORY/WEAKNESS taxonomy: regex-parity
  diffs against the legacy `humane_gate.py` (set-equality, not just spot checks), fixture-based
  harmful/benign classification, the engineering-decision-log-confirmed mapping's four outcomes,
  and an `ast`-based import-boundary check that `policy.py`/`harm_net.py` never import from the
  dead legacy modules.

**What is NOT yet done — stated plainly, not implied closed:**

1. **`decision.schema.Candidate`/S4 machinery is not yet threaded into the live `verify()` →
   `authorize()` path.** Only `core.models.EvidenceCandidate` flows through the served pipeline
   today. `decision/schema.py`'s `Candidate` (with its required `S4` `resolution` field),
   `VerificationResult`, and the `evidence_candidate_to_decision_candidate()` adapter are real,
   tested code — but `pipeline/authorize.py` currently reconstructs a *proxy* witness signal
   (`_witness_probe()`, `authorize.py:45-66`) from `EvidenceCandidate.provenance.verifiability`
   alone, rather than consuming a real `VerificationResult` that `verify()` produced. The proxy is
   documented as temporary in its own docstring ("once `verify()` threads the real
   `VerifierResult` through to `authorize()` ... this shim should be replaced with the real value,
   not kept alongside it").
2. **No real `DecisionBackend` is wired in yet.** `needs_decision_backend()` is a real, tested,
   pure function (`authorization/policy.py:183-195`), but nothing in the live pipeline calls a
   `DecisionBackend.decide()` when it returns `True` — `_authorize_status()` defaults straight to
   `HOLD` instead (`authorize.py:96-123`, explicitly marked `*** TEMPORARY BEHAVIOR ***` in the
   code). OpenThai-SystemOne is confirmed in the project's engineering decision log as the intended
   production backend (`the project's internal engineering decision log` Phase 0 item 2), but its implementation is still
   design-only.
3. `safety.py` (the pipeline's independent pre-flight safety check, distinct from the harm-net
   taxonomy described here) remains a self-labeled keyword stub by engineering decision
   (`the project's internal engineering decision log` Phase 0 item 6: "stays a dev-stub for now — no red-team scoping work starts
   yet"). This document does not claim otherwise.
4. Whether `REJECT`/`ESCALATE` should also filter the dangerous candidate out of
   `resp.candidates` entirely (not just out of `primary`) is an open design question, flagged but
   not resolved (the project's internal status notes' "what remains open" list).

---

## 6. Cross-references

- `the project's internal architecture audit notes` — the Phase A audit that first named F1–F15 as required
  invariants and confirmed none of them existed or were tested before this work.
- `the project's architecture design notes` §2.3/§2.4/§2.5/§3 — the `A3` witness/`S4`/resolution-gate
  formal grounding (Toledo-verified primitives) that `needs_decision_backend()` and
  `decision/schema.py`'s `S4`-typed fields implement.
- `the project's internal engineering decision log` Phase 0 item 5 — the engineering decision log entry this document's §2 quotes
  verbatim.
- `docs/DECISION_MODEL.md` (parallel doc, same batch) — the Propose-stage `Candidate`/
  `DecisionProposal`/`DecisionBackend`/`ComputationBackend` machinery this document deliberately
  does not duplicate.
