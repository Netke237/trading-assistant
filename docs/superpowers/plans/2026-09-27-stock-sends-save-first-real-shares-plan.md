# STOCK-SENDS — stock sends save first, then real-share judging — plan

Phase: STOCK-SENDS-SAVE-FIRST-THEN-REAL-SHARES. Package: P1 remainder (`2026-09-25-work-packages.md` §P1).
Decisions: P1-STOCK-CLAMP-REAL-SHARES-DEFERRED-2026-09-25 (stocks judged at their real share count, AFTER the send paths save first), STOCK-SENDS-STOCK-CAPS-2026-09-27 (stock caps 20% single / 100% total on dollar value; each kind's total counts only its own rows).
Precedent: P1b-i options direct send (`2026-09-25-p1b1-step7-save-first-core-plan.md`, `step-7-trade-card/page.tsx` `placeDirectOrder`, `directOrder.ts`, `directSendNotesStore.ts`) — this plan applies the same shape to stocks and reuses its pure helpers unchanged.
Branch `claude/clever-planck-rpz8yh`, from main `11479bf`.

Three build parts, one layer each (audit_rule: batch size), built and code-audited in the order A, B, C and merged together. **Part A (frontend send paths) lands before Part B (backend)** — the decision's order: judging real shares while a stock order is still sent before its save would trim or refuse the books after a full-size order.

## 0. Today (main `11479bf`)

Three stock paths place a broker order and save the position second:
- `step-7-position-card/page.tsx` `submit()` :130 `postStockOrder(quantity: card.shares)` then :147 `addPosition`.
- `StockPositionCard/index.tsx` `submit()` :533 `postStockOrder(quantity: overlay.shares)` then :545 `addPosition`.
- `StockSendDialog/index.tsx` `submit()` auto-send branch :160 `postStockOrder(quantity: r.shares)` then :175 `addPosition`.
A refused or resized save leaves a full-size order at the broker with no row, or a row smaller than the order ("Order placed but not yet tracked" warning only).

`portfolio_risk.check_position_risk` clamps a `|STOCK` quantity to `max_contracts_per_trade` (5) before judging (:71-76), so the 5%/25% caps judge 5 shares. The total cap sums EVERY open row (`_current_exposure_abs`), stocks at full notional, so one large stock row blocks every option trade.

Save-only stock paths (StockPositionCard "Add to portfolio" :727, StockSendDialog manual/recommendation branches, step-4 after-scan auto-execute) are already save-first; they are touched only for the resize note (A4).

## Part A — frontend: every stock order saves first

**A1. `frontend/lib/stockDirectSend.ts` (new).** One function all three paths call:
```ts
export async function sendStockSaveFirst(args: {
  pos: PortfolioPosition;           // built by buildPaperStockPosition, recId set, contract 'SYM|STOCK'
  broker: string; orderType: 'LMT' | 'MKT'; limitPrice: number | null;
  action: 'BUY' | 'SELL';
  addPosition: PortfolioState['addPosition'];
}): Promise<StockSendOutcome>
type StockSendOutcome =
  | { kind: 'placed'; orderId: string; qty: number; resizedFrom: number | null }
  | { kind: 'refused'; message: string }         // nothing saved, no order
  | { kind: 'not-placed'; message: string }      // saved, order provably not received, row removed (or a NOT-REMOVED note)
  | { kind: 'unknown'; message: string; qty: number | null; resizedFrom: number | null }; // note pushed; qty = the quantity sent (null when the save was unconfirmed and nothing was sent)
```
Sequence, mirroring `placeDirectOrder` step for step:
1. `directOrderBlock(orderType, broker)` → `refused`. Local duplicate (`positions.some(p => p.contract === pos.contract)`) → `refused` ("a position for SYM is already tracked in Portfolio").
2. `persistPosition(pos)` (portfolioValue = `accountValue()`, as today).
3. Unconfirmed (offline; bare `HTTP 5xx`; 2xx with `entryPrice == null`) → note `save-unconfirmed`, `dropLocal`, best-effort `removeTrackedRow(recId, false)`, → `unknown`. No order.
4. `!saved.ok` → `refused` with the server's detail (a 409/422 wrote nothing). No order.
5. `orderQty = saved.adjustedQty ?? pos.contracts`. `postStockOrder({ broker, symbol, action, effect:'OPEN', quantity: orderQty, order_type, limit_price, tif:'DAY' })`; `classifyDirectFailure` on the reply or the throw.
6. `delete` → `removeTrackedRow(recId, true)` → `not-placed`; if the delete throws, note `not-removed`, → `not-placed`.
   `keep` → note `order-unknown` FIRST, then `applyPersistedPosition(saved, {...pos, contracts: orderQty}, addPosition)` → `unknown`.
   `placed` → `applyPersistedPosition(saved, {...pos, contracts: orderQty, source:'broker', sourceLabel: \`${brokerLabelFor(broker)} — ${Limit|Market} (ID: ${id})\`, orderedAt}, addPosition)` → `placed` with `resizedFrom = saved.adjustedQty != null ? pos.contracts : null`.
7. Everything after a confirmed save is inside one try; an unexpected throw there pushes `order-unknown` (row kept), as `keepRow`.
- Labels (R1-2). Before the save, and for `refused` / save-unconfirmed, the label is `"<SYM> <pos.contracts> sh"`. After a confirmed save EVERY message and note uses `"<SYM> <orderQty> sh"` -- the quantity actually sent -- and, when `saved.adjustedQty != null`, the message adds `"(Portfolio sized it from <pos.contracts>)"`. Labels are captured in locals, never re-read from the card (Prev/Next and the basket keep running while a send is in flight).
- Broker labels (R1-1). `brokerLabelFor` (directOrder.ts) gains `alpaca_paper -> 'Alpaca Paper'`; today it maps every other broker to 'IBKR Paper', and the stock paths offer Alpaca, so an ORDER-UNKNOWN note would send the user to the wrong broker before pressing Remove. Options never pass `alpaca_paper`, so the options page is unaffected. Test: each of the four brokers maps to its own label.
- Reused unchanged: `classifyDirectFailure`, `directOrderBlock`, `whyOf`, `isNotFound` (imported from `@/app/(frame)/screener/step-7-trade-card/directOrder`), `persistPosition`, `applyPersistedPosition`, `useDirectSendNotesStore`.
- `dropLocal` / `removeTrackedRow` are page-local in step-7-trade-card; A1 carries its own copies (same bodies). The options page is NOT edited.

**A2. The three callers.**
- step-7-position-card `submit()`: builds the same `pos` it saves today (snapshot, stop/targets, picks) with a fresh `recId`; calls A1; `orderId/orderedIdx` are set ONLY on `placed` (and on `unknown` with `qty != null`, so the Buy buttons stay disabled for that candidate — a second click would duplicate a possibly-live order). On `placed` and on `unknown` with `resizedFrom != null` it shows (R1-2) "Portfolio sized it to <qty> shares; the order was sent for <qty>" beside the card's SHARES figure, which stays the card's own number. Messages go through the existing `stillViewing()` guard; the note store is not guarded (it names the symbol and the sent quantity).
- StockPositionCard `submit()`: same, from the overlay (entry, stop, t1–t3 with sharesT1–3, structuralStop), including the same resize line (R1-2). `orderId` set on `placed`/`unknown` with `qty != null`.
- StockSendDialog auto-send branch: per row, A1. `placed` → success (a resize goes into `warn` as "sized to N shares"); `refused` or `not-placed` → `errs` (retryable: nothing is tracked and no order exists); `unknown` → `warn` (NOT retryable — the row stays out of `targets` on a retry, as today's warn rows).
- The Tastytrade-MKT refusal and all existing `disabled`/`pickMissing` guards are unchanged.

**A3. Notes are visible where stock sends happen.** New organism `DirectSendNotesPanel` (`components/organisms/DirectSendNotesPanel/`): renders `useDirectSendNotesStore` notes with `directSendNoteText`, a Remove button with `removeConfirmText` confirm, and the same remove/patch logic as the options page's `removeNoteRow` (via A1's exported `removeTrackedRow`). Rendered on `step-7-position-card/page.tsx` and `step-4-stocks/page.tsx` (where StockPositionCard and StockSendDialog live). The options page keeps its own rendering.

**A4. Resize is shown on the save-only paths too.** StockPositionCard "Add to portfolio" and StockSendDialog manual/recommendation branches: when `addPosition` returns `adjustedQty`, show "Portfolio sized it to N shares (exposure limit)". (Part B makes resizes common; the card's SHARES figure must not be the only number on screen.)

**A tests (Jest).** Resize (R1-2): save returns adjustedQty 100 for 300 → order quantity 100, the `placed` message and any note name "100 sh" and "sized it from 300"; both single-card callers render the resize line. `stockDirectSend.test.ts`: order is never posted before the save resolves; unconfirmed/refused saves post no order; `adjustedQty` is the order quantity; delete/keep/placed branches (row removed / note + row kept / sourceLabel carries the ID); a throw after the save leaves a note. One test per caller that the POST precedes `postStockOrder` and the order carries the saved quantity; dialog: `unknown` rows are not retried, `refused` rows are. Panel: Remove confirms and deletes exactly the note's rec_id.
Mutations (each must fail a test): swap save/order order; send `pos.contracts` instead of `orderQty`; label a post-save note with `pos.contracts`; drop the `alpaca_paper` label; treat `unknown` as retryable in the dialog; drop the `not-removed` note.

## Part B — backend: stocks judged at their real share count

**B1. Config** (`backend/config/risk_rules.yaml`, `portfolio:`): `max_single_stock_position_pct: 0.20`, `max_total_stock_exposure_pct: 1.00`, commented with the decision id. Existing keys unchanged.

**B2. `check_position_risk`.**
- Delete the `|STOCK` clamp (the defect marker `= min\(proposed_contracts, `). A stock quantity is never refused for `max_contracts_per_trade`; `judged_size = proposed_contracts` for both kinds.
- `is_stock` decides the caps: stocks read the two new keys, options the existing `max_single_position_pct` / `max_total_exposure_pct`.
- `_current_exposure_abs(portfolio, kind)` sums only rows of the same kind (`contract_id.endswith('|STOCK')`); `portfolio_exposure_pct` in every return reports that same-kind figure.
- Unchanged: `min_portfolio_value`, `max_daily_recommendations`, `max_concurrent_positions` and `duplicate_symbol_already_open` (all still counted over every row), the soft-resize arithmetic (multiplier 1 for stocks), the option refusal.
- Callers: card POST (writer), drawer PATCH qty increase, auto-trader `_check_exposure` (options only — its totals now exclude stock rows, per the decision).

**B3. Writer: rung shares follow a resize.** In `create_position`, when the stored `qty` is smaller than `body.qty` on a `|STOCK` row and its targets carry `contractsToSell`, rescale them proportionally to the stored qty (R1-4): `S = sum(contractsToSell)`, `target = min(qty, floor(S * qty / body.qty))`; each rung gets `floor(c * qty / body.qty)`, then the `target - sum(floors)` leftover units go one each to the largest fractional parts (ties: earlier rung). So a partial ladder stays partial (the runner is kept): 33/33 of 100 → 13/13 of 40, not 20/20; a full ladder 50/30/20 of 100 → 20/12/8 of 40. A rung left at 0 keeps its price with `contractsToSell: 0`. Options rows unchanged. (Without it Portfolio shows "sell 50 of 12".) Reachable partial ladder: StockPositionCard `submit()` has no `invalidTargetRungs` guard and `stockPositionLevels` drops a wrong-side rung with its shares.

**B4. Writer's stock-clamp residue.** Remove the gates-off `judged_size != body.qty` breach wording that existed only for the stock clamp; the comparison stays (harmless, now always equal). The log/docstring lines naming the deferred clamp are corrected (mechanism claims).

**B5. The stock caps are readable and editable (R1-3, backend half).** `routers/risk_settings.py`: GET returns `maxSingleStockPositionPct` / `maxTotalStockExposurePct` from the two new keys (defaults 0.20 / 1.00); `RiskConfig` accepts both as optional fractions (`ge=0.0, le=1.0`) and POST writes them to `portfolio:` exactly as it writes `max_single_position_pct`, then clears `portfolio_risk._load_config`'s cache the same way it does for the existing keys.

**B tests (pytest).** Settings GET/POST round-trips both stock keys (tests patch the YAML path, never write backend/config). Rescale partial ladder: 33/33 of 100 → 13/13 of 40. Stock 300 sh × $200 on $100k: judged at 300, single cap 20% → resized to 100; option caps unaffected by a $60k stock row (option total counts options only); stock total counts stocks only; a 10-share stock is not refused for `max_contracts_per_trade`; drawer PATCH stock increase judged at real shares; auto-trader exposure ignores stock rows; writer rescales `contractsToSell` 50/30/20 of 100 → 20/12/8 of 40 and leaves options untouched.
Mutations: restore the clamp; judge stocks with the option caps; sum all rows in the total; skip the rescale; use `min(S, qty)` as the rescale target.

## Part C — frontend: the screens judge each kind by its own caps (R1-3)

Without this, after Part B the screens contradict the server: StockPositionCard's concentration flag (`index.tsx:1109-1122`) warns against the OPTIONS 5% cap ("≈23 shares") on a stock the server books at 20%; `lib/risk.ts` `totalNotional` (:354) feeds stock notional into `checkTradeRisk` (:536, SendToBrokerDialog's options basket), which then demands an override for an option the server accepts; the dashboard RiskPanel and `statusTooltips.ts:427-437` judge one combined total.

**C1. Limits.** `RiskLimits` (types/domain.ts) gains `maxSingleStockPositionPct` and `maxTotalStockExposurePct`. `riskStore` DEFAULT_LIMITS 0.20 / 1.00; persist `version` bumped with a `migrateRisk` branch that fills both with `boundedNumber(…, default, 0, 1)` (existing keys untouched). Settings → Risk hydrates them from GET `/settings/risk` (`isUserEdit: false`, as the existing keys), shows two inputs "Max single stock position %" / "Max total stock exposure %" beside the option caps, and saves them with the rest. `api.ts` `RiskSettings` gains the two optional fields.

**C2. Options judged on option rows only.** `totalNotional(positions, kind?: 'option' | 'stock')` filters by `|STOCK`; `checkTradeRisk` (options only) passes `'option'`.

**C3. The dashboard shows each kind against its own caps.** The dashboard's numbers come from `riskStore.computeMetrics` (riskStore.ts:162-203, read by RiskPanel via `useRiskStore(s => s.metrics)`), NOT from `lib/risk.ts` `computePortfolioRiskMetrics`, which has no production caller (R2-1). C3 changes `computeMetrics`: its per-symbol grouping runs separately per kind; `totalExposurePct` and `largestConcentration*` become option-row figures; new `stockExposurePct`, `largestStockConcentrationPct`, `largestStockConcentrationSymbol` come from stock rows (per-symbol grouped the same way); `statuses` adds `riskBandStatus('fraction', stockExposurePct, maxTotalStockExposurePct)` and `riskBandStatus('fraction', largestStockConcentrationPct, maxSingleStockPositionPct)` beside the existing four, the option bands now fed the option-only figures. `PortfolioRiskMetrics` and DEFAULT_METRICS gain the three fields. `computePortfolioRiskMetrics` is left as is (unused; not a screen number). RiskPanel renders "Option exposure", "Stock exposure", "Largest option position", "Largest stock position", each toned against its own cap; `statusTooltips.ts` lists the stock bands with their caps.

**C4. StockPositionCard's concentration flag** reads `riskLimits.maxSingleStockPositionPct` in BOTH places (R2-2): the `cap` argument (index.tsx:1113) and the printed percentage (:1120). The docstring at :59-61 ("the same two numbers RiskPanel and computeMetrics measure concentration against") is updated to name the stock cap and C3's stock band.

**C tests (Jest).** migrate fills defaults for a v-old persisted state; a $60k stock row does not raise `total_exposure_limit_reached` in `checkTradeRisk` for an option; `useRiskStore.getState().computeMetrics(...)` bands per kind (a $25k stock row on $100k: stock single band REJECT, `totalExposurePct` 0, and a $60k stock row alone leaves the option band PASS); RiskPanel renders the stock rows; the flag's rendered text says "20%" and $20000 on $100k. Mutations: `checkTradeRisk` summing all rows; `computeMetrics`' option band summing all rows; the flag's cap argument OR its printed percentage reading the option cap; migrate dropping the new keys.

## What changes for Kenneth
- A stock order is sent only after Portfolio accepts it, at the size Portfolio accepted. A refusal means no order. An order whose fate is unknown leaves a note with a Remove button.
- Stock cards larger than 20% of portfolio value are cut to 20%; stock exposure beyond 100% is refused. Stock positions no longer count against the options 25% total, and vice versa.

## Out of scope (logged)
- `max_concurrent_positions` / duplicate-symbol stay shared across kinds.
- The options page keeps its own copies of `dropLocal`/`removeTrackedRow`/notes rendering (duplication, below the gate).
- Concurrent bookings reading the snapshot without a lock (P1 backlog entry, unchanged).

## Owned files
Part A: `frontend/lib/stockDirectSend.ts` (new), `frontend/components/organisms/DirectSendNotesPanel/` (new), `frontend/app/(frame)/screener/step-7-position-card/page.tsx`, `frontend/components/organisms/StockPositionCard/index.tsx`, `frontend/components/organisms/StockSendDialog/index.tsx`, `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (panel only), their tests.
Part A also: `frontend/app/(frame)/screener/step-7-trade-card/directOrder.ts` (`brokerLabelFor` only).
Part B: `backend/config/risk_rules.yaml`, `backend/app/services/portfolio_risk.py`, `backend/app/services/position_writer.py`, `backend/app/routers/risk_settings.py`, their tests.
Part C: `frontend/types/domain.ts` (RiskLimits, PortfolioRiskMetrics), `frontend/lib/riskStore.ts`, `frontend/lib/risk.ts`, `frontend/lib/api.ts` (RiskSettings), `frontend/app/(frame)/settings/page.tsx` (risk form), `frontend/components/molecules/RiskPanel/`, `frontend/lib/statusTooltips.ts`, `frontend/components/organisms/StockPositionCard/index.tsx` (flag), their tests. `docs/superpowers/PROJECT_STATE.json`.

## Verification
Backend `cd backend && .venv/bin/python -m pytest -q`; frontend `npm run typecheck && npm run test`; `python3 scripts/state.py` exit 0 with the defect marker gone after Part B.

## Round log
- **Plan round 1 -- 4 gate-level findings, all fixed in r2:** R1-1 `brokerLabelFor` labels Alpaca 'IBKR Paper' (a note would send the user to the wrong broker before Remove) -> alpaca label; R1-2 labels/messages showed the requested, not the sent, share count after a resize -> post-save labels use orderQty, resize line on both single-card paths, `unknown` carries qty/resizedFrom; R1-3 frontend cap copies (concentration flag, checkTradeRisk, RiskPanel) stay on the combined options rules -> Part C + B5; R1-4 rescale sum rule over-allocated a partial ladder -> proportional target.
- **Plan round 2 -- 2 gate-level findings, fixed in r3:** R2-1 C3 targeted `computePortfolioRiskMetrics`, which nothing calls; the dashboard reads `riskStore.computeMetrics` -> C3 retargeted, tests drive the store; R2-2 C4 named only the flag's cap argument, not its printed percentage -> both, plus docstring.
- **Plan round 3 -- CLEAN** (zero gate-level findings; brief quoted audit_rule's severity filter; scope = round-2 fixes). Below the gate, noted: the three new required `PortfolioRiskMetrics` fields need values in the unused `computePortfolioRiskMetrics` too (typecheck catches it).
