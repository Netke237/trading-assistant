# PORTFOLIO-NUMBERS — implementation plan (board item #657)

- **Phase id:** `PORTFOLIO-NUMBERS` · **Tracking issue = board item:** #657 · **Umbrella / spec:** #656, mapping rows 9, 12 (label only), 17, 20, 30, 34, 39, 40, 41, 60, 65
- **Branch:** `board/portfolio-numbers-3b6830e9` (cut from `origin/main` 8268d4c7)
- **Decision:** Kenneth in chat 2026-11-17, "Move all to ticket" (approves the preview's NEW rows); "Take no information away".
- **Frontend only.** No backend, persistence, API, broker or risk-limit change.

## 1. Goal

Every number on the Portfolio page and its right rail is correct and in consistent units; contracts and money are readable. Nothing on the page disappears.

## 2. Confirmed defects this phase fixes (evidence, 2026-11-17 live :8000)

Live `GET /api/portfolio` (contracts = 1 each):

| Row | entry → now | underlying | delta | theta / share | pnl |
|---|---|---|---|---|---|
| `CMG\|40\|2027-06-17\|C` | 2.90 → 3.03 | 36.06 | 0.4452 | −0.011 | +13 |
| `NCLH\|20\|2027-06-17\|C` | 2.41 → 1.91 | 17.70 | 0.478 | −0.0071 | −50 |
| `BMY\|67\|2027-03-19\|C` | 5.78 → no quote (`quoteUnavailable`) | 60.95 | — | — | — |

(These are the review-time figures behind #656's −7.5 % / −7.0 %; the 17:4x refresh had CMG 3.00 / NCLH 1.97, same greeks.)

- **D1 theta units.** `frontend/app/(frame)/@contextRail/portfolio/page.tsx:34-37` multiplies delta by 100 per option contract but not theta: the rail shows `−0.0` instead of **−$1.81 / day** (−0.011 × 100 + −0.0071 × 100). The table's Θ/DAY column shows per-share theta (`−0.01`) and is always red.
- **D2 return denominator.** `frontend/lib/portfolioTotals.ts:38` divides open P&L by current market value: −37 / 494 = **−7.49 %**. On cost basis (the per-row % is vs entry): −37 / 531 = **−6.97 %**.
- **D3 polish.** Raw contract keys (`CMG|40|2027-06-17|C`), `$-44` sign format, perf strip labels say "Today/Week/…" though the numbers are realized P&L only, stale "mock only" header comment in `portfolio/page.tsx`.

## 3. Design decisions (made here, within the item's scope)

1. **`openPnLPct` switches to cost basis** (the item allows "switch them all"). `openTotals()` gains `costBasis` = Σ over quoted rows of `entryPrice × multiplier × contracts` (multiplier 1 for `|STOCK`, else 100; `contracts ?? 1`). `openPnLPct = costBasis > 0 ? openPnL / costBasis × 100 : 0`. Consumers: Portfolio footer (relabelled "Return on cost") and the Dashboard "Portfolio" card's "Return" stat (`app/(frame)/dashboard/page.tsx:265`), which follows automatically with **no edit to that file**; RailQuickLook and the Dashboard rail read `deployed` / `openPnL` / `winners` / `quoted` / `unquoted` only, unchanged. `deployed`, `exposureMark()`, `lib/risk.ts`, `lib/riskStore.ts` and every risk limit are untouched.
2. **Multiplier inside `portfolioTotals.ts`** stays the local `endsWith('|STOCK') ? 1 : 100` rule (identical to `positionMultiplier` in `lib/risk.ts`); importing `lib/risk.ts` would create an import cycle (`risk.ts` imports `exposureMark` from `portfolioTotals.ts`).
3. **Greek aggregation becomes one pure helper** `aggregateGreeks(positions)` in `lib/portfolioTotals.ts` (spec in Task 1). The share-equivalent delta keeps today's exact formula and its `hasGreeks` null rule, so the rail's delta number is unchanged ("same number", row 39). Stock rows: the backend sends `delta: null, theta: null` for `|STOCK` (`backend/app/data/market.py:2118-2124`), so a stock row adds 0 to share-equiv. delta and to theta exactly as today, and is left out of "Δ in dollars" and counted in its note (item scope 2 rule). Treating a stock share as delta ±1 would change the delta number and is not in scope; logged in §8.
4. **Money format** `formatMoney()` (new `frontend/lib/portfolioFormat.ts`): Unicode minus U+2212, `$` after the sign, optional `+` for positives, `$0` for anything that rounds to zero (never `−$0` / `+$0`), `en-US` grouping (`−$2,595`) fixed explicitly so output does not depend on the browser or Jest locale. Rounding keeps today's `Math.round` semantics (half toward +∞), so every whole-dollar figure has the same magnitude as before. Theta uses 2 decimals (`−$1.10`), everything else on this page 0 decimals as today.
5. **Percent format** `formatSignedPct(v, decimals = 1)`: today's `toFixed` digits, `+` for positives, U+2212 for negatives, `0.0%` when it rounds to zero. Row P&L % keeps 1 decimal; footer "Return on cost" moves from 2 to **1** decimal to match the item's acceptance (`−7.0%`). The Dashboard card keeps its own 2-decimal ASCII format (file not touched; same underlying number).
6. **Readable contract** `readableContract(key)` (same new file): `CMG|40|2027-06-17|C` → `40C · 17 Jun 27`; `BMY|187.5|2027-03-05|P` → `187.5P · 5 Mar 27` (strike exactly as `parseContractId` parses it, day without leading zero, English month abbreviations from a fixed array, 2-digit year); `XYZ|STOCK` → `Stock`; anything `parseContractId` (`lib/contractGrading.ts:134`) rejects → the key unchanged. The raw key stays in a `title` attribute on a wrapping `<span>` (the `Text` primitive has no `title` prop). `aria-label="Edit <raw key>"`, React keys, `editing`/`closing` state and the CSV export (`lib/portfolioHistory.ts` `toHistoryCsv`) keep the raw key. `contractLabel()` in `types/domain.ts` is not used: its `"AAPL 220C 05/16/27"` shape differs from the approved "40C · 17 Jun 27" and `types/domain.ts` is outside this item's Touches.
7. **EditDrawer** (`app/(frame)/portfolio/EditDrawer.tsx`) is outside this item's Touches and owned by PORTFOLIO-EDITOR-LAYOUT (#662); it prints only unsigned prices/limits, none in this item's mapping rows. Not changed.

## 4. Files

| File | Tasks |
|---|---|
| `frontend/lib/portfolioFormat.ts` (new) | 1 |
| `frontend/lib/__tests__/portfolioFormat.test.ts` (new) | 1 |
| `frontend/lib/portfolioTotals.ts` | 1 |
| `frontend/lib/__tests__/portfolioTotals.test.ts` (new) | 1 |
| `frontend/test-utils/portfolioFixture20261117.ts` (new; outside `__tests__` so Jest does not collect it as a suite) | 1 |
| `frontend/app/(frame)/@contextRail/portfolio/page.tsx` | 2 |
| `frontend/app/(frame)/@contextRail/portfolio/__tests__/page.test.tsx` | 2 |
| `frontend/app/(frame)/portfolio/page.tsx` | 3 |
| `frontend/app/(frame)/portfolio/__tests__/quoteUnavailable.test.tsx` | 3 |
| `frontend/app/(frame)/portfolio/__tests__/portfolioNumbers.test.tsx` (new) | 3 |
| `frontend/components/organisms/ClosePositionDrawer/index.tsx` | 3 |
| `frontend/components/organisms/ClosePositionDrawer/__tests__/ClosePositionDrawer.test.tsx` | 3 |

Tasks are sequential: 2 and 3 import Task 1's helpers; 2 and 3 share no file.

Commands (from `frontend/`): `npm run typecheck`, `npm run test` (full), `npm run test -- --testPathPattern=<name>` (focused).

## 5. Tasks

### Task 1 — formatting helpers, cost basis, greek aggregation, shared fixture

**Fixture** `frontend/test-utils/portfolioFixture20261117.ts` exports `portfolio20261117(): PortfolioPosition[]` returning the three §2 rows (fresh objects per call), each a complete `PortfolioPosition` (copy the `makePosition` field set from `app/(frame)/portfolio/__tests__/quoteUnavailable.test.tsx:15-24`): 
- CMG: contract `CMG|40|2027-06-17|C`, Bullish, entryPrice 2.90, currentPrice 3.03, currentStockPrice 36.06, delta 0.4452, theta −0.011, pnlDollar 13, pnlPct 4.48, contracts 1, recId `REC-CMG`.
- NCLH: `NCLH|20|2027-06-17|C`, Bullish, 2.41 → 1.91, currentStockPrice 17.70, delta 0.478, theta −0.0071, pnlDollar −50, pnlPct −20.75, contracts 1, recId `REC-NCLH`.
- BMY: `BMY|67|2027-03-19|C`, Bullish, entryPrice 5.78, currentPrice 0, currentStockPrice 60.95, no delta/theta, pnlDollar 0, pnlPct 0, `quoteUnavailable: true`, contracts 1, recId `REC-BMY`.
All with `status: 'PENDING'`, `stop: null`, `targets: []`, distinct `symbol`.

**`frontend/lib/portfolioFormat.ts`** (new, pure, no React):
```ts
export const MINUS = '−';
export function formatMoney(value: number, opts?: { decimals?: 0 | 2; plus?: boolean }): string
export function formatSignedPct(value: number, decimals?: number): string   // default 1
export function readableContract(key: string): string
export function moneyTone(value: number, decimals?: 0 | 2): 'pass' | 'reject' | undefined
```
- `formatMoney`: non-finite → `'—'`. `d = decimals ?? 0`; `r = Math.round(value * 10**d) / 10**d`; `body = Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })`; `r < 0` → `MINUS + '$' + body`; `r > 0 && plus` → `'+$' + body`; else `'$' + body` (covers `r === 0` and `-0` → `$0` / `$0.00`).
- `formatSignedPct`: non-finite → `'—'`; `s = Math.abs(value).toFixed(decimals)`; `n = Number(value.toFixed(decimals))`; `n > 0` → `'+' + s + '%'`; `n < 0` → `MINUS + s + '%'`; else `(0).toFixed(decimals) + '%'`.
- `moneyTone`: tone from the value **as `formatMoney` rounds it** (same `d`, same `Math.round`): `< 0` → `'reject'`, `> 0` → `'pass'`, `0` or non-finite → `undefined`. (Jest maps CSS modules to `{}`, so tone classes are not observable in the DOM; the tone rule is pinned here, and components must call this helper rather than re-deriving it.)
- `readableContract`: as decided in §3.6. `MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']`; month index from the expiry's `MM` (out of range → return key); day `String(Number(DD))`; year `YYYY.slice(2)`; strike `String(parsed.strike)`.

**`frontend/lib/portfolioTotals.ts`**:
- `OpenTotals` gains `costBasis: number` (doc: "Σ entryPrice × multiplier × contracts over the quoted rows"); `openPnLPct` doc becomes "openPnL / costBasis in percent (return on cost), 0 when costBasis ≤ 0". Header comment updated to say the percent is on cost basis and that the Dashboard card shares it.
- `export function positionThetaDollars(p: PortfolioPosition): number | null` → `p.theta` finite ? `p.theta × multiplier × (p.contracts ?? 1)` : `null` (null and undefined both → null).
- `export interface GreekTotals { deltaShares: number | null; thetaDollars: number | null; deltaDollars: number | null; deltaDollarsExcluded: number }` and `export function aggregateGreeks(positions): GreekTotals`:
  - `hasGreeks = positions.some(p => p.delta != null || p.theta != null)` (today's rule, rail `page.tsx:32`).
  - `deltaShares = hasGreeks ? Σ (p.delta ?? 0) × multiplier × (p.contracts ?? 1) : null` (today's formula, unrounded).
  - `thetaDollars = hasGreeks ? Σ (positionThetaDollars(p) ?? 0) : null`.
  - A row is **in** delta-dollars iff `p.delta` is a finite number and `underlying > 0` and finite, where `underlying = |STOCK ? (p.quoteUnavailable ? NaN : p.currentPrice) : p.currentStockPrice`. `deltaDollars = included.length ? Σ delta × multiplier × contracts × underlying : null`; `deltaDollarsExcluded = positions.length − included.length`.
- Add `export function deltaDollarsNote(excluded: number): string | null` → `null` when ≤ 0, else `` `Δ in dollars excludes ${n} position${n === 1 ? '' : 's'} without delta or underlying price` ``.
- `exposureMark`, `unquotedNote` unchanged.

**Tests first** (`lib/__tests__/portfolioFormat.test.ts`, `lib/__tests__/portfolioTotals.test.ts`); they fail with "Cannot find module" / missing export before the change:
- `formatMoney`: −564 → `−$564` (assert the char is U+2212); 89 with plus → `+$89`; 89 without plus → `$89`; 0, −0, −0.4 and 0.4 with plus → `$0`; −2595 → `−$2,595`; 1234567 plus → `+$1,234,567`; −44.5 → `−$44` (Math.round parity with today); −1.1 decimals 2 → `−$1.10`; −1.81 decimals 2 → `−$1.81`; 0.004 decimals 2 → `$0.00`; NaN → `—`.
- `moneyTone`: −0.004 decimals 2 → undefined; −0.006 decimals 2 → `'reject'`; 0.02 decimals 2 → `'pass'`; −0.4 (decimals 0) → undefined; NaN → undefined.
- `formatSignedPct`: −18.26 → `−18.3%`; 4.48 → `+4.5%`; −0.04 → `0.0%`; −6.968 → `−7.0%`; 20 → `+20.0%`; −10 → `−10.0%`; Infinity → `—`.
- `readableContract`: `CMG|40|2027-06-17|C` → `40C · 17 Jun 27`; `BMY|187.5|2027-03-05|P` → `187.5P · 5 Mar 27`; `BA|STOCK` → `Stock`; `garbage` → `garbage`; `AAPL|185|2027-13-15|C` → unchanged key.
- `openTotals(portfolio20261117())`: deployed 494, openPnL −37, costBasis 531, openPnLPct ≈ −6.968 (`toBeCloseTo(-6.968, 3)`), quoted 2, unquoted 1. Mixed: a 3-contract option (entry 1.00) + a 10-share `X|STOCK` (entry 50) quoted → costBasis 300 + 500 = 800. costBasis 0 (entryPrice 0) → openPnLPct 0.
- `aggregateGreeks(portfolio20261117())`: deltaShares ≈ 92.32, thetaDollars ≈ −1.81 (`toBeCloseTo(-1.81, 6)`), deltaDollars ≈ 0.4452×100×36.06 + 0.478×100×17.70 = 2451.45 (`toBeCloseTo(2451.45, 2)`), deltaDollarsExcluded 1. Mixed contracts: theta −0.05 with contracts 3 → −15; a `|STOCK` row with theta 0.02 and 10 shares → +0.2 (×1). No greeks anywhere → all three null, excluded = positions.length. A row with delta but `currentStockPrice` undefined → excluded. Theta `null` row → `positionThetaDollars` null.

**Commit:** `feat(portfolio): money/percent/contract formatters, return on cost, greek dollars (PORTFOLIO-NUMBERS T1)`

### Task 2 — right rail (rows 39, 40, 41; rail money)

`frontend/app/(frame)/@contextRail/portfolio/page.tsx`:
- Replace the inline `hasGreeks` / `aggDelta` / `aggTheta` block with `aggregateGreeks(positions)`.
- Totals: Deployed → `formatMoney(deployed)`; Open P&L → `formatMoney(openPnL, { plus: true })` (tone rule unchanged).
- Aggregate Greeks section, in this order:
  1. label `Δ Delta (share-equiv.)`, value `deltaShares != null ? deltaShares.toFixed(2) : '—'` (string identical to today's).
  2. **new** label `Δ in dollars`, value `deltaDollars != null ? formatMoney(deltaDollars) : '—'`, no tone.
  3. label `Θ Theta / day`, value `thetaDollars != null ? formatMoney(thetaDollars, { decimals: 2, plus: true }) : '—'`; tone `moneyTone(thetaDollars, 2)`.
  4. `deltaDollarsNote(deltaDollarsExcluded)` as `<Text size={11} tone="caution">` when non-null **and** `deltaShares != null` (no note when nothing has greeks, where both rows already read `—`).
- Header comment: one line saying greeks are summed per position as θ/Δ × multiplier × contracts (dollars per day for theta).

**Tests first** (append to `@contextRail/portfolio/__tests__/page.test.tsx`, keeping its existing mocks): seed `usePortfolioStore` with `portfolio20261117()`; expect texts `Δ Delta (share-equiv.)`, `92.32`, `Δ in dollars`, `$2,451`, `−$1.81` (tone is not DOM-observable under the CSS-module mock; it is pinned by Task 1's `moneyTone` tests), `Δ in dollars excludes 1 position without delta or underlying price`, Deployed `$494`, Open P&L `−$37`, `Excludes 1 position without a quote` (unchanged). A no-greeks portfolio shows `—` for all three and no delta-dollars note. Before the change these fail (`−0.0` / missing labels).

**Commit:** `fix(portfolio-rail): theta in dollars per day, delta share-equiv. label, delta in dollars (PORTFOLIO-NUMBERS T2)`

### Task 3 — Portfolio page and close dialog (rows 9, 12 label, 17, 20, 30, 34, 60, 65)

`frontend/app/(frame)/portfolio/page.tsx`:
- Header comment (lines 3-8): replace with an accurate one — the page lists open positions (synced from the backend every 30 s) with a totals footer, an editor drawer per row, a close dialog, and a History tab; no "in-memory" / "mock only" wording.
- Perf strip: labels `Realized today`, `Realized this week`, `Realized this month`, `Realized this year`; `PerfStat` value → `formatMoney(value, { plus: true })`; periods and tone unchanged.
- Open table, contract cell: `<span title={p.contract}><Text size={12} tone="secondary">{readableContract(p.contract)}</Text></span>` followed by the unchanged source badges.
- P&L cell: `formatMoney(p.pnlDollar, { plus: true })` and `formatSignedPct(p.pnlPct, 1)`; quote-unavailable branch and tones unchanged.
- Θ column: header text `Θ $/DAY`; cell `const th = positionThetaDollars(p)`; `th == null` → `—` with no tone; else `formatMoney(th, { decimals: 2, plus: true })`, tone `moneyTone(th, 2)`. In `COLUMNS` widen that 10th track from `60px` to `76px` (fits `−$150.00`); nothing else in the grid changes.
- Footer: Deployed `formatMoney(deployed)`; Open P&L `formatMoney(openPnL, { plus: true })`; label `Return` → `Return on cost`, value `formatSignedPct(openPnLPct, 1)` (tone rule unchanged); **new** group after it: label `Θ per day`, value from `aggregateGreeks(positions).thetaDollars` formatted and toned exactly like the rail; `—` when null. W / L and the unquoted note unchanged.
- History rows: contract cell `<span title={h.contract}><Text …>{readableContract(h.contract)}</Text></span>`; P&L `formatMoney(h.realizedPnlDollar, { plus: true })`. Header labels, qty/price/date cells, remove button, toolbar, CSV button unchanged.

`frontend/components/organisms/ClosePositionDrawer/index.tsx`:
- Title: `<span title={position.contract}><Text size={12} weight={400}>Close {position.symbol} {readableContract(position.contract)}</Text></span>` (e.g. `Close CMG 40C · 17 Jun 27`).
- Realized P&L: `{formatMoney(realizedDollar, { plus: true })}{'  '}({formatSignedPct(realizedPct, 1)})`; `realizedDollar` / `realizedPct` computation and tone unchanged.

**Tests first:**
- New `app/(frame)/portfolio/__tests__/portfolioNumbers.test.tsx` (mock `PnlChart`/`PnlHeatmap` like `quoteUnavailable.test.tsx`; seed `portfolio20261117()` and a `usePerformanceStore` state with `performance.realizedToday = -2595` (other periods 0, 89, 0) and one history row `{ contract: 'NFLX|82|2026-10-16|C', realizedPnlDollar: -564, … }`):
  - CMG row: text `40C · 17 Jun 27` inside an element with `title="CMG|40|2027-06-17|C"`; raw key text not rendered as visible text; P&L `+$13` / `+4.5%`; NCLH `−$50` / `−20.8%` (−20.75 → toFixed(1) "20.8"; assert what `formatSignedPct` returns); Θ header `Θ $/DAY`; CMG Θ `−$1.10`, NCLH `−$0.71`; BMY Θ `—`.
  - Footer: `Return on cost`, `−7.0%`, `Θ per day`, `−$1.81`, Deployed `$494`, Open P&L `−$37`.
  - Perf strip: `Realized today` with `−$2,595`, `Realized this week` with `+$89`, `Realized this month`, `Realized this year` with `$0`.
  - History tab (click `History (1)`): `82C · 16 Oct 26` with `title="NFLX|82|2026-10-16|C"`, `−$564`.
  - A positive-theta row (theta +0.02, 1 contract) renders `+$2.00`.
- `quoteUnavailable.test.tsx`: `rowOf(contract)` (line 26) finds the row through the element whose `title` is the raw key (`container.querySelector(`[title="${contract}"]`)`), not visible text; expectations `+$20` / `+20.0%` / `$120` stay valid; add `Return on cost`.
- `ClosePositionDrawer.test.tsx`: `$-50` → `−$50`, `-10.0%` → `−10.0%`, `$-200` → `−$200`, `-50.0%` → `−50.0%`, `+$1000` → `+$1,000`; add a title test for an option key (`Close AAPL 185C · 15 Jan 27`, `title` raw) and for `AAPL|STOCK` (`Close AAPL Stock`).

**Commit:** `fix(portfolio): theta $/day column and footer, return on cost, readable contracts, signed money (PORTFOLIO-NUMBERS T3)`

### Task 4 — coordinator: verify, "nothing disappears", code audit, PR

1. Full `npm run typecheck` + `npm run test` on the integrated branch.
2. **Rendered-text diff.** A throwaway Jest file in the scratchpad (never committed) renders `PortfolioPage` (Open tab, History tab, the close dialog opened for CMG) and `PortfolioContextRail` with `portfolio20261117()` and prints every text node and every `title`/`aria-label` attribute. Run it against the branch and against `origin/main`'s versions of the five Task 2/3 source files (restored temporarily with `git show origin/main:<path> > <path>`, then `git checkout -- <path>`). Every removed or changed line must map to one of rows 9, 12, 17, 20, 30, 34, 39, 40, 41, 60, 65; every raw contract key must still be present as a `title`. Result recorded in the PR body.
3. `git merge origin/main` (re-run typecheck + tests) immediately before code-audit round 1; audit `origin/main..HEAD` with fresh gate auditors (cap 3).
4. PR `Closes #657`, then `board.md` step 7.

## 6. Acceptance mapping (item #657)

| Item acceptance | Where |
|---|---|
| Unit tests: theta/delta aggregation (option + stock, mixed contracts, missing greeks); return on cost; money formatter (negative, zero, thousands) | Task 1 |
| Fixtures CMG/NCLH/BMY: rail Θ −$1.81, Δ 92.3 (renders `92.32`, 2 decimals as today), footer Return on cost −7.0 % (was −7.5 %) | Tasks 1-3 tests |
| Rows 9, 17, 20, 30, 34, 39, 40, 41, 60, 65 as specified; row 12 label; nothing else disappears | Tasks 2-3 tests + Task 4 step 2 |
| Typecheck + full tests; plan and code audit clean | Task 4 |

## 7. Out of scope

Layout moves (RISK-VIEW #660), status derivation, sync/loading state (#661), editor (#662), history insights (#663), contrast (#659), backend (#658, #664), the Dashboard card's own formatting, `PnlChart` / `PnlHeatmap`.

## 8. Logged, not fixed (below this item's scope)

- Backend `routers/portfolio.py` computes `pnlDollar` as `(current − entry) × mult × qty` with no sign flip for a Bearish `|STOCK` (short) row, while `ClosePositionDrawer` flips it; a short stock row's open P&L sign may be inverted. Belongs to a backend item.
- Stock rows carry no delta from the backend, so share-equiv. delta and delta-in-dollars omit stock exposure (now disclosed by the delta-dollars note).
