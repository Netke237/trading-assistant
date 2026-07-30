# Strategy Watch Direction Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Kenneth create Bearish (not just Bullish) strategy watches — both from the Strategy Watch page and from the auto-trade "Armed" button on a stock's position card — and see each watch's direction in the table.

**Architecture:** The backend (`strategy_watch_store.py`, `strategy_watch.py` router, `strategy_watch_evaluator.py`, `strategy_engine.py`) already fully supports a per-watch `direction: "Bullish" | "Bearish"` field end-to-end — it defaults to `"Bullish"` when omitted. The gap is on the frontend, and it has **two** entry points that create watches without ever specifying a direction:

1. The Strategy Watch page (`frontend/app/(frame)/strategy-watch/page.tsx`) — no direction control at all.
2. `StockAutoTradeArm` (`frontend/components/organisms/StockAutoTradeArm/index.tsx:38`) — the "Armed — add to Strategy Watches now" button on a stock's position card, which calls `api.addStrategyWatch(symbol, strategyKey)` directly (bypassing the Zustand store), also with no direction. This one is silently wrong today: a Bearish stock scan card (`StockPositionCard`'s `card.direction`, already in scope at `StockPositionCard/index.tsx:45`) still arms a Bullish watch.

This plan wires `direction` through the API client and Zustand store, fixes both creation entry points, adds a Bullish/Bearish `<select>` and a Direction column to the Strategy Watch page, and closes one legacy-data gap: watches created before the backend gained the `direction` field (the two entries already in `backend/config/strategy_watches.yaml`) have no top-level `direction` key at all, so the store's `load()` migration needs a `setdefault` for it — otherwise the new frontend type (`direction: 'Bullish' | 'Bearish'`, non-optional) would be a lie for those rows. Finally, it corrects a docstring in `strategy_watch_evaluator.py` that currently misattributes *why* the reversal transition is dormant.

**Known, deliberately out-of-scope gap:** `page.tsx`'s `STRATEGIES` list is missing `mean_reversion_bb` (present in the backend's `VALID_STRATEGIES`), so that strategy can't be watched from the UI at all yet, direction or no direction. Not fixed here — flagging so it isn't mistaken for an oversight of this plan.

**Tech Stack:** FastAPI + Pydantic (backend, unchanged — already supports this), Zustand v5 + TypeScript (frontend store/types), React (`page.tsx`, `StockAutoTradeArm`), CSS Modules, pytest, Jest + Testing Library.

**Scope note on testing:** This codebase has no precedent for testing `app/**/page.tsx` files directly (only `components/**/__tests__` and `lib/__tests__` have test files), but organism-level components like `StockAutoTradeArm` *do* have that precedent (e.g. `TradeCard/__tests__`, `RunScanButton/__tests__`). So: Task 4's page UI is verified via `npm run typecheck` plus a manual browser check with the dev server (matching how the rest of that page was built), while Tasks 1–3 (backend migration, API client, Zustand store, `StockAutoTradeArm`) get real automated tests following existing `lib/__tests__` / `components/**/__tests__` / `backend/tests` conventions — including the `jest.mock('@/lib/api')` pattern already used in `RunScanButton.test.tsx` and `TradeCard.test.tsx`, and the `act()`-wrapped `setState` reset pattern already used in `riskStore.test.ts`.

---

### Task 1: Backend — migrate legacy watch entries that lack a `direction` field

**Files:**
- Modify: `backend/app/services/strategy_watch_store.py` (the `load()` migration loop, currently lines 60-75, with the `setdefault` calls at lines 70-74)
- Test: `backend/tests/test_strategy_watch_store.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_strategy_watch_store.py`:

```python
def test_load_migrates_legacy_entries_missing_direction(tmp_path):
    path = tmp_path / "watches.yaml"
    path.write_text(
        "schedule: {enabled: false, mode: eod, eod_time: '16:15', poll_hours: 4, sustain_minutes: 0}\n"
        "watches:\n"
        "- id: wch_legacy001\n"
        "  symbol: AAPL\n"
        "  strategy_key: pullback_ema\n"
        "  params_override: {}\n"
        "  enabled: true\n"
        "  created_at: '2026-06-13T20:48:29.893224+00:00'\n"
        "  last_state: {phase: idle, direction: null, entry_price: null, stop_price: null,\n"
        "               target_price: null, last_event: null, last_event_at: null}\n"
        "  watch_type: strategy\n"
        "  trigger_def: null\n"
        "  interval: 1D\n"
    )
    store = StrategyWatchStore(path=path)
    assert store.list_watches()[0]["direction"] == "Bullish"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_strategy_watch_store.py::test_load_migrates_legacy_entries_missing_direction -v`
Expected: FAIL with `KeyError: 'direction'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/strategy_watch_store.py`, inside `load()`, extend the existing migration loop:

```python
            for w in self._watches:
                w.setdefault("watch_type", "strategy")
                w.setdefault("trigger_def", None)
                w.setdefault("interval", "1D")
                w.setdefault("last_state", _fresh_state())
                w.setdefault("enabled", True)
                w.setdefault("direction", "Bullish")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_strategy_watch_store.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_watch_store.py backend/tests/test_strategy_watch_store.py
git commit -m "fix(strategy-watch): migrate legacy watch entries to carry a direction field"
```

---

### Task 2: Frontend — carry `direction` through the API client

**Files:**
- Modify: `frontend/lib/api.ts:81-89` (`StrategyWatch` interface)
- Modify: `frontend/lib/api.ts:506-509` (`addStrategyWatch`, `addStrategyWatchesBulk`)

- [ ] **Step 1: Add `direction` to the `StrategyWatch` interface**

In `frontend/lib/api.ts`, replace:

```ts
export interface StrategyWatch {
  id: string;
  symbol: string;
  strategy_key: string;
  params_override: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  last_state: StrategyWatchState;
}
```

with:

```ts
export interface StrategyWatch {
  id: string;
  symbol: string;
  strategy_key: string;
  direction: 'Bullish' | 'Bearish';
  params_override: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  last_state: StrategyWatchState;
}
```

- [ ] **Step 2: Accept and send `direction` from the add functions**

In `frontend/lib/api.ts`, replace:

```ts
  addStrategyWatch: (symbol: string, strategy_key: string) =>
    post<StrategyWatch>('/api/strategy-watch/', { symbol, strategy_key }),
  addStrategyWatchesBulk: (symbols: string[], strategy_key: string) =>
    post<{ added: number; watches: StrategyWatch[] }>('/api/strategy-watch/bulk', { symbols, strategy_key }),
```

with:

```ts
  addStrategyWatch: (symbol: string, strategy_key: string, direction: 'Bullish' | 'Bearish' = 'Bullish') =>
    post<StrategyWatch>('/api/strategy-watch/', { symbol, strategy_key, direction }),
  addStrategyWatchesBulk: (symbols: string[], strategy_key: string, direction: 'Bullish' | 'Bearish' = 'Bullish') =>
    post<{ added: number; watches: StrategyWatch[] }>('/api/strategy-watch/bulk', { symbols, strategy_key, direction }),
```

- [ ] **Step 3: Run typecheck to verify no type errors**

Run: `cd frontend && npm run typecheck`
Expected: clean. Note this will **not**, by itself, catch every caller that should be passing a real direction instead of relying on the `'Bullish'` default — both `addStrategyWatch` and `addStrategyWatchesBulk` take `direction` as an optional parameter, so an existing call site with only 2 arguments still type-checks. Task 3 below fixes the one caller (`StockAutoTradeArm`) that needs to pass a real direction; Task 4 fixes the other (`strategyWatchStore.ts`).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(strategy-watch): carry direction through the API client"
```

---

### Task 3: Frontend — thread direction through `StockAutoTradeArm`

**Files:**
- Modify: `frontend/components/organisms/StockAutoTradeArm/index.tsx`
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx:416-421` (the call site)
- Test: Create `frontend/components/organisms/StockAutoTradeArm/__tests__/StockAutoTradeArm.test.tsx`

This is the entry point the plan's own review round caught as missed: `StockAutoTradeArm` calls `api.addStrategyWatch` directly (not through the Zustand store), and today it never passes a direction — so arming a watch from a **Bearish** stock scan card still silently creates a **Bullish** watch. `StockPositionCard` has `card.direction` in scope (used at `StockPositionCard/index.tsx:189` and `:303`) but never passes it down to `StockAutoTradeArm`.

**Type note:** `card` is a `PositionCardData` (`frontend/types/stockDomain.ts:14`), where `direction` is declared as a plain `string`, not a `'Bullish' | 'Bearish'` literal union — same on the backend, `StockAnalysisOut.direction` (`backend/app/schemas/stock_scan.py:199`) is also plain `str`. Narrowing that shared type is out of scope here (`PositionCardData` is used across 9 frontend files, 21 occurrences — `StockPositionCard/index.tsx` itself, `StockSendDialog`, `step-7-position-card`, `step-4-prebreakout`, `step-6-backtest`, `scanStore.ts`, plus two test files — widening the blast radius well beyond this plan). Instead, Step 3 below normalizes at the boundary with a ternary (the same pattern already used for the Direction column pill in Task 5, and already the established convention at every other `.direction`-branching call site: `StockPositionCard:189,303`, `StockSendDialog:99`, `step-7-position-card:92`, `step-4-prebreakout:329,418,512,544`), so a stray non-`'Bearish'` value defaults safely to `'Bullish'` instead of failing typecheck or being passed through unchecked.

- [ ] **Step 1: Write the failing test**

Create `frontend/components/organisms/StockAutoTradeArm/__tests__/StockAutoTradeArm.test.tsx`:

```tsx
import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StockAutoTradeArm } from '@/components/organisms/StockAutoTradeArm';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    addStrategyWatch: jest.fn().mockResolvedValue({ id: 'wch_test001' }),
  },
}));

const mockAdd = api.addStrategyWatch as jest.MockedFunction<typeof api.addStrategyWatch>;

describe('StockAutoTradeArm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('arms a watch with the given direction', async () => {
    render(
      <StockAutoTradeArm
        symbol="TSLA"
        strategyKey="pullback_ema"
        direction="Bearish"
        afterScanArmed={false}
        onAfterScanToggle={() => {}}
      />
    );

    fireEvent.click(screen.getByText('Armed — add to Strategy Watches now'));
    fireEvent.click(screen.getByText(/Watch TSLA — pullback_ema/));

    await waitFor(() => {
      expect(mockAdd).toHaveBeenCalledWith('TSLA', 'pullback_ema', 'Bearish');
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=StockAutoTradeArm`
Expected: FAIL — TypeScript error (`direction` isn't a known prop on `StockAutoTradeArmProps`), or, if it compiles, the assertion fails because `handleArm` calls `api.addStrategyWatch(symbol, strategyKey)` with only 2 arguments.

- [ ] **Step 3: Write minimal implementation**

In `frontend/components/organisms/StockAutoTradeArm/index.tsx`, replace:

```tsx
interface StockAutoTradeArmProps {
  symbol: string;
  strategyKey: string;
  afterScanArmed: boolean;
  onAfterScanToggle: (symbol: string, armed: boolean) => void;
}

export function StockAutoTradeArm({
  symbol,
  strategyKey,
  afterScanArmed,
  onAfterScanToggle,
}: StockAutoTradeArmProps) {
```

with:

```tsx
interface StockAutoTradeArmProps {
  symbol: string;
  strategyKey: string;
  direction: 'Bullish' | 'Bearish';
  afterScanArmed: boolean;
  onAfterScanToggle: (symbol: string, armed: boolean) => void;
}

export function StockAutoTradeArm({
  symbol,
  strategyKey,
  direction,
  afterScanArmed,
  onAfterScanToggle,
}: StockAutoTradeArmProps) {
```

Replace:

```tsx
      const res = await api.addStrategyWatch(symbol, strategyKey);
```

with:

```tsx
      const res = await api.addStrategyWatch(symbol, strategyKey, direction);
```

In `frontend/components/organisms/StockPositionCard/index.tsx`, replace:

```tsx
      <StockAutoTradeArm
        symbol={card.symbol}
        strategyKey={strategyKey}
        afterScanArmed={afterScanArmed ?? false}
        onAfterScanToggle={onAfterScanToggle ?? (() => {})}
      />
```

with:

```tsx
      <StockAutoTradeArm
        symbol={card.symbol}
        strategyKey={strategyKey}
        direction={card.direction === 'Bearish' ? 'Bearish' : 'Bullish'}
        afterScanArmed={afterScanArmed ?? false}
        onAfterScanToggle={onAfterScanToggle ?? (() => {})}
      />
```

`card.direction` is a plain `string` (see the type note above), so this narrows it to the `'Bullish' | 'Bearish'` literal union `StockAutoTradeArmProps` expects instead of failing typecheck or requiring an unsafe cast.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=StockAutoTradeArm`
Expected: PASS

- [ ] **Step 5: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (confirms `StockPositionCard`'s `card.direction` really is a `'Bullish' | 'Bearish'` and there are no other callers of `<StockAutoTradeArm>` left unpassed — if there were, this step would now fail because `direction` is a required prop).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/StockAutoTradeArm/index.tsx frontend/components/organisms/StockAutoTradeArm/__tests__/StockAutoTradeArm.test.tsx frontend/components/organisms/StockPositionCard/index.tsx
git commit -m "fix(strategy-watch): auto-trade arm now watches in the card's actual direction"
```

---

### Task 4: Frontend — thread `direction` through the Zustand store

**Files:**
- Modify: `frontend/lib/strategyWatchStore.ts`
- Test: Create `frontend/lib/__tests__/strategyWatchStore.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/strategyWatchStore.test.ts`:

```ts
import { renderHook, act } from '@testing-library/react';
import { useStrategyWatchStore } from '@/lib/strategyWatchStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: {
    getStrategyWatches: jest.fn().mockResolvedValue([]),
    getStrategyWatchSchedule: jest.fn().mockResolvedValue({
      enabled: false, mode: 'eod', eod_time: '16:15', poll_hours: 4, sustain_minutes: 0,
    }),
    addStrategyWatch: jest.fn().mockResolvedValue({}),
    addStrategyWatchesBulk: jest.fn().mockResolvedValue({ added: 0, watches: [] }),
  },
}));

const mockAdd = api.addStrategyWatch as jest.MockedFunction<typeof api.addStrategyWatch>;
const mockAddBulk = api.addStrategyWatchesBulk as jest.MockedFunction<typeof api.addStrategyWatchesBulk>;

describe('strategyWatchStore', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    act(() => {
      useStrategyWatchStore.setState({ watches: [], schedule: null, loading: false, error: null });
    });
  });

  it('add() defaults direction to Bullish when none is given', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.add('AAPL', 'pullback_ema');
    });
    expect(mockAdd).toHaveBeenCalledWith('AAPL', 'pullback_ema', 'Bullish');
  });

  it('add() passes through an explicit Bearish direction', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.add('AAPL', 'pullback_ema', 'Bearish');
    });
    expect(mockAdd).toHaveBeenCalledWith('AAPL', 'pullback_ema', 'Bearish');
  });

  it('addBulk() passes through direction', async () => {
    const { result } = renderHook(() => useStrategyWatchStore());
    await act(async () => {
      await result.current.addBulk(['AAPL', 'MSFT'], 'breakout_base', 'Bearish');
    });
    expect(mockAddBulk).toHaveBeenCalledWith(['AAPL', 'MSFT'], 'breakout_base', 'Bearish');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=strategyWatchStore`
Expected: FAIL — TypeScript error, since `add`/`addBulk` currently take only 2 arguments (or, if TS is loose enough to compile, the assertions fail because the store never forwards a third argument to the mocks).

- [ ] **Step 3: Write minimal implementation**

In `frontend/lib/strategyWatchStore.ts`, replace the interface signatures:

```ts
  add: (symbol: string, strategyKey: string) => Promise<void>;
  addBulk: (symbols: string[], strategyKey: string) => Promise<void>;
```

with:

```ts
  add: (symbol: string, strategyKey: string, direction?: 'Bullish' | 'Bearish') => Promise<void>;
  addBulk: (symbols: string[], strategyKey: string, direction?: 'Bullish' | 'Bearish') => Promise<void>;
```

and replace the implementations:

```ts
  add: async (symbol, strategyKey) => {
    try {
      await api.addStrategyWatch(symbol, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  addBulk: async (symbols, strategyKey) => {
    try {
      await api.addStrategyWatchesBulk(symbols, strategyKey);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
```

with:

```ts
  add: async (symbol, strategyKey, direction = 'Bullish') => {
    try {
      await api.addStrategyWatch(symbol, strategyKey, direction);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },

  addBulk: async (symbols, strategyKey, direction = 'Bullish') => {
    try {
      await api.addStrategyWatchesBulk(symbols, strategyKey, direction);
      await get().refresh();
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=strategyWatchStore`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/strategyWatchStore.ts frontend/lib/__tests__/strategyWatchStore.test.ts
git commit -m "feat(strategy-watch): thread direction through the Zustand store"
```

---

### Task 5: Frontend — Bullish/Bearish picker and Direction column on the Strategy Watch page

**Files:**
- Modify: `frontend/app/(frame)/strategy-watch/page.tsx`
- Modify: `frontend/app/(frame)/strategy-watch/page.module.css`

- [ ] **Step 1: Add direction state and selects to the add forms**

In `frontend/app/(frame)/strategy-watch/page.tsx`, add state after the existing `useState` calls (after line 28, before `useEffect`):

```tsx
  const [direction, setDirection] = useState<'Bullish' | 'Bearish'>('Bullish');
  const [bulkDirection, setBulkDirection] = useState<'Bullish' | 'Bearish'>('Bullish');
```

Replace `onAdd` and `onBulkAdd`:

```tsx
  const onAdd = async () => {
    if (!symbol.trim()) return;
    await add(symbol.trim(), strategyKey, direction);
    setSymbol('');
  };

  const onBulkAdd = async () => {
    const syms = bulkSymbols.split(',').map((s) => s.trim()).filter(Boolean);
    if (syms.length === 0) return;
    await addBulk(syms, bulkStrategy, bulkDirection);
    setBulkSymbols('');
  };
```

Replace the single-add row:

```tsx
        <div className={styles.row}>
          <input className={styles.input} placeholder="Symbol (e.g. AAPL)"
                 value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <select className={styles.select} value={strategyKey}
                  onChange={(e) => setStrategyKey(e.target.value as typeof strategyKey)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <button className={styles.btn} onClick={onAdd}>Add</button>
        </div>
```

with:

```tsx
        <div className={styles.row}>
          <input className={styles.input} placeholder="Symbol (e.g. AAPL)"
                 value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <select className={styles.select} value={strategyKey}
                  onChange={(e) => setStrategyKey(e.target.value as typeof strategyKey)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className={styles.select} value={direction}
                  onChange={(e) => setDirection(e.target.value as 'Bullish' | 'Bearish')}>
            <option value="Bullish">Bullish</option>
            <option value="Bearish">Bearish</option>
          </select>
          <button className={styles.btn} onClick={onAdd}>Add</button>
        </div>
```

Replace the bulk-add row:

```tsx
        <div className={styles.row}>
          <input className={styles.input} placeholder="Bulk: AAPL, MSFT, GOOG"
                 value={bulkSymbols} onChange={(e) => setBulkSymbols(e.target.value)} />
          <select className={styles.select} value={bulkStrategy}
                  onChange={(e) => setBulkStrategy(e.target.value as typeof bulkStrategy)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <button className={styles.btn} onClick={onBulkAdd}>Bulk add</button>
        </div>
```

with:

```tsx
        <div className={styles.row}>
          <input className={styles.input} placeholder="Bulk: AAPL, MSFT, GOOG"
                 value={bulkSymbols} onChange={(e) => setBulkSymbols(e.target.value)} />
          <select className={styles.select} value={bulkStrategy}
                  onChange={(e) => setBulkStrategy(e.target.value as typeof bulkStrategy)}>
            {STRATEGIES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <select className={styles.select} value={bulkDirection}
                  onChange={(e) => setBulkDirection(e.target.value as 'Bullish' | 'Bearish')}>
            <option value="Bullish">Bullish</option>
            <option value="Bearish">Bearish</option>
          </select>
          <button className={styles.btn} onClick={onBulkAdd}>Bulk add</button>
        </div>
```

- [ ] **Step 2: Add a Direction column to the watch table**

Replace the table header:

```tsx
          <thead><tr><th>Symbol</th><th>Strategy</th><th>State</th><th>Enabled</th><th></th></tr></thead>
```

with:

```tsx
          <thead><tr><th>Symbol</th><th>Strategy</th><th>Direction</th><th>State</th><th>Enabled</th><th></th></tr></thead>
```

Replace the table row:

```tsx
              <tr key={w.id}>
                <td>{w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
                <td>{phasePill(w.last_state.phase)}</td>
                <td><input type="checkbox" checked={w.enabled}
                           onChange={(e) => setEnabled(w.id, e.target.checked)} /></td>
                <td><button className={styles.btn} onClick={() => remove(w.id)}>Remove</button></td>
              </tr>
```

with:

```tsx
              <tr key={w.id}>
                <td>{w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
                <td>
                  <span className={`${styles.pill} ${w.direction === 'Bearish' ? styles.pillBearish : styles.pillBullish}`}>
                    {w.direction === 'Bearish' ? 'Bearish' : 'Bullish'}
                  </span>
                </td>
                <td>{phasePill(w.last_state.phase)}</td>
                <td><input type="checkbox" checked={w.enabled}
                           onChange={(e) => setEnabled(w.id, e.target.checked)} /></td>
                <td><button className={styles.btn} onClick={() => remove(w.id)}>Remove</button></td>
              </tr>
```

- [ ] **Step 3: Add the direction pill styles**

In `frontend/app/(frame)/strategy-watch/page.module.css`, append after the existing `.pillArmed` rule:

```css
.pillBullish { background: color-mix(in srgb, var(--pass) 14%, var(--bg-surface)); color: var(--pass); }
.pillBearish { background: color-mix(in srgb, var(--reject) 14%, var(--bg-surface)); color: var(--reject); }
```

- [ ] **Step 4: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 5: Manual verification with the dev server**

Run: `cd frontend && npm run dev` (or use the existing preview if already running), open `/strategy-watch`.

- Add a watch with Symbol `TSLA`, Strategy `Pullback EMA`, Direction `Bearish`, click Add.
- Confirm the new row shows a Bearish pill (styled with the reject/red tint) in the Direction column.
- Add another watch with Direction left at the default `Bullish` and confirm it shows a Bullish pill (pass/green tint).
- Reload the page and confirm both watches still show their correct direction (proves the backend round-trip and the Task 1 migration both work).

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/(frame)/strategy-watch/page.tsx" "frontend/app/(frame)/strategy-watch/page.module.css"
git commit -m "feat(strategy-watch): add Bullish/Bearish picker and Direction column to the watch page"
```

---

### Task 6: Backend — fix the stale "Bullish-only" docstring claim

**Files:**
- Modify: `backend/app/services/strategy_watch_evaluator.py:1-8`

The current docstring says reversal is dormant *because* "the four current strategy functions emit Bullish-only signals." That's stale — there are now five direction-aware strategy functions, each mirroring Bullish/Bearish logic. But reversal is still dormant, just for a different reason: `direction` is fixed on a watch at creation time (there is no PATCH endpoint to change it — the only PATCH in `strategy_watch.py` is `EnabledPatch`), so every evaluation tick calls the signal function with the *same* `wdir` that was already written into `state["direction"]` when the watch was armed. The reversal check at `strategy_watch_evaluator.py:179` (`signal.direction != state.get("direction")`) can therefore never trip in practice. The fix corrects the *reason*, not the *conclusion*.

- [ ] **Step 1: Correct the module docstring**

Replace:

```python
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Reversal is wired but dormant — the four current
strategy functions emit Bullish-only signals.
"""
```

with:

```python
"""Runs each enabled strategy-watch on daily bars and emits state-transition events.

The state machine (per watch) is the dedup mechanism: it only returns events on a
genuine transition (idle→entry, armed→exit_stop/exit_target, armed→reversal), so a
standing setup never re-alerts. Reversal is wired but still dormant in practice:
each watch's direction (Bullish/Bearish) is fixed at creation and there is no
endpoint to change it later, so the signal function is evaluated with the same
direction every tick and can never disagree with the armed state's direction.
"""
```

- [ ] **Step 2: Verify no other file repeats the stale claim**

Run: `cd backend && grep -rin --include='*.py' "bullish-only\|bullish only" app/`
Expected: no matches (the `--include='*.py'` excludes stale compiled `__pycache__/*.pyc` files, which can otherwise keep matching the old docstring text as binary hits until Python recompiles them — a false alarm, not a sign the edit failed. The two unrelated `.py` hits found during planning — a `# Soft demote (Bullish only)` comment in `app/scoring/stock_scorer.py` and a `# legacy flat active = bullish only` comment in `app/services/strategy_param_store.py` — are about different subsystems and are out of scope for this plan, so leave them untouched).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/strategy_watch_evaluator.py
git commit -m "docs(strategy-watch): correct stale Bullish-only claim in evaluator docstring"
```

---

## Post-implementation checklist

- [ ] `cd backend && pytest tests/test_strategy_watch_store.py tests/test_strategy_watch_evaluator.py tests/test_strategy_watch_router.py tests/test_strategy_watch_bearish.py -v` — all pass
- [ ] `cd frontend && npm run typecheck` — clean
- [ ] `cd frontend && npm run test -- --testPathPattern=strategyWatchStore` — pass
- [ ] `cd frontend && npm run test -- --testPathPattern=StockAutoTradeArm` — pass
- [ ] Manual browser check from Task 5 Step 5 completed
