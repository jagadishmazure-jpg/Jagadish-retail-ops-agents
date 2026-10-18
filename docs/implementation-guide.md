# Implementation guide: from offline build to Azure

> Status: **planned**. Nothing here has been deployed. The offline build in this
> repository is what exists today; this guide is how it would be taken to a
> real Azure environment.

## Azure service mapping

| Offline component | Azure service (planned) | Notes |
|---|---|---|
| Sales and inventory data | Fabric lakehouse or Azure SQL with read-only views for the agent |  |
| SOP retrieval | Azure AI Search |  |
| Planner | Azure OpenAI tool calling in Container Apps | Gate stays in code |
| Approvals | Teams adaptive card or Power Apps | Approver identity recorded in audit |
| Demand signal | Azure Machine Learning forecast endpoint |  |

## Steps

1. Point the gateway at read-only views in the warehouse under an agent identity.
2. Let a model choose templates and write the answer; keep gates and citations in code.
3. Send gate tokens to approvers with a timeout and record the approver.
4. Replace the fake demand backend with a forecast endpoint.

## Guardrails to keep when going live

- Read-only views through a gateway; one SELECT; no base tables.
- Template SQL; the model never writes queries.
- Markdowns and purchase orders above $5,000 need human approval by token.
- Answers quote SOP sentences with a file and section citation.
- Hash-chained audit of every tool call and decision.
- Feedback corrections are capped at 2,000 characters, and emails and long numbers are redacted before they reach the append-only audit log.

## What to measure before calling it production-ready

- Stockouts avoided vs flagged risks; purchase orders approved vs rejected.
- Markdown proposals accepted and their margin effect.
- Planner time saved per question (from user studies).
