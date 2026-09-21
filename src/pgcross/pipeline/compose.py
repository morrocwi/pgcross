# compose.py — deterministic card-to-card slot composition.
#
# PROBLEM THIS SOLVES: EngineCardProvider subclasses only ever read from QueryIR.slots,
# which is populated exclusively by ground()'s regex extraction over the raw user text
# (pipeline/ground.py). Two cards can read the SAME grounded slot in parallel (e.g. SIS and
# NetworkCentrality both read "lambda_max"), but one card's COMPUTED *output* could never
# become another card's input — e.g. SisThresholdCard computes R0 = beta*lambda_max/gamma
# internally, but HerdImmunityCard (which requires "R0") could only fire if the user typed
# "R0" literally in the query text.
#
# WHY THIS IS NOT "MycoRAG multi-hop reasoning" (do not conflate the two):
# MycoRAG's refutation chain is about a small LLM chaining its own UNCERTAIN natural-language
# inferences — each hop can silently introduce or compound error, and there is no way to audit
# a hop's correctness other than re-running the same unreliable LLM. Composition here is the
# opposite: every hop is a call into another registered EngineCardProvider's own validate()+
# compute() — the exact same deterministic function that would run if that card fired directly
# off grounded text. There is no new inference logic, no LLM in the loop, and no uncertainty
# introduced by the act of composing (the composed value is bit-for-bit identical to what the
# producing card would have emitted as its own COMPUTED candidate). The real risks here are
# engineering risks, not reasoning-ceiling risks:
#   (1) unbounded/circular composition graphs (a bug, not a reasoning failure)  -> MAX_HOPS cap.
#   (2) tier laundering: a value that passed through another card must not silently inherit
#       the HIGHER tier of a directly-grounded value (I1/I2 discipline)         -> see below.
#
# HOW A CARD DECLARES PARTICIPATION:
#   - CONSUME: a card already declares what it needs via `required_slots` (no new mechanism —
#     if a slot it requires shows up in q.slots, composed or not, it can fire, exactly as today).
#   - PRODUCE: a card opts in to being a composable slot *source* by declaring a NEW class
#     attribute `produces: list[str]` (see providers/cards/base.py) — an explicit allow-list of
#     which of its own `compute()` output-dict keys may be exported as a slot for other cards.
#     A card that does not declare `produces` (the default is []) can never feed another card,
#     even if its `compute()` dict happens to contain a same-named key — this is a deliberate,
#     explicit opt-in (no accidental leakage of internal computation keys).
#
# GENERALIZING ACROSS VOCABULARY — readout_family + slot_aliases:
#   The mechanism above only matches an EXACT slot name (producer's `produces` key == consumer's
#   `required_slots` name). That is narrow: it only lets two cards compose if whoever wrote them
#   happened to use the identical Python string for the same quantity. Per
#   research_universal_solver's InterpretationCards philosophy ("one operator, many domains as
#   readout cards" — a private sibling repo, internal docs not included here), two cards can share the SAME
#   underlying readout (e.g. R2 = spectrum/eigenvalue) while using DIFFERENT domain vocabulary for
#   the quantity (e.g. "lambda_max" vs "spectral_radius"). To compose across that vocabulary gap
#   without hand-wiring every pair, a card may ALSO declare:
#     - `readout_family: str | None` — which shared readout (R0-R6) its math instantiates.
#     - `slot_aliases: dict[str, str]` — its OWN required_slot name -> the canonical quantity name
#       used across that family (defaults to the slot's own name if not aliased).
#   A producer's value for canonical name P becomes available to a consumer's required slot S
#   whenever EITHER: (a) S == P directly (the original, simplest path — always tried first), OR
#   (b) both cards declare the SAME non-None readout_family AND the consumer's alias for S equals
#   P. This still requires an explicit, deliberate declaration on both sides (readout_family +,
#   where names differ, slot_aliases) — nothing is inferred or fuzzy-matched by string similarity.
#
# HOW A COMPOSED SLOT IS REPRESENTED (QueryIR.composed_from, core/models.py):
#   q.slots[slot] = <value>            — same dict as directly-grounded slots (so existing
#                                         `required_slots not in q.slots` checks need no change).
#   q.composed_from[slot] = provider_id — NEW field, parallel to grounding_map but for
#                                         composition provenance. A slot appears in AT MOST ONE
#                                         of {grounding_map, composed_from} — grounding_map is
#                                         only ever written by ground() from literal text spans
#                                         (I7); composed_from is only ever written here, from
#                                         another card's verified compute() output. This keeps
#                                         "read from text" and "derived by another card"
#                                         distinguishable downstream (grounding/audit trail).
#
# HOW TIER/GROUNDING DISCIPLINE IS PRESERVED (no free lunch, I1/I2-style):
#   EngineCardProvider._grounding_status() (base.py) marks a required slot "ungrounded" for
#   ceiling purposes whenever it has NO entry in q.grounding_map — composed slots deliberately
#   have NO grounding_map entry (they live in composed_from instead), so a card firing on a
#   composed input is *automatically* capped at Grounding.PARTIAL, never Grounding.ALL, and can
#   therefore never reach Tier.Th_coqc via final_tier()'s grounding_cap (tiering.py) — even if
#   the card is coq_checked=True and every OTHER required slot is directly grounded. This is
#   enforced by REUSE of the existing grounding_cap floor, not a new special case: no tier code
#   had to change for this guarantee to hold.
#
# HOP CAP: exactly ONE hop (MAX_HOPS = 1). Chosen deliberately conservative: the one concrete
# case this ships to solve (SIS -> HerdImmunity) is a single hop, and a hard cap of 1 makes any
# multi-hop chain (composed-from-a-composed-value) structurally impossible rather than merely
# improbable — if a future case needs depth 2, that is a deliberate, reviewed bump of one
# constant, not an emergent property of the loop. The loop is ALSO progress-bounded internally
# (stops as soon as a full pass injects nothing new), so raising MAX_HOPS later still cannot
# spin forever on a circular producer graph.
from __future__ import annotations
from ..core.models import QueryIR

MAX_HOPS = 1


def compose(q: QueryIR, registry, route_fn, max_hops: int | None = None) -> QueryIR:
    """Fill missing required_slots on already-ROUTED cards from other already-ROUTED cards'
    declared `produces` outputs, for up to `max_hops` passes (module default MAX_HOPS).

    Restricting both producer and consumer to providers that `route_fn` already selected for
    this query (i.e. cards whose OWN routing signal — keyword/symbolic match independent of the
    slot being composed — already made them relevant) is what prevents composition from being a
    back door for scope creep: a card that has no textual/slot reason at all to consider this
    query never gets a chance to receive a composed slot and start firing (see conformance test
    `test_compose_no_scope_creep_without_consumer_signal`).
    """
    if max_hops is None:
        max_hops = MAX_HOPS
    providers = registry.all()
    by_id = {p.id: p for p in providers}

    for _ in range(max_hops):
        routed = route_fn(q, registry)
        routed_ids = [r.provider_id for r in routed if r.provider_id in by_id]

        needed: set[str] = set()
        for pid in routed_ids:
            p = by_id[pid]
            for s in getattr(p, "required_slots", []):
                if s not in q.slots:
                    needed.add(s)
        if not needed:
            break

        # Snapshot slots as of the START of this hop. Producers may only fire off slots that
        # were already present BEFORE this hop began — never off a slot another producer just
        # added in this same pass. Without this snapshot, a chain of producers registered in a
        # convenient order could cascade fully within a single "hop" (e.g. P0->s1, then P1
        # immediately reading the freshly-added s1 in the same pass), silently defeating the
        # MAX_HOPS cap. This is exactly what `test_compose_hop_cap_bounds_chain_depth` checks.
        hop_start_slots = set(q.slots)
        additions: dict[str, tuple] = {}   # slot -> (value, provider_id), applied after the pass

        for pid in routed_ids:
            p = by_id[pid]
            produces = getattr(p, "produces", [])
            if not produces:
                continue
            required = getattr(p, "required_slots", [])
            if not all(s in hop_start_slots for s in required):
                continue  # producer itself could not fire at hop-start — nothing to compose from
            p_family = getattr(p, "readout_family", None)

            # Which of THIS producer's canonical output keys are actually wanted right now —
            # by exact name (any consumer's `needed` slot literally equals a produced key), or
            # by same-family alias (some OTHER routed consumer's required slot, resolved through
            # its own slot_aliases, equals a produced key, and both cards share a non-None family).
            offer = set()
            for slot in produces:
                if slot in needed:
                    offer.add(slot)        # exact-name path — unchanged original behavior
                    continue
                if p_family is None:
                    continue
                for cid in routed_ids:
                    if cid == pid:
                        continue
                    c = by_id[cid]
                    if getattr(c, "readout_family", None) != p_family:
                        continue
                    for s in getattr(c, "required_slots", []):
                        if s in needed and getattr(c, "slot_aliases", {}).get(s, s) == slot:
                            offer.add(slot)
                            break
            if not offer:
                continue
            try:
                p.validate(q.slots)
                val = p.compute(q.slots)
            except Exception:
                continue  # producer would itself CLARIFY/refuse — do not propagate garbage
            for slot in offer:
                if slot not in val:
                    continue
                # Deliver the value under EVERY needed name it satisfies (its own canonical name
                # if a consumer needed it directly, and/or each consumer's own aliased slot name)
                # so each consuming card can read it under the name IT expects, unchanged.
                targets = {slot} if slot in needed else set()
                if p_family is not None:
                    for cid in routed_ids:
                        c = by_id[cid]
                        if getattr(c, "readout_family", None) != p_family:
                            continue
                        for s in getattr(c, "required_slots", []):
                            if s in needed and getattr(c, "slot_aliases", {}).get(s, s) == slot:
                                targets.add(s)
                for t in targets:
                    if t not in additions:
                        additions[t] = (val[slot], pid)

        if not additions:
            break
        for slot, (value, pid) in additions.items():
            q.slots[slot] = value
            q.composed_from[slot] = pid
    return q
