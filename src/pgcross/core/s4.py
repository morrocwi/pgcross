"""S4 — the four-value algebra: `+ / - / 0 / ⊥`, with `0 ≠ ⊥` formally enforced.

Toledo `D/M.65.v1` (`neutral_distinct_from_bottom`, **Th_coqc**), statement as registered in
Toledo's canonical equation registry (read verbatim, also quoted in the project's architecture
design notes §1/§2.4):

    Sz <> Sbot

"the four-value algebra's 'determinate zero' and 'unresolved' are formally distinct
constructors, never conflatable."

Concretely: "checked, found nothing" (`ZERO`) and "could not check" (`BOT`) must never collapse
into each other, and must never collapse into `None`/falsy/`0`/`""` at any serialization
boundary — this is the project's architecture design notes §2.4's action item for the future
`decision/schema.py`'s `DecisionAnswer`/`Candidate` types. `BOT` maps directly to `HOLD` in the
Verify/Authorize kernel (§2 of the same doc); it is a genuinely distinct algebra member, not an
absence.

Members are named ASCII-safe (`POS`/`NEG`/`ZERO`/`BOT`) for JSON/log-safety, per plus/minus/
zero/bottom. Members are plain `str` Enum members (matching this module's `CType`/`Verifiability`
pattern in `core/enums.py`, not `Tier`'s `IntEnum` — `S4` carries no ordinal/min()-able structure,
it is a four-way classification, not a floor).
"""
from __future__ import annotations

from enum import Enum


class S4(str, Enum):
    POS = "POS"
    NEG = "NEG"
    ZERO = "ZERO"
    BOT = "BOT"
