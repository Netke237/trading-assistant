# Stocks Tab Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 7-step stocks screener flow with a single self-contained `step-4-stocks` page (strategy picker → scan log → results table with deltas → inline position card), leaving the first three steps shared with options mode.

**Architecture:** Stocks mode's stepper drops from 7 to 4 entries. A new client page composes existing building blocks (`ScanFunnel`, the step-5 params panel, the step-6 backtest row, the step-7 position card actions). A shared `runStockScan()` helper centralises the scan call so both the in-page button and the topbar `RunScanButton` (mode-aware) use it. Two new scanStore fields (`previousStockScanResult`, `stockBasket`) back the delta columns and basket pinning.

**Tech Stack:** Next.js 15 App Router (`'use client'`), TypeScript 5.7 strict, CSS Modules, Zustand v5, Jest + @testing-library/react.

---

## Reconciliations with the spec

The spec was written before reading the code. These existing names/types are reused instead of inventing new ones — the plan below is authoritative:

| Spec said | Reality / plan uses |
|---|---|
| new `activeStockStrategy` | existing `scanStore.activeStrategy` (already present) |
| new `StockPositionCard` type | existing `PositionCardData` from `types/stockDomain.ts` (has every sizing field) |
| add `setActiveStockStrategy` | existing `setActiveStrategy` |
| create `@contextRail/.../step-4-stocks/*` | NOT needed — `@contextRail/screener/default.tsx` already covers unmatched segments |
| "Add to Portfolio" helper | existing `buildPaperStockPosition()` in `lib/paperTrade.ts` |
| "View Chart" | `Link` to existing route `/chart?symbol=SYMBOL` (ChartWorkspace reads `?symbol`) |

`stockBasket` and `previousStockScanResult` are genuinely new (options basket is page-local `useState`, not a store).

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Modify | `frontend/lib/scanStore.ts` | Add `previousStockScanResult` + swap; add `stockBasket` + actions; version 4→5 |
| Create | `frontend/lib/stockDelta.ts` | Pure delta computation (score + rank vs previous run) |
| Create | `frontend/lib/stockScan.ts` | Shared `runStockScan()` — builds request, calls API, updates store |
| Modify | `frontend/components/organisms/Stepper/index.tsx` | `SCREENER_STEPS_STOCKS` → 4 entries |
| Create | `frontend/components/organisms/StrategyParamsPanel/index.tsx` | Extracted strategy params `<details>` panel (shared) |
| Create | `frontend/components/organisms/StrategyParamsPanel/StrategyParamsPanel.module.css` | Moved styles for the panel |
| Modify | `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | Consume `StrategyParamsPanel` (keeps step-5 working) |
| Create | `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | The combined Stocks page |
| Create | `frontend/app/(frame)/screener/step-4-stocks/page.module.css` | Page styles |
| Modify | `frontend/components/organisms/RunScanButton/index.tsx` | Mode-aware: stocks → `runStockScan()` |

---

## Task 1: scanStore — `previousStockScanResult` + delta swap

**Files:**
- Modify: `frontend/lib/scanStore.ts`
- Test: `frontend/lib/__tests__/scanStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/lib/__tests__/scanStore.test.ts` inside the `describe('scanStore', …)` block:

```ts
it('shifts old stockScanResult into previousStockScanResult on new result', () => {
  const { result } = renderHook(() => useScanStore());
  const first  = { scan_id: 'S-1', timestamp: 't1', rejected: [], candidates: [] };
  const second = { scan_id: 'S-2', timestamp: 't2', rejected: [], candidates: [] };

  act(() => { result.current.setStockScanResult(first as any); });
  expect(result.current.stockScanResult).toEqual(first);
  expect(result.current.previousStockScanResult).toBeNull();

  act(() => { result.current.setStockScanResult(second as any); });
  expect(result.current.stockScanResult).toEqual(second);
  expect(result.current.previousStockScanResult).toEqual(first);
});

it('preserves previousStockScanResult when clearing stockScanResult', () => {
  const { result } = renderHook(() => useScanStore());
  const first  = { scan_id: 'S-1', timestamp: 't1', rejected: [], candidates: [] };
  const second = { scan_id: 'S-2', timestamp: 't2', rejected: [], candidates: [] };

  act(() => { result.current.setStockScanResult(first as any); });
  act(() => { result.current.setStockScanResult(second as any); });
  act(() => { result.current.setStockScanResult(null); });

  expect(result.current.stockScanResult).toBeNull();
  expect(result.current.previousStockScanResult).toEqual(first);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=scanStore`
Expected: FAIL — `previousStockScanResult` is undefined.

- [ ] **Step 3: Add the field + swap to the store**

In `frontend/lib/scanStore.ts`, in the `ScanStoreState` interface, add right after the `stockScanResult` line (currently line 75-76):

```ts
  stockScanResult:     StockScanResult | null;
  previousStockScanResult: StockScanResult | null;
  setStockScanResult:  (r: StockScanResult | null) => void;
```

In the store body, change the `stockScanResult` initial value and `setStockScanResult` (currently lines 115 and 118):

```ts
      stockScanResult:     null,
      previousStockScanResult: null,
```

```ts
      setStockScanResult:  (r) => set((state) => ({
        stockScanResult: r,
        previousStockScanResult: r !== null ? state.stockScanResult : state.previousStockScanResult,
      })),
```

In `partialize` (currently ends ~line 148), add `previousStockScanResult`:

```ts
        stockScanResult: state.stockScanResult,
        previousStockScanResult: state.previousStockScanResult,
```

Bump `version: 4` to `version: 5` and add a migration branch before `return prev;`:

```ts
        if (version < 5) return { ...prev, previousStockScanResult: null, stockBasket: [] };
```

(`stockBasket` is seeded here too so Task 2 needs no further migration.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=scanStore`
Expected: PASS (all scanStore tests green).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/scanStore.ts frontend/lib/__tests__/scanStore.test.ts
git commit -m "feat(stocks): track previousStockScanResult for deltas"
```

---

## Task 2: scanStore — `stockBasket` + actions

**Files:**
- Modify: `frontend/lib/scanStore.ts`
- Test: `frontend/lib/__tests__/scanStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to the `describe('scanStore', …)` block:

```ts
it('adds, dedupes by symbol, removes and clears the stock basket', () => {
  const { result } = renderHook(() => useScanStore());
  act(() => { useScanStore.setState({ stockBasket: [] }); });

  const aapl = { symbol: 'AAPL' } as any;
  const aapl2 = { symbol: 'AAPL' } as any;  // same symbol, newer card
  const msft = { symbol: 'MSFT' } as any;

  act(() => { result.current.addToStockBasket(aapl); });
  act(() => { result.current.addToStockBasket(msft); });
  expect(result.current.stockBasket.map((c) => c.symbol)).toEqual(['AAPL', 'MSFT']);

  act(() => { result.current.addToStockBasket(aapl2); });   // replaces AAPL, no dupe
  expect(result.current.stockBasket.filter((c) => c.symbol === 'AAPL')).toHaveLength(1);

  act(() => { result.current.removeFromStockBasket('AAPL'); });
  expect(result.current.stockBasket.map((c) => c.symbol)).toEqual(['MSFT']);

  act(() => { result.current.clearStockBasket(); });
  expect(result.current.stockBasket).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=scanStore`
Expected: FAIL — `addToStockBasket` is not a function.

- [ ] **Step 3: Add basket state + actions**

In `frontend/lib/scanStore.ts`, add to the top imports (the domain import line) — `PositionCardData` lives in stockDomain, so extend that import:

```ts
import type { StockScanResult, PositionCardData } from '@/types/stockDomain';
```

In the `ScanStoreState` interface, add after `setStockScanResult`:

```ts
  stockBasket:           PositionCardData[];
  addToStockBasket:      (card: PositionCardData) => void;
  removeFromStockBasket: (symbol: string) => void;
  clearStockBasket:      () => void;
```

In the store body, add after `setStockScanResult`:

```ts
      stockBasket:           [],
      addToStockBasket:      (card) => set((s) => ({
        stockBasket: [...s.stockBasket.filter((c) => c.symbol !== card.symbol), card],
      })),
      removeFromStockBasket: (symbol) => set((s) => ({
        stockBasket: s.stockBasket.filter((c) => c.symbol !== symbol),
      })),
      clearStockBasket:      () => set({ stockBasket: [] }),
```

In `partialize`, add:

```ts
        stockBasket:     state.stockBasket,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=scanStore`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/scanStore.ts frontend/lib/__tests__/scanStore.test.ts
git commit -m "feat(stocks): add stockBasket state + actions to scanStore"
```

---

## Task 3: Pure delta helper `lib/stockDelta.ts`

**Files:**
- Create: `frontend/lib/stockDelta.ts`
- Test: `frontend/lib/__tests__/stockDelta.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/stockDelta.test.ts`:

```ts
import { computeStockDeltas } from '@/lib/stockDelta';
import type { StockScanResult } from '@/types/stockDomain';

function mk(symbols: Array<[string, number]>): StockScanResult {
  return {
    scan_id: 's', timestamp: 't', rejected: [],
    candidates: symbols.map(([symbol, stock_score]) => ({ symbol, stock_score } as any)),
  };
}

describe('computeStockDeltas', () => {
  it('returns empty map when previous is null', () => {
    const d = computeStockDeltas(mk([['AAPL', 80]]), null);
    expect(d.get('AAPL')).toBeUndefined();
  });

  it('computes score delta and rank delta vs previous run', () => {
    // previous order by score desc: MSFT(90, rank0), AAPL(70, rank1)
    const prev = mk([['MSFT', 90], ['AAPL', 70]]);
    // current order by score desc: AAPL(85, rank0), MSFT(80, rank1)
    const curr = mk([['AAPL', 85], ['MSFT', 80]]);

    const d = computeStockDeltas(curr, prev);
    expect(d.get('AAPL')).toEqual({ scoreDelta: 15, rankDelta: 1 });   // 85-70; moved 1→0 = +1
    expect(d.get('MSFT')).toEqual({ scoreDelta: -10, rankDelta: -1 }); // 80-90; moved 0→1 = -1
  });

  it('omits symbols not present in previous run', () => {
    const d = computeStockDeltas(mk([['NVDA', 50]]), mk([['AAPL', 80]]));
    expect(d.get('NVDA')).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=stockDelta`
Expected: FAIL — cannot find module `@/lib/stockDelta`.

- [ ] **Step 3: Implement the helper**

Create `frontend/lib/stockDelta.ts`:

```ts
import type { StockScanResult } from '@/types/stockDomain';

export interface StockDelta {
  scoreDelta: number;  // current score − previous score
  rankDelta:  number;  // positive = moved up (lower index) vs previous
}

/**
 * Build a symbol → delta map comparing the current run to the previous run.
 * Rank is the candidate's index in each run (already sorted by score desc by
 * the backend). Symbols absent from the previous run get no entry.
 */
export function computeStockDeltas(
  current: StockScanResult,
  previous: StockScanResult | null,
): Map<string, StockDelta> {
  const out = new Map<string, StockDelta>();
  if (!previous) return out;

  const prevRank  = new Map<string, number>();
  const prevScore = new Map<string, number>();
  previous.candidates.forEach((c, i) => {
    prevRank.set(c.symbol, i);
    prevScore.set(c.symbol, c.stock_score);
  });

  current.candidates.forEach((c, i) => {
    if (!prevRank.has(c.symbol)) return;
    out.set(c.symbol, {
      scoreDelta: c.stock_score - (prevScore.get(c.symbol) ?? c.stock_score),
      rankDelta:  (prevRank.get(c.symbol) ?? i) - i,
    });
  });

  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=stockDelta`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/stockDelta.ts frontend/lib/__tests__/stockDelta.test.ts
git commit -m "feat(stocks): pure delta helper for results table"
```

---

## Task 4: Shared `lib/stockScan.ts` runner

**Files:**
- Create: `frontend/lib/stockScan.ts`
- Test: `frontend/lib/__tests__/stockScan.test.ts`

**Context:** Today `step-5-strategy` builds the `postStockScan` request inline (page.tsx lines 122-158). We centralise that so both the new page and the topbar button share one code path. The helper reads `scanStore` (context, scanOverrides) and `scanParamsStore` (params) from `.getState()`, calls `api.postStockScan`, and writes the result + scan state into the store.

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/stockScan.test.ts`:

```ts
import { runStockScan } from '@/lib/stockScan';
import { useScanStore } from '@/lib/scanStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: { postStockScan: jest.fn() },
}));

describe('runStockScan', () => {
  beforeEach(() => {
    (api.postStockScan as jest.Mock).mockReset();
    useScanStore.setState({
      context: { universe: 'NAS100', direction: 'Bullish', horizon: 'Swing (5–15d)' },
      scanOverrides: {},
      stockScanResult: null,
      previousStockScanResult: null,
      activeStrategy: null,
      scanState: 'IDLE',
    } as any);
  });

  it('calls postStockScan with the strategy + universe and stores the result', async () => {
    const fake = { scan_id: 'S-1', timestamp: 't', rejected: [], candidates: [] };
    (api.postStockScan as jest.Mock).mockResolvedValue(fake);

    await runStockScan('pullback_ema');

    expect(api.postStockScan).toHaveBeenCalledTimes(1);
    const arg = (api.postStockScan as jest.Mock).mock.calls[0][0];
    expect(arg.strategy).toBe('pullback_ema');
    expect(arg.universe).toEqual(['NAS100']);
    expect(arg.direction).toBe('Bullish');
    expect(arg.horizon).toBe('Swing');
    expect(useScanStore.getState().stockScanResult).toEqual(fake);
    expect(useScanStore.getState().activeStrategy).toBe('pullback_ema');
  });

  it('sets scanState FAILED when the API throws', async () => {
    (api.postStockScan as jest.Mock).mockRejectedValue(new Error('boom'));
    await runStockScan('pullback_ema');
    expect(useScanStore.getState().scanState).toBe('FAILED');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=stockScan`
Expected: FAIL — cannot find module `@/lib/stockScan`.

- [ ] **Step 3: Implement the runner**

Create `frontend/lib/stockScan.ts`:

```ts
import { api } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import type { StockScanResult } from '@/types/stockDomain';

/** Optional per-run param overrides (the page passes its locally-edited params). */
export interface StockScanParamOverrides {
  pullbackTolerancePct?: number;
  pullbackEmaPeriod?: number;
  pullbackTrendEma?: number;
  pullbackMaType?: 'EMA' | 'SMA';
  maCrossoverFast?: number;
  maCrossoverSlow?: number;
  maCrossoverLookback?: number;
  breakoutVolumeMult?: number;
  rsiPeriod?: number;
  rsiOversold?: number;
  rsiTrendSma?: number;
  btMinTrades?: number;
  btMinWinRate?: number;
  stockShortlistMax?: number;
}

/**
 * Run a stock scan with `strategy`, reading universe/direction/horizon from
 * scanStore.context and parameters from scanParamsStore (overridable per-run).
 * Writes result + scanState into scanStore. Returns the result or null on error.
 */
export async function runStockScan(
  strategy: string,
  overrides: StockScanParamOverrides = {},
): Promise<StockScanResult | null> {
  const store  = useScanStore.getState();
  const saved  = useScanParamsStore.getState();
  const p = { ...saved, ...overrides };

  const context        = store.context;
  const requireReversal =
    (store.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  store.setActiveStrategy(strategy);
  store.setStockScanResult(null);
  store.setScanState('SCANNING');

  try {
    const result = await api.postStockScan({
      universe:  context?.universe ? [context.universe] : ['SP500'],
      direction: context?.direction ?? 'Bullish',
      horizon:   (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
      strategy,
      pullback_tolerance_pct:    p.pullbackTolerancePct,
      pullback_ema_period:       p.pullbackEmaPeriod,
      pullback_trend_ema:        p.pullbackTrendEma,
      pullback_ma_type:          p.pullbackMaType,
      pullback_require_reversal: requireReversal,
      ma_crossover_fast:      p.maCrossoverFast,
      ma_crossover_slow:      p.maCrossoverSlow,
      ma_crossover_lookback:  p.maCrossoverLookback,
      breakout_volume_mult:   p.breakoutVolumeMult,
      rsi_period:             p.rsiPeriod,
      rsi_oversold:           p.rsiOversold,
      rsi_trend_sma:          p.rsiTrendSma,
      bt_min_trades:          p.btMinTrades,
      bt_min_win_rate:        p.btMinWinRate,
      account_size: 50_000,
      risk_pct: 0.01,
      shortlist_max_candidates: p.stockShortlistMax,
    });
    store.setStockScanResult(result);
    store.setScanState('COMPLETED');
    return result;
  } catch {
    store.setScanState('FAILED');
    return null;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=stockScan`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/stockScan.ts frontend/lib/__tests__/stockScan.test.ts
git commit -m "feat(stocks): shared runStockScan helper"
```

---

## Task 5: Stepper — stocks mode has 4 steps

**Files:**
- Modify: `frontend/components/organisms/Stepper/index.tsx:32-40`
- Test: `frontend/components/organisms/Stepper/__tests__/Stepper.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/components/organisms/Stepper/__tests__/Stepper.test.tsx`:

```ts
import { SCREENER_STEPS_STOCKS, getSteps } from '@/components/organisms/Stepper';

describe('SCREENER_STEPS_STOCKS', () => {
  it('has exactly 4 steps ending at step-4-stocks', () => {
    expect(SCREENER_STEPS_STOCKS).toHaveLength(4);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.slug)).toEqual([
      'step-1-regime',
      'step-2-universe',
      'step-3-direction',
      'step-4-stocks',
    ]);
  });

  it('getSteps("stocks") returns the 4-step sequence', () => {
    expect(getSteps('stocks')).toBe(SCREENER_STEPS_STOCKS);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=Stepper`
Expected: FAIL — array has 7 entries / slug `step-4-ranking`.

- [ ] **Step 3: Update the array**

Replace `frontend/components/organisms/Stepper/index.tsx` lines 32-40 with:

```ts
export const SCREENER_STEPS_STOCKS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',    label: 'Market Regime' },
  { index: 2, slug: 'step-2-universe',  label: 'Universe'      },
  { index: 3, slug: 'step-3-direction', label: 'Direction'     },
  { index: 4, slug: 'step-4-stocks',    label: 'Stocks'        },
];
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=Stepper`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/Stepper/index.tsx frontend/components/organisms/Stepper/__tests__/Stepper.test.tsx
git commit -m "feat(stocks): collapse stocks stepper to 4 steps"
```

---

## Task 6: Extract `StrategyParamsPanel` component

**Files:**
- Create: `frontend/components/organisms/StrategyParamsPanel/index.tsx`
- Create: `frontend/components/organisms/StrategyParamsPanel/StrategyParamsPanel.module.css`
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`

**Context:** The params `<details>` block (step-5 page.tsx lines 193-482) is needed verbatim on the new page. Extract it once into a reusable component driven by a `params` object + `setParams` setter, plus `requireReversal`. This keeps step-5 working and lets step-4-stocks reuse it.

The `params` shape (the fields the panel reads/writes):

```ts
export interface StrategyParams {
  pullbackTolerancePct: number;
  pullbackEmaPeriod: number;
  pullbackTrendEma: number;
  pullbackMaType: 'EMA' | 'SMA';
  maCrossoverFast: number;
  maCrossoverSlow: number;
  maCrossoverLookback: number;
  breakoutVolumeMult: number;
  rsiPeriod: number;
  rsiOversold: number;
  rsiTrendSma: number;
  btMinTrades: number;
  btMinWinRate: number;
  eventFilter: 'include' | 'avoid' | 'only_pre_event';
  stockShortlistMax: number;
}
```

- [ ] **Step 1: Move the CSS**

Copy the rules used by the params panel from `frontend/app/(frame)/screener/step-5-strategy/page.module.css` — specifically the classes: `.paramsPanel`, `.paramsSummary`, `.paramsGrid`, `.paramSection`, `.paramLabel`, `.paramInput`, `.maToggle`, `.maToggleBtn`, `.maToggleBtnActive`, `.resetBtn` — into new file `frontend/components/organisms/StrategyParamsPanel/StrategyParamsPanel.module.css`. Leave the originals in the step-5 CSS in place (step-5 still imports its own module for the cards/header; harmless duplication, removed only if unused).

- [ ] **Step 2: Create the component**

Create `frontend/components/organisms/StrategyParamsPanel/index.tsx`. Move the entire `<details className={styles.paramsPanel}>…</details>` JSX block from step-5 page.tsx (lines 193-482) into this component's return. Replace `styles` references with the new module, replace `params`/`setParams` with the props, and replace the `resetParams` call with the `onReset` prop:

```tsx
'use client';

import { Text } from '@/components/primitives';
import styles from './StrategyParamsPanel.module.css';

export interface StrategyParams {
  pullbackTolerancePct: number;
  pullbackEmaPeriod: number;
  pullbackTrendEma: number;
  pullbackMaType: 'EMA' | 'SMA';
  maCrossoverFast: number;
  maCrossoverSlow: number;
  maCrossoverLookback: number;
  breakoutVolumeMult: number;
  rsiPeriod: number;
  rsiOversold: number;
  rsiTrendSma: number;
  btMinTrades: number;
  btMinWinRate: number;
  eventFilter: 'include' | 'avoid' | 'only_pre_event';
  stockShortlistMax: number;
}

interface Props {
  params: StrategyParams;
  setParams: React.Dispatch<React.SetStateAction<StrategyParams>>;
  requireReversal: boolean;
  onReset: () => void;
}

export function StrategyParamsPanel({ params, setParams, requireReversal, onReset }: Props) {
  return (
    // ↓ PASTE the <details className={styles.paramsPanel}>…</details> block here,
    //   with: styles.* now resolving against this module,
    //         all setParams((p) => …) calls unchanged,
    //         the final <button onClick={resetParams}> changed to onClick={onReset}.
    //   `requireReversal` is already a prop (was a local const in step-5).
  );
}
```

(The pasted block uses `params.*` and `setParams` exactly as in step-5, so no logic changes — only the import source of `styles` and the reset handler change.)

- [ ] **Step 3: Wire step-5 to the component**

In `frontend/app/(frame)/screener/step-5-strategy/page.tsx`:
- Add import: `import { StrategyParamsPanel } from '@/components/organisms/StrategyParamsPanel';`
- Delete the `<details className={styles.paramsPanel}>…</details>` block (lines 193-482) and replace with:

```tsx
      <StrategyParamsPanel
        params={params}
        setParams={setParams}
        requireReversal={requireReversal}
        onReset={resetParams}
      />
```

- [ ] **Step 4: Verify typecheck + step-5 unaffected**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors).

Run: `cd frontend && npm run test -- --testPathPattern=step-5` (if no step-5 test exists this reports "0 tests" — that is acceptable; the typecheck above is the gate).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/StrategyParamsPanel/ "frontend/app/(frame)/screener/step-5-strategy/page.tsx"
git commit -m "refactor(stocks): extract StrategyParamsPanel for reuse"
```

---

## Task 7: New page — strategy picker + params + scan log

**Files:**
- Create: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- Create: `frontend/app/(frame)/screener/step-4-stocks/page.module.css`

**Context:** This task builds the top half of the page (strategy selection, params, Run button, ScanFunnel log). The results table (Task 8) and inline position card (Task 9) are added to this same file afterward. The strategy metadata (`STRATEGIES`, `REGIME_FIT`, `REGIME_BADGE`, `strategyLabel`, `entryLabel`) is the same as step-5 — copy it.

- [ ] **Step 1: Create the page (top half)**

Create `frontend/app/(frame)/screener/step-4-stocks/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Title, Text } from '@/components/primitives';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { useShallow } from 'zustand/shallow';
import { ScanFunnel } from '@/components/organisms/ScanFunnel';
import { StrategyParamsPanel, type StrategyParams } from '@/components/organisms/StrategyParamsPanel';
import { runStockScan } from '@/lib/stockScan';
import styles from './page.module.css';

const STRATEGIES = [
  { key: 'pullback_ema',       label: 'Pullback to 20-EMA',        when: 'Steady uptrends',  entry: 'Dip to 20-EMA + reversal candle in uptrend',                 stop: 'Below recent swing low', exit: 'Prior high / trailing stop under higher lows' },
  { key: 'breakout_base',      label: 'Breakout from tight base',  when: 'Momentum stocks',  entry: 'Break above N-day high after narrow range + volume spike',    stop: 'Below the base low',     exit: 'Measured move / trailing stop' },
  { key: 'ma_crossover',       label: 'MA Crossover 20/50',        when: 'Simple trend entry', entry: '20-SMA crosses above 50-SMA',                              stop: 'Below 50-SMA',           exit: 'Cross back down' },
  { key: 'mean_reversion_rsi', label: 'Mean Reversion RSI',        when: 'Oversold in uptrend', entry: 'RSI < 30 while above 200-SMA',                            stop: 'Below recent swing low', exit: 'RSI returns to mid / take-profit target' },
] as const;

type RegimeFit = 'PASS' | 'CAUTION' | 'REJECT';
const REGIME_FIT: Record<string, Partial<Record<string, RegimeFit>>> = {
  pullback_ema:       { PASS: 'PASS',    CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  breakout_base:      { PASS: 'PASS',    CAUTION: 'REJECT',  REJECT: 'REJECT'  },
  ma_crossover:       { PASS: 'CAUTION', CAUTION: 'CAUTION', REJECT: 'REJECT'  },
  mean_reversion_rsi: { PASS: 'CAUTION', CAUTION: 'PASS',    REJECT: 'CAUTION' },
};
const REGIME_BADGE: Record<RegimeFit, { label: string; cls: string }> = {
  PASS:    { label: 'Recommended', cls: 'regimeBadgePass'    },
  CAUTION: { label: 'Neutral',     cls: 'regimeBadgeCaution' },
  REJECT:  { label: 'Avoid',       cls: 'regimeBadgeReject'  },
};

export default function Step4StocksPage() {
  const context        = useScanStore((s) => s.context);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
  const combinedRegime = useScanStore((s) => s.combinedRegime);
  const result         = useScanStore((s) => s.stockScanResult);
  const scanState      = useScanStore((s) => s.scanState);

  const savedParams = useScanParamsStore(useShallow((s) => ({
    pullbackTolerancePct: s.pullbackTolerancePct, pullbackEmaPeriod: s.pullbackEmaPeriod,
    pullbackTrendEma: s.pullbackTrendEma, pullbackMaType: s.pullbackMaType,
    maCrossoverFast: s.maCrossoverFast, maCrossoverSlow: s.maCrossoverSlow,
    maCrossoverLookback: s.maCrossoverLookback, breakoutVolumeMult: s.breakoutVolumeMult,
    rsiPeriod: s.rsiPeriod, rsiOversold: s.rsiOversold, rsiTrendSma: s.rsiTrendSma,
    btMinTrades: s.btMinTrades, btMinWinRate: s.btMinWinRate,
    eventFilter: s.eventFilter, stockShortlistMax: s.stockShortlistMax,
  })));
  const scanOverrides   = useScanStore((s) => s.scanOverrides);
  const requireReversal = (scanOverrides.pullback_require_reversal as boolean | undefined) ?? false;

  const [params, setParams] = useState<StrategyParams>(() => ({ ...savedParams }));
  const [selected, setSelected] = useState<string | null>(activeStrategy);
  const [error, setError] = useState<string | null>(null);

  const scanning = scanState === 'SCANNING';

  const strategyLabel: Record<string, string> = {
    pullback_ema:       `Pullback to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
    ma_crossover:       `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
    mean_reversion_rsi: `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
    breakout_base:      'Breakout from tight base',
  };
  const entryLabel: Record<string, string> = {
    pullback_ema:       `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} in uptrend${requireReversal ? ' + reversal candle' : ''}`,
    ma_crossover:       `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
    mean_reversion_rsi: `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
    breakout_base:      `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
  };

  async function onRun() {
    if (!selected) return;
    setError(null);
    const res = await runStockScan(selected, params);
    if (!res) setError('Scan failed — is the backend running on port 8000?');
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Text size={11} tone="dim" weight={500}>STEP 4 OF 4</Text>
        <Title as="h1" size={24}>Stocks</Title>
        <Text size={13} tone="secondary">
          Pick a strategy, run the scan, and act on the results — all on this page.
        </Text>
        <Text size={12} tone="secondary">
          Scanning full {context?.universe ?? 'SP500'} universe for stock setups
        </Text>
      </div>

      <div className={styles.grid}>
        {STRATEGIES.map((s) => {
          const fit = REGIME_FIT[s.key]?.[combinedRegime] as RegimeFit | undefined;
          const badge = fit ? REGIME_BADGE[fit] : null;
          return (
            <button
              key={s.key}
              type="button"
              className={`${styles.card} ${selected === s.key ? styles.cardActive : ''}`}
              onClick={() => setSelected(s.key)}
            >
              <div className={styles.cardHeader}>
                <Text size={14} weight={600}>{strategyLabel[s.key] ?? s.label}</Text>
                <Text size={11} tone="secondary">{s.when}</Text>
                {badge && <span className={`${styles.regimeBadge} ${styles[badge.cls]}`}>{badge.label}</span>}
              </div>
              <div className={styles.cardBody}>
                <Text size={11} tone="dim">Entry: {entryLabel[s.key] ?? s.entry}</Text>
                <Text size={11} tone="dim">Stop: {s.stop}</Text>
                <Text size={11} tone="dim">Exit: {s.exit}</Text>
              </div>
            </button>
          );
        })}
      </div>

      <StrategyParamsPanel
        params={params}
        setParams={setParams}
        requireReversal={requireReversal}
        onReset={() => setParams({ ...savedParams })}
      />

      <div className={styles.runRow}>
        <button
          type="button"
          className={styles.runBtn}
          onClick={onRun}
          disabled={!selected || scanning}
          title={!selected ? 'Select a strategy first' : undefined}
        >
          {scanning ? 'Running backtest scan…' : 'Run Stock Scan'}
        </button>
      </div>

      {error && <Text size={12} tone="reject">{error}</Text>}

      {result?.pipeline && (
        <details className={styles.logPanel} open={false}>
          <summary><Text size={12} tone="secondary">Pipeline log</Text></summary>
          <ScanFunnel mode="stock" pipeline={result.pipeline} />
        </details>
      )}

      {/* Results table — added in Task 8 */}
    </div>
  );
}
```

- [ ] **Step 2: Create the stylesheet**

Create `frontend/app/(frame)/screener/step-4-stocks/page.module.css`:

```css
.main { display: flex; flex-direction: column; gap: 16px; padding: 20px 24px; }
.header { display: flex; flex-direction: column; gap: 4px; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.card {
  display: flex; flex-direction: column; gap: 8px; text-align: left;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px;
  background: var(--bg-surface); cursor: pointer;
}
.cardActive { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-surface)); }
.cardHeader { display: flex; flex-direction: column; gap: 2px; }
.cardBody { display: flex; flex-direction: column; gap: 2px; }

.regimeBadge { align-self: flex-start; padding: 1px 6px; border-radius: 4px; font-size: 10px; margin-top: 2px; }
.regimeBadgePass    { background: color-mix(in srgb, var(--pass) 18%, var(--bg-surface));    color: var(--pass); }
.regimeBadgeCaution { background: color-mix(in srgb, var(--caution) 18%, var(--bg-surface)); color: var(--caution); }
.regimeBadgeReject  { background: color-mix(in srgb, var(--reject) 18%, var(--bg-surface));  color: var(--reject); }

.runRow { display: flex; }
.runBtn {
  padding: 8px 16px; border: 1px solid var(--accent); border-radius: 6px;
  background: var(--accent); color: var(--accent-fg, #fff); cursor: pointer; font-size: 13px;
}
.runBtn:disabled { opacity: 0.5; cursor: not-allowed; }

.logPanel { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 8px 12px; }
.logPanel summary { cursor: pointer; }
```

- [ ] **Step 3: Verify it renders without errors**

Run: `cd frontend && npm run typecheck`
Expected: clean.

Then start the dev server and confirm the page mounts (manual smoke — server task):
Run: `cd frontend && npm run dev` then load `http://localhost:3001/screener/step-4-stocks` (toggle Stocks mode). Expected: strategy cards, params panel, and a disabled "Run Stock Scan" button until a card is selected. Stop the server when confirmed.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-stocks/"
git commit -m "feat(stocks): step-4-stocks page — picker, params, scan log"
```

---

## Task 8: New page — results table with deltas + rejected section

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.module.css`

**Context:** Adapts the step-6 `BacktestRow` (columns Symbol, Win%, Trades, Return, Max DD, Gate) and adds a Δ column from `computeStockDeltas`. Clicking a row toggles an inline accordion (the position card lands here in Task 9). One row open at a time.

- [ ] **Step 1: Add imports + delta computation**

In `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, add imports at top:

```tsx
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { Data } from '@/components/primitives';
import { computeStockDeltas } from '@/lib/stockDelta';
import type { PositionCardData } from '@/types/stockDomain';
```

Inside the component, after the existing `result` selector add:

```tsx
  const previous = useScanStore((s) => s.previousStockScanResult);
  const [openSymbol, setOpenSymbol] = useState<string | null>(null);
  const deltas = result ? computeStockDeltas(result, previous) : new Map();
```

- [ ] **Step 2: Add the results table JSX**

Replace the `{/* Results table — added in Task 8 */}` placeholder with:

```tsx
      {result && (
        <div className={styles.results}>
          <div className={styles.tableHeader}>
            <Text size={11} tone="dim">SYMBOL</Text>
            <Text size={11} tone="dim">SCORE</Text>
            <Text size={11} tone="dim">Δ</Text>
            <Text size={11} tone="dim">WIN %</Text>
            <Text size={11} tone="dim">TRADES</Text>
            <Text size={11} tone="dim">RETURN</Text>
            <Text size={11} tone="dim">MAX DD</Text>
            <Text size={11} tone="dim">GATE</Text>
          </div>

          <div className={styles.tableBody}>
            {result.candidates.filter((c) => c.backtest.passes_gate).map((c) => {
              const d = deltas.get(c.symbol);
              const bt = c.backtest;
              const open = openSymbol === c.symbol;
              return (
                <div key={c.symbol}>
                  <button
                    type="button"
                    className={`${styles.row} ${open ? styles.rowOpen : ''}`}
                    onClick={() => setOpenSymbol(open ? null : c.symbol)}
                  >
                    <Data size={12} weight={500}>{c.symbol}</Data>
                    <Data size={12}>{c.stock_score}</Data>
                    <Text size={11} tone={!d ? 'dim' : d.scoreDelta > 0 ? 'pass' : d.scoreDelta < 0 ? 'reject' : 'secondary'}>
                      {!d ? '—' : `${d.scoreDelta > 0 ? '+' : ''}${d.scoreDelta}${d.rankDelta !== 0 ? ` (${d.rankDelta > 0 ? '↑' : '↓'}${Math.abs(d.rankDelta)})` : ''}`}
                    </Text>
                    <Data size={12} tone={bt.win_rate >= 0.5 ? 'pass' : bt.win_rate >= 0.45 ? 'caution' : 'reject'}>
                      {(bt.win_rate * 100).toFixed(0)}%
                    </Data>
                    <Data size={12}>{bt.n_trades}</Data>
                    <Data size={12} tone={bt.total_return_pct >= 0 ? 'pass' : 'reject'}>{bt.total_return_pct.toFixed(1)}%</Data>
                    <Data size={12} tone="reject">{Math.abs(bt.max_drawdown_pct).toFixed(1)}%</Data>
                    <StatusBadge status={bt.passes_gate ? 'PASS' : 'REJECT'} />
                  </button>
                  {open && <PositionCardAccordion card={c} />}
                </div>
              );
            })}
          </div>

          {result.rejected.length > 0 && (
            <details className={styles.rejectedSection}>
              <summary><Text size={12} tone="dim">{result.rejected.length} rejected</Text></summary>
              {result.rejected.map((r) => (
                <Text key={r.symbol} size={11} tone="dim">{r.symbol}: {r.reason}</Text>
              ))}
            </details>
          )}
        </div>
      )}
```

NOTE: `PositionCardAccordion` is defined in Task 9. To keep this task compiling on its own, add a temporary stub at the bottom of the file (Task 9 replaces it):

```tsx
function PositionCardAccordion({ card }: { card: PositionCardData }) {
  return <div className={styles.accordion}><Text size={12} tone="dim">{card.symbol} details…</Text></div>;
}
```

- [ ] **Step 3: Add table styles**

Append to `frontend/app/(frame)/screener/step-4-stocks/page.module.css`:

```css
.results { display: flex; flex-direction: column; gap: 4px; }
.tableHeader, .row {
  display: grid;
  grid-template-columns: 1fr 0.7fr 1.1fr 0.7fr 0.7fr 0.8fr 0.8fr 0.8fr;
  align-items: center; gap: 8px; padding: 6px 10px;
}
.tableHeader { border-bottom: 1px solid var(--border-subtle); }
.row { width: 100%; text-align: left; background: none; border: 1px solid transparent; border-radius: 6px; cursor: pointer; }
.row:hover { background: var(--bg-surface); }
.rowOpen { background: var(--bg-surface); border-color: var(--border-subtle); }
.accordion { border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; margin: 4px 0 8px; display: flex; flex-direction: column; gap: 12px; }
.rejectedSection { margin-top: 8px; display: flex; flex-direction: column; gap: 2px; }
.rejectedSection summary { cursor: pointer; }
```

- [ ] **Step 4: Verify**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-stocks/"
git commit -m "feat(stocks): results table with score/rank deltas"
```

---

## Task 9: New page — inline position card accordion

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.module.css`

**Context:** Replace the stub `PositionCardAccordion` with the real card: sizing grid (ported from step-7), then action buttons — Pin to Basket (scanStore), Add to Portfolio (`buildPaperStockPosition` + portfolioStore), View Chart (`Link` to `/chart?symbol=`), and the three paper-execution buttons (`api.postStockOrder`, ported from step-7).

- [ ] **Step 1: Add imports**

Add to the top of `frontend/app/(frame)/screener/step-4-stocks/page.tsx`:

```tsx
import Link from 'next/link';
import { useEffect } from 'react';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useSettingsStore } from '@/lib/settingsStore';
import { buildPaperStockPosition } from '@/lib/paperTrade';
import { api } from '@/lib/api';
```

(Combine the `useEffect` import with the existing `useState` import from `'react'` rather than duplicating.)

- [ ] **Step 2: Replace the stub with the real accordion**

Replace the temporary `PositionCardAccordion` stub at the bottom of the file with:

```tsx
type ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper';

function PositionCardAccordion({ card }: { card: PositionCardData }) {
  const stockBasket   = useScanStore((s) => s.stockBasket);
  const addToBasket   = useScanStore((s) => s.addToStockBasket);
  const removeBasket  = useScanStore((s) => s.removeFromStockBasket);
  const addPosition   = usePortfolioStore((s) => s.addPosition);
  const settings      = useSettingsStore();

  const [execMode, setExecMode] = useState<ExecutionMode>('recommendation');
  const [placingType, setPlacingType] = useState<'LMT' | 'MKT' | null>(null);
  const [orderId, setOrderId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [alpacaConfigured, setAlpacaConfigured] = useState(false);

  const pinned = stockBasket.some((c) => c.symbol === card.symbol);
  const ibkrConfigured    = !!settings.ibkrPaper.accountId && !!settings.ibkrPaper.baseUrl;
  const tradierConfigured = !!settings.tradierPaper.token && !!settings.tradierPaper.accountId;

  useEffect(() => {
    api.getBrokerStatus()
      .then((s) => setAlpacaConfigured(s.alpaca_paper?.configured ?? false))
      .catch(() => {});
  }, []);

  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation') return;
    setPlacingType(orderType);
    setErr(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        quantity: card.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? card.strategy.entry_price : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }

  function onAddToPortfolio() {
    addPosition(buildPaperStockPosition(card.symbol, card.price, card.shares));
    setAdded(true);
  }

  return (
    <div className={styles.accordion}>
      <div className={styles.grid4}>
        <div><Text size={10} tone="dim">ENTRY</Text><Data size={16} weight={500}>${card.strategy.entry_price}</Data></div>
        <div><Text size={10} tone="dim">STOP</Text><Data size={16} weight={500} tone="reject">${card.strategy.stop_price}</Data></div>
        <div><Text size={10} tone="dim">TARGET</Text><Data size={16} weight={500} tone="pass">${card.strategy.target_price}</Data></div>
        <div><Text size={10} tone="dim">R:R</Text><Data size={16} weight={500}>{card.strategy.rr_ratio.toFixed(1)}</Data></div>
      </div>
      <div className={styles.grid4}>
        <div><Text size={10} tone="dim">SHARES</Text><Data size={16} weight={500}>{card.shares}</Data></div>
        <div><Text size={10} tone="dim">RISK $</Text><Data size={16} weight={500}>{card.dollar_risk.toFixed(0)}</Data></div>
        <div><Text size={10} tone="dim">SIZE $</Text><Data size={16} weight={500}>{card.dollar_size.toFixed(0)}</Data></div>
        <div><Text size={10} tone="dim">WIN %</Text><Data size={16} weight={500} tone={card.backtest.win_rate >= 0.5 ? 'pass' : 'caution'}>{(card.backtest.win_rate * 100).toFixed(0)}%</Data></div>
      </div>

      <div className={styles.actionRow}>
        <Link href={`/chart?symbol=${encodeURIComponent(card.symbol)}`} className={styles.actionBtn}>View Chart</Link>
        <button type="button" className={styles.actionBtn}
          onClick={() => (pinned ? removeBasket(card.symbol) : addToBasket(card))}>
          {pinned ? 'Unpin from Basket' : 'Pin to Basket'}
        </button>
        <button type="button" className={styles.actionBtn} onClick={onAddToPortfolio} disabled={added}>
          {added ? 'Added to Portfolio' : 'Add to Portfolio'}
        </button>
      </div>

      <div className={styles.modeRow}>
        {([
          ['recommendation', 'Recommendation', true],
          ['ibkr_paper', 'IBKR Paper', ibkrConfigured],
          ['tradier_paper', 'Tradier Paper', tradierConfigured],
          ['alpaca_paper', 'Alpaca Paper', alpacaConfigured],
        ] as Array<[ExecutionMode, string, boolean]>).map(([mode, label, ok]) => (
          <button key={mode} type="button"
            className={`${styles.modeBtn} ${execMode === mode ? styles.modeBtnActive : ''}`}
            disabled={!ok}
            title={!ok ? 'Not configured — Settings → Brokers' : undefined}
            onClick={() => setExecMode(mode)}>
            <Text size={12} weight={600}>{label}</Text>
          </button>
        ))}
      </div>

      {execMode !== 'recommendation' && (
        <div className={styles.actionRow}>
          <button type="button" className={styles.actionBtn} onClick={() => submit('LMT')} disabled={placingType !== null}>
            {placingType === 'LMT' ? 'Placing…' : `Limit @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={styles.actionBtn} onClick={() => submit('MKT')} disabled={placingType !== null}>
            {placingType === 'MKT' ? 'Placing…' : 'Market Order'}
          </button>
        </div>
      )}

      {orderId && <Text size={12} tone="pass">Order placed — ID: {orderId}</Text>}
      {err && <Text size={12} tone="reject">{err}</Text>}
    </div>
  );
}
```

- [ ] **Step 3: Add accordion styles**

Append to `frontend/app/(frame)/screener/step-4-stocks/page.module.css`:

```css
.grid4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.grid4 > div { display: flex; flex-direction: column; gap: 2px; }
.actionRow { display: flex; flex-wrap: wrap; gap: 8px; }
.actionBtn {
  padding: 6px 12px; border: 1px solid var(--border-subtle); border-radius: 6px;
  background: var(--bg-surface); cursor: pointer; font-size: 12px; color: var(--text-primary);
  text-decoration: none; display: inline-flex; align-items: center;
}
.actionBtn:disabled { opacity: 0.5; cursor: not-allowed; }
.modeRow { display: flex; flex-wrap: wrap; gap: 8px; }
.modeBtn { padding: 6px 12px; border: 1px solid var(--border-subtle); border-radius: 6px; background: var(--bg-surface); cursor: pointer; }
.modeBtn:disabled { opacity: 0.5; cursor: not-allowed; }
.modeBtnActive { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, var(--bg-surface)); }
```

- [ ] **Step 4: Verify (typecheck + smoke)**

Run: `cd frontend && npm run typecheck`
Expected: clean.

Run dev server, toggle Stocks mode, go to `step-4-stocks`, select a strategy, Run Stock Scan (backend must be running on port 8000). Expected: results table populates, clicking a row opens the card, Pin/Add/View Chart and paper-mode buttons render. Stop server when confirmed.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-stocks/"
git commit -m "feat(stocks): inline position card with pin/portfolio/exec actions"
```

---

## Task 10: Topbar Run Scan — mode-aware

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx`
- Test: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`

**Context:** In stocks mode the FAB must trigger a stock scan via `runStockScan(activeStrategy)` instead of the options `postScan`. If no strategy is selected, show a toast and do nothing.

- [ ] **Step 1: Write the failing test**

Add to `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx` (mock both api and runStockScan; follow the file's existing mock style for `@/lib/api`). Add at top with the other `jest.mock` calls:

```ts
jest.mock('@/lib/stockScan', () => ({ runStockScan: jest.fn().mockResolvedValue(null) }));
```

Add a test case:

```ts
it('runs a stock scan when screenerMode is stocks and a strategy is active', async () => {
  const { runStockScan } = require('@/lib/stockScan');
  useScanStore.setState({ screenerMode: 'stocks', activeStrategy: 'pullback_ema' } as any);

  render(<RunScanButton />);
  fireEvent.click(screen.getByRole('button', { name: /run scan|run stock scan/i }));

  expect(runStockScan).toHaveBeenCalledWith('pullback_ema');
});
```

(Use the same `render`/`fireEvent`/`screen` imports already present in the test file. If the file currently imports only some of these, extend the import.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: FAIL — `runStockScan` not called (button still runs options scan).

- [ ] **Step 3: Make the button mode-aware**

In `frontend/components/organisms/RunScanButton/index.tsx`:
- Add import: `import { runStockScan } from '@/lib/stockScan';`
- Add a selector inside the component (near the other `useScanStore` selectors, ~line 48):

```tsx
  const screenerMode  = useScanStore((s) => s.screenerMode);
  const activeStrategy = useScanStore((s) => s.activeStrategy);
```

- At the very start of the `onClick` callback (right after `if (scanning) return;`, ~line 64), branch for stocks mode:

```tsx
    if (screenerMode === 'stocks') {
      if (!activeStrategy) {
        useAlertStore.getState().addToast({
          kind: 'Critical',
          symbol: 'SYSTEM',
          reason: 'Select a strategy first on the Stocks page.',
          recId: 'NO-STRATEGY',
          alertType: 'SCAN_FAILED',
        });
        return;
      }
      runStockScan(activeStrategy);
      return;
    }
```

- Add `screenerMode` and `activeStrategy` to the `useCallback` dependency array (the array currently ending at line 165).

- Update the button label so stocks mode reads "Run Stock Scan". Change the label span (~line 208):

```tsx
        <span>{scanning ? 'Scanning…' : screenerMode === 'stocks' ? 'Run Stock Scan' : 'Run Scan'}</span>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton`
Expected: PASS. Then confirm no regression: `cd frontend && npm run test`

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/RunScanButton/
git commit -m "feat(stocks): mode-aware Run Scan button"
```

---

## Final verification

- [ ] **Typecheck clean**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Full frontend test suite green**

Run: `cd frontend && npm run test`
Expected: all pass.

- [ ] **Manual end-to-end (dev server, backend on 8000)**

1. Toggle Stocks mode → stepper shows 4 steps.
2. Steps 1-3 unchanged.
3. Step 4: select strategy → Run Stock Scan → log + results table appear.
4. Δ column dashes on first run; run again → deltas populate.
5. Row click → position card; Pin/Add to Portfolio/View Chart/paper buttons work.
6. Topbar Run Scan (stocks mode) reruns the active strategy.
7. Toggle Options mode → 7 steps, options scan unaffected.

---

## Self-Review

**Spec coverage:**
- 4-step stocks stepper → Task 5 ✓
- Single combined page (picker/params/log/table/card) → Tasks 7-9 ✓
- Δscore/Δrank vs previous run → Tasks 1, 3, 8 ✓
- ScanFunnel log preserved → Task 7 ✓
- Pin to Basket / Add to Portfolio / paper exec / View Chart → Task 9 ✓
- Mode-aware Run Scan → Task 10 ✓
- Prewarm history removed from page → not ported into step-4-stocks (Task 7 omits it) ✓
- Options mode unaffected → no options files touched except mode-aware FAB (guarded) ✓
- Bug #6 (Tradier data source) → out of scope per spec ✓

**Placeholder scan:** The only forward reference is `PositionCardAccordion` (stubbed in Task 8, replaced in Task 9) — explicitly handled so each task compiles. No TBDs.

**Type consistency:** `StrategyParams` (Task 6) is consumed by Tasks 7. `PositionCardData` used consistently (Tasks 2, 8, 9). `runStockScan(strategy, overrides?)` signature matches all call sites (page passes `params`; FAB passes none). `computeStockDeltas` returns `Map<string, StockDelta>` consumed in Task 8. `addToStockBasket/removeFromStockBasket/clearStockBasket` names match between Task 2 and Task 9.
