# SOP-04: Replenishment Policy

## Reorder points
Reorder point per SKU per store defaults to 7 days of trailing velocity.
Seasonal SKUs use the same 7-day rule against the seasonal baseline, not the
annual average.

## Lead-time buffer
Order-up-to quantity covers lead-time demand plus a 3-day safety buffer.
Suppliers with on-time rates below 90% or lead times above 14 days are
flagged high-risk; buffer doubles to 6 days for their SKUs.

## Supplier performance
On-time rate is reviewed monthly. Two consecutive months below 90% triggers a
supplier review meeting; three consecutive months triggers dual-sourcing
evaluation.

## Purchase orders
The assistant drafts purchase orders from stockout-risk rows. Orders above
$5,000 are gated behind human confirmation. The agent never sends a purchase
order to a supplier autonomously.
