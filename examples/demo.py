"""Planner questions against a synthetic retail chain (in-memory SQLite)."""
from pathlib import Path

from retail import inventory, orchestrator, views
from retail.audit import AuditLog
from retail.feedback import capture_feedback, list_feedback

ROOT = Path(__file__).resolve().parent.parent
conn = inventory.connect()
views.bootstrap(conn, seed=42)
agent = orchestrator.PlannerAgent(conn, str(ROOT / "docs" / "sops"))

for q in ["Which SKUs are at risk of stockout, and what does the SOP say?",
          "Who is abusing our returns policy?",
          "What should we mark down?"]:
    r = agent.ask(q)
    print(f"> {q}\n{r['answer']}\n")

print("pending confirmation gates:", [(g["token"], g["action"]) for g in agent.gate.pending()])
print("audit chain intact:", agent.audit.verify_chain())

# Feedback capture: thumbs up/down into the same hash-chained audit log, emails, phones, SSNs and long numbers redacted.
fb_log = AuditLog()
capture_feedback(fb_log, session_id="s-demo", turn_id="t1", rating="up")
fb = capture_feedback(fb_log, session_id="s-demo", turn_id="t2", rating="down",
                      correction="stock count was off, call me on +1 555 010 2030")
print(f"Feedback: {len(list_feedback(fb_log))} entries, stored correction {fb['details']['correction']!r}, "
      f"redactions {fb['details']['pii_redactions']}, chain verifies: {fb_log.verify_chain()}")
