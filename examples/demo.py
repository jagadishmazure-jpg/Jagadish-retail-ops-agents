"""Planner questions against a synthetic retail chain (in-memory SQLite)."""
from pathlib import Path

from retail import inventory, orchestrator, views

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
