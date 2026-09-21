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
- Safety: keyword stub only — a real classifier and red-team are required before any external use
- Single-turn only (v0.1 declared; multi-turn is out of scope)

## What is not yet done

- Real safety classifier (PROVE-IT; startup guarantees a layer is present, not that it works)
- NLI entailment in `support_check` (PROVE-IT; current lexical gate will pass paraphrases)
- Larger-model comparison K2/K3 (OPEN; not a release blocker)

## License

PGCross is licensed under the Apache License 2.0 — see `LICENSE`. It is assembled from
permissive OSS dependencies (MIT/BSD/Apache-2.0 — see `THIRD_PARTY_NOTICES.md` and
`licenses/AUDIT.md`). GPL/AGPL dependencies are banned; CI fails on them.

The safety layer shipped here is a keyword stub, not a production classifier (see "Known limits"
above) — treat this as research/development-stage software, not a hardened production service,
until a real safety classifier lands.

See `CLAIMS.md` for pre-registered claims with CIs.
