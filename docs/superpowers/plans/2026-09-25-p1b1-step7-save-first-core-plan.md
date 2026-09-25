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

Plan stage: round 2 findings applied (round 1: 12 findings, 11 fixed, 1 re-logged; round 2: 12 findings, 11 fixed, 1 put to Kenneth: §3).

**Merge order:** P1a (the backend refuses above 5 contracts) must not reach main
before this phase. Today the page sends first, so a 422 on the save leaves a live
order untracked. The two merge together, `--no-ff`.

## 1. Files

| File | Owner |
|---|---|
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | P1 |
| `frontend/lib/api.ts` | no package lists it. One line is added: `deletePortfolioPosition`. |
| `step-7-trade-card/directOrder.ts` (new, not a route file) | P1. Pure helpers `directOrderBlock(orderType, broker)` and `classifyDirectFailure(...)` (§2.1, §2.5), so they can be unit-tested; a Next.js page file may not export them. |
| `step-7-trade-card/__tests__/`: `edited-fields-sync`, `contracts-sync`, `direct-send-stop-gate`, `a8-rail-and-structural-cache` (edited), and new `direct-send-save-first.test.tsx` and `directOrder.test.ts` | P1 (tests of the owned page) |
| `frontend/lib/__tests__/api.test.ts` (one case added: `deletePortfolioPosition` URL-encodes the recId and uses DELETE) | tests of the one `api.ts` line |

NOT touched: TradeCard, CandidateNav, portfolioStore.ts (P2), backend (P1a).

Checked against the code before writing this:
- `sourceLabel` is never sent to the backend (`toBackendPayload` omits it; no backend field). So saving with `ID: pending` loses no persisted data. Only the local row carries the order id, as it does today.
- `DELETE /api/portfolio/{rec_id}` answers 204, or 404 when the row does not exist (`routers/portfolio.py:304`).
- `api.ts`'s `apiError` throws `API ${path} → ${status}: ${detail}` (`api.ts:117`). Every class in §2.5 is matched on the text after `→ `.

## 2. `placeDirectOrder(orderType: 'LMT' | 'MKT')` replaces the two duplicated bodies

`placeLimitPaper` and `placeMarketNow` become one-line wrappers. The guards
(`checkInvalidation`, `checkMethodPick`), the per-type spinner flags and the
note/banner clears at the start stay as they are today.

1. **Guard.** `directOrderBlock(orderType, selectedBroker)` returns `Tastytrade paper accepts limit orders only — use Place Limit.` for `'MKT'` with `tastytrade_paper`, else `null`. When non-null, set `orderError` to it and return before any save. `TastytradePaperAdapter` refuses non-limit orders (`tastytrade_paper.py:106-111`). The "Right Now — Market" button is also `disabled` for that broker, with the same text as its `title`. Title precedence: the Tastytrade text wins over the existing `stopMissing`/`pickMissing` titles (`page.tsx:1412-1416`), because it cannot be cured by filling a field.
2. **Capture the label and build the position.** `label = contractLabelFor(card)` is captured once (not `sendLabel`: that name is already the basket button text at `page.tsx:1264`) and never re-read. It is `contractLabel({symbol, strike, right, expiry})` from `card.contractDetails` when all three are present, else `card.contract`. `setOrderError(null)`, `setPaperOrderId(null)`. `contracts = Math.max(1, orderContractsBySymbol[card.symbol] ?? 1)`. `pos = buildPaperPosition(card, orderType, broker, 'pending', livePrice, contracts)`. `pos.recId` is new for each send.
   - **Compute every order argument now, before the save:** `optionSymbol = toOptionSymbol(card)`, `limitPrice = orderType === 'LMT' ? entryLimitFor(card) : null`, and the side/broker fields. A throw here happens before anything is written, so the outer catch is correct for it. After a confirmed save nothing card-derived is evaluated except `orderQty`.
   - **Local duplicate check.** If `usePortfolioStore.getState().positions` already has a row with `contract === pos.contract`, set the "already tracked" banner (§2.3) and return: no save, no order. The backend would 409 anyway; refusing locally means the SAVE-UNCONFIRMED note (§3) can only ever point at a row this send created.
3. **Save.** `saved = await persistPosition(pos)`. It returns `{ok, offline?, detail?, adjustedQty?, entryPrice?}`. The page never sees the HTTP status.
   - **Bare `HTTP 5xx` detail** (`saved.detail` matches `/^HTTP 5\d\d$/`, i.e. no JSON detail): treated exactly like offline below. Today such a response cannot reach the page (an unhandled backend 500 lacks CORS headers, so the browser throws and `persistPosition` reports offline), but a gateway 502/504 in front of the backend could arrive while the create is still running, so the save is unconfirmed.
   - **Not ok, not offline** (the server answered no): **no delete, no note.** Every server refusal is raised before the commit or after a rollback (`position_writer.py:193`, `:305`, `:353`, `:417`, `:600-631`, `:641-652`), and a post-commit `log_approval` failure is swallowed (`routers/portfolio.py:163-169`), so nothing was written. A delete there is not only useless but dangerous: a failed one would push a NOT-REMOVED note, and on a 409 the only `${label}` row in Portfolio is the user's real, order-backed one.
     - The banner is `${label}: No order was sent — a position for this contract is already tracked in Portfolio. Close or edit that one instead.` when the detail contains `already exists`. Otherwise it is `${label}: No order was sent — ${detail}.`, with one trailing `.` stripped from `detail` first so the line never ends `..`. This includes P1a's refusal (`position_writer.py:655-673`: `N contracts is above the 5-contract limit per trade (max_contracts_per_trade). Lower Contracts to 5 or fewer and send again.`).
     - Return. No local row is added.
   - **Offline** (`saved.offline`): no order is sent. Best-effort delete of `pos.recId`. The banner is `${label}: Portfolio tracking could not be confirmed, so NO order was sent.` Exactly one `POST /api/portfolio` is made. ALWAYS push the SAVE-UNCONFIRMED note, whatever the delete answered, and `dropLocal(pos.recId)`. The create may still be in flight on the server; its live fetches take up to 8s before the commit. A DELETE that lands first answers 404, and the row commits afterwards. `applyPersistedPosition` is NOT called, so `addPosition`'s own retry never runs. Return.
   - **2xx whose body did not parse** (`saved.ok && saved.entryPrice == null`): `persistPosition` swallows a body parse failure into `{ok:true, entryPrice:null}` with no `adjustedQty` (`portfolioStore.ts:400-417`), so the page cannot know whether the server resized. A parsed 201 always carries a positive `entryPrice` (schema `gt=0`, `position_writer.py` replaces the entry only with a positive quote). Treat it exactly like offline, with the banner `${label}: Portfolio saved it but its reply could not be read, so NO order was sent.` Return.
4. **Send.** `orderQty = saved.adjustedQty ?? contracts`. Call `api.postOptionOrder` at `orderQty` with the arguments computed in step 2. **Everything after the confirmed save sits in one try/catch**: the call, the status and id checks, and the success path's bookkeeping. A thrown exception that `classifyDirectFailure` does not recognise as provably pre-submit goes to the keep branch (row plus ORDER-UNKNOWN note). Nothing after the save may reach the handler's outer `catch` (`page.tsx:1089-1091`), which would leave a saved row with no note.
5. **Classify a failure.** The row is deleted automatically ONLY when the failure provably happened before the order was submitted. `why` is the text after `→ NNN: ` when the thrown message has one, else `String(e)` for a throw, or the status for a 2xx. It is never `undefined`.
   - a thrown `→ 422:` (FastAPI request validation);
   - a thrown `→ 503:` whose detail starts with `Broker credentials unavailable`;
   - a thrown `→ 400:` whose detail starts with `live trading via` or `Unknown broker` (`services/broker_router.py:38-45`);
   - a thrown `→ 502:` whose detail STARTS WITH `IBKR did not place the order:` (`routers/broker.py:166-171`). This is a prefix match on the text after `→ 502: `, because other adapters echo broker text into their 502s;
   - a 2xx whose normalised status is `rejected`. Normalised = `String(status ?? '').trim().toLowerCase()` with a leading `orderstatus.` stripped (defensive: `tastytrade==13.2.3`'s `OrderStatus` is a `StrEnum`, so `str()` already yields the value, but an `Enum` repr must never slip past as unknown-and-safe by accident while tests assume otherwise). That is the only 2xx status that is dead on arrival for every adapter.

   A 2xx whose normalised status is one of `inactive`, `error`, `canceled`, `cancelled`, `expired`, `removed`, `partially removed` is NOT auto-deleted: the broker received the order, and IBKR `Inactive` also covers held orders that can still be transmitted. It goes to the kept branch (UNKNOWN), as does an `order_id` that is not a string, or is blank or `unknown` (trimmed, case-insensitive) — so a missing field can never render `ID: undefined` as a success. All of these rules live in `classifyDirectFailure` in `directOrder.ts`, which returns `'delete' | 'keep'` plus `why`.

   **`dropLocal(recId)`** = `usePortfolioStore.setState(s => ({ positions: s.positions.filter(p => p.recId !== recId) }))`. A `syncFromBackend` (QuickLook on mount, `QuickLook.tsx:34`; AutoTradeArm, `:449`, `:475`) may have copied the saved row into the local store between the save and the broker's answer. Called after a successful auto-delete, and in the bare-5xx, offline and unparsed-2xx branches (not the refused branch: nothing was written, and the only matching row may be a real one — `dropLocal` filters by recId, so it is harmless there, but it is not needed). It is a page-level `setState`, not a `portfolioStore.ts` change.

   A sync whose GET started before the DELETE and resolves after `dropLocal` writes the stale row back (`portfolioStore.ts:1257-1263`; that GET fetches quotes with a 10s timeout, `routers/portfolio.py:91-101`). So after a successful auto-delete the page also fires `void usePortfolioStore.getState().syncFromBackend(true).then(() => dropLocal(recId))`, not awaited so the spinner is not held. A forced sync chains after the in-flight one (`:1280-1285`), so its GET post-dates the DELETE.

   **On an auto-delete:** `await api.deletePortfolioPosition(recId)`. A thrown `→ 404` counts as success: the server answered the save, so its write is over. On success `dropLocal(recId)`. The banner reads `${label}: Order NOT placed: ${why}. The tracked position was removed.` When the delete fails, the banner reads `${label}: Order NOT placed: ${why}.` and the NOT-REMOVED note is pushed.

   **Everything else keeps the row.** That covers other 400s and 502s, a fetch `TypeError`, any other throw after the save, an unparseable error, a non-`rejected` terminal 2xx status, and the bad `order_id` cases above. Order matters: FIRST push the ORDER-UNKNOWN note and set the banner `${label}: Order status UNKNOWN (${why}).`, THEN add the row with `applyPersistedPosition(saved, {...pos, contracts: orderQty}, addPosition, onAdjusted → addSaveNote(\`${label}: Portfolio sized it to ${q}; the order was requested for ${q}, status unknown.\`), onDropped → addSaveNote(\`${label}: ${droppedStopNote(r)}\`))` inside a try/catch (a throw appends ` The local view failed to update: ${e}` to the banner and leaves the saved row alone). So a throw can never leave a row without its note.
6. **Success.** `applyPersistedPosition(saved, {...pos, contracts: orderQty, sourceLabel: '… (ID: ' + res.order_id + ')'}, addPosition, onAdjusted → addSaveNote(\`${label}: ${sizeNote(q)}\`), onDropped → addSaveNote(\`${label}: ${droppedStopNote(r)}\`))`. Then `setPaperOrderId({ label, id: res.order_id })`.
   - `sizeNote(q)` gains ` The order was sent for ${q}.`
   - If `applyPersistedPosition` throws, the banner reads `${label}: Order placed (ID ${id}) but the local view failed to update: ${e}`. The saved row is not touched.

**Why every message carries `label`.** Prev/Next stay enabled during a send (`CandidateNav/index.tsx:48,65`, not P1's file). A result that resolves after the user moved to another candidate lands on that candidate's screen. With the label, every line is still true there. The `[active]` effect (`page.tsx:607`) still clears `paperOrderId`, `orderError` and `saveNotes`. `applyPersistedPosition`/`addPosition` act on the saved row, which carries its own contract, so the local store is right whatever card is showing.

## 3. The persistent note (no buttons)

- `const [orphanNotes, setOrphanNotes] = useState<string[]>([])`, with a dedup `addOrphanNote` shaped like `addSaveNote`.
- It is NOT cleared by the `[active]` effect, by a basket submit, or by a new direct send. It goes only when the page unmounts, per Kenneth's decision. **Known limitation:** following the note to Portfolio unmounts Step 7, and a reload loses it too. So it is the page-lifetime record, not a durable one. Whether it should survive navigation (a non-persisted module-level store) is put to Kenneth, not decided here.
- It renders in the `effectiveCard` block OUTSIDE the `selectedBroker` gate, beside `basketNotes`, with `tone="reject"`. Each note names the contract and the rec_id, and says what to do:
  - **ORDER-UNKNOWN:** `${label}: order status UNKNOWN${idPart}. Check ${brokerLabel} first. If an order exists there, keep the ${label} position in Portfolio; if none does, delete it (rec_id ${recId}).` `idPart` is ` (broker order ID ${id})` when a 2xx carried a usable string id (e.g. an `Inactive` or `Cancelled` reply), else empty.
  - **SAVE-UNCONFIRMED:** `${label}: NO order was sent, but Portfolio may still have saved it. If a ${label} position appears in Portfolio and you did not already hold ${label} before this send, delete it (rec_id ${recId}).` The local duplicate check (§2.2) already refuses a send when this browser holds a `${label}` row, so normally a matching row is this send's. The "did not already hold" clause covers the residual case (a row opened elsewhere and not yet synced: the backend 409'd, no new row exists, and the only match is the real one). P1b-ii's Remove-by-recId removes the need for the clause.
  - **NOT-REMOVED:** `${label}: NO order was placed, but its tracked position could not be removed. Delete the ${label} position in Portfolio (rec_id ${recId}).` Pushed only from the auto-delete branch (§2.5), where the row provably is this send's.

  Portfolio does not display rec_ids; the contract label is what the user finds there (one row per contract, per the 409 rule). The rec_id is kept in brackets for support.
- `brokerLabel` is the same broker label `buildPaperPosition` already derives. It is lifted into a module-level `brokerLabelFor(broker)` so the note and the source label cannot disagree.

**The invariant.** Every branch whose outcome may leave a Portfolio row with no order behind it, or an order whose status is unknown, pushes a note. `orderError` explains the moment; the note outlives Prev/Next, basket sends and new sends (see the limitation above). No such case is recorded only in `orderError`.

## 4. The rest

- **paperOrderId** becomes `{ label: string; id: string } | null`, rendered `${label}: Order placed — ID: ${id}`. `handleSubmit` (basket) no longer calls `setPaperOrderId(null)`. The basket never sets it, so clearing it there erased a direct send's confirmation. Its comment is corrected.
- **Positive mid.** Add `positiveOrNull(x)` at module level.
  - `positionFromOrder`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? positiveOrNull(entryLimit) ?? c.entry.limit`.
  - `buildPaperPosition`: `positiveOrNull(livePrice) ?? positiveOrNull(cd?.mid) ?? entryLimitFor(card)`.
  - Today `cd?.mid ?? …` keeps a `0` mid, and the router refuses `entryPrice` 0 (`gt=0`).
- **`api.ts`:** `deletePortfolioPosition: (recId: string) => del(\`/api/portfolio/${encodeURIComponent(recId)}\`)`. It is a plain `del`, which throws on a non-2xx. The page is the one place that reads a `→ 404` as already removed.

## 5. Tests

**Mocks:** the global fetch mock becomes a method- and URL-aware `mockImplementation`: `POST /api/portfolio` echoes the request body (so `entryPrice` and `recId` come back); every other request keeps today's reply. A single `mockResolvedValue` echo would throw on body-less GETs. `deletePortfolioPosition: jest.fn().mockResolvedValue(undefined)` is added to the `@/lib/api` mock factory in the four existing Step-7 test files. Every success mock of the persist POST ECHOES the request body's `entryPrice` back (`JSON.parse(init.body).entryPrice`), or §2.3's unparsed-2xx rule blocks it. A constant would blind the entry-price tests. Every entry-price assertion (existing `edited-fields-sync.test.tsx:717` and `:750-751`, and new test 11) reads the captured `POST /api/portfolio` request body, not the store row.

**Existing tests, updated and never deleted.** The build commit lists each one.
- In `edited-fields-sync`, "broker down" (a plain Error) now expects the UNKNOWN banner, the row kept, and the ORDER-UNKNOWN note.
- The IBKR confirm-502 test expects one persist POST, `deletePortfolioPosition` called with the recId, no "Order placed" line, and IBKR's text in the banner.
- `edited-fields-sync.test.tsx:717` and `:750-751` switch from store rows to the captured POST body (see Mocks).
- `edited-fields-sync` tests using `acceptAll` (`:937`, whose `{}` body would now hit the unparsed-2xx rule and send no order): the A8b direct and market tests (`:973`, `:993`) and both "broker down" tests (`:1030`, `:1049`) move to the echoing mock.
- "a BASKET send clears a direct-path error" (`:1049-1066`) is reworked so it does not lean on the kept AAA row (which now exists and would make the basket merge by contract and `toHaveLength(1)` vacuous): it asserts the basket `POST /api/portfolio` was made, then reads the banner after it resolves.
- Any test that assumed the broker is called before the save, or that read the green line without a label.

**New tests** in `direct-send-save-first.test.tsx`:
1. The persist POST happens before `postOptionOrder` (a shared call-order log).
2. A 422 persist detail with P1a's real sentence (§2.3) → no `postOptionOrder`, the banner says "No order was sent" and does not contain `..`, and the delete is called. `deletePortfolioPosition` is NOT called and no note is pushed.
3. Offline → no `postOptionOrder`, exactly one `POST /api/portfolio`, no local row, the "could not be confirmed" banner, the delete attempted. With the delete resolving, and separately throwing `→ 404` → the SAVE-UNCONFIRMED note is present both times.
4. A `duplicate rec_id` detail and a 409 `already exists` detail → no delete, no note. A bare `HTTP 502` detail → no `postOptionOrder`, the delete is called with the recId, and the SAVE-UNCONFIRMED note is pushed. Local duplicate: a store row with the card's contract → no `POST /api/portfolio`, no `postOptionOrder`, the "already tracked" banner.
5. `adjustedQty: 2` on a 4-lot → `postOptionOrder` with quantity 2, the local row has contracts 2, and the note says "sent for 2".
6. Auto-delete, one case each: a 422, the 503 credentials error, "Unknown broker", "live trading via", the IBKR confirm 502, and status "Rejected" → the delete is called, the "removed" banner shows, and no local row is present. The simulated sync copy is seeded from INSIDE the persist fetch mock (`usePortfolioStore.setState(s => ({positions: [...s.positions, {...row, recId: JSON.parse(init.body).recId}]}))`), since `recId` is generated in the handler (`page.tsx:63-65`). A second case: the auto-delete answers `→ 404` → the "removed" banner and no NOT-REMOVED note. A third: a GET `/api/portfolio` mock that resolves AFTER the delete with the row in it → once everything settles, the row is gone.
7. Kept, one case each: a 400 "Expecting value: line 1 column 1", a 502 "Tradier paper order failed: HTTP 401…", a 502 `Tradier paper order failed: HTTP 400 — IBKR did not place the order: x` (the full marker, but not as the prefix), a 400 `x Unknown broker y` and a 503 `x Broker credentials unavailable` (markers not as prefix), a `TypeError`, a 200 with `order_id: ""`, 200s with a valid id and status `Inactive`, `Cancelled` and `Removed` (the note carries that id), a 200 with no `order_id` field (no "ID: undefined" anywhere), and a plain `Error('boom')` (banner reads `UNKNOWN (Error: boom)`) → no delete, the UNKNOWN banner, the local row present, and the ORDER-UNKNOWN note naming the recId and the broker.
8. Persistence: an UNKNOWN send, then Next, then Prev, then a basket submit, then a successful direct send → the ORDER-UNKNOWN note is still there. Two UNKNOWN sends → two notes.
9. An auto-delete whose delete fails → the NOT-REMOVED note names the recId and survives Next.
10. paperOrderId: a successful Limit, then a failed Market → no green line. A basket submit after a direct success keeps the green line.
11. `contractDetails.mid: 0` with no live quote → the persisted `entryPrice` is the entry limit, for both builders.
12. Tastytrade: the Market button is disabled with the refusal text as its `title` (DOM). Separately, `directOrder.test.ts` unit-tests `directOrderBlock('MKT','tastytrade_paper')` → the text, and `('LMT','tastytrade_paper')`, `('MKT','ibkr_paper')` → null. It also unit-tests `classifyDirectFailure` over every §2.5 case.
15. Order in the kept branch: `applyPersistedPosition` mocked to throw → the ORDER-UNKNOWN note is still present.
13. Labels: Place Limit on AAA, then Next to BBB, then resolve the broker → BBB's screen shows AAA's label on the green line, and no result line without a label. With `adjustedQty: 2`, the note names AAA and "sent for 2".
14. Unparsed 2xx: persist resolves `{ok:true, entryPrice:null}` → `postOptionOrder` is not called, exactly one `POST /api/portfolio`, no local row, the delete is attempted, and the SAVE-UNCONFIRMED note is present.
16. After the save, `postOptionOrder`'s success handling throws (mock `applyPersistedPosition`'s callback to throw, or a `res` getter that throws) → a note is pushed; the handler's outer catch banner alone never appears.

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
| M20 | Clear `orphanNotes` in the `[active]` effect | 8 |
| M21 | Treat a bare `HTTP 502` persist detail as a plain refusal (no SAVE-UNCONFIRMED) | 4 |
| M22 | Match any marker (IBKR, Unknown broker, credentials) as a substring instead of a prefix | 7 |
| M23 | Push the SAVE-UNCONFIRMED note only when the offline delete failed | 3 |
| M24 | Drop the label from the green line | 13 |
| M25 | Drop the unparsed-2xx check | 14 |
| M27 | Skip the NOT-REMOVED push when the auto-delete's delete fails | 9 |
| M28 | Restore a cleanup delete in the refused branch | 4 |
| M33 | Call `applyPersistedPosition` in the offline or unparsed-2xx branch | 3, 14 |
| M34 | Treat the auto-delete's `→ 404` as a failure | 6 |
| M35 | Drop the local duplicate check | 4 |
| M36 | Drop the post-delete forced sync + `dropLocal` | 6 |
| M37 | Let a post-save throw reach the outer catch | 16 |

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
