# MANUAL-IBKR-CONFIRM-AS-ERROR — plan (2026-09-25)

Decision: MANUAL-IBKR-CONFIRM-AS-ERROR-2026-09-25 (Kenneth: "Yes I want to fix it").
Follows AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED (merged at cd4a2fa), which added the flag this uses.
(Rewritten: the first draft of this plan was never pushed and was lost with its container.)

## 1. The defect, as it stands on main

`IbkrPaperAdapter.place_order` (backend/app/data/ibkr_paper.py) returns
`OrderResult(order_id="", awaiting_confirmation=True, message=<IBKR's question>)` when IBKR
answers the submission with an order-reply message (2xx; `id` + `message`, no `order_id` key).
IBKR does not place such an order until `POST /iserver/reply/{id}` confirms it, and nothing in the
codebase sends that reply. So the order is **not placed**.

The two manual routes in backend/app/routers/broker.py — `place_stock_order` (`/broker/stock-order`)
and `place_option_order` (`/broker/option-order`) — never read the flag. For that reply they:

1. log `broker_order_filled` with `order_id: ""`;
2. return HTTP 200 `{order_id: "", status: <order_status or "Unknown">, broker: "ibkr_paper", deduped: False}`;
3. cache that response via `_release_claim(idem_key, response)`, so a retry of the same order
   within the 3 s dedup window gets the same false success (`deduped: True`) without asking IBKR.

On the frontend, all four manual-send call sites treat a 200 as a placed order and immediately
create a Portfolio position with `order_id ''` (a phantom position for an order that does not exist):

| Call site | On 200 | On throw |
|---|---|---|
| components/organisms/StockPositionCard/index.tsx `submit` (~:533) | `setOrderId`, `addPosition` | `setErr(String(e))`, no position |
| components/organisms/StockSendDialog/index.tsx auto-send (~:160) | `addPosition` | `errs[symbol] = String(e)` (drives the retry set), no position |
| app/(frame)/screener/step-7-trade-card/page.tsx `placeLimitPaper` / `placeMarketNow` (~:1066, ~:1117) | `persistPosition`, `setPaperOrderId` | `setOrderError(String(e))`, no position |
| app/(frame)/screener/step-7-position-card/page.tsx submit (~:130) | `setOrderId`, `addPosition` | `setError(String(e))` (if still viewing), no position |

`api.post` (frontend/lib/api.ts:126) throws on any non-2xx with
`API <path> → <status>: <detail>` (string `detail` taken verbatim, `apiError` :94).
`SendToBrokerDialog` makes no order API call itself. The auto-trader (`auto_trader.py:2180`) is the
only current reader of the flag and is out of scope.

**Conclusion: a non-2xx from the backend with IBKR's question as `detail` fixes every call site;
no frontend source change is needed.**

## 2. Change (backend only)

In backend/app/routers/broker.py:

1. One module-level helper shared by both routes (never copied):

   ```python
   def _confirmation_question(result) -> str | None:
       """IBKR's order-reply question when the broker asked instead of placing the
       order (OrderResult.awaiting_confirmation), else None. getattr: only
       ibkr_paper's OrderResult has the field (Tradier's has its own class)."""
   ```

   Returns `None` unless `getattr(result, "awaiting_confirmation", False) is True`.
   Otherwise returns `result.message` stripped, or a fixed fallback
   (`"IBKR asked for a confirmation"`) if that is empty. Capped at 500 chars, so a long
   broker text cannot bloat the log or the UI.

   Why `is True` and not truthiness: tests' `MagicMock` results would read truthy on any
   attribute. A real `OrderResult` carries a real bool. This keeps every existing
   MagicMock-based route test on its current path.

2. In each route, right after `result = await asyncio.to_thread(...)` and before the
   `broker_order_filled` log, add:

   ```python
   question = _confirmation_question(result)
   if question is not None:
       log_event("broker_order_failed", rec_id, {
           "kind": ..., "broker": result.broker, "symbol": req.symbol,
           "http_status": 502, "awaiting_confirmation": True, "error": question,
       })
       raise HTTPException(
           status_code=502,
           detail=f"IBKR did not place the order: it asked for a confirmation this app "
                  f"does not send, so nothing was submitted. IBKR said: {question}",
       )
   ```

   - **Status 502**, the same code these routes already use for "the broker call did not
     produce an order" (the `RuntimeError` branch). 409 was considered. It was rejected because
     no client retries with a confirmation and nothing branches on the code: the UI shows the
     text. 5xx also stops any client from treating this as a success.
   - `response` stays `None`, so `finally: _release_claim(idem_key, None)` writes **no cache
     entry**. A retry (or a concurrent waiter) becomes the new leader and asks IBKR again.
     That is correct: nothing was placed, so a retry is a genuine new submission.
     This is the existing failure-path contract (`_release_claim` docstring), not a new one.
   - No `broker_order_filled` event for this reply.

3. Nothing else changes: `ibkr_paper.py`, `broker_router.py`, `auto_trader.py`, other
   brokers' results (no field → `getattr` False → unchanged 200), the response shape on success,
   `/broker/status`.

## 3. Tests

New file backend/tests/test_manual_ibkr_confirm_as_error.py. It uses real `OrderResult` objects,
the `_make_app()` / patched `build_router_from_credentials` pattern of
tests/test_broker_idempotency.py, and clears `_idempotency_cache`/`_idempotency_inflight`.

1. stock-order + confirmation reply (`OrderResult(order_id="", status="Unknown", broker="ibkr_paper",
   message="You are about to submit ... Are you sure?", awaiting_confirmation=True)`) → 502. The
   `detail` contains the question and "did not place the order". The response has no `order_id` key.
2. Same for option-order.
3. The audit trail: `log_event` (patched in `app.routers.broker`) is called with
   `broker_order_failed`, carrying `awaiting_confirmation: True` and the question.
   It is **never** called with `broker_order_filled`. Both routes.
4. No cache on this path: two identical posts → both 502, `execute` called twice, and neither
   response says `deduped`. After both, `_idempotency_cache` is empty and `_idempotency_inflight`
   is empty.
5. A confirmation followed by a normal reply for the same order within the window: first → 502,
   second → 200 with the real order id and `deduped: False`.
6. Unchanged paths: a normal IBKR result (`order_id="123"`, flag False) → 200 as before, and so
   does an empty-order-id result **without** the flag (shape unchanged; it stays covered by decision
   NO-ORDER-ID-BOOKS-FULL-PREMIUM and is out of scope). So does a result object with no
   `awaiting_confirmation` attribute (a Tradier-shaped dataclass or a `SimpleNamespace`).
7. Message edge cases: empty/whitespace message with the flag → 502 with the fallback text; a
   600-char message → detail carries at most 500 chars of it.
8. Helper unit tests: `_confirmation_question` for True/False/missing attribute/MagicMock
   (a MagicMock result → None).

Frontend: no source change. Add tests only where the throw path isn't already pinned:
- StockPositionCard: `postStockOrder` rejects with
  `Error('API /broker/stock-order → 502: IBKR did not place the order: ...')` → the error text is
  shown, `addPosition` is not called, and no order id is shown.
- step-7-position-card page: same assertion.
- StockSendDialog (StockSendDialog.test.tsx:132) and the step-7 trade card
  (edited-fields-sync.test.tsx:1033) already pin the throw → error, no position.

Mutation checks to run and record (each must fail ≥1 test):
(a) drop the check in stock-order; (b) the same in option-order; (c) truthiness instead of `is True`
(the MagicMock test must catch it); (d) cache the error response (`response = {...}` before
raising); (e) log `broker_order_filled` before the check.

## 4. Verification

- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → all pass. The baseline on
  main after A4f is 3144 passed / 1 skipped, plus the new tests.
- Focused: `tests/test_manual_ibkr_confirm_as_error.py tests/test_broker_idempotency.py tests/test_broker_router.py tests/test_ibkr_paper.py tests/test_autotrade_ibkr_confirm_not_submitted.py`.
- `cd frontend && npm run typecheck && npm run test` (tests added there).
- `python3 scripts/state.py` exit 0.

## 5. State

Add a PROJECT_STATE.json phase `MANUAL-IBKR-CONFIRM-AS-ERROR`
(verify: present, `backend/app/routers/broker.py`, pattern `def _confirmation_question\(`; note:
presence only, behaviour pinned by the new test file). Record each audit round. Mark the decision
built. Rounds: plan stage and code stage each up to 3 (AUDIT-CAP-PER-STAGE-2026-09-25).

## 6. Out of scope

- Sending IBKR's `/iserver/reply/{id}` confirmation (auto-confirm). Not asked for, and it changes
  what gets traded.
- `id` + empty `message: []` replies (not flagged by the adapter; deferred by the earlier round 2).
- Empty-order-id success without the flag (decision NO-ORDER-ID-BOOKS-FULL-PREMIUM).
- The auto-trade `/fire` path (already handled) and its synchronous broker call.
- Any wording change in the frontend beyond what the backend `detail` supplies.

## Audit rounds

(none yet)
