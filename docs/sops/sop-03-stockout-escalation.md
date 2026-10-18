# SOP-03: Stockout Escalation Protocol

## Detection
A SKU is at stockout risk when days of cover falls below the supplier's lead
time in days. The assistant recomputes this continuously from POS velocity.

## Escalation tiers
- T1 (Info): healthy cover. No action; standard monitoring.
- T2 (Watch): cover below lead time. Planner notified; transfer from
  warehouse or nearby store evaluated.
- T3 (Act planned): cover at or below 7 days. Replenishment plan drafted;
  expedite options checked with the supplier.
- T4 (Act now): cover at or below 2 days, or zero on-hand on a high-velocity
  SKU. Immediate escalation to the store manager; emergency transfer or
  expedited purchase order.

## Purchase order approval
Purchase orders above $5,000 require human approval through the assistant's
confirmation gate. Emergency T4 orders may be pre-approved by the store
manager verbally, but the gate record must still be completed the same day.

## Communication
T3/T4 escalations are logged to the audit trail with the cited SKU, store,
cover, and supplier lead time so the decision is reconstructable later.
