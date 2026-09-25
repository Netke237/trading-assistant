# P1b — Step-7 direct sends save first and send the approved quantity: plan

Split from P1 on 2026-09-25 by Kenneth's decision `P1-SPLIT-P1A-P1B-2026-09-25`.
This is the Step-7 page half of the P1 plan (`2026-09-25-p1-order-booking-safety-plan.md`).
The backend half is P1a (`2026-09-25-p1a-backend-contract-cap-plan.md`).
The round count restarts at 0.

This file is self-contained. It folds the P1 plan's §4, §6 and §7 with the
frontend answers from its R, S and T sections. Where this file and the P1 plan
disagree, this file wins for P1b.

Phase `P1B-STEP7-SAVE-FIRST`. Branch `claude/order-booking-safety-7evlql`.
Decision implemented: **P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25**. Step-7
Place Limit / Place Market save the position first, send the broker order at
the approved quantity, and delete the saved row when the broker refuses.

**Merge order:** P1a (the backend refuses above 5 contracts) must not reach
main before this phase. Today the page sends first, so a 422 on the save would
leave a live order untracked. See P1a §0.

## 1. Files

| File | Owner |
|---|---|
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | P1 |
| `frontend/lib/api.ts` | no package lists it. One line is added: `deletePortfolioPosition`. |
| `step-7-trade-card/__tests__/`: `edited-fields-sync`, `contracts-sync`, `direct-send-stop-gate`, `a8-rail-and-structural-cache` (edited), plus a new `direct-send-save-first.test.tsx` | P1 (tests of the owned page) |

NOT touched: TradeCard and portfolioStore.ts (P2), backend (P1a).

## 2. `placeDirectOrder(orderType)`: one helper replaces the two duplicated bodies

The guards (`checkInvalidation`, `checkMethodPick`) and the per-type spinner
flags stay. The steps are:

1. **Guard.** For `'MKT'` with `selectedBroker === 'tastytrade_paper'`, set this `orderError` and return before any save: `Tastytrade paper accepts limit orders only — use Place Limit.` (`TastytradePaperAdapter` refuses non-limit orders: `tastytrade_paper.py:106-111`.) The "Right Now — Market" button is also `disabled` for that broker, with the same text as its title.
2. **Build the position.** `setOrderError(null)` and `setPaperOrderId(null)`. `contracts = Math.max(1, orderContractsBySymbol[sym] ?? 1)`. Then `pos = buildPaperPosition(card, type, broker, 'pending', livePrice, contracts)`, with the sourceLabel `… (ID: pending)`. `pos.recId` is new for each send.
3. **Save.** `saved = await persistPosition(pos)`. That returns `{ok, offline?, detail?, adjustedQty?, …}`, and the page never sees the HTTP status.
   - **Not ok, not offline:** make a best-effort `api.deletePortfolioPosition(pos.recId)`, UNLESS the detail contains `duplicate rec_id`. That rec_id belongs to another row. The delete does no harm when nothing was written (a 404) and is needed after a 500 that came after the commit.
     - The banner is `No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.` when the detail contains `already exists`.
     - Otherwise it is `No order was sent — ${detail}.`
     - Either banner gets ` If ${recId} appears in Portfolio, delete it.` appended when the delete threw anything other than `→ 404`.
     - Return.
   - **Offline:** make a best-effort delete of `pos.recId` too. The banner is `Portfolio tracking could not be confirmed, so NO order was sent.`, with the same "If … delete it." suffix when the delete threw anything other than `→ 404`. Return.
4. **Send.** `orderQty = saved.adjustedQty ?? contracts`. Send `api.postOptionOrder` at `orderQty`. The auto-delete and keep logic wraps ONLY this call and the status check below.
5. **Classify a failure.** The row is deleted automatically ONLY when the failure is provably from before the order was submitted:
   - a thrown `→ 422:` (FastAPI request validation);
   - a thrown `→ 503:` whose detail starts with `Broker credentials unavailable`;
   - a thrown `→ 400:` whose detail starts with `live trading via` or `Unknown broker`;
   - a thrown `→ 502:` whose detail STARTS WITH `IBKR did not place the order:` (`routers/broker.py:166-171`). This is a prefix match on the text after `→ 502: `, because other adapters echo broker text into their 502s;
   - a 2xx whose `String(status ?? '').trim().toLowerCase()` is one of rejected, inactive, error, canceled, cancelled, expired.

   On an auto-delete: `await api.deletePortfolioPosition(recId)`. A thrown `→ 404` counts as success. On success, drop the row from the store: `usePortfolioStore.setState(s => ({ positions: s.positions.filter(r => r.recId !== recId) }))`. The banner reads `Order NOT placed: ${why}. The tracked position was removed.`, or, when the delete fails, `Order NOT placed: ${why}. Its tracked position ${recId} could not be removed — delete it in Portfolio.`

   **Everything else keeps the row.** That covers other 400s and 502s, a fetch TypeError, an unparseable error, and a 2xx whose `order_id` is `""` or `"unknown"`. The banner reads `Order status UNKNOWN (${why}). The tracked position ${recId} was kept — check the broker. If no order exists there, remove it:`, and the recId is pushed onto `unknownRecIds`.
6. **Success.** `applyPersistedPosition(saved, {...pos, contracts: orderQty, sourceLabel: …ID: res.order_id}, addPosition, onAdjusted → addSaveNote(sizeNote(q)), onDropped)`, then `setPaperOrderId(res.order_id)`.
   - `sizeNote` gains ` The order was sent for N.`
   - If `applyPersistedPosition` fails, the banner reads `Order placed (ID …) but the local view failed to update: …`. The row is not touched.

## 3. The Remove buttons

- `const [unknownRecIds, setUnknownRecIds] = useState<string[]>([])` is separate from `orderError`.
- There is one button per recId, labelled `Remove tracked position ${recId}`. It shows under whatever banner is up.
- A click deletes by recId (never by reading the active card), applies the store drop from §2.5, and removes that recId from the list. A thrown `→ 404` counts as success. The banner becomes `Tracked position removed.`
- The list is NOT cleared by Prev/Next, a basket submit, or a new direct send. It is cleared only by unmount.

## 4. The rest

- **paperOrderId:** `handleSubmit` (basket) no longer calls `setPaperOrderId(null)`, and its misleading comment is corrected.
- **Positive mid:** add `positiveOrNull(x)` at module level.
  - `positionFromOrder`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? positiveOrNull(entryLimit) ?? c.entry.limit`.
  - `buildPaperPosition`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? entryLimitFor(card)`.
- **`api.ts`:** `deletePortfolioPosition: (recId: string) => del(\`/api/portfolio/${encodeURIComponent(recId)}\`)`. It is a plain `del`, which throws on a non-2xx. The page is the one place that reads a `→ 404` as already removed.

## 5. Tests

**Mocks:** `deletePortfolioPosition: jest.fn().mockResolvedValue(undefined)` is added to the `@/lib/api` mock factory in the four existing Step-7 test files.

**Existing tests, updated and never deleted.** The build commit lists each one.
- In `edited-fields-sync`, "broker down" (a plain Error) now expects the UNKNOWN banner, with the row kept.
- The IBKR confirm-502 test expects one persist POST, `deletePortfolioPosition` called with the recId, no "Order placed" line, and IBKR's text in the banner.
- Any other test that assumed the broker is called before the save.

**New tests** in `direct-send-save-first.test.tsx`:
1. The persist POST happens before `postOptionOrder` (a shared call-order log).
2. A 422 persist detail → no `postOptionOrder`, the banner says "No order was sent", and the delete is called (a mocked 404 shows no "delete it" line).
3. Offline → no `postOptionOrder`, the "could not be confirmed" banner, the delete attempted.
4. A `duplicate rec_id` detail → the delete is NOT called. An `HTTP 500` detail → the delete is called with the recId.
5. `adjustedQty: 2` on a 4-lot → `postOptionOrder` with quantity 2, the local row has contracts 2, and the note says "sent for 2".
6. Auto-delete, one case each: a 422, the 503 credentials error, "Unknown broker", the IBKR confirm 502, and status "Rejected" → the delete is called, the "removed" banner shows, and no local row is added.
7. Kept, one case each: a 400 "Expecting value: line 1 column 1", a 502 "Tradier paper order failed: HTTP 401…", a 502 "Tradier paper order failed: … did not place the order …" (the text appears but not as the prefix), a TypeError, and a 200 with `order_id: ""` → no delete, the UNKNOWN banner, and the Remove button.
8. Remove button: an UNKNOWN send, then Next, then Prev → the button is still there, and a click deletes that recId and drops the store row. Two UNKNOWN sends → two buttons.
9. An auto-delete whose delete fails → the banner names the recId and "delete it in Portfolio".
10. paperOrderId: a successful Limit, then a failed Market → no green "Order placed" line. A basket submit after a direct success keeps the green line.
11. `contractDetails.mid: 0` with no live quote → the persisted `entryPrice` is the entry limit (both builders).
12. Tastytrade: the Market button is disabled, and calling the handler anyway sends neither a persist POST nor `postOptionOrder`.

## 6. Mutation checks

| # | Mutation | Test that turns red |
|---|---|---|
| M9 | Send the order before persisting | 1 |
| M10 | Send `contracts` instead of `orderQty` | 5 |
| M11 | Skip the auto-delete | 6 |
| M12 | Revert to `??` | 11 |
| M13 | Restore `setPaperOrderId(null)` in handleSubmit | 10 |
| M19 | Drop the Tastytrade guard | 12 |
| M20 | Clear `unknownRecIds` in the `[active]` effect | 8 |
| M21 | Skip the delete on an `HTTP 500` persist detail | 4 |
| M22 | Match the IBKR text as a substring instead of a prefix | 7 |

## 7. Gate reminder for the reviewer

Per `audit_rule`, a finding blocks only if it can put a wrong number in front of
a user or on a broker order, or corrupt persisted data.

## 8. PROJECT_STATE at close

- The phase becomes shipped when its code round is clean.
- Closes: round_11_followups items 5 and 7, round_13_followups item 7 (the TradeCard `max` stays with P2), and round_2_batch_followups item 3.
- Re-logged, for the broker/adapters owner (unassigned): post-submit parse errors should raise `RuntimeError` rather than `ValueError`, and a broker 4xx should be told apart from a transport failure in the 502 detail.
