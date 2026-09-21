"""decision/schema.py — the reconciled Verify/Authorize-stage contract.

The design confirmed by the project maintainers as the base for `decision/schema.py`/
`authorization/policy.py` (Phase 0 item 1 of the project's internal task-tracking notes,
RESOLVED 2026-09-21). This is Phase 2 item 16 of the same tracking notes.

Grounds (Toledo-verified primitives, cited by exact code, per this project's own lookup-before-derive discipline and the
project's architecture design notes §1/§2.4):

- `D/M.65.v1` (`neutral_distinct_from_bottom`, **Th_coqc**): `Sz <> Sbot` — "determinate zero"
  and "unresolved" are formally distinct constructors, never conflatable. This is why every
  typed resolution in this module is `core.s4.S4` (imported, not re-derived — one algebra, one
  owner) with **no default and no `Optional[S4] = None` workaround**: `S4.BOT` already *is* the
  "don't know" state; a bare `None` would silently reintroduce exactly the 0-vs-unknown collapse
  `D/M.65.v1` forbids. Construction without an explicit `resolution=` must fail loudly
  (`pydantic.ValidationError`), not default to something that reads as "no" or "nothing".
- `D/M.77.v1` (`bot_monotone_in_floor`, **Th_coqc**): coarsening the resolution floor can only
  ever grow the unresolved region, never shrink it — `VerificationResult.witness_checked=False`
  therefore never gets silently upgraded to a stronger claim than the check it actually ran.
- `A3` (`P(X) <=> exists w finite: check(X,w)=True`; `witness_sound`/`witness_complete`/
  `decide_reflect` all **Th_coqc**): `VerificationResult.witness_checked` records whether a
  finite witness resolved the candidate deterministically (no model call) — this is the field
  `authorization/policy.py`'s "witness before model" rule (§2.3 of the architecture doc) reads.

Per the project's internal architecture audit notes' explicit incident record (the orphaned root-level
`provider.py` vs. `core/models.py`'s `CapabilityDescriptor` — two silently-diverging contracts
for the same concept, found by the Phase A audit), this module does **not** redefine
`core/models.py`'s shapes. It extends alongside them:

- `Provenance` is imported and reused as-is (no decision-layer re-definition).
- `Candidate` (this module) is the Verify/Authorize-stage analog of `core.models.EvidenceCandidate`
  (the Propose-stage type) — same content/provenance/tier shape, plus the `S4` classification the
  Propose stage never carries. `evidence_candidate_to_decision_candidate()` is the one, explicit,
  single-direction adapter between them; nothing else in this codebase is allowed to hand-roll a
  second conversion.

`AuthorizationStatus` spells `ADMIT`/`HOLD`/`REJECT`/`ESCALATE` verbatim, matching the PGCross
Next engineering letter's own vocabulary as quoted in the project's internal architecture audit
notes and resolved (mapping from DANGER/ADVISORY/WEAKNESS) in the project's internal
task-tracking notes, Phase 0 item 5.

Integration note for whoever reconciles `decision/backend.py` next (that module's own docstring:
"this module checks for [schema.py] first and imports from it"): as of this file landing,
`decision.backend`'s `try: from .schema import DecisionProposal, DecisionQuestion` branch will
succeed, but that import list is incomplete — it does not also import `S4`/`DecisionAnswer` from
here, so `MockBackend`/`DeterministicBackend` (which reference bare `S4`/`DecisionAnswer` at
call time) will raise `NameError` once this file exists, and `tests/test_decision_backend.py`
constructs `DecisionAnswer(question_id=..., value=...)` (field name `value`) against this file's
`DecisionAnswer(question_id=..., resolution=...)` (field name `resolution`, per this file's
own explicit spec). Both are flagged here, not silently patched around, per this run's
per-file scope (`decision/schema.py` + its own test only) — someone will reconcile
`decision/backend.py` and `tests/test_decision_backend.py` against this file's field names next.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_serializer

from ..core.enums import CType, Grounding, Stakes, Tier, Verifiability
from ..core.models import EvidenceCandidate, Provenance
from ..core.s4 import S4

__all__ = [
    "S4",
    "AuthorizationStatus",
    "Readout",
    "Candidate",
    "DecisionQuestion",
    "DecisionAnswer",
    "DecisionProposal",
    "VerificationResult",
    "AuthorizationResult",
    "evidence_candidate_to_decision_candidate",
]


class AuthorizationStatus(str, Enum):
    """The Authorize stage's four outcomes — the letter's own vocabulary, verbatim.

    Confirmed mapping (project's internal task-tracking notes, Phase 0 item 5, RESOLVED
    2026-09-21): DANGER -> REJECT/ESCALATE (never self-authorized, always REFER_TO_HUMAN + crisis
    bridge); ADVISORY -> ADMIT (with-caution: opinion + explicit consult-a-human caveat, never
    blanket-refused); WEAKNESS -> HOLD (pending further evidence). That taxonomy port itself is
    separate, maintainer-gated work (Phase 3 item 23) — this enum only fixes the four target
    values.
    """

    ADMIT = "ADMIT"
    HOLD = "HOLD"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


class Readout(BaseModel):
    """One finite, retained readout of world/state (δ_R) feeding a `DecisionQuestion`.

    Per this project's own readout-not-truth epistemic stance: a readout is a finite observation, not the
    thing-in-itself. `source_ref` names where it came from (a `Candidate.provider_id`, a raw
    field in `pipeline.ground`'s slots, etc.) so a reader can trace a `Readout` back to its
    origin instead of treating it as free-floating truth.
    """

    kind: str
    value: str | float | int | None = None
    source_ref: str | None = None


class Candidate(BaseModel):
    """Decision-layer candidate — the Verify/Authorize-stage analog of
    `core.models.EvidenceCandidate` (the Propose-stage type).

    Carries the same content/provenance/tier shape as `EvidenceCandidate` (deliberately: this is
    an extension, not a competing contract — see this module's docstring on the `provider.py` vs
    `CapabilityDescriptor` divergence incident) plus `resolution: S4`, the classification
    `EvidenceCandidate` never carries because the Propose stage does not decide anything (`D/M.65
    .v1`; §2.4 of the project's architecture design notes). Built from an `EvidenceCandidate` via
    `evidence_candidate_to_decision_candidate()` below — never independently constructed by
    hand-copying `EvidenceCandidate`'s fields elsewhere.
    """

    content: str
    ctype: CType
    provider_id: str
    provenance: Provenance
    declared_tier: Tier
    grounding: Grounding = Grounding.ALL
    grounding_refs: list[str] = Field(default_factory=list)
    resolution: S4  # required — no default; BOT is the honest "not yet classified" state
    tier: Tier | None = None
    floor_reason: str | None = None

    @field_serializer("declared_tier")
    def _ser_declared_tier(self, v: Tier) -> str:
        return v.name

    @field_serializer("tier")
    def _ser_tier(self, v: Tier | None) -> str | None:
        return v.name if v is not None else None

    @field_serializer("resolution")
    def _ser_resolution(self, v: S4) -> str:
        return v.value


def evidence_candidate_to_decision_candidate(
    ec: EvidenceCandidate, resolution: S4 = S4.BOT
) -> Candidate:
    """The one explicit adapter: Propose-stage `EvidenceCandidate` -> decision-layer `Candidate`.

    `resolution` defaults to `S4.BOT` ("not yet classified") because a bare `EvidenceCandidate`
    coming out of the Propose stage has not been through Verify's witness-check/resolution-gate
    yet (the project's architecture design notes §2.3/§2.5) — this function never guesses
    `POS`/`NEG`/`ZERO` on the caller's behalf. A caller that already has a verified classification
    (e.g. from a `VerificationResult`) passes it explicitly.

    Per this module's docstring: this is the ONLY conversion path between the two schemas. Do not
    hand-roll a second one (this is exactly the mistake Phase A found already happened once with
    the orphaned root-level `provider.py` vs. `core/models.py`'s `CapabilityDescriptor`).
    """
    return Candidate(
        content=ec.content,
        ctype=ec.ctype,
        provider_id=ec.provider_id,
        provenance=ec.provenance,
        declared_tier=ec.declared_tier,
        grounding=ec.grounding,
        grounding_refs=list(ec.grounding_refs),
        resolution=resolution,
        tier=ec.tier,
        floor_reason=ec.floor_reason,
    )


class DecisionQuestion(BaseModel):
    """A single typed question posed to a `DecisionBackend` (`decision/backend.py`).

    `kind` matches the three typed-question shapes a real System-One-style backend (e.g.
    OpenThai-SystemOne) supports natively, so `decision/backend.py`'s implementations can map a
    `DecisionQuestion` onto the backend's own question type directly, without a lossy translation
    layer:
      - `"choice"` (default, backward-compatible with the original options-only shape): pick one
        of up to 255 labeled options. `options` holds the option labels; `option_descriptions`
        (parallel dict, optional) gives each option a longer instruction/criterion string, since a
        real backend answers more reliably from a description than a bare label alone.
      - `"score"`: an ordered scale from 2-10 described levels. `levels` holds the level
        descriptions in order (e.g. `["not frustrated", "mildly annoyed", "very frustrated"]`).
      - `"noul"`: a yes/no question — no `options`/`levels` needed, `text` is the question itself.
    """

    id: str
    text: str
    kind: str = "choice"  # "choice" | "score" | "noul"
    options: list[str] = Field(default_factory=list)  # empty = open/free-form answer (kind="choice")
    option_descriptions: dict[str, str] = Field(default_factory=dict)  # optional, kind="choice"
    levels: list[str] = Field(default_factory=list)  # ordered level descriptions, kind="score"


class DecisionAnswer(BaseModel):
    """One answer to one `DecisionQuestion`, carrying a required `S4` resolution.

    `resolution: S4` has **no default** and is **not** `Optional[S4] = None` — per `D/M.65.v1`,
    `S4.BOT` already is the formally-distinct "unresolved" constructor; a separate `None` would
    reintroduce the exact 0-vs-unknown collapse this schema exists to prevent. Constructing a
    `DecisionAnswer` without an explicit `resolution=` therefore raises
    `pydantic.ValidationError`, not a silent fallback.
    """

    question_id: str
    resolution: S4
    label: str | None = None  # free-form content when resolution is POS/NEG and options is empty
    probability: float = 0.0  # in [0, 1]; meaningless/ignored when resolution is BOT
    probabilities: dict[str, float] = Field(default_factory=dict)  # full distribution, kind="choice"

    @field_serializer("resolution")
    def _ser_resolution(self, v: S4) -> str:
        return v.value


class DecisionProposal(BaseModel):
    """A `DecisionBackend`'s proposal for a batch of questions — NEVER an authorization.

    Per the project's architecture design notes §3: this always passes back through PGCross's
    Verify/Authorize gate before it can become an `AuthorizationResult`; a proposal's confidence
    never bypasses a failed gate (F1, per the project's internal architecture audit notes'
    invariants list).
    """

    answers: list[DecisionAnswer]
    backend_id: str
    rationale: str = ""


class VerificationResult(BaseModel):
    """Verify-stage output for one `Candidate` — the result of a witness-check
    (`A3`, §2.3) and/or resolution-gate readout (`D/M.77.v1`, §2.5), never a guess.

    `witness_checked=True` means a finite, deterministic witness resolved this candidate with no
    model call (`A3`'s `witness_sound`/`witness_complete`/`decide_reflect`, all `Th_coqc`) —
    `authorization/policy.py`'s "witness before model" rule reads this field before ever
    constructing a `DecisionBackend` call. `resolution=S4.BOT` with `witness_checked=False` is the
    honest "genuinely could not resolve this, and did not fake a resolution" state; it must never
    be reported as `ZERO` (`D/M.65.v1`).
    """

    candidate_provider_id: str
    resolution: S4
    verifiability: Verifiability
    tier: Tier
    witness_checked: bool = False
    detail: str = ""

    @field_serializer("resolution")
    def _ser_resolution(self, v: S4) -> str:
        return v.value

    @field_serializer("tier")
    def _ser_tier(self, v: Tier) -> str:
        return v.name


class AuthorizationResult(BaseModel):
    """Authorize-stage output — the terminal ADMIT/HOLD/REJECT/ESCALATE decision.

    Per the confirmed DANGER/ADVISORY/WEAKNESS mapping (project's internal task-tracking notes,
    Phase 0 item 5): HIGH stakes must always retain a consultation option (I5, per the project's
    internal architecture audit notes' invariants list) — `consultation_offered` records whether
    that option was actually attached to
    this result, so a caller can assert it rather than trust the label alone.
    """

    status: AuthorizationStatus
    reason: str
    stakes: Stakes
    consultation_offered: bool = False
    source_verifications: list[VerificationResult] = Field(default_factory=list)

    @field_serializer("status")
    def _ser_status(self, v: AuthorizationStatus) -> str:
        return v.value
