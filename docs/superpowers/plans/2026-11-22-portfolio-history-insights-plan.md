# PORTFOLIO-HISTORY-INSIGHTS — plan (#663, part of umbrella #656)

Branch `board/portfolio-history-insights-9e3de20c`. Blockers: none (#661 merged). Blocks #664 (EXIT-RECORD) and #672 (ALERT-ACTION): keep `frontend/lib/tradeStats.ts` and the History-tab structure documented for them.

**Gate for this phase: a wrong number in front of the user** — win rate, average win/loss, profit factor, expectancy, hold days, return %, the stop-check labels, and the realized-total claim behind the × confirm. Every formula below is exact and is pinned by tests in T1.

## 1. Data (what the code gives us)

`ClosedPosition` (`frontend/lib/performanceStore.ts`): `id, recId, symbol, contract, direction, entryPrice, entryDate?, exitPrice, exitDate, qtyClosed, realizedPnlDollar, realizedPnlPct, closedAt`. Backend (`portfolio_performance.realized_pnl`): `dollar = round((exit−entry)·mult·qty, 2)`, `pct = round((exit−entry)/entry·100, 2)`, **`pct = 0.0` when `entry == 0`**; for a short stock (Bearish `|STOCK`) both dollar and pct are negated. `entryDate` is a nullable string, `exitDate` a string; both may carry a time suffix, the backend itself reads `d[:10]`.

A row is **one close event**, not one position: a partial close and the later remainder close are two rows (two trades in every statistic below). Documented in the module header; not changed here.

## 2. Existing History-tab inventory (ui-parity: nothing is removed)

| Element | Tag | Plan |
|---|---|---|
| Tabs Open/History with counts | existing | untouched |
| PerfStrip realized today/week/month/year | existing | untouched |
| `PnlChart` (Total value / Realized P&L, Days/Weeks/Months) | existing | Realized curve only gets `lineType: WithSteps` (T2) |
| Toolbar: "N closed trades", Clear all + confirm, Download CSV | existing | untouched; the count stays the total `history.length` (the filtered count is a new line in the filter bar) |
| List columns SYMBOL, CONTRACT (readable), QTY · ENTRY → EXIT, DATES, P&L, × | existing | kept in this order; new columns appended **between P&L and ×** |
| Empty text "No closed trades yet." | existing | kept |
| `PnlHeatmap history={history}` | existing | untouched, still fed the **unfiltered** history |
| `toHistoryCsv(history)` | existing | untouched, unfiltered, no new columns |
| Trade statistics strip | **new** | T3 |
| Filter (All/Wins/Losses), symbol search | **new** | T3 |
| Sortable headers | **new** | T3 |
| Return %, Hold, Exit check columns | **new** | T3 |
| Journal link icon | **new** | T4 |
| × confirm | **changed** | T4 |
| Realized curve stepped | **changed** | T2 |

## 3. Exact formulas (`frontend/lib/tradeStats.ts`)

Input rows with a non-finite `realizedPnlDollar` are **dropped before any statistic** and counted in `skipped` (shown as "N rows with invalid P&L ignored" when > 0). Everything else is defined on the remaining rows ("trades").

- **cents(x) = Math.round(x·100)**. Class of a trade: `win` if `cents(realizedPnlDollar) > 0`, `loss` if `< 0`, else `flat`. (A −0.004 is flat; the display `$0` never gets a colour or a class — same rule as `moneyTone`.)
- `wins, losses, flats` = counts. `count = wins + losses + flats`.
- **winRate** = `wins / (wins + losses) · 100`; `null` when `wins + losses == 0`. Flats are excluded from numerator and denominator. Display: `Math.round`, `"29%"`; `null` → `"—"`.
- **grossWon** = Σ dollar of wins; **grossLost** = Σ |dollar| of losses.
- **avgWin** = `grossWon / wins` (`null` if no wins). **avgLoss** = `−grossLost / losses` (negative, `null` if no losses). Display `formatMoney(v, {plus:true})` (whole dollars).
- **lossToWin** = `|avgLoss| / avgWin`, `null` unless both exist and `avgWin > 0`. Display `"1.8× the average win"` (1 decimal, `toFixed(1)`).
- **profitFactor** = `grossWon / grossLost`; `null` when `losses == 0` (shown `"—"`); `0` when there are losses and no wins (shown `0.00`). Display `toFixed(2)`.
- **total** = Σ dollar over all trades; **expectancy** = `total / count` (flats count in the denominator), `null` when `count == 0`. Display `formatMoney(v, {plus:true})`.
- **holdDays(h)**: take `entryDate.slice(0,10)` and `exitDate.slice(0,10)`; each must match `^\d{4}-\d{2}-\d{2}$` **and** round-trip through `Date.UTC(y, m−1, d)` to the same y/m/d (rejects `2026-02-31`); result `(exitUTC − entryUTC) / 86_400_000`, an exact integer because both are UTC midnights — **calendar days between the two date strings, no timezone, no DST** (they are the same date strings the backend stores). `null` when either is missing/invalid **or the result is negative** (exit before entry is bad data, never shown as a hold). `0` is a valid same-day hold, shown `"0d"`. Row display `"76d"`; `null` → `"—"`.
- **hold stats**: over trades with non-null holdDays: `avg = Math.round(Σ/n)`, `min`, `max`, `n`; all `null` when `n == 0`. Strip shows `"76 days (6–111)"`; when `n < count` it adds `"· N of M trades"`.
- **returnPct(h)** = `realizedPnlPct` if `entryPrice > 0` and `realizedPnlPct` finite, else `null` (the API reports `0.0` for a zero-cost entry, which must not display as a real `0.0%`). Display `formatSignedPct(v, 1)`; `null` → `"—"`.
- **isStock(contract)** = `contract.endsWith('|STOCK')`; **isOption(contract)** = `parseContractId(contract) !== null` (`lib/contractGrading`); anything else is "unknown".
- **exitCheck(h, stopPct)** where `stopPct` is the global `premiumStopPct` ratio (e.g. 0.60), valid only if finite and `0 < stopPct < 1`:
  - class `win` → `{kind:'win', label:'Win'}`; class `flat` → `{kind:'flat', label:'Flat'}`;
  - class `loss`:
    - stock → `{kind:'stock-loss', label:'Stock loss'}` (the premium stop does not apply to shares; excluded from the stop count);
    - not option (unknown contract), or `returnPct == null`, or `returnPct >= 0`, or `stopPct` invalid → `{kind:'unknown', label:'—'}` (excluded);
    - option: `lossPct = −returnPct`; `lossPct > stopPct·100` (strict; the API's 2-dp rounding is the resolution) → `{kind:'past-stop', lossPct, label:'Lost 99%: past 60% premium stop'}`; otherwise `{kind:'within-stop', label:'Within premium stop'}`.
  - Label numbers: `Lost ${L}%` and `past ${S}% premium stop` where `S = Math.round(stopPct·100)` and `L = Math.round(lossPct)`, **except** when `L <= S` (a 60.4% loss against a 60% stop), then `L = lossPct.toFixed(1)` so the label never reads "Lost 60%: past 60%".
- **pastStop** = `{ n: count of past-stop, of: count of past-stop + within-stop }` — the "N of M losses" denominator is **only option losses that could be checked**, never all losses. Strip text `"Past premium stop: 4 of 5 losses"`; if `of == 0` → `"—"`. When `of < losses` the strip appends `" (N losses not checked: stock or no entry price)"`.
- Tooltip (column header and strip cell): `"Compared with today's global premium stop (60%), not the stop that applied at entry — the stop at entry is not stored yet."` where 60 is `Math.round(stopPct·100)`.
- **tradeLabel(h)** for the × confirm: stock (`|STOCK`) → `"NFLX stock"`; option via `parseContractId` → `"NFLX 82C"` (`${symbol} ${strike}${right}`; strike printed as a number with no trailing `.0`); otherwise `"${symbol}"`.
- **Filter**: `all | wins | losses` by class (`flat` rows appear only under All) AND symbol search: `needle = query.trim().toUpperCase()`; empty matches all, else `symbol.toUpperCase().includes(needle)`.
- **Sort** keys `symbol | entry | exit | hold | pnl | return`, direction `asc | desc`, or none (= API order, **unchanged default**). Missing values (`null` hold/return/entry date) sort **last in both directions**; ties keep the original API order (stable, index tiebreak). Dates compared as the `slice(0,10)` strings; `pnl` by `realizedPnlDollar`; `return` by `returnPct`; `symbol` by `localeCompare`-free uppercase string compare. The sort never mutates `history`.
- **Stats follow the filter**: the strip is `computeTradeStats(filteredRows, stopPct)` over the filtered rows (before sort — sort cannot change a statistic).

### Pinned fixture (the 2026-11-17 numbers)

Eight rows. Wins +400, +360. Losses −1000, −900, −655, −500, −300. One flat 0. Option losses' `realizedPnlPct`: −99, −85, −70, −65, −40 (stop 0.60 → 4 past the stop of 5 option losses). Hold days per row (any order): 6, 111, 100, 90, 80, 70, 60, 91. Expected: winRate `29%` (2 wins · 5 losses · 1 flat), avgWin +$380, avgLoss −$671, lossToWin 1.8, profitFactor `0.23` (760/3355 = 0.2265), total −$2,595, expectancy −$324 (−324.375), hold `76 days (6–111)`, past stop `4 of 5`.

## 4. Journal link decision

`JournalEntry.position_id` carries the position's `recId`, but `GET /journal/entries` has **no `position_id` filter** (filters: symbol, strategy_tag, status, entry_type, date range) and the journal page filters server-side. So the link is **`/journal?symbol=<SYMBOL>`**, not recId and not an exit-date range (a journal entry dates the *trade entry*, so an exit-date window would hide it). The Journal page reads `symbol` from `window.location.search` **in a mount effect** (not `useSearchParams`, which would force a Suspense boundary and risks the `next build` prerender) and seeds its symbol filter. Symbol is `encodeURIComponent`-ed.

## 5. Remove × behaviour

Click × → inline confirm strip above the list: `Remove ${tradeLabel} from history? This changes realized totals.` + Confirm / Cancel. Nothing is DELETEd before Confirm. Confirm → `await removeHistory(id)` → `fetchPerformance()` (the realized figures and curve are server-computed; the existing × never refetched them, so the page kept showing the removed trade's P&L in the strip and curve — this is the stale number the confirm text warns about). `removeHistory` is fixed to drop the row locally **only on a 2xx/204 or a 404** response (today a 500 removes the row from the screen while it still counts server-side). Only one confirm open at a time; opening × on another row replaces it; changing tab/filter that hides the row closes it. Clear all keeps its existing confirm and refetch.

## 6. Stepped realized curve

`PnlChart`: the realized series uses `lineType: LineType.WithSteps` (horizontal to the next close date, then vertical), the Total-value/Open series stay plain lines. Set via `applyOptions` in the data effect keyed on `kind`, so switching kind never leaves a stepped equity line. The server already emits one cumulative point per distinct exit date, so seven closes on one day are one vertical step. No other change to the curve data, resampling or the (intentional) absence of a stale notice for realized.

## 7. Tickets (sequential; one file region each)

All tickets: tests first; run `npx eslint` on every changed file (lint errors fail `next build`), `npm run typecheck`, the touched suites (`--runInBand`, no real worker/MessageChannel handles). Page files in `frontend/app/(frame)/portfolio/` are CRLF — preserve. New CSS goes in one new block at the end of `page.module.css`; do not reformat existing rules.

**T1 — `tradeStats.ts` (pure)** — `frontend/lib/tradeStats.ts`, `frontend/lib/__tests__/tradeStats.test.ts`. Implements §3 exactly: `classOf`, `holdDays`, `returnPct`, `exitCheck`, `computeTradeStats`, `filterTrades`, `sortTrades`, `tradeLabel`. Header documents formulas, the "row = close event" caveat, and the EXIT-RECORD extension point (`exitCheck` takes the stop as an argument; #664 passes the stored stop-at-entry instead of the global). Tests: the pinned fixture; no trades (all `null`, count 0); no losses (profitFactor `null`, avgLoss `null`); no wins; all flat (winRate `null`, expectancy 0); missing entry date; invalid date `2026-02-31`; exit before entry; same-day hold 0; datetime suffix stripped; zero-cost option (`returnPct null`, exitCheck not past-stop); stock loss excluded from `of`; unknown contract; stop invalid; `lossPct` exactly 60.00 → within; 60.4 label `Lost 60.4%`; non-finite dollar dropped and counted in `skipped`; filter wins/losses/all (flat only in all); search case-insensitive substring and whitespace; sort every key both ways, nulls last both ways, stable ties, input not mutated, no-sort returns API order.

**T2 — store + stepped curve** — `frontend/lib/performanceStore.ts`, `frontend/components/organisms/PnlChart/index.tsx` (+ `frontend/__mocks__/lightweight-charts.js` if `LineType` is missing), tests in `frontend/lib/__tests__/` and `PnlChart/__tests__/`. `removeHistory` per §5 (returns a boolean for the page: removed or not). `PnlChart` per §6. Tests: remove on 204/200/404 drops the row; on 500 and on network error keeps it; realized applies `WithSteps`, equity does not, switching back and forth.

**T3 — stats strip, columns, filter/search/sort UI** — new `frontend/app/(frame)/portfolio/TradeStatsStrip.tsx`, `page.tsx` History panel, `page.module.css` (new block), tests `frontend/app/(frame)/portfolio/__tests__/historyInsights.test.tsx`. Filter bar (All/Wins/Losses radio-style buttons with `aria-pressed`, symbol search input with label, "showing N of M" line) between toolbar and list; strip above the chart? **Placement: directly above the chart, as the issue says**, over the filtered rows. Columns appended before ×: RETURN, HOLD, EXIT CHECK (header tooltip §3). Sortable headers are real `<button>`s with `aria-sort` on the header cell; DATES holds two sort buttons (ENTRY, EXIT). Empty-after-filter message "No trades match this filter." (the existing "No closed trades yet." stays for an empty history; the strip shows `—` for everything when no trades). Stop value is `useSettingsStore.premiumStopPct`. Tests: strip renders the fixture numbers through the real page; stats change with each filter and with search; columns render `—` for missing entry date; sort order of rows; heatmap/CSV still receive the full history; `grid-template-columns` constant extended (not rewritten) so existing columns keep their order.

**T4 — remove confirm + journal link + journal page seed** — `page.tsx`, `page.module.css` (same block), `frontend/app/(frame)/journal/page.tsx`, tests (`historyRemoveConfirm.test.tsx`, `journalSymbolParam.test.tsx`). Per §4 and §5. Tests: × alone issues no fetch; Cancel issues no fetch; Confirm issues exactly one DELETE for that id then a performance refetch; failed delete keeps the row and does not claim removal; confirm text exact for option and stock; journal link `href` for `NFLX` and a symbol with `.`/`&` is encoded; Journal page seeds the symbol filter from `?symbol=` and an absent param changes nothing.

## 8. Acceptance (from #663) mapping

- tradeStats tests reproduce the 2026-11-17 numbers + edge cases → T1.
- Filter/sort/search tests, stats follow filter → T1 + T3.
- × confirm, DELETE only on Confirm → T4.
- Mapping rows 61, 62, 64, 66, 67, 68 (flag part), 69, 70 present; heatmap, toolbar, existing columns unchanged → T2–T4 (row 68's exit-reason column is #664's).
- Typecheck + full tests (full suite may time out under load: rerun failing suites alone) + eslint on changed files; plan audit and code audit clean.
