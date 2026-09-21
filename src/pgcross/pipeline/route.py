# route.py
from dataclasses import dataclass
from ..core.enums import RoutingCertainty
from ..core.models import QueryIR
from ..core.provider import Registry
MIN_ROUTE = 0.0
@dataclass
class RoutedProvider: provider_id: str; certainty: RoutingCertainty; score: float
def route(q: QueryIR, registry: Registry):
    out = [RoutedProvider(p.id, p.routing_certainty(q), p.can_serve(q))
           for p in registry.all() if p.can_serve(q) > MIN_ROUTE]
    return sorted(out, key=lambda r: r.score, reverse=True)
    # ▸ PROVE-IT routing: measure real accuracy; the argmax is not guaranteed correct.
