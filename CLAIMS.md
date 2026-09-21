# CLAIMS — pgcross-1

> Pre-registered claims with measured numbers and kill conditions.
> A number appears here ONLY when a committed eval run backs it.
> Format: claim → metric → measured value → CI → kill condition.

## K1 — Engine causality (PASSED)

**Claim:** the engine, not the controller LLM, produces structure-determined answers.
**Metric:** C2-K1 ablation ladder (placebo: engine output replaced by reference MC)
**Measured:** K1=0/51 (engine-off placebo correct), C2=51/51 (engine-on correct)
**CI:** [+1.000, +1.000] p=0.0000 (exact Binomial)
**Status:** PASSED
**Kill condition:** if engine-off placebo ever matches engine-on above epsilon on
structure-determined tasks, the engine is not doing the work.

## K4 — Verifier integrity (CONDITIONAL)

**Claim:** V_answer oracle catches computation errors.
**Actual:** oracle ACTIVE only on cards with `independent_oracle=True`.
Closed-form cards (sis_threshold, finance, epidemiology): oracle INACTIVE —
these cards are capped at Dr, not certified.
**Status:** CONDITIONAL
**Kill condition:** any card claiming tier above Dr without an active independent oracle
is a forged tier.

## K5 — Routing accuracy (SCOPED)

**Claim:** the pipeline routes queries to the correct engine card.
**Measured (real keyword-evading queries):** 0.785 (n=135)
**Measured (LOOCV calibration):** 0.911 — OPTIMISTIC by 12.6pp; do not cite as accuracy.
**Status:** SCOPED — 0.785 is the honest figure; 0.911 must not appear in any claim.
**Kill condition:** if real-query routing falls below 0.70 on a 200+ query held-out set,
a reroute mechanism is required before internal use continues.

## K2/K3 — Efficiency vs larger model (OPEN)

**Claim:** small model + engine matches or exceeds a larger standalone model on
structure-determined tasks.
**Measured:** NOT RUN. No comparison has been made.
**Status:** OPEN — gates the external "efficient-alternative" claim only.
Does NOT block internal use.
**Kill condition:** if small-model + engine loses to a modest 7B/14B on structure tasks
the engine dominates, the value story must be rewritten before any external release.

## Grounding robustness (PASSED)

**Claim:** grounding guards detect hallucinated or omitted parameters.
**Measured (eval/grounding_robustness_test.py, re-run 2026-09-21 to confirm — reproduced exactly):**
FP_rate=0.000 (24/24 clean paraphrases not falsely flagged);
recall=1.000 (15/15 hallucinated/omitted params caught)
**Status:** PASSED

Note (Phase 8 adversarial-review finding): this claim previously appeared in this file and in
`README.md` without its source script cited, unlike the RAG-entailment/K6 numbers above/below which
cite exact eval scripts. The source was identified and re-run to confirm the numbers still hold
(`python eval/grounding_robustness_test.py`, `VERDICT: PASS`); the citation above is now traceable.

## PROVE-IT items (required experiments — not done; not mere TODOs)

These cannot be closed by unit tests. Each requires a committed experiment on real data.

**Safety:** the shipped safety layer is a placeholder. `assert_serving_ready` guarantees
a layer is PRESENT, not that it WORKS. Measure refusal recall on adversarial inputs and
child-safety probes. Red-team required before any external use.

**RAG entailment:** `support_check` as shipped is lexical-only. Measure recall of False
on paraphrased unsupported claims and FP rate on diverse supported phrasings on real text.
A mock proves wiring; it does not prove ML quality. The NLI gate must be implemented and
measured before RAG grounding is treated as real.

**Backend transport:** verify that your chosen weights' JSON transport returns STRUCTURE
only and never asserts a fact (I7). A unit test proves wiring; only real inference on
your weights closes this.

**Routing:** measure real routing accuracy on a held-out set of 200+ keyword-evading queries.
The 0.785 figure is directional; intra-type mis-routing is a blind spot the verifier cannot
catch. Do not assume the argmax is correct without measuring it on your query distribution.

## Real SNAP network λmax (VERIFIED 2026-06-30)

**Claim:** pgcross-1 computes real network spectral radius (λmax) and SIS R0 correctly
on empirically-calibrated graphs from the Stanford SNAP collection.

**Measured (eval/snap_real_network.py, no server — offline oracle):**

| Network | n | e | λmax | β | γ | R0_oracle | verdict |
|---------|---|---|------|---|---|-----------|---------|
| N1 Zachary Karate Club | 34 | 78 | 21.688 | 0.20 | 0.10 | 43.375 | above |
| N2 Barabási–Albert 500 | 500 | 1491 | 12.947 | 0.05 | 0.10 | 6.474 | above |
| N3 Watts–Strogatz 200 | 200 | 600 | 6.167 | 0.30 | 0.25 | 7.401 | above |
| N4 SNAP email-Eu-core | 986 | 24925 | 76.266 | 0.10 | 0.20 | 38.133 | above |

All four: R0 match within rel_tol=1e-3, tier=Th_coqc, verdict correct.

**Status:** VERIFIED

**Kill condition:** any R0 error > 0.1% on networks with N ≤ 2000 (dense path),
or > 1% on sparse path (N > 500, eigsh).

## SIR well-mixed + HIT cards (v0.2.0 — ADDED 2026-06-30)

**Claim:** two new engine cards — SirWellMixedCard (R0 = β/γ) and HerdImmunityCard
(HIT = 1 − 1/R0) — fire correctly, declare their model assumptions, and are
disambiguated from SisThresholdCard in the conformance suite.

**Measured (tests/conformance, 5 new tests):**

- SIR fires on β+γ alone; SIS does NOT emit COMPUTED without λmax
- SIS R0 ≠ SIR R0 when both fire (λmax factor distinguishes them)
- Both declare model assumptions in render()
- HIT correct for R0=3 (HIT=0.667); refuses to compute when R0≤1 (validate() raises)
- 22/22 conformance tests pass

**Status:** PASSED (internal conformance gate)

## Network centrality card (K6 track 1 — SHIPPED)

**Claim:** a fourth engine card, `NetworkCentralityCard` (`providers/cards/network_centrality.py`),
fires on centrality/PageRank-shaped queries, reuses the same R2 spectrum readout (dominant
eigenvalue λmax) `sis_threshold` already grounds, and is correctly disambiguated from
`sis_threshold`/`sir_wellmixed` in the conformance suite. `coq_checked=True`, but
`independent_oracle=False` — the value is READ from the query (I7), not independently re-derived,
so it does not move K4 off CONDITIONAL. See the project's internal benchmark design notes (track 1)
for the full design/shipped-deviation notes.

**Measured:** 4 new conformance tests (fires on keyword+slot, silent without keyword,
disambiguates from SIS when both fire, clarifies on missing slot); conformance suite 22→26, full
repo suite 64→64 passing (no regression).

**Status:** SHIPPED (internal conformance gate; not oracle-certified — see K4)

## RAG entailment (K6 track 2a — MEASURED + recalibrated, CONDITIONAL)

**Claim (was a PROVE-IT item above):** `support_check`'s NLI stage was lexical-overlap-only
(a stub). It is now backed by a real cross-encoder NLI model
(`cross-encoder/nli-distilroberta-base`, CPU) — lexical overlap stays the necessary prefilter,
NLI entailment probability (`NLI_MIN`) is the sufficient decision.

**Round 1 — naive hard-coded default (`NLI_MIN=0.7`, a textbook literature value, never
fitted):** on `eval/rag_entailment_recall.py` (30 hand-written real-text premise/claim pairs,
15 supported paraphrases + 15 unsupported-but-plausible claims, NOT synthetic keyword swaps):
recall of False = 1.000 (15/15), but **FP rate = 0.800 (12/15)** — the gate wrongly rejected
80% of TRUE paraphrased claims. One case debugged directly: lexical overlap passes (0.25 ≥
0.15) but entailment probability lands at 0.646 — a real, legitimate paraphrase, still below
the 0.7 bar. This distilled NLI model scores natural paraphrase (reasonable inference, not
strict logical entailment) much lower than a textbook default assumes.

**Round 2 — calibrated (`NLI_MIN=0.05`):** threshold picked via
`eval/rag_entailment_calibration.py` on a **DISJOINT** set of 20 premise/claim pairs (10
supported / 10 unsupported, different topics/phrasing from the round-1 test set) — swept
thresholds for best balanced accuracy = (recall_of_True + recall_of_False)/2, found 0.85 at
`NLI_MIN=0.05`. **Re-measured on the original round-1 30-pair set** (genuinely held-out —
never used for calibration): **recall of False = 1.000 (15/15) unchanged**, **FP rate = 0.333
(5/15)**, down from 0.800.

**Status:** CONDITIONAL — a real, measured, and now materially-improved gate (FP_rate
0.800 → 0.333 on a held-out set, recall_of_False holds at 1.000), but FP_rate=0.333 is still
too high to call this production-ready: 1 in 3 true paraphrased claims still gets wrongly
suppressed. This is honest progress, not a PASS.

**Kill condition / next PROVE-IT:** do NOT retune `NLI_MIN` again against either the round-1
or round-2 set — both are now spent (one calibration set, one test set). The next round needs
a THIRD, still-unseen set, larger than 20-30 pairs, before any accuracy number here can be
cited as more than directional. If FP_rate cannot be pushed below ~0.10 on a genuinely
held-out set, this cross-encoder is the wrong model class for this gate and a larger/better
NLI checkpoint (or a different decision rule than a single probability threshold) is required
before RAG grounding is treated as production-ready.

## K6 — bare backend vs backend+execution-oracle repair, on real HumanEval (RUN, small real lift)

**Claim:** a small (1B-class) code model, given one repair turn backed by real test execution
(not an LLM judge), solves more HumanEval problems than the same model with no repair.

**Scope declaration (I7 exception):** `providers/oracle/execution_oracle.py` runs generated
code against a real test and reads pass/fail as ground truth — execution, not the LLM,
asserts the fact. This is a declared exception to I7, bounded to exactly HumanEval/MBPP's own
grain (one function, one test file). See `NON_CLAIMS.md` for the explicit, permanent boundary
against ever widening this to repo-level/multi-file/agentic coding (the SWE-bench class).

**Mechanism (verified before any model was involved):** `tests/test_execution_oracle.py`,
6/6 passing — correct code passes, buggy code fails with a real traceback, a runaway
`while True` is killed by the timeout (2s), a syntax-error candidate degrades to a failed
verdict instead of crashing the harness, and the completion-style repair prompt (below)
itself stays valid, compilable Python. The benchmark harness (`eval/k6_humaneval_bench.py`)
fetches the REAL official OpenAI HumanEval set (`openai/human-eval`, MIT-licensed) — not a
hand-reproduced subset — and was verified by running the official CANONICAL solutions for
HumanEval/0–2 through it: all 3 PASS. The harness deliberately does NOT reuse
`backends.registry.build_backend`/`LlamaCppBackend.transport()` (hard-locked to I7
transport-only JSON extraction, cannot do free-form code generation) — it loads `.gguf`
weights directly via `llama_cpp.Llama`.

**Model:** `typhoon-ai/llama3.2-typhoon2-1b` (base, not instruct-tuned), Q4_K_M GGUF
quantization (`mradermacher/llama3.2-typhoon2-1b-GGUF`), run on CPU.

**Round 1 (discarded — sampling bug, caught before being recorded as a claim):** the first
run sampled Arm A's and Arm B's *first* completion independently (default `temperature=0.8`),
so Arm B wasn't "Arm A + repair" but a second, unrelated random draw with a bonus turn —
e.g. HumanEval/7 and /13 showed bare=PASS, +repair=fail, only possible if the two arms saw
different first attempts. Fixed: `complete()` now uses `temperature=0.0` (greedy,
deterministic) and both arms share the exact same first completion (`run_both_arms`) — Arm B
only diverges from Arm A when the shared first attempt fails and a repair turn runs.

**Round 2 (discarded — repair-prompt-format bug, caught before being recorded as a claim):**
with the sampling bug fixed, both arms scored 3/20 = 0.150 (zero net change). Before
accepting that as "repair doesn't help," inspected the actual repair completions directly:
every single one of the 17 repair attempts failed with the identical `IndentationError:
unexpected indent` — a mechanical tell that something was structurally broken, not that the
model tried and failed 17 times differently. Root cause: `repair_prompt` (original version)
was an INSTRUCTION-style prompt ("Task: ... Write a corrected solution. Return only the
corrected function.") fed to a BASE (non-instruct) model, which has no chat/instruct training
to follow that framing — it just continued the text as prose (verified directly: the model's
"repair" was literally the sentence "The test case should pass with the corrected solution."
repeated verbatim). Naively splicing that prose after the original prompt produced invalid,
mis-indented code every time. Fixed: `repair_prompt_completion_style` keeps the model in its
native code-completion mode — it returns `problem_prompt` + one valid Python comment line
naming the failure, and the model continues writing code from there (same convention as the
original prompt), never an instruction.

**Round 3 (the real result), n=20 HumanEval problems, fixed before running, same set + same
shared first completion both arms, single run:**

| Arm | pass@1 |
|---|---|
| A — bare (no repair) | 3/20 = 0.150 |
| B — bare + one oracle-verified repair turn (completion-style prompt) | 4/20 = 0.200 |

HumanEval/8 flipped fail→PASS under repair; no other problem changed (no regressions, since
Arm B's first attempt equals Arm A's by construction). That is 1 of the 17 first-attempt
failures rescued (≈5.9% of the failing set), a real, small, honestly-measured lift — not the
fabricated lift round 1's bug would have shown, and not the false null result round 2's bug
would have shown.

**Round 4 — same n=20 set, `typhoon2-1b-instruct` (instruct-tuned, `--chat` mode):
`ChatCompletionModel` (chat turns via `create_chat_completion`, code extracted from markdown
fences, import header reattached since an instruct model rewrites the whole function fresh
rather than continuing the stub) + instruction-style `repair_prompt` (appropriate here — the
model can actually follow "here is what failed, write a corrected version"):**

| Arm | pass@1 |
|---|---|
| A — bare (no repair) | 6/20 = 0.300 |
| B — bare + one oracle-verified repair turn (instruction-style prompt) | 6/20 = 0.300 |

Base rate roughly doubled vs the base model (0.150 → 0.300), as expected for instruct-tuning.
But repair again gave **zero net lift** — this time verified NOT to be a mechanical bug:
inspected the first 6 failing problems directly, the model produced genuinely DIFFERENT code
on every repair attempt (not a repeat, not a parse error), just still incorrect. A real,
honest null result for repair on this model too, for a different reason than round 3's base
model (there, the repair prompt was reasoned about correctly but the model's writing capacity
was the bottleneck for the rescued case; here, the model changes its answer but the 1B
instruct model's coding capacity itself is the bottleneck across all 14 remaining failures).

**Status:** RUN. Two real, honestly-measured configurations now recorded, same n=20 set:

| Model | bare pass@1 | +repair pass@1 | repair lift |
|---|---|---|---|
| typhoon2-1b (base) | 3/20 = 0.150 | 4/20 = 0.200 | +1 problem |
| typhoon2-1b-instruct | 6/20 = 0.300 | 6/20 = 0.300 | 0 |

Neither is a general verdict on oracle-repair framing — both are single, narrow
configurations (n=20, one repair turn, one prompt style each) on one small model family. The
mechanism (generate → execute → feed real failure back → regenerate → re-execute) is now
demonstrated honestly end-to-end on two different model/prompt-style pairings, with two real
methodology bugs (round 1 sampling, round 2/base-model prompt-format) caught and fixed before
either was recorded, and the instruct-model null result verified directly (not assumed) to be
a genuine capability ceiling rather than a repeat of round 2's mechanical bug.

**Kill condition:** do not report a different K6 number without (a) a fixed `n` chosen BEFORE
running, (b) both arms run on the identical problem set with the identical first
completion/solution in the same run, (c) recording exactly which model + prompt style was
used — a different checkpoint, repair prompt, number of repair turns, or larger `n` is a new,
not-yet-run condition, not a re-measurement of either of the two above. n=20 is too small to
generalize a percentage from either row; treat both as directional evidence only.
