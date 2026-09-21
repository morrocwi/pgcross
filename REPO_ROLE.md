# REPO_ROLE — pgcross

**Product direction:** Decision Forge / verified-reasoning server — a model-agnostic
`Readout → Route → Propose → Verify → Authorize → Act` pipeline (per the project's internal
architecture design records). This supersedes the earlier "PGcross Mini" universal-offline-bundle
direction (Typhoon-1b/GGUF composer + bundled corpus, `DEC-n14-pgcross-universal-scope-2026-0630`)
— that N14/N21 DAG-node framing is retired; the superseded plan is kept in the project's internal
historical record per this workspace's append-only discipline.

**Upstream/downstream (current):** pgcross is a standalone repo. It **routes to**, rather than
imports/forks, external capability providers when they exist as separate systems — e.g. a future
`ComputationBackend` (`information-discrete-math`'s `idm.solve()`, `research_universal_solver`'s
MCP tools — both design-only as of this writing) and a future `DecisionBackend`
(OpenThai-SystemOne — confirmed target, integration not yet implemented; see
`src/pgcross/decision/backend.py`'s `SystemOneHTTPBackend`, which currently raises
`NotImplementedError` by design, not by omission). Do not describe either integration as working
until it actually is.

The live product surface today: the `pgcross` CLI/server (`src/pgcross/cli.py`, `server/app.py`)
running the pipeline in `src/pgcross/pipeline/*.py` over the currently-live evidence providers
(`providers/cards/`, `providers/rag/`, `providers/atlas/`, `providers/live/`,
`providers/oracle/`) and the `LLMBackend` protocol (`backends/{base,llamacpp,openai}.py`).

## What this repo IS
- The pgcross pipeline, providers, backends, server, and CLI — the actual code path exercised by
  `tests/conformance/test_conformance.py` and the installed `pgcross` command.
- The place where evidence providers (engine cards, RAG, atlas constants, live data, execution
  oracle) are composed, tiered, and — once the Verify/Authorize split lands (a planned near-term
  phase per the project's internal engineering roadmap) — authorized under an explicit
  ADMIT/HOLD/REJECT/ESCALATE vocabulary (`src/pgcross/decision/schema.py`'s `AuthorizationStatus`).
- Architecture/design records for how this pipeline should evolve (kept as internal engineering
  design docs, not part of the public release).

## What this repo is NOT
- Not a decision model or model provider — `DecisionBackend`/`ComputationBackend` implementations
  route to external systems; pgcross does not train, fine-tune, or vendor model weights.
- Not any ARAYA/salamxp organization-specific content — no ARAYA/salamxp product-specific content
  in the public-core candidate files, aside from the copyright-holder attribution in `LICENSE`
  itself (confirmed via the project's internal public/private content audit and this session's own
  leak-scan work). This boundary is unchanged from the earlier N14 framing and stays load-bearing:
  nothing ARAYA/salamxp-specific belongs in this product, regardless of which architecture
  generation the repo is in.
- Not `main.hub` (the public routing graph) — pgcross is currently absent from it by design
  (private status); a future consumer-only `hub/` module (planned per the project's internal
  roadmap) reads `main.hub`, it does not register pgcross into it. Registering pgcross itself as
  a hub node is separate, later work gated on an internal engineering decision.
- Not yet public — the repository visibility itself is still private. The license was switched to
  `Apache-2.0` (see `LICENSE`) on 2026-09-21 with explicit internal authorization (per the
  project's internal engineering decision log), now that Phase 7 (license/dependency audit) has
  completed — but a license change is not the same thing as actually publishing; the repo staying
  private and the license already being Apache-2.0 are two independent facts, do not conflate them.

## Release gate
See `RELEASE_GATE.md`. No `gate_passed: true` / release tag until the gate checklist is genuinely
met and it is authorized internally.
