# P1b-i — Step-7 direct sends save first and send the approved quantity (core): plan

Phase `P1B1-STEP7-SAVE-FIRST-CORE`. Branch `claude/order-booking-safety-7evlql`.
Split from P1b by Kenneth's decision `P1B-SPLIT-AGAIN-2026-09-25`. Decision
implemented: **P1-CARD-SAVE-FIRST-SEND-TRIMMED-2026-09-25**. Step-7 Place Limit
and Place Market save the position first, send the broker order at the quantity
the gate approved, and delete the saved row only when the broker provably never
received the order.

Carved from `2026-09-25-p1b-step7-save-first-plan.md` (superseded). This file is
self-contained: where the two disagree, this file wins. Taken from it: §2, §4,
U2 (contract labels), U3 (prefix pin), U4 (unparsed 2xx), and U1's rule that an
offline 404 proves nothing. **Left for P1b-ii** (`P1B2-STEP7-ORPHAN-ROW-UI`):
§3's Remove buttons, V1's Dismiss, and the unaudited W1/W2. In their place
P1b-i gives a row that may have no order a **plain persistent note** with no
buttons (§3 below). Kenneth's decision names that note and rules the buttons out.

Plan stage: round 1 findings applied (12 findings, 11 fixed, 1 re-logged: §8).

**Merge order:** P1a (the backend refuses above 5 contracts) must not reach main
before this phase. Today the page sends first, so a 422 on the save leaves a live
order untracked. The two merge together, `--no-ff`.

## 1. Files

| File | Owner |
|---|---|
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | P1 |
| `frontend/lib/api.ts` | no package lists it. One line is added: `deletePortfolioPosition`. |
| `step-7-trade-card/directOrder.ts` (new, not a route file) | P1. Pure helpers `directOrderBlock(orderType, broker)` and `classifyDirectFailure(...)` (§2.1, §2.5), so they can be unit-tested; a Next.js page file may not export them. |
| `step-7-trade-card/__tests__/`: `edited-fields-sync`, `contracts-sync`, `direct-send-stop-gate`, `a8-rail-and-structural-cache` (edited), and a new `direct-send-save-first.test.tsx` | P1 (tests of the owned page) |

NOT touched: TradeCard, CandidateNav, portfolioStore.ts (P2), backend (P1a).

Checked against the code before writing this:
- `sourceLabel` is never sent to the backend (`toBackendPayload` omits it; no backend field). So saving with `ID: pending` loses no persisted data. Only the local row carries the order id, as it does today.
- `DELETE /api/portfolio/{rec_id}` answers 204, or 404 when the row does not exist (`routers/portfolio.py:304`).
- `api.ts`'s `apiError` throws `API ${path} → ${status}: ${detail}` (`api.ts:117`). Every class in §2.5 is matched on the text after `→ `.

## 2. `placeDirectOrder(orderType: 'LMT' | 'MKT')` replaces the two duplicated bodies

`placeLimitPaper` and `placeMarketNow` become one-line wrappers. The guards
(`checkInvalidation`, `checkMethodPick`), the per-type spinner flags and the
note/banner clears at the start stay as they are today.

1. **Guard.** `directOrderBlock(orderType, selectedBroker)` returns `Tastytrade paper accepts limit orders only — use Place Limit.` for `'MKT'` with `tastytrade_paper`, else `null`. When non-null, set `orderError` to it and return before any save. `TastytradePaperAdapter` refuses non-limit orders (`tastytrade_paper.py:106-111`). The "Right Now — Market" button is also `disabled` for that broker, with the same text as its `title`.
2. **Capture the label and build the position.** `label = contractLabelFor(card)` is captured once (not `sendLabel`: that name is already the basket button text at `page.tsx:1264`) and never re-read. It is `contractLabel({symbol, strike, right, expiry})` from `card.contractDetails` when all three are present, else `card.contract`. `setOrderError(null)`, `setPaperOrderId(null)`. `contracts = Math.max(1, orderContractsBySymbol[card.symbol] ?? 1)`. `pos = buildPaperPosition(card, orderType, broker, 'pending', livePrice, contracts)`. `pos.recId` is new for each send.
3. **Save.** `saved = await persistPosition(pos)`. It returns `{ok, offline?, detail?, adjustedQty?, entryPrice?}`. The page never sees the HTTP status.
   - **Bare `HTTP 5xx` detail** (`saved.detail` matches `/^HTTP 5\d\d$/`, i.e. no JSON detail): treated exactly like offline below. Today such a response cannot reach the page (an unhandled backend 500 lacks CORS headers, so the browser throws and `persistPosition` reports offline), but a gateway 502/504 in front of the backend could arrive while the create is still running, so the save is unconfirmed.
   - **Not ok, not offline** (the server answered no): make a best-effort `api.deletePortfolioPosition(pos.recId)`, UNLESS the detail contains `duplicate rec_id`, because that rec_id belongs to another row. The delete is defensive: it does no harm when nothing was written (404).
     - The banner is `${label}: No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.` when the detail contains `already exists`. Otherwise it is `${label}: No order was sent — ${detail}.`, with one trailing `.` stripped from `detail` first so the line never ends `..`. This includes P1a's refusal (`position_writer.py:655-673`: `N contracts is above the 5-contract limit per trade (max_contracts_per_trade). Lower Contracts to 5 or fewer and send again.`).
     - When the delete threw anything other than `→ 404`, push the NOT-REMOVED note (§3).
     - `dropLocal(pos.recId)` (below), then return. No local row is added.
   - **Offline** (`saved.offline`): no order is sent. Best-effort delete of `pos.recId`. The banner is `${label}: Portfolio tracking could not be confirmed, so NO order was sent.` ALWAYS push the SAVE-UNCONFIRMED note, whatever the delete answered, and `dropLocal(pos.recId)`. The create may still be in flight on the server; its live fetches take up to 8s before the commit. A DELETE that lands first answers 404, and the row commits afterwards. `applyPersistedPosition` is NOT called, so `addPosition`'s own retry never runs. Return.
   - **2xx whose body did not parse** (`saved.ok && saved.entryPrice == null`): `persistPosition` swallows a body parse failure into `{ok:true, entryPrice:null}` with no `adjustedQty` (`portfolioStore.ts:400-417`), so the page cannot know whether the server resized. A parsed 201 always carries a positive `entryPrice` (schema `gt=0`, `position_writer.py` replaces the entry only with a positive quote). Treat it exactly like offline, with the banner `${label}: Portfolio saved it but its reply could not be read, so NO order was sent.` Return.
4. **Send.** `orderQty = saved.adjustedQty ?? contracts`. Call `api.postOptionOrder` at `orderQty`, with the same fields as today's two bodies (`LMT` with `entryLimitFor(card)`, `MKT` with `null`). The classification below wraps ONLY this call and the status check.
5. **Classify a failure.** The row is deleted automatically ONLY when the failure provably happened before the order was submitted. `why` is the text after `→ NNN: `, or the status for a 2xx.
   - a thrown `→ 422:` (FastAPI request validation);
   - a thrown `→ 503:` whose detail starts with `Broker credentials unavailable`;
   - a thrown `→ 400:` whose detail starts with `live trading via` or `Unknown broker` (`services/broker_router.py:38-45`);
   - a thrown `→ 502:` whose detail STARTS WITH `IBKR did not place the order:` (`routers/broker.py:166-171`). This is a prefix match on the text after `→ 502: `, because other adapters echo broker text into their 502s;
   - a 2xx whose `String(status ?? '').trim().toLowerCase()` is `rejected`. That is the only 2xx status that is dead on arrival for every adapter.

   A 2xx whose normalised status is one of `inactive`, `error`, `canceled`, `cancelled`, `expired`, `removed`, `partially removed` is NOT auto-deleted: the broker received the order, and IBKR `Inactive` also covers held orders that can still be transmitted. It goes to the kept branch (UNKNOWN), as does a blank/`unknown` `order_id`. All of these rules live in `classifyDirectFailure` in `directOrder.ts`, which returns `'delete' | 'keep'` plus `why`.

   **`dropLocal(recId)`** = `usePortfolioStore.setState(s => ({ positions: s.positions.filter(p => p.recId !== recId) }))`. A `syncFromBackend` (QuickLook on mount, `QuickLook.tsx:34`; AutoTradeArm, `:449`, `:475`) may have copied the saved row into the local store between the save and the broker's answer. Called after a successful auto-delete, and in the refused, bare-5xx, offline and unparsed-2xx branches. It is a page-level `setState`, not a `portfolioStore.ts` change.

   **On an auto-delete:** `await api.deletePortfolioPosition(recId)`. A thrown `→ 404` counts as success: the server answered the save, so its write is over. On success `dropLocal(recId)`. The banner reads `${label}: Order NOT placed: ${why}. The tracked position was removed.` No local row was ever added. When the delete fails, the banner reads `${label}: Order NOT placed: ${why}.` and the NOT-REMOVED note is pushed.

   **Everything else keeps the row.** That covers other 400s and 502s, a fetch `TypeError`, an unparseable error, and a 2xx whose `order_id` is blank or `unknown` (trimmed, case-insensitive). Order matters: FIRST push the ORDER-UNKNOWN note and set the banner `${label}: Order status UNKNOWN (${why}).`, THEN add the row with `applyPersistedPosition(saved, {...pos, contracts: orderQty}, …)` inside a try/catch (a throw appends ` The local view failed to update: ${e}` to the banner and leaves the saved row alone). So a throw can never leave a row without its note.
6. **Success.** `applyPersistedPosition(saved, {...pos, contracts: orderQty, sourceLabel: '… (ID: ' + res.order_id + ')'}, addPosition, onAdjusted → addSaveNote(\`${label}: ${sizeNote(q)}\`), onDropped → addSaveNote(\`${label}: ${droppedStopNote(r)}\`))`. Then `setPaperOrderId({ label, id: res.order_id })`.
   - `sizeNote(q)` gains ` The order was sent for ${q}.`
   - If `applyPersistedPosition` throws, the banner reads `${label}: Order placed (ID ${id}) but the local view failed to update: ${e}`. The saved row is not touched.

**Why every message carries `label`.** Prev/Next stay enabled during a send (`CandidateNav/index.tsx:48,65`, not P1's file). A result that resolves after the user moved to another candidate lands on that candidate's screen. With the label, every line is still true there. The `[active]` effect (`page.tsx:607`) still clears `paperOrderId`, `orderError` and `saveNotes`. `applyPersistedPosition`/`addPosition` act on the saved row, which carries its own contract, so the local store is right whatever card is showing.

## 3. The persistent note (no buttons)

- `const [orphanNotes, setOrphanNotes] = useState<string[]>([])`, with a dedup `addOrphanNote` shaped like `addSaveNote`.
- It is NOT cleared by the `[active]` effect, by a basket submit, or by a new direct send. It goes only when the page unmounts. That is the point: this is the one record that a row may exist without an order, or an order without the user having checked.
- It renders in the `effectiveCard` block OUTSIDE the `selectedBroker` gate, beside `basketNotes`, with `tone="reject"`. Each note names the contract and the rec_id, and says what to do:
  - **ORDER-UNKNOWN:** `${label}: order status UNKNOWN. Check ${brokerLabel} first. If an order exists there, keep the ${label} position in Portfolio; if none does, delete it (rec_id ${recId}).`
  - **SAVE-UNCONFIRMED:** `${label}: NO order was sent, but Portfolio may still have saved it. If a ${label} position appears in Portfolio, delete it (rec_id ${recId}).`
  - **NOT-REMOVED:** `${label}: NO order was placed, but its tracked position could not be removed. Delete the ${label} position in Portfolio (rec_id ${recId}).`

  Portfolio does not display rec_ids; the contract label is what the user finds there (one row per contract, per the 409 rule). The rec_id is kept in brackets for support.
- `brokerLabel` is the same broker label `buildPaperPosition` already derives. It is lifted into a module-level `brokerLabelFor(broker)` so the note and the source label cannot disagree.

**The invariant.** Every branch whose outcome may leave a Portfolio row with no order behind it, or an order whose status is unknown, pushes a note. `orderError` explains the moment; the note is the durable record. No such case is recorded only in `orderError`.

## 4. The rest

- **paperOrderId** becomes `{ label: string; id: string } | null`, rendered `${label}: Order placed — ID: ${id}`. `handleSubmit` (basket) no longer calls `setPaperOrderId(null)`. The basket never sets it, so clearing it there erased a direct send's confirmation. Its comment is corrected.
- **Positive mid.** Add `positiveOrNull(x)` at module level.
  - `positionFromOrder`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? positiveOrNull(entryLimit) ?? c.entry.limit`.
  - `buildPaperPosition`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? entryLimitFor(card)`.
  - Today `cd?.mid ?? …` keeps a `0` mid, and the router refuses `entryPrice` 0 (`gt=0`).
- **`api.ts`:** `deletePortfolioPosition: (recId: string) => del(\`/api/portfolio/${encodeURIComponent(recId)}\`)`. It is a plain `del`, which throws on a non-2xx. The page is the one place that reads a `→ 404` as already removed.

## 5. Tests

**Mocks:** `deletePortfolioPosition: jest.fn().mockResolvedValue(undefined)` is added to the `@/lib/api` mock factory in the four existing Step-7 test files. Every success mock of the persist POST ECHOES the request body's `entryPrice` back (`JSON.parse(init.body).entryPrice`), or §2.3's unparsed-2xx rule blocks it. A constant would blind the entry-price tests. Every entry-price assertion (existing `edited-fields-sync.test.tsx:717` and `:750-751`, and new test 11) reads the captured `POST /api/portfolio` request body, not the store row.

**Existing tests, updated and never deleted.** The build commit lists each one.
- In `edited-fields-sync`, "broker down" (a plain Error) now expects the UNKNOWN banner, the row kept, and the ORDER-UNKNOWN note.
- The IBKR confirm-502 test expects one persist POST, `deletePortfolioPosition` called with the recId, no "Order placed" line, and IBKR's text in the banner.
- `edited-fields-sync.test.tsx:717` and `:750-751` switch from store rows to the captured POST body (see Mocks).
- Any test that assumed the broker is called before the save, or that read the green line without a label.

**New tests** in `direct-send-save-first.test.tsx`:
1. The persist POST happens before `postOptionOrder` (a shared call-order log).
2. A 422 persist detail with P1a's real sentence (§2.3) → no `postOptionOrder`, the banner says "No order was sent" and does not contain `..`, and the delete is called. A mocked `→ 404` delete → no NOT-REMOVED note. A row with that recId pre-seeded in the local store is gone afterwards (`dropLocal`).
3. Offline → no `postOptionOrder`, the "could not be confirmed" banner, the delete attempted. With the delete resolving, and separately throwing `→ 404` → the SAVE-UNCONFIRMED note is present both times.
4. A `duplicate rec_id` detail → the delete is NOT called. A bare `HTTP 502` detail → no `postOptionOrder`, the delete is called with the recId, and the SAVE-UNCONFIRMED note is pushed. A JSON 409 `already exists` detail with the delete rejecting `→ 500: x` → the NOT-REMOVED note.
5. `adjustedQty: 2` on a 4-lot → `postOptionOrder` with quantity 2, the local row has contracts 2, and the note says "sent for 2".
6. Auto-delete, one case each: a 422, the 503 credentials error, "Unknown broker", "live trading via", the IBKR confirm 502, and status "Rejected" → the delete is called, the "removed" banner shows, and no local row is present (including one pre-seeded to simulate a sync).
7. Kept, one case each: a 400 "Expecting value: line 1 column 1", a 502 "Tradier paper order failed: HTTP 401…", a 502 `Tradier paper order failed: HTTP 400 — IBKR did not place the order: x` (the full marker, but not as the prefix), a 400 `x Unknown broker y` and a 503 `x Broker credentials unavailable` (markers not as prefix), a `TypeError`, a 200 with `order_id: ""`, and 200s with a valid id and status `Inactive`, `Cancelled` and `Removed` → no delete, the UNKNOWN banner, the local row present, and the ORDER-UNKNOWN note naming the recId and the broker.
8. Persistence: an UNKNOWN send, then Next, then Prev, then a basket submit, then a successful direct send → the ORDER-UNKNOWN note is still there. Two UNKNOWN sends → two notes.
9. An auto-delete whose delete fails → the NOT-REMOVED note names the recId and survives Next.
10. paperOrderId: a successful Limit, then a failed Market → no green line. A basket submit after a direct success keeps the green line.
11. `contractDetails.mid: 0` with no live quote → the persisted `entryPrice` is the entry limit, for both builders.
12. Tastytrade: the Market button is disabled with the refusal text as its `title` (DOM). Separately, `directOrder.test.ts` unit-tests `directOrderBlock('MKT','tastytrade_paper')` → the text, and `('LMT','tastytrade_paper')`, `('MKT','ibkr_paper')` → null. It also unit-tests `classifyDirectFailure` over every §2.5 case.
15. Order in the kept branch: `applyPersistedPosition` mocked to throw → the ORDER-UNKNOWN note is still present.
13. Labels: Place Limit on AAA, then Next to BBB, then resolve the broker → BBB's screen shows AAA's label on the green line, and no result line without a label. With `adjustedQty: 2`, the note names AAA and "sent for 2".
14. Unparsed 2xx: persist resolves `{ok:true, entryPrice:null}` → `postOptionOrder` is not called, the delete is attempted, and the SAVE-UNCONFIRMED note is present.

## 6. Mutation checks

| # | Mutation | Test that turns red |
|---|---|---|
| M9 | Send the order before persisting | 1 |
| M10 | Send `contracts` instead of `orderQty` | 5 |
| M11 | Skip the auto-delete | 6 |
| M12 | Revert to `??` in either builder | 11 |
| M13 | Restore `setPaperOrderId(null)` in handleSubmit | 10 |
| M19a | Drop the `disabled` on the Market button for Tastytrade | 12 (DOM) |
| M19b | Drop the handler's `directOrderBlock` check (or make it return null) | 12 (unit) |
| M29 | Put `inactive` back in the auto-delete set | 7 |
| M30 | Push the ORDER-UNKNOWN note after `applyPersistedPosition` | 15 |
| M31 | Skip `dropLocal` on the auto-delete | 6 |
| M32 | Echo a constant `entryPrice` in the persist mock (test-side) | 11 must still fail against M12 |
| M20 | Clear `orphanNotes` in the `[active]` effect | 8 |
| M21 | Treat a bare `HTTP 502` persist detail as a plain refusal (no SAVE-UNCONFIRMED) | 4 |
| M22 | Match any marker (IBKR, Unknown broker, credentials) as a substring instead of a prefix | 7 |
| M23 | Push the SAVE-UNCONFIRMED note only when the offline delete failed | 3 |
| M24 | Drop the label from the green line | 13 |
| M25 | Drop the unparsed-2xx check | 14 |
| M27 | Skip the NOT-REMOVED push when the auto-delete's delete fails | 9 |
| M28 | Skip the NOT-REMOVED push when the refused save's cleanup delete fails | 4 |

## 7. Gate reminder for the reviewer

Per `audit_rule`, a finding blocks only if it can put a wrong number in front of
a user or on a broker order, or corrupt persisted data. Removing or dismissing a
note, and a per-row Remove, are P1b-ii by Kenneth's decision. Their absence is
not a finding against this plan.

## 8. PROJECT_STATE at close

- The phase becomes shipped when its code round is clean. Then P1a and P1b-i merge to main together.
- Closes: round_11_followups items 5 and 7, round_13_followups item 7 (the TradeCard `max` stays with P2), and round_2_batch_followups item 3.
- Re-logged for the broker/adapters owner (unassigned): post-submit parse errors should raise `RuntimeError`, not `ValueError`, and a broker 4xx should be told apart from a transport failure in the 502 detail. Until then those land in ORDER-UNKNOWN, which keeps the row. That is the safe side.
- Re-logged for the backend owner (round 1 finding 12): when an offline save's DELETE lands after the create commits but before `log_approval`'s own commit (`routers/portfolio.py:163-168`), an APPROVE audit event is written for a rec_id that no longer exists. `log_approval` should skip a missing position. Backend is out of P1b-i's files.
