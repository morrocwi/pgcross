from __future__ import annotations
from dataclasses import dataclass, field
from ..core.enums import CType, Stakes, Tier, Verifiability, Grounding
from ..core.models import EvidenceCandidate, Provenance, QueryIR, Response
from ..core.provider import Registry
from ..decision.schema import AuthorizationStatus
from .assemble import assemble
from .route import route
from .ground import ground
from .compose import compose
from .imagine import imagine_bridge
from .lens import consultation_candidate, pick_primary

class HarmfulRequest(Exception): pass

@dataclass
class Config:
    backend: object = None
    lens_sources: list = field(default_factory=list)
    high_stakes_tier_bar: Tier = Tier.finite_diagnostic
    enable_imagine_bridge: bool = False   # OFF by default (I8): see pipeline/imagine.py
    enable_general_chat_fallback: bool = False   # OFF by default (I8): see _general_chat_fallback below
    decision_backend: object = None   # optional decision.backend.DecisionBackend, e.g.
        # OpenThaiSystemOneLocalBackend/SystemOneHTTPBackend/MockBackend. None (default) preserves
        # pipeline/authorize.py's honest HOLD-on-unresolved behavior; only reached AFTER the
        # deterministic harm-net check + witness-before-model gate both find nothing (see
        # pipeline/authorize.py::_authorize_status) -- "the model proposed, PGCross authorized."

@dataclass
class Ctx:
    backend: object
    registry: Registry
    cfg: Config
    stakes_policy: object = None
    safety: object = None            # INJECTED is_harmful(text)->bool (do NOT hard-import a stub)
    def classify_stakes(self, text): return Stakes.LOW if self.stakes_policy is None else self.stakes_policy(text)

def _general_chat_fallback(q: QueryIR, resp: Response, backend) -> list:
    """The router the engine-card architecture was always missing a third path for: not
    "a structured card fired" and not "refuse" but "genuinely no structured signal, so answer
    as a plain assistant instead of a canned refusal." This is what makes pgcross usable as a
    general model backend (e.g. behind Codex CLI, which also sends casual chat / `/review` /
    general coding requests no engine card exists for).

    SAFETY-CRITICAL conditions, ALL required, so this can never override a real refusal:
      - q.stakes != HIGH: a HIGH-stakes CONSULTATION is assemble.py's I5 safety gate doing its
        job on purpose — this fallback must never paper over it.
      - the primary candidate is CType.CONSULTATION: i.e. nothing else beat it already.
      - ZERO CType.COMPUTED/RETRIEVED candidates exist anywhere in the response: not just "the
        primary happens to be a refusal" but genuinely no structured signal was found at all —
        a partial/low-confidence structured answer must never be silently replaced.
    The engine-card layer itself is completely unmodified by this — it still fires exactly as
    before whenever it has real signal; this only fills the previously-empty "neither" case.
    """
    primary = resp.candidates[resp.primary]
    if q.stakes == Stakes.HIGH or primary.ctype != CType.CONSULTATION:
        return []
    if any(c.ctype in (CType.COMPUTED, CType.RETRIEVED) for c in resp.candidates):
        return []
    if backend is None or not hasattr(backend, "general_chat"):
        return []
    try:
        reply = backend.general_chat(q.text)
    except Exception:
        return []
    if not reply:
        return []
    return [EvidenceCandidate(
        content=reply, ctype=CType.GUESS, provider_id="general_chat",
        provenance=Provenance(kind="MODEL_PRIOR", verifiability=Verifiability.NONE),
        # tier/floor_reason set explicitly (not just declared_tier) — this candidate is built
        # outside assemble.py's final_tier() pass, which is the only place .tier normally gets
        # computed; matches pipeline/lens.py's clarify_candidate/consultation_candidate
        # convention (caught by test_general_chat_fallback_fires_on_zero_signal_low_stakes,
        # which also caught the identical pre-existing gap in pipeline/imagine.py).
        declared_tier=Tier.Open, tier=Tier.Open, floor_reason="meta", grounding=Grounding.NONE,
    )]


def _reassert_f1_gate(resp: Response, q: QueryIR) -> None:
    """FIX F1 (found live by this run's adversarial verify pass, internal task-tracking notes item 30):
    `_general_chat_fallback`/`imagine_bridge` append a new `CType.GUESS` candidate and recompute
    `resp.primary` via a plain `pick_primary()` call that knows nothing about
    `AuthorizationResult` — `pick_primary`'s tie-break ranks GUESS above CONSULTATION at equal
    (Tier.Open) tier, so the newly-appended, completely unguarded candidate can silently become
    primary even when `authorize()` (pipeline/authorize.py) already forced primary to a safe
    CONSULTATION candidate because the query/a candidate triggered REJECT/ESCALATE. Confidence
    (or, here, a bare GUESS append) must never bypass a failed gate (F1) — re-assert it here,
    every time a post-assemble() step is allowed to touch `resp.primary`.

    `authorize()` already guarantees at least one CONSULTATION candidate exists in `resp.candidates`
    whenever `resp.authorization.status` is REJECT/ESCALATE (see its own `primary_is_dangerous`
    branch) — this only needs to re-pin primary to it, defensively re-creating one if that
    invariant were ever violated upstream.
    """
    auth = getattr(resp, "authorization", None)
    if auth is None or auth.status not in (AuthorizationStatus.REJECT, AuthorizationStatus.ESCALATE):
        return
    if resp.candidates[resp.primary].ctype in (CType.CONSULTATION, CType.CLARIFY):
        return  # already safe — nothing to reassert
    for i, c in enumerate(resp.candidates):
        if c.ctype == CType.CONSULTATION:
            resp.primary = i
            return
    resp.candidates = resp.candidates + [consultation_candidate(q)]
    resp.primary = len(resp.candidates) - 1


def run_pipeline(user_text: str, ctx: Ctx, decision_question: object = None) -> Response:
    """`decision_question` (optional, a `decision.schema.DecisionQuestion`): when a caller has a
    real typed noul/choice/score question to ask (not just free text) -- e.g. `server/
    systemone.py`, answering a Jev/TypeSafe-style typed request -- pass it here so `pipeline/
    authorize.py`'s witness-before-model gate asks THIS question directly to a configured
    `decision_backend` instead of its own synthetic "is the fallback candidate admissible"
    question. See `core/models.py::QueryIR.decision_question` and `authorize.py::
    _authorize_status`'s own docstring for why this distinction is real, not cosmetic (a real
    bug, found live 2026-09-21, otherwise: a trivially-true factual question got a confident
    "no" back, because the synthetic question was being asked instead of the real one)."""
    if ctx.safety is not None and ctx.safety(user_text):     # I8 — separate switch, injected
        raise HarmfulRequest()
    q = QueryIR(text=user_text, decision_question=decision_question)
    q.stakes = ctx.classify_stakes(user_text)
    q = ground(q, ctx.backend)
    q = compose(q, ctx.registry, route)               # engine-to-engine slot composition (1 hop, capped)
    resp = assemble(q, route(q, ctx.registry), ctx.registry, ctx.cfg)
    if getattr(ctx.cfg, "enable_imagine_bridge", False):
        extra = imagine_bridge(q, ctx.registry, route, ctx.backend)
        if extra:                              # never replaces existing candidates, only adds
            resp.candidates = resp.candidates + extra
            resp.primary = pick_primary(resp.candidates)
            _reassert_f1_gate(resp, q)
    if getattr(ctx.cfg, "enable_general_chat_fallback", False):
        extra = _general_chat_fallback(q, resp, ctx.backend)
        if extra:
            resp.candidates = resp.candidates + extra
            resp.primary = pick_primary(resp.candidates)
            _reassert_f1_gate(resp, q)
    return resp

def assert_serving_ready(ctx: "Ctx", allow_unsafe_dev: bool = False) -> None:
    """FIX F1: fail CLOSED. server startup + `pgcross serve` MUST call this. Empirically, safety=None
    otherwise fails OPEN (the pipeline answered a harmful-looking request in testing)."""
    if ctx.safety is None and not allow_unsafe_dev:
        raise RuntimeError("refusing to serve: no safety layer wired "
                           "(set ctx.safety, or pass allow_unsafe_dev=True for local dev only)")
