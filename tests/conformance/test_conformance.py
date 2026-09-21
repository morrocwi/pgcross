"""29-test conformance suite — the acceptance gate.
All I1-I8 invariants must pass before any distribution decision.
Run: python -m pytest tests/conformance/ -v (from the repository root)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import pytest
from pgcross.core.enums import (
    Tier, CType, Verifiability, RoutingCertainty, Grounding, Stakes, ASSERTIVE
)
from pgcross.core.models import (
    Provenance, EvidenceCandidate, QueryIR, CapabilityDescriptor, VerifierResult
)
from pgcross.core.tiering import final_tier, verifiability_ceiling, routing_cap, grounding_cap
from pgcross.core.provider import Registry
from pgcross.pipeline.run import Ctx, Config, assert_serving_ready, HarmfulRequest, run_pipeline
from pgcross.pipeline.assemble import assemble
from pgcross.pipeline.route import route
from pgcross.pipeline.ground import ground
from pgcross.pipeline.lens import consultation_candidate, clarify_candidate
from pgcross.providers.cards.sis_threshold import SisThresholdCard

# ---------------------------------------------------------------------------
# Helpers: minimal stub providers for pipeline tests
# ---------------------------------------------------------------------------

def _make_cand(ctype, v, declared=Tier.Th_coqc, grounding=Grounding.ALL, kind="ENGINE_CARD"):
    return EvidenceCandidate(
        content="test", ctype=ctype, provider_id="test",
        provenance=Provenance(kind=kind, verifiability=v),
        declared_tier=declared, grounding=grounding,
    )


class _SimpleProvider:
    """Fully-conformant base for test providers."""
    id = "simple"

    def capability(self):
        return CapabilityDescriptor(
            provider_id=self.id, readout_intents={"test"},
            verifiability_kind=Verifiability.SELF_CONSISTENT,
            static_ceiling=Tier.Dr,
        )

    def routing_certainty(self, q):
        return RoutingCertainty.DENSE_WEAK

    def can_serve(self, q):
        return 0.5

    def produce(self, q):
        return []

    def verify(self, cand):
        return VerifierResult(ok=True, verifiability=Verifiability.SELF_CONSISTENT)

    def ground(self, claim, cands):
        return []


class _ComputedProvider(_SimpleProvider):
    """Returns one COMPUTED@Wf candidate (grounding=ALL, SELF_CONSISTENT)."""
    id = "computed_wf"

    def produce(self, q):
        return [EvidenceCandidate(
            content="computed result", ctype=CType.COMPUTED, provider_id=self.id,
            provenance=Provenance(kind="ENGINE_CARD", verifiability=Verifiability.SELF_CONSISTENT),
            declared_tier=Tier.Wf, grounding=Grounding.ALL,
        )]


class _RetrievedProvider(_SimpleProvider):
    """Returns one RETRIEVED candidate backed by a supported span."""
    id = "rag:peer"
    authority_ceiling = Tier.Dr

    def capability(self):
        return CapabilityDescriptor(
            provider_id=self.id, readout_intents={"passage_backed"},
            verifiability_kind=Verifiability.SOURCE_ATTRIBUTED,
            static_ceiling=Tier.Dr,
        )

    def produce(self, q):
        return [EvidenceCandidate(
            content="peer reviewed passage", ctype=CType.RETRIEVED, provider_id=self.id,
            provenance=Provenance(kind="RAG_CHUNK", source_ref="peer:0:span",
                                  verifiability=Verifiability.SOURCE_ATTRIBUTED),
            declared_tier=Tier.Dr, grounding_refs=["span"],
        )]

    def ground(self, claim, cands):
        return ["span"]  # supported


class _UnsupportedRagProvider(_SimpleProvider):
    """Returns a RETRIEVED candidate whose ground() returns None (unsupported)."""
    id = "rag:unsupported"
    authority_ceiling = Tier.Dr

    def capability(self):
        return CapabilityDescriptor(
            provider_id=self.id, readout_intents={"passage_backed"},
            verifiability_kind=Verifiability.SOURCE_ATTRIBUTED,
            static_ceiling=Tier.Dr,
        )

    def produce(self, q):
        return [EvidenceCandidate(
            content="some retrieved text", ctype=CType.RETRIEVED, provider_id=self.id,
            provenance=Provenance(kind="RAG_CHUNK", source_ref="test:0:span",
                                  verifiability=Verifiability.SOURCE_ATTRIBUTED),
            declared_tier=Tier.Dr, grounding_refs=["span"],
        )]

    def ground(self, claim, cands):
        return None  # unsupported → I3 suppression


class _ThrowingProvider(_SimpleProvider):
    """Throws on produce() to test provider-crash isolation (I4/A3)."""
    id = "thrower"

    def produce(self, q):
        raise RuntimeError("deliberate provider crash")


class _UngroundedComputedProvider(_SimpleProvider):
    """Returns a COMPUTED candidate with Grounding.NONE (should be suppressed — I2)."""
    id = "ungrounded_computed"

    def produce(self, q):
        return [EvidenceCandidate(
            content="ungrounded number 42", ctype=CType.COMPUTED, provider_id=self.id,
            provenance=Provenance(kind="ENGINE_CARD", verifiability=Verifiability.SELF_CONSISTENT),
            declared_tier=Tier.Dr, grounding=Grounding.NONE,
        )]


class _FailingOracleProvider(_SimpleProvider):
    """independent_oracle=True but verify() fails → verifiability → NONE → tier → Open."""
    id = "failing_oracle"

    def capability(self):
        return CapabilityDescriptor(
            provider_id=self.id, readout_intents={"test"},
            verifiability_kind=Verifiability.INDEPENDENT_ORACLE,
            static_ceiling=Tier.finite_diagnostic,
        )

    def produce(self, q):
        return [EvidenceCandidate(
            content="oracle answer", ctype=CType.COMPUTED, provider_id=self.id,
            provenance=Provenance(kind="ENGINE_CARD", verifiability=Verifiability.INDEPENDENT_ORACLE),
            declared_tier=Tier.finite_diagnostic, grounding=Grounding.ALL,
        )]

    def verify(self, cand):
        # independent_oracle check fails
        return VerifierResult(ok=False, verifiability=Verifiability.NONE, detail="oracle_fail")

    def ground(self, claim, cands):
        return []


class _WeakComputedProvider(_SimpleProvider):
    """Returns a COMPUTED@Wf candidate for high-stakes test."""
    id = "weak_computed"

    def produce(self, q):
        return [EvidenceCandidate(
            content="weak computed", ctype=CType.COMPUTED, provider_id=self.id,
            provenance=Provenance(kind="ENGINE_CARD", verifiability=Verifiability.SELF_CONSISTENT),
            declared_tier=Tier.Wf, grounding=Grounding.ALL,
        )]


def _make_ctx(providers, stakes_policy=None, safety=None, cfg=None):
    """Build a minimal Ctx from a list of provider instances."""
    reg = Registry()
    for p in providers:
        reg.register(p)
    if cfg is None:
        cfg = Config()
    return Ctx(backend=None, registry=reg, cfg=cfg, stakes_policy=stakes_policy, safety=safety)


# ---------------------------------------------------------------------------
# 1. differential_tiering — exhaustive product check
# ---------------------------------------------------------------------------

def _ref_tier(ctype, v, rc, g, declared=Tier.Th_coqc, authority_ceiling=Tier.Dr):
    """Independent reference implementation of final_tier semantics."""
    if ctype == CType.COMPUTED:
        vc = verifiability_ceiling(v, authority_ceiling)
        r  = routing_cap(rc)
        gc = grounding_cap(g)
        return min(declared, vc, r, gc)
    elif ctype == CType.RETRIEVED:
        # RETRIEVED: only verifiability ceiling (v1 bug was adding routing/grounding caps)
        vc = verifiability_ceiling(v, authority_ceiling)
        return min(declared, vc)
    elif ctype == CType.LENS:
        return min(declared, Tier.Wf)
    elif ctype == CType.GUESS:
        return Tier.Open
    else:
        # CLARIFY, CONSULTATION
        return Tier.Open


def test_differential_tiering():
    """final_tier() vs independent reference over the full enum product — zero disagreements."""
    disagreements = []
    declared = Tier.Th_coqc  # set high so other caps bind

    for ctype in CType:
        for v in Verifiability:
            for rc in RoutingCertainty:
                for g in Grounding:
                    cand = EvidenceCandidate(
                        content="x", ctype=ctype, provider_id="t",
                        provenance=Provenance(kind="ENGINE_CARD", verifiability=v),
                        declared_tier=declared, grounding=g,
                    )
                    got, _ = final_tier(cand, rc=rc, authority_ceiling=Tier.Dr)
                    expected = _ref_tier(ctype, v, rc, g, declared=declared, authority_ceiling=Tier.Dr)
                    if got != expected:
                        disagreements.append(
                            f"ctype={ctype} v={v} rc={rc} g={g}: got={got} expected={expected}"
                        )

    assert disagreements == [], "Tier algebra disagreements:\n" + "\n".join(disagreements)


# ---------------------------------------------------------------------------
# 2. A1_ceiling — verifiability ceiling caps tier
# ---------------------------------------------------------------------------

def test_A1_ceiling():
    """Candidate declares Th_coqc but SELF_CONSISTENT verifiability → capped at Dr."""
    cand = _make_cand(CType.COMPUTED, Verifiability.SELF_CONSISTENT, declared=Tier.Th_coqc)
    t, reason = final_tier(cand, rc=RoutingCertainty.SYMBOLIC)
    assert t <= Tier.Dr, f"Expected <= Dr, got {t}"
    assert t == verifiability_ceiling(Verifiability.SELF_CONSISTENT), \
        "Verifiability ceiling must be the binding cap"


# ---------------------------------------------------------------------------
# 3. A4_floor — routing_cap(DENSE_WEAK) = Wf creates the floor
# ---------------------------------------------------------------------------

def test_A4_floor():
    """COMPUTED with COQ_CHECKED + ALL grounding + DENSE_WEAK routing → floor = Wf."""
    cand = _make_cand(CType.COMPUTED, Verifiability.COQ_CHECKED,
                      declared=Tier.Th_coqc, grounding=Grounding.ALL)
    t, reason = final_tier(cand, rc=RoutingCertainty.DENSE_WEAK)
    # verifiability_ceiling(COQ_CHECKED)=Th_coqc, grounding_cap(ALL)=Th_coqc
    # routing_cap(DENSE_WEAK)=Wf → min = Wf
    assert t == Tier.Wf, f"Expected Wf, got {t}"
    assert reason == "routing"


# ---------------------------------------------------------------------------
# 4. A2_downgrade — unsupported RETRIEVED is suppressed (I3)
# ---------------------------------------------------------------------------

def test_A2_downgrade():
    """RETRIEVED candidate where support_check returns None must be suppressed in assemble()."""
    provider = _UnsupportedRagProvider()
    ctx = _make_ctx([provider])
    q = QueryIR(text="some query about retrieved content")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)

    # The unsupported RETRIEVED candidate must NOT be in the response
    retrieved_cands = [c for c in resp.candidates if c.ctype == CType.RETRIEVED]
    assert retrieved_cands == [], "Unsupported RETRIEVED must be suppressed (I3)"
    # But I4: response is non-empty
    assert len(resp.candidates) >= 1, "Response must not be empty (I4)"


# ---------------------------------------------------------------------------
# 5. R8_rag_reaches_Dr — supported peer-reviewed RETRIEVED emits at Dr
# ---------------------------------------------------------------------------

def test_R8_rag_reaches_Dr():
    """Grounded peer-reviewed chunk must emit at Dr (regression of v1 routing-cap bug)."""
    provider = _RetrievedProvider()
    ctx = _make_ctx([provider])
    q = QueryIR(text="peer reviewed query")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)

    retrieved = [c for c in resp.candidates if c.ctype == CType.RETRIEVED]
    assert retrieved, "RETRIEVED candidate must be present"
    assert retrieved[0].tier == Tier.Dr, (
        f"Peer-reviewed RETRIEVED must emit at Dr, got {retrieved[0].tier}"
    )


# ---------------------------------------------------------------------------
# 6. R7_static_not_emitted — verify() failure → Open, not static_ceiling
# ---------------------------------------------------------------------------

def test_R7_static_not_emitted():
    """independent_oracle card whose verify() FAILS → tier drops to Open, not finite_diagnostic."""
    provider = _FailingOracleProvider()
    ctx = _make_ctx([provider])
    q = QueryIR(text="any query")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)

    oracle_cands = [c for c in resp.candidates if c.provider_id == "failing_oracle"]
    assert oracle_cands, "Provider must produce a candidate"
    assert oracle_cands[0].tier == Tier.Open, (
        f"After verify() fail, tier must be Open, got {oracle_cands[0].tier}"
    )


# ---------------------------------------------------------------------------
# 7. A3_never_empty — provider crash + OOB → ≥1 candidate (I4)
# ---------------------------------------------------------------------------

def test_A3_never_empty():
    """OOB query with a throwing provider → response has >= 1 candidate (I4)."""
    provider = _ThrowingProvider()
    ctx = _make_ctx([provider])
    q = QueryIR(text="some out-of-bounds query")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)
    assert len(resp.candidates) >= 1, "I4: response must never be empty even when provider crashes"


# ---------------------------------------------------------------------------
# 8. I2_suppression — COMPUTED with Grounding.NONE suppressed
# ---------------------------------------------------------------------------

def test_I2_suppression():
    """Fully ungrounded COMPUTED candidate (grounding=NONE) must be suppressed (I2)."""
    provider = _UngroundedComputedProvider()
    ctx = _make_ctx([provider])
    q = QueryIR(text="ungrounded test")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)

    # No COMPUTED candidate from this provider should appear
    computed_from_provider = [
        c for c in resp.candidates
        if c.ctype == CType.COMPUTED and c.provider_id == "ungrounded_computed"
    ]
    assert computed_from_provider == [], "COMPUTED@Grounding.NONE must be suppressed (I2)"
    assert len(resp.candidates) >= 1, "I4: response still non-empty"


# ---------------------------------------------------------------------------
# 9. A5_high_stakes — weak assertive below tier_bar are dropped; CONSULTATION present
# ---------------------------------------------------------------------------

def test_A5_high_stakes():
    """HIGH stakes: COMPUTED@Wf and RETRIEVED@Dr both below finite_diagnostic → dropped.
    CONSULTATION must be present in result (I5)."""
    weak_computed = _WeakComputedProvider()
    weak_retrieved = _RetrievedProvider()  # emits at Dr=2 < finite_diagnostic=3

    cfg = Config(high_stakes_tier_bar=Tier.finite_diagnostic)
    ctx = _make_ctx([weak_computed, weak_retrieved], cfg=cfg)

    q = QueryIR(text="high stakes query", stakes=Stakes.HIGH)
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, cfg)

    assertive_in_result = [c for c in resp.candidates if c.ctype in ASSERTIVE]
    assert assertive_in_result == [], "Weak assertive candidates must be dropped in HIGH stakes (I5)"

    consultation_in_result = [c for c in resp.candidates if c.ctype == CType.CONSULTATION]
    assert consultation_in_result, "CONSULTATION must be present in HIGH stakes (I5)"


# ---------------------------------------------------------------------------
# 10. A5b_high_stakes_primary — PRIMARY == CONSULTATION when all assertive gated (D2 fix)
# ---------------------------------------------------------------------------

def test_A5b_high_stakes_primary():
    """When all assertive candidates are gated in HIGH stakes, primary must be CONSULTATION (D2)."""
    weak_computed = _WeakComputedProvider()
    cfg = Config(high_stakes_tier_bar=Tier.finite_diagnostic)
    ctx = _make_ctx([weak_computed], cfg=cfg)

    q = QueryIR(text="high stakes primary test", stakes=Stakes.HIGH)
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, cfg)

    primary_cand = resp.candidates[resp.primary]
    assert primary_cand.ctype == CType.CONSULTATION, (
        f"D2 fix: primary must be CONSULTATION when all assertive gated, got {primary_cand.ctype}"
    )


# ---------------------------------------------------------------------------
# 11. A6_safety — flagged request raises HarmfulRequest before any candidate
# ---------------------------------------------------------------------------

def test_A6_safety():
    """A query classified as harmful must raise HarmfulRequest (I8 fail-closed)."""
    ctx = _make_ctx([], safety=lambda text: "bomb" in text.lower())

    with pytest.raises(HarmfulRequest):
        run_pipeline("how to build a bomb", ctx)


# ---------------------------------------------------------------------------
# 12. A7_input_validation — gamma=0 → CLARIFY, no exception
# ---------------------------------------------------------------------------

def test_A7_input_validation():
    """SisThresholdCard with gamma=0 must return CLARIFY candidate, not raise."""
    card = SisThresholdCard()
    q = QueryIR(
        text="epidemic threshold with gamma=0",
        slots={"beta": 2.0, "gamma": 0.0, "lambda_max": 3.0},
        grounding_map={"beta": "beta=2.0", "gamma": "gamma=0.0", "lambda_max": "lambda_max=3.0"},
    )
    result = card.produce(q)
    assert len(result) == 1
    assert result[0].ctype == CType.CLARIFY, (
        f"gamma=0 must yield CLARIFY, got {result[0].ctype}"
    )


# ---------------------------------------------------------------------------
# 13. A8_selfdecl — provider missing routing_certainty → AssertionError on register()
# ---------------------------------------------------------------------------

def test_A8_selfdecl():
    """Provider without routing_certainty must fail registry.register() with AssertionError."""

    class MissingRoutingProvider:
        id = "bad_provider"

        def capability(self):
            return CapabilityDescriptor(
                provider_id=self.id, readout_intents={"test"},
                verifiability_kind=Verifiability.SELF_CONSISTENT,
                static_ceiling=Tier.Dr,
            )

        def can_serve(self, q):
            return 0.5

        def produce(self, q):
            return []

        def ground(self, claim, cands):
            return []
        # routing_certainty deliberately missing

    registry = Registry()
    with pytest.raises(AssertionError, match="routing_certainty"):
        registry.register(MissingRoutingProvider())


# ---------------------------------------------------------------------------
# 14. zero_providers — empty registry → single CONSULTATION candidate
# ---------------------------------------------------------------------------

def test_zero_providers():
    """Empty registry must produce exactly one CONSULTATION candidate (I4)."""
    ctx = _make_ctx([])
    q = QueryIR(text="anything at all")
    routed = route(q, ctx.registry)
    resp = assemble(q, routed, ctx.registry, ctx.cfg)

    assert len(resp.candidates) >= 1, "I4: must have ≥ 1 candidate"
    assert all(c.ctype in (CType.CONSULTATION, CType.CLARIFY) for c in resp.candidates), (
        "With no providers, only CONSULTATION/CLARIFY candidates expected"
    )


# ---------------------------------------------------------------------------
# 15. primary_order — COMPUTED wins over RETRIEVED when tiers are equal
# ---------------------------------------------------------------------------

def test_primary_order():
    """With equal tiers, COMPUTED outranks RETRIEVED in pick_primary order dict."""
    from pgcross.pipeline.lens import pick_primary

    computed_cand = EvidenceCandidate(
        content="computed", ctype=CType.COMPUTED, provider_id="c",
        provenance=Provenance(kind="ENGINE_CARD", verifiability=Verifiability.SELF_CONSISTENT),
        declared_tier=Tier.Dr, tier=Tier.Dr, grounding=Grounding.ALL,
    )
    retrieved_cand = EvidenceCandidate(
        content="retrieved", ctype=CType.RETRIEVED, provider_id="r",
        provenance=Provenance(kind="RAG_CHUNK", verifiability=Verifiability.SOURCE_ATTRIBUTED),
        declared_tier=Tier.Dr, tier=Tier.Dr,
    )

    cands = [retrieved_cand, computed_cand]  # RETRIEVED first in list
    primary_idx = pick_primary(cands)
    assert cands[primary_idx].ctype == CType.COMPUTED, (
        f"COMPUTED must outrank RETRIEVED at equal tiers; primary was {cands[primary_idx].ctype}"
    )


# ---------------------------------------------------------------------------
# 16. F1_serving — assert_serving_ready fail-closed
# ---------------------------------------------------------------------------

def test_F1_serving():
    """assert_serving_ready raises RuntimeError without safety; passes with allow_unsafe_dev."""
    ctx_no_safety = Ctx(backend=None, registry=Registry(), cfg=Config(), safety=None)

    with pytest.raises(RuntimeError, match="safety"):
        assert_serving_ready(ctx_no_safety)

    # Must NOT raise with the dev escape hatch
    assert_serving_ready(ctx_no_safety, allow_unsafe_dev=True)


# ---------------------------------------------------------------------------
# 17. D1_disclosure — PARTIAL-grounded COMPUTED render() contains assumption disclosure
# ---------------------------------------------------------------------------

def test_D1_disclosure():
    """SisThresholdCard produce() with PARTIAL grounding (lambda_max not in grounding_map)
    must include a disclosure string ('assuming'/'provide'/'missing') in the candidate content."""
    card = SisThresholdCard()
    # All slots present (so not CLARIFY), but lambda_max NOT in grounding_map → PARTIAL
    q = QueryIR(
        text="epidemic query",
        slots={"beta": 2.0, "gamma": 0.5, "lambda_max": 3.0},
        grounding_map={"beta": "beta=2.0", "gamma": "gamma=0.5"},
        # lambda_max deliberately absent from grounding_map
    )
    result = card.produce(q)
    assert len(result) == 1
    assert result[0].ctype == CType.COMPUTED, f"Expected COMPUTED, got {result[0].ctype}"
    assert result[0].grounding == Grounding.PARTIAL, "Expected PARTIAL grounding"

    content = result[0].content.lower()
    assert any(word in content for word in ("assuming", "provide", "missing")), (
        f"D1: PARTIAL-grounded candidate must disclose assumption. Content: {result[0].content!r}"
    )


# ---------------------------------------------------------------------------
# 18-21. SIR + HIT disambiguation (v0.2.0)
# ---------------------------------------------------------------------------
import math as _math, re as _re
from pgcross.providers.cards.sir_wellmixed import SirWellMixedCard
from pgcross.providers.cards.herd_immunity import HerdImmunityCard
from pgcross.safety import make_dev_safety
from pgcross.policy.stakes import classify_stakes


def _make_full_ctx():
    """Context with all three engine cards registered."""
    reg = Registry()
    reg.register(SisThresholdCard())
    reg.register(SirWellMixedCard())
    reg.register(HerdImmunityCard())
    return Ctx(backend=None, registry=reg, cfg=Config(),
               stakes_policy=classify_stakes, safety=make_dev_safety())


def _r0_from(content: str) -> float | None:
    m = _re.search(r"R0\s*=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)", content)
    return float(m.group(1)) if m else None


def test_disambiguation_both_computed_present():
    """When beta+gamma+lambda_max all present, SIS AND SIR both emit COMPUTED@Th_coqc."""
    ctx = _make_full_ctx()
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=3.0. Epidemic threshold?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    pids = {c.provider_id for c in computed}
    assert "sis_threshold" in pids, f"SIS missing from {pids}"
    assert "sir_wellmixed" in pids, f"SIR missing from {pids}"
    for c in computed:
        assert c.tier == Tier.Th_coqc, f"{c.provider_id} tier={c.tier.name}"


def test_disambiguation_different_R0_and_assumptions():
    """SIS and SIR must produce different R0 values and declare their model assumptions."""
    ctx = _make_full_ctx()
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=3.0. Epidemic threshold?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    sis = next(c for c in computed if c.provider_id == "sis_threshold")
    sir = next(c for c in computed if c.provider_id == "sir_wellmixed")
    # R0 values must differ: SIS=9.0 (0.3*3/0.1), SIR=3.0 (0.3/0.1)
    r0_sis, r0_sir = _r0_from(sis.content), _r0_from(sir.content)
    assert r0_sis is not None and r0_sir is not None
    assert not _math.isclose(r0_sis, r0_sir, rel_tol=0.01), \
        f"SIS R0={r0_sis} and SIR R0={r0_sir} must differ"
    # SIS declares network assumption
    assert any(k in sis.content.lower() for k in ("network","λmax","lambda")), \
        f"SIS must declare network assumption. Content: {sis.content!r}"
    # SIR declares well-mixed assumption
    assert any(k in sir.content.lower() for k in ("well-mixed","homogeneous")), \
        f"SIR must declare well-mixed assumption. Content: {sir.content!r}"


def test_sir_fires_with_two_params_only():
    """SIR fires on beta+gamma alone (no lambda_max); SIS must NOT emit COMPUTED."""
    ctx = _make_full_ctx()
    resp = run_pipeline("beta=0.4, gamma=0.2. What is R0?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    sir_cands = [c for c in computed if c.provider_id == "sir_wellmixed"]
    sis_cands = [c for c in computed if c.provider_id == "sis_threshold"]
    assert sir_cands, "SIR must fire with just beta+gamma"
    assert not sis_cands, "SIS must NOT emit COMPUTED without lambda_max"
    r0 = _r0_from(sir_cands[0].content)
    assert r0 is not None and _math.isclose(r0, 2.0, rel_tol=1e-3), f"R0 should be 2.0, got {r0}"


def test_hit_valid_R0():
    """HIT card computes 1-1/R0 correctly for R0=3."""
    ctx = _make_full_ctx()
    resp = run_pipeline("R0=3.0. What is the herd immunity threshold?", ctx)
    hit_cands = [c for c in resp.candidates
                 if c.ctype == CType.COMPUTED and c.provider_id == "herd_immunity"]
    assert hit_cands, "HIT card must fire when R0 slot present"
    content = hit_cands[0].content
    # HIT = 1 - 1/3 = 0.6667; check either decimal or percentage form
    assert "0.667" in content or "66.7" in content or "66.6" in content, \
        f"HIT value not found in: {content!r}"


def test_hit_refuses_subthreshold_R0():
    """HIT must NOT emit COMPUTED when R0 <= 1 (validate() raises, produce() returns CLARIFY)."""
    ctx = _make_full_ctx()
    resp = run_pipeline("R0=0.8. Calculate herd immunity threshold.", ctx)
    hit_computed = [c for c in resp.candidates
                    if c.provider_id == "herd_immunity" and c.ctype == CType.COMPUTED]
    assert not hit_computed, "HIT must not compute when R0 <= 1"
    assert len(resp.candidates) >= 1, "I4: response must still be non-empty"


# ---------------------------------------------------------------------------
# 22-25. NetworkCentralityCard (K6 track 1 — InfoDomains R2 card)
# ---------------------------------------------------------------------------
from pgcross.providers.cards.network_centrality import NetworkCentralityCard


def _make_full_ctx_with_centrality():
    """Context with all four engine cards registered (SIS/SIR/HIT + network centrality)."""
    reg = Registry()
    reg.register(SisThresholdCard())
    reg.register(SirWellMixedCard())
    reg.register(HerdImmunityCard())
    reg.register(NetworkCentralityCard())
    return Ctx(backend=None, registry=reg, cfg=Config(),
               stakes_policy=classify_stakes, safety=make_dev_safety())


def test_network_centrality_fires_on_keyword_plus_lambda_max():
    """Card fires only when BOTH a centrality keyword AND lambda_max are present."""
    ctx = _make_full_ctx_with_centrality()
    resp = run_pipeline("Network spectral radius (dominant eigenvalue) is 4.0. "
                         "What is the network centrality?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    nc = [c for c in computed if c.provider_id == "network_centrality"]
    assert nc, "NetworkCentralityCard must fire on centrality keyword + lambda_max"
    assert nc[0].tier == Tier.Th_coqc, f"tier={nc[0].tier.name} (want Th_coqc, coq_checked)"
    assert "4" in nc[0].content


def test_network_centrality_silent_without_keyword():
    """Card must NOT fire on a bare epidemic question even with lambda_max present —
    it requires the centrality/PageRank framing, not just the slot (I1: no silent scope creep)."""
    ctx = _make_full_ctx_with_centrality()
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=3.0. Epidemic threshold?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    pids = {c.provider_id for c in computed}
    assert "sis_threshold" in pids, f"SIS missing from {pids}"
    assert "network_centrality" not in pids, \
        "NetworkCentralityCard must not fire without a centrality/PageRank framing"


def test_network_centrality_disambiguates_from_sis():
    """When both SIS and centrality framing are present, both fire, reading the SAME
    lambda_max value under different domain names (no new math, just the InfoDomains card)."""
    ctx = _make_full_ctx_with_centrality()
    resp = run_pipeline(
        "beta=0.2, gamma=0.1, network spectral radius is 5.0. "
        "Is this above the epidemic threshold, and what is the network centrality?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    pids = {c.provider_id for c in computed}
    assert "sis_threshold" in pids and "network_centrality" in pids, f"got {pids}"
    nc = next(c for c in computed if c.provider_id == "network_centrality")
    assert "5" in nc.content
    assert "r2" in nc.content.lower() or "spectrum" in nc.content.lower(), \
        f"card must declare its readout family. Content: {nc.content!r}"


def test_network_centrality_missing_slot_clarifies():
    """No lambda_max in text/slots -> CLARIFY, never a crash (I4 never-empty)."""
    ctx = _make_full_ctx_with_centrality()
    resp = run_pipeline("What is the network centrality?", ctx)
    computed = [c for c in resp.candidates
                if c.provider_id == "network_centrality" and c.ctype == CType.COMPUTED]
    assert not computed, "must not compute without lambda_max"
    assert len(resp.candidates) >= 1, "I4: response must still be non-empty"


# ---------------------------------------------------------------------------
# 26-28. LiveDataProvider (K6 track 2b — new LIVE_LOOKUP provider kind)
# ---------------------------------------------------------------------------
from pgcross.providers.live.base import LiveDataProvider


class _FakeLiveProvider(LiveDataProvider):
    """Deterministic stand-in for a real LiveDataProvider — no network in tests."""
    id = "live:fake"

    def __init__(self, value=42.0, fail=False):
        super().__init__()
        self._value, self._fail = value, fail

    def _keys(self):
        return {"widget_price": ["widget price", "price of a widget"]}

    def _fetch(self, key):
        if self._fail:
            raise RuntimeError("network down")
        return {"value": self._value, "unit": "usd", "description": "test widget price",
                "url": "https://example.test", "retrieved_at": "2026-07-01T00:00:00+00:00"}


def test_live_provider_produces_candidate_on_key_match():
    p = _FakeLiveProvider(value=7.5)
    q = QueryIR(text="What is the widget price today?")
    cands = p.produce(q)
    assert len(cands) == 1
    c = cands[0]
    assert c.provenance.kind == "LIVE_LOOKUP", "must be LIVE_LOOKUP, not BOUNDARY_LOOKUP"
    assert "live:widget_price@2026-07-01T00:00:00+00:00" == c.provenance.source_ref, \
        "staleness must be embedded in source_ref (no core Provenance field added)"
    assert "7.5" in c.content


def test_live_provider_silent_on_no_key_match():
    p = _FakeLiveProvider()
    q = QueryIR(text="What is the epidemic threshold?")
    assert p.produce(q) == [], "must not fire on unrelated queries"
    assert p.can_serve(q) == 0.0


def test_live_provider_fail_closed_no_candidate_no_crash():
    """I8 fail-closed: a failed fetch with no prior cache -> no candidate, never a raise."""
    p = _FakeLiveProvider(fail=True)
    q = QueryIR(text="What is the widget price today?")
    cands = p.produce(q)  # must not raise
    assert cands == [], "a failed fetch with nothing cached must produce nothing, not a guess"


# ---------------------------------------------------------------------------
# 30-33. Composition layer (pipeline/compose.py) — SIS -> HerdImmunity engine-to-engine
# ---------------------------------------------------------------------------
from pgcross.pipeline.compose import compose, MAX_HOPS
from pgcross.providers.cards.base import EngineCardProvider


def _make_full_ctx_with_hit():
    """SIS + SIR + HIT, same registry as the disambiguation block above."""
    reg = Registry()
    reg.register(SisThresholdCard())
    reg.register(SirWellMixedCard())
    reg.register(HerdImmunityCard())
    return Ctx(backend=None, registry=reg, cfg=Config(),
               stakes_policy=classify_stakes, safety=make_dev_safety())


def test_compose_sis_feeds_herd_immunity():
    """Concrete target case: no 'R0' token anywhere in the raw text. SIS computes
    R0=beta*lambda_max/gamma=15.0 internally; the composition layer must expose that as a
    slot so HerdImmunityCard ALSO fires, computing HIT=1-1/15=0.9333, without the user ever
    typing R0."""
    ctx = _make_full_ctx_with_hit()
    text = "beta=0.3, gamma=0.1, lambda_max=5. What vaccination coverage is needed to stop this?"
    assert "r0" not in text.lower(), "sanity: raw text must not state R0 literally"
    resp = run_pipeline(text, ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    pids = {c.provider_id for c in computed}
    assert "sis_threshold" in pids, f"SIS missing from {pids}"
    assert "herd_immunity" in pids, f"HerdImmunity must fire via composed R0, got {pids}"
    hit = next(c for c in computed if c.provider_id == "herd_immunity")
    m = _re.search(r"threshold:\s*([0-9.]+)", hit.content)
    assert m is not None, f"HIT value not found in: {hit.content!r}"
    assert _math.isclose(float(m.group(1)), 1 - 1 / 15, rel_tol=1e-3), \
        f"HIT should be 1-1/15=0.9333, got {m.group(1)}"


def test_compose_no_regression_without_consumer_signal():
    """A query with NO composable-consumption reason present (no herd-immunity/vaccination
    framing) must behave EXACTLY as before composition existed: SIS/SIR fire, HerdImmunity
    stays silent, even though R0 is technically composable from SIS's output. Composition must
    never be a back door for scope creep (I1)."""
    ctx = _make_full_ctx_with_hit()
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=3.0. Epidemic threshold?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    pids = {c.provider_id for c in computed}
    assert "sis_threshold" in pids and "sir_wellmixed" in pids
    assert "herd_immunity" not in pids, (
        f"HerdImmunity must NOT fire on a query with no herd-immunity/vaccination signal, "
        f"even though R0 is composable; got {pids}"
    )


def test_compose_hop_cap_bounds_chain_depth():
    """Regression guard for the hop cap: a synthetic producer chain longer than MAX_HOPS must
    NOT fully resolve in one compose() call. This directly exercises the cap (not just the
    'no infinite loop' happy path) — if a future change removed the per-hop snapshot (letting
    a pass cascade through the whole chain) or removed the max_hops bound entirely, this test
    would start failing because slots beyond the permitted depth would appear."""
    assert MAX_HOPS == 1, "this test's assertions are calibrated to a 1-hop cap; update both together"

    class _ChainCard(EngineCardProvider):
        def __init__(self, id_, req, prod_key):
            self.id, self.required_slots, self.produces = id_, req, [prod_key]
            self._prod_key = prod_key
        def symbolic_match(self, q):
            # Always routed, independent of whether required_slots are present yet — models
            # a realistic consumer routing signal (e.g. a keyword match) so that composition,
            # not routing eligibility, is the thing under test here.
            return True
        def compute(self, slots):
            return {self._prod_key: 1.0}
        def render(self, val, q):
            return f"{self.id} computed"

    # p0 needs nothing, produces s1. p1 needs s1, produces s2. p2 needs s2, produces s3.
    # p3 needs s3 (final consumer, produces nothing further).
    p0 = _ChainCard("chain0", [], "s1")
    p1 = _ChainCard("chain1", ["s1"], "s2")
    p2 = _ChainCard("chain2", ["s2"], "s3")
    p3 = _ChainCard("chain3", ["s3"], "s4")
    reg = Registry()
    for p in (p0, p1, p2, p3):
        reg.register(p)
    q = QueryIR(text="chain test")
    q = compose(q, reg, route)
    # With a 1-hop cap: p0 fires (needs nothing) and produces s1 in hop 1. p1/p2/p3 all
    # required a slot that did not exist at hop-START, so none of them may fire this hop.
    assert "s1" in q.slots, "the first link (no prerequisites) must compose in hop 1"
    assert "s2" not in q.slots, (
        "s2 requires s1, which only became available DURING hop 1 — with the hop cap "
        "correctly enforced this must NOT resolve in the same compose() call"
    )
    assert "s3" not in q.slots and "s4" not in q.slots


def test_compose_provenance_distinguishable_from_grounding():
    """A composed slot must be recorded in QueryIR.composed_from (never in grounding_map),
    so downstream code — and a human auditor — can always tell 'read from text' apart from
    'derived by another card', per I7/I1 discipline."""
    ctx = _make_full_ctx_with_hit()
    text = "beta=0.3, gamma=0.1, lambda_max=5. What vaccination coverage is needed to stop this?"
    q = QueryIR(text=text)
    q.stakes = ctx.classify_stakes(text)
    q = ground(q, ctx.backend)
    assert "R0" not in q.grounding_map, "R0 must not be directly grounded from this text"
    q = compose(q, ctx.registry, route)
    assert q.slots.get("R0") is not None, "compose() must have populated R0"
    assert q.composed_from.get("R0") == "sis_threshold", (
        f"R0's provenance must be recorded as derived from sis_threshold, got {q.composed_from}"
    )
    assert "R0" not in q.grounding_map, (
        "a composed slot must never be written into grounding_map — that field is reserved "
        "for literal text-span provenance (I7); composed_from is the separate, distinguishable "
        "provenance channel for engine-to-engine derivation"
    )
    # And the resulting candidate must show the PARTIAL-grounding tier discipline (I1/I2):
    # a composed input caps the consuming card below Th_coqc even though it is coq_checked=True.
    resp = assemble(q, route(q, ctx.registry), ctx.registry, ctx.cfg)
    hit = next(c for c in resp.candidates if c.provider_id == "herd_immunity")
    assert hit.grounding == Grounding.PARTIAL
    assert hit.tier < Tier.Th_coqc, (
        f"a composed-R0 candidate must not silently inherit Th_coqc; got {hit.tier.name}"
    )


# ---------------------------------------------------------------------------
# 34-36. Composition generalized by readout_family + slot_aliases (cross-vocabulary)
# ---------------------------------------------------------------------------

class _FamilyCard(EngineCardProvider):
    """Synthetic stub proving the readout_family/slot_aliases mechanism generically —
    deliberately using DIFFERENT slot names for the same canonical quantity than any real
    card, so this test cannot pass via the (already-tested) exact-name path by accident."""
    def __init__(self, id_, required, produces_, family=None, aliases=None):
        self.id = id_
        self.required_slots = required
        self.produces = produces_
        self.readout_family = family
        self.slot_aliases = aliases or {}
    def symbolic_match(self, q):
        return True   # always routed — isolates composition from routing eligibility
    def compute(self, slots):
        return {k: 99.0 for k in self.produces}
    def render(self, val, q):
        return f"{self.id} fired"


def test_compose_cross_vocabulary_via_readout_family():
    """Two cards sharing a readout_family but using DIFFERENT slot names for the same
    quantity must still compose, via slot_aliases resolving the consumer's own name to the
    producer's canonical produced name."""
    producer = _FamilyCard("producer_r2", required=[], produces_=["lambda_max"], family="R2")
    consumer = _FamilyCard("consumer_r2", required=["spectral_radius"], produces_=[],
                            family="R2", aliases={"spectral_radius": "lambda_max"})
    reg = Registry()
    reg.register(producer)
    reg.register(consumer)
    q = QueryIR(text="cross-vocabulary test")
    q = compose(q, reg, route)
    assert q.slots.get("spectral_radius") == 99.0, (
        "consumer's own slot name must be populated from the producer's differently-named "
        "canonical output, via readout_family + slot_aliases"
    )
    assert q.composed_from.get("spectral_radius") == "producer_r2"


def test_compose_exact_name_match_ignores_family():
    """Same produced/needed key name, DIFFERENT readout_family — exact-name matching still
    applies regardless of family (that path never depended on family; family is an ADDITIONAL
    path for cross-vocabulary cases, not a restriction on the original exact-name one)."""
    producer = _FamilyCard("producer_r3", required=[], produces_=["value"], family="R3")
    consumer = _FamilyCard("consumer_r5", required=["value"], produces_=[], family="R5")
    reg = Registry()
    reg.register(producer)
    reg.register(consumer)
    q = QueryIR(text="family mismatch test")
    q = compose(q, reg, route)
    assert q.slots.get("value") == 99.0, (
        "exact-name matching must still work regardless of family (this was always true)"
    )


def test_compose_different_readout_family_blocks_cross_vocabulary_match():
    """DIFFERENT slot names AND different readout_family — must NOT compose. A shared name
    alone (via alias) is not sufficient without shared family; two unrelated domains whose
    aliases happen to resolve to the same canonical string must not silently cross-wire."""
    producer = _FamilyCard("producer_r3b", required=[], produces_=["lambda_max"], family="R3")
    consumer = _FamilyCard("consumer_r5b", required=["spectral_radius"], produces_=[],
                            family="R5", aliases={"spectral_radius": "lambda_max"})
    reg = Registry()
    reg.register(producer)
    reg.register(consumer)
    q = QueryIR(text="cross-family alias mismatch test")
    q = compose(q, reg, route)
    assert "spectral_radius" not in q.slots, (
        "differently-named slots must NOT compose across different readout_family values, "
        "even if their aliases happen to resolve to the same canonical name"
    )


# ---------------------------------------------------------------------------
# 37-40. imagine_bridge (pipeline/imagine.py) — speculative cross-domain layer
# ---------------------------------------------------------------------------
from pgcross.pipeline.imagine import imagine_bridge


class _StubBridgeBackend:
    """Deterministic stand-in for a real backend's propose_bridge — no model involved."""
    def __init__(self, guess=42.0, rationale="stub reasoning", fail=False):
        self._guess, self._rationale, self._fail = guess, rationale, fail
    def propose_bridge(self, p):
        from pgcross.backends.base import TransportOut
        if self._fail:
            raise RuntimeError("backend down")
        return TransportOut(json={"guess": self._guess, "rationale": self._rationale})


def test_imagine_bridge_produces_guess_for_missing_slot():
    reg = Registry()
    reg.register(HerdImmunityCard())  # requires R0, nothing grounds/composes it here
    q = QueryIR(text="What vaccination coverage is needed?")
    backend = _StubBridgeBackend(guess=7.5, rationale="analogy from a related domain")
    cands = imagine_bridge(q, reg, route, backend)
    assert len(cands) == 1
    c = cands[0]
    assert c.ctype == CType.GUESS
    assert c.declared_tier == Tier.Open
    assert c.provider_id == "imagine:bridge"
    assert "7.5" in c.content and "UNVERIFIED" in c.content
    assert "R0" not in q.slots, "imagine_bridge must NEVER inject into q.slots (unlike compose())"


def test_imagine_bridge_disabled_by_default_in_run_pipeline():
    """Config.enable_imagine_bridge defaults False — no behavior change unless opted in."""
    reg = Registry()
    reg.register(HerdImmunityCard())
    cfg = Config()
    assert cfg.enable_imagine_bridge is False
    ctx = Ctx(backend=_StubBridgeBackend(), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("What vaccination coverage is needed?", ctx)
    assert not any(c.provider_id == "imagine:bridge" for c in resp.candidates), (
        "imagine_bridge must not run when enable_imagine_bridge is False (the default)"
    )


def test_imagine_bridge_enabled_surfaces_guess_but_never_outranks_computed():
    """When enabled AND a real COMPUTED candidate exists, the guess must still surface (so it's
    visible) but must never become primary over a real answer (pick_primary ordering)."""
    reg = Registry()
    reg.register(SisThresholdCard())
    reg.register(HerdImmunityCard())
    cfg = Config(enable_imagine_bridge=True)
    ctx = Ctx(backend=_StubBridgeBackend(guess=3.0), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=5. Epidemic threshold?", ctx)
    computed = [c for c in resp.candidates if c.ctype == CType.COMPUTED]
    assert computed, "SIS must still fire normally"
    assert resp.candidates[resp.primary].ctype == CType.COMPUTED, (
        "primary must remain the real computed answer even with imagine enabled"
    )


def test_imagine_bridge_backend_failure_is_fail_closed():
    reg = Registry()
    reg.register(HerdImmunityCard())
    q = QueryIR(text="What vaccination coverage is needed?")
    cands = imagine_bridge(q, reg, route, _StubBridgeBackend(fail=True))
    assert cands == [], "a failing backend call must yield no candidates, never a raise"


def test_compose_no_family_no_cross_vocabulary_match():
    """Without a shared non-None readout_family, differently-named slots must NOT compose —
    proving family+alias is required for the cross-vocabulary path, not a fuzzy fallback."""
    producer = _FamilyCard("producer_none", required=[], produces_=["lambda_max"], family=None)
    consumer = _FamilyCard("consumer_none", required=["spectral_radius"], produces_=[],
                            family=None, aliases={"spectral_radius": "lambda_max"})
    reg = Registry()
    reg.register(producer)
    reg.register(consumer)
    q = QueryIR(text="no family test")
    q = compose(q, reg, route)
    assert "spectral_radius" not in q.slots, (
        "without readout_family set on both cards, cross-vocabulary composition must not fire"
    )


# ---------------------------------------------------------------------------
# 41-45. General-chat router fallback (pipeline/run.py) — the missing third path
# ---------------------------------------------------------------------------

class _StubChatBackend:
    """Deterministic stand-in for a real backend's general_chat — no model involved."""
    def __init__(self, reply="a plain chat reply", fail=False):
        self._reply, self._fail = reply, fail
    def general_chat(self, text):
        if self._fail:
            raise RuntimeError("backend down")
        return self._reply


def test_general_chat_fallback_disabled_by_default():
    reg = Registry()  # no cards at all — guarantees zero structured signal
    cfg = Config()
    assert cfg.enable_general_chat_fallback is False
    ctx = Ctx(backend=_StubChatBackend(), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("สวัสดี", ctx)
    assert not any(c.provider_id == "general_chat" for c in resp.candidates), (
        "must not fire when enable_general_chat_fallback is False (the default)"
    )
    assert resp.candidates[resp.primary].ctype == CType.CONSULTATION


def test_general_chat_fallback_fires_on_zero_signal_low_stakes():
    reg = Registry()  # no cards — genuinely nothing structured could ever fire
    cfg = Config(enable_general_chat_fallback=True)
    ctx = Ctx(backend=_StubChatBackend(reply="สวัสดีครับ!"), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("สวัสดี", ctx)
    primary = resp.candidates[resp.primary]
    assert primary.provider_id == "general_chat"
    assert primary.ctype == CType.GUESS
    assert primary.tier == Tier.Open
    assert primary.content == "สวัสดีครับ!"


def test_general_chat_fallback_never_overrides_real_computed_answer():
    reg = Registry()
    reg.register(SisThresholdCard())
    cfg = Config(enable_general_chat_fallback=True)
    ctx = Ctx(backend=_StubChatBackend(reply="a distracting chat reply"), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("beta=0.3, gamma=0.1, lambda_max=5. Epidemic threshold?", ctx)
    assert not any(c.provider_id == "general_chat" for c in resp.candidates), (
        "must not fire at all when a real COMPUTED candidate exists"
    )
    assert resp.candidates[resp.primary].ctype == CType.COMPUTED


def test_general_chat_fallback_never_overrides_high_stakes_refusal():
    """SAFETY-CRITICAL: a HIGH-stakes CONSULTATION is assemble.py's I5 gate refusing on
    purpose — the general-chat fallback must NEVER paper over that, no matter how it's
    configured. This is the single most important test in this block."""
    reg = Registry()  # zero cards: this alone would normally trigger the fallback...
    cfg = Config(enable_general_chat_fallback=True)
    ctx = Ctx(backend=_StubChatBackend(reply="a chat reply that must never appear"), registry=reg,
              cfg=cfg, stakes_policy=lambda text: Stakes.HIGH, safety=make_dev_safety())
    resp = run_pipeline("a query forced to HIGH stakes", ctx)
    assert not any(c.provider_id == "general_chat" for c in resp.candidates), (
        "must NEVER fire on HIGH stakes, even with zero structured signal and enabled=True"
    )
    assert resp.candidates[resp.primary].ctype == CType.CONSULTATION


def test_general_chat_fallback_backend_failure_is_fail_closed():
    reg = Registry()
    cfg = Config(enable_general_chat_fallback=True)
    ctx = Ctx(backend=_StubChatBackend(fail=True), registry=reg, cfg=cfg,
              stakes_policy=classify_stakes, safety=make_dev_safety())
    resp = run_pipeline("สวัสดี", ctx)  # must not raise
    assert not any(c.provider_id == "general_chat" for c in resp.candidates)
    assert resp.candidates[resp.primary].ctype == CType.CONSULTATION
