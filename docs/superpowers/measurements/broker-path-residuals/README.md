# BROKER-PATH-RESIDUALS discovery — 2026-10-13

Board item #165, source baseline `5f98b791`. Evidence only: no application fix,
implementation plan or qualifying independent plan/code audit yet. No real broker
order, production database write or production configuration change occurred.

## Reproduce

Python 3.11.16 in the prepared backend environment. Run from repository root:

```sh
backend/.venv/bin/python docs/superpowers/measurements/broker-path-residuals/broker_error_probe.py
backend/.venv/bin/python docs/superpowers/measurements/broker-path-residuals/risk_probe.py
```

Broker observations and mocking boundaries: [broker_error_probe.md](broker_error_probe.md).
Risk probe uses a fresh in-memory SQLite database with the actual PATCH handler,
ORM and risk calculation. Account/configuration are mocked: account value 10,000,
stock total cap 1.5%, single-position cap 20%. Two synthetic positions start at
one share at entry 10. Each PATCH requests ten shares. A deterministic barrier
holds both snapshots after reading other positions and before either writes.

Observed output (exit 0):

```text
PATCH accepted quantities: [10, 10]
Persisted combined exposure: 200.00; configured total cap: 150.00
Quantity changed 1 -> 10; entry remains 10.00
Bullish stored entry 10.00; PATCH accepted stop 11.00
```

The combined-cap breach is a reachable PATCH-versus-PATCH race. Each snapshot
sees the other row at 10 and its proposed row at 100, so 110 passes the 150 cap;
after both commits the total is 200. `portfolio.py:update_position` does not use
`position_writer._booking_lock`. Create-versus-PATCH and fire-versus-PATCH remain
scope to validate in the eventual plan; this probe does not claim to run them.

Quantity increases keep the old entry. That proves current behavior, not the
correct cost basis of an actual broker fill: this API has no added-fill price.
Choosing a quantity correction versus added-fill operation is a product decision.
The positive stop above stored bullish entry also proves PATCH accepts it; it
does not prove the stop is on the wrong side of the current market quote.
Plan-derived stop policy must remain distinct from manual corrections and must
be resolved before altering either behavior.

## Proposed implementation boundaries

1. Explicit submission outcome/attempt contract: preserve uncertain tracked rows
   and risk reservations; prevent a waiting duplicate from dispatching; never
   equate accepted/submitted with filled. Durable identity/reconciliation needs
   the user's choice before planning restart behavior and deliberate scaling.
2. Serialize portfolio risk-changing writes and judge a fresh snapshot at the
   actual boundary, while preserving late-422 companion-field behavior.
   Include create/PATCH/fire interactions rather than claiming the booking lock
   alone closes every dispatch race.
3. Determine quantity-edit semantics before adding weighted entry inputs.
   Keep existing approval cleanup policy, but fix the separate-commit orphan
   window without silently changing approvals to permanent audit history.

These are candidate boundaries, not audited build tickets. Audit counters remain
zero; the target remains unfinished and is not ready to merge.

## User choices in this session

2026-10-13, answers to the two explicit questions:

- "Keep blocked until manual verification (Recommended)": use a durable attempt
  identity and preserve an uncertain hold across retries and restarts until
  the user verifies the broker outcome. No automatic broker lookup or retry.
- "Added fill with price and average entry (Recommended)": a Portfolio quantity
  increase means additional filled units, with their positive fill price
  required to recompute the weighted average entry.

The implementation plan must apply these choices. These approvals do not mark
an audit clean or authorize skipping the independent phase gates.

Follow-up answer in the same chat: "Record full fill and warn (Recommended)".
If an additional fill breaches an exposure cap, record all actually filled
units and show the breach. This changes the editor's former pre-trade-style
clamp/refusal for increases; pre-trade order authorization still enforces caps.
