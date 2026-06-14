# Stocks Tab Redesign — Design Spec

**Date:** 2026-06-14
**Author:** Kenneth / Claude

---

## Goal

Replace the current 7-step stocks workflow with a single self-contained "Stocks" page at Step 4, keeping the first three steps (Regime, Universe, Direction) shared between options and stocks modes.

---

## Background & motivation

The current stocks flow has two problems:

1. **Architectural mismatch (now fixed):** before the 2026-06-14 decoupling fix, the stock scan used the options candidates as its symbol pool — meaning IV rank and options liquidity filtered the universe before any stock-quality scoring ran. That fix has already landed (`step-5-strategy/page.tsx`, `scanParamsStore.ts`).

2. **UX fragmentation:** strategy selection, backtest log, results table, and position card are spread across four separate pages (Steps 4–7). This makes iteration slow and hides context — you can't see the log and the results table at the same time.

---

## Architecture

### Step counts

| Mode | Before | After |
|---|---|---|
| Options | 7 steps (unchanged) | 7 steps (unchanged) |
| Stocks | 7 steps | **4 steps** |

### Stocks stepper after redesign

| # | Slug | Notes |
|---|---|---|
| 1 | `step-1-regime` | Shared, no change |
| 2 | `step-2-universe` | Shared, no change |
| 3 | `step-3-direction` | Shared, no change |
| 4 | `step-4-stocks` | **New combined page** |

`SCREENER_STEPS_STOCKS` in `frontend/components/organisms/Stepper/index.tsx` is updated to these 4 entries.

The pages `step-4-ranking`, `step-5-strategy`, `step-6-backtest`, `step-7-position-card` are **not deleted** — they remain in the filesystem (the options route still uses some of them, and the stocks-mode route previously used all of them). They are simply removed from `SCREENER_STEPS_STOCKS`.

---

## New page: `step-4-stocks`

**File:** `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
**CSS:** `frontend/app/(frame)/screener/step-4-stocks/page.module.css`

### Layout (vertical stack, single column)

```
┌─ Strategy ───────────────────────────────────────────────────────┐
│  [Pullback EMA ✓]  [Breakout]  [MA Cross]  [RSI Reversal]        │
│  ▸ Scan Parameters  (expandable — bt_min_trades, win rate, etc.) │
│  [Run Stock Scan]                                                 │
└───────────────────────────────────────────────────────────────────┘

┌─ Pipeline Log ────────────────────────────────────────────────────┐
│  ScanFunnel component (hidden before first run; collapsible       │
│  after run)                                                       │
│  Universe → Pre-screen → Score → Backtest Gate → PASS             │
└───────────────────────────────────────────────────────────────────┘

┌─ Results ─────────────────────────────────────────────────────────┐
│  SYMBOL  SCORE  Δ   WIN%   TRADES  RETURN  MAX DD  GATE           │
│  AAPL      78  ↑3   35%      34    +8.2%   −4.1%   PASS          │
│  ▼ MSFT    71   ─   41%      28    +6.1%   −3.5%   PASS  ← open  │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  Entry $415  Stop $401  Target $445  R:R 2.1x            │     │
│  │  24 shares · Risk $340 · Size $9,965 · Win% 41%          │     │
│  │  [View Chart]  [Pin to Basket]  [Add to Portfolio]       │     │
│  │  [IBKR Paper]  [Tradier Paper]  [Alpaca Paper]           │     │
│  └──────────────────────────────────────────────────────────┘     │
│  JPM       63  ↓2   26%      19    +3.4%   −5.8%   PASS          │
│  ▸ 412 rejected  (collapsed)                                      │
└───────────────────────────────────────────────────────────────────┘
```

### Section 1 — Strategy picker

Four strategy cards in a horizontal row. Selecting a card:
- Highlights it (active state)
- Updates `activeStockStrategy` in `scanStore`

Below the cards, an expandable "Scan Parameters" section exposes the same controls currently in `step-5-strategy`: `bt_min_trades`, `bt_min_win_rate`, lookback period, and any strategy-specific parameters. These read from / write to `scanParamsStore`.

**Run Stock Scan button:**
- Disabled (with tooltip "Select a strategy first") when `activeStockStrategy` is null
- In stocks mode the topbar "Run Scan" button is also wired to trigger a stock scan (mode-aware); the in-page button is the primary affordance
- On click: calls `api.postStockScan(...)` with `activeStockStrategy`, universe from context, direction and horizon from context
- While running: button shows spinner; previous results remain visible

### Section 2 — Pipeline log

Reuses the existing `ScanFunnel` component from `step-6-backtest`.

- Hidden before the first scan run
- Collapsible (collapsed by default after a run completes, so results are visible immediately)
- Full detail (stage counts, rejection reasons) expandable on demand
- All backtest gate logging is preserved — this is a direct reuse of the existing component, not a simplified version

### Section 3 — Results table

Columns:

| Column | Source | Notes |
|---|---|---|
| Symbol | `stockScanResult.candidates[].symbol` | Clickable to expand inline card |
| Score | `stock_score` | 0–100 |
| Δ | computed | `currentScore − previousScore` for matching symbol; dash on first run |
| Win % | `backtest.win_rate` | From backtest result |
| Trades | `backtest.num_trades` | |
| Return | `backtest.total_return_pct` | |
| Max DD | `backtest.max_drawdown_pct` | |
| Gate | `finalStatus` | PASS / CAUTION / REJECT pill using `StatusBadge` |

**Rank delta (Δrank):** shown as a secondary sub-value within the Δ cell — current rank position vs previous rank position (e.g. "↑3 / score +5"). Uses existing `RankDelta` component.

**Row expansion:** clicking a row toggles an inline accordion below it. Only one row open at a time. Clicking a second row closes the first.

**Rejected section:** collapsed by default at the bottom of the table. Shows all symbols that did not reach PASS, with their rejection stage and reason. This is a direct adaptation of the existing rejected section in `step-6-backtest`.

### Section 4 — Inline position card (accordion)

Displayed inside the expanded table row. Content:

**Sizing block:**
- Entry, Stop, Target prices
- R:R ratio
- Shares, Risk $, Position size $
- Strategy win rate (from backtest)

**Action buttons:**
- `[View Chart]` — opens the right-panel candle chart for the symbol (existing chart panel)
- `[Pin to Basket]` — adds `StockPositionCard` to `scanStore.stockBasket`; button toggles to "Unpin" if already pinned
- `[Add to Portfolio]` — opens a lightweight confirm dialog, then calls `portfolioStore.addPosition()`
- `[IBKR Paper]` / `[Tradier Paper]` / `[Alpaca Paper]` — paper execution buttons, same broker API calls as in the current `step-7-position-card`

---

## Data model changes

### `scanStore.ts`

Three new fields:

```ts
previousStockScanResult: StockScanResult | null   // set to old stockScanResult before each new scan
stockBasket: StockPositionCard[]                   // pinned position cards
activeStockStrategy: string | null                 // persisted strategy slug
```

Three new actions:

```ts
addToStockBasket(card: StockPositionCard): void
removeFromStockBasket(symbol: string): void
clearStockBasket(): void
setActiveStockStrategy(slug: string | null): void
```

On each successful scan: `previousStockScanResult = current stockScanResult` (swap before overwriting).

`StockPositionCard` type: all position sizing fields (entry, stop, target, rrRatio, shares, riskDollars, sizeDollars, winRate, symbol, strategy).

### `scanParamsStore.ts`

No schema changes — existing params already cover the strategy controls. `activeStockStrategy` belongs in `scanStore` (it's scan context, not a parameter).

---

## Run Scan — mode-aware behavior

In `screenerMode === 'stocks'`:
- Topbar "Run Scan" button label reads "Run Stock Scan"
- Button calls `api.postStockScan({ strategy: activeStockStrategy, universe, direction, horizon, bt_min_trades, bt_min_win_rate })`
- Button is disabled if `activeStockStrategy` is null

In `screenerMode === 'options'`:
- No change to existing behavior

---

## Stepper update

`SCREENER_STEPS_STOCKS` in `Stepper/index.tsx`:

```ts
export const SCREENER_STEPS_STOCKS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',    label: 'Market Regime'    },
  { index: 2, slug: 'step-2-universe',  label: 'Universe'         },
  { index: 3, slug: 'step-3-direction', label: 'Direction'        },
  { index: 4, slug: 'step-4-stocks',    label: 'Stocks'           },
];
```

`StepNavBar` reads this array; no changes to `StepNavBar` itself.

---

## What is NOT in scope

- **Bug #6 (Tradier Paper data source):** Tradier Paper not displaying as active in the context rail. Tracked separately.
- **Prewarm history button:** removed from the Stocks page. The `/api/scan/prewarm-candles` endpoint remains unchanged and can be wired into the Universe step later.
- **Deleting old stocks pages:** `step-4-ranking`, `step-5-strategy`, `step-6-backtest`, `step-7-position-card` stay in the codebase. Only the stepper array changes.
- **Backend changes:** none required for this redesign.

---

## Files to create / modify

| Action | Path |
|---|---|
| Create | `frontend/app/(frame)/screener/step-4-stocks/page.tsx` |
| Create | `frontend/app/(frame)/screener/step-4-stocks/page.module.css` |
| Create | `frontend/app/(frame)/screener/@contextRail/step-4-stocks/page.tsx` |
| Create | `frontend/app/(frame)/screener/@contextRail/step-4-stocks/default.tsx` |
| Modify | `frontend/components/organisms/Stepper/index.tsx` — update `SCREENER_STEPS_STOCKS` |
| Modify | `frontend/lib/scanStore.ts` — add `previousStockScanResult`, `stockBasket`, `activeStockStrategy` |
| Modify | `frontend/types/domain.ts` — add `StockPositionCard` type |

---

## Success criteria

1. In stocks mode, the stepper shows exactly 4 steps
2. Step 4 shows strategy cards, expandable params, pipeline log, results table, and inline position card — all on one page
3. Δscore / Δrank columns are empty on first run and populated on second run with the correct delta
4. All backtest gate details (ScanFunnel) are visible and collapsible
5. Pin to Basket, Add to Portfolio, and all three paper-execution buttons work
6. Options mode is completely unaffected (regression: existing tests pass)
7. `npm run typecheck` clean; `npm run test` green
