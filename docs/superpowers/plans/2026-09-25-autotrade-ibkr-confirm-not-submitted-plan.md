# AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED — plan (2026-09-25)

Kenneth picked **option A**: item 3(b), with item 2 folded in. Item 2 (the scan
trigger logs a rejection as REJECTED) already shipped on this branch as
AUTOTRADE-SCAN-REJECT-LOG.

## Problem
IBKR's Client Portal can answer `POST /iserver/account/{acct}/orders` with an
"order reply message": HTTP 2xx, body `[{"id": <reply id>, "message": [..],
"isSuppressed": false, "messageIds": [..]}]`, no `order_id`. IBKR does not take
the order until `POST /iserver/reply/{id}` confirms it. Nothing in this
codebase sends that reply. `IbkrPaperAdapter.place_order` returned
`OrderResult(order_id="", status="Unknown")`. `fire()` booked it as a live
order at the full premium and paged nothing.

## Change
1. `ibkr_paper.OrderResult.awaiting_confirmation: bool = False`. `place_order`
   sets it only for the reply-message shape: no `order_id` key, a truthy `id`,
   and a truthy `message`. A list `message` is joined into readable text. Manual
   `/broker/*` routes see the same `OrderResult` as before, with an empty id.
2. `auto_trader.OrderAwaitingConfirmationError(OrderNotSubmittedError)`.
   `execute_option_order` raises it after `place_order` when the flag is set.
   It is the only not-submitted error raised past the `place_order` boundary,
   and it is justified by the broker's own answer.
3. `fire()`: the existing `not_submitted` branch catches it, so the row books
   0 at risk. The row also carries `broker_contacted` (True only for this
   class). `/auto-trade/fire` answers "Order not submitted: …" (400), which the
   frontend classifies as refused.
4. `_alert_for_consumed_attempt` passes `broker_contacted` from the row, and
   `_alert_not_submitted` words that case as "the broker was contacted but did
   NOT accept the order … NO position was opened". The pre-submission wording
   is unchanged.
5. Folded in, per option A: `fire()`'s own "AutoTrader fired" INFO line becomes
   a "REJECTED by the broker" WARNING on `_is_rejected_status`. This closes the
   AUTOTRADE-SCAN-REJECT-LOG round-1 open question.

## Out of scope (logged)
- Manual `/broker/option-order` and `/broker/stock-order` on IBKR still show an
  empty-id "success" for a confirmation question.
- Answering the question automatically (`/iserver/reply`) is not proposed. It
  would place orders past warnings nobody read.

## Tests
`backend/tests/test_autotrade_ibkr_confirm_not_submitted.py`. The adapter shape
cases, the real adapter via respx through `maybe_fire_on_scan`, the alert text
through the real `notify_alert`, and `fire()`'s log line. 5 mutants killed.
