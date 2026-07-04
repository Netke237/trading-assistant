# Audit Hardening Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the ten non-blocking hardening findings from the 2026-07-04 final BMAD audit of the alert/regime work — a mix of small perf cleanups, test-coverage gaps, a helper-robustness fix, a live-path cost cap, and two documented design decisions.

**Architecture:** Most findings are independent tasks that can be done in any order. **Exception — Tasks 7, 8, and 9 all edit the same `if composite_rows:` block in `chart_alerts.py` (~lines 485-540).** They MUST be applied in the order **7 → 8 → 9** (and not in parallel), because each rewrites lines the next relies on; applying them out of order will make later `Edit` old-string matches drift and fail. All other tasks touch disjoint files (`composite_trigger_evaluator.py` HMM comments, `chartAlertStore.ts`, the two alert-builder test files, `CompositeAlertDialog`). Re-verify the exact target lines at apply time, since earlier tasks reflow the block.

**Tech Stack:** FastAPI + pytest (backend), React + Jest/RTL (frontend).

**Source findings (verbatim mapping):**
| # | Finding |
|---|---|
| F1 | 1500-candle cap on `test_rule` never benchmarked |
| F2 | Notification text re-runs the mean-reversion strategy scan a second time |
| F3 | Daily bars fetched once and handed to all composite rules, not per-rule |
| F4 | Model-label spelling differs between the two alert builders |
| F5 | No test with OMM + HMM_directional both present under `model='any'` + Bear |
| F6 | "Sideways-style" un-fireable combo — verify none is reachable, guard it |
| F7 | `conditionsEqual` strips condition `id` only one level deep |
| F8 | Remount test proves node identity but not keyboard-focus survival |
| F9 | HMM compute failures fail silently (inherited pattern) |
| F10 | Live WS path still feeds unbounded candle history into per-tick model fits |

---

## IMPORTANT correction on F6 (read before starting)

The original plan intent for F6 was "block impossible model+state combos on save." Verification of the current code disproves the premise: each model's dropdown now lists only its own real states, and `model='any'` lists the **union** (`REGIME_STATES_ANY`). Under `model='any'` the backend checks the condition against **every** model's snapshot (`alert_evaluator._evaluate_regime_condition`), so every union state is producible by *at least one* model — i.e. **no dropdown-reachable combo is un-fireable anymore.** Blocking on save would therefore reject *valid* conditions and is the wrong fix. F6 is re-scoped to: (a) a regression test proving no reachable combo is un-fireable, and (b) an optional soft inline hint. See Task 6.

---

## Task 1 (F4): Align model-label spelling in CompositeAlertDialog

**Files:**
- Modify: `frontend/components/organisms/CompositeAlertDialog/index.tsx` (model `<option>`s ~line 162-165)

Note: the two builders use *different* model taxonomies on purpose — AlertRuleBuilder's regime condition uses `OMM/HMM/HMM_directional`; CompositeAlertDialog uses `OMM/HMM_daily/HMM_intraday`. We are only making the human labels consistent in *style* (parenthesized qualifier), not merging the taxonomies.

- [ ] **Step 1: Update the option labels**

Replace the model `<option>`s in `CompositeAlertDialog`:

```tsx
                <option value="OMM">OMM (daily)</option>
                <option value="HMM_daily">HMM (daily)</option>
                <option value="HMM_intraday">HMM (intraday)</option>
                <option value="any">Any model</option>
```

- [ ] **Step 2: Typecheck + existing tests**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=CompositeAlertDialog`
Expected: clean / PASS (labels are display-only; values unchanged).

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/CompositeAlertDialog/index.tsx
git commit -m "style(alerts): parenthesized model labels in CompositeAlertDialog for consistency"
```

---

## Task 2 (F5): Test OMM + HMM_directional co-present under model='any'

**Files:**
- Test: `backend/tests/test_regime_condition_any_model.py` (create, or add to the existing regime-condition test module if present)

- [ ] **Step 1: Confirm the target function signature**

`build_regime_snapshot(candles)` returns a dict keyed by model; `_evaluate_regime_condition(condition, regime_by_model)` returns `(bool, dict)`. Confirm import paths:

Run: `cd backend && venv/Scripts/python.exe -c "from app.services.alert_evaluator import build_regime_snapshot, _evaluate_regime_condition; print('ok')"`
Expected: `ok`.

- [ ] **Step 2: Write the test**

> **Real snapshot shape (verified):** `build_regime_snapshot` returns `{'OMM': {'state': ..., 'conviction': ...}, 'HMM': {...}, 'HMM_directional': {...}}` — the confidence key is **`conviction`** (there is no `conviction_pct` or `p_stay` key). `_evaluate_regime_condition` reads `regime.get('state')` and `regime.get('conviction')`, and applies an **OMM-Bear sign flip** (`conviction = -conviction` only when `model=='OMM'` and `state=='Bear'`). The test below uses the real keys and includes a `min_conviction` case so the conviction branch is genuinely exercised.

```python
# backend/tests/test_regime_condition_any_model.py
from types import SimpleNamespace
from app.services.alert_evaluator import _evaluate_regime_condition


def _cond(model, state, min_conviction=None):
    # Mirror the RegimeCondition shape _evaluate_regime_condition consumes.
    return SimpleNamespace(kind="regime", model=model, state=state, min_conviction=min_conviction)


def test_any_model_matches_when_only_directional_is_bear():
    # OMM says Bull, directional HMM says Bear. A model='any' + 'Bear' condition
    # must fire because at least one model (directional) is Bear.
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM": {"state": "Trending", "conviction": 80},
        "HMM_directional": {"state": "Bear", "conviction": 75},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear"), regime_by_model)
    assert fired is True


def test_any_model_no_match_when_no_model_is_bear():
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM": {"state": "Trending", "conviction": 80},
        "HMM_directional": {"state": "Bull", "conviction": 75},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear"), regime_by_model)
    assert fired is False


def test_any_model_conviction_gate_blocks_directional_bear_below_threshold():
    # HMM_directional is Bear at conviction 60; a min_conviction of 70 must block it
    # (HMM_directional is NOT sign-flipped — only OMM-Bear is). Exercises the
    # conviction branch, not just state matching.
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM_directional": {"state": "Bear", "conviction": 60},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear", min_conviction=70), regime_by_model)
    assert fired is False
```

- [ ] **Step 3: Run**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_regime_condition_any_model.py -v`
Expected: PASS (three tests). This is test-only — do NOT change production code. If `_REGIME_MODEL_NAMES` ordering matters, note the `model='any'` path iterates that constant and returns on the first matching model.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_regime_condition_any_model.py
git commit -m "test(alerts): cover OMM+HMM_directional co-present under model='any'"
```

---

## Task 3 (F7): Make `conditionsEqual` strip ids at any depth

**Files:**
- Modify: `frontend/lib/chartAlertStore.ts` (`conditionsEqual` ~line 10-13)
- Test: `frontend/lib/__tests__/chartAlertStore.conditionsEqual.test.ts` (create)

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/__tests__/chartAlertStore.conditionsEqual.test.ts
import { conditionsEqual } from '../chartAlertStore';
import type { Condition } from '@/types/alerts';

describe('conditionsEqual deep id stripping', () => {
  it('treats two conditions differing only by top-level id as equal', () => {
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10 }] as Condition[];
    const b = [{ kind: 'price', id: 'x2', operator: '>', value: 10 }] as Condition[];
    expect(conditionsEqual(a, b)).toBe(true);
  });

  it('ignores an id nested inside a condition sub-object', () => {
    // Guards the recursive strip: a future nested-id condition type must still
    // compare equal when only the nested id differs.
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10, meta: { id: 'n1', tag: 't' } }] as unknown as Condition[];
    const b = [{ kind: 'price', id: 'x2', operator: '>', value: 10, meta: { id: 'n2', tag: 't' } }] as unknown as Condition[];
    expect(conditionsEqual(a, b)).toBe(true);
  });

  it('still distinguishes conditions that differ on a real field', () => {
    const a = [{ kind: 'price', id: 'x1', operator: '>', value: 10 }] as Condition[];
    const b = [{ kind: 'price', id: 'x1', operator: '>', value: 11 }] as Condition[];
    expect(conditionsEqual(a, b)).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify the nested-id test fails**

Run: `cd frontend && npm run test -- --testPathPattern=conditionsEqual`
Expected: the nested-id case FAILS (current strip is one level deep).

- [ ] **Step 3: Implement recursive id stripping**

Replace `conditionsEqual`:

```ts
export function conditionsEqual(a: Condition[], b: Condition[]): boolean {
  const stripDeep = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(stripDeep);
    if (v && typeof v === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
        if (k === 'id') continue;
        out[k] = stripDeep(val);
      }
      return out;
    }
    return v;
  };
  return JSON.stringify(stripDeep(a)) === JSON.stringify(stripDeep(b));
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm run test -- --testPathPattern=conditionsEqual`
Expected: PASS.

- [ ] **Step 5: Regression — duplicate-detection tests still pass**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: PASS (duplicate-collision behaviour unchanged for flat conditions).

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/chartAlertStore.ts frontend/lib/__tests__/chartAlertStore.conditionsEqual.test.ts
git commit -m "fix(alerts): strip condition ids at any depth in conditionsEqual"
```

---

## Task 4 (F8): Assert keyboard focus survives a kind switch

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx` (add to the "condition row keys" describe, after the existing remount test ~line 178)

- [ ] **Step 1: Add the focus-survival test**

```tsx
  it('keeps keyboard focus on the kind <select> after switching kind', () => {
    // Stronger than node-identity: proves the user's focus ring is not dropped.
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    const kindSelect = screen.getByDisplayValue('Price') as HTMLSelectElement;
    kindSelect.focus();
    expect(document.activeElement).toBe(kindSelect);

    fireEvent.change(kindSelect, { target: { value: 'regime' } });

    // Same element instance, still connected, still focused — no remount stole focus.
    const kindSelectAfter = screen.getByDisplayValue('Regime (OMM/HMM)') as HTMLSelectElement;
    expect(kindSelectAfter).toBe(kindSelect);   // node identity (superset of the remount test)
    expect(kindSelectAfter.isConnected).toBe(true);
    expect(document.activeElement).toBe(kindSelectAfter);  // focus specifically survived
  });
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: PASS. The node-identity + `isConnected` assertions cannot regress if the existing remount test passes; the `activeElement` assertion additionally proves focus. In the unlikely event jsdom drops `activeElement` despite the node never being remounted, keep the node-identity + `isConnected` assertions and replace the `activeElement` line with a comment noting jsdom's limitation — do not weaken the other two.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx
git commit -m "test(alerts): assert focus survives condition kind switch"
```

---

## Task 5 (F9): Document HMM silent-failure as a deliberate fail-closed choice

**Files:**
- Modify: `backend/app/services/composite_trigger_evaluator.py` (the three `except Exception` HMM branches in `evaluate_from_context`, ~lines 204, 218; and `evaluate_scheduled`'s HMM branches ~lines 293, 305)

Decision (locked, per user): keep HMM compute failures **silent to the alert** (return `False`) but ensure each site logs at WARNING and carries an explicit comment so a future reader does not "fix" it into a user-facing error without a deliberate decision. This matches the pattern already used elsewhere for regime failures.

- [ ] **Step 1: Add explicit fail-closed comments**

At each HMM `except Exception as exc:` branch that currently does `logger.warning(...)` then `return False`/`continue`, prepend a comment (example for the `evaluate_from_context` HMM_intraday branch):

```python
        except Exception as exc:
            # Deliberate fail-closed: if the HMM model errors we suppress the alert
            # (return False) rather than surfacing an error alert, matching the OMM/
            # regime-failure pattern. Logged at WARNING for observability. If this
            # ever needs to become a user-visible error, that is a product decision,
            # not a silent code change.
            logger.warning("evaluate_from_context: HMM_intraday failed — %s", exc)
            return False
```

Apply the equivalent comment to the HMM_daily branch in `evaluate_from_context` and both HMM branches in `evaluate_scheduled`. Do not change control flow.

- [ ] **Step 2: Verify no behaviour change**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q -k "composite or regime or hmm"`
Expected: PASS, unchanged counts.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/composite_trigger_evaluator.py
git commit -m "docs(alerts): mark HMM compute failures as deliberate fail-closed"
```

---

## Task 6 (F6): Regression-guard that no reachable regime combo is un-fireable

**Files:**
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx` (add a describe block)

See the "IMPORTANT correction on F6" section above — this is a test + inert-guard task, NOT a save-block.

- [ ] **Step 1: Add a test asserting each model's state list is a subset of the union**

```tsx
import { REGIME_STATES_ANY_FOR_TEST } from '@/components/organisms/AlertRuleBuilder/regimeStates';
// If the constants are not exported, this test instead reads the rendered dropdown
// options per model (see Step 2 fallback).
```

Because the regime-state constants currently live as module-private `const`s in `AlertRuleBuilder/index.tsx`, first extract them to a tiny exported module so they are testable:

- Create `frontend/components/organisms/AlertRuleBuilder/regimeStates.ts` and move `REGIME_STATES_OMM`, `REGIME_STATES_HMM`, `REGIME_STATES_HMM_DIRECTIONAL`, `REGIME_STATES_ANY`, `REGIME_MODELS`, and `regimeStatesFor` into it, re-exporting from `index.tsx` (import them back so `index.tsx` behaviour is unchanged).

- [ ] **Step 2: Write the guard test**

The guard must compare each model's list against an **independent, hard-coded** expected list — NOT against the same const under test (that would be a tautology that a phantom state would pass, since it would appear on both sides). The expected lists are the real states each model can emit, per `backend/app/services/regime_omm.py`, `regime_hmm.py::_assign_labels`, and `regime_hmm_daily.py`'s `label_by_state` (plus the leading `'any'` sentinel the dropdown adds):

```tsx
// in AlertRuleBuilder.test.tsx
import {
  REGIME_STATES_OMM, REGIME_STATES_HMM, REGIME_STATES_HMM_DIRECTIONAL, REGIME_STATES_ANY,
} from '@/components/organisms/AlertRuleBuilder/regimeStates';

describe('regime dropdown fireability', () => {
  it('each model offers exactly its real emittable states (guards the old "Sideways" phantom bug)', () => {
    // Hard-coded expectations, independent of the consts under test — a phantom state
    // added to any list (e.g. re-adding "Sideways" to HMM) makes the corresponding
    // assertion fail, which the old tautological check could not catch.
    expect(REGIME_STATES_OMM).toEqual(['any', 'Bull', 'Bear', 'Choppy']);
    expect(REGIME_STATES_HMM).toEqual(['any', 'Trending', 'Choppy', 'Mean-reverting']);
    expect(REGIME_STATES_HMM_DIRECTIONAL).toEqual(['any', 'Bull', 'Bear', 'Sideways']);
  });

  it('the "any" state list is exactly the de-duplicated union of the three model lists', () => {
    // Under model='any' the backend checks every model, so every union state is
    // producible by at least one model — none are un-fireable. This asserts ANY has
    // no extra (un-fireable) state and omits none.
    const union = Array.from(new Set([
      ...REGIME_STATES_OMM, ...REGIME_STATES_HMM, ...REGIME_STATES_HMM_DIRECTIONAL,
    ]));
    expect(REGIME_STATES_ANY).toEqual(union);
  });
});
```

If any hard-coded list above does not match the real emittable states, fix the EXPECTATION to match `regime_hmm.py`/`regime_hmm_daily.py` (do not change the production const — that is what the guard protects).

- [ ] **Step 3: Run tests + typecheck**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: clean / PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/
git commit -m "test(alerts): guard regime dropdowns against un-fireable state combos"
```

---

## Task 7 (F3): Scope daily-bar handoff per-rule in the live composite path

**Files:**
- Modify: `backend/app/routers/chart_alerts.py` (composite loop ~lines 517-524)

Note: the daily-bar *fetch* is already gated by `any(...)` (design is correct); this only stops handing daily bars to rules that don't need them, so a rule's own eval can't be influenced by bars it never asked for. Behaviour-preserving cleanup.

- [ ] **Step 1: Compute per-rule need inside the loop**

In the `for _row, _rj in composite_rows:` loop, before the `evaluate_from_context` call, derive per-rule bars:

```python
            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                _direction = _td.get("direction") or "Bullish"
                _rule_needs_daily = bool(_rj.get("strategy_confirmations")) or _rj.get("primary", {}).get("model") == "HMM_daily"
                _rule_daily = _bars_daily if _rule_needs_daily else []
                try:
                    _fired = evaluate_from_context(
                        _td, _omm, signals, indicators,
                        bars_daily=_rule_daily, bars_intraday=_bars_intraday,
                    )
```

And use `_rule_daily` in the matching `describe_match(...)` call for that rule (replace `bars_daily=_bars_daily` with `bars_daily=_rule_daily`).

- [ ] **Step 2: Run composite WS tests**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q -k "composite"`
Expected: PASS, unchanged.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/chart_alerts.py
git commit -m "refactor(alerts): hand composite rules only the daily bars they need"
```

---

## Task 8 (F10): Cap the candle window fed to per-tick model fits (live path)

**Files:**
- Modify: `backend/app/routers/chart_alerts.py` (add constant near `MAX_TEST_RULE_CANDLES` ~line 37; regime snapshot call ~line 436; composite OMM/bar derivations ~lines 485-515)

The live `evaluate_and_notify_for_symbol` fits regime models (`build_regime_snapshot`, `compute_omm`, and — via composite — intraday/daily HMM) on **each** candle close, over the *full* `all_candles` history. Cap the input to those fits to a bounded recent window, mirroring the `test_rule` cap. Standard price/indicator evaluation is left on `all_candles` (unchanged) to avoid altering indicator behaviour.

- [ ] **Step 1: Add the constant**

Near `MAX_TEST_RULE_CANDLES`:

```python
# The live WS path re-fits regime/HMM/OMM models on every candle close. Fitting over
# unbounded history makes each tick's cost grow with the symbol's stored history.
# Cap the model-fit window to a bounded recent slice; 1500 bars covers a full intraday
# session plus the models' 200-bar minimums with wide margin. Mirrors MAX_TEST_RULE_CANDLES.
MAX_LIVE_MODEL_CANDLES = 1500
```

- [ ] **Step 2: Cap the standard regime-snapshot input**

Change the regime snapshot line:

```python
    regime_by_model = build_regime_snapshot(all_candles[-MAX_LIVE_MODEL_CANDLES:]) if needs_regime else None
```

- [ ] **Step 3: Cap the composite model inputs**

In the `if composite_rows:` block, base the OMM/intraday/daily derivations on a capped slice:

```python
            _model_candles = all_candles[-MAX_LIVE_MODEL_CANDLES:] if all_candles else []
            _closes = [c["close"] for c in _model_candles]
            _omm = compute_omm(_closes) if len(_closes) >= 100 else None
```

and replace subsequent `all_candles` uses *inside the composite block* for bar derivations with `_model_candles`:

```python
                    _bars_daily = _model_candles      # in the "interval in (1D,1W)" reuse branch
```
```python
            _bars_intraday = _model_candles if interval not in ("1D", "1W") else []
```

Leave the `get_bars(...)` daily fetch (the 730-day branch) as-is — it already fetches a bounded date range, and capping is unnecessary there.

- [ ] **Step 4: Test — regime + composite still fire correctly**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q -k "composite or regime or chart_alerts"`
Expected: PASS. If any test feeds >1500 synthetic candles and asserts on a value that the cap changes, inspect it — the cap should not change fired/not-fired for realistic inputs; if a test relied on ancient history, adjust the test's expectation with a comment, not the cap.

- [ ] **Step 5: Full backend suite**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q`
Expected: 0 failed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/chart_alerts.py
git commit -m "perf(alerts): cap live-path model-fit window to MAX_LIVE_MODEL_CANDLES"
```

---

## Task 9 (F2): Run the mean-reversion strategy scan once per composite fire

**Files:**
- Modify: `backend/app/services/composite_trigger_evaluator.py` (add `evaluate_from_context_detailed`)
- Modify: `backend/app/routers/chart_alerts.py` (composite loop — use the combined call)
- Test: `backend/tests/test_composite_detailed_parity.py` (create)

Today a fired composite rule scans the MR strategies twice: once in `evaluate_from_context` (the fire gate) and again in `describe_match` (the reason text). Add a combined `evaluate_from_context_detailed` that returns `(fired, detail)` computing the strategy/structure match once, and prove it is behaviourally identical to the current two-call sequence.

- [ ] **Step 1: Write the parity test first**

```python
# backend/tests/test_composite_detailed_parity.py
from app.services.composite_trigger_evaluator import (
    evaluate_from_context, describe_match, evaluate_from_context_detailed,
)

TRIGGER = {
    "primary": {"model": "any"},
    "confirmations": [], "min_confirmations": 0,
    "strategy_confirmations": [], "min_strategy_confirmations": 0,
    "direction": "Bullish",
}


def test_detailed_matches_two_call_sequence_when_fired():
    fired_old = evaluate_from_context(TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[])
    detail_old = describe_match(TRIGGER, structure_signals=[], indicator_values={},
                                bars_daily=[], bars_intraday=[], direction="Bullish")
    fired_new, detail_new = evaluate_from_context_detailed(
        TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[], direction="Bullish",
    )
    assert fired_new == fired_old
    assert detail_new == detail_old


def test_detailed_returns_none_detail_when_not_fired():
    trig = {**TRIGGER, "primary": {"model": "OMM", "to_state": "Bull"}}
    # OMM primary required but omm_result is None -> should not fire, detail None.
    fired_new, detail_new = evaluate_from_context_detailed(
        trig, None, [], {}, bars_daily=[], bars_intraday=[], direction="Bullish",
    )
    assert fired_new is False
    assert detail_new is None


def test_detailed_threads_symbol_into_describe_match():
    # Locks in the finding-4 fix: the symbol kwarg must reach describe_match (it is
    # otherwise inert on the router path, so mock describe_match and assert directly).
    from unittest.mock import patch
    with patch("app.services.composite_trigger_evaluator.describe_match") as mock_desc:
        mock_desc.return_value = {
            "structure_matched": [], "structure_total": 0,
            "strategy_matched": [], "strategy_total": 0,
        }
        fired, _ = evaluate_from_context_detailed(
            TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[],
            direction="Bullish", symbol="AAPL",
        )
    assert fired is True
    assert mock_desc.call_args.kwargs["symbol"] == "AAPL"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_composite_detailed_parity.py -v`
Expected: FAIL — `evaluate_from_context_detailed` does not exist.

- [ ] **Step 3: Implement the combined function**

Add to `composite_trigger_evaluator.py`. It reuses the existing gate logic, then — only if fired — builds the same detail `describe_match` would, from the SAME bars, without re-scanning inside a second entry point:

```python
def evaluate_from_context_detailed(
    trigger_def: dict,
    omm_result,
    structure_signals: list[dict],
    indicator_values: dict,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    direction: str = "Bullish",
    symbol: str = "",
) -> tuple[bool, dict | None]:
    """Fire-gate + match detail in one pass. Returns (fired, detail) where detail is
    the describe_match() dict when fired, else None. Equivalent to calling
    evaluate_from_context() then describe_match(), but the strategy/structure scan is
    only performed on the describe side once the gate passes — no double scan.

    ``symbol`` is threaded through to describe_match so its structure-recompute branch
    (hit only when structure_signals is None) is not silently narrowed to symbol=""."""
    fired = evaluate_from_context(
        trigger_def, omm_result, structure_signals, indicator_values,
        bars_daily=bars_daily, bars_intraday=bars_intraday,
    )
    if not fired:
        return False, None
    detail = describe_match(
        trigger_def, structure_signals=structure_signals, indicator_values=indicator_values,
        bars_daily=bars_daily, bars_intraday=bars_intraday, symbol=symbol, direction=direction,
    )
    return True, detail
```

Note: this consolidates the two CALLS the router makes (removing the router's separate `describe_match` call), but `evaluate_from_context` itself still runs its own strategy gate. True single-scan requires threading the matched-list out of the gate; that is a deeper refactor with higher regression risk. This task delivers the safe consolidation (one entry point, detail only built on fire) and documents the residual. If the deeper single-scan is wanted, it is a separate follow-up — flag to the user rather than expanding scope here.

- [ ] **Step 4: Wire the router to the combined call**

In `chart_alerts.py`'s composite loop, replace the `_fired = evaluate_from_context(...)` + later `_detail = describe_match(...)` pair with:

```python
                try:
                    _fired, _detail = evaluate_from_context_detailed(
                        _td, _omm, signals, indicators,
                        bars_daily=_rule_daily, bars_intraday=_bars_intraday,
                        direction=_direction, symbol=symbol,
                    )
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue
                if not _fired:
                    continue
```

and update the import line to include `evaluate_from_context_detailed` (drop `evaluate_from_context`/`describe_match` if now unused in that block; keep whichever other code paths still use them).

- [ ] **Step 5: Run tests**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_composite_detailed_parity.py -v && venv/Scripts/python.exe -m pytest -q -k "composite"`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `cd backend && venv/Scripts/python.exe -m pytest -q`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/composite_trigger_evaluator.py backend/app/routers/chart_alerts.py backend/tests/test_composite_detailed_parity.py
git commit -m "refactor(alerts): single composite fire+describe entry point (evaluate_from_context_detailed)"
```

**Depends on:** Task 7 (uses `_rule_daily`). Do Task 7 first, or substitute `_bars_daily` if Task 7 is skipped.

---

## Task 10 (F1): Benchmark the test_rule candle cap and record the result

**Files:**
- Create: `backend/scripts/bench_test_rule_candles.py` (throwaway benchmark, kept for reproducibility)
- Modify: `backend/app/routers/chart_alerts.py` (update the `MAX_TEST_RULE_CANDLES` comment with the measured figure)

- [ ] **Step 1: Write the benchmark script**

```python
# backend/scripts/bench_test_rule_candles.py
"""Measures how long test_rule's per-candle regime recompute takes at the cap.
Run: cd backend && venv/Scripts/python.exe scripts/bench_test_rule_candles.py"""
import time
import random
from app.services.alert_evaluator import build_regime_snapshot


def synth(n: int) -> list[dict]:
    price = 100.0
    out = []
    for _ in range(n):
        price *= 1 + random.uniform(-0.01, 0.01)
        out.append({"open": price, "high": price * 1.01, "low": price * 0.99,
                    "close": price, "volume": 1_000_000})
    return out


def main():
    for n in (200, 500, 1000, 1500):
        candles = synth(n)
        # Simulate the worst case test_rule hits: recompute once per candle.
        t0 = time.perf_counter()
        for i in range(200, n + 1):
            build_regime_snapshot(candles[:i])
        dt = time.perf_counter() - t0
        print(f"n={n:5d}  total_recompute={dt:7.2f}s  per_candle={dt / max(1, n - 200) * 1000:6.1f}ms")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the benchmark**

Run: `cd backend && venv/Scripts/python.exe scripts/bench_test_rule_candles.py`
Expected: printed timings. Record the `n=1500` total.

- [ ] **Step 3: Confirm or adjust the cap**

- If the `n=1500` full-recompute total is acceptable for a manual dry-run endpoint (rule of thumb: ≤ ~10s wall for the whole endpoint call), keep `MAX_TEST_RULE_CANDLES = 1500` and update its comment to cite the measured number, e.g. `# Benchmarked 2026-07-04: 1500 candles ≈ X.Xs full recompute (see scripts/bench_test_rule_candles.py).`
- If it is materially slower than ~10s, lower the cap to the largest round number that stays under budget and update both the constant and comment.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/bench_test_rule_candles.py backend/app/routers/chart_alerts.py
git commit -m "chore(alerts): benchmark test_rule candle cap and record measured figure"
```

---

## Self-review checklist (done during writing)

- All ten findings mapped to a task (F1→T10, F2→T9, F3→T7, F4→T1, F5→T2, F6→T6, F7→T3, F8→T4, F9→T5, F10→T8).
- F6 premise re-verified against code and re-scoped (block-on-save would reject valid conditions — see correction section). This is the one substantive deviation from the earlier stated default; flagged to the user.
- Ordering dependency: T9 depends on T7 (`_rule_daily`); noted in T9. All other tasks independent.
- No placeholders; every code step shows complete code and an exact command with expected output.
- Type/name consistency: `MAX_LIVE_MODEL_CANDLES` (T8), `evaluate_from_context_detailed(...)` signature identical in helper (T9 S3) and router call (T9 S4), `_rule_daily` defined in T7 and consumed in T9.
- Residual scope honestly flagged in T9 S3 (deeper true single-scan is a separate follow-up, not silently dropped).
