# pgcross — Verified-Reasoning, Evidence-Gated Decision Server

> Licensed under Apache License 2.0 (see `LICENSE`). Public repository.

## What it is

One server that speaks the model API (`POST /v1/chat/completions`). NOT a model checkpoint.
The engine, verifier, and tier/provenance discipline live OUTSIDE the LLM weights.
You call it like a model; inside, a pipeline turns the query into tier-labelled candidates
of knowledge (never "knowledge"), each with auditable provenance. The system abstains
rather than fabricating outside coverage.

## Pipeline

```
route → ground → engine → verify → assemble → emit
```

Every response carries:
- `choices[0].message.content` — tier-labelled answer in plain words
- `choices[0].message.pgcross` — machine-readable `{candidates, stakes}`

## Tier ladder (I1: weakest link wins)

```
Th_coqc          machine-verified structure (Coq-checked)
finite_diagnostic independently cross-checked value
Dr               source-attributed / single-path computation
Wf               working-framework consistency
Open             ungrounded lens or guess — never a verdict
```

The floor over all links is the emitted tier. A strong computation does not rescue
weak routing or ungrounded parameters.

## Invariants

The conformance suite (46 tests) enforces all invariants. A change that breaks any one
is wrong regardless of what else it improves.

- **I1** tier = floor over links (never max or avg)
- **I2** no grounded-looking number on ungrounded inputs
- **I3** unsupported RAG claim suppressed, not shown
- **I4** response never empty (CONSULTATION floor)
- **I5** HIGH stakes: weak assertive candidates dropped; lens + consultation remain
- **I6** raw LLM unreachable (only via pipeline)
- **I7** LLM transports only (structures/extracts — never asserts a fact)
- **I8** harmful requests fail CLOSED before any candidate enters the pipeline

## Quickstart

Nothing to download from anywhere else first — clone, install, run. `pgcross serve` starts on
the deterministic pipeline alone by default (no model weights needed at all for the engine
cards / RAG / grounding path):

```bash
git clone https://github.com/morrocwi/pgcross.git
cd pgcross
pip install -e .[dev]
pgcross init
pgcross serve --unsafe-dev   # dev only: wires keyword safety stub
```

```bash
curl localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"pgcross-1","messages":[{"role":"user","content":"epidemic beta=0.3 gamma=0.1 lambda_max=3?"}]}'
```

### Optional: a model behind the witness-before-model gate

Add `--decision-backend openthai-local` to route the small residual of queries the
deterministic gate can't resolve to [OpenThai-SystemOne](https://huggingface.co/iapp/OpenThai-SystemOne)
(Apache-2.0), run in-process:

```bash
pip install -e .[openthai]                     # one extra, no separate download step
pgcross serve --unsafe-dev --decision-backend openthai-local
```

The model weights (~0.8B params, BF16) download automatically from the Hugging Face Hub on
first use (standard `huggingface_hub` caching — a one-time transparent download the first time
the backend is actually reached, not a manual step you do beforehand). See `REPO_ROLE.md` for
what this backend can and cannot do: it only ever *proposes* — see the Invariants above.

**`examples/decision_backend_demo.py`** runs the same chain directly (no server) — a captured
real run (2026-09-21, real weights, not a mock):

```
$ python examples/decision_backend_demo.py
[demo] query: 'epidemic beta=0.3 gamma=0.1 lambda_max=3?'
[demo] authorization status: ADMIT
[demo] authorization reason: DecisionBackend 'openthai-systemone-local' proposed 'yes' for
'primary_candidate_admissible' with probability=0.797 (>= 0.7); PGCross admits the proposal
after witness-before-model found no deterministic resolution -- the model proposed, PGCross
authorized
```

### Optional: a real trained safety classifier

`--safety classifier` layers [`unitary/toxic-bert`](https://huggingface.co/unitary/toxic-bert)
(Apache-2.0, a real trained model) on top of the keyword stub via OR — either flagging is enough
to refuse:

```bash
pip install -e .[safety]
pgcross serve --unsafe-dev --safety classifier
```

Neither `keyword` nor `classifier` is proven safe for production without red-teaming — see
"Known limits" below.

### pgcross as a Jev/TypeSafe-compatible System One *provider*

`decision/backend.py`'s `SystemOneHTTPBackend` is the client side — pgcross calling OUT to a
TypeSafe/System-One-compatible server. `POST /v1/systemone` (served by every `pgcross serve`,
no extra flag) is the other direction: pgcross itself answering typed `noul`/`score`/`choice`
questions for any Jev/TypeSafe-compatible caller, backed by pgcross's own full deterministic-
first pipeline (engine cards, RAG, the witness-before-model gate), not a separate, weaker code
path. Verified full-circle: pgcross's own `SystemOneHTTPBackend` client pointed at pgcross's own
`/v1/systemone` endpoint, round-tripped for real.

```bash
curl localhost:8000/v1/systemone \
  -H "Content-Type: application/json" \
  -d '{"state":{"query":"10*10"},"questions":{"admissible":{"type":"noul","instructions":"Is 100 correct for 10*10?"}}}'
```

Answer probabilities here are a **declared tier-floor mapping** (I1's tier ladder above, e.g.
`Th_coqc`/`finite_diagnostic` → 1.0, `Wf` → 0.65), not a measured model confidence — see
`server/systemone.py`'s module docstring for the exact, explicit mapping. This is pgcross
*speaking the wire contract*, not pgcross *being* Jev/TypeSafe — no affiliation is claimed.

## Configuration

See `configs/default.yaml`.

```bash
pgcross backend add --kind llamacpp --weights <path>
pgcross rag add <path> --corpus <id> --authority peer_reviewed
pgcross check --conformance    # verify I1-I8 against your loaded config
```

## Proven (measured, committed tests)

- **Engine causality K1:** placebo n=51, CI [+1.000, +1.000], p=0.0000 — PASSED
- **Grounding recall:** 1.000 (15/15 detected); FP=0.000 (24/24 clean paraphrases) — PASSED
  (`eval/grounding_robustness_test.py`; see CLAIMS.md)
- **Conformance:** 46-test suite green (`pytest tests/conformance -q`, re-verified 2026-09-21;
  I1-I8 fully exercised, including differential tiering over the full enum product with zero
  disagreements)
- **Decision Forge benchmark: 12/12 (100%)** — `eval/decision_forge_benchmark.py`, a small (12
  case), hand-labeled benchmark of the whole wired system (deterministic pipeline + real
  OpenThai-SystemOne backend), not the bare model. **Not comparable** to a general-purpose NLU
  benchmark — same honesty discipline as the LOOCV note above. Covers: deterministic queries
  correctly bypass the model entirely (2/2), harm-net safety override wins regardless of what the
  model would say (2/2), real model-assisted judgment in English (4/4) and Thai (4/4).
- **External public-dataset check: 82/100 (82.0%)** — `eval/xnli_th_external_benchmark.py`
  (`pip install pgcross[openthai,eval]`), a genuine third-party dataset
  (`facebook/xnli`, Thai config, `validation` split, 2490 examples), NOT authored by this
  project, sampled 100 with a fixed seed (reproducible reruns) and scored for real.
  **Not comparable** to OpenThai-SystemOne's own published XNLI-th number (76.5%) — different
  system (the whole Forge, not the bare model), different sample size, different harness; see
  the script's own docstring before citing this number anywhere else.
- **Same public benchmark suite, 3 of 13 subsets** — `eval/jev_public_benchmark_suite.py`.
  OpenThai-SystemOne's own model card cites a 13-dataset public benchmark (Bespoke Nimble's own
  `docs/PUBLIC_BENCHMARKS.md` methodology): `aegis2`, `boolq`, `civil_comments`, `helpsteer2`,
  `massive-de-DE`, `massive-en-US`, `multinli`, `paws`, `pubmedqa`, `squad2`,
  `summeval-consistency`, `summeval-relevance`, `vitaminc-dev`. This covers 3 of those 13 (the
  ones directly loadable via `datasets` with unambiguous ground truth), 60 real examples each,
  fixed seed: **boolq 43/60 (71.7%), paws 37/60 (61.7%), multinli 55/60 (91.7%)** — combined
  135/180 (75.0%). **Not a reproduction of their published 61.9/74.8/76.0 aggregate numbers** —
  same dataset names, not a byte-identical harness, and only 3 of the 13 subsets; see the
  script's own docstring for exactly what is and isn't covered.

## Engine cards

Four engine cards ship today: `sis_threshold`, `sir_wellmixed`, `herd_immunity` (epidemiology,
closed-form), and `network_centrality` (network centralization/PageRank, read as the same R2
spectrum quantity — dominant eigenvalue λmax — that `sis_threshold` already uses for the epidemic
threshold). `network_centrality` reads its λmax value from the query rather than independently
computing it, so it carries the same Dr-capped, non-oracle posture as the other closed-form cards
below.

## Known limits

- V_answer oracle INACTIVE on closed-form cards (sis_threshold, finance, epidemiology,
  network_centrality): capped at Dr, not certified (see K4 in CLAIMS.md)
- Real-query routing: 0.785 — the 0.911 LOOCV figure is optimistic by 12.6pp; do not cite it as accuracy
- RAG `support_check` entailment gate: lexical-only as shipped (NLI gate STUBBED — measure recall on
  paraphrased unsupported claims before treating it as a real grounding gate)
- Safety: `keyword` (default) is a stub; `--safety classifier` adds a real trained model
  (`unitary/toxic-bert`) but neither has been red-teamed — required before any production use
- Single-turn only (v0.1 declared; multi-turn is out of scope)

## What is not yet done

- Red-teaming of either safety layer (PROVE-IT; startup guarantees a layer is present, not that
  it works — `--safety classifier` is a real trained model now, not a stub, but still unproven
  against adversarial inputs)
- NLI entailment in `support_check` (PROVE-IT; current lexical gate will pass paraphrases)
- Larger-model comparison K2/K3 (OPEN; not a release blocker)

## License

PGCross is licensed under the Apache License 2.0 — see `LICENSE`. It is assembled from
permissive OSS dependencies (MIT/BSD/Apache-2.0 — see `THIRD_PARTY_NOTICES.md` and
`licenses/AUDIT.md`). GPL/AGPL dependencies are banned; CI fails on them.

Both shipped safety layers (`keyword`, `classifier`) are unproven against adversarial inputs
(see "Known limits" above) — treat this as research/development-stage software, not a hardened
production service, until real red-teaming lands.

See `CLAIMS.md` for pre-registered claims with CIs.
