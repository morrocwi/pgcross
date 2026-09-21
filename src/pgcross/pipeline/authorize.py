from __future__ import annotations
from typing import Any

from .. import crisis_resources
from ..core.enums import Tier, CType, Grounding, Stakes, ASSERTIVE
from ..core.models import Response, VerifierResult
from ..core.s4 import S4
from ..decision.schema import AuthorizationResult, AuthorizationStatus, DecisionQuestion
from ..authorization.policy import (
    authorize_decision_proposal,
    classify_and_authorize,
    needs_decision_backend,
)
from .lens import consultation_candidate, clarify_or_consultation, pick_primary

_MODEL_QUESTION_ID = "primary_candidate_admissible"

# Marker substring identifying an already-attached crisis-resources block, so
# `_attach_crisis_resources` never double-appends if it is called more than once against the
# same promoted CONSULTATION candidate (e.g. a pre-existing CONSULTATION candidate reused across
# calls). This mirrors `crisis_resources.render()`'s own EN/TH disclaimer wording rather than a
# private symbol from that module (keeps this file decoupled from that module's internals).
_CRISIS_MARKER = "findahelpline.com"


def _attach_crisis_resources(cand: Any, lang: str = "en", region: str = "TH") -> None:
    """Append the static, offline crisis-resources block (`crisis_resources.render()`) onto
    `cand.content` in place, unless it is already present. Scoped narrowly to the self-harm/
    ESCALATE path only (see `authorize()` below) — never fired for the harm-to-others/REJECT
    path (no crisis bridge applies to "how do I make a bomb") nor for plain ADVISORY/HOLD paths
    (over-triggering a crisis resource on a non-self-harm case would be its own harm)."""
    if _CRISIS_MARKER in (cand.content or ""):
        return
    cand.content = f"{cand.content}\n\n{crisis_resources.render(lang=lang, region=region)}"


class AuthorizedResponse(Response):
    """`Response` extended with the Authorize stage's `AuthorizationStatus` (this module's design,
    internal task-tracking notes, item 17-adjacent wiring). Subclasses rather than modifying
    `core.models.Response` directly, to avoid a circular import (`decision/schema.py` already
    imports `EvidenceCandidate`/`Provenance` FROM `core/models.py`; `core/models.py` importing
    back from `decision/schema.py` would be exactly the divergent-contract mistake the
    project's internal architecture audit notes already flagged once for the orphaned root
    `provider.py`
    vs. `CapabilityDescriptor`). `isinstance(resp, Response)` still holds for every existing
    caller/test that only reads `.candidates`/`.primary`/`.stakes` — this is additive, not a
    breaking schema change."""

    authorization: AuthorizationResult


def _witness_probe(cand: Any) -> VerifierResult:
    """Best-effort `A3` witness proxy for a live `EvidenceCandidate`.

    `verify()` (`pipeline/verify.py`) calls `provider.verify()` and folds the result into
    `provenance.verifiability` (downgrading to `Verifiability.NONE` on failure) but does not
    persist the raw `VerifierResult` on the candidate itself — so by the time a candidate reaches
    `authorize()`, the original `ok`/`detail` pair from `has_finite_witness`'s two recognized
    witness-check instances (`providers/cards/base.py`'s coq_checked/independent_oracle path,
    `providers/oracle/execution_oracle.py`'s pass/fail) is gone. This reconstructs the closest
    honest proxy from what DOES survive: `provenance.verifiability` == `COQ_CHECKED` or
    `INDEPENDENT_ORACLE` is exactly `has_finite_witness`'s own "a real deterministic check ran
    and passed" condition (see that function's docstring, case 1) — anything else
    (`SOURCE_ATTRIBUTED`/`SELF_CONSISTENT`/`NONE`) is honestly reported as no witness, never
    guessed as one. This is a documented, temporary proxy — once `verify()` threads the real
    `VerifierResult` through to `authorize()` (a future stream), this shim should be replaced
    with the real value, not kept alongside it."""
    verifiability = cand.provenance.verifiability
    witness_ok = verifiability.name in ("COQ_CHECKED", "INDEPENDENT_ORACLE")
    return VerifierResult(
        ok=witness_ok, verifiability=verifiability,
        detail="witness_proxy_pass" if witness_ok else "no_witness",
    )


def _authorize_status(cands: list, q, decision_backend: Any = None) -> tuple[AuthorizationStatus, str, Any]:
    """Harm/stakes taxonomy (`classify_and_authorize`, `authorization/policy.py`) + witness-
    before-model gate (`needs_decision_backend`), per the project's architecture design notes
    §2.3/§3/§4 item 1. Returns `(status, reason, danger_source)`; `danger_source` is the
    candidate whose content triggered a DANGER classification (or `None` when the query text
    itself did, or when nothing did) — the caller uses it to make sure that exact candidate can
    never become `Response.primary` (the F1 invariant below).

    Query text is checked FIRST (matches `classify_harm_taxonomy`'s own "gated by the
    independent harm net first" ordering); every surviving candidate's own content is then
    checked too, since a DANGER-triggering candidate can originate from a provider (e.g. a
    retrieved/composed value) even when the raw query text itself did not match the harm net.

    `decision_backend` (optional, a `decision.backend.DecisionBackend`-shaped object, e.g.
    `OpenThaiSystemOneLocalBackend`/`SystemOneHTTPBackend`/`MockBackend`) is only ever reached
    AFTER the harm-net check above found nothing AND `needs_decision_backend()` (A3 witness +
    D/M.77.v1 resolution gate) says no deterministic resolution exists either — "the model
    proposed, PGCross authorized" (`authorization/policy.py::authorize_decision_proposal`), never
    the reverse. `decision_backend=None` (the default) preserves this stage's original honest
    HOLD-default behavior exactly.
    """
    q_status = classify_and_authorize(q.text)
    if q_status in (AuthorizationStatus.REJECT, AuthorizationStatus.ESCALATE):
        return q_status, f"harm/stakes taxonomy on query text: {q_status.value}", None

    for c in cands:
        c_status = classify_and_authorize(c)
        if c_status in (AuthorizationStatus.REJECT, AuthorizationStatus.ESCALATE):
            return c_status, f"harm/stakes taxonomy on candidate {c.provider_id!r}: {c_status.value}", c

    # No DANGER anywhere (query or candidates). q_status is now ADMIT (ADVISORY) or HOLD
    # (WEAKNESS) — still gate it through "witness before model" (A3 + D/M.77.v1) for the primary
    # candidate: if resolving it would require a DecisionBackend call, only make that call when
    # one is actually configured; otherwise the honest answer stays HOLD, never a fabricated call.
    if cands:
        primary_probe = pick_primary(cands)
        primary = cands[primary_probe]
        vr = _witness_probe(primary)
        # The witness probe never itself runs the resolution-gate (`D/M.77.v1`, §2.5) — it only
        # recognizes whether a deterministic check already resolved the candidate. So the
        # `s4_result` fed to `needs_decision_backend()` is `S4.BOT` whenever nothing else has
        # resolved it either; per `D/M.65.v1` (`0 != ⊥`), `S4.ZERO` is never substituted here
        # even when `vr.ok` is `False` — "witness said no" is a determinate answer already
        # handled by the caller's normal candidate filtering, not the ⊥-state
        # `needs_decision_backend` gates on.
        if needs_decision_backend(gate=None, candidate=vr, s4_result=S4.BOT):
            if decision_backend is None:
                return (
                    AuthorizationStatus.HOLD,
                    "no finite witness resolved the primary candidate and no DecisionBackend is "
                    "configured for this call — defaulting to HOLD, never a guess",
                    None,
                )
            # "The model proposed, PGCross authorized": one typed question about the primary
            # candidate, per DecisionBackend's own documented FAILURE POLICY (decision/backend.py)
            # -- a raise/timeout here is THIS caller's responsibility to default to HOLD, exactly
            # like the no-backend-configured branch above, never propagated as an unhandled error.
            question = DecisionQuestion(
                id=_MODEL_QUESTION_ID,
                text=(
                    f"Given the query {q.text!r}, is the following proposed answer admissible "
                    f"as a response: {primary.content!r}?"
                ),
                kind="noul",
            )
            try:
                proposal = decision_backend.decide(
                    state={"query": q.text, "candidate_content": primary.content,
                           "candidate_tier": str(primary.tier) if primary.tier else None},
                    questions=[question],
                )
            except Exception as exc:  # noqa: BLE001 -- FAILURE POLICY: any backend failure -> HOLD
                return (
                    AuthorizationStatus.HOLD,
                    f"DecisionBackend call raised ({type(exc).__name__}: {exc}) — defaulting to "
                    "HOLD per its documented FAILURE POLICY, never a guess",
                    None,
                )
            status, reason = authorize_decision_proposal(proposal, _MODEL_QUESTION_ID)
            return status, reason, None
    return q_status, f"harm/stakes taxonomy: {q_status.value}", None


def authorize(cands: list, q, cfg) -> Response:
    """Authorize stage (pure, behavior-preserving extraction from the former fused
    pipeline/assemble.py): I2 ungrounded-COMPUTED skip, I5 HIGH-stakes CONSULTATION-lead
    filtering, I4 non-empty-response fallback, primary-candidate selection, and the D2
    consultation-lead fix. Takes the raw candidate list verify() produced (already tiered via
    core.tiering.final_tier) and decides what survives / leads. This function has NO knowledge
    of provider.produce()/provider.verify() or core.tiering.final_tier — that is verify()'s job
    (pipeline/verify.py).

    this module's design (internal task-tracking notes, items 17/23, the project's architecture
    design notes §2.3/§3/§4): the ADMIT/HOLD/REJECT/ESCALATE layer below runs AFTER all of the
    I2/I5/I4/D2
    logic above — it does not reorder or replace any of it, it only adds an `AuthorizationStatus`
    on top and enforces the F1 invariant (an ESCALATE/REJECT-classified candidate can never
    become `Response.primary`, regardless of its declared/final tier — "a model may propose,
    never authorize ... confidence never bypasses a failed gate").
    """
    cands = [c for c in cands
             if not (c.ctype == CType.COMPUTED and c.grounding == Grounding.NONE)]  # I2
    if q.stakes == Stakes.HIGH:                                  # I5
        bar = cfg.high_stakes_tier_bar
        cands = [c for c in cands if not (c.ctype in ASSERTIVE and int(c.tier or Tier.Open) < int(bar))]
        if not any(c.ctype == CType.CONSULTATION for c in cands):
            cands.append(consultation_candidate(q))
    if not cands:                                                # I4
        cands.append(clarify_or_consultation(q))
    primary = pick_primary(cands)
    # FIX D2: in HIGH stakes, if no assertive candidate survived, LEAD with the CONSULTATION, not a lens.
    if q.stakes == Stakes.HIGH and cands[primary].ctype not in ASSERTIVE:
        for i, c in enumerate(cands):
            if c.ctype == CType.CONSULTATION: primary = i; break

    # ---- NEW (this module's design): ADMIT/HOLD/REJECT/ESCALATE + witness-before-model gate -------
    # cfg.decision_backend is optional (getattr default None) -- callers that don't configure one
    # get the exact same honest HOLD-on-⊥ behavior as before a real backend existed.
    status, reason, danger_source = _authorize_status(cands, q, getattr(cfg, "decision_backend", None))

    # F1 invariant, first-ever test in this codebase (tests/test_f1_gate_bypass.py): an
    # ESCALATE/REJECT-classified candidate can NEVER become Response.primary, no matter its
    # declared_tier/tier. Tier is a Verify-stage grounding-strength measure; authorization status
    # is a Verify-stage-independent safety gate — a high tier never overrides a failed gate.
    if status in (AuthorizationStatus.REJECT, AuthorizationStatus.ESCALATE):
        # Either the exact candidate that triggered DANGER is currently primary, or the query
        # text itself triggered DANGER (danger_source is None) and primary is still an
        # assertive/lens/guess candidate rather than an already-safe CONSULTATION/CLARIFY one.
        primary_is_dangerous = (
            (danger_source is not None and cands[primary] is danger_source)
            or (danger_source is None and cands[primary].ctype not in (CType.CONSULTATION, CType.CLARIFY))
        )
        if primary_is_dangerous:
            for i, c in enumerate(cands):
                if c.ctype == CType.CONSULTATION:
                    primary = i
                    break
            else:
                cands.append(consultation_candidate(q))
                primary = len(cands) - 1

        # Crisis-resources wiring (self-harm/ESCALATE only — never REJECT/harm-to-others, never
        # plain ADVISORY/HOLD): the promoted CONSULTATION candidate that just became primary is
        # the "choice-first SAFETY path" `crisis_resources.py` was built for — attach the real,
        # offline Thailand + international-fallback hotline block onto it so the response is a
        # genuine human bridge, not a vague "see a hotline".
        if status is AuthorizationStatus.ESCALATE:
            _attach_crisis_resources(cands[primary])

    auth_result = AuthorizationResult(
        status=status,
        reason=reason,
        stakes=q.stakes,
        consultation_offered=any(c.ctype == CType.CONSULTATION for c in cands),
    )
    return AuthorizedResponse(candidates=cands, primary=primary, stakes=q.stakes, authorization=auth_result)
