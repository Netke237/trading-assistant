# Chart Phase 3 — Alert Engine: Context Document

**Date:** 2026-05-27  
**Status:** Ready for implementation planning  
**Depends on:** Phase 1 (chart workspace + WS data), Phase 2 (market structure signals)  
**Branch to work from:** After Phase 2 is merged

---

## Overview

Phase 3 adds an in-app alert engine. Users define rules through a visual rule builder (no code), combining price conditions, indicator crossings, and market structure signals. Rules are evaluated on each **candle-close** event. Triggered alerts are stored locally and shown in a new "Alerts" tab inside `ChartRightPanel`. Storage is localStorage in Phase 3; Phase 4 will sync to the backend database.

---

## Phase 1 + 2 Foundation — What Already Exists

An implementer must understand these before starting.

### Existing WS message types (from Phase 1 + 2)

```typescript
// lib/chartWS.ts — WSMessage union (already implemented):
type WSMessage =
  | { type: 'history'; candles: Candle[] }
  | { type: 'tick'; data: { symbol: string; price: number; volume: number; timestamp: string } }
  | { type: 'structure'; symbol: string; interval: string; signals: StructureSignal[] }  // added Phase 2
  | { type: 'ping' }
  | { type: 'error'; message: string };
```

### Existing Zustand stores

```typescript
// lib/chartStore.ts — key fields:
{ symbol: string; interval: Interval; activeIndicators: IndicatorConfig[] }
// Persisted to localStorage under key 'bamendjou:chart', version 1

// lib/structureStore.ts (Phase 2) — key fields:
{ signals: Record<string, StructureSignal[]>; visibility: Record<SignalKind, boolean> }
```

### Existing component layout

```
ChartWorkspace/
  ChartTopBar/        ← symbol, TF, chart type, Indicators button, Structure button (Phase 2), [Alerts button — Phase 3 adds this]
  DrawingToolbar/     ← left sidebar
  ChartPane/          ← lightweight-charts panes
  ChartRightPanel/    ← currently: Watchlist tab + Data tab
                        Phase 3 adds: Alerts tab
```

### Existing indicator types

Computed in browser from candles:
```typescript
type IndicatorType = 'SMA' | 'EMA' | 'RSI' | 'MACD' | 'BB' | 'ATR' | 'VWAP' | 'VOL';
```

### Styling conventions (mandatory)

- CSS Modules only — no Tailwind
- Token names: `var(--bg-base)`, `var(--bg-surface)`, `var(--bg-nav)`, `var(--border-subtle)`, `var(--text-primary)`, `var(--text-secondary)`, `var(--text-dim)`, `var(--pass)`, `var(--caution)`, `var(--reject)`
- Component convention: `ComponentName/index.tsx` + `ComponentName.module.css`

---

## Phase 3 Requirements

### 1. Alert rule model

Each rule is a named condition applied to a specific symbol and timeframe.

```typescript
// frontend/types/alerts.ts

export type ConditionOperator = '>' | '<' | '>=' | '<=' | 'crosses_above' | 'crosses_below';
export type LogicOperator = 'AND' | 'OR';

export interface PriceCondition {
  kind: 'price';
  operator: ConditionOperator;
  value: number;                   // e.g. price > 185.00
}

export interface IndicatorCondition {
  kind: 'indicator';
  indicator: string;               // e.g. 'RSI(14)' | 'EMA(20)' | 'MACD_histogram'
  operator: ConditionOperator;
  value: number;                   // e.g. RSI(14) < 30
}

export interface StructureCondition {
  kind: 'structure';
  signal_kind: SignalKind;         // 'FVG' | 'BOS' | 'CHoCH' | 'OrderBlock' | 'Divergence'
  direction?: 'bullish' | 'bearish';
  min_confidence?: number;         // e.g. only trigger if confidence >= 70
}

export type Condition = PriceCondition | IndicatorCondition | StructureCondition;

export interface ConditionGroup {
  logic: LogicOperator;            // how conditions within this group combine
  conditions: Condition[];
}

export interface AlertRule {
  id: string;                      // uuid
  name: string;
  symbol: string;
  interval: Interval;
  enabled: boolean;
  group: ConditionGroup;           // the condition tree (Phase 3: flat one-level; nesting is Phase 4+)
  cooldown_minutes: number;        // minimum gap between triggers (default: 60)
  expiry_date: string | null;      // ISO date string, null = never expires
  created_at: string;              // ISO timestamp
  last_triggered_at: string | null;
}

export interface AlertHistory {
  id: string;                      // uuid
  rule_id: string;
  symbol: string;
  interval: Interval;
  triggered_at: string;            // ISO timestamp (candle-close time)
  candle: Candle;                  // the candle that triggered it
  trigger_values: Record<string, number>;   // snapshot of indicator/price values
  reason: string;                  // human-readable: "RSI(14) crossed below 30 + BOS bullish"
}
```

### 2. Alert rule evaluation engine

Evaluated on each **candle-close** event (when a `tick` message's timestamp is different from the previous tick's timestamp = new candle started). The evaluation is done entirely in the browser.

```typescript
// frontend/lib/alertEngine.ts
// Pure function — no side effects other than returning triggered rules

function evaluateRules(
  rules: AlertRule[],
  closedCandle: Candle,
  allCandles: Candle[],
  indicators: Record<string, Point[]>,  // pre-computed per indicator id
  signals: StructureSignal[],
  now: Date,
): AlertHistory[] {
  // For each enabled, non-expired rule matching symbol+interval:
  //   1. Check cooldown (now - last_triggered_at >= cooldown_minutes)
  //   2. Evaluate all conditions in the group using logic operator
  //   3. If triggered, build AlertHistory record
  //   4. Return all triggered histories
}
```

**Condition evaluation:**
- `PriceCondition`: compare `closedCandle.close` (or open/high/low depending on future extension) with `value`
- `IndicatorCondition 'crosses_above'`: indicator value for closed candle > threshold AND previous candle's value <= threshold
- `StructureCondition`: check if `signals` contains a matching signal on or after the current candle time

### 3. Rule builder UI

New component `AlertRuleBuilder/` — a slide-in panel (same slide-in pattern as `IndicatorPanel`).

```
AlertRuleBuilder layout:
  ┌─────────────────────────────────┐
  │  Alert Name  [_____________]    │
  │  Symbol: AAPL   Interval: 1D   │
  │                                 │
  │  Conditions  [AND ▾]           │
  │  ┌─────────────────────────┐   │
  │  │ [Price ▾] [>▾] [185.00] │ ✕ │
  │  │ [RSI(14)▾][<▾] [30]    │ ✕ │
  │  │ [BOS▾][bullish▾][≥70%] │ ✕ │
  │  └─────────────────────────┘   │
  │  [+ Add Condition]              │
  │                                 │
  │  Cooldown: [60] min             │
  │  Expires: [never ▾]            │
  │                                 │
  │  [Cancel]          [Save Rule]  │
  └─────────────────────────────────┘
```

**Condition type options:**
- **Price**: operator dropdown + number input
- **Indicator**: indicator selector (RSI, EMA, MACD, etc.) + operator dropdown + value input
- **Structure**: signal kind dropdown + direction dropdown + minimum confidence slider

**Logic operator:** AND / OR radio at the top of the conditions list. Phase 3 supports flat AND/OR only (no nested groups). Nested groups are Phase 4+.

### 4. Alert history panel — new "Alerts" tab in ChartRightPanel

Extend `ChartRightPanel` with a third tab "Alerts" that shows triggered alert history for the current symbol:

```
Alerts tab:
  [filter: All ▾]  [Clear all]
  ┌─────────────────────────────┐
  │ AAPL · 1D · just now        │
  │ RSI crossed below 30 + BOS  │
  │ O:182.50 H:183.00 L:181.00  │
  │                       [✕]   │
  ├─────────────────────────────┤
  │ AAPL · 1h · 2h ago         │
  │ Price > 185.00              │
  │                       [✕]   │
  └─────────────────────────────┘
```

### 5. Alerts management page

Add a route `frontend/app/(frame)/alerts/page.tsx` — a full-page alert management view with:
- Table of all rules: Name | Symbol | Interval | Conditions summary | Status | Last triggered | Actions
- Actions: Edit | Duplicate | Enable/Disable | Delete
- "Create Alert" button — opens `AlertRuleBuilder`
- Tab: Rules | History

This page should be accessible from the NavRail "ALERTS" item (already in NavRail) — but currently that item shows the `Alerts` page from `app/(frame)/alerts/`. Check if the page already exists before creating it. If it exists, add the rules management section to it; don't replace existing content.

### 6. Alert state — chartAlertStore.ts

```typescript
// frontend/lib/chartAlertStore.ts
interface AlertState {
  rules: AlertRule[];
  history: AlertHistory[];           // last 200 entries, LIFO
  addRule: (rule: AlertRule) => void;
  updateRule: (id: string, patch: Partial<AlertRule>) => void;
  deleteRule: (id: string) => void;
  addHistory: (entry: AlertHistory) => void;
  clearHistory: () => void;
  dismissHistory: (id: string) => void;
}
// Persisted to localStorage under key 'bamendjou:alerts', version 1
// Limit history to 200 entries; drop oldest when exceeded
```

### 7. Candle-close detection in ChartWorkspace

The existing `tick` handler in `ChartWorkspace` already detects when a new candle starts:

```typescript
// Already in ChartWorkspace useEffect for WS messages:
if (msg.type === 'tick') {
  setCandles(prev => {
    const last = prev[prev.length - 1];
    if (last.time === msg.data.timestamp) {
      // same candle — update it
      return [...prev.slice(0, -1), updatedCandle];
    }
    // NEW CANDLE — previous candle just closed
    const closedCandle = last;  // ← this is the trigger point for alert evaluation
    // TODO Phase 3: evaluateRules(closedCandle) here
    return [...prev, newCandle];
  });
}
```

Phase 3 extends this: when a new candle starts, call `evaluateRules` and dispatch any triggered histories to `chartAlertStore`.

### 8. Alert triggered — UX feedback

When an alert triggers:
- Show a toast notification (bottom-right, auto-dismiss after 5s): "AAPL · RSI crossed below 30"
- Increment the badge on the "Alerts" tab in `ChartRightPanel`
- Add to `chartAlertStore.history`

---

## Architecture

### Data flow

```
Candle tick received in ChartWorkspace
        │
        ▼ (new candle detected)
evaluateRules(closedCandle, allCandles, indicators, signals)  ← lib/alertEngine.ts
        │
        ├── no triggers → nothing
        │
        └── triggers → AlertHistory[]
                │
                ├── chartAlertStore.addHistory() for each trigger
                ├── update AlertRule.last_triggered_at
                └── show toast notification
```

### New files

```
frontend/
  types/
    alerts.ts                     # AlertRule, AlertHistory, Condition types
  lib/
    chartAlertStore.ts            # Zustand + persist: rules + history
    alertEngine.ts                # Pure evaluation function
  components/
    organisms/
      AlertRuleBuilder/
        index.tsx                 # Slide-in rule editor
        AlertRuleBuilder.module.css
      AlertToast/
        index.tsx                 # Toast notification for triggered alerts
        AlertToast.module.css
```

### Modified files

| File | Change |
|---|---|
| `frontend/lib/chartWS.ts` | No change needed |
| `frontend/components/organisms/ChartWorkspace/index.tsx` | Call `evaluateRules` on candle-close; dispatch history entries; import `chartAlertStore` |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Add "Alerts" button to open `AlertRuleBuilder` |
| `frontend/components/organisms/ChartRightPanel/index.tsx` | Add third "Alerts" tab; show triggered history for current symbol |
| `frontend/app/(frame)/alerts/page.tsx` | Add full rules management table (check if file exists first) |

---

## Key Implementation Notes

### Cooldown logic

```typescript
function isCooldownPassed(rule: AlertRule, now: Date): boolean {
  if (!rule.last_triggered_at) return true;
  const lastMs = new Date(rule.last_triggered_at).getTime();
  return (now.getTime() - lastMs) >= rule.cooldown_minutes * 60 * 1000;
}
```

### Expiry logic

```typescript
function isExpired(rule: AlertRule, now: Date): boolean {
  if (!rule.expiry_date) return false;
  return now > new Date(rule.expiry_date);
}
```

### Deduplication

Rules with the same (symbol, interval, conditions) as an already-existing rule should be blocked at save time, not at trigger time. Show a validation error in `AlertRuleBuilder`.

### Indicator snapshot at trigger time

When building `AlertHistory.trigger_values`, capture the CURRENT values of all indicators referenced in the rule's conditions. Store them so the user can review what values caused the trigger. Format:
```typescript
{ 'RSI(14)': 28.4, 'close': 182.50, 'EMA(20)': 183.10 }
```

### Reason string generation

```typescript
function buildReason(rule: AlertRule, triggerValues: Record<string, number>): string {
  return rule.group.conditions
    .map(c => {
      if (c.kind === 'price') return `Price ${c.operator} ${c.value}`;
      if (c.kind === 'indicator') return `${c.indicator} ${c.operator} ${c.value} (was ${triggerValues[c.indicator]?.toFixed(2)})`;
      if (c.kind === 'structure') return `${c.signal_kind} ${c.direction ?? ''} detected`;
      return '';
    })
    .filter(Boolean)
    .join(` ${rule.group.logic} `);
}
```

---

## Tests Required

### Frontend (Jest)

`frontend/lib/__tests__/alertEngine.test.ts`:
- `test_price_condition_gt_triggers` — price > 185 triggers when close = 186
- `test_price_condition_lt_does_not_trigger` — price > 185 does not trigger when close = 184
- `test_indicator_crosses_above` — EMA crosses above threshold between two candles
- `test_structure_condition_matches` — BOS bullish signal in signals list triggers
- `test_and_logic_requires_all` — AND group: both conditions must pass
- `test_or_logic_requires_one` — OR group: one condition sufficient
- `test_cooldown_blocks_retrigger` — second trigger within cooldown window blocked
- `test_expired_rule_skipped` — rule past expiry_date not evaluated

### No backend tests needed for Phase 3 (all client-side).

---

## Out of Scope (Phase 3)

- Notification delivery (Gmail, Telegram) — Phase 4
- Backend persistence of rules and history — Phase 4
- Nested AND/OR condition groups — Phase 4+
- Alert replay / backtesting
- Multi-symbol alert watching from one WS (already handled — rules filter by symbol)
- User-defined indicator parameters in conditions (Phase 3 uses defaults: RSI=14, EMA period from active indicators)

---

## Acceptance Criteria

1. User can create an alert rule with at least 3 condition types (price, indicator, structure)
2. Rule is persisted to localStorage and survives page reload
3. On candle-close, rules are evaluated — a `price > X` rule triggers correctly when price crosses
4. Triggered alert appears in ChartRightPanel "Alerts" tab within 1 render cycle
5. Triggered alert appears in toast notification
6. Cooldown correctly blocks re-trigger within the configured window
7. Expired rules are silently skipped
8. History panel shows reason string and trigger values
9. Rules management page (alerts route) lists all rules with enable/disable/delete
10. `npm run typecheck` passes with zero errors
11. All new Jest tests pass
