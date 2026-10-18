# Shared spine with the sibling repo

[Jagadish-coldchain-logistics-agents](https://github.com/jagadishmazure-jpg/Jagadish-coldchain-logistics-agents)
and [Jagadish-retail-ops-agents](https://github.com/jagadishmazure-jpg/Jagadish-retail-ops-agents)
use the same agent design, applied to two domains. I am stating the overlap
openly so nobody reads them as two unrelated systems.

## What is the same (the spine)

| Piece | coldchain | retail | Notes |
|---|---|---|---|
| Hash-chained audit log | `coldchain/audit.py` | `retail/audit.py` | Same idea; field names differ |
| Governed SQL views + read-only gateway | `coldchain/views.py` | `retail/views.py` | One SELECT, allowlisted views only |
| Intent-to-SQL templates (no free-form SQL) | `coldchain/text2sql.py` | `retail/text2sql.py` | Domain-specific templates |
| SOP retrieval with citations | `coldchain/sop_rag.py` | `retail/sop_rag.py` | Keyword scoring, whole-sentence excerpts |
| Escalation tiers T1 to T4 | `coldchain/escalation.py` | `retail/replenishment.py` | Thresholds come from the SOPs |
| Human confirmation gate | `coldchain/escalation.py` | `retail/replenishment.py` | Tokens; nothing high-impact runs on its own |
| Planner / orchestrator | `coldchain/orchestrator.py` | `retail/orchestrator.py` | Route, call tools, cite, escalate |

## What is different (the domain)

- **coldchain:** reefer telemetry, temperature-breach detection, delay risk, a
  weather tool, port impact. High-impact action: reroute a shipment.
- **retail:** stockout risk from POS velocity and supplier lead time, returns
  abuse, overstock markdowns, a demand-signal tool, purchase-order drafts.
  High-impact actions: markdowns and purchase orders above $5,000. Has a thin
  Streamlit demo (`pip install -e ".[demo]"`).

## Why I did not extract a shared package

I looked at pulling the spine into one small library. I decided against it
for now:

- Both repos are stdlib-only and install with no dependencies. A shared
  package adds a cross-repo version pin and a release step for little gain at
  this size (about 2,200 lines across both).
- The pieces are similar, not identical (audit field names, signal inputs to
  the tier rules), so extraction means a behaviour change in at least one repo.

If a third domain repo uses the same spine, extracting `audit`, `views`
(gateway) and the confirmation gate into one package becomes worth it. That
is the point where duplication costs more than the dependency.
