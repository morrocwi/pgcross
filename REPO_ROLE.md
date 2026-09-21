# REPO_ROLE — pgcross

**Product direction:** Decision Forge / verified-reasoning server — a model-agnostic
`Readout → Route → Propose → Verify → Authorize → Act` pipeline.

**Upstream/downstream (current):** pgcross is a standalone repo. It **routes to**, rather than
imports/forks, external capability providers when they exist as separate systems:
- a `ComputationBackend` (exact/certified computation; see `src/pgcross/decision/computation_backend.py`)
- a `DecisionBackend` (typed decisions with probabilities; see `src/pgcross/decision/backend.py`) —
  implementations include `OpenThaiSystemOneLocalBackend` (in-process, via the `openthai_systemone`
  package, `pip install pgcross[openthai]`) and `SystemOneHTTPBackend` (HTTP client for a
  TypeSafe-compatible `POST /v1/systemone` server). Neither is wired into `serve`/CLI by default —
  opt in with `pgcross serve --decision-backend {openthai-local,openthai-http}`.

The live product surface today: the `pgcross` CLI/server (`src/pgcross/cli.py`, `server/app.py`)
running the pipeline in `src/pgcross/pipeline/*.py` over the currently-live evidence providers
(`providers/cards/`, `providers/rag/`, `providers/atlas/`, `providers/live/`,
`providers/oracle/`) and the `LLMBackend` protocol (`backends/{base,llamacpp,openai}.py`).

## What this repo IS
- The pgcross pipeline, providers, backends, server, and CLI — the actual code path exercised by
  `tests/conformance/test_conformance.py` and the installed `pgcross` command.
- The place where evidence providers (engine cards, RAG, atlas constants, live data, execution
  oracle) are composed, tiered, and authorized under an explicit ADMIT/HOLD/REJECT/ESCALATE
  vocabulary (`src/pgcross/decision/schema.py`'s `AuthorizationStatus`,
  `src/pgcross/authorization/policy.py`). A model may propose (via a `DecisionBackend`), never
  authorize its own decision — `authorization/policy.py::authorize_decision_proposal` restricts a
  model proposal to ADMIT/HOLD only; REJECT/ESCALATE stay exclusively the deterministic
  harm-net path's territory.

## What this repo is NOT
- Not a decision model or model provider — `DecisionBackend`/`ComputationBackend` implementations
  route to external systems; pgcross does not train, fine-tune, or vendor model weights.

## Release gate
See `RELEASE_GATE.md`.
