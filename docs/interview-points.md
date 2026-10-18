# Interview points

Short, honest talking points for Jagadish-retail-ops-agents. Every number quoted is from the
real run shown in the README.

- Risky actions with money attached (POs, markdowns) are proposals with a token, never automatic.
- My first version leaked markdown into quotes and cut them at 200 characters; now clean sentences with a test.
- I point out a remaining weakness in the README: a loosely related SOP can be cited.
- This repo and the cold-chain one share a design on purpose; I document the overlap.

## Likely follow-up questions

- Why $5,000 for the PO gate? (It is the SOP's number; the threshold belongs to the business.)
- How would you catch returns abuse better? (Features per customer over time and a reviewed label set.)
- What if a store manager disagrees with a tier? (Feedback recorded and used to tune thresholds.)
