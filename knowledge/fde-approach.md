# FDE Approach Notes: Retail Operations

Distilled from the forward-deployed-engineer engagement pattern: a vague
client ask ("help our planners") becomes a production assistant through
discovery, design, and a build that respects the client's existing systems.

## Discovery: planner interviews
- Planners juggle stockouts, overstocks, returns abuse, promotions, and
  supplier lead times across spreadsheets and static BI dashboards.
- Manual analysis is the bottleneck: by the time a stockout is visible in BI,
  the shelf has been empty for days.
- No access to tribal knowledge: markdown rules, abuse thresholds, and
  escalation habits live in planners' heads, not in systems.

## Problem statements
1. "Which SKUs will stock out before the next delivery?" (telemetry + lead times)
2. "Who is abusing our returns policy?" (reason codes + thresholds)
3. "What should we mark down, and who approves it?" (overstock + gated actions)
4. "Are our suppliers slipping?" (on-time rate + lead-time drift)
5. "Did that promotion actually work?" (velocity vs baseline)

## HLD: target architecture
Streamlit demo UI (stateless presentation) -> ReAct planner orchestrator
(reasoner + tool node, audited) -> three tools: text-to-SQL over governed
inventory views, TF-IDF RAG over retail SOPs, external demand-signal feed.
High-impact actions (purchase orders > $5,000, all markdowns) are gated behind
human confirmation tokens.

## LLD: key decisions
- Text-to-SQL over read-only views instead of direct table access: least
  privilege at the data layer, SELECT-only gateway with cited rule IDs.
- RAG-as-a-tool for SOPs: answers cite `file §section`; unknown policy
  questions get an explicit "could not find", never an invented policy.
- Demand feed degrades gracefully: on outage the planner reports the gap.
- Immutable hash-chained audit log: every question, query, and gate decision
  is reconstructable.

## Documentation is half the job
HLD/LLD, SOP citations, and the audit trail are the deliverable as much as
the code: they are what let a client's risk and compliance teams say yes.
