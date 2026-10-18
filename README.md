# Retail Ops Agents

An end-to-end **retail operations AI assistant** built like a real Forward
Deployed Engineer engagement: a retail chain runs stores and warehouses on
static BI while planners juggle stockouts, overstocks, returns abuse,
promotions, and supplier lead times by hand. This assistant answers planner
questions over live inventory telemetry, cites retail SOPs, factors external
demand signals, and gates high-impact actions behind human confirmation.

This is the second "enterprise problem statement" domain showcase, using the
same agentic spine as the cold-chain logistics repo: telemetry DB +
text-to-SQL + SOP RAG + external signal + ReAct orchestrator + escalation
gates + hash-chained audit -- plus a thin Streamlit demo UI.

## Problem -> Approach -> Outcome

- **Problem:** planners detect stockouts days late, returns abuse hides in
  reason codes, markdown decisions live in people's heads, supplier slippage
  is invisible until shelves go empty.
- **Approach:** a ReAct planner with three tools (governed text-to-SQL over
  read-only inventory views, TF-IDF RAG over 4 retail SOPs, external
  demand-signal feed), T1-T4 escalation tiers, and confirmation gates for
  purchase orders above $5,000 and every markdown. Every step is audit-logged
  in a hash-chained ledger.
- **Outcome:** cited answers to questions like *"which SKUs will stock out
  before the next delivery?"*, abuse flags with thresholds from SOP-01, and
  gated high-impact actions -- demonstrated in the Streamlit demo.

## Modules

| Module | Role |
|---|---|
| `retail/inventory.py` | Synthetic SQLite telemetry: stores, SKUs, inventory, sales, returns, suppliers, promotions, warehouses (seeded, deterministic anchors) |
| `retail/views.py` | Least-privilege gateway: 4 read-only views, SELECT-only with cited rule IDs, auto LIMIT cap |
| `retail/text2sql.py` | Rule-based NL->SQL: 5 intents, guardrails, one simplified retry then escalation |
| `retail/sop_rag.py` | Hand-rolled TF-IDF RAG over `docs/sops/`; cited answers; explicit not-found |
| `retail/demand.py` | Demand-signal client: deterministic fake + live HTTP stub; failures -> explicit gap, never hallucinated |
| `retail/orchestrator.py` | ReAct loop: reasoner, multi-intent fan-out, cited synthesis, tier + gate tokens, full audit |
| `retail/replenishment.py` | T1-T4 tiers + `ConfirmationGate` (request/approve/deny); POs > $5k and markdowns gated |
| `retail/audit.py` | SHA-256 hash-chained immutable log with `verify_chain()` |
| `retail/demo_helpers.py` | Stdlib-only presentation helpers for the demo (unit-tested) |
| `demo/app.py` | Thin Streamlit UI: ask questions, approve/deny gates, view audit trail |

## Quickstart

```bash
python -m pytest tests/ -q
python - <<'EOF'
from retail import inventory, views, orchestrator
conn = inventory.connect()
views.bootstrap(conn, seed=42)
agent = orchestrator.PlannerAgent(conn, "docs/sops")
result = agent.ask("Which SKUs are at risk of stockout, and what does the SOP say?")
print(result["answer"])
EOF
```

## Demo

```bash
pip install streamlit
streamlit run demo/app.py
```

The demo is a thin stateless shell: ask planner questions, see cited
answers, approve or deny pending confirmation gates, and inspect the audit
trail. All logic stays in `retail/` and is covered by the test suite
(`demo_helpers` is fully unit-tested; the demo itself needs no tests).

## Knowledge base

- [knowledge/fde-approach.md](knowledge/fde-approach.md) -- discovery notes:
  planner interviews, problem statements, HLD/LLD decisions.
- [knowledge/architecture.md](knowledge/architecture.md) -- Mermaid diagrams:
  legacy vs target, ReAct loop, demo UI layer, security model.
- [docs/sops/](docs/sops/) -- the 4 retail SOPs the RAG tool cites.

## Production path

| Demo | Production |
|---|---|
| SQLite telemetry | Real POS/ERP feeds (incremental ingest) |
| Hand-rolled TF-IDF | Managed RAG (Azure AI Search / Pinecone) |
| FakeDemand | Live demand/events feed with the same gap contract |
| In-process gate ledger | Durable workflow (Service Bus / Durable Functions) |
| Streamlit demo | AKS-hosted app, Entra ID auth, GitHub Actions deploy |

## Disclaimer

All data is synthetic and fictional. This is an independent portfolio
project, not affiliated with or endorsed by any retailer.
