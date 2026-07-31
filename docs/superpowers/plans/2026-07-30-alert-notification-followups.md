# Alert Notification Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two gaps deferred from the 2026-07-30 plain-language notification redesign (commit `d9733d5`): (A) N_OF_M alert rules silently ignore their configured threshold and always fire on any 1 condition, and (B) alerts fired by the frontend's own client-side `chartAlertEngine.ts` (when a chart tab is open) still render in the old raw-technical notification format instead of the new plain-language checklist.

**Architecture:** Part A is a 2-line backend bugfix (a Pydantic schema missing a field, and a deserializer dropping it) plus regression tests that pin both the fix and the required backward-compatible default for pre-existing rules. Part B ports the backend's `_condition_label()` checklist-building logic into TypeScript so `chartAlertEngine.ts` can attach the same `checklist` array to its `AlertHistory` results, then threads that field through `chartAlertStore.ts` → `POST /alerts/history` → a new optional `AlertHistoryCreate.checklist` field → `_build_notification_text()`, mirroring the pattern the composite-rule code path already uses (checklist is computed in memory and used only for the notification text, never persisted to the `AlertHistoryModel` DB row).

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy (backend), Next.js/TypeScript + Jest (frontend). No new dependencies.

---

## Root cause (confirmed by reading the current code, 2026-07-30)

**Part A** — three places conspire to silently discard the user's N-of-M threshold:
1. `ConditionGroupIn` in `backend/app/routers/chart_alerts.py:69-71` has no `n_of_m_threshold` field. FastAPI/Pydantic v2 defaults to `extra='ignore'`, so `body.group.model_dump()` — used to build the `rule_json` that gets persisted — silently drops the value the frontend already sends (`AlertRuleBuilder` at `frontend/components/organisms/AlertRuleBuilder/index.tsx:110` correctly includes `n_of_m_threshold` in its save payload; **no frontend change is needed for Part A**, this is a backend-only bug).
2. `_deserialize_rule()` at `chart_alerts.py:393-425` only reads `group_data.get('logic', ...)` and `conditions` out of the stored `rule_json` — even if the threshold were persisted, this function throws it away when building the `ConditionGroup` dataclass.
3. `evaluate_rules()` in `backend/app/services/alert_evaluator.py:418` does `threshold = rule.group.n_of_m_threshold or 1` — since the dataclass field is always `None` today, every N_OF_M rule evaluates as "any 1 condition fires."

Existing rows in the DB that were saved as N_OF_M rules never had their threshold persisted in the first place (bug #1 happened before the row was ever written), so there is nothing to backfill. The fix must keep defaulting to `1` for rules whose stored `rule_json` lacks the key — that is the correct backward-compatible behavior, not a bug to also fix.

**Part B** — `POST /alerts/history` (`create_history_entry` at `chart_alerts.py:548-580`) is the endpoint `chartAlertStore.ts`'s `pushHistoryToAPI()` calls when a chart tab evaluates rules locally via `chartAlertEngine.ts`. That endpoint already calls `_build_notification_text()` and dispatches email/Telegram — it is **not** dead code, it just never receives a `checklist`, so `_build_notification_text()` falls through to the old `Symbol:/Interval:/Trigger:/Values:` layout (`chart_alerts.py:369-380`). The backend's own scheduled evaluation (`chart_alert_scheduler.py` → `evaluate_and_notify_for_symbol` → `evaluate_rules()` at `alert_evaluator.py:437-440`) already builds a `checklist` via `_condition_label()` and never goes through this HTTP endpoint at all, so it is unaffected by anything in this plan.

---

## File Structure

| File | Change |
|---|---|
| `backend/app/routers/chart_alerts.py` | Add `n_of_m_threshold` to `ConditionGroupIn`; populate it in `_deserialize_rule`; add `checklist` to `AlertHistoryCreate`; merge it into the entry passed to `_build_notification_text` in `create_history_entry`; update two stale comment blocks |
| `backend/tests/test_n_of_m_threshold_persistence.py` | New — Part A regression tests |
| `backend/tests/test_chart_alerts_notification_text.py` | Extend — Part B HTTP-level wiring test |
| `frontend/types/alerts.ts` | Add `checklist?` to `AlertHistory` |
| `frontend/lib/chartAlertEngine.ts` | Add `_OPERATOR_PHRASES`, `_STRUCTURE_LABELS`, `conditionLabel()`; attach `checklist` in `evaluateRules()` |
| `frontend/lib/chartAlertStore.ts` | Include `checklist` in `pushHistoryToAPI()`'s POST body |
| `frontend/lib/__tests__/chartAlertEngine.test.ts` | Extend — Part B TS unit tests |

---

## Part A — N_OF_M threshold bug

### Task 1: Write failing regression tests

**Files:**
- Create: `backend/tests/test_n_of_m_threshold_persistence.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_n_of_m_threshold_persistence.py
"""Regression coverage for the N_OF_M threshold bug: ConditionGroupIn never
declared n_of_m_threshold, so FastAPI/Pydantic silently dropped it from every
saved rule, and _deserialize_rule() never read it back even when present.
Net effect: every N_OF_M rule ran as "any 1 condition fires" regardless of
the threshold configured in the UI. See docs/superpowers/plans/
2026-07-30-alert-notification-followups.md for the full root-cause writeup.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport

from app.routers.chart_alerts import _deserialize_rule


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router

    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


def _n_of_m_rule_body(threshold: int = 2):
    return {
        'name': 'N of M test rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {
            'logic': 'N_OF_M',
            'n_of_m_threshold': threshold,
            'conditions': [
                {'kind': 'price', 'operator': '>', 'value': 100},
                {'kind': 'price', 'operator': '<', 'value': 50},
            ],
        },
        'cooldown_minutes': 60, 'expiry_date': None,
    }


@pytest.mark.asyncio
async def test_n_of_m_threshold_round_trips_through_create_and_get():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=2))
        assert resp.status_code == 201
        rule_id = resp.json()['id']
        assert resp.json()['group']['n_of_m_threshold'] == 2

        resp2 = await client.get(f'/alerts/rules/{rule_id}')
        assert resp2.status_code == 200
        assert resp2.json()['group']['n_of_m_threshold'] == 2


@pytest.mark.asyncio
async def test_n_of_m_threshold_is_enforced_by_test_rule_endpoint():
    """With threshold=2 and only 1 of 2 conditions satisfiable by the test
    candle, the rule must NOT fire. Pre-fix, this fired anyway because the
    threshold was silently coerced to 1 by the time it reached evaluate_rules().
    """
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=2))
        rule_id = resp.json()['id']

        # close=190 satisfies "price > 100" but not "price < 50" -- 1 of 2 met.
        candle = {'time': '2024-01-05T00:00:00', 'open': 188, 'high': 192, 'low': 187, 'close': 190}
        test_resp = await client.post(f'/alerts/rules/{rule_id}/test', json={'candles': [candle]})
        assert test_resp.status_code == 200
        assert test_resp.json()['matches'] == []


@pytest.mark.asyncio
async def test_n_of_m_threshold_of_one_still_fires_with_one_condition_met():
    """Sanity check the same rule DOES fire once threshold=1 -- proves the
    previous test's empty result is the threshold being enforced, not some
    unrelated evaluation failure.
    """
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=_n_of_m_rule_body(threshold=1))
        rule_id = resp.json()['id']

        candle = {'time': '2024-01-05T00:00:00', 'open': 188, 'high': 192, 'low': 187, 'close': 190}
        test_resp = await client.post(f'/alerts/rules/{rule_id}/test', json={'candles': [candle]})
        assert test_resp.status_code == 200
        assert len(test_resp.json()['matches']) == 1


def test_legacy_rule_without_stored_threshold_still_defaults_to_none():
    """Pins the required backward-compatible behavior: a rule saved before this
    fix has rule_json with no 'n_of_m_threshold' key at all (the value was
    never persisted, so there's nothing to migrate). _deserialize_rule must
    keep producing n_of_m_threshold=None for these rows so evaluate_rules()'s
    `or 1` fallback keeps their existing runtime behavior unchanged.
    """
    row = SimpleNamespace(
        id='legacy-1', name='Legacy rule', symbol='AAPL', interval='15min', enabled=True,
        cooldown_minutes=60, expiry_date=None, created_at='2026-01-01T00:00:00',
        last_triggered_at=None, condition_state='{}',
    )
    legacy_rule_json = (
        '{"logic": "N_OF_M", "conditions": '
        '[{"kind": "price", "operator": ">", "value": 100}, '
        '{"kind": "price", "operator": "<", "value": 50}]}'
    )
    rule_input = _deserialize_rule(legacy_rule_json, row)
    assert rule_input.group.n_of_m_threshold is None
```

- [ ] **Step 2: Run tests to verify the first two fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_n_of_m_threshold_persistence.py -v`
Expected: `test_n_of_m_threshold_round_trips_through_create_and_get` FAILS (`assert None == 2` or `KeyError`), `test_n_of_m_threshold_is_enforced_by_test_rule_endpoint` FAILS (`assert [...] == []` finds a spurious match), `test_n_of_m_threshold_of_one_still_fires_with_one_condition_met` PASSES already, `test_legacy_rule_without_stored_threshold_still_defaults_to_none` PASSES already.

### Task 2: Fix `ConditionGroupIn` to declare the field

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:69-71`

- [ ] **Step 1: Add the field**

```python
class ConditionGroupIn(BaseModel):
    logic: str = 'AND'
    conditions: list = Field(default_factory=list)
    n_of_m_threshold: Optional[int] = None
```

### Task 3: Fix `_deserialize_rule` to read the field back

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:418-425`

- [ ] **Step 1: Populate `ConditionGroup.n_of_m_threshold`**

```python
    return AlertRuleInput(
        id=row.id, name=row.name, symbol=row.symbol, interval=row.interval,
        enabled=bool(row.enabled),
        group=ConditionGroup(
            logic=group_data.get('logic', 'AND'),
            conditions=conditions,
            n_of_m_threshold=group_data.get('n_of_m_threshold'),
        ),
        cooldown_minutes=row.cooldown_minutes, expiry_date=row.expiry_date,
        created_at=row.created_at, last_triggered_at=row.last_triggered_at,
        condition_state=json.loads(row.condition_state or '{}'),
    )
```

### Task 4: Update the now-stale comments describing the N_OF_M bug as still-present

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:309-321`
- Modify: `backend/tests/test_chart_alerts_notification_text.py:227-233`

- [ ] **Step 1: Replace the comment describing the bug as still-present**

Find this block (lines 309-321):

```python
        elif rule_logic == 'N_OF_M':
            # `rule_threshold` is always None today: _deserialize_rule() never
            # populates ConditionGroup.n_of_m_threshold from the stored rule_json
            # (a pre-existing bug, not introduced here), so every N_OF_M rule
            # actually runs -- and is displayed here -- as a 1-of-total OR gate.
            # `or 1` mirrors evaluate_rules()'s own fallback so this text always
            # matches real runtime behavior. If _deserialize_rule is ever fixed
            # to read a real threshold, this text's meaning changes automatically
            # -- see test_n_of_m_without_stored_threshold_shows_only_needs_one in
            # test_chart_alerts_notification_text.py, which pins today's
            # always-1 behavior so that fix doesn't change this silently.
            _threshold = rule_threshold or 1
            need_suffix = '' if _threshold >= total else f' (only needs {_threshold} to fire)'
```

Replace with:

```python
        elif rule_logic == 'N_OF_M':
            # `rule_threshold` is the rule's configured n_of_m_threshold, or None
            # for rules saved before that field existed (see
            # test_legacy_rule_without_stored_threshold_still_defaults_to_none in
            # test_n_of_m_threshold_persistence.py) -- `or 1` mirrors
            # evaluate_rules()'s own fallback so this text always matches real
            # runtime behavior for both old and new rules.
            _threshold = rule_threshold or 1
            need_suffix = '' if _threshold >= total else f' (only needs {_threshold} to fire)'
```

- [ ] **Step 2: Update the now-stale comment in the existing pinning test**

`backend/tests/test_chart_alerts_notification_text.py:227-233`'s `test_n_of_m_without_stored_threshold_shows_only_needs_one` still passes after this fix (it hard-codes `rule_threshold=None` as a call argument, independent of `_deserialize_rule`'s real behavior), but its comment describes `_deserialize_rule()`'s missing-threshold behavior as "the CURRENT (buggy) runtime behavior" that "if... ever fixed... should be revisited" -- that fix is this very task. Replace the comment:

```python
    def test_n_of_m_without_stored_threshold_shows_only_needs_one(self):
        # Pins _build_notification_text()'s own rule_threshold=None fallback in
        # isolation from _deserialize_rule() (which, as of the N_OF_M threshold
        # fix, does populate a real threshold when one is stored -- see
        # test_n_of_m_threshold_persistence.py). This test still covers the
        # genuinely-legacy case: a rule saved before that fix has no threshold
        # in its stored rule_json at all, so _deserialize_rule() still passes
        # through None here, and this text must keep matching that reality.
        entry = self._entry(checklist=[
            {'label': 'A', 'met': True}, {'label': 'B', 'met': False}, {'label': 'C', 'met': False},
        ])
        _subject, plain, _html = _build_notification_text(
            entry, 'R', rule_logic='N_OF_M', rule_threshold=None,
        )
```

- [ ] **Step 3: Run the full Part A test suite**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_n_of_m_threshold_persistence.py tests/test_chart_alerts_notification_text.py tests/test_alert_router.py tests/test_alert_evaluator.py -v`
Expected: all PASS, including all four new tests from Task 1 and the pre-existing `test_n_of_m_without_stored_threshold_shows_only_needs_one`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_n_of_m_threshold_persistence.py \
        backend/tests/test_chart_alerts_notification_text.py
git commit -m "fix(alerts): persist and honor N_OF_M rule threshold

ConditionGroupIn never declared n_of_m_threshold, so Pydantic silently
dropped it from every saved rule; _deserialize_rule() also never read it
back even when present. Every N_OF_M rule ran as any-1-condition-fires
regardless of the threshold configured in the UI. Legacy rows (saved
before this fix, with no threshold in their stored rule_json) keep
defaulting to 1 -- there is nothing to backfill since the value was
never persisted for them."
```

---

## Part B — `chartAlertEngine.ts` checklist parity

### Task 5: Add `checklist` to the `AlertHistory` type

**Files:**
- Modify: `frontend/types/alerts.ts:68-77`

- [ ] **Step 1: Add the optional field**

```typescript
export interface AlertHistory {
  id: string;
  rule_id: string;
  symbol: string;
  interval: Interval;
  triggered_at: string;
  candle: Candle;
  trigger_values: Record<string, number>;
  reason: string;
  checklist?: { label: string; met: boolean }[];
}
```

### Task 6: Write failing TS tests for `conditionLabel` and the checklist

**Files:**
- Modify: `frontend/lib/__tests__/chartAlertEngine.test.ts`

- [ ] **Step 1: Add the test block**

Add near the bottom of the file (after the existing `describe('evaluateRules', ...)` block), matching the Python pinning tests in `backend/tests/test_chart_alerts_notification_text.py::TestConditionLabel` exactly so the two implementations can never silently drift apart:

```typescript
import { conditionLabel } from '@/lib/chartAlertEngine';
import type { PriceCondition, IndicatorCondition, RegimeCondition, StructureCondition } from '@/types/alerts';

describe('conditionLabel', () => {
  it('price: includes live value when available', () => {
    const c: PriceCondition = { kind: 'price', operator: '>', value: 119 };
    expect(conditionLabel(c, { close: 128.68 })).toBe('Price above 119 (was 128.68)');
  });

  it('price: omits value when not available', () => {
    const c: PriceCondition = { kind: 'price', operator: '>', value: 119 };
    expect(conditionLabel(c, {})).toBe('Price above 119');
  });

  it('indicator: includes live reading', () => {
    const c: IndicatorCondition = { kind: 'indicator', indicator: 'RSI(14)', operator: '>', value: 70 };
    expect(conditionLabel(c, { 'RSI(14)': 62.4 })).toBe('RSI(14) above 70 (was 62.40)');
  });

  it('regime: distinguishes model and conviction', () => {
    const omm: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'Bull' };
    const hmm: RegimeCondition = { kind: 'regime', model: 'HMM', state: 'Bull' };
    expect(conditionLabel(omm, {})).toBe('Trend regime: Bull');
    expect(conditionLabel(hmm, {})).toBe('Trend regime: Bull (HMM model)');
    expect(conditionLabel(omm, {})).not.toBe(conditionLabel(hmm, {}));
  });

  it('regime: shows conviction threshold when set', () => {
    const c: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'Bull', min_conviction: 70 };
    expect(conditionLabel(c, {})).toBe('Trend regime: Bull, conviction ≥70%');
  });

  it('structure: maps known signal kinds to plain labels', () => {
    const c: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bullish' };
    expect(conditionLabel(c, {})).toBe('Breakout structure (BOS, bullish)');
  });

  it('structure: falls back to the raw kind for unmapped signal kinds', () => {
    const c: StructureCondition = { kind: 'structure', signal_kind: 'Fibonacci' };
    expect(conditionLabel(c, {})).toBe('Fibonacci (Fibonacci)');
  });

  it('structure: distinguishes direction', () => {
    const bull: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bullish' };
    const bear: StructureCondition = { kind: 'structure', signal_kind: 'BOS', direction: 'bearish' };
    expect(conditionLabel(bull, {})).not.toBe(conditionLabel(bear, {}));
    expect(conditionLabel(bull, {})).toContain('bullish');
    expect(conditionLabel(bear, {})).toContain('bearish');
  });

  it('regime: the explicit "any" literal renders as "any state"', () => {
    const c: RegimeCondition = { kind: 'regime', model: 'OMM', state: 'any' };
    expect(conditionLabel(c, {})).toBe('Trend regime: any state');
  });

  // The next five tests simulate a rule fetched from the backend whose stored
  // rule_json is missing a field entirely, or has it as an explicit JSON
  // null -- GET /alerts/rules returns the raw stored JSON (see _rule_to_dict
  // in chart_alerts.py), not run through Python's own c.get(key, default)
  // defaulting, so these are real runtime shapes despite the Condition types
  // declaring these fields as required. Each test isolates exactly one null
  // field so a regression in a single `||`/`&&` guard condition is caught,
  // mirroring TestConditionLabel's null-guard tests in
  // backend/tests/test_chart_alerts_notification_text.py one-for-one.

  it('regime: null model AND null state together do not leak "null" and still read "any state"', () => {
    const c = JSON.parse('{"kind":"regime","model":null,"state":null}') as RegimeCondition;
    const label = conditionLabel(c, {});
    expect(label).not.toContain('null');
    expect(label).toBe('Trend regime: any state');
  });

  it('structure: null signal_kind falls back to "Structure signal" without leaking "null"', () => {
    const c = JSON.parse('{"kind":"structure","signal_kind":null}') as StructureCondition;
    const label = conditionLabel(c, {});
    expect(label).not.toContain('null');
    expect(label).toBe('Structure signal');
  });

  it('price: null operator alone falls back to "Price condition"', () => {
    const c = JSON.parse('{"kind":"price","operator":null,"value":119}') as PriceCondition;
    expect(conditionLabel(c, {})).toBe('Price condition');
  });

  it('price: null value alone falls back to "Price condition"', () => {
    const c = JSON.parse('{"kind":"price","operator":">","value":null}') as PriceCondition;
    expect(conditionLabel(c, {})).toBe('Price condition');
  });

  it('indicator: null indicator alone (operator/value present) falls back to "Indicator condition"', () => {
    const c = JSON.parse('{"kind":"indicator","indicator":null,"operator":">","value":70}') as IndicatorCondition;
    expect(conditionLabel(c, {})).toBe('Indicator condition');
  });

  it('indicator: null operator alone (indicator present) falls back to "Indicator condition"', () => {
    const c = JSON.parse('{"kind":"indicator","indicator":"RSI(14)","operator":null,"value":70}') as IndicatorCondition;
    expect(conditionLabel(c, {})).toBe('Indicator condition');
  });
});

describe('evaluateRules checklist', () => {
  it('attaches a checklist entry per condition with correct met flags', () => {
    const rule: AlertRule = {
      id: 'r1', name: 'N of M', symbol: SYM, interval: INT, enabled: true,
      group: {
        logic: 'N_OF_M', n_of_m_threshold: 1,
        conditions: [
          { kind: 'price', operator: '>', value: 185 },
          { kind: 'price', operator: '<', value: 100 },
        ],
      },
      cooldown_minutes: 60, expiry_date: null, created_at: '2024-01-01T00:00:00Z', last_triggered_at: null,
    };
    const result = evaluateRules([rule], closedCandle, candles(), indicators, [], now, SYM, INT);
    expect(result).toHaveLength(1);
    expect(result[0].checklist).toEqual([
      { label: 'Price above 185 (was 190.00)', met: true },
      { label: 'Price below 100 (was 190.00)', met: false },
    ]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=chartAlertEngine`
Expected: FAIL — `conditionLabel` is not exported from `@/lib/chartAlertEngine`, and `result[0].checklist` is `undefined`.

### Task 7: Implement `conditionLabel()` and wire it into `evaluateRules()`

**Files:**
- Modify: `frontend/lib/chartAlertEngine.ts`

- [ ] **Step 1: Add the phrase/label maps and `conditionLabel()`, mirroring `alert_evaluator.py`'s `_OPERATOR_PHRASES`, `_STRUCTURE_LABELS`, and `_condition_label()` (`backend/app/services/alert_evaluator.py:255-327`) exactly**

Insert after `comparePrice()` (after line 36):

```typescript
const OPERATOR_PHRASES: Record<string, string> = {
  '>': 'above', '<': 'below', '>=': 'at or above', '<=': 'at or below',
  crosses_above: 'crosses above', crosses_below: 'crosses below',
};

const STRUCTURE_LABELS: Record<string, string> = {
  BOS: 'Breakout structure',
  CHoCH: 'Reversal structure',
  FVG: 'Price gap',
  OrderBlock: 'Order block',
  Divergence: 'Divergence',
};

// Mirrors backend/app/services/alert_evaluator.py's _condition_label() --
// including its null guards -- exactly. This is the checklist label shown in
// plain-language notification text, so the two implementations must stay
// textually identical or the same rule firing from the backend scheduler vs.
// this client-side engine would show different wording for the same
// condition. The guards below are NOT dead code despite Condition's TS types
// declaring operator/value/indicator/signal_kind/state as required: this
// function also runs on rules fetched from the backend via
// chartAlertStore.ts's syncRules(), which does `await res.json()` against
// GET /alerts/rules with no runtime validation -- and that endpoint's
// _rule_to_dict() (chart_alerts.py) returns the raw stored rule_json
// untouched by Python's own defaulting logic. A rule created via a raw API
// call, or edited directly in the DB, can genuinely reach this function with
// a null/missing field at runtime despite what the type says. Without these
// guards, such a rule would interpolate JS's stringification of null/
// undefined directly into real notification text (e.g. "Price null 100").
export function conditionLabel(condition: Condition, triggerValues: Record<string, number>): string {
  if (condition.kind === 'price') {
    if (condition.operator == null || condition.value == null) return 'Price condition';
    const phrase = OPERATOR_PHRASES[condition.operator] ?? condition.operator;
    // `${value}` matches Python's f'{condition.value}' for any value actually
    // reachable here: both drop a trailing ".0" for whole numbers and print
    // fractional values (e.g. 119.5) the same way, since neither side ever
    // serializes a whole number with an artificial decimal point.
    let label = `Price ${phrase} ${condition.value}`;
    const close = triggerValues.close;
    if (typeof close === 'number') label += ` (was ${close.toFixed(2)})`;
    return label;
  }
  if (condition.kind === 'indicator') {
    if (!condition.indicator || condition.operator == null || condition.value == null) return 'Indicator condition';
    const phrase = OPERATOR_PHRASES[condition.operator] ?? condition.operator;
    let label = `${condition.indicator} ${phrase} ${condition.value}`;
    const val = triggerValues[condition.indicator];
    if (typeof val === 'number') label += ` (was ${val.toFixed(2)})`;
    return label;
  }
  if (condition.kind === 'regime') {
    const state = condition.state;
    const stateLabel = !state || state === 'any' ? 'any state' : state;
    let label = `Trend regime: ${stateLabel}`;
    if (condition.model && condition.model !== 'OMM' && condition.model !== 'any') {
      label += ` (${condition.model} model)`;
    }
    if (condition.min_conviction != null) label += `, conviction ≥${condition.min_conviction}%`;
    return label;
  }
  if (condition.kind === 'structure') {
    if (!condition.signal_kind) return 'Structure signal';
    const base = STRUCTURE_LABELS[condition.signal_kind] ?? condition.signal_kind;
    const suffix = condition.direction ? `${condition.signal_kind}, ${condition.direction}` : condition.signal_kind;
    return `${base} (${suffix})`;
  }
  return 'Condition';
}
```

- [ ] **Step 2: Attach the checklist in `evaluateRules()`**

In the `for (const rule of rules)` loop, the `evaluations` array is already built from each condition. Change the block that constructs `results.push(...)` (currently lines 173-185):

```typescript
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
        checklist: rule.group.conditions.map((c, i) => ({
          label: conditionLabel(c, accumulatedTriggerValues),
          met: evaluations[i],
        })),
      });
    }
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=chartAlertEngine`
Expected: PASS.

- [ ] **Step 4: Typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean (no errors).

### Task 8: Send the checklist to the backend

**Files:**
- Modify: `frontend/lib/chartAlertStore.ts:109-121`

- [ ] **Step 1: Include `checklist` in the POST body**

```typescript
async function pushHistoryToAPI(entry: AlertHistory): Promise<void> {
  try {
    await fetch(`${BASE_URL}/alerts/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        rule_id: entry.rule_id, symbol: entry.symbol, interval: entry.interval,
        triggered_at: entry.triggered_at, candle: entry.candle,
        trigger_values: entry.trigger_values, reason: entry.reason,
        checklist: entry.checklist,
      }),
    });
  } catch {}
}
```

### Task 9: Write failing backend test proving the checklist reaches the notification text

**Files:**
- Modify: `backend/tests/test_chart_alerts_notification_text.py`

- [ ] **Step 1: Add the HTTP-level wiring test**

Add near the end of the file (needs `AsyncClient`/`ASGITransport` imports and a small local app factory, matching `backend/tests/test_alert_router.py`'s pattern):

```python
import pytest
from httpx import AsyncClient, ASGITransport


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router

    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_post_history_with_checklist_uses_plain_language_layout(monkeypatch):
    """Proves the wiring all the way from POST /alerts/history's checklist
    field through to the dispatched notification text -- this is the endpoint
    chartAlertStore.ts's pushHistoryToAPI() calls when a chart tab evaluates
    rules locally via chartAlertEngine.ts. Without this, that path silently
    kept rendering the old Symbol:/Interval:/Trigger:/Values: layout forever,
    since _build_notification_text() only takes the plain-language branch when
    entry['checklist'] is present.
    """
    import app.routers.chart_alerts as chart_alerts_module

    captured = []
    monkeypatch.setattr(chart_alerts_module, '_dispatch', lambda channel, **kw: captured.append((channel, kw)))
    monkeypatch.setattr(
        chart_alerts_module, '_load_notification_config',
        lambda: {'telegram': {'enabled': True, 'bot_token': 'x', 'chat_id': 'y'}},
    )

    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        rule_resp = await client.post('/alerts/rules', json={
            'name': 'Client-side rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
            'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
            'cooldown_minutes': 60, 'expiry_date': None,
        })
        rule_id = rule_resp.json()['id']

        hist_resp = await client.post('/alerts/history', json={
            'rule_id': rule_id, 'symbol': 'AAPL', 'interval': '15min',
            'triggered_at': '2026-07-30T12:00:00', 'candle': {'close': 190},
            'trigger_values': {'close': 190}, 'reason': 'Price > 100',
            'checklist': [{'label': 'Price above 100 (was 190.00)', 'met': True}],
        })
        assert hist_resp.status_code == 201

    assert len(captured) == 1
    _channel, kwargs = captured[0]
    assert 'Conditions met: 1 of 1' in kwargs['text']
    assert 'Price above 100 (was 190.00)' in kwargs['text']
    assert 'Trigger:' not in kwargs['text']
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_chart_alerts_notification_text.py::test_post_history_with_checklist_uses_plain_language_layout -v`
Expected: FAIL — `AlertHistoryCreate` rejects the unknown `checklist` field... actually Pydantic v2 default `extra='ignore'` means it won't error, it will just drop it, so the failure mode is `assert 'Conditions met: 1 of 1' in kwargs['text']` failing because the old fallback layout was used instead.

### Task 10: Accept and use `checklist` in `create_history_entry`

**Files:**
- Modify: `backend/app/routers/chart_alerts.py`

- [ ] **Step 1: Add the field to `AlertHistoryCreate`**

```python
class AlertHistoryCreate(BaseModel):
    rule_id: str
    symbol: str
    interval: str
    triggered_at: str
    candle: dict
    trigger_values: dict = Field(default_factory=dict)
    reason: str
    checklist: Optional[list[dict]] = None
```

- [ ] **Step 2: Merge it into the entry before building notification text**

In `create_history_entry` (`chart_alerts.py:548-564`), the checklist is intentionally **not** added to the `AlertHistoryModel` row being persisted (`AlertHistoryModel` has no `checklist` column — this mirrors the existing composite-rule pattern at `chart_alerts.py:872-894`, where `_entry['checklist']` is used only for the in-memory dict passed to `_build_notification_text` and never written to the DB):

```python
@router.post('/history', status_code=status.HTTP_201_CREATED)
async def create_history_entry(body: AlertHistoryCreate, db: AsyncSession = Depends(get_db)):
    entry = AlertHistoryModel(
        id=uuid.uuid4().hex, rule_id=body.rule_id, symbol=body.symbol,
        interval=body.interval, triggered_at=body.triggered_at,
        candle_json=json.dumps(body.candle),
        trigger_values=json.dumps(body.trigger_values), reason=body.reason,
    )
    db.add(entry)
    await db.commit()

    entry_dict = _history_to_dict(entry)
    if body.checklist:
        entry_dict['checklist'] = body.checklist
    rule_row = (await db.execute(
        select(AlertRuleModel).where(AlertRuleModel.id == body.rule_id)
    )).scalar_one_or_none()
    rule_name = rule_row.name if rule_row else None
    subject, plain_body, html_body = _build_notification_text(entry_dict, rule_name)
```

(The rest of the function — `_load_notification_config()`, the gmail/telegram `_dispatch` calls, and `return entry_dict` — is unchanged.)

- [ ] **Step 3: Update the now-stale docstring in `_build_notification_text`**

Find this paragraph in the docstring (`chart_alerts.py:266-277`):

```python
    When ``entry`` carries a 'checklist' (populated by evaluate_rules() for
    standard rules, or _composite_checklist() for composite rules), the
    plain-language layout is used: rule name first, chart timeframe instead of
    raw interval code, and a per-condition ✓/✗ checklist instead of the flat
    "(N-of-M)"-joined condition text. Entries without a checklist -- history
    rows posted directly via POST /alerts/history without one, e.g. from the
    frontend's own client-side chartAlertEngine.ts evaluation path -- fall back
    to the original technical Symbol/Interval/Trigger/Values layout. That
    frontend path does not build a checklist today, so alerts fired from an
    open chart tab still render in the old format; giving it parity would mean
    porting _condition_label()'s logic into TypeScript, which is out of scope
    here.
```

Replace with:

```python
    When ``entry`` carries a 'checklist' (populated by evaluate_rules() for
    standard rules, _composite_checklist() for composite rules, or -- via
    POST /alerts/history's optional checklist field -- chartAlertEngine.ts's
    own conditionLabel()-based checklist for alerts fired locally from an open
    chart tab), the plain-language layout is used: rule name first, chart
    timeframe instead of raw interval code, and a per-condition ✓/✗ checklist
    instead of the flat "(N-of-M)"-joined condition text. Entries without a
    checklist fall back to the original technical Symbol/Interval/Trigger/
    Values layout -- this only happens today for a raw POST /alerts/history
    call that omits the optional field.
```

- [ ] **Step 4: Run the full Part B test suite**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && python -m pytest tests/test_chart_alerts_notification_text.py tests/test_alert_router.py -v`
Expected: all PASS, including `test_post_history_with_checklist_uses_plain_language_layout`.

- [ ] **Step 5: Commit**

```bash
git add frontend/types/alerts.ts frontend/lib/chartAlertEngine.ts frontend/lib/chartAlertStore.ts \
        frontend/lib/__tests__/chartAlertEngine.test.ts backend/app/routers/chart_alerts.py \
        backend/tests/test_chart_alerts_notification_text.py
git commit -m "feat(alerts): give chartAlertEngine.ts checklist parity with the backend evaluator

Ports _condition_label()'s label logic into a new conditionLabel() in
chartAlertEngine.ts so alerts fired from an open chart tab (the client-side
evaluation path) attach the same per-condition checklist the backend
scheduler already builds. Threaded through pushHistoryToAPI() -> a new
optional AlertHistoryCreate.checklist field -> _build_notification_text(),
mirroring how composite rules already pass their checklist in memory
without persisting it to the AlertHistoryModel row."
```

---

## Self-Review

**Spec coverage:**
- Deferred item 1 (n_of_m_threshold never populated) → Tasks 1-4, with tests pinning both the fix and the required legacy-default behavior.
- Deferred item 2 (chartAlertEngine.ts checklist parity) → Tasks 5-10, porting `_condition_label()` to TS and wiring it end-to-end to the notification text, with tests at both the TS-unit and backend-HTTP-wiring levels.
- "When done audit and fix with /K-adversarial-audit-loop" → see Next Steps below.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `conditionLabel(condition: Condition, triggerValues: Record<string, number>): string` is defined once in Task 7 and used identically in Task 6's tests and the `evaluateRules()` wiring. `AlertHistory.checklist` (Task 5) matches the shape produced in Task 7 and consumed in Task 8/10.

---

## Next Steps (per user instruction, not part of this file's task list)

1. Spawn a subagent to run the `bmad-review-adversarial-general` skill against **this plan document** (audit-only mode of `K-adversarial-audit-loop`), fix findings, and repeat until a round comes back clean.
2. Once clean, execute the plan (subagent-driven-development recommended).
3. After implementation, run `K-adversarial-audit-loop` again — this time against the resulting code diff — and fix until clean.
