from .base import EngineCardProvider

def _cent(t):
    tl = t.lower()
    return any(k in tl for k in (
        "centrality", "pagerank", "page rank", "most connected", "most influential",
        "network connectivity", "how connected", "centralization",
    ))

class NetworkCentralityCard(EngineCardProvider):
    """R2 (spectrum) card: network centralization ≡ dominant eigenvalue of the adjacency
    matrix — the same lambda_max quantity SisThresholdCard uses for the epidemic threshold,
    read here under the centrality/PageRank framing instead.

    No new math: this instantiates the same already-proved R2 spectrum readout under a
    different domain name, per a private sibling repo's InterpretationCards pattern
    ("no new operator, no new proof of structure" — an internal formal-verification
    reference, not part of this package).
    coq_law_ref anchors this card's instance in the private sibling repo's formal-verification
    kernel (principal-eigenvector case); the general R2 law itself lives in the core spectral
    theorem, not here. The exact anchor string is an opaque `source_ref` value only — no code in
    this package parses its internal structure.

    Like SisThresholdCard, this card does not independently recompute lambda_max — the
    value is READ from the query (I7), not derived. independent_oracle stays False,
    honestly matching K4's existing posture on the other coq_checked-only cards.
    """
    id = "network_centrality"
    coq_checked = True
    coq_law_ref = "research_universal_solver:network_K3_principal"
    required_slots = ["lambda_max"]
    produces = ["lambda_max"]   # composition layer: this card's reading of lambda_max may feed
                                # another R2-family card that needs the same quantity under a
                                # different vocabulary (pipeline/compose.py slot_aliases)
    readout_family = "R2"   # spectrum readout — same family as SisThresholdCard (see that card's
                             # readout_family comment); the InterpretationCards table lists network
                             # centrality/PageRank as R2 too.

    def symbolic_match(self, q):
        return "lambda_max" in q.slots and _cent(q.text)

    def dense_score(self, q):
        return 0.4 if _cent(q.text) else 0.0

    def compute(self, slots):
        lam = float(slots["lambda_max"])
        return {"lambda_max": lam}

    def render(self, val, q):
        lam = val["lambda_max"]
        return (
            f"Network centralization (dominant eigenvalue) = {lam:.6g}. "
            f"[network: PageRank/centrality ≡ principal eigenvector of the adjacency "
            f"matrix, R2 spectrum readout; same λmax used for the SIS epidemic threshold]"
        )
