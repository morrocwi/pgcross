"""Standalone demo: the witness-before-model Decision Forge gate, end to end.

Run after `pip install -e .[openthai]` (or `pip install pgcross[openthai]` from PyPI once
published):

    python examples/decision_backend_demo.py

No server, no curl -- this calls `run_pipeline()` directly so the whole chain (deterministic
harm-net check -> A3 witness/resolution gate -> DecisionBackend proposal -> ADMIT/HOLD
authorization) is visible in one script. The first run downloads OpenThai-SystemOne's weights
(~1.6GB) from the Hugging Face Hub -- a one-time, automatic download, not a separate manual step.
"""
from __future__ import annotations

from pgcross.core.provider import Registry
from pgcross.decision.backend import OpenThaiSystemOneLocalBackend
from pgcross.pipeline.run import Config, Ctx, run_pipeline


def main() -> None:
    print("[demo] constructing OpenThaiSystemOneLocalBackend (downloads weights on first use)...")
    decision_backend = OpenThaiSystemOneLocalBackend()

    cfg = Config(decision_backend=decision_backend)
    ctx = Ctx(backend=None, registry=Registry(), cfg=cfg, safety=lambda text: False)

    query = "epidemic beta=0.3 gamma=0.1 lambda_max=3?"
    print(f"[demo] query: {query!r}")
    resp = run_pipeline(query, ctx)

    print(f"[demo] authorization status: {resp.authorization.status.value}")
    print(f"[demo] authorization reason: {resp.authorization.reason}")
    primary = resp.candidates[resp.primary]
    print(f"[demo] primary candidate tier: {primary.tier}")
    print(f"[demo] primary candidate content: {primary.content!r}")


if __name__ == "__main__":
    main()
