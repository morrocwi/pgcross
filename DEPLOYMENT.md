# DEPLOYMENT — pgcross

**Status:** NOT RELEASED. Version is `0.2.0` (per `pyproject.toml`); `RELEASE_MANIFEST.yaml
gate_passed` stays `false` until `RELEASE_GATE.md`'s gate is authorised internally. This document
describes the *installable* current pipeline server — it does not authorise a release, and it does
not claim any air-gap property the current build cannot actually back.

This supersedes the earlier offline-bundle deployment story (self-installable wheel with a
vendored corpus + optional local Qwen-0.5B composer) — that direction was the "PGcross Mini"
universal-bundle product, now retired; see the project's internal historical record. The
current deliverable is a **pip-installable server + CLI** (`pgcross`) that composes
model-agnostic evidence providers behind a `run_pipeline()` call, with an LLM backend you point it
at — not a bundle that vendors a corpus or a model inside the wheel.

---

## Install (real, from `pyproject.toml`)

Base install (`fastapi`, `uvicorn`, `pydantic`, `typer`, `numpy`, `pyyaml`, `httpx` — no LLM
backend, no RAG):
```bash
pip install pgcross
```

Optional extras (`[project.optional-dependencies]` in `pyproject.toml`):

| Extra | Adds | Use case |
|-------|------|----------|
| `pgcross[llamacpp]` | `llama-cpp-python>=0.2.70` | local GGUF-weight inference via `LlamaCppBackend` |
| `pgcross[vllm]` | `vllm>=0.4` | vLLM-served backend (`registry.py` wiring for this kind — confirm current status before relying on it) |
| `pgcross[rag]` | `sentence-transformers>=2.7`, `pypdf>=4` | RAG corpus ingestion/retrieval (`providers/rag/`) |
| `pgcross[dev]` | `pytest>=8`, `pip-licenses>=4` | running the test suite / license audit locally |

No extra vendors a corpus or model weights inside the wheel — that was the retired bundle
product's design, not the current one. Weights/corpora are supplied by whoever deploys pgcross,
via config.

## Configure

```bash
pgcross init                        # writes a starter configs/default.yaml
pgcross backend add --kind llamacpp --weights /path/to/model.gguf
pgcross rag add /path/to/docs --corpus my-corpus --authority curated
```
`configs/default.yaml` declares the backend, the evidence providers to register, `lens_sources`,
and server `host`/`port`. `pgcross serve` reads it; CLI flags override config; config overrides
built-in defaults.

## Run the server

```bash
pgcross serve --config configs/default.yaml --port 8000 --host 127.0.0.1
```
`serve` calls `assert_serving_ready()` (F1 fail-closed) before binding — it refuses to serve when
`ctx.safety is None` unless `--unsafe-dev` is passed explicitly (dev-only escape hatch, never for
a real deployment). Endpoints exposed: `GET /healthz`, `GET /v1/models`,
`POST /v1/chat/completions` (OpenAI-compatible), `POST /v1/responses` (OpenAI Responses-API
compatible), and `POST /v1/decision` (the Decision Forge structured endpoint, if mounted — see
`PRODUCTION_CHECKLIST.md`).

By default `general_chat` fallback is ON for `serve` (plain-assistant fallback only when no
structured evidence provider fires and stakes are LOW; never overrides a real refusal or a real
structured answer) — pass `--no-general-chat` to keep pgcross strictly structured-domain-only.

## Backend/network posture (honest, not assumed)

pgcross itself makes no network calls beyond whatever backend it is configured to call:
- `LlamaCppBackend`: local inference, no network at request time, once the GGUF weights are on
  disk (you supply them — pgcross does not fetch or vendor them).
- `OpenAIBackend`: calls an OpenAI-compatible HTTP endpoint you configure (API key from
  config/env, never hardcoded) — network required at request time.
- A `DecisionBackend`/`ComputationBackend` integration (OpenThai-SystemOne, IDM,
  `research_universal_solver`) is **not implemented yet** (`SystemOneHTTPBackend` raises
  `NotImplementedError` by design) — do not describe a deployment as having working access to any
  of these until the integration actually lands.

Do **not** claim an air-gapped deployment unless every configured backend genuinely requires no
network at request time — this document does not assert that property as a default; it depends on
which backend you configure.

## Verify an install

```bash
pgcross check --conformance   # runs tests/conformance (pytest) — confirms the invariant suite
                               # passes against the installed package
```

## Release discipline
- Version and `gate_passed` stay as `RELEASE_GATE.md`/`RELEASE_MANIFEST.yaml` record them until
  internal authorization approves a release. No automated step bumps the version, cuts a tag,
  or sets `gate_passed:true`.
- pgcross routes to external backends/capability systems; it does not fork or vendor their code
  (`backends/base.py`'s `LLMBackend` Protocol is the seam).
