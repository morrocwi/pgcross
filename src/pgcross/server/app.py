"""server/app.py — FastAPI application factory.

SPEC §7: create_app builds the FastAPI app, calls assert_serving_ready (F1),
and mounts the /v1/chat/completions and /v1/models and /healthz endpoints.
"""
from __future__ import annotations
from fastapi import FastAPI
from ..pipeline.run import assert_serving_ready


def create_app(ctx, allow_unsafe_dev: bool = False) -> "FastAPI":
    """Build and return the FastAPI application.

    Calls assert_serving_ready before binding — F1 fail-closed.
    """
    assert_serving_ready(ctx, allow_unsafe_dev=allow_unsafe_dev)

    app = FastAPI(title="pgcross", version="0.1.0")

    # Lazy import to avoid circular deps
    try:
        from .chat import router as chat_router
        app.include_router(chat_router)
    except ImportError:
        pass  # chat.py not yet implemented; stub endpoint below

    try:
        from .responses_api import router as responses_router
        app.include_router(responses_router)
    except ImportError:
        pass  # OpenAI Responses API compatibility (Codex CLI etc.) — see responses_api.py

    try:
        from .decision import router as decision_router
        app.include_router(decision_router)
    except ImportError:
        pass  # Decision Forge structured endpoint — see decision.py

    try:
        from .systemone import router as systemone_router
        app.include_router(systemone_router)
    except ImportError:
        pass  # TypeSafe/Jev-compatible System One provider endpoint — see systemone.py

    @app.get("/healthz")
    async def healthz():
        backend_ok = ctx.backend is not None
        providers = [p.id for p in ctx.registry.all()]
        return {
            "status": "ok",
            "backend": "loaded" if backend_ok else "missing",
            "providers": providers,
            "safety": ctx.safety is not None,
        }

    @app.get("/v1/models")
    async def list_models():
        entry = {
            "id": "pgcross-1",
            "object": "model",
            "created": 0,
            "owned_by": "pgcross",
        }
        return {
            "object": "list",
            "data": [entry],
            # Codex CLI's model-metadata refresh (codex_models_manager) requires a top-level
            # "models" key (confirmed directly: without it, it logs "missing field `models`"
            # and falls back to generic metadata — non-fatal, but noisy). Kept alongside the
            # standard OpenAI "object"/"data" shape so classic Chat Completions clients are
            # unaffected.
            "models": [entry],
        }

    # NOTE: no inline /v1/chat/completions handler here. `chat_router` (mounted above) already
    # registers that route and, per FastAPI's first-registered-wins routing, always won over an
    # inline duplicate that used to be defined here — confirmed dead code
    # (per the project's internal architecture audit notes, contradiction #7). Removed 2026-09-21
    # (Phase 4) rather
    # than left to accumulate alongside this run's new `/v1/decision` router addition; `chat.py`'s
    # router is the sole implementation now. See `tests/test_decision_endpoint.py` for the
    # regression check confirming `POST /v1/chat/completions` still works identically.

    # Store ctx on the app for downstream access
    app.state.ctx = ctx
    return app
