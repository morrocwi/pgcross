# imagine.py — the speculative cross-domain "imagine" layer.
#
# WHY THIS EXISTS: pipeline/compose.py generalizes engine-to-engine composition across
# vocabulary (readout_family + slot_aliases), but it is still bounded by which cards actually
# EXIST and share a declared family — it cannot bridge a query into a domain nobody has written
# a card for yet. That is a real, permanent limit of a deterministic-only system: "not stuck in
# a domain" in the fully general sense (any domain, even ones with no card) requires SOME
# generative step somewhere.
#
# THE ARCHITECTURE CONSTRAINT THIS MUST RESPECT: pgcross wraps exactly ONE model (whichever one
# is configured) — it must never require a SECOND, separate (e.g. "stronger") model to do the
# imagining. This module uses the SAME `ctx.backend` already wired into the pipeline, through a
# DIFFERENT invocation (`backend.propose_bridge`, backends/base.py) — not a second model.
#
# THE HONESTY DISCIPLINE THIS MUST RESPECT: an imagined value must NEVER be indistinguishable
# from a verified one, and must NEVER silently drive another card's compute() (unlike
# pipeline/compose.py, which only ever chains VERIFIED engine-card outputs). Doing that would
# let a hallucinated number quietly produce a candidate that LOOKS COMPUTED/verified from a
# different, unrelated card — a worse version of the "tier laundering" risk already flagged
# during compose()'s own adversarial review. So: an imagined bridge is ALWAYS its own standalone
# CType.GUESS candidate (never injected into q.slots), hard-capped at Tier.Open by tiering.py
# regardless of content, and ranked below any real COMPUTED/RETRIEVED candidate by
# pipeline/lens.py's pick_primary — it only becomes the primary answer when nothing better
# exists, which is exactly the right behavior for "when genuinely stuck, at least offer a
# clearly-labeled hypothesis instead of nothing."
#
# OFF BY DEFAULT (I8 fail-closed / no silent behavior change): only runs when
# Config.enable_imagine_bridge=True AND the configured backend implements propose_bridge.
from __future__ import annotations
from ..core.enums import CType, Verifiability, Tier, Grounding
from ..core.models import EvidenceCandidate, Provenance


def imagine_bridge(q, registry, route_fn, backend) -> list:
    """Propose at most one speculative CType.GUESS candidate per still-missing required slot
    on an already-routed card, after pipeline/compose.py's deterministic pass. Returns [] if
    the backend has no propose_bridge, or nothing is missing, or every guess comes back null.
    """
    if backend is None or not hasattr(backend, "propose_bridge"):
        return []

    routed = route_fn(q, registry)
    by_id = {p.id: p for p in registry.all()}
    missing: set[str] = set()
    for r in routed:
        p = by_id.get(r.provider_id)
        if p is None:
            continue
        for s in getattr(p, "required_slots", []):
            if s not in q.slots:
                missing.add(s)
    if not missing:
        return []

    from ..backends.base import TransportPrompt
    out_candidates = []
    for slot in sorted(missing):
        try:
            out = backend.propose_bridge(
                TransportPrompt(task="imagine_bridge", text=q.text, schema_hint={"missing_slot": slot})
            )
            guess = out.json.get("guess")
            rationale = out.json.get("rationale", "")
        except Exception:
            continue
        if guess is None:
            continue
        content = (
            f"[Speculative, UNVERIFIED cross-domain bridge for '{slot}'] "
            f"possible value: {guess}. {rationale} "
            f"This is a model-proposed hypothesis, not a computed or sourced fact."
        ).strip()
        out_candidates.append(EvidenceCandidate(
            content=content, ctype=CType.GUESS, provider_id="imagine:bridge",
            provenance=Provenance(kind="MODEL_PRIOR", verifiability=Verifiability.NONE),
            # tier/floor_reason set explicitly (not just declared_tier) — candidates built
            # outside assemble.py's final_tier() pass never get .tier computed automatically;
            # matches pipeline/lens.py's clarify_candidate/consultation_candidate convention.
            declared_tier=Tier.Open, tier=Tier.Open, floor_reason="meta", grounding=Grounding.NONE,
        ))
    return out_candidates
