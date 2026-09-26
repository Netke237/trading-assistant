# STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES — stock sends save first; stocks judged by risk at the stop: plan

Phase `STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES`. Branch `claude/order-booking-safety-7evlql`.
Queued by `P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25`. Policy decision:
**`STOCK-RISK-AT-STOP-2026-09-26`** (Kenneth).

The phase has two parts. **Part B (the frontend) ships in the same merge as Part A (the backend), or before it — never after.**
- **Part A:** `check_position_risk` drops its 5-share stock clamp. It judges a stock at its real share count, by its risk at the stop.
- **Part B:** the three stock broker-send paths save the position first, then send the quantity the save approved. Once the save can resize, sending before saving would put a full-size order at the broker while the books hold a smaller one.

The pattern is P1b-i's (`2026-09-25-p1b1-step7-save-first-core-plan.md`, shipped at `106d853`). Wherever this file says "as P1b-i", the rule and its reasons are the ones stated there, and they are not repeated here.

## 0. What the code does today (checked before writing)

**Backend clamp.**
- `services/portfolio_risk.py:81-86` clamps a stock's `proposed_contracts` to `max_contracts_per_trade` (5).
- It then measures `entry × qty` against `max_single_position_pct` (0.05) and `max_total_exposure_pct` (0.25).
- So any stock order is judged as at most 5 shares of notional. It is always approved, and then booked at the real count.

**Existing positions in the total.** Two builders count every stock row at full notional: `orm_positions_to_risk` (`portfolio_risk.py:180-198`) and `position_writer.py:395-405`.

**Callers of `check_position_risk`:**
- `position_writer.py:407` — the create path, serving the card POST and auto-trade booking;
- `routers/portfolio.py:226` — the PATCH qty-increase path;
- `auto_trader.py:2701` — `_check_exposure`. It is options-only today, but its snapshot, built by `routers/auto_trade.py:209` via `orm_positions_to_risk`, includes stock rows.

`routers/scan.py:1831` also builds a snapshot with `orm_positions_to_risk`. `scan.py` belongs to P3c (`claude/clever-planck-rpz8yh`) and is NOT edited here: its call site does not change, only the helper's output for stock rows does.

**Stock send paths.** All three call `api.postStockOrder` FIRST, then `addPosition(...)` with `source:'broker'`. A save failure after the order only yields the warning "Order placed but not yet tracked in Portfolio".
1. `app/(frame)/screener/step-7-position-card/page.tsx:118-176` — `submit(orderType)`, quantity `card.shares`, stop `card.strategy.stop_price`.
2. `components/organisms/StockPositionCard/index.tsx:523-570` — `submit(orderType)`, quantity `overlay.shares`, stop `overlay.stop`, three target rungs, `structuralStop`. It is rendered by `step-4-stocks/page.tsx:454`.
3. `components/organisms/StockSendDialog/index.tsx:107-225` — its auto-send branch (`:153-192`), a Limit order at `r.shares`, with the per-symbol retry sets `errs` / `q` / `warn`. It is rendered by `step-4-stocks/page.tsx:484`. The dialog's manual and "recommendation" branches only save, and are unchanged.

**Other stock `addPosition` callers.** `step-4-stocks` auto-execute and the ChartWorkspace buy popover only save; they send no broker order. They need no reorder, but Part A now judges their saves at real shares (§A5).

**`/broker/stock-order`** (`routers/broker.py:217-282`) raises the same shapes as `/broker/option-order`: 503 `Broker credentials unavailable`, 400 `ValueError` text, 502 `RuntimeError` text, and 502 `IBKR did not place the order:`. So P1b-i's `classifyDirectFailure` applies unchanged.

**Frontend stop rule.** `lib/paperTrade.ts:36-48` `stockPositionLevels` already drops a stop on the wrong side of entry (Bullish needs `stop < entry`, Bearish needs `stop > entry`) or a non-positive stop, to `null`. Part A uses the same rule.

**Tastytrade** refuses non-limit orders for every instrument (`tastytrade_paper.py:106-110`, a `ValueError` raised as a 400).

## Part A — backend: judge a stock at real shares, by risk at the stop

### A1. One helper, `position_capital_at_risk`

In `services/portfolio_risk.py`:

```python
def position_capital_at_risk(contract_id: str, entry: float, qty: int,
                             stop: float | None = None, direction: str | None = None) -> float:
    """Option: entry x qty x 100 (premium is the max loss). Stock: |entry - stop| x qty
    when the stop is usable, else entry x qty (full notional)."""
```

- **Usable stop:**
  - `stop` is a finite number `> 0`;
  - `direction` is `'Bullish'` with `stop < entry`, or `'Bearish'` with `stop > entry`;
  - this is the same rule as `stockPositionLevels`.
- A stop equal to entry, on the wrong side, missing, or with an unknown direction falls back to notional. The fallback is strictly larger than any valid risk-at-stop for the same row, so a bad stop can never loosen a cap.
- The direction strings are the ones `PortfolioPositionModel.direction` stores (`'Bullish'` / `'Bearish'`).
- An option ignores `stop` and `direction`.

### A2. `check_position_risk`

- **Two new keyword arguments, both optional, defaulting to `None`:** `stop: float | None = None` and `direction: str | None = None`. Existing call sites that pass neither behave exactly as today for options.
- **The clamp goes.** Lines 81-86 become `if not is_stock and proposed_contracts > max_per_trade: reasons.append(EXCEEDS_MAX_CONTRACTS)`.
  - The contract cap stays an OPTION rule.
  - `judged_size` is now always the ordered quantity, for stocks too.
  - The comment is replaced by one naming this phase and `STOCK-RISK-AT-STOP-2026-09-26`.
- **Single-trade exposure:** `capital_at_risk = position_capital_at_risk(contract_id, entry_premium, proposed_contracts, stop, direction)`.
- **The resize** (`single_exposure_pct > max_single`) divides by the **per-unit risk** actually used:
  - `per_unit = capital_at_risk / proposed_contracts`;
  - `adjusted = int(portfolio_value * max_single / per_unit)`.
  - For options this equals today's `entry × 100`.
  - For a stock with a usable stop it is `|entry − stop|`, else `entry`.
- The total-exposure line is unchanged in shape. It now sums the helper's value for the new trade plus the existing rows (A3).

### A3. Existing rows count the same way

- `orm_positions_to_risk` computes `capital_at_risk` with `position_capital_at_risk(p.contract, entry, qty, p.stop, p.direction)`.
- `position_writer.py:395-405` does the same, via the helper and not `_contract_multiplier`.
- One definition, used by all four places: the new trade, both builders, and the PATCH path. Rows are no longer counted at notional while the trade is counted at risk.

### A4. Callers pass the stop

- **`position_writer.py:407`:** `stop=body.stop, direction=body.direction`. `entry_premium` is the writer's final entry, after any live-quote replacement, so the risk is measured against the price actually booked.
- **`routers/portfolio.py:226`** (PATCH qty increase): `stop=position.stop, direction=position.direction`.
- **`auto_trader.py:2701`:** unchanged; options only.

### A5. Consequences, stated so the reviewer can check them

- **A stock save can now come back resized.** `adjusted_size` is set, and the writer applies it with gates on (`position_writer.py` resize path). `persistPosition` surfaces it as `adjustedQty`.
  - Worked example: 200 shares at $50 with a stop at $45 is $1,000 at risk, 1% of $100k. It is approved at 200.
  - The same trade with no stop is $10,000 notional, 10%. It is resized to 100.
- **A stock save can now be refused.** Examples: `total_exposure_limit_reached`, or a stock at notional whose single cap rounds to 0 shares.
- **ChartWorkspace's manual buy has no stop**, so it is judged at notional. That is the fallback working as decided.
- **PATCHing a stop wider is not re-gated.** That is today's behaviour for options as well, and it is out of scope; it is logged in §9.
- **The gates-off `over_exposure` breach list** (`position_writer.py`) no longer reports "the check judged 5, not the ordered N" for stocks, because `judged_size == qty` now. This closes the open question "gates-off clamp applies a CONTRACT cap to STOCK share counts".

### A6. Backend tests (file names corrected in the round-1 section R6)

- **T-A1 `position_capital_at_risk`:**
  - option `(2.00, 3)` gives 600;
  - Bullish stock 200 @ 50, stop 45 → 1000;
  - Bearish 100 @ 50, stop 55 → 500;
  - stop None, equal to entry, wrong side, 0, or `nan`, and direction None → notional.
- **T-A2 no clamp:** a 10-share stock with a usable stop → `judged_size == 10`, not 5, and approved.
- **T-A3 risk resize:** a portfolio of $100k, a Bullish stock at entry 50 with stop 49, 6000 shares → $6,000 at risk, 6% → `adjusted_size == 5000`, reason `size_reduced_to_fit_exposure_limit`, approved.
- **T-A4 notional fallback:** the same trade with no stop → `adjusted_size == 100`.
- **T-A5 total at risk:** existing rows are one stock with a usable stop (risk 20,000) plus one option (premium 3,000). A new stock of risk 3,000 gives total 26% → `total_exposure_limit_reached`. The same stock rows at notional would have been counted larger, so assert the exact percentage the check reports.
- **T-A6 option unchanged:** a 6-lot option still gets `exceeds_max_contracts_per_trade` (the P1a pin), and a passed `stop` does not change an option's capital at risk.
- **T-A7 writer:** a stock POST whose risk exceeds 5% → 201 with the resized `qty` and its `adjustedQty` in the response. A no-stop stock POST over 5% notional → the notional resize.
- **T-A8 PATCH:** raising a stock's qty is judged with the row's stored stop. With a usable stop an increase is approved that the notional rule would have resized.
- **T-A9 `orm_positions_to_risk`:** a stock row with a usable stop yields `capital_at_risk == |entry − stop| × qty`; without one it yields notional.

## Part B — frontend: the three stock sends save first

### B1. Shared code (moved, not duplicated)

- **Pure helpers move to `frontend/lib/directOrder.ts`.** These are `directOrderBlock`, `brokerLabelFor`, `whyOf`, `isNotFound`, `normaliseStatus`, `classifyDirectFailure`, `directSendNoteText` and `removeConfirmText`, taken from `app/(frame)/screener/step-7-trade-card/directOrder.ts`. The old file keeps only `contractLabelFor` (it needs `TradeCardData`) and re-exports the rest, so the P1b-i page and its tests change no import.
- **`removeTrackedRow` and `dropLocal` move** from the options page into `lib/directOrder.ts`, exported. Their behaviour is unchanged, including X1's forced sync plus `dropLocal`.
- **The notes panel.** The options page's inline notes block (`page.tsx:1641-1655`) and its `removeNoteRow` (`:1238-1257`) become a molecule, `components/molecules/DirectSendNotes/index.tsx` (+ `.module.css`, taking over `directNote` / `directNoteRemove`). The molecule reads `useDirectSendNotesStore` itself and renders every note with its confirm-first Remove. The options page renders `<DirectSendNotes />` where the block was.
  - Behaviour, text and DOM are identical, so every P1b-i test (including tests 17-23 and M39-M45) must pass unmodified. That is the acceptance check for the move.
- **The stock orchestration** is one new function, `placeStockOrderSaveFirst(args)`, in `frontend/lib/stockSaveFirst.ts`, used by all three send paths:

```ts
type StockSendArgs = {
  pos: PortfolioPosition;          // buildPaperStockPosition(...) + picks, source 'broker', sourceLabel `${broker} — ${type} (ID: pending)`
  broker: string; orderType: 'LMT' | 'MKT'; limitPrice: number | null;
  action: 'BUY' | 'SELL'; label: string;   // label = `${symbol} stock`
};
type StockSendOutcome =
  | { kind: 'blocked'; message: string }                       // Tastytrade MKT, or a local duplicate
  | { kind: 'refused'; message: string }                       // server said no; nothing written
  | { kind: 'unconfirmed'; message: string }                   // offline / bare 5xx / unparsed 2xx; SAVE-UNCONFIRMED note pushed
  | { kind: 'removed'; message: string }                       // pre-submit broker failure; row auto-deleted
  | { kind: 'not-removed'; message: string }                   // pre-submit failure; delete failed; NOT-REMOVED note
  | { kind: 'unknown'; message: string }                       // kept row + ORDER-UNKNOWN note
  | { kind: 'placed'; orderId: string; qty: number; message: string | null }; // message = size note when resized
```

- It follows P1b-i §2 step for step:
  - the guard;
  - the local duplicate check on `pos.contract`;
  - `persistPosition`;
  - the bare-5xx, refused, offline and unparsed-2xx branches;
  - `orderQty = saved.adjustedQty ?? pos.contracts`;
  - one try/catch around everything after the save;
  - `classifyDirectFailure`;
  - the auto-delete via `removeTrackedRow`;
  - the keep branch: note first, then `applyPersistedPosition`;
  - the success branch: `applyPersistedPosition` with `contracts: orderQty` and the real order id in `sourceLabel`.
- The note and banner texts are P1b-i's, with `label` = `${symbol} stock`.
- It never touches React state. Each caller maps the outcome onto its own UI (B2-B4).
- It is a plain async function, so it is unit-tested directly (B5).
- **Notes rendered on the stock surfaces:** `<DirectSendNotes />` goes into `step-7-position-card/page.tsx` and `step-4-stocks/page.tsx` (the host of the card and the dialog). The store is shared, so a note is visible on every surface that renders the panel, carrying its own label.

### B2. `step-7-position-card/page.tsx` `submit(orderType)`

- The existing guards stay: `execMode`, `hasOrderForCurrent`, `pickMissing`.
- `pos = buildPaperStockPosition(card.symbol, card.strategy.entry_price, card.shares, dir, snapshot, {stop, targets})` + `pickedFieldsFrom(...)`, with `source:'broker'`.
- Call `placeStockOrderSaveFirst`.
  - **`placed`:** `setOrderId(orderId)`, `setOrderedIdx(submittedIdx)`. If `message`, `setWarning(message)` when `stillViewing()`.
  - **Every other kind:** `setError(message)` when `stillViewing()`. The notes hold the durable record.
- The Market button is `disabled` for `tastytrade_paper` with `directOrderBlock`'s text as its `title`, as P1b-i.
- `orderId` is still set only on `placed`. For `unknown`, the kept row makes the local duplicate check refuse a second send.

### B3. `StockPositionCard` `submit(orderType)`

- The same mapping onto `setOrderId` / `setErr` / `setWarning`.
- `pos` is built from `overlay`: shares, stop, the three rungs and `structuralStop`, exactly as today's `addPosition` call.
- **Rung shares on a resize.** When `placed.qty < overlay.shares`, the saved row's target-rung shares are scaled to `placed.qty` with the same rule the card already uses when SHARES shrinks (`index.tsx:272-277`: scale, floor, T3 takes the remainder). That rule is moved to `lib/paperTrade.ts` as `scaleRungShares(targets, total)` and used in both places, so the booked rungs never sum above the booked shares.
- **The Market button** gets the Tastytrade `disabled` / `title`, as B2.

### B4. `StockSendDialog` auto-send branch

- It is Limit only, so the Tastytrade guard never fires. `pos` is built exactly as today's post-order `addPosition`.
- **Outcome → the dialog's sets:**
  - **`placed`** → success. A size note goes into `warn` (informational; not retryable, since the order is live).
  - **`refused` / `blocked` / `unconfirmed` / `removed`** → `errs[symbol] = message`. No order is live, so a retry is safe. On `unconfirmed`, a retry is refused by the local duplicate check if the row synced, and otherwise by the backend's `duplicate_symbol_already_open`, so it can never double-book.
  - **`unknown` / `not-removed`** → `warn[symbol] = message`. **Never `errs`:** a retry could double-place a live order. This is the dialog's existing rule for "the order may be live".
- **`onSubmit(orders)`** is unchanged. A resize puts a note into `warn`, and a non-empty `warn` keeps the dialog open (`index.tsx:216`), so `onSubmit` never runs for a resized basket. `step-4-stocks` ignores the orders passed to it anyway.

### B5. Frontend tests

**Move checks:**
- All existing P1b-i Step-7 tests pass unmodified after B1. The build commit states the before and after counts.
- `lib/__tests__/directOrder.test.ts` (moved from the route folder) still covers every `classifyDirectFailure` case.

**`lib/__tests__/stockSaveFirst.test.ts`:** a fetch mock aware of method and URL, with `POST /api/portfolio` echoing the body (P1b-i §5 Mocks).
1. The persist POST comes before `postStockOrder` (a call-order log).
2. **Refused:** a 422 carrying `total_exposure_limit_reached` → no order, `refused`, no delete, no note.
3. **Offline:** no order, one POST, the delete attempted, the SAVE-UNCONFIRMED note, `unconfirmed`.
4. **Resize:** `adjustedQty: 100` on a 200-share send → `postStockOrder` with quantity 100, the local row has 100 shares, and `placed.qty === 100` with a size note.
5. **Auto-delete:** one case each for a 422, the 503 credentials error, "Unknown broker", "live trading via", the IBKR confirm 502, and status `Rejected` → `removed`, the delete called with the recId, no local row.
6. **Keep:**
   - a 400 `TastytradePaperAdapter only supports limit orders` sent anyway (not a prefix marker);
   - a 502 `Tradier…`;
   - a `TypeError`;
   - an `order_id` of `""`;
   - a status of `Inactive`;
   - a plain `Error('boom')`;
   - → `unknown`, the ORDER-UNKNOWN note pushed BEFORE the row is added, and the row kept.
7. **Local duplicate:** the store already holds `AAA|STOCK` → `blocked`, no POST, no order.
8. **Unparsed 2xx:** `{ok:true, entryPrice:null}` → no order, `unconfirmed`.
9. **Not-removed:** the auto-delete's DELETE rejects with a 500 → `not-removed` and the NOT-REMOVED note.

**Surface tests** (one file per surface, extending the existing tests):
10. **step-7-position-card:** a resize shows the size warning and `orderId` is set. An `unknown` outcome shows the banner, and the panel renders the note with its Remove button. Navigating to another candidate and back leaves the note present.
11. **StockPositionCard:** on a resize to 100 from 200, the saved row's rungs sum to 100. Tastytrade + Market is disabled with the title.
12. **StockSendDialog:** `unknown` lands in `warn`, not `errs`, and a retry does NOT resend that symbol. `removed` lands in `errs`, and a retry resends.
13. **Panel on stock pages:** a note pushed by an options send is visible on `step-4-stocks`, and Remove works there (the confirm and the DELETE by rec_id).

## 6. Mutation checks

| # | Mutation | Test that turns red |
|---|---|---|
| S1 | Keep the stock clamp in `check_position_risk` | T-A2 |
| S2 | Judge a stock by notional even with a usable stop | T-A1, T-A3 |
| S3 | Accept a wrong-side stop as usable | T-A1 |
| S4 | Resize with `entry × multiplier` instead of per-unit risk | T-A3 |
| S5 | Leave `orm_positions_to_risk` at notional for stocks | T-A5, T-A9 |
| S6 | Leave `position_writer`'s builder at notional | T-A11 (R4) |
| S7 | Drop `stop=` in the PATCH call | T-A8 |
| S8 | Apply the contract cap to stocks | T-A2 |
| S9 | Send the order before persisting | 1 |
| S10 | Send `pos.contracts` instead of `orderQty` | 4 |
| S11 | Put `unknown` into the dialog's `errs` | 12 |
| S13 | Skip the rung scaling on a resize | 11 |
| S14 | Drop the local duplicate check | 7 |
| S15 | Push the ORDER-UNKNOWN note after `applyPersistedPosition` | 6 |
| S16 | Render `<DirectSendNotes />` only on the options page | 13 |

## 7. Files

| File | Change |
|---|---|
| `backend/app/services/portfolio_risk.py` | A1-A3 |
| `backend/app/services/position_writer.py` | A3 builder, A4 |
| `backend/app/routers/portfolio.py` | A4 (PATCH) |
| `backend/tests/test_portfolio_risk_contract_cap.py`, `test_position_writer.py`, `test_position_writer_gates.py`, `test_portfolio_update.py` | A6 + R1 (see the round-1 section) |
| `frontend/lib/directOrder.ts` (new, moved), `frontend/app/(frame)/screener/step-7-trade-card/directOrder.ts` (re-export + `contractLabelFor`) | B1 |
| `frontend/lib/stockSaveFirst.ts` (new) | B1 |
| `frontend/components/molecules/DirectSendNotes/` (new) | B1 |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | B1 only: use the moved helpers and the molecule; no behaviour change |
| `frontend/app/(frame)/screener/step-7-position-card/page.tsx` | B2 |
| `frontend/components/organisms/StockPositionCard/index.tsx` | B3 |
| `frontend/components/organisms/StockSendDialog/index.tsx` | B4 |
| `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | render `<DirectSendNotes />` |
| `frontend/lib/paperTrade.ts` | `scaleRungShares` (B3) |
| tests listed in B5 | |
| `CLAUDE.md` | the `directSendNotesStore` row: notes now come from stock sends too |

NOT touched:
- `routers/scan.py` (P3c's; its snapshot changes only through the helper, see §0);
- `auto_trader.py`;
- the alert files (P4a);
- `portfolioStore.ts` (the orchestration uses its exports).

## 8. Gate reminder for the reviewer

Per `audit_rule`, a finding blocks only if it can:
- put a wrong number in front of a user or on a broker order; or
- corrupt persisted data (a live order untracked, a row mis-sized or wrongly deleted); or
- leave a planned test or mutation unable to fail, so that one of the above ships unpinned.

**Decided, and not findings:**
- risk at the stop as the stock measure, with a notional fallback (`STOCK-RISK-AT-STOP-2026-09-26`);
- P1b-i's note lifetime and Remove design (`P1B1-NOTE-IN-MEMORY`, `P1B1-MINIMAL-REMOVE`);
- no Dismiss (`P1B2-CLOSED-BY-ABSORPTION`).

## 9. Logged, not fixed here

- **PATCHing a stop wider is not re-gated.** A position whose stop moves away from entry grows its risk at the stop without a check. This is the same for options today. Owner: whoever next touches the PATCH gate.
- **Stock-scan sizing.** `recommendedShares` sizes from the risk budget. Under risk-at-stop, a trade sized at 1-3.75% risk passes the 5% single cap. The concentration question from Phase E (the open question on `max_single_position_pct` vs notional) is now answered by decision: the cap measures risk, not concentration. There is no notional concentration cap, and that is deliberate.

---

## Plan round 1: 3 gate-level findings (1 HIGH, 2 MEDIUM) and 3 LOW. All fixed below; these SUPERSEDE the sections above where they conflict

Round 1 confirmed several things:
- §0 is accurate;
- the resize can never divide by zero or grow a quantity;
- `unconfirmed` → retry is stopped by the local duplicate check or the backend 409;
- `unknown` and `not-removed` in `warn` are never retried;
- the B1 move is behaviour-neutral for the P1b-i tests;
- mutations S1, S4, S7 and S8 can fail.

**R1 (HIGH): a note must name the broker the order actually went to.** `brokerLabelFor` knows only Tradier and Tastytrade, and labels everything else `IBKR Paper`. The stock paths offer `alpaca_paper`, so an Alpaca ORDER-UNKNOWN note would say "Check IBKR Paper first", and a Remove could leave a live Alpaca order untracked.
- In the moved `lib/directOrder.ts`, `brokerLabelFor` maps `ibkr_paper → 'IBKR Paper'`, `tradier_paper → 'Tradier Paper'`, `tastytrade_paper → 'Tastytrade Paper'` and `alpaca_paper → 'Alpaca Paper'`. Any other key returns the raw key, never another broker's name.
- The options page's labels are unchanged for its three brokers.
- **Test 14** (`stockSaveFirst.test.ts`): an `alpaca_paper` send, then a 502 `Alpaca paper order failed: connection error` → the ORDER-UNKNOWN note and its Remove confirm text contain `Alpaca Paper` and not `IBKR`.
  - A `directOrder.test.ts` case: an unknown key `foo_paper` → `foo_paper`.
- **Mutation S17:** drop the Alpaca branch → test 14 red.

**R2 (MEDIUM): a resize must scale the STORED rungs, not only the local row.** The writer applies `adjusted_size` to `qty` and stores `targets` as sent. The next `syncFromBackend` would then restore rungs that sum above the booked shares.
- **Backend.** In `position_writer.create_position`, when the booked qty differs from `body.qty` (gates on, `risk.adjusted_size` applied), the targets' `contractsToSell` are scaled before storing, by the rule below.
  - It covers every resize path: the card POST, auto-trade booking, and all three stock sends.
  - It covers options too, whose rungs are contract counts. That is correct for them: an option resize already books fewer contracts than the rungs claim.
- **The rule** (`scale_rung_quantities(targets, old_qty, new_qty)`, in `position_writer.py`):
  - only rungs whose `contractsToSell` is a positive number take part;
  - each such rung except the LAST becomes `floor(c × new / old)`;
  - the last becomes `max(0, new − sum(others))`.
  - It is the same rule as the card's existing shrink branch (`StockPositionCard/index.tsx:272-277`), and the frontend `scaleRungShares` (B3) implements the identical rule, so the local row and the stored row agree before the first sync.
- **Tests:**
  - **T-A10** (writer): a Bullish stock POST of 200 with rungs 66/66/68 is resized to 100 → the stored targets are 33/33/34 and sum to 100.
  - A rung set with no `contractsToSell` is stored unchanged.
  - **Test 11** now also asserts the captured `POST /api/portfolio` body's echo. The mock's reply carries the scaled rungs, as the writer returns them.
- **Mutation S18:** skip the writer scaling → T-A10 red.

**R3 (MEDIUM): PATCH judges a qty increase against the stop that the SAME PATCH stores.** The qty gate runs before `position.stop` is updated (`routers/portfolio.py:211-242`), and edits made within 600ms merge into one PATCH.
- A4's PATCH call passes `stop = _floor_stop(updates["stop"]) if "stop" in updates else position.stop`.
- **T-A8 is extended:** row 100 @ 50, stop 49. One PATCH `{qty: 1000, stop: null, portfolioValue: 100000}` → judged at notional: 50,000 is 50%, resized to 100. The row is stored at 100 shares with no stop.
- **Mutation S19:** read `position.stop` regardless → T-A8 (extended) red.

**R4 (MEDIUM): mutation S6 had no test that could fail.** T-A5 refuses under both measures, and the writer's 422 carries only reason codes.
- **T-A11** (writer): the portfolio is $100k with two existing stock rows, each 1000 shares @ $50 with a usable stop at $45. That is $5,000 at risk each ($10,000 total, 10%), but $50,000 each at notional ($100,000, 100%).
- A new stock POST of 100 @ $50, stop $48 ($200 at risk) → 201.
- Under S6 (the writer's builder at notional) the total is over 25% → 422 `total_exposure_limit_reached`.
- S6 now points at T-A11.

**R5 (LOW, closed as a fix): the check reads the stop the writer STORES.** A4's writer call passes `stop=_floor_stop(adjusted_stop)`, the re-anchored and floored stop stored at `position_writer.py:564`, and not `body.stop`.
- Latent today: the stock builders send no `scanStockPrice`, so no re-anchor happens.
- **T-A12:** a stock POST with `scanStockPrice` set and a live quote that moves the price toward a non-user-set stop → the check's capital at risk equals the stored row's `|entry − stored stop| × qty`.
- **Mutation S20:** pass `body.stop` → T-A12 red.

**R6 (LOW): corrections to the test inventory.**
- The backend test files are these; `test_portfolio_risk.py` and `test_portfolio_router.py` do not exist:
  - `backend/tests/test_portfolio_risk_contract_cap.py` — T-A1 to T-A6, T-A9;
  - `backend/tests/test_position_writer.py` — T-A7, T-A10 to T-A12;
  - `backend/tests/test_portfolio_update.py` — T-A8.
- **Two existing tests pin the clamp and are REWRITTEN deliberately, never "fixed" by restoring the clamp.** The build commit names both:
  - `test_portfolio_risk_contract_cap.py::test_3_stock_shares_keep_the_deferred_clamp` becomes "stock shares are judged at the real count": `judged_size == 100`.
  - `test_position_writer_gates.py::test_p1a_6b_...` no longer reports "the check judged 5, not the ordered 20". With gates off and 20 shares that fit every cap, `over_exposure` is now False.
- The B4 clause "`onSubmit` reports the booked qty", and mutation S12, are withdrawn (edited in place above): a resized basket keeps the dialog open, so `onSubmit` never runs for it.

---

## Plan round 2: 3 gate-level findings (1 HIGH, 2 MEDIUM). All fixed below; these SUPERSEDE R2, B3 and A4 where they conflict

Round 2 confirmed several things:
- R1 leaves the options page's labels unchanged (`OptionsBroker` has only the three brokers), and test 14 can fail under S17;
- R3's arithmetic holds, and the extended T-A8 fails under S19;
- T-A11 gives 201 against 422 once its three symbols are distinct;
- T-A12 can fail;
- scaling option rungs breaks nothing, since no backend code reads `contractsToSell`.

**Q1 (MEDIUM): ONE rung rule, the card's own, used in both places.** R2's "always scale by new ÷ old" disagreed with the card whenever the rungs summed to less than the quantity. Rungs can do that: a rung dropped by `stockPositionLevels`, or edited down. Example: 10/33/34 on 100 resized to 80 would store 8/26/46, and T3 would sell the runner the user had left unallocated.
- **The rule** (`scale_rung_quantities(targets, new_qty)` in `position_writer.py`, `scaleRungShares(targets, newQty)` in `lib/paperTrade.ts`, identical):
  - `alloc` = the sum of the positive `contractsToSell`;
  - if `alloc <= new_qty`, the rungs are returned unchanged;
  - otherwise each positive rung except the last becomes `floor(c × new_qty / alloc)`, and the last positive rung becomes `max(0, new_qty − sum(others))`.
  - This is the card's shrink branch (`StockPositionCard/index.tsx:268-277`) generalised to "the last positive rung". The card's own branch calls `scaleRungShares`, so there is one implementation per language.
  - The writer applies it only when it books fewer than `body.qty` (gates on, a resize applied). The rule never grows rungs.
- **Tests:**
  - T-A10 (66/66/68 on 200 → 100 gives 33/33/34) stays.
  - **T-A10b:** 10/33/34 on 100 → 80 is stored unchanged. 10/33/34 on 100 → 50 gives floor(10×50/77)=6, floor(33×50/77)=21, and the last 50−27=23, which sums to 50.
  - **The frontend `paperTrade` test** runs the same two cases through `scaleRungShares`.
- **Mutation S21:** scale by new ÷ old instead of new ÷ alloc → T-A10b red.

**Q2 (MEDIUM): the local row gets the scaled rungs BEFORE it enters the store.** `placeStockOrderSaveFirst` itself calls `applyPersistedPosition` (P1b-i's shape), so B3's "scale after `placed`" came too late. It also never ran on `unknown`, and an EditDrawer targets PATCH in that window could overwrite the correctly scaled stored rungs.
- Inside `placeStockOrderSaveFirst`, every `applyPersistedPosition` receives `{...pos, contracts: orderQty, targets: scaleRungShares(pos.targets, orderQty)}`, in the success branch and the keep branch alike.
- B3's separate post-`placed` scaling is withdrawn. The card only maps the outcome.
- **Tests:** tests 4 and 6 assert that the local row's rung sum is `<=` its `contracts` (for 66/66/68 resized to 100: 33/33/34). S13 now points at tests 4 and 6.

**Q3 (HIGH): a PATCH that RAISES qty must never SHRINK the row.** `routers/portfolio.py:236-241` sets `qty = risk.adjusted_size` unchecked. After Part A, a stock booked at risk that then has its stop cleared or widened is judged at notional, and the resize can fall BELOW the current qty.
- Example: 1000 @ 50, stop 49; the PATCH `{qty: 1001, stop: null}` is resized to 100. The books would say 100 while the broker holds 1000.
- **The fix, in the PATCH qty-increase branch:** if `risk.adjusted_size is not None and risk.adjusted_size < position.qty`, set `qty_error` = `Raising qty to {qty} exceeds the exposure limit even at the current size ({position.qty}); qty left unchanged.` and leave `position.qty` untouched.
  - A resize that lands between the current and the requested qty is applied as today.
  - The rest of the same PATCH (the stop, the targets) still applies, as a `qty_error` does today. Check the router's existing handling of `qty_error` in the build and keep it.
- **T-A8b** (`test_portfolio_update.py`): row 1000 @ 50, stop 49, portfolioValue 100k. PATCH `{qty: 1001, stop: null}` → the response carries the qty error and the stored qty is still 1000. PATCH `{qty: 1001, stop: 40}` ($10 per share × 1001 = 10%, resize 500) → the same.
- **Mutation S22:** drop the guard → T-A8b red.
