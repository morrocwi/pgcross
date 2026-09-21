# PRODUCTION_CHECKLIST — pgcross

**Run before every production release. All items required.** Honesty floor (unchanged from the
prior checklist): a box is checked ONLY when a committed artifact backs it — not a design intent,
not a "should work," not a partial implementation.

## Pre-flight
- [ ] `RELEASE_GATE.md`'s `GATE_RELEASE_PGCROSS` passed — **OPEN** (internal sign-off pending).
- [ ] `UPSTREAM_RELEASES.yaml` / `pyproject.toml` dependencies reconciled — no unpinned branches.
- [ ] `ROLLBACK.md`: rollback procedure documented and tested (not just written).
- [ ] `DEPLOYMENT.md`: deploy steps current and match the real `pyproject.toml` extras
      (`[llamacpp]`, `[vllm]`, `[rag]`, `[dev]`) and `pgcross serve` CLI behavior.
- [ ] No ARAYA/salamxp-specific content anywhere in the public-core candidate file set (re-confirm
      against the current file set — do not assume the prior leak-scan finding still holds).

## Server surface (real endpoints, as of this checklist's retarget)
- [ ] `GET /healthz` — reports backend-loaded status, registered provider ids, safety-loaded
      status (`server/app.py`).
- [ ] `GET /v1/models` — lists the served model id.
- [ ] `POST /v1/chat/completions` — OpenAI-compatible, wired once (`server/chat.py`'s router);
      confirm no duplicate/dead inline registration exists in `server/app.py`.
- [ ] `POST /v1/responses` — OpenAI Responses-API compatibility (`server/responses_api.py`).
- [ ] `POST /v1/decision` — the Decision Forge structured endpoint (`server/decision.py`), thin
      adapter over `run_pipeline()`, own request/response schema. Confirm it is actually mounted
      (`server/app.py`'s `try: from .decision import router` block) and does not silently
      no-op on `ImportError`.
- [ ] `assert_serving_ready()` (F1 fail-closed) confirmed called before `create_app()` binds —
      server refuses to serve when `ctx.safety is None` unless `--unsafe-dev` is explicit.

## Backends
- [ ] `LLMBackend` protocol implementations: `LlamaCppBackend` (GGUF, opt-in `[llamacpp]` extra)
      and `OpenAIBackend` (OpenAI-compatible HTTP) both wired in `backends/registry.py` — confirm
      the `kind="openai"` wiring bug (registry rejecting a kind `backends/openai.py` already
      implements) is fixed, not merely documented as known.
- [x] `DecisionBackend` protocol (`src/pgcross/decision/backend.py`): `MockBackend`,
      `DeterministicBackend`, `OpenThaiSystemOneLocalBackend`, and `SystemOneHTTPBackend` are all
      implemented and tested (2026-09-21). What's checked into this repo and independently
      re-runnable by anyone: `OpenThaiSystemOneLocalBackend` exercised end-to-end against real
      downloaded weights and a 100-example external public-dataset check (`eval/
      decision_forge_benchmark.py`, `eval/xnli_th_external_benchmark.py`); `SystemOneHTTPBackend`
      round-tripped against `server/systemone.py` via FastAPI's in-process `TestClient`
      (`tests/test_systemone_endpoint.py::test_full_circle_via_real_systemone_http_backend_client`)
      — a full-circle proof of the wire contract, but NOT a real network socket (see that
      backend's own module docstring, which says exactly this and does not overclaim it). A
      separate real-socket round trip (a real `pgcross serve` process, a real port, no
      TestClient) was also run once by hand during development; that manual step is not itself a
      reproducible artifact in this repo, so it is not cited as checkable evidence here. **This
      entry previously said `SystemOneHTTPBackend` "is NOT implemented" — that was stale; a
      stranger cross-checking README/REPO_ROLE.md against this file would have found a real
      contradiction. Caught by an external review; both the original claim and this fix's own
      wording were independently verified against the actual code/tests before being written
      (the first draft of this fix over-cited a real socket round trip as checked-in evidence —
      an independent review caught that too, and it was corrected to the above).**
- [ ] `ComputationBackend` protocol (IDM/`research_universal_solver` routing) — design-only as of
      this checklist; not yet implemented. Same rule: do not claim it works before it does.

## Testing
- [ ] `pytest tests/conformance -q` passes (46 `test_*` functions currently defined — verify the
      count and pass status at release time, do not cite this number as evergreen).
- [ ] `pytest tests/ -q` (full suite, including property-based/Hypothesis tests per
      `CHANGELOG.md`) passes.
- [ ] F1-fail-closed / A-series tiering-and-stakes invariants (`tests/conformance/test_conformance.py`)
      all pass — this is the closest existing analog to the letter's F1–F15 authorization-runtime
      invariants; as new Verify/Authorize-stage tests land (a planned near-term phase per the
      project's internal engineering roadmap), list them here individually rather than as one
      aggregate claim.
- [ ] Leak-scan pass run (per `PUB-ADVERSARIAL-REVIEW`/`glosa-publish-gate`) before any
      public-facing step — see `RELEASE_GATE.md`.

## Security
- [ ] No credentials in code or config (backends read API keys/URLs from config/env, not
      hardcoded).
- [ ] `pgcross serve` binds `127.0.0.1` by default; any LAN/public exposure requires an explicit
      firewall rule and a rate limiter first — neither exists yet, do not check this box for a
      public-exposed deployment.
- [ ] `safety.py` status disclosed honestly: it is a keyword-only dev-stub (confirmed staying that
      way per the project's internal engineering decision log) — `SECURITY_AND_PRIVACY.md`
      (a later phase) must state this gap, not imply it is closed.

## Sign-off
- [ ] Internal approval (required) — NOT given.
- [ ] Record in `RELEASE_MANIFEST.yaml` — currently `releases: []`.
