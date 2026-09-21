from __future__ import annotations
from ..core.enums import Tier, CType
from ..core.models import Response

_TIER_LABELS = {
    Tier.Th_coqc: "machine-verified structure (Coq-checked)",
    Tier.finite_diagnostic: "independently cross-checked value",
    Tier.Dr: "source-attributed / single-path computation",
    Tier.Wf: "working-framework consistency (treat as a starting point)",
    Tier.Open: "ungrounded — offered as a lens or guess, not a verdict",
}

_CTYPE_PREFIXES = {
    CType.COMPUTED: "Computed",
    CType.RETRIEVED: "Retrieved",
    CType.LENS: "Lens",
    CType.GUESS: "Guess",
    CType.CLARIFY: "Clarification needed",
    CType.CONSULTATION: "Consultation recommended",
}

def render_candidates_for_human(resp: Response) -> str:
    """Render the pipeline response as readable text.

    Primary candidate first with plain-word tier tag.
    Alternatives listed. Consultation pointer on abstain.
    Machine tier stays in .pgcross — this is the human-facing text.
    """
    lines = []
    primary = resp.candidates[resp.primary]
    tier_label = _TIER_LABELS.get(primary.tier, str(primary.tier))
    ctype_prefix = _CTYPE_PREFIXES.get(primary.ctype, str(primary.ctype))
    lines.append(f"[{ctype_prefix} · {tier_label}]")
    lines.append(primary.content)
    others = [c for i, c in enumerate(resp.candidates) if i != resp.primary]
    if others:
        lines.append("")
        lines.append("Alternatives:")
        for c in others:
            tl = _TIER_LABELS.get(c.tier, str(c.tier))
            cp = _CTYPE_PREFIXES.get(c.ctype, str(c.ctype))
            lines.append(f"  [{cp} · {tl}] {c.content[:200]}")
    return "\n".join(lines)
