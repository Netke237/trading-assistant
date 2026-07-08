# Directional HMM Regime Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `regime_hmm_daily.py`'s Bull/Bear/Sideways directional HMM model into the *simple* alert-condition regime system (`RegimeCondition` / `build_regime_snapshot()` in `alert_evaluator.py`, used by standard chart alert rules — NOT the composite-watch system), fixing four related gaps in that one area: the model is completely unreachable from alert conditions today (so `'Sideways'` is dead type-union member no rule can ever match), the Bear-conviction sign-flip is hardcoded to assume every model's conviction is Bullish-framed like OMM's (which would silently break for this new model), and the UI mislabels HMM p_stay as "Conv%".

**Architecture:** Add a third snapshot key, `'HMM_directional'`, to `build_regime_snapshot()`, computed via `regime_hmm_daily.py::compute_directional_hmm()` under the same `len(candles) >= 200` gate the existing `'HMM'` key uses. Fix `_evaluate_regime_condition()`'s sign-flip to be scoped to the model that actually has Bullish-framed conviction (OMM) rather than firing for any model whenever `condition.state == 'Bear'` — this is a **narrower, more correct fix than adding a new `direction` field to `RegimeCondition`** (the fix path implied by the deferred item's wording): scoping by model requires no schema/API change on either side of the stack, and is the actually-correct semantics (HMM-family conviction is an unsigned p_stay value with no Bull/Bear framing to flip). Wire the new model into `AlertRuleBuilder`'s model/state dropdowns the same way `'OMM'`/`'HMM'` already are. Fix the "Conv%" mislabeling by making the placeholder model-aware (`'Conv%'` for OMM, `'P(stay)%'` for both HMM variants, since neither HMM model's snapshot value is true directional conviction).

**Tech Stack:** FastAPI/Python backend, React/TypeScript frontend, pytest, Jest + React Testing Library.

**Practical note on the 200-bar gate:** `build_regime_snapshot()` gates both `'HMM'` and the new `'HMM_directional'` on `len(candles) >= 200`, matching the existing `'HMM'` key's threshold exactly. `compute_directional_hmm` is timeframe-agnostic (fits on whatever bars it's given), so this is functionally correct either way — but it means the practical bar this threshold represents differs a lot by rule interval: ~200 15-minute bars is a few trading days, while ~200 candles for a `"1D"`-interval rule is ~200 trading days (roughly 10 months) before `'HMM_directional'` ever populates. Not a bug, just something to flag to a user setting up a daily-interval `HMM_directional` condition and wondering why it never fires on a freshly-added symbol with limited history.

**Known, deliberately out-of-scope adjacent gap:** `frontend/lib/chartAlertEngine.ts` is a *second*, independent client-side regime-condition evaluator (used by `ChartWorkspace` to show in-browser alert history entries without waiting for the backend WS round-trip). Its `RegimeSnapshot.model` type is `'OMM' | 'HMM'` and nothing in `ChartWorkspace` ever populates a live snapshot with model `'HMM_directional'` — so a saved rule using the new model will simply never match in that client-side path (fails closed, the same behavior as when regime data is altogether missing today — not a regression). That evaluator also never had the Bear-conviction sign-flip fix from the prior session ported into it at all. Both are pre-existing gaps in a second, parallel implementation, out of scope for this plan; flag to the user separately if this matters for how alert history entries populate live in the chart before the backend confirms them.

---

## File Structure

- Modify: `backend/app/services/alert_evaluator.py` — `build_regime_snapshot()` (currently lines 132-162): add the `'HMM_directional'` branch. `_evaluate_regime_condition()` (currently lines 97-129): scope the sign-flip to `model_name == 'OMM'`.
- Modify: `frontend/types/alerts.ts` — `RegimeModel` type (line 8): add `'HMM_directional'`.
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx` — add `REGIME_STATES_HMM_DIRECTIONAL`, extend `REGIME_MODELS`/`regimeStatesFor()`, extend the model `<option>` list, make the conviction input's placeholder model-aware.
- Test: `backend/tests/test_alert_evaluator.py` — new `TestDirectionalHmmRegimeCondition` and `TestBuildRegimeSnapshotDirectionalHmm` classes; new sign-flip-scoping regression test.
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx` — new assertions for the `HMM_directional` option and the placeholder text.

---

## Task 1: Wire `compute_directional_hmm` into `build_regime_snapshot()`

**Files:**
- Modify: `backend/app/services/alert_evaluator.py:132-162`
- Test: `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alert_evaluator.py`:

```python
class TestBuildRegimeSnapshotDirectionalHmm:
    def test_hmm_directional_absent_below_minimum_bars(self):
        candles = [{'close': 100.0 + i} for i in range(50)]
        snapshot = build_regime_snapshot(candles)
        assert 'HMM_directional' not in snapshot

    def test_hmm_directional_populated_when_enough_bars(self, monkeypatch):
        import app.services.regime_hmm_daily as regime_hmm_daily
        from unittest.mock import MagicMock

        result = MagicMock(state='Bull', p_stay=0.75)
        monkeypatch.setattr(regime_hmm_daily, 'compute_directional_hmm', lambda bars: result)

        candles = [{'close': 100.0 + i * 0.1} for i in range(210)]
        snapshot = build_regime_snapshot(candles)
        assert snapshot['HMM_directional'] == {'state': 'Bull', 'conviction': 75.0}

    def test_hmm_directional_absent_when_model_returns_none(self, monkeypatch):
        """hmmlearn unavailable or fit failure → compute_directional_hmm returns None
        → key must be absent, matching the existing 'HMM' key's fail-closed behavior."""
        import app.services.regime_hmm_daily as regime_hmm_daily

        monkeypatch.setattr(regime_hmm_daily, 'compute_directional_hmm', lambda bars: None)
        candles = [{'close': 100.0 + i * 0.1} for i in range(210)]
        snapshot = build_regime_snapshot(candles)
        assert 'HMM_directional' not in snapshot
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v -k Directional`
Expected: FAIL — `KeyError: 'HMM_directional'` or assertion failures, since `build_regime_snapshot()` doesn't populate that key yet.

- [ ] **Step 3: Implement**

In `backend/app/services/alert_evaluator.py`, modify `build_regime_snapshot()` (lines 132-162):

Before:
```python
def build_regime_snapshot(candles: list[dict]) -> dict:
    """Compute {'OMM': {...}, 'HMM': {...}} regime data for regime-kind alert conditions.

    A missing key means that model's regime could not be computed (insufficient
    bars, or hmmlearn unavailable) — matching conditions for that model fail closed
    rather than raising.

    OMM conviction is always computed with a fixed Bullish framing (RegimeCondition
    has no direction field to pick a framing from); _evaluate_regime_condition()
    flips the sign for Bear-state conditions so min_conviction reads consistently
    regardless of which state the condition targets.
    """
    closes = [c["close"] for c in candles] if candles else []
    snapshot: dict = {}

    if len(closes) >= 100:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes)
        if omm is not None:
            snapshot['OMM'] = {'state': omm.state, 'conviction': omm.conviction_pct}

    if len(candles) >= 200:
        from app.services.regime_hmm import compute_intraday_hmm
        hmm = compute_intraday_hmm(candles)
        if hmm is not None:
            # HmmResult has no conviction score; p_stay (probability of remaining
            # in the detected state) is the closest available confidence metric —
            # the regime-snapshot endpoint already surfaces P(stay) for HMM users.
            snapshot['HMM'] = {'state': hmm.state, 'conviction': round(hmm.p_stay * 100, 1)}

    return snapshot
```

After:
```python
def build_regime_snapshot(candles: list[dict]) -> dict:
    """Compute {'OMM': {...}, 'HMM': {...}, 'HMM_directional': {...}} regime data for
    regime-kind alert conditions.

    A missing key means that model's regime could not be computed (insufficient
    bars, or hmmlearn unavailable) — matching conditions for that model fail closed
    rather than raising.

    OMM conviction is always computed with a fixed Bullish framing (RegimeCondition
    has no direction field to pick a framing from); _evaluate_regime_condition()
    only flips the sign for OMM Bear-state conditions, since OMM is the only model
    here whose conviction is Bullish-framed — 'HMM' and 'HMM_directional' report an
    unsigned p_stay-based conviction with no directional axis to flip.
    """
    closes = [c["close"] for c in candles] if candles else []
    snapshot: dict = {}

    if len(closes) >= 100:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes)
        if omm is not None:
            snapshot['OMM'] = {'state': omm.state, 'conviction': omm.conviction_pct}

    if len(candles) >= 200:
        from app.services.regime_hmm import compute_intraday_hmm
        hmm = compute_intraday_hmm(candles)
        if hmm is not None:
            # HmmResult has no conviction score; p_stay (probability of remaining
            # in the detected state) is the closest available confidence metric —
            # the regime-snapshot endpoint already surfaces P(stay) for HMM users.
            snapshot['HMM'] = {'state': hmm.state, 'conviction': round(hmm.p_stay * 100, 1)}

    if len(candles) >= 200:
        from app.services.regime_hmm_daily import compute_directional_hmm
        dhmm = compute_directional_hmm(candles)
        if dhmm is not None:
            # Same p_stay-as-conviction proxy as 'HMM' above — DirectionalHmmResult
            # has no separate conviction score either.
            snapshot['HMM_directional'] = {'state': dhmm.state, 'conviction': round(dhmm.p_stay * 100, 1)}

    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v`
Expected: all tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_evaluator.py backend/tests/test_alert_evaluator.py
git commit -m "feat(alerts): wire the directional Bull/Bear/Sideways HMM into build_regime_snapshot"
```

---

## Task 2: Scope the Bear-conviction sign-flip to OMM only; add HMM_directional condition handling

**Files:**
- Modify: `backend/app/services/alert_evaluator.py:97-129`
- Test: `backend/tests/test_alert_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_alert_evaluator.py`:

```python
class TestDirectionalHmmRegimeCondition:
    def test_hmm_directional_state_match(self):
        condition = RegimeCondition(kind='regime', model='HMM_directional', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM_directional': {'state': 'Bull', 'conviction': 82.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_hmm_directional_sideways_state_is_reachable(self):
        """'Sideways' was previously a dead RegimeState no model could ever produce —
        confirm HMM_directional can now actually match it."""
        condition = RegimeCondition(kind='regime', model='HMM_directional', state='Sideways')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM_directional': {'state': 'Sideways', 'conviction': 55.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_hmm_directional_bear_conviction_is_not_sign_flipped(self):
        """Unlike OMM, HMM_directional's conviction (p_stay-based) is unsigned — a
        Bear-state condition must NOT flip its sign, or a legitimately high p_stay
        would be turned negative and fail min_conviction for no reason. This is the
        bug the deferred item described as 'sign flip only covers OMM's axis' — fixed
        here by scoping the flip to the model, not by adding a new field."""
        condition = RegimeCondition(kind='regime', model='HMM_directional', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM_directional': {'state': 'Bear', 'conviction': 85.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_any_model_checks_hmm_directional_too(self):
        condition = RegimeCondition(kind='regime', model='any', state='Sideways')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM_directional': {'state': 'Sideways', 'conviction': 60.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_omm_bear_sign_flip_still_works_after_scoping_fix(self):
        """Regression guard: scoping the flip to model=='OMM' must not break the
        original OMM Bear-conviction behavior this replaces."""
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bear', 'conviction': -85}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v -k "Directional or sign_flip"`
Expected: FAIL — `test_hmm_directional_state_match` etc. fail because `_evaluate_regime_condition`'s `'any'` branch only checks `regime_by_model.get('OMM')`/`regime_by_model.get('HMM')`, never `'HMM_directional'`; `test_hmm_directional_bear_conviction_is_not_sign_flipped` fails because the current code flips sign for ANY model when `state == 'Bear'`.

- [ ] **Step 3: Implement**

In `backend/app/services/alert_evaluator.py`, replace `_evaluate_regime_condition()` (lines 97-129):

Before:
```python
def _evaluate_regime_condition(condition, regime_by_model: Optional[dict]) -> tuple[bool, dict]:
    if not regime_by_model:
        return False, {}
    if condition.model == 'any':
        # Check every available model's snapshot, not just whichever happens to be
        # present first — a rule with model='any' means "match if either model
        # reports this state," not "match against OMM if OMM data exists, HMM only
        # as an afterthought."
        candidates = [r for r in (regime_by_model.get('OMM'), regime_by_model.get('HMM')) if r]
    else:
        regime = regime_by_model.get(condition.model)
        candidates = [regime] if regime else []
    if not candidates:
        return False, {}
    for regime in candidates:
        state_match = condition.state == 'any' or regime.get('state') == condition.state
        conviction = regime.get('conviction')
        # build_regime_snapshot() computes OMM conviction with a fixed Bullish framing
        # (positive = model favors Bull persisting). For a condition targeting the Bear
        # state, flip the sign so min_conviction consistently means "how strongly does
        # the regime favor the selected state" — otherwise a strongly-Bear regime shows
        # up as strongly-negative conviction and can never clear a positive min_conviction
        # threshold. Other states (Choppy/any/HMM's Trending/Mean-reverting/...) have no
        # natural Bull/Bear opposite, so their conviction is left as computed.
        if conviction is not None and condition.state == 'Bear':
            conviction = -conviction
        conviction_match = (
            condition.min_conviction is None
            or (conviction is not None and conviction >= condition.min_conviction)
        )
        if state_match and conviction_match:
            return True, {'regime_state': 1}
    return False, {}
```

After:
```python
_REGIME_MODEL_NAMES = ('OMM', 'HMM', 'HMM_directional')


def _evaluate_regime_condition(condition, regime_by_model: Optional[dict]) -> tuple[bool, dict]:
    if not regime_by_model:
        return False, {}
    if condition.model == 'any':
        # Check every available model's snapshot, not just whichever happens to be
        # present first — a rule with model='any' means "match if either model
        # reports this state," not "match against OMM if OMM data exists, HMM only
        # as an afterthought." Model name travels with each candidate so the
        # sign-flip below can stay scoped to OMM specifically.
        candidates = [
            (name, regime_by_model.get(name)) for name in _REGIME_MODEL_NAMES if regime_by_model.get(name)
        ]
    else:
        regime = regime_by_model.get(condition.model)
        candidates = [(condition.model, regime)] if regime else []
    if not candidates:
        return False, {}
    for model_name, regime in candidates:
        state_match = condition.state == 'any' or regime.get('state') == condition.state
        conviction = regime.get('conviction')
        # OMM conviction is computed with a fixed Bullish framing (positive = model
        # favors Bull persisting). For a condition targeting the Bear state, flip the
        # sign so min_conviction consistently means "how strongly does the regime
        # favor the selected state" — otherwise a strongly-Bear regime shows up as
        # strongly-negative conviction and can never clear a positive min_conviction
        # threshold. This is scoped to OMM specifically: 'HMM' and 'HMM_directional'
        # report an unsigned p_stay-based conviction with no Bull/Bear framing to
        # flip — flipping it there would turn a legitimately high value negative and
        # make it fail min_conviction for no reason.
        if conviction is not None and model_name == 'OMM' and condition.state == 'Bear':
            conviction = -conviction
        conviction_match = (
            condition.min_conviction is None
            or (conviction is not None and conviction >= condition.min_conviction)
        )
        if state_match and conviction_match:
            return True, {'regime_state': 1}
    return False, {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_alert_evaluator.py -v`
Expected: all tests in the file PASS, including all pre-existing `TestRegimeCondition` tests (regression check) and the new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_evaluator.py backend/tests/test_alert_evaluator.py
git commit -m "fix(alerts): scope Bear-conviction sign flip to OMM; add HMM_directional model support"
```

---

## Task 3: Wire `HMM_directional` into the frontend type and `AlertRuleBuilder` dropdowns

**Files:**
- Modify: `frontend/types/alerts.ts:8`
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx:34-50,239,344-372`
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`:

```tsx
describe('AlertRuleBuilder directional HMM regime model', () => {
  it('offers HMM_directional as a model choice with Bull/Bear/Sideways states', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Regime'));

    const modelSelect = screen.getByLabelText('Regime model 2') as HTMLSelectElement;
    const modelValues = Array.from(modelSelect.options).map((o) => o.value);
    expect(modelValues).toContain('HMM_directional');

    fireEvent.change(modelSelect, { target: { value: 'HMM_directional' } });
    const stateSelect = screen.getByLabelText('Regime state 2') as HTMLSelectElement;
    const stateValues = Array.from(stateSelect.options).map((o) => o.value);
    expect(stateValues).toEqual(['any', 'Bull', 'Bear', 'Sideways']);
  });

  it('labels the conviction input P(stay)% for HMM models, Conv% for OMM', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    fireEvent.click(screen.getByText('+ Regime'));

    const modelSelect = screen.getByLabelText('Regime model 2') as HTMLSelectElement;

    // Default model is OMM.
    expect(screen.getByPlaceholderText('Conv%')).toBeInTheDocument();

    fireEvent.change(modelSelect, { target: { value: 'HMM_directional' } });
    expect(screen.getByPlaceholderText('P(stay)%')).toBeInTheDocument();

    fireEvent.change(modelSelect, { target: { value: 'HMM' } });
    expect(screen.getByPlaceholderText('P(stay)%')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: FAIL — `HMM_directional` isn't a valid option yet; `'P(stay)%'` placeholder doesn't exist (current code always renders `'Conv%'`).

- [ ] **Step 3: Implement**

In `frontend/types/alerts.ts`, change line 8:

Before:
```typescript
export type RegimeModel = 'OMM' | 'HMM' | 'any';
```

After:
```typescript
export type RegimeModel = 'OMM' | 'HMM' | 'HMM_directional' | 'any';
```

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, replace lines 34-50:

Before:
```typescript
const REGIME_STATES_OMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Choppy'];
// Must match the state labels backend/app/services/regime_hmm.py::_assign_labels
// can actually produce — offering Bull/Bear/Sideways here would let a user save a
// condition that can never fire (the HMM model never emits those labels).
const REGIME_STATES_HMM: RegimeState[] = ['any', 'Trending', 'Choppy', 'Mean-reverting'];
// When model === 'any', the backend checks the condition against BOTH the OMM and HMM
// snapshots (see backend/app/services/alert_evaluator.py::_evaluate_regime_condition),
// so the state list here must be the union of both models' real states. Derived (not
// hand-maintained) so it can't silently drift if either model's own list changes.
const REGIME_STATES_ANY: RegimeState[] = Array.from(new Set([...REGIME_STATES_OMM, ...REGIME_STATES_HMM]));
const REGIME_MODELS: RegimeModel[] = ['any', 'OMM', 'HMM'];

function regimeStatesFor(model: RegimeModel): RegimeState[] {
  if (model === 'OMM') return REGIME_STATES_OMM;
  if (model === 'HMM') return REGIME_STATES_HMM;
  return REGIME_STATES_ANY;
}
```

After:
```typescript
const REGIME_STATES_OMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Choppy'];
// Must match the state labels backend/app/services/regime_hmm.py::_assign_labels
// can actually produce — offering Bull/Bear/Sideways here would let a user save a
// condition that can never fire (the HMM model never emits those labels).
const REGIME_STATES_HMM: RegimeState[] = ['any', 'Trending', 'Choppy', 'Mean-reverting'];
// The 3 real states backend/app/services/regime_hmm_daily.py::compute_directional_hmm
// can produce (Bull/Bear/Sideways, per its label_by_state mapping) — dropdown order
// here is cosmetic (Bull-first, matching REGIME_STATES_OMM's own Bull-before-Bear
// convention above) and intentionally does NOT mirror label_by_state's internal
// Bear/Sideways/Bull ordering, which is irrelevant to a user-facing picklist.
const REGIME_STATES_HMM_DIRECTIONAL: RegimeState[] = ['any', 'Bull', 'Bear', 'Sideways'];
// When model === 'any', the backend checks the condition against every available
// model's snapshot (see backend/app/services/alert_evaluator.py::_evaluate_regime_condition),
// so the state list here must be the union of all three models' real states. Derived
// (not hand-maintained) so it can't silently drift if any model's own list changes.
const REGIME_STATES_ANY: RegimeState[] = Array.from(
  new Set([...REGIME_STATES_OMM, ...REGIME_STATES_HMM, ...REGIME_STATES_HMM_DIRECTIONAL]),
);
const REGIME_MODELS: RegimeModel[] = ['any', 'OMM', 'HMM', 'HMM_directional'];

function regimeStatesFor(model: RegimeModel): RegimeState[] {
  if (model === 'OMM') return REGIME_STATES_OMM;
  if (model === 'HMM') return REGIME_STATES_HMM;
  if (model === 'HMM_directional') return REGIME_STATES_HMM_DIRECTIONAL;
  return REGIME_STATES_ANY;
}
```

Then update the model `<option>` list (around line 345-347):

Before:
```tsx
                  >
                    {REGIME_MODELS.map((m) => (
                      <option key={m} value={m}>{m === 'any' ? 'any model' : m}</option>
                    ))}
                  </select>
```

After:
```tsx
                  >
                    {REGIME_MODELS.map((m) => (
                      <option key={m} value={m}>
                        {m === 'any' ? 'any model' : m === 'HMM_directional' ? 'HMM (directional)' : m}
                      </option>
                    ))}
                  </select>
```

Then update the conviction `<input>`'s `placeholder` (around line 359-364):

Before:
```tsx
                  <input
                    className={styles.numInput}
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Conv%"
                    value={c.min_conviction ?? ''}
```

After:
```tsx
                  <input
                    className={styles.numInput}
                    type="number"
                    min={0}
                    max={100}
                    placeholder={c.model === 'OMM' ? 'Conv%' : 'P(stay)%'}
                    value={c.min_conviction ?? ''}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: all tests in the file PASS — the file currently has 6 tests (3 in "edit mode", 2 in "duplicate mode", 1 in "regime condition state options" from the prior deferred-fixes session); this task adds 2 more (both in the new "directional HMM regime model" describe block), for 8 total. Don't hardcode this count as a gate elsewhere — it will shift again once Task 3 of the sibling `2026-07-04-alert-condition-stable-keys.md` plan adds its own tests to this same file.

- [ ] **Step 5: Run typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/types/alerts.ts frontend/components/organisms/AlertRuleBuilder/index.tsx frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx
git commit -m "feat(alerts): add HMM_directional regime model to AlertRuleBuilder; fix Conv% mislabel"
```

---

## Final verification (run once, after all three tasks)

- [ ] `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest -q` — expect all pass, no regressions.
- [ ] `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck` — expect clean.
- [ ] `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern=AlertRuleBuilder` — expect all pass.

## Self-Review Notes

- **Spec coverage:** Task 1 = deferred item 3 (wire directional HMM into `build_regime_snapshot`) and item 4 (dead `'Sideways'` becomes reachable). Task 2 = deferred item 2 (Bear-sign-flip generalization), resolved via model-scoping rather than a new `direction` field — documented above as an intentional, narrower design choice. Task 3 = the frontend half of items 2/3/4, plus item 6 (Conv%/p_stay mislabel).
- **Design deviation flagged for review:** the deferred item's wording ("RegimeCondition has no direction field") suggested adding a schema field; this plan instead scopes the existing sign-flip to `model_name == 'OMM'`, which fixes the same bug with a smaller, non-breaking change (no new field on either the Python dataclass or the TS interface, no migration, no new frontend input). Flag this trade-off explicitly during adversarial review — if the reviewer has a reason the `direction`-field approach is preferable (e.g. future models with genuinely mixed framing), reconsider before implementing.
- **No placeholders:** every step has literal before/after code and runnable commands.
- **Type/name consistency:** `'HMM_directional'` is used identically as the Python dict key, the TS type literal, the dropdown `value`, and the test fixture key throughout.
