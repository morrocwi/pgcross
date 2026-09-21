"""LiveFxRateProvider — concrete LiveDataProvider example: USD/THB exchange rate.

Two independent, free, no-API-key sources (Phase A / internal task-tracking notes open risk: relying on a
single unauthenticated third-party endpoint is a fragility risk once "live" becomes a
first-class provenance tier — this closes it with a second, structurally-independent
provider rather than a retry against the same one). Primary: open.er-api.com. Fallback:
frankfurter.app (ECB-sourced). Each is tried in turn; `_fetch` returns the first one that
succeeds. If BOTH fail, `_fetch` returns None like before — `LiveDataProvider._get()`'s
existing "serve stale over nothing" / I8 fail-closed discipline is unchanged, this only
reduces how often a single endpoint's outage empties the cache. Still opt-in only, never
registered by default ("cloud adapters stay opt-in optional, never required").
"""
from __future__ import annotations
import json
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from .base import LiveDataProvider

_PRIMARY_URL = "https://open.er-api.com/v6/latest/USD"
_FALLBACK_URL = "https://api.frankfurter.app/latest?from=USD&to=THB"
_UA = "pgcross-live-fx/0.1 (+https://github.com/morrocwi/pgcross)"


def _fetch_primary() -> Optional[float]:
    req = urllib.request.Request(_PRIMARY_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.load(r)
    if data.get("result") != "success":
        return None
    return data["rates"]["THB"]


def _fetch_fallback() -> Optional[float]:
    req = urllib.request.Request(_FALLBACK_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.load(r)
    rate = data.get("rates", {}).get("THB")
    return rate


class LiveFxRateProvider(LiveDataProvider):
    id = "live:fx_rate"

    def _keys(self) -> dict[str, list[str]]:
        return {
            "usd_thb": ["usd/thb", "usd to thb", "dollar to baht", "usd thb exchange rate"],
        }

    def _fetch(self, key: str) -> Optional[dict[str, Any]]:
        if key != "usd_thb":
            return None
        for fetch_fn, url in ((_fetch_primary, _PRIMARY_URL), (_fetch_fallback, _FALLBACK_URL)):
            try:
                rate = fetch_fn()
            except Exception:
                rate = None  # this source failed — try the next one, never raise past _fetch
            if rate is not None:
                return {
                    "value": rate,
                    "unit": "THB per USD",
                    "description": "Live USD to THB exchange rate",
                    "url": url,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
        return None  # both sources failed — I8 fail-closed, LiveDataProvider._get() handles this
