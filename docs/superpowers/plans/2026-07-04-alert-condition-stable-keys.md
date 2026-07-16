# Alert Condition Stable Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each condition row in `AlertRuleBuilder` a stable React `key`, replacing the current `key={idx}` array-index anti-pattern — so reordering, adding, or removing a condition doesn't cause React to misattribute an input's state to the wrong row.

**Architecture:** Add an optional `id?: string` field to each of the four `Condition` interfaces in `types/alerts.ts`. Generate one in every `empty*Condition()` constructor in `AlertRuleBuilder` (new conditions), and backfill one for any condition loaded from an existing saved rule that predates this change (old data has no `id`). Use `key={c.id}` once every condition is guaranteed to have one. Because two duplicate-rule-detection code paths (`chartAlertStore.ts::addRule` and `AlertRuleBuilder`'s own edit-collision check) currently compare `JSON.stringify(conditions)` directly, adding a per-condition `id` would make every condition array unique (even truly identical ones) and silently break duplicate detection — both call sites must compare conditions with `id` stripped out. A single shared `conditionsEqual()` helper (added to `chartAlertStore.ts`, which already owns the "is this a duplicate rule" concept) is used by both.

**Tech Stack:** TypeScript, React, Zustand, Jest + React Testing Library.

**Known, pre-existing limitation this plan doesn't fix:** `conditionsEqual()` (like the `JSON.stringify` comparison it replaces) is order-sensitive — two conditions with identical fields but different key insertion order would compare unequal. This risk pre-dates this plan (the original code had the exact same fragility) and this plan's own new test only exercises same-shape objects differing by `id`, not cross-origin key-order differences (e.g. a condition round-tripped through the backend's Pydantic `model_dump()` could theoretically have different key order than a frontend object literal). A structural deep-equal would close this properly but is a larger, riskier change than this plan's scope — flag to the user as a follow-up if duplicate-rule detection is ever observed to miss an actual duplicate.

---

## File Structure

- Modify: `frontend/types/alerts.ts` — add `id?: string` to `PriceCondition`, `IndicatorCondition`, `StructureCondition`, `RegimeCondition`.
- Modify: `frontend/lib/chartAlertStore.ts` — add and export `conditionsEqual()`; use it in `addRule()`'s duplicate check.
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx` — generate/backfill `id`s, use `key={c.id}`, use `conditionsEqual()` in the edit-collision check.
- Test: `frontend/lib/__tests__/chartAlertStore.test.ts` — new test proving duplicate detection ignores `id`.
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx` — new test proving condition rows get stable, non-index keys and that editing a rule with legacy (id-less) conditions still detects collisions correctly.

---

## Task 1: Add `id?: string` to the `Condition` union

**Files:**
- Modify: `frontend/types/alerts.ts:10-35`

- [ ] **Step 1: Implement**

In `frontend/types/alerts.ts`, replace lines 10-35:

Before:
```typescript
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

export interface RegimeCondition {
  kind: 'regime';
  model: RegimeModel;
  state: RegimeState;
  min_conviction?: number;
}
```

After:
```typescript
export interface PriceCondition {
  kind: 'price';
  id?: string;
  operator: ConditionOperator;
  value: number;
}

export interface IndicatorCondition {
  kind: 'indicator';
  id?: string;
  indicator: string;
  operator: ConditionOperator;
  value: number;
}

export interface StructureCondition {
  kind: 'structure';
  id?: string;
  signal_kind: SignalKind;
  direction?: 'bullish' | 'bearish';
  min_confidence?: number;
}

export interface RegimeCondition {
  kind: 'regime';
  id?: string;
  model: RegimeModel;
  state: RegimeState;
  min_conviction?: number;
}
```

`id` is optional (not required) because existing saved rules in the DB and in each user's persisted Zustand store have conditions with no `id` at all — making it required would be a breaking type change for data already on disk. Task 3 backfills a real `id` for any condition missing one as soon as it's loaded into `AlertRuleBuilder`.

- [ ] **Step 2: Run typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, no output (adding an optional field cannot break existing usages).

- [ ] **Step 3: Commit**

```bash
git add frontend/types/alerts.ts
git commit -m "feat(alerts): add optional stable id field to Condition types"
```

---

## Task 2: Make duplicate-rule detection ignore `id`

**Files:**
- Modify: `frontend/lib/chartAlertStore.ts:1-3,101-116`
- Test: `frontend/lib/__tests__/chartAlertStore.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/lib/__tests__/chartAlertStore.test.ts`:

```ts
it('blocks duplicate rule even when conditions carry different ids', () => {
  const { result } = renderHook(() => useChartAlertStore());
  act(() =>
    result.current.addRule(
      makeRule({ id: 'r1', group: { logic: 'AND', conditions: [{ kind: 'price', id: 'cond-a', operator: '>', value: 185 } as PriceCondition] } }),
    ),
  );
  act(() =>
    result.current.addRule(
      makeRule({ id: 'r2', group: { logic: 'AND', conditions: [{ kind: 'price', id: 'cond-b', operator: '>', value: 185 } as PriceCondition] } }),
    ),
  );
  // Same symbol/interval/operator/value — only the per-condition `id` differs.
  // Must still be treated as a duplicate, or every rule created through the UI
  // (which now generates a fresh id per condition) would defeat this check.
  expect(result.current.rules).toHaveLength(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=chartAlertStore`
Expected: FAIL — the new test's second `addRule` call succeeds (2 rules), because `JSON.stringify` sees the differing `id` fields as making the condition arrays different.

- [ ] **Step 3: Implement**

In `frontend/lib/chartAlertStore.ts`, update the import (line 3) and add a new exported helper after it:

Before:
```typescript
import type { AlertRule, AlertHistory } from '@/types/alerts';
```

After:
```typescript
import type { AlertRule, AlertHistory, Condition } from '@/types/alerts';

/** Compares condition arrays for the purpose of duplicate-rule detection,
 * ignoring each condition's `id` — two conditions with identical fields but
 * different (freshly generated) ids are still the same condition. */
export function conditionsEqual(a: Condition[], b: Condition[]): boolean {
  const strip = (conds: Condition[]) => conds.map(({ id: _id, ...rest }) => rest);
  return JSON.stringify(strip(a)) === JSON.stringify(strip(b));
}
```

Then update `addRule`'s duplicate check (currently lines 101-116):

Before:
```typescript
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
        if (added) pushRuleToAPI(rule);
        return added;
      },
```

After:
```typescript
      addRule: (rule) => {
        let added = false;
        set((s) => {
          const duplicate = s.rules.some(
            (r) =>
              r.symbol === rule.symbol &&
              r.interval === rule.interval &&
              conditionsEqual(r.group.conditions, rule.group.conditions),
          );
          if (duplicate) return s;
          added = true;
          return { rules: [...s.rules, rule] };
        });
        if (added) pushRuleToAPI(rule);
        return added;
      },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=chartAlertStore`
Expected: all tests in the file PASS, including the 3 pre-existing duplicate-detection tests (regression check) and the new one.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/chartAlertStore.ts frontend/lib/__tests__/chartAlertStore.test.ts
git commit -m "fix(alerts): ignore per-condition id when detecting duplicate rules"
```

---

## Task 3: Generate/backfill condition ids and use `key={c.id}` in `AlertRuleBuilder`

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx:52-82,113-144,223-224`
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`:

```tsx
describe('AlertRuleBuilder condition row keys', () => {
  it('gives every new condition a stable, generated id (not array index)', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Price'));
    fireEvent.click(screen.getByText('+ Indicator'));

    const addRuleSpy = jest.fn().mockReturnValue(true);
    useChartAlertStore.setState({ addRule: addRuleSpy } as any);
    fireEvent.change(screen.getByPlaceholderText('e.g. AAPL breakout'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('Create Alert'));

    const savedConditions = addRuleSpy.mock.calls[0][0].group.conditions;
    expect(savedConditions).toHaveLength(3); // default price condition + 2 added
    const ids = savedConditions.map((c: any) => c.id);
    expect(new Set(ids).size).toBe(3); // all unique
    expect(ids.every((id: string) => typeof id === 'string' && id.length > 0)).toBe(true);
  });

  it('backfills an id for legacy conditions loaded from a rule with none', () => {
    const legacyRule = {
      ...AAPL_RULE,
      group: { logic: 'AND' as const, conditions: [{ kind: 'price' as const, operator: '>' as const, value: 100 }] },
    };
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={legacyRule} />);
    fireEvent.click(screen.getByText('Save'));

    const savedConditions = updateRuleSpy.mock.calls[0][1].group.conditions;
    expect(savedConditions[0].id).toEqual(expect.any(String));
    expect(savedConditions[0].id.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: FAIL — conditions built today have no `id` field at all, so `savedConditions.map(c => c.id)` is all `undefined`.

- [ ] **Step 3: Implement**

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, replace the condition constructors and `makeId` (currently lines 52-70):

Before:
```typescript
function emptyPriceCondition(): PriceCondition {
  return { kind: 'price', operator: '>', value: 0 };
}

function emptyIndicatorCondition(): IndicatorCondition {
  return { kind: 'indicator', indicator: '', operator: '>', value: 0 };
}

function emptyStructureCondition(): StructureCondition {
  return { kind: 'structure', signal_kind: 'BOS' };
}

function emptyRegimeCondition(): RegimeCondition {
  return { kind: 'regime', model: 'OMM', state: 'Bull' };
}

function makeId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}
```

After:
```typescript
function makeId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

function emptyPriceCondition(): PriceCondition {
  return { kind: 'price', id: makeId(), operator: '>', value: 0 };
}

function emptyIndicatorCondition(): IndicatorCondition {
  return { kind: 'indicator', id: makeId(), indicator: '', operator: '>', value: 0 };
}

function emptyStructureCondition(): StructureCondition {
  return { kind: 'structure', id: makeId(), signal_kind: 'BOS' };
}

function emptyRegimeCondition(): RegimeCondition {
  return { kind: 'regime', id: makeId(), model: 'OMM', state: 'Bull' };
}
```

(`makeId` is moved above the constructors that now call it — function declarations are hoisted in JS so this reordering isn't strictly required, but keeps read order sensible.)

Then update the `conditions` state initializer (currently lines 79-82) to backfill missing ids:

Before:
```typescript
  const [conditions, setConditions] = useState<Condition[]>(
    seed?.group.conditions
    ?? (prefill ? [{ kind: 'price', operator: 'crosses_above', value: prefill.price } as PriceCondition] : [emptyPriceCondition()]),
  );
```

After:
```typescript
  const [conditions, setConditions] = useState<Condition[]>(
    (
      seed?.group.conditions
      ?? (prefill ? [{ kind: 'price', operator: 'crosses_above', value: prefill.price } as PriceCondition] : [emptyPriceCondition()])
    ).map((c) => (c.id ? c : { ...c, id: makeId() })),
  );
```

Then update the condition row `key` (currently line 223-224):

Before:
```tsx
        <div className={styles.conditions}>
          {conditions.map((c, idx) => (
            <div key={idx} className={styles.conditionRow}>
```

After:
```tsx
        <div className={styles.conditions}>
          {conditions.map((c, idx) => (
            <div key={c.id} className={styles.conditionRow}>
```

Finally, update the edit-collision check in `handleSave` (currently lines 131-143) to ignore `id`, using the shared helper from Task 2:

Before:
```typescript
    if (editRule) {
      const existingRules = useChartAlertStore.getState().rules;
      const collision = existingRules.some(
        (r) =>
          r.id !== editRule.id &&
          r.symbol === symbol &&
          r.interval === interval &&
          JSON.stringify(r.group.conditions) === JSON.stringify(conditions),
      );
      if (collision) {
        setError('Another rule with these conditions already exists');
        return;
      }
      updateRule(editRule.id, rule);
```

After:
```typescript
    if (editRule) {
      const existingRules = useChartAlertStore.getState().rules;
      const collision = existingRules.some(
        (r) =>
          r.id !== editRule.id &&
          r.symbol === symbol &&
          r.interval === interval &&
          conditionsEqual(r.group.conditions, conditions),
      );
      if (collision) {
        setError('Another rule with these conditions already exists');
        return;
      }
      updateRule(editRule.id, rule);
```

And add the import at the top of the file (currently line 4):

Before:
```typescript
import { useChartAlertStore } from '@/lib/chartAlertStore';
```

After:
```typescript
import { useChartAlertStore, conditionsEqual } from '@/lib/chartAlertStore';
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: all tests in the file PASS, including all pre-existing tests (regression check) and the 2 new ones.

- [ ] **Step 5: Run typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/index.tsx frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx
git commit -m "fix(alerts): use stable per-condition id as React key instead of array index"
```

---

## Final verification

- [ ] `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck` — expect clean.
- [ ] `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test` — expect all frontend tests pass, no regressions.

## Self-Review Notes

- **Spec coverage:** directly fixes deferred item 8 (`key={idx}`), plus the two duplicate-detection code paths that would otherwise silently break as a direct side effect of the fix (a risk not mentioned in the original deferred item, but a necessary consequence of it — discovered during planning, not left for implementation time to discover).
- **No placeholders:** every step has literal before/after code and runnable commands.
- **Type/name consistency:** `conditionsEqual` is defined once in `chartAlertStore.ts` and imported by `AlertRuleBuilder`, not duplicated.
