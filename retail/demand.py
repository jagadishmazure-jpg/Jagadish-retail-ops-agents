"""External demand-signal client (mirrors the weather-tool pattern).

``FakeDemand`` is deterministic and used in tests/demos. ``LiveDemandBackend``
fetches a local events/promotions feed over HTTP; any failure returns an
explicit gap result -- the planner reports the gap instead of hallucinating
demand.
"""

import hashlib
import json
import urllib.request

_DRIVERS = [
    "weekend uplift",
    "local event nearby",
    "promo halo",
    "seasonal trend",
    "payday week",
]


class FakeDemand:
    """Deterministic demand index in [0.5, 2.0] derived from store+sku."""

    def __init__(self, seed="retail-demand"):
        self.seed = seed

    def get_signal(self, store_id, sku):
        digest = hashlib.sha256(f"{self.seed}|{store_id}|{sku}".encode()).hexdigest()
        idx = 0.5 + (int(digest[:8], 16) % 150) / 100.0  # 0.50 .. 1.99
        drivers = [_DRIVERS[int(digest[i * 2:(i + 1) * 2], 16) % len(_DRIVERS)]
                   for i in range(8, 10)]
        return {
            "ok": True,
            "store_id": store_id,
            "sku": sku,
            "demand_index": round(idx, 2),
            "drivers": sorted(set(drivers)),
            "as_of_day": 90,
        }


class LiveDemandBackend:
    """HTTP feed stub. Configure with the real feed URL in production."""

    def __init__(self, url, timeout=5):
        self.url = url
        self.timeout = timeout

    def get_signal(self, store_id, sku):
        try:
            req = urllib.request.Request(
                f"{self.url}?store={store_id}&sku={sku}",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return {
                "ok": True,
                "store_id": store_id,
                "sku": sku,
                "demand_index": float(payload.get("demand_index", 1.0)),
                "drivers": list(payload.get("drivers", [])),
                "as_of_day": 90,
            }
        except Exception as exc:  # never let a feed outage become an answer
            return {
                "ok": False,
                "store_id": store_id,
                "sku": sku,
                "demand_index": None,
                "drivers": [],
                "gap": f"demand signal unavailable: {exc.__class__.__name__}",
            }
