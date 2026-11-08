# DIRECT-SEND-NULL-ORDER-ID plan (#593)

**Size** XS · **Complexity** 2 · **Branch** `board/direct-send-null-order-id-fbc69da3`

## Problem

`tradier_paper.py:149` and `ibkr_paper.py:175` build `order_id` with `str(...)`, so a JSON-null id reaches the frontend as the text `"None"` in a 200 body. The backend already treats that as unusable: `routers/broker.py` `_UNUSABLE_ORDER_IDS = {"", "unknown", "none", "null"}` records the attempt as `outcome-unknown`.

`frontend/lib/directOrder.ts` `classifyDirectFailure` refuses only `""` and `"unknown"`. So a `"None"` or `"null"` id with a non-terminal status returns `verdict: 'placed'`:

- Step 7 shows "Order placed — ID: None", and no ORDER-UNKNOWN note is raised (`page.tsx:1311-1328`, `:1834`).
- The position's `sourceLabel` records `(ID: None)` (`page.tsx:1320`).
- The stock path has the same outcome and stores the same label (`lib/stockDirectSend.ts:249-268`).
- The Broker Order Outcome panel, on `responseFacts` in `lib/brokerReview.ts`, already says "Not reported", so the two disagree on one screen.

## Change

1. **`frontend/lib/directOrder.ts`:** export `UNUSABLE_ORDER_IDS = new Set(['', 'unknown', 'none', 'null'])`, mirroring the backend's set. `classifyDirectFailure` computes `usableId` as today (string only, trimmed) and refuses any id whose lowercase form is in the set.
2. **`frontend/lib/brokerReview.ts`:** delete its private `UNUSABLE_ID` and use the exported set, so the two frontend readers cannot drift apart. `responseFacts` behaviour does not change.

Resulting behaviour, with no other branch of `classifyDirectFailure` touched:

| Reply | Before | After |
|---|---|---|
| `order_id` `"None"` / `"null"` (any case, surrounding spaces), status not terminal or rejected | `placed` with that text as the id | `keep`, "broker reply had no usable order ID", `orderId: null` |
| Same id, `TERMINAL_KEEP` status | `keep`, `orderId` is that text | `keep`, `orderId: null` |
| Same id, status `rejected` | `delete` | `delete` (unchanged: rejected is checked first and is proof the order did not stand) |
| Real id, any status | unchanged | unchanged |
| JSON `null`, number, or missing `order_id` | `keep` (not a string) | unchanged |

`keep` keeps the Portfolio row and raises the existing ORDER-UNKNOWN note, which the backend's `outcome-unknown` already implies. It tells the user to check the broker before removing the row. No order is cancelled or resent.

## Tests (written first; each must fail on today's code where it pins new behaviour)

- `frontend/lib/__tests__/directOrder.test.ts`: `"None"`, `"null"`, `"NONE"`, `" none "` with `Submitted` give `keep` with `orderId: null`; the same ids with `Inactive` give `keep` with `orderId: null`; with `Rejected` give `delete`; a real id still gives `placed`; a real id that merely contains the text (`"none-123"`) still gives `placed`.
- `frontend/lib/__tests__/stockDirectSend.test.tsx`: a `"None"` reply gives outcome kind `unknown`, adds one `order-unknown` note with `orderId: null`, and keeps the row with no `(ID: None)` label.
- `frontend/app/(frame)/screener/step-7-trade-card/__tests__/integrated-flows.test.tsx`, block `#584 CHECK b`: its comment says to change it when this is aligned. Flip it: the classifier returns `keep`; on the page the outcome says "Not reported", "Order placed — ID: None" is absent, and exactly one `order-unknown` note exists.
- `responseFacts` assertions stay, proving the shared set did not change that reader.

## Out of scope

- Broker adapters and `routers/broker.py` (the backend already classifies this correctly).
- `/fire` auto-trade paths, which do not use `classifyDirectFailure`.
- Existing Portfolio rows already labelled `(ID: None)`.
- #591 (made-up expiry), its own item.

## Acceptance

- [ ] A null, empty or "None" order id shows the order-unknown note, not "Order placed", on option and stock direct sends
- [ ] `npm run typecheck` clean; full Jest green apart from the known Windows locale failures
- [ ] Plan audit and code audit clean under `audit_rule`

## Completion milestones (`docs/agents/task-ratings.md`)

20% plan approved · 50% implemented · 70% local checks pass · 85% independent code audit clean · 100% merged.
