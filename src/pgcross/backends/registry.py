"""backends/registry.py — backend factory.

SPEC §6: build_backend dispatches on cfg['kind'] to the concrete backend class.
"""
from __future__ import annotations


def build_backend(cfg: dict):
    """Instantiate a backend from a config dict.

    cfg keys:
      kind: llamacpp | openai | vllm | ollama
      weights: str  (llamacpp)
      url: str      (openai/vllm/ollama)
      model: str    (openai/vllm)
      context_length: int  (llamacpp, default 8192)
    """
    kind = cfg.get("kind", "llamacpp")

    if kind == "llamacpp":
        from .llamacpp import LlamaCppBackend
        weights = cfg.get("weights")
        if not weights:
            raise ValueError("llamacpp backend requires 'weights' (path to .gguf)")
        return LlamaCppBackend(
            weights=weights,
            context_length=cfg.get("context_length", 8192),
        )

    if kind == "openai":
        from .openai import OpenAIBackend
        url = cfg.get("url")
        model = cfg.get("model")
        if not url or not model:
            raise ValueError("openai backend requires 'url' and 'model'")
        return OpenAIBackend(
            url=url,
            model=model,
            api_key=cfg.get("api_key", "sk-placeholder"),
            context_length=cfg.get("context_length", 8192),
        )

    if kind in ("vllm", "ollama"):
        raise NotImplementedError(
            f"backend kind {kind!r} is not yet implemented. "
            "Contribute backends/vllm.py / ollama.py to add it."
        )

    raise ValueError(
        f"unknown backend kind: {kind!r}. Supported: llamacpp, openai, vllm, ollama"
    )
