"""Escalation tiers (T1-T4) and human confirmation gates.

Tiers mirror docs/sops/sop-03-stockout-escalation.md. High-impact actions --
purchase orders above PO_GATE_THRESHOLD and every markdown -- are gated: the
planner mints a gate token and a human must approve/deny before execution.
"""

PO_GATE_THRESHOLD = 5000.0


def assess_tier(stockout_rows=(), returns_rows=()):
    """Worst-case tier across stockout and returns-abuse signals."""
    covers = [r["days_of_cover"] for r in stockout_rows
              if r.get("days_of_cover") is not None]
    if covers and min(covers) <= 2:
        return "T4"
    if covers and min(covers) <= 7:
        return "T3"
    worst_suspicious = max(
        (r.get("suspicious_events", 0) for r in returns_rows), default=0
    )
    if worst_suspicious >= 10:
        return "T3"
    if stockout_rows or returns_rows:
        return "T2"
    return "T1"


class ConfirmationGate:
    """In-memory approve/deny ledger for high-impact actions."""

    def __init__(self):
        self._pending = {}
        self._decided = {}
        self._seq = 0

    @staticmethod
    def requires_gate(action_type, value=0.0):
        if action_type == "purchase_order":
            return value > PO_GATE_THRESHOLD
        if action_type == "markdown":
            return True
        return False

    def request(self, action_type, summary, payload=None):
        self._seq += 1
        token = f"GATE-{self._seq:04d}"
        self._pending[token] = {
            "token": token,
            "action": action_type,
            "summary": summary,
            "payload": payload or {},
            "status": "pending",
        }
        return token

    def approve(self, token):
        return self._decide(token, "approved")

    def deny(self, token, reason=""):
        return self._decide(token, "denied", reason)

    def _decide(self, token, status, reason=""):
        if token not in self._pending:
            raise KeyError(f"unknown or already-decided gate token: {token}")
        record = self._pending.pop(token)
        record["status"] = status
        record["reason"] = reason
        self._decided[token] = record
        return record

    def pending(self):
        return [dict(v) for v in self._pending.values()]

    def decided(self):
        return [dict(v) for v in self._decided.values()]

    def get(self, token):
        if token in self._pending:
            return dict(self._pending[token])
        return dict(self._decided.get(token, {})) or None
