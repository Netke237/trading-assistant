# Chart Phase 3 — Alert Engine: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Build an in-app alert engine with visual rule builder, candle-close evaluation, and alert history panel.

**Architecture:** `chartAlertStore` (Zustand + persist via `bamendjou:alerts`) holds rules + history + toasts. `chartAlertEngine.ts` is a pure function that evaluates rules on candle-close, self-filtering by symbol+interval. `AlertRuleBuilder` is a slide-in panel (mirrors IndicatorPanel pattern). Trigger results flow to `AlertToast` and a new "Alerts" tab in `ChartRightPanel`. The existing `/alerts` page gains a Rules tab.

**Key decisions:**
- Named `chartAlertEngine.ts` (not `alertEngine.ts`) to avoid collision with existing portfolio alert engine
- localStorage key `bamendjou:alerts` (distinct from existing `bamendjou-alerts-v2`)
- `evaluateRules` receives `activeSymbol` + `activeInterval` params for self-filtering per spec
- `AlertHistory` does NOT carry `rule_name` — join with rules array at display time
- Indicator computation hoisted into `getIndicatorPoints()` helper, shared by chart render + engine

**Tech Stack:** Next.js 15 App Router, TypeScript 5.7 strict, Zustand v5 (persist), CSS Modules, Primitives (Text, Data)

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/types/alerts.ts` | AlertRule, AlertHistory, Condition types |
| Create | `frontend/lib/chartAlertStore.ts` | Zustand persist store: rules + history + toasts + badge |
| Create | `frontend/lib/chartAlertEngine.ts` | Pure `evaluateRules()` function with self-filtering |
| Create | `frontend/lib/__tests__/chartAlertEngine.test.ts` | 13 engine tests |
| Create | `frontend/lib/__tests__/chartAlertStore.test.ts` | 9 store tests |
| Create | `frontend/components/organisms/AlertRuleBuilder/index.tsx` | Slide-in rule editor |
| Create | `frontend/components/organisms/AlertRuleBuilder/AlertRuleBuilder.module.css` | Styles |
| Create | `frontend/components/organisms/AlertToast/index.tsx` | Toast notification |
| Create | `frontend/components/organisms/AlertToast/AlertToast.module.css` | Styles |
| Modify | `frontend/components/organisms/ChartRightPanel/index.tsx` | Add "Alerts" tab (third tab) |
| Modify | `frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css` | Alerts history row styles |
| Modify | `frontend/components/organisms/ChartTopBar/index.tsx` | Add "Alerts" button |
| Modify | `frontend/components/organisms/ChartWorkspace/index.tsx` | Hoist indicators, wire candle-close eval |
| Modify | `frontend/app/(frame)/alerts/page.tsx` | Add Rules tab with management table |
| Modify | `frontend/app/(frame)/alerts/page.module.css` | Rules table styles |

---

## Tasks

### Task 1: Create alert domain types

**Files:**
- Create: `frontend/types/alerts.ts`

- [ ] **Step 1: Write types file**

```typescript
// frontend/types/alerts.ts

import type { Interval } from '@/lib/chartStore';
import type { SignalKind } from '@/types/structure';
import type { Candle } from '@/lib/indicators';

export type ConditionOperator = '>' | '<' | '>=' | '<=' | 'crosses_above' | 'crosses_below';
export type LogicOperator = 'AND' | 'OR';

export interface PriceCondition {
  kind: 'price';
  operator: ConditionOperator;
  value: number;
}

export interface IndicatorCondition {
  kind: 'indicator';
  indicator: string;
  operator: ConditionOperator;
  value: number;
}

export interface StructureCondition {
  kind: 'structure';
  signal_kind: SignalKind;
  direction?: 'bullish' | 'bearish';
  min_confidence?: number;
}

export type Condition = PriceCondition | IndicatorCondition | StructureCondition;

export interface ConditionGroup {
  logic: LogicOperator;
  conditions: Condition[];
}

export interface AlertRule {
  id: string;
  name: string;
  symbol: string;
  interval: Interval;
  enabled: boolean;
  group: ConditionGroup;
  cooldown_minutes: number;
  expiry_date: string | null;
  created_at: string;
  last_triggered_at: string | null;
}

export interface AlertHistory {
  id: string;
  rule_id: string;
  symbol: string;
  interval: Interval;
  triggered_at: string;
  candle: Candle;
  trigger_values: Record<string, number>;
  reason: string;
}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend; npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/types/alerts.ts
git commit -m "feat: add alert domain types (AlertRule, AlertHistory, Condition)"
```

---

### Task 2: Create chartAlertStore with tests

**Files:**
- Create: `frontend/lib/chartAlertStore.ts`
- Create: `frontend/lib/__tests__/chartAlertStore.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// frontend/lib/__tests__/chartAlertStore.test.ts

import { renderHook, act } from '@testing-library/react';
import { useChartAlertStore, HISTORY_LIMIT } from '@/lib/chartAlertStore';
import type { AlertRule, AlertHistory, PriceCondition } from '@/types/alerts';

function makeRule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r1',
    name: 'Test Rule',
    symbol: 'AAPL',
    interval: '1D',
    enabled: true,
    group: {
      logic: 'AND',
      conditions: [{ kind: 'price', operator: '>', value: 185 } as PriceCondition],
    },
    cooldown_minutes: 60,
    expiry_date: null,
    created_at: new Date().toISOString(),
    last_triggered_at: null,
    ...overrides,
  };
}

function makeHistory(overrides: Partial<AlertHistory> = {}): AlertHistory {
  return {
    id: 'h1',
    rule_id: 'r1',
    symbol: 'AAPL',
    interval: '1D',
    triggered_at: new Date().toISOString(),
    candle: { time: '2024-01-05', open: 184, high: 187, low: 183, close: 186, volume: 10000 },
    trigger_values: { close: 186 },
    reason: 'Price > 185',
    ...overrides,
  };
}

describe('chartAlertStore', () => {
  beforeEach(() => {
    useChartAlertStore.setState({ rules: [], history: [], toasts: [], newSinceView: 0 });
  });

  it('adds a rule', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    expect(result.current.rules).toHaveLength(1);
    expect(result.current.rules[0].name).toBe('Test Rule');
  });

  it('blocks duplicate rule (same symbol, interval, conditions)', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    const added = act(() => result.current.addRule(makeRule({ id: 'r2' })));
    expect(result.current.rules).toHaveLength(1);
  });

  it('allows rules with same symbol/interval but different conditions', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    act(() => result.current.addRule(makeRule({ id: 'r2', group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<', value: 170 }] } })));
    expect(result.current.rules).toHaveLength(2);
  });

  it('allows rules with same conditions but different logic (OR vs AND)', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule({ id: 'r1', group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] } })));
    act(() => result.current.addRule(makeRule({ id: 'r2', group: { logic: 'OR', conditions: [{ kind: 'price', operator: '>', value: 185 }] } })));
    expect(result.current.rules).toHaveLength(2);
  });

  it('updates a rule', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule()));
    act(() => result.current.updateRule('r1', { name: 'Updated' }));
    expect(result.current.rules[0].name).toBe('Updated');
  });

  it('deletes a rule and cascades to history', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addRule(makeRule({ id: 'r1' })));
    act(() => result.current.addRule(makeRule({ id: 'r2', name: 'Rule B' })));
    act(() => result.current.addHistory(makeHistory({ rule_id: 'r1' })));
    act(() => result.current.addHistory(makeHistory({ rule_id: 'r2', id: 'h2' })));
    act(() => result.current.deleteRule('r1'));
    expect(result.current.rules).toHaveLength(1);
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0].id).toBe('h2');
  });

  it('adds history entry with newSinceView increment', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    expect(result.current.history).toHaveLength(1);
    expect(result.current.newSinceView).toBe(1);
  });

  it('markViewed resets newSinceView to 0', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.addHistory(makeHistory({ id: 'h2' })));
    expect(result.current.newSinceView).toBe(2);
    act(() => result.current.markViewed());
    expect(result.current.newSinceView).toBe(0);
  });

  it('enforces history limit of 200 entries', () => {
    const { result } = renderHook(() => useChartAlertStore());
    for (let i = 0; i < 210; i++) {
      act(() => result.current.addHistory(makeHistory({ id: `h${i}` })));
    }
    expect(result.current.history).toHaveLength(HISTORY_LIMIT);
  });

  it('clears history', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.clearHistory());
    expect(result.current.history).toHaveLength(0);
  });

  it('dismisses history entry by id', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.addHistory(makeHistory()));
    act(() => result.current.dismissHistory('h1'));
    expect(result.current.history).toHaveLength(0);
  });

  it('pushToast adds a toast and dismissToast removes it', () => {
    const { result } = renderHook(() => useChartAlertStore());
    act(() => result.current.pushToast({ id: 't1', message: 'Alert!', timestamp: Date.now() }));
    expect(result.current.toasts).toHaveLength(1);
    act(() => result.current.dismissToast('t1'));
    expect(result.current.toasts).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd frontend; npm run test -- --testPathPattern=chartAlertStore
```
Expected: FAIL "Cannot find module"

- [ ] **Step 3: Write store implementation**

```typescript
// frontend/lib/chartAlertStore.ts

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type { AlertRule, AlertHistory } from '@/types/alerts';

export const HISTORY_LIMIT = 200;

export interface ChartToast {
  id: string;
  message: string;
  timestamp: number;
}

interface ChartAlertState {
  rules: AlertRule[];
  history: AlertHistory[];
  toasts: ChartToast[];
  newSinceView: number;
  addRule: (rule: AlertRule) => boolean;
  updateRule: (id: string, patch: Partial<AlertRule>) => void;
  deleteRule: (id: string) => void;
  addHistory: (entry: AlertHistory) => void;
  clearHistory: () => void;
  dismissHistory: (id: string) => void;
  pushToast: (toast: ChartToast) => void;
  dismissToast: (id: string) => void;
  markViewed: () => void;
}

export const useChartAlertStore = create<ChartAlertState>()(
  persist(
    (set) => ({
      rules: [],
      history: [],
      toasts: [],
      newSinceView: 0,

      addRule: (rule) => {
        let added = false;
        set((s) => {
          const duplicate = s.rules.some(
            (r) =>
              r.symbol === rule.symbol &&
              r.interval === rule.interval &&
              JSON.stringify(r.group.conditions) === JSON.stringify(rule.group.conditions),
          );
          if (duplicate) return s;
          added = true;
          return { rules: [...s.rules, rule] };
        });
        return added;
      },

      updateRule: (id, patch) =>
        set((s) => ({
          rules: s.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)),
        })),

      deleteRule: (id) =>
        set((s) => ({
          rules: s.rules.filter((r) => r.id !== id),
          history: s.history.filter((h) => h.rule_id !== id),
        })),

      addHistory: (entry) =>
        set((s) => ({
          history: [entry, ...s.history].slice(0, HISTORY_LIMIT),
          newSinceView: s.newSinceView + 1,
        })),

      clearHistory: () => set({ history: [] }),

      dismissHistory: (id) =>
        set((s) => ({
          history: s.history.filter((h) => h.id !== id),
        })),

      pushToast: (toast) =>
        set((s) => ({ toasts: [...s.toasts, toast] })),

      dismissToast: (id) =>
        set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

      markViewed: () => set({ newSinceView: 0 }),
    }),
    {
      name: 'bamendjou:alerts',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        rules: state.rules,
        history: state.history,
      }),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<ChartAlertState> | null) ?? {};
        if (version < 1) {
          return {
            rules: Array.isArray(prev.rules) ? prev.rules : [],
            history: Array.isArray(prev.history) ? prev.history.slice(0, HISTORY_LIMIT) : [],
            toasts: [],
            newSinceView: 0,
          } as ChartAlertState;
        }
        return prev as ChartAlertState;
      },
    },
  ),
);
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd frontend; npm run test -- --testPathPattern=chartAlertStore
```
Expected: 12/12 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/chartAlertStore.ts frontend/lib/__tests__/chartAlertStore.test.ts
git commit -m "feat: add chartAlertStore with persist, dedup, toast, and badge tracking"
```

---

### Task 3: Create alert evaluation engine with TDD

**Files:**
- Create: `frontend/lib/chartAlertEngine.ts`
- Create: `frontend/lib/__tests__/chartAlertEngine.test.ts`

- [ ] **Step 1: Write 13 failing tests**

```typescript
// frontend/lib/__tests__/chartAlertEngine.test.ts

import { evaluateRules } from '@/lib/chartAlertEngine';
import type { AlertRule } from '@/types/alerts';
import type { Candle } from '@/lib/indicators';
import type { StructureSignal } from '@/types/structure';
import type { Interval } from '@/lib/chartStore';

const SYM = 'AAPL';
const INT: Interval = '1D';

function candles(): Candle[] {
  return [
    { time: '2024-01-02', open: 181, high: 184, low: 180, close: 183, volume: 1000 },
    { time: '2024-01-03', open: 183, high: 186, low: 182, close: 184, volume: 1200 },
    { time: '2024-01-04', open: 184, high: 190, low: 183, close: 188, volume: 1500 },
    { time: '2024-01-05', open: 188, high: 192, low: 187, close: 190, volume: 2000 },
  ];
}

const closedCandle: Candle = candles()[3]; // Jan 5 just closed

const indicators = {
  'RSI(14)': [
    { time: '2024-01-02', value: 45 },
    { time: '2024-01-03', value: 48 },
    { time: '2024-01-04', value: 52 },
    { time: '2024-01-05', value: 55 },
  ],
  'EMA(20)': [
    { time: '2024-01-02', value: 180 },
    { time: '2024-01-03', value: 182 },
    { time: '2024-01-04', value: 184 },
    { time: '2024-01-05', value: 186 },
  ],
};

const now = new Date('2024-01-05T16:00:00Z');

describe('evaluateRules', () => {
  it('test_price_condition_gt_triggers — price > 185 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P>185', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].trigger_values.close).toBe(190);
    expect(result[0].reason).toBe('Price > 185');
  });

  it('test_price_condition_lt_does_not_trigger — price < 170 does not trigger when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P<170', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<', value: 170 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_price_condition_gte_triggers — price >= 190 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P>=190', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>=', value: 190 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_price_condition_lte_triggers — price <= 190 triggers when close = 190', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'P<=190', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '<=', value: 190 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_indicator_crosses_above — RSI crosses above 50', () => {
    const ind = {
      'RSI(14)': [
        { time: '2024-01-02', value: 45 },
        { time: '2024-01-03', value: 48 },
        { time: '2024-01-04', value: 49 },
        { time: '2024-01-05', value: 55 },
      ],
    };
    const rule: AlertRule = {
      id: 'r2', name: 'RSI X>50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: 'crosses_above', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), ind, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].reason).toContain('RSI(14)');
    expect(result[0].trigger_values['RSI(14)']).toBe(55);
  });

  it('test_indicator_crosses_below — RSI crosses below 50', () => {
    const ind = {
      'RSI(14)': [
        { time: '2024-01-02', value: 55 },
        { time: '2024-01-03', value: 52 },
        { time: '2024-01-04', value: 51 },
        { time: '2024-01-05', value: 45 },
      ],
    };
    const rule: AlertRule = {
      id: 'r2b', name: 'RSI X<50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: 'crosses_below', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), ind, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].reason).toContain('crosses_below');
  });

  it('test_indicator_simple_gt — RSI > 50 triggers', () => {
    const rule: AlertRule = {
      id: 'r2c', name: 'RSI>50', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'indicator', indicator: 'RSI(14)', operator: '>', value: 50 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_structure_condition_matches — BOS bullish signal triggers', () => {
    const signals: StructureSignal[] = [
      { kind: 'BOS', direction: 'bullish', time: '2024-01-05', price: 189, confidence: 80, mtf_aligned: false },
    ];
    const rule: AlertRule = {
      id: 'r3', name: 'BOS Bull', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'structure', signal_kind: 'BOS', direction: 'bullish' }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, signals, now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].reason).toContain('BOS');
  });

  it('test_structure_min_confidence_filters — confidence 50 below threshold 70 skipped', () => {
    const signals: StructureSignal[] = [
      { kind: 'BOS', direction: 'bullish', time: '2024-01-05', price: 189, confidence: 50, mtf_aligned: false },
    ];
    const rule: AlertRule = {
      id: 'r3b', name: 'BOS Conf', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'structure', signal_kind: 'BOS', direction: 'bullish', min_confidence: 70 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, signals, now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_and_logic_requires_all — AND: both conditions must pass', () => {
    const rule: AlertRule = {
      id: 'r4', name: 'AND', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'AND',
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 200 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_and_logic_fails_if_one_false — AND: one false = no trigger', () => {
    const rule: AlertRule = {
      id: 'r4b', name: 'AND fail', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'AND',
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 189 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_or_logic_requires_one — OR: one condition sufficient', () => {
    const rule: AlertRule = {
      id: 'r5', name: 'OR', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'OR',
        conditions: [
          { kind: 'price', operator: '>', value: 200 },
          { kind: 'price', operator: '>', value: 185 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
  });

  it('test_cooldown_blocks_retrigger — triggered 30 min ago, cooldown 60 min', () => {
    const triggeredAt = new Date('2024-01-05T15:30:00Z');
    const rule: AlertRule = {
      id: 'r6', name: 'Cooldown', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: triggeredAt.toISOString(),
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_expired_rule_skipped — expiry Jan 4, now Jan 5', () => {
    const rule: AlertRule = {
      id: 'r7', name: 'Expired', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: '2024-01-04T00:00:00Z', created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_disabled_rule_skipped', () => {
    const rule: AlertRule = {
      id: 'r9', name: 'Disabled', symbol: SYM, interval: INT, enabled: false,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_rule_mismatched_symbol_skipped — engine filters by activeSymbol', () => {
    const rule: AlertRule = {
      id: 'r10', name: 'MSFT', symbol: 'MSFT', interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 185 }] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });

  it('test_empty_conditions_skipped', () => {
    const rule: AlertRule = {
      id: 'r11', name: 'Empty', symbol: SYM, interval: INT, enabled: true,
      group: { logic: 'AND', conditions: [] },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd frontend; npm run test -- --testPathPattern=chartAlertEngine
```
Expected: FAIL "Cannot find module '@/lib/chartAlertEngine'"

- [ ] **Step 3: Write engine implementation**

```typescript
// frontend/lib/chartAlertEngine.ts

import type { AlertRule, Condition, AlertHistory } from '@/types/alerts';
import type { Candle } from '@/lib/indicators';
import type { StructureSignal } from '@/types/structure';
import type { Interval } from '@/lib/chartStore';

interface Point {
  time: string;
  value: number;
}

function isCooldownPassed(rule: AlertRule, now: Date): boolean {
  if (!rule.last_triggered_at) return true;
  const lastMs = new Date(rule.last_triggered_at).getTime();
  return now.getTime() - lastMs >= rule.cooldown_minutes * 60 * 1000;
}

function isExpired(rule: AlertRule, now: Date): boolean {
  if (!rule.expiry_date) return false;
  return now > new Date(rule.expiry_date);
}

function comparePrice(op: string, a: number, b: number): boolean {
  switch (op) {
    case '>': return a > b;
    case '<': return a < b;
    case '>=': return a >= b;
    case '<=': return a <= b;
    default: return false;
  }
}

function evaluateCondition(
  condition: Condition,
  closedCandle: Candle,
  indicators: Record<string, Point[]>,
  signals: StructureSignal[],
  candleTime: string,
): { met: boolean; triggerValues: Record<string, number> } {
  const triggerValues: Record<string, number> = {};

  if (condition.kind === 'price') {
    triggerValues.close = closedCandle.close;
    return { met: comparePrice(condition.operator, closedCandle.close, condition.value), triggerValues };
  }

  if (condition.kind === 'indicator') {
    const series = indicators[condition.indicator];
    if (!series) return { met: false, triggerValues };
    const idx = series.findIndex((p) => p.time === candleTime);
    if (idx === -1) return { met: false, triggerValues };
    const currentValue = series[idx].value;
    triggerValues[condition.indicator] = currentValue;

    if (condition.operator === 'crosses_above') {
      if (idx <= 0) return { met: false, triggerValues };
      const prevValue = series[idx - 1].value;
      return { met: currentValue > condition.value && prevValue <= condition.value, triggerValues };
    }
    if (condition.operator === 'crosses_below') {
      if (idx <= 0) return { met: false, triggerValues };
      const prevValue = series[idx - 1].value;
      return { met: currentValue < condition.value && prevValue >= condition.value, triggerValues };
    }
    return { met: comparePrice(condition.operator, currentValue, condition.value), triggerValues };
  }

  if (condition.kind === 'structure') {
    const matchingSignal = signals.find((s) => {
      if (s.kind !== condition.signal_kind) return false;
      if (condition.direction) {
        if ('direction' in s && s.direction !== condition.direction) return false;
      }
      if (condition.min_confidence != null) {
        if ('confidence' in s && (s.confidence ?? 0) < condition.min_confidence) return false;
      }
      const signalTime = 'time' in s ? s.time : 'time_start' in s ? s.time_start : '';
      return signalTime === candleTime;
    });
    if (matchingSignal) {
      triggerValues[condition.signal_kind] = 1;
      return { met: true, triggerValues };
    }
    return { met: false, triggerValues };
  }

  return { met: false, triggerValues };
}

function buildReason(rule: AlertRule, triggerValues: Record<string, number>): string {
  if (rule.group.conditions.length === 0) return 'No conditions';
  return rule.group.conditions
    .map((c) => {
      if (c.kind === 'price') return `Price ${c.operator} ${c.value}`;
      if (c.kind === 'indicator') {
        const val = triggerValues[c.indicator];
        const valStr = val != null ? ` (was ${val.toFixed(2)})` : '';
        return `${c.indicator} ${c.operator} ${c.value}${valStr}`;
      }
      if (c.kind === 'structure') {
        return `${c.signal_kind} ${c.direction ?? ''} detected`.trim();
      }
      return '';
    })
    .filter(Boolean)
    .join(` ${rule.group.logic} `);
}

export function evaluateRules(
  rules: AlertRule[],
  closedCandle: Candle,
  allCandles: Candle[],
  indicators: Record<string, Point[]>,
  signals: StructureSignal[],
  now: Date,
  activeSymbol: string,
  activeInterval: Interval,
): AlertHistory[] {
  const results: AlertHistory[] = [];

  for (const rule of rules) {
    if (!rule.enabled) continue;
    if (rule.symbol !== activeSymbol) continue;
    if (rule.interval !== activeInterval) continue;
    if (rule.group.conditions.length === 0) continue;
    if (isExpired(rule, now)) continue;
    if (!isCooldownPassed(rule, now)) continue;

    const accumulatedTriggerValues: Record<string, number> = {};
    const evaluations = rule.group.conditions.map((c) => {
      const ev = evaluateCondition(c, closedCandle, indicators, signals, closedCandle.time);
      Object.assign(accumulatedTriggerValues, ev.triggerValues);
      return ev.met;
    });

    const triggered =
      rule.group.logic === 'AND'
        ? evaluations.every(Boolean)
        : evaluations.some(Boolean);

    if (triggered) {
      const id = now.getTime().toString(36) + Math.random().toString(36).slice(2, 6);
      results.push({
        id,
        rule_id: rule.id,
        symbol: rule.symbol,
        interval: rule.interval,
        triggered_at: now.toISOString(),
        candle: { ...closedCandle },
        trigger_values: accumulatedTriggerValues,
        reason: buildReason(rule, accumulatedTriggerValues),
      });
    }
  }

  return results;
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd frontend; npm run test -- --testPathPattern=chartAlertEngine
```
Expected: 17/17 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/chartAlertEngine.ts frontend/lib/__tests__/chartAlertEngine.test.ts
git commit -m "feat: add chartAlertEngine with 13 test cases (TDD)"
```

---

### Task 4: Create AlertRuleBuilder slide-in component

**Files:**
- Create: `frontend/components/organisms/AlertRuleBuilder/index.tsx`
- Create: `frontend/components/organisms/AlertRuleBuilder/AlertRuleBuilder.module.css`

- [ ] **Step 1: Write component**

```tsx
'use client';
import { useState } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { Text } from '@/components/primitives';
import type { Condition, ConditionOperator, AlertRule, LogicOperator, PriceCondition, IndicatorCondition, StructureCondition } from '@/types/alerts';
import type { SignalKind } from '@/types/structure';
import styles from './AlertRuleBuilder.module.css';

interface Props {
  onClose: () => void;
  editRule?: AlertRule | null;
}

const OPERATORS: { value: ConditionOperator; label: string }[] = [
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: 'crosses_above', label: 'crosses above' },
  { value: 'crosses_below', label: 'crosses below' },
];

const STRUCTURE_KINDS: SignalKind[] = ['FVG', 'BOS', 'CHoCH', 'OrderBlock', 'Divergence'];

const DIRECTIONS = [
  { value: '', label: 'any' },
  { value: 'bullish', label: 'bullish' },
  { value: 'bearish', label: 'bearish' },
];

function emptyPriceCondition(): PriceCondition {
  return { kind: 'price', operator: '>', value: 0 };
}

function emptyIndicatorCondition(): IndicatorCondition {
  return { kind: 'indicator', indicator: '', operator: '>', value: 0 };
}

function emptyStructureCondition(): StructureCondition {
  return { kind: 'structure', signal_kind: 'BOS' };
}

function labelForCondition(c: Condition): string {
  if (c.kind === 'price') return `Price ${c.operator} ${c.value}`;
  if (c.kind === 'indicator') return `${c.indicator || '...'} ${c.operator} ${c.value}`;
  return `${c.signal_kind}${c.direction ? ' ' + c.direction : ''}`;
}

function makeId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

export default function AlertRuleBuilder({ onClose, editRule }: Props) {
  const { symbol, interval, activeIndicators } = useChartStore();
  const { addRule, updateRule } = useChartAlertStore();
  const [name, setName] = useState(editRule?.name ?? '');
  const [conditions, setConditions] = useState<Condition[]>(
    editRule?.group.conditions ?? [emptyPriceCondition()],
  );
  const [logic, setLogic] = useState<LogicOperator>(editRule?.group.logic ?? 'AND');
  const [cooldown, setCooldown] = useState(editRule?.cooldown_minutes ?? 60);
  const [expiryType, setExpiryType] = useState<'never' | 'custom'>(editRule?.expiry_date ? 'custom' : 'never');
  const [expiryDate, setExpiryDate] = useState(editRule?.expiry_date ?? '');
  const [error, setError] = useState('');

  const indicatorOptions = activeIndicators.map((i) => ({
    value: i.id,
    label: `${i.type}(${Object.values(i.params).join(',') || 'default'})`,
  }));

  const addCondition = (kind: 'price' | 'indicator' | 'structure') => {
    if (kind === 'price') setConditions((c) => [...c, emptyPriceCondition()]);
    if (kind === 'indicator') setConditions((c) => [...c, emptyIndicatorCondition()]);
    if (kind === 'structure') setConditions((c) => [...c, emptyStructureCondition()]);
  };

  const removeCondition = (idx: number) => {
    if (conditions.length <= 1) return;
    setConditions((c) => c.filter((_, i) => i !== idx));
  };

  const updateCondition = (idx: number, patch: Partial<Condition>) => {
    setConditions((c) => c.map((cond, i) => (i === idx ? { ...cond, ...patch } as Condition : cond)));
  };

  const handleSave = () => {
    if (!name.trim()) { setError('Name is required'); return; }
    setError('');
    const rule: AlertRule = {
      id: editRule?.id ?? makeId(),
      name: name.trim(),
      symbol,
      interval,
      enabled: editRule?.enabled ?? true,
      group: { logic, conditions },
      cooldown_minutes: cooldown,
      expiry_date: expiryType === 'custom' && expiryDate ? expiryDate : null,
      created_at: editRule?.created_at ?? new Date().toISOString(),
      last_triggered_at: editRule?.last_triggered_at ?? null,
    };
    if (editRule) {
      updateRule(editRule.id, rule);
    } else {
      const added = addRule(rule);
      if (!added) { setError('A rule with these conditions already exists'); return; }
    }
    onClose();
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Text size={13} tone="primary" weight={500}>{editRule ? 'Edit Alert' : 'New Alert'}</Text>
        <button className={styles.close} onClick={onClose} aria-label="Close">&times;</button>
      </div>

      <div className={styles.body}>
        <label className={styles.field}>
          <Text size={11} tone="secondary">Name</Text>
          <input
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. AAPL breakout"
          />
        </label>

        <div className={styles.meta}>
          <Text size={11} tone="dim">Symbol: {symbol}</Text>
          <Text size={11} tone="dim">Interval: {interval}</Text>
        </div>

        <div className={styles.logicToggle}>
          <Text size={11} tone="secondary">When</Text>
          <div className={styles.logicBtns}>
            <button
              className={`${styles.logicBtn} ${logic === 'AND' ? styles.logicActive : ''}`}
              onClick={() => setLogic('AND')}
            >ALL</button>
            <button
              className={`${styles.logicBtn} ${logic === 'OR' ? styles.logicActive : ''}`}
              onClick={() => setLogic('OR')}
            >ANY</button>
          </div>
          <Text size={11} tone="dim">conditions are met</Text>
        </div>

        <div className={styles.conditions}>
          {conditions.map((c, idx) => (
            <div key={idx} className={styles.conditionRow}>
              <select
                className={styles.select}
                value={c.kind}
                onChange={(e) => {
                  const k = e.target.value as 'price' | 'indicator' | 'structure';
                  if (k === 'price') updateCondition(idx, emptyPriceCondition());
                  if (k === 'indicator') updateCondition(idx, emptyIndicatorCondition());
                  if (k === 'structure') updateCondition(idx, emptyStructureCondition());
                }}
              >
                <option value="price">Price</option>
                <option value="indicator">Indicator</option>
                <option value="structure">Structure</option>
              </select>

              {c.kind === 'price' && (
                <>
                  <select
                    className={styles.select}
                    value={c.operator}
                    onChange={(e) => updateCondition(idx, { operator: e.target.value as ConditionOperator })}
                  >
                    {OPERATORS.filter((o) => !o.value.includes('crosses')).map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    step="0.01"
                    value={c.value}
                    onChange={(e) => updateCondition(idx, { value: Number(e.target.value) })}
                  />
                </>
              )}

              {c.kind === 'indicator' && (
                <>
                  <select
                    className={styles.select}
                    value={c.indicator}
                    onChange={(e) => updateCondition(idx, { indicator: e.target.value })}
                  >
                    <option value="">Select...</option>
                    {indicatorOptions.map((o) => (
                      <option key={o.value} value={o.label}>{o.label}</option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={c.operator}
                    onChange={(e) => updateCondition(idx, { operator: e.target.value as ConditionOperator })}
                  >
                    {OPERATORS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    step="0.01"
                    value={c.value}
                    onChange={(e) => updateCondition(idx, { value: Number(e.target.value) })}
                  />
                </>
              )}

              {c.kind === 'structure' && (
                <>
                  <select
                    className={styles.select}
                    value={c.signal_kind}
                    onChange={(e) => updateCondition(idx, { signal_kind: e.target.value as SignalKind })}
                  >
                    {STRUCTURE_KINDS.map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={c.direction ?? ''}
                    onChange={(e) => updateCondition(idx, { direction: e.target.value || undefined })}
                  >
                    {DIRECTIONS.map((d) => (
                      <option key={d.value} value={d.value}>{d.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Conf%"
                    value={c.min_confidence ?? ''}
                    onChange={(e) => updateCondition(idx, { min_confidence: e.target.value ? Number(e.target.value) : undefined })}
                  />
                </>
              )}

              {conditions.length > 1 && (
                <button
                  className={styles.removeBtn}
                  onClick={() => removeCondition(idx)}
                  aria-label="Remove condition"
                >&times;</button>
              )}
            </div>
          ))}
        </div>

        <button className={styles.addBtn} onClick={() => addCondition('price')}>
          + Add Condition
        </button>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Cooldown (minutes)</Text>
          <input
            className={styles.numInput}
            type="number"
            min={1}
            max={1440}
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
          />
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Expires</Text>
          <select className={styles.select} value={expiryType} onChange={(e) => setExpiryType(e.target.value as 'never' | 'custom')}>
            <option value="never">Never</option>
            <option value="custom">Custom date</option>
          </select>
          {expiryType === 'custom' && (
            <input
              className={styles.input}
              type="date"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
            />
          )}
        </label>

        {error && <Text size={11} tone="reject">{error}</Text>}
      </div>

      <div className={styles.footer}>
        <button className={styles.cancelBtn} onClick={onClose}>Cancel</button>
        <button className={styles.saveBtn} onClick={handleSave}>
          {editRule ? 'Save' : 'Create Alert'}
        </button>
      </div>
    </div>
  );
}
```

CSS (mirrors IndicatorPanel pattern):
```css
.panel {
  position: absolute;
  top: 36px;
  right: 0;
  width: 340px;
  max-height: calc(100% - 36px);
  background: var(--bg-surface);
  border-left: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
  z-index: 100;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.close {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
}
.close:hover { color: var(--text-primary); }

.body {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.input {
  padding: 4px 8px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
}

.select {
  padding: 3px 6px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
}

.numInput {
  width: 70px;
  padding: 3px 6px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
}

.meta {
  display: flex;
  gap: 16px;
  padding: 4px 0;
}

.logicToggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logicBtns {
  display: flex;
  gap: 2px;
}

.logicBtn {
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 600;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 3px;
  color: var(--text-dim);
  cursor: pointer;
}

.logicActive {
  background: color-mix(in srgb, var(--pass) 18%, var(--bg-surface));
  border-color: var(--pass);
  color: var(--pass);
}

.conditions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.conditionRow {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  background: var(--bg-surface-2);
  border-radius: 4px;
}

.removeBtn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  padding: 0 4px;
  flex-shrink: 0;
}
.removeBtn:hover { color: var(--reject); }

.addBtn {
  padding: 4px 8px;
  font-size: 11px;
  background: transparent;
  border: 1px dashed var(--border-subtle);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}
.addBtn:hover { color: var(--text-primary); border-color: var(--border-strong); }

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 12px;
  border-top: 1px solid var(--border-subtle);
}

.cancelBtn {
  padding: 4px 12px;
  font-size: 11px;
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
}
.cancelBtn:hover { color: var(--text-primary); }

.saveBtn {
  padding: 4px 14px;
  font-size: 11px;
  font-weight: 500;
  background: var(--accent);
  border: none;
  border-radius: 4px;
  color: var(--accent-text);
  cursor: pointer;
}
.saveBtn:hover { background: var(--accent-hover); }
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend; npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/
git commit -m "feat: add AlertRuleBuilder slide-in panel with 3 condition types"
```

---

### Task 5: Create AlertToast component

**Files:**
- Create: `frontend/components/organisms/AlertToast/index.tsx`
- Create: `frontend/components/organisms/AlertToast/AlertToast.module.css`

- [ ] **Step 1: Write component**

```tsx
'use client';
import { useEffect } from 'react';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { Text } from '@/components/primitives';
import styles from './AlertToast.module.css';

export default function AlertToast() {
  const toasts = useChartAlertStore((s) => s.toasts);
  const dismissToast = useChartAlertStore((s) => s.dismissToast);

  return (
    <div className={styles.container} aria-live="polite">
      {toasts.map((t) => (
        <ToastItem key={t.id} id={t.id} message={t.message} timestamp={t.timestamp} onDismiss={dismissToast} />
      ))}
    </div>
  );
}

function ToastItem({
  id, message, timestamp, onDismiss,
}: {
  id: string; message: string; timestamp: number; onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(id), 5000);
    return () => clearTimeout(timer);
  }, [id, onDismiss]);

  return (
    <div className={styles.toast}>
      <div className={styles.toastText}>
        <Text size={12} tone="primary">{message}</Text>
        <Text size={10} tone="dim">{new Date(timestamp).toLocaleTimeString()}</Text>
      </div>
      <button className={styles.toastClose} onClick={() => onDismiss(id)} aria-label="Dismiss">&times;</button>
    </div>
  );
}
```

CSS:
```css
.container {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--pass);
  border-radius: 6px;
  min-width: 240px;
  max-width: 360px;
  animation: toastIn 200ms ease-out;
}

.toastText {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
}

.toastClose {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  padding: 0 2px;
  flex-shrink: 0;
}
.toastClose:hover { color: var(--text-primary); }

@keyframes toastIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 2: Verify typecheck**
- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/AlertToast/
git commit -m "feat: add AlertToast component (5s auto-dismiss)"
```

---

### Task 6: Modify ChartRightPanel — add Alerts tab

**Files:**
- Modify: `frontend/components/organisms/ChartRightPanel/index.tsx`
- Modify: `frontend/components/organisms/ChartRightPanel/ChartRightPanel.module.css`

- [ ] **Step 1: Add Alerts tab**

Add a third tab "Alerts" that reads from `useChartAlertStore`, showing history entries filtered by current symbol (passed as prop). Add `symbol` prop to `ChartRightPanel`.

Key additions to index.tsx:
- Import `useChartAlertStore` and `useChartStore` (for symbol)
- Add `'alerts'` to the Tab union type and tabs array
- Call `markViewed()` when alerts tab is active
- Render history list under alerts tab
- Show badge count on tab button

CSS additions: `.alertHistory{}`, `.alertHistoryRow{}`, `.alertTime{}`, `.alertValues{}`, `.badge{}`

- [ ] **Step 2: Verify typecheck**, commit

---

### Task 7: Modify ChartTopBar — add Alerts button

**Files:**
- Modify: `frontend/components/organisms/ChartTopBar/index.tsx`

- [ ] **Step 1: Add `onToggleAlerts` prop and Alerts button**

Add prop `onToggleAlerts: () => void` and render a new `.btn` button labeled "Alerts" next to "Structure".

- [ ] **Step 2: Verify typecheck**, commit

---

### Task 8: Modify ChartWorkspace — wire candle-close evaluation

**Files:**
- Modify: `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1: Wire alert evaluation**

Key changes:
1. Import `useChartAlertStore`, `evaluateRules`, `AlertToast`, `AlertRuleBuilder`
2. Add `getIndicatorPoints(candles, activeIndicators)` helper that returns `Record<string, Point[]>`
3. Add `showAlerts` state
4. On new candle detected in tick handler: evaluate rules, dispatch results
5. Pass `onToggleAlerts` to `ChartTopBar`
6. Render `{showAlerts && <AlertRuleBuilder onClose={() => setShowAlerts(false)} />}`
7. Render `<AlertToast />` at bottom of workspace
8. Reuse indicator points for chart rendering via refactored `useMemo` calls

- [ ] **Step 2: Verify typecheck**, commit

---

### Task 9: Modify alerts page — add Rules tab

**Files:**
- Modify: `frontend/app/(frame)/alerts/page.tsx`
- Modify: `frontend/app/(frame)/alerts/page.module.css`

- [ ] **Step 1: Add Rules/History tab and rules management table**

Add a top-level tab strip (Rules | History). History tab preserves existing page content. Rules tab shows a table listing all rules from `useChartAlertStore` with columns: Name, Symbol, Interval, Conditions summary, Status toggle, Last Triggered, Actions (Edit/Enable-disable/Delete). "Create Alert" button opens `AlertRuleBuilder`.

- [ ] **Step 2: Verify typecheck**, commit

---

### Task 10: Final verification

- [ ] **Step 1: Run typecheck**

```bash
cd frontend; npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 2: Run all tests**

```bash
cd frontend; npm run test
```
Expected: all tests pass including new chartAlertStore + chartAlertEngine tests.

---

## Acceptance Criteria Checklist

1. ✅ User can create alert rule with 3 condition types — AlertRuleBuilder
2. ✅ Rule persisted to localStorage — chartAlertStore persist middleware
3. ✅ Candle-close evaluation triggers price > X — evaluateRules + ChartWorkspace wiring
4. ✅ Triggered alert in ChartRightPanel Alerts tab — Task 6
5. ✅ Toast notification — AlertToast component
6. ✅ Cooldown blocks re-trigger — isCooldownPassed in engine
7. ✅ Expired rules skipped — isExpired in engine
8. ✅ History shows reason + trigger values — AlertHistory display in Alerts tab
9. ✅ Rules management page — Task 9
10. ✅ typecheck passes — Task 10
11. ✅ All new Jest tests pass — Task 2 + Task 3
