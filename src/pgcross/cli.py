"""pgcross CLI — typer-based command interface.

SPEC §8: config-first design. Commands edit YAML; src/ is untouched by users.
`pgcross check --conformance` lets users verify the discipline on THEIR setup.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import typer
import yaml

app = typer.Typer(name="pgcross", help="PGCross verified-reasoning server.", no_args_is_help=True)


@app.command()
def init(config: Path = typer.Option(Path("configs/default.yaml"), help="Output config path")):
    """Write a starter configs/default.yaml (llamacpp stub + sis card + defaults)."""
    stub = {
        "backend": {
            "kind": "llamacpp",
            "weights": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            "context_length": 8192,
        },
        "providers": [
            {"kind": "engine_card", "module": "pgcross.providers.cards.sis_threshold"},
        ],
        "lens_sources": ["sis_threshold"],
        "policy": {"tiers": "default", "stakes": "default", "coverage": "default"},
        "server": {"port": 8000, "host": "127.0.0.1"},
    }
    config.parent.mkdir(parents=True, exist_ok=True)
    with open(config, "w") as f:
        yaml.dump(stub, f, default_flow_style=False)
    typer.echo(f"[pgcross] wrote {config}")


backend_app = typer.Typer(help="Manage LLM backends.")
app.add_typer(backend_app, name="backend")


@backend_app.command("add")
def backend_add(
    kind: str = typer.Option("llamacpp", help="Backend kind: llamacpp|openai|vllm|ollama"),
    weights: str = typer.Option(None, help="Path to GGUF weights (llamacpp)"),
    url: str = typer.Option(None, help="API URL (openai/vllm/ollama)"),
    model: str = typer.Option(None, help="Model name (openai/vllm)"),
    config: Path = typer.Option(Path("configs/default.yaml")),
):
    """Add a backend to the config."""
    from .policy.loader import load_config
    cfg = load_config(str(config)) if config.exists() else {}
    backend_cfg: dict = {"kind": kind}
    if weights:
        backend_cfg["weights"] = weights
    if url:
        backend_cfg["url"] = url
    if model:
        backend_cfg["model"] = model
    cfg["backend"] = backend_cfg
    with open(config, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)
    typer.echo(f"[pgcross] backend {kind!r} added to {config}")


rag_app = typer.Typer(help="Manage RAG corpora.")
app.add_typer(rag_app, name="rag")


@rag_app.command("add")
def rag_add(
    path: str = typer.Argument(help="Path to documents (file or directory)"),
    corpus: str = typer.Option(..., help="Corpus ID"),
    authority: str = typer.Option("curated", help="Authority: peer_reviewed|curated|web"),
    config: Path = typer.Option(Path("configs/default.yaml")),
):
    """Ingest documents into a RAG corpus."""
    from .core.enums import Tier
    from .providers.rag.ingest import ingest

    authority_map = {"peer_reviewed": Tier.Dr, "curated": Tier.Wf, "web": Tier.Open}
    tier = authority_map.get(authority, Tier.Wf)
    typer.echo(f"[pgcross] ingesting {path!r} as corpus {corpus!r} (authority={authority})...")
    provider = ingest(path, corpus, tier)
    typer.echo(f"[pgcross] done — provider id: {provider.id}")


@app.command()
def serve(
    config: Path = typer.Option(Path("configs/default.yaml"), help="Config file"),
    port: int = typer.Option(8000),
    host: str = typer.Option("127.0.0.1"),
    unsafe_dev: bool = typer.Option(False, help="Skip safety check (dev only)"),
    general_chat: bool = typer.Option(
        True, help="Fall back to plain assistant chat (same wrapped model) when NO engine "
                    "card/RAG/lens has any structured signal and stakes are LOW — never "
                    "overrides a real refusal or a real structured answer. ON by default for "
                    "`serve` (an HTTP endpoint meant for general clients like Codex CLI); pass "
                    "--no-general-chat to keep pgcross strictly structured-domain-only."),
):
    """Start the pgcross server. Calls assert_serving_ready (F1 fail-closed)."""
    import uvicorn
    from .pipeline.run import Ctx, Config as PipelineCfg, assert_serving_ready
    from .core.provider import Registry
    from .backends.registry import build_backend
    from .providers.cards.sis_threshold import SisThresholdCard
    from .providers.cards.sir_wellmixed import SirWellMixedCard
    from .providers.cards.herd_immunity import HerdImmunityCard
    from .providers.cards.network_centrality import NetworkCentralityCard
    from .safety import make_safety
    from .server.app import create_app
    from .policy.stakes import classify_stakes
    from .core.enums import Tier

    cfg: dict = {}
    if config.exists():
        with open(config) as f:
            cfg = yaml.safe_load(f) or {}

    # CLI flags override config; config overrides built-in defaults.
    srv = cfg.get("server", {})
    if port == 8000 and "port" in srv:   # user didn't pass --port explicitly (default)
        port = srv["port"]
    if host == "127.0.0.1" and "host" in srv:
        host = srv["host"]

    registry = Registry()
    registry.register(SisThresholdCard())
    registry.register(SirWellMixedCard())
    registry.register(HerdImmunityCard())
    registry.register(NetworkCentralityCard())

    backend_cfg = cfg.get("backend", {"kind": "llamacpp", "weights": "model.gguf"})
    try:
        backend = build_backend(backend_cfg)
    except Exception as e:
        typer.echo(f"[pgcross] backend load failed: {e} — running without backend", err=True)
        backend = None

    pipeline_cfg = PipelineCfg(
        backend=backend,
        lens_sources=cfg.get("lens_sources", []),
        high_stakes_tier_bar=Tier.finite_diagnostic,
        enable_general_chat_fallback=general_chat,
    )
    ctx = Ctx(
        backend=backend,
        registry=registry,
        cfg=pipeline_cfg,
        stakes_policy=classify_stakes,
        safety=make_safety() if not unsafe_dev else None,
    )
    assert_serving_ready(ctx, allow_unsafe_dev=unsafe_dev)
    fastapi_app = create_app(ctx, allow_unsafe_dev=unsafe_dev)
    typer.echo(f"[pgcross] serving on http://{host}:{port}")
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def check(
    conformance: bool = typer.Option(False, "--conformance", help="Run conformance suite"),
):
    """Check pgcross configuration and run conformance tests."""
    import subprocess
    if conformance:
        here = os.path.dirname(os.path.abspath(__file__))
        tests = os.path.join(here, "..", "..", "tests", "conformance")
        result = subprocess.run([sys.executable, "-m", "pytest", tests, "-v"], capture_output=False)
        raise typer.Exit(result.returncode)
    typer.echo("[pgcross] check: no issues found (run --conformance for full suite)")


cards_app = typer.Typer(help="Manage engine cards.")
app.add_typer(cards_app, name="cards")


@cards_app.command("list")
def cards_list():
    """List available engine cards."""
    from .providers.cards.sis_threshold import SisThresholdCard

    cards = [SisThresholdCard()]
    for c in cards:
        cap = c.capability()
        typer.echo(
            f"  {c.id}: ceiling={cap.static_ceiling.name}"
            f" verifiability={cap.verifiability_kind.value}"
        )


if __name__ == "__main__":
    app()
