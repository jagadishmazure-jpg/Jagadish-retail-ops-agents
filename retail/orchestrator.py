"""ReAct-style planner orchestrating inventory, SOP, and demand tools.

Loop: reason (detect intents, possibly several -> fan-out) -> act (run each
tool, audited) -> synthesize (cited answer + escalation tier + optional
confirmation-gate token for high-impact actions). Every step is audit-logged.
"""

import re

from . import audit as audit_mod
from . import demand as demand_mod
from . import replenishment as repl
from . import sop_rag, text2sql

_PO_RE = re.compile(r"purchase order|create (a )?po\b|raise (a )?po\b", re.I)
_MARKDOWN_RE = re.compile(r"\bmark\s*-?\s*down\b|markdown|clearance", re.I)


class PlannerAgent:
    def __init__(self, conn, sops_dir, demand_backend=None):
        self.conn = conn
        self.audit = audit_mod.AuditLog()
        self.gate = repl.ConfirmationGate()
        self.sops = sop_rag.SopIndex(sop_rag.load_chunks(sops_dir))
        self.demand = demand_backend or demand_mod.FakeDemand()

    # -- tool-facing helpers -------------------------------------------------
    def _tool_inventory(self, intent):
        result = text2sql.run(self.conn, intent)
        self.audit.record("planner", "tool.inventory", {
            "intent": intent, "sql": result["sql"], "rows": len(result["rows"]),
        })
        return result

    def _tool_sop(self, question):
        answer = self.sops.answer(question)
        self.audit.record("planner", "tool.sop", {
            "found": answer["found"], "citations": answer["citations"],
        })
        return answer

    def _tool_demand(self, store_id, sku):
        signal = self.demand.get_signal(store_id, sku)
        self.audit.record("planner", "tool.demand", {
            "store_id": store_id, "sku": sku,
            "ok": signal.get("ok"), "demand_index": signal.get("demand_index"),
        })
        return signal

    # -- main entry point ----------------------------------------------------
    def ask(self, question):
        self.audit.record("planner", "question_received", {"question": question})
        intents = text2sql.detect_intents(question)

        inventory_results, stockout_rows, returns_rows = {}, [], []
        for intent in intents:  # multi-intent fan-out
            try:
                result = self._tool_inventory(intent)
            except text2sql.EscalationNeeded:
                self.audit.record("planner", "inventory.escalated", {"intent": intent})
                continue
            inventory_results[intent] = result
            if intent == "stockout_risk":
                stockout_rows = result["rows"]
            if intent == "returns_abuse":
                returns_rows = result["rows"]

        sop_answer = self._tool_sop(question)

        demand_signal = None
        if stockout_rows:
            top = stockout_rows[0]
            demand_signal = self._tool_demand(top["store_id"], top["sku"])

        tier = repl.assess_tier(stockout_rows, returns_rows)

        gate_token = self._maybe_gate(question, stockout_rows)

        answer, citations = self._synthesize(
            question, intents, inventory_results, sop_answer, demand_signal,
            tier, gate_token,
        )
        self.audit.record("planner", "answer_synthesized", {
            "tier": tier, "gate_token": gate_token, "citations": citations,
        })
        return {
            "question": question,
            "intents": intents,
            "row_counts": {k: len(v["rows"]) for k, v in inventory_results.items()},
            "answer": answer,
            "citations": citations,
            "tier": tier,
            "gate_token": gate_token,
            "demand": demand_signal,
            "audit_events": len(self.audit.events()),
        }

    def _maybe_gate(self, question, stockout_rows):
        if _PO_RE.search(question) and stockout_rows:
            value = sum(
                max(0, r["reorder_point"] - r["on_hand"]) * (r.get("unit_cost") or 0)
                for r in stockout_rows
            )
            if repl.ConfirmationGate.requires_gate("purchase_order", value):
                token = self.gate.request(
                    "purchase_order",
                    f"Purchase order for {len(stockout_rows)} at-risk SKUs "
                    f"(est. ${value:,.2f})",
                    {"estimated_value": round(value, 2),
                     "lines": len(stockout_rows)},
                )
                self.audit.record("planner", "gate.requested",
                                  {"token": token, "value": round(value, 2)})
                return token
        if _MARKDOWN_RE.search(question):
            token = self.gate.request(
                "markdown", "Markdown action requested by planner",
                {"question": question},
            )
            self.audit.record("planner", "gate.requested", {"token": token})
            return token
        return None

    def _synthesize(self, question, intents, inventory_results, sop_answer,
                    demand_signal, tier, gate_token):
        lines, citations = [], []
        if not intents and not sop_answer["found"]:
            return ("I couldn't map that to an inventory question or a retail SOP. "
                    "Try asking about stockout risk, overstocks, returns, "
                    "promotions, or suppliers."), []
        for intent, result in inventory_results.items():
            lines.append(f"[{intent}] {len(result['rows'])} row(s) from governed views.")
            if intent == "stockout_risk" and result["rows"]:
                worst = result["rows"][0]
                lines.append(
                    f"Worst cover: {worst['sku_name']} at {worst['store_name']} -- "
                    f"{worst['days_of_cover']} days of cover "
                    f"(supplier {worst['supplier_name']}, {worst['lead_time_days']}d lead)."
                )
            if intent == "returns_abuse" and result["rows"]:
                worst = result["rows"][0]
                lines.append(
                    f"Top flag: customer {worst['customer_id']} -- "
                    f"{worst['return_events']} returns, "
                    f"{worst['suspicious_events']} suspicious."
                )
        if sop_answer["found"]:
            lines.append(sop_answer["message"])
            for excerpt in sop_answer["excerpts"]:
                lines.append(f"- {excerpt['citation']}: {excerpt['text']}")
            citations.extend(sop_answer["citations"])
        if demand_signal:
            if demand_signal.get("ok"):
                lines.append(
                    f"Demand signal for {demand_signal['sku']} at "
                    f"{demand_signal['store_id']}: index "
                    f"{demand_signal['demand_index']} "
                    f"({', '.join(demand_signal['drivers'])})."
                )
            else:
                lines.append(
                    f"Demand signal gap: {demand_signal.get('gap')} -- "
                    "answered without external demand data."
                )
        lines.append(f"Escalation tier: {tier}.")
        if gate_token:
            lines.append(
                f"High-impact action gated behind human confirmation: {gate_token}. "
                "Approve or deny it in the demo before anything executes."
            )
        return "\n".join(lines), citations
