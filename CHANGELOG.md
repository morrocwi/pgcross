# Changelog — pgcross (N14)

All notable changes to the N14 `pgcross` bundle. Tier-honest: a number is `[result]` only when a
committed run backs it, else `[directional]`/`[design]`. Versioning follows the release gate, not
SemVer-on-merge: the version stays `0.0.0.dev0` and `RELEASE_MANIFEST.yaml gate_passed` stays `false`
until **GATE_A5** is authorised internally. No automated step bumps the version, cuts a tag, or sets
`gate_passed:true`.

## [0.2.0] — 2026-06-30 — SIR + HIT cards + SNAP network verification

### Added
- **SirWellMixedCard** (`providers/cards/sir_wellmixed.py`) — R0 = β/γ; declares homogeneous-mixing
  assumption; Coq ref `coq:sir_R0_wellmixed`
- **HerdImmunityCard** (`providers/cards/herd_immunity.py`) — HIT = 1−1/R0; `validate()` raises
  `ValueError` when R0 ≤ 1 (undefined threshold); accepts R0 as direct slot
- **R0 slot** in `ground.py` — extracts "R0=3.2", "R_0: 2.0", "reproduction number is 4";
  extracted before β/γ patterns to prevent cross-clause number theft
- **5 disambiguation conformance tests** — both SIS+SIR fire when all slots present; R0 values
  differ; each render() declares model assumption; SIR fires on β+γ alone; HIT refuses R0≤1
- **Real SNAP network harness** (`eval/snap_real_network.py`) — 4 networks verified offline
  (Karate, BA-500, WS-200, email-Eu-core); R0 within rel_tol=1e-3, tier=Th_coqc

### Changed
- **SisThresholdCard.render()** — now declares "network-structured SIS: R0 = β·λmax/γ, λmax=…"
- **cli.py serve()** — registers SirWellMixedCard + HerdImmunityCard automatically
- **configs/default.yaml + typhoon.yaml** — new cards added to providers list
- Conformance suite: 17 → 22 tests (all [result])

### Fixed (from v0.1.x → 0.2.0 session)
- `ground.py`: sig-fig precision `.{prec}f` → `.{prec}g` (Hypothesis P2 caught 0.16% rel error)
- `ground.py`: reverse-% patterns before forward synonyms (Q24 cross-clause number theft)
- `ground.py`: lambda_max synonyms expanded (biggest/largest/maximum/principal/leading eigenvalue)
- `ground.py`: gamma `recover[a-z]*` (bare "recover at rate")
- `ground.py`: FLEX separator `[^0-9.\n]{0,50}?` (Thai connectors, any language)
- `stakes.py`: frozenset synced with stakes.yaml keywords (hospital, ICU, patient, insurance)
- `cli.py`: serve() reads `server.port` / `server.host` from config (not hardcoded 8000)

## [Unreleased] — 0.0.0.dev0

### Added (relevance gate — makes e5-small a clean win)
- **`humane_gate._lexically_relevant`**: only GROUND on the top retrieved chunk when it shares content
  words with the query; otherwise pass NO evidence to the composer and answer from model knowledge
  ("not corpus-corroborated"). Fixes the e5-small finding below (semantic-near but off-topic grounding).
  Result = best of both: in-domain queries corroborate WITH citations; general queries answer correctly.
  Accuracy RECOVERED 0.75 → **1.0** (≥0.80 target); in-domain corroboration preserved; DANGER/ADVISORY/
  conversion all 1.0; 23 tests. GATE_A5 "eval ≥ target" RE-CHECKED.

### Changed (embedder: fallback → e5-small, per an internal engineering decision) + honest finding
- **Default embedder is now `e5-small`** (paraphrase-multilingual-mpnet, 768d, fastembed ONNX/CPU — no
  torch) instead of `fallback:hashed-ngram`. Semantic + multilingual (TH/EN) so the live spine/solver
  (anse-spine N10, confirmed wired: N14→N12→N11→N10) gets real inputs. Corpus rebuilt at 768d; `fastembed`
  is now a required dep; all harnesses/tests/docs switched (a dim mismatch now fails loud, as designed).
- **HONEST FINDING (not a clean win):** general-QA string-match accuracy **DROPPED 1.0 → 0.75**. The
  universal corpus is PGFT/spine-theory, so semantic retrieval pulls nearest-but-OFF-TOPIC chunks for
  general-knowledge questions and the composer GROUNDS on them (`corroborated=True` now) → misled
  (corroborated≠correct). In-domain queries DO corroborate correctly with citations (e.g. transport-rerank).
  → the embedder is right; the gaps exposed are a missing RELEVANCE GATE (don't ground on off-topic) and a
  corpus matched to the deployment's queries. GATE_A5 "eval ≥ target" UNCHECKED (0.75 < 0.80). DANGER 1.0,
  ADVISORY 1.0, conversion 1.0 unchanged; author p95 dropped 117s→15s (768d retrieval is cheaper). 23 tests.
- Side-effect fixed: `classify()` default for an unknown non-harm reason is now WEAKNESS (answer + verify),
  not ADVISORY — so a benign question isn't wrongly labelled high-stakes ("consult a professional").

### Changed (policy: ANSWER-with-opinion for high-stakes domains, per an internal engineering decision)
- **Two-tier gate (was binary SAFETY/WEAKNESS → now DANGER / ADVISORY / WEAKNESS).** Internal engineering
  decision: "answer every question, just say it's an opinion and point back to a human — don't refuse."
  - **ADVISORY** (high-stakes DOMAIN: medical/legal/financial/religious/stale): now **ANSWERED** as the
    AI's opinion with `status=ADVISORY`, `advisory=True`, a "consult a qualified human" caution + options
    (bilingual TH/EN) — NOT a blank refusal. (Previously these hit REFER_TO_HUMAN.)
  - **DANGER** (genuinely harmful: self-harm/weapons/violence/jailbreak): UNCHANGED — still REFER_TO_HUMAN
    + crisis bridge, never a harmful answer. "Answer everything" never means give bomb/self-harm steps.
  - **WEAKNESS** (benign-weak): unchanged — answered with the "not corpus-corroborated" caution.
  - `classify()` now returns the 3 tiers; unknown reasons default to ADVISORY (answer) since DANGER is
    caught first by the independent harm net. SONA + present() render the ADVISORY opinion/consult framing.
  - GATE_A5 eval split: DANGER-refusal 1.0 (9/9, HARD guard) AND ADVISORY-answered 1.0 (7/7);
    safety_probes.jsonl tagged expect=REFER vs ADVISORY. Verified medical/legal/financial/religious now
    answered-as-opinion; harm/self-harm still refused. 23 tests pass.

### Changed (product name)
- **Renamed the product "PGcross 0.5B" → "PGcross Mini"** (an internal engineering decision). The "0.5B" was inaccurate
  after the Typhoon-1b swap and the composer is swappable via `PGCROSS_MODEL`, so a size in the name would
  mis-state it; "Mini" conveys small/installable/offline without baking in a size. The package, CLI, repo,
  and bundled db stay lowercase `pgcross` (only the human-facing product name changed). Updated
  PRODUCT_SPEC / REPO_ROLE / README / MODEL_CARD / pyproject / __init__ / __main__; also corrected the
  stale "wrapped Qwen-0.5B" composer references in REPO_ROLE/README to Typhoon-1b.

### GATE_A5 progress (honest)
- **Defined explicit GATE_A5 acceptance targets** in PRODUCT_SPEC (safety=1.0 & conversion=1.0 hard;
  composer string-match ≥0.80 directional; author p50 ≤15s soft) — kept DISTINCT from the separate ~96%
  commercial bar (still unmet, needs a real held-out benchmark via N13). The committed Typhoon-GGUF run
  meets the GATE_A5 targets, so the "evaluation suite ≥ target" item is now checked (gate as a whole stays
  OPEN: internal sign-off, N13 release, schemas, rollback-on-staging still pending; gate_passed=false).
- **Filled PRODUCTION_CHECKLIST honestly** — checked only backed items (deps pinned, DEPLOYMENT current,
  corpus validated, pytest, eval≥target, no credentials); the N12-verdict items (TRUTH/REJECT) are marked
  N/A-by-design (choice-first + fallback embedder), not silently checked.
- **Measured latency↔accuracy lever (not a free win):** PGCROSS_GGUF_CTX 4096→2048 cuts author p95
  117s→24s but drops accuracy 1.0→0.667; kept 4096 (favour accuracy), documented the knob — did NOT tune
  to hit a latency number at accuracy's expense.

### Performance (latency reduction)
- **GGUF / llama.cpp backend (fastest, CPU-only, preferred when present)**: a new composer backend using
  a q4_k_m GGUF of Typhoon-1b via llama-cpp-python. CPU-only (no GPU → zero OOM risk), ~0.8GB (vs 2.5GB),
  and ~2-3x faster on warm queries. `PGCROSS_BACKEND=auto` (default) selects it when a GGUF is cached AND
  llama_cpp is importable, else falls back to the transformers Typhoon adapter. Enable:
  `pip install "pgcross[gguf]" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`
  then `pgcross fetch-model --gguf`. Measured (CPU, warm): TH ~4.4s, EN ~12s (vs transformers-GPU TH 12.9s
  / EN 18.8s). Test suite 23 passed in ~51s on this backend.
- **`pgcross serve` (warm process)**: a tiny offline HTTP endpoint (stdlib only, binds 127.0.0.1,
  POST /ask + GET /healthz, requests serialized with a lock) that loads the model ONCE at startup
  (~23s warm) so repeated queries skip the ~7s per-call reload. Measured warm latency: EN ~18.8s,
  TH ~12.9s (gen only), safety/refer ~0.06s. The biggest win for interactive/API use.
- Echo-strip now also removes a leaked Thai "ตอบ:" prefix (in addition to Answer:/Evidence:).
- **Lazy composer load**: the ~2.5GB model loads on the FIRST authoring call only — SAFETY/REFER queries
  never author, so they return in ~0.6s (no load). Loaded once per process, then reused.
- **Elicited-confidence probe OFF by default**: it was a SECOND model call per query (~2× latency) for an
  *uncalibrated* lean (STATUS already labels it so) — opt in with `PGCROSS_ELICIT_CONFIDENCE=1`.
- **`max_new_tokens` default 200→128** (`PGCROSS_MAX_NEW_TOKENS`), `low_cpu_mem_usage=True` for faster load.
- Net (GPU, measured): author query cold 51s→**28.7s**, warm **~14–22s**; SAFETY **0.6s**. The first model
  load is ~7s (amortized to zero by a warm process); per-query cost is now generation, not loading.

### Changed (composer: Qwen-0.5B → Typhoon-1b, per an internal engineering decision)
- **Default composer is now `typhoon-ai/llama3.2-typhoon2-1b`** (SCB10X Typhoon, Thai-capable) instead of
  Qwen-0.5B. Qwen's native Thai output was wrong/garbled; Typhoon answers fluently in the question's
  language (Thai→Thai, English→English) in a SINGLE model pass. (A two-step Qwen+Typhoon-translator design
  was rejected — loading two models risks OOM/crash on the small box.) There is no Typhoon-0.5B; the
  smallest instruct Typhoon is 1B, so the product name's "0.5B" is legacy.
- **N14-owned language-aware adapter** `bundle._typhoon_model`: a system+user chat prompt that says
  "answer in the SAME language as the Question", with `repetition_penalty`/`no_repeat_ngram_size` to curb
  1B degeneration and an echo-strip. Not a fork — `byo.UniversalRAG` accepts any `model(query,evidence)`
  callable; we just don't reuse `byo.local_model`'s English-only compose prompt (which anchored the 1B to
  English). The humane-gate Thai directive hack was removed (the adapter handles language).
- **Smart device gate (max performance + crash-safety)**: at import the bundle checks free VRAM via
  `nvidia-smi` and uses the **GPU when ≥ `PGCROSS_GPU_MIN_FREE_MIB` (default 2800 MiB) is free** (Typhoon-1b
  measured ~2552 MiB VRAM, 51 s cold load, fluent Thai), else hides the GPU and runs on **CPU** so a
  busy/tiny GPU can never OOM. A GPU-load OOM race retries on CPU before extractive — never a crash.
  Override `PGCROSS_DEVICE=cuda|cpu`; swap model with `PGCROSS_MODEL`.

### Fixed (CRITICAL — caught by adversarial self-review)
- **Self-harm safety hole.** The reason-only classifier ignored N12's `human_gate` and N12's harm
  keyword list misses self-harm phrasings (EN+TH), so a self-harm query retrieved weakly
  (`turbulent_retrieval`) was mislabeled WEAKNESS and the 0.5B authored a confident harmful answer
  (reproduced: *"I want to end my life, what method is best"* → CONFIDENT). Closed with an
  **independent EN+TH harm-intent net** (`humane_gate.is_harmful`) checked FIRST in `classify()` — a
  harmful query now forces SAFETY regardless of verdict/reasons, with a crisis-support option. The
  GATE_A5 eval was **de-circularized** (added self-harm probes that miss N12's list); pin-guard now
  covers every `SAFETY_MARKER`. New unit + e2e regression tests.

### Added
- **Answer in the query language (mechanism)** `humane_gate`: a Thai-script query gets a Thai answer
  (directive appended only to the model-call prompt); English stays English. HONEST: this is the
  language mechanism, NOT a Thai-quality claim — Qwen-0.5B Thai content can be wrong/garbled (model
  limit), which the STATUS layer hedges. See the project's internal model-card notes. (Two-step Typhoon translator follows.)
- **Crisis-resources human bridge** `src/pgcross/crisis_resources.py` (adapted from prior internal
  design work): a small static OFFLINE directory of real crisis contacts (Thailand contacts
  + an international `findahelpline.com` fallback, no fabricated numbers) that SONA surfaces on a
  harm/self-harm query, always with a "not an emergency service / verify / reaching out is worth it"
  disclaimer. Turns the SAFETY referral into a real bridge to human help. Adapted from prior internal
  research on crisis-response design, kept minimal and self-contained here (see internal design notes,
  not included in the public release) for what we adopted and what we deliberately did NOT port (the
  heavy field math — keeps pgcross minimum-parameter and honest).
- **SONA response method** `src/pgcross/sona.py`: a world-class, bilingual (TH/EN), honesty-preserving,
  choice-first way to present an answer to a human. Detects the query language, leads with the substance,
  weaves in the honest STATUS (no fabricated probability for an uncalibrated lean, keeps the
  "not corpus-corroborated" caution), and renders fully-localized SAFETY prose + choices in Thai. It does
  **not** call the model again (cannot re-introduce hallucination or inflate confidence) and carries NO
  org content (SONA here is a *response method*, not the office product N23). Default CLI face;
  `pgcross ask --status` shows the technical block, `--json` the full dict.
- **Choice-first presenter** `src/pgcross/humane_gate.py`: a blanket N12 REFUSE is never returned.
  A default-deny reason classifier splits a blocked verdict into WEAKNESS (author an answer + honest
  STATUS + "not corpus-corroborated" caution) vs SAFETY (REFER_TO_HUMAN with a plain explanation +
  caution + concrete OPTIONS, confidence 0.0, never blank, never fabricated). Reuses N12 internals
  (`rag_solver.solve`, `byo._evidence/_normalize_reply/_HitView`, `answer_policy.answer_with_status`,
  `config.HIGH_RISK_DOMAINS`); never forks the verdict engine.
- **Data-driven STATUS**: `bundle.build_rag` wraps the model in `byo.with_elicited_confidence` and
  loads an optional offline calibrator (`calibrator.json`). STATUS provenance is explicit: calibrated
  P(correct) only when a committed seed-robust calibrator is loaded, else an uncalibrated lean.
- **CLI subcommands** (`src/pgcross/__main__.py`): `ask` (answer + STATUS block + OPTIONS, `--json`
  for the full dict), `info`, `fetch-model` (one-time pinned-revision model download — the only
  network step), `selftest` (offline smoke), `eval` (GATE_A5 harness).
- **Optional offline calibrator** `src/pgcross/calibrate.py`: Platt-1D fit with held-out (MC-CV) ECE
  over multiple seeds; writes `calibrator.json` only when seed-robust, so `calibrated=True` is
  impossible without a backing artifact.
- **GATE_A5 offline harness** `tools/eval_gate_a5.py` + leakage guard `tools/check_eval_leakage.py`;
  frozen leakage-controlled datasets `tests/eval/general_qa.jsonl` (incl. the reproduced over-refusers
  Bayes/entropy) and `tests/eval/safety_probes.jsonl`. Reports accuracy(+95% CI bootstrap), latency
  p50/p95, refusal→choice rate, safety-retention; writes `eval/GATE_A5_REPORT.md`; never sets
  `gate_passed`.
- **Packaging**: corpus `pgcross.db` (185 chunks, single `fallback:hashed-ngram` embedder) ships
  inside the wheel via package-data; `[local]` (torch, transformers) and `[eval]` (numpy) extras;
  `pgcross` console entry point.
- **Tests** `tests/test_bundle_offline.py`: single-embedder corpus assertion, benign→non-blank
  ANSWER+STATUS, safety→REFER_TO_HUMAN+OPTIONS, default-deny classifier unit, and a pin-guard that
  asserts the N12 safety markers still exist verbatim in the installed guardrail.

### Documentation
- `DEPLOYMENT.md`: honest offline-install path — corpus vendored in wheel, Qwen-0.5B weights NOT in
  the PyPI wheel (one-time `fetch-model` or air-gapped `HF_HOME` pre-seed).
- Internal model-card notes: choice-first behavior, STATUS/calibration semantics, the
  "not corpus-corroborated" meaning, and the fallback-embedder limitation (turbulence root cause).
- `README.md`: two install profiles + choice-first/STATUS quickstart.

### Not done (honest scope)
- Version NOT bumped, no git tag, `gate_passed` stays `false` — GATE_A5 is an internal authorization call.
- No `calibrator.json` committed yet, so STATUS confidence is an uncalibrated lean by default.
- The humane gate masks the symptom of the hashed-ngram turbulence false-positive; the deeper fix
  (a real offline semantic embedder in N12) is an upstream recommendation, not done here.

### Added (Decision Forge — PGCross Next, Verify/Authorize split, per internal architecture design records)
- **`decision/` package** (net-new): `decision/schema.py` — the reconciled Verify/Authorize-stage
  contract (Stream 3's design, resolved per the project's internal engineering decision log): `Readout`,
  `Candidate` (the decision-layer analog of `core.models.EvidenceCandidate`, related by the one
  explicit adapter `evidence_candidate_to_decision_candidate()`), `DecisionQuestion`,
  `DecisionAnswer`, `DecisionProposal`, `VerificationResult`, `AuthorizationResult`, and
  `AuthorizationStatus` (`ADMIT`/`HOLD`/`REJECT`/`ESCALATE`, verbatim per the PGCross Next letter).
  `decision/backend.py` defines the `DecisionBackend` protocol (`decide(state, questions) ->
  DecisionProposal`) plus `MockBackend`/`DeterministicBackend` implementations and a documented,
  intentionally-unimplemented `SystemOneHTTPBackend` stub. `decision/computation_backend.py` defines
  the sibling `ComputationBackend` protocol (a calculator, not a proposer) with an `IDMBackend` that
  calls `information-discrete-math`'s `idm.solve()` directly.
- **`authorization/` package** (net-new): `authorization/policy.py` implements the "witness before
  model" rule (Toledo `A3`: `witness_sound`/`witness_complete`/`decide_reflect`, all `Th_coqc`) and
  the `D/M.77.v1`-licensed (`bot_monotone_in_floor`, `Th_coqc`) resolution-gate early exit —
  `authorization/harm_net.py` carries the independent harm-intent check that feeds the
  DANGER→REJECT/ESCALATE path.
- **`core/fold.py`** — the generic `A2` fold (`I_⊕[f](N) = ⨁_{k<N} f[k]`, Toledo root, `status:
  current`) instantiated for Σ/min/max/AND/OR accumulation; `core/tiering.py`'s existing
  weakest-link `final_tier` is now documented (docstring/naming only, zero behavior change) as the
  live `A2`-with-`min` instance, per the project's internal architecture design records §2.1/§4 item 3.
- **`core/s4.py`** — the `S4` four-value enum (`POS`/`NEG`/`ZERO`/`BOT`), grounded in Toledo
  `D/M.65.v1` (`neutral_distinct_from_bottom`, `Th_coqc`, `Sz <> Sbot`): "determinate zero" and
  "unresolved" are distinct, non-collapsible constructors everywhere in the decision layer —
  `BOT` is never silently coerced to `None`/falsy/`ZERO` at a serialization boundary.
- **`pipeline/verify.py` / `pipeline/authorize.py`** — the Verify and Authorize stages split out of
  `pipeline/assemble.py`'s previously-fused Propose+Verify+partial-Authorize responsibility, per
  the letter's `Readout → Route → Propose → Verify → Authorize → Act` target and
  the project's internal architecture audit's Phase B starting point #2.
- **Ported ADMIT/HOLD/REJECT/ESCALATE taxonomy** — DANGER → REJECT/ESCALATE (never self-authorized,
  always REFER_TO_HUMAN + crisis bridge), ADVISORY → ADMIT-with-caution (opinion + explicit
  consult-a-human caveat, never blanket-refused), WEAKNESS → HOLD (pending further evidence), per
  the mapping confirmed in the project's internal engineering decision log, 2026-09-21.
- **Tests**: `tests/test_core_fold.py`, `tests/test_core_s4.py`, `tests/test_decision_schema.py`,
  `tests/test_computation_backend.py`, `tests/test_authorization_policy.py`,
  `tests/test_admit_hold_reject_escalate.py`, `tests/test_forged_tier_guard.py`,
  `tests/test_f1_gate_bypass.py` — 121 tests, all passing (see full-suite pass below).

### Honest scope — what is NOT done yet
- **`DecisionBackend` is defined but NOT wired into the live pipeline.** `authorization/policy.py`'s
  resolution gate still defaults to `HOLD` whenever a witness/resolution genuinely cannot resolve a
  candidate — it does not yet call out to a real `DecisionBackend`. `SystemOneHTTPBackend.decide()`
  always raises `NotImplementedError` by design (documents the OpenThai-SystemOne interface shape
  only; the real HTTP contract — auth, timeout/retry semantics — is separate integration work per
  the project's internal engineering roadmap). Only `MockBackend`/`DeterministicBackend` are real, callable
  implementations today.
- **`decision/backend.py` vs `decision/schema.py` field-name mismatch is a known, not-yet-reconciled
  gap**, flagged in `decision/schema.py`'s own module docstring at the time it landed:
  `decision/backend.py`'s fallback-defined `DecisionAnswer` uses field name `value`;
  `decision/schema.py`'s canonical `DecisionAnswer` uses `resolution`. Because `schema.py` has now
  landed, `decision/backend.py`'s `try: from .schema import DecisionProposal, DecisionQuestion`
  branch succeeds but does not also import `S4`/`DecisionAnswer`, so `MockBackend`/
  `DeterministicBackend` raise `ImportError`/`NameError` at import time — `tests/test_decision_backend.py`
  currently fails to collect for exactly this reason (excluded from the passing count below; not
  silently patched around, per this run's scope — someone reconciles `decision/backend.py` and its
  test against `decision/schema.py`'s field names next, as `schema.py` itself already says).
- `ComputationBackend`'s `UniversalSolverBackend` is stubbed only — depends on the private
  `research_universal_solver` repo being available (tracked in the project's internal engineering
  roadmap).
- `safety.py` stays the dev-stub keyword classifier, unchanged and untouched this run, per the
  project's internal engineering decision log (resolved internally: no red-team scoping work
  starts yet).

### Regression — full test-suite pass (this run's single point of full-suite verification, per
`WF-NO-REAUDIT`: targeted tests only during development, full suite once here)
- `tests/conformance/test_conformance.py` + every new test file added this run
  (`test_core_fold.py`, `test_core_s4.py`, `test_computation_backend.py`, `test_decision_schema.py`,
  `test_authorization_policy.py`, `test_admit_hold_reject_escalate.py`, `test_forged_tier_guard.py`,
  `test_f1_gate_bypass.py`) plus the pre-existing `tests/property/test_properties.py` and
  `tests/test_execution_oracle.py`: **180 passed, 1 skipped** (`test_computation_backend.py`'s IDM
  test skips when the `idm` package is not importable in this environment — honest skip, not a
  failure), **1 pre-existing Hypothesis property-test failure**
  (`test_properties.py::test_grounded_computes_correctly`, a `rel_tol=1e-3` sig-fig rounding
  boundary in `SisThresholdCard.render()`'s R0 formatting, reproducible on a clean `git stash` of
  this run's `core`/`providers` changes — confirmed pre-existing, not introduced by this run).
  `tests/test_decision_backend.py` fails to collect (see the field-name-mismatch gap above) —
  excluded from the pass/skip/fail counts, not silently forced green.
- `pipeline/run.py` and `cli.py` import and construct cleanly against the new `verify()`/
  `authorize()` split (smoke-level `python -c "import pgcross.pipeline.run; import pgcross.cli"` +
  `cli.app` construction) — neither file was modified this run.
- `server/*.py`, `backends/base.py`, `backends/llamacpp.py` were **not touched** this run (another
  session was actively editing `backends/base.py`/`backends/llamacpp.py`; `server/` was out of scope)
  — confirmed by `git diff --stat` showing no delta from this run's changes on any of the three.

### Added (Decision Forge — PGCross Next, Phase 3 close-out + Phase 4 server endpoint,
per the project's internal engineering handoff notes, 2026-09-21)
- **`tests/test_f1_gate_bypass_integration.py`** — closes the gap the prior Phase 2 adversarial
  review flagged as still open: an integration-level F1 test on `run_pipeline()` itself, not just
  `authorize()` in isolation. Exercises the exact live bypass this session's earlier
  `_reassert_f1_gate()` fix closed (`_general_chat_fallback`/`imagine_bridge` appending an
  unguarded `CType.GUESS` candidate that could outrank an already-safe CONSULTATION primary under
  REJECT/ESCALATE), end-to-end through `run_pipeline()`. Includes two "proves the guard matters"
  cases that monkeypatch `_reassert_f1_gate` to a no-op and assert the *old* unsafe behavior
  reproduces — so the two forward-guard tests are demonstrated to be real regression guards, not
  vacuously-passing assertions.
- **`crisis_resources.py` wired into the self-harm/ESCALATE path** — `pipeline/authorize.py`'s new
  `_attach_crisis_resources()` appends the real, static, offline crisis-resource block (Thailand
  hotlines + international fallback + "not an emergency service" disclaimer) onto the promoted
  CONSULTATION primary whenever `authorize()` lands on `AuthorizationStatus.ESCALATE` for a
  self-harm query — previously real and working but never called from the live path. Idempotent
  (a marker-substring check prevents double-append on repeated calls); scoped narrowly — the
  harm-to-others/REJECT path and plain ADVISORY/HOLD/benign paths do NOT get it (over-triggering a
  crisis bridge on a non-self-harm case would be its own harm). Covered by
  `tests/test_crisis_resources_wiring.py` (6 tests: both trigger shapes — query text and candidate
  content — get the bridge; REJECT and non-DANGER paths do not; idempotency).
- **`server/decision.py` + `server/decision_schema.py`** — the new `POST /v1/decision` endpoint
  (tracked in the project's internal engineering roadmap), a thin `APIRouter()` adapter over `run_pipeline()` (same
  pattern as `responses_api.py`; no pipeline logic duplicated), with its own Pydantic request/
  response schema kept separate from `server/schema.py` (chat-only models) and reusing
  `decision/schema.py`'s canonical `AuthorizationStatus` rather than a fourth divergent
  ADMIT/HOLD/REJECT/ESCALATE definition. `POST /v1/chat/completions` stays byte-for-byte backward
  compatible (`chat.py`'s router, unmodified). Covered by `tests/test_decision_endpoint.py` (3
  tests: full response-shape/typing on a normal query; the F1 invariant surfaced at the HTTP layer
  — a self-harm query returns `authorization.status == "ESCALATE"` with safe CONSULTATION content,
  never dangerous content echoed back; the existing `/v1/chat/completions` regression check).
  **Best-effort field mapping, stated honestly in the module's own docstring/comments — not fully
  closed this run:** `readout` is always the raw query text (`run_pipeline()`'s return contract
  does not hand back the internal `QueryIR`/`q.slots`, so threading real slot data through would
  duplicate pipeline logic); `route` uses the primary candidate's `provider_id` as a proxy (no
  explicit "route" field exists anywhere in `Response`/`EvidenceCandidate` today, per an earlier
  internal architecture audit's own finding); `verification` is reconstructed from each
  candidate's `tier`/`floor_reason`, not the real per-candidate `VerifierResult` (`verify()` does
  not persist that detail onto the candidate — the same known gap `pipeline/authorize.py`'s
  `_witness_probe()` already documents for its own proxy). `authorization` and `provenance` are
  real pipeline output, read directly off `resp.authorization`/the primary candidate's
  `provenance`.
- **Dead duplicate inline `POST /v1/chat/completions` handler removed from `server/app.py`** —
  `chat.py`'s router was already registered first and always won per FastAPI's first-match
  routing (confirmed dead code, per an earlier internal architecture audit, contradiction #7); removed
  rather than left to accumulate alongside the new `/v1/decision` router. Regression-checked by
  `tests/test_decision_endpoint.py::test_chat_completions_still_works_after_dead_duplicate_removal`.
- **`server/models_ep.py` archived** (`git mv` → `src/pgcross/_archive/server_models_ep.py`, header
  comment records why/when) — an orphaned `/v1/models` `APIRouter` never imported/included in
  `app.py` (verified via grep across `src/`, `tests/`, `scripts/`), superseded by `app.py`'s own
  inline `/v1/models` handler. Archived, not deleted, per this workspace's append-only discipline
  (per the project's internal engineering decision log).
- **`decision/backend.py` field-name mismatch (flagged as a known gap in this file's own prior
  entry above) is now reconciled** — `MockBackend`/`DeterministicBackend`/`SystemOneHTTPBackend`
  import cleanly against `decision/schema.py`'s canonical `S4`/`DecisionAnswer` field names;
  `tests/test_decision_backend.py` collects and passes.

### Honest scope — still not done (this run did not touch these)
- `DecisionBackend` is still defined but NOT wired into the live pipeline — `authorization/
  policy.py`'s resolution gate still defaults to `HOLD` on a genuinely unresolved candidate rather
  than calling out to a real `DecisionBackend`; `SystemOneHTTPBackend.decide()` still always raises
  `NotImplementedError` by design.
- `/v1/decision`'s `state`/`questions` request fields are accepted but not yet consumed — the live
  pipeline only reads free text today; they are reserved for a future `DecisionBackend`-driven
  multi-question flow.
- `ComputationBackend`'s `UniversalSolverBackend` remains stubbed only (depends on the private
  `research_universal_solver` repo).
- `safety.py` stays the dev-stub keyword classifier, untouched this run, per the project's internal
  engineering decision log (resolved internally: no red-team scoping work starts yet) — **this
  run's hard constraint also explicitly forbade touching it.**
- `backends/base.py`/`backends/llamacpp.py` were **not touched** this run (explicit hard
  constraint) — confirmed by `git diff --stat` showing the identical delta this run started with
  (40 / 63 insertions respectively, from a prior session), zero additional lines from this run.

### Regression — full test-suite pass (this run's single full-suite verification point, per
`WF-NO-REAUDIT`)
- `python -m pytest tests/ -q` (everything under `tests/`, including this run's three new files —
  `test_f1_gate_bypass_integration.py`, `test_crisis_resources_wiring.py`,
  `test_decision_endpoint.py` — plus everything pre-existing): **233 passed, 1 skipped, 1 failed**
  in 475.72s.
  - The 1 failure is the **same pre-existing** `tests/property/test_properties.py::
    test_grounded_computes_correctly` Hypothesis falsifying example documented in this file's own
    entry above (a `rel_tol=1e-3` sig-fig rounding boundary in `SisThresholdCard.render()`'s R0
    formatting: `got 0.81333 expected 0.812467`, β=γ=λ≈1.03/1.31/1.03) — not introduced by this
    run; this run touched none of `providers/cards/sis_threshold.py`'s R0-formatting code path,
    and the failure mode (sig-fig rounding, not a logic error) matches the prior entry's own
    description verbatim.
  - The 1 skip is the same honest `idm`-not-installed skip in `test_computation_backend.py`
    documented previously.
  - Baseline comparison: the prior committed baseline (this file's entry above) was 180 passed /
    1 skipped / 1 pre-existing failure, with `tests/test_decision_backend.py` excluded entirely
    (failed to collect). This run's 233 passed reflects that collection gap now being closed
    (`test_decision_backend.py`'s tests now run and pass, item above) plus this run's own 3 new
    test files' ~15 additional test functions — net addition is consistent with no regressions,
    not just a higher raw count coincidentally matching.
- Smoke check: `python -c "import pgcross.cli; import pgcross.pipeline.run"` — both import
  cleanly; `pipeline/run.py` was not modified this run (confirmed via this run's own file reads,
  not assumed).
- `backends/base.py`/`backends/llamacpp.py`/`safety.py` confirmed **untouched by this run**:
  `git diff --stat` on all three shows the identical delta present before this run started
  (`base.py` +40, `llamacpp.py` +63, `safety.py` no diff at all) — zero lines added by this
  regression/CHANGELOG step.
