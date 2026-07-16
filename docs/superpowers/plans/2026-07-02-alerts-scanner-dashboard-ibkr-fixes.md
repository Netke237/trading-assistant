# Alerts, Pre-Breakout Scanner, Chart Links & IBKR Reliability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two confirmed alert-CRUD bugs (Edit silently retargets symbol, Duplicate silently no-ops), make alert fired-reasons name which structures/mean-reversion strategies matched, enlarge the two alert configuration panels, show live regime conviction/P(stay) in the regime-alert dialog, add a missing "open in chart" button to the Pre-Breakout scanner, make all "open in chart" links open in a new tab consistently, and close the IBKR session keep-alive gap.

**Architecture:** All changes are localized, additive fixes to existing files — no new subsystems. Backend: refactor `composite_trigger_evaluator.py`'s private match-counting helpers into match-*naming* helpers (backward compatible), add one read-only regime-snapshot endpoint, add one APScheduler-based keep-alive job. Frontend: fix two state-derivation bugs in `AlertRuleBuilder`, CSS-only sizing bumps, one new fetch+display in `CompositeAlertDialog`, `window.open` swaps for same-tab chart links, and three new per-row chart buttons in the Pre-Breakout scanner.

**Tech Stack:** Next.js 15 / TypeScript / Zustand / CSS Modules (frontend), FastAPI / Pydantic v2 / APScheduler / pytest (backend).

---

## Investigation summary (read this before starting)

Research confirmed the following ground truth — do not re-derive it, use it:

1. **"Duplicate" alert button is wired up but is a functional no-op.** `handleDuplicate` in `frontend/app/(frame)/alerts/page.tsx:218-227` copies the rule with the *same* `symbol`, `interval`, and `group.conditions`, then calls `addRule()`. The store's `addRule` (`frontend/lib/chartAlertStore.ts:101-116`) silently rejects any rule that matches an existing rule's `symbol`+`interval`+`conditions` (returns `false`, does not sync to the backend) — and `handleDuplicate` never checks that return value. A true duplicate can **never** be added; the click appears to do nothing.
2. **"Edit" alert button is wired up but silently corrupts the rule's symbol/interval.** `AlertRuleBuilder` (`frontend/components/organisms/AlertRuleBuilder/index.tsx:58`) reads `symbol`/`interval` from `useChartStore()` (the globally active charted symbol) unconditionally — never from `editRule.symbol`/`editRule.interval`. Editing a rule for AAPL while the chart currently shows MSFT silently retargets the saved rule to MSFT.
3. **The "Set Regime Alert" dialog the user screenshotted is `CompositeAlertDialog`** (`frontend/components/organisms/CompositeAlertDialog/index.tsx`), not the generic `AlertRuleBuilder` ("New Alert" panel on the Alerts page — a separate component). `CompositeAlertDialog` **already implements** M-of-N selection for both "Structure confirmations" and "Mean Reversion strategies" (`Require X of Y` sliders, lines 191-244) and **already has** Conviction and P(stay) *threshold* sliders (lines 171-189). These are not missing — no UI work needed there.
4. **The alert fired-reason text does not name what matched.** Both firing paths build a generic reason string that ignores which structures/strategies fired:
   - `backend/app/routers/chart_alerts.py:475`: `f"Composite Markov trigger: {...} regime"`
   - `backend/app/services/strategy_watch_evaluator.py:198`: `f"{symbol}: composite Markov trigger fired"`
   The underlying evaluator (`backend/app/services/composite_trigger_evaluator.py`) already computes match counts internally (`_count_confirmations`, `_check_strategy_signals`) but discards *which* ones matched — this is the real gap behind the user's ask.
   **Caveat discovered during review:** `evaluate_from_context` (the live WebSocket firing path, used by `chart_alerts.py`) never gates on `strategy_confirmations`/`min_strategy_confirmations` at all — only `evaluate_scheduled` (the watch/scheduler path) does. Combined with the WebSocket path having no `bars_daily`/`bars_intraday` available, mean-reversion strategy names will only ever appear in reason text for watch-fired alerts, never live-chart-fired ones. Task 3 documents this with an inline comment rather than silently shipping an inconsistent fix — changing `evaluate_from_context`'s firing semantics to also gate on strategy confirmations is a separate, larger change (it would alter which alerts fire, not just their text) and is out of scope here.
5. **`CompositeAlertDialog` has no live "current regime" display** — only min-threshold sliders. There is no per-symbol regime snapshot endpoint (the existing `/regime` endpoint is SPX/NDX market-wide only). This is a genuine missing feature, not a bug.
6. **Both alert panels are genuinely undersized.** `AlertRuleBuilder`: fixed `360px` width, `10-12px` fonts. `CompositeAlertDialog`: `400px` width, `11-14px` fonts.
   **Design-system constraint (read before touching sizes):** `<Text>` primitive caps at `size=16` and `<Data>` at `size=24` (`frontend/components/primitives/Text.tsx:13`, `Data.tsx:13`) — these are closed TypeScript unions. A literal "×2" on Text-driven labels (e.g. 12→24) is **not achievable** without widening the primitive's type for the whole app, which is out of scope here. This plan doubles every *raw CSS* pixel value (panel width, `<input>`/`<select>`/`<button>` padding & font-size, gaps) and caps any Text-primitive size bump at the primitive's existing maximum (16). Flag to the user if the max-16 cap still looks too small in practice — that would require a separate, app-wide primitive change.
7. **`step-4-prebreakout` has zero chart-related code today** — no "Open in Chart" button exists on any of its 3 result tables (Pre-Breakout / Pullback / Fib). This is a missing feature, not a same-tab bug.
8. **5 confirmed same-tab chart links across the app** need to become new-tab (2 already correctly use new tabs and need no change):
   | # | File | Line | Fix |
   |---|------|------|-----|
   | 1 | `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | 262 | `router.push` → `window.open(..., '_blank')` |
   | 2 | `frontend/app/(frame)/watchlist/page.tsx` | 317 | same |
   | 3 | `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | 271 | same |
   | 4 | `frontend/components/organisms/StockPositionCard/index.tsx` | 311-316 | `<Link href>` → `<a target="_blank">` |
   | 5 | `frontend/components/organisms/ContextRail/QuickLook.tsx` | 73 | `router.push` → `window.open(..., '_blank')` |
   Already correct, no change: `frontend/app/(frame)/analysis/page.tsx:119` (`window.open(..., '_blank')`), `frontend/components/organisms/ChartTopBar/index.tsx:49` ("Pop out" button).
9. **IBKR keep-alive gap confirmed** (`backend/app/data/ibkr.py`, `backend/app/data/ibkr_paper.py`):
   - Live gateway (`ibkr.py:51-88`, `ibkr_available()`) only tickles the gateway *opportunistically* — when some other code happens to call it, capped by a 60s cache. No background heartbeat.
   - Paper gateway (`ibkr_paper.py`) has **no** auth-status check or tickle call anywhere — `place_order()` just POSTs and lets a stale-session HTTP error surface as a confusing order failure.
   - No scheduled job re-authenticates or pings IBKR (confirmed via grep across `backend/app/services/*_scheduler.py`).
   - IBKR's Client Portal Gateway requires a `/tickle` at least every ~1 min (5-min hard idle timeout) and a **daily interactive re-login** (2FA) that cannot be automated safely — this plan closes the tickle gap; the daily re-login remains a manual step and is documented as a known limitation, not faked.
10. **Discovered but out of scope (recommend a tracked follow-up, do not silently drop):** `AlertRuleBuilder`'s regime condition (`frontend/components/organisms/AlertRuleBuilder/index.tsx:34`) hardcodes 7 HMM states (`Bull, Bear, Sideways, Trending, Choppy, Mean-reverting, any`), but the actual HMM model (`backend/app/services/regime_hmm.py`) only ever produces 3 states (`Trending, Choppy, Mean-reverting`). Additionally the backend's generic regime evaluator (`backend/app/services/alert_evaluator.py:97-106`, `_evaluate_regime_condition`) never reads `condition.model` at all — the OMM/HMM dropdown in the *generic* "New Alert" panel has no effect on evaluation; whichever regime dict the caller happens to pass in is checked regardless of which model the user selected. This is a separate latent bug from everything the user asked about (it affects the generic `AlertRuleBuilder` regime condition, not `CompositeAlertDialog`, which is unaffected and correct). Not fixed in this plan because it requires a design decision (does the generic condition need per-model regime computation threaded through the WebSocket alert-evaluation context, or should the HMM option be removed from that dropdown until it's wired up?) — that's a scoping conversation, not a mechanical fix. **Action:** after this plan lands, raise this as its own follow-up plan/ticket rather than letting it sit as a comment in this document indefinitely.

---

## Task 1: Fix "Edit" alert bug — lock symbol/interval to the rule being edited

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/index.tsx:57-71`
- Test: `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`. Note: `useChartAlertStore` is a `persist()`-backed store (localStorage-synced); do not seed `rules` via `setState` expecting `AlertRuleBuilder` to read them — it never does (it only reads the `editRule`/`duplicateFrom` props). Instead, replace `updateRule`/`addRule` with `jest.fn()` spies via `useChartAlertStore.setState(...)` so the tests can assert on what actually gets saved, which is what the bug reports were about (not just what's displayed):

```tsx
import '@testing-library/jest-dom';
import { render, screen, fireEvent } from '@testing-library/react';
import AlertRuleBuilder from '@/components/organisms/AlertRuleBuilder';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import type { AlertRule } from '@/types/alerts';

const AAPL_RULE: AlertRule = {
  id: 'rule-1',
  name: 'AAPL breakout',
  symbol: 'AAPL',
  interval: '1D',
  enabled: true,
  group: { logic: 'AND', conditions: [{ kind: 'price', operator: '>', value: 100 }] },
  cooldown_minutes: 60,
  expiry_date: null,
  created_at: '2026-01-01T00:00:00.000Z',
  last_triggered_at: null,
};

beforeEach(() => {
  // Chart is currently showing MSFT, NOT the rule's own symbol (AAPL).
  useChartStore.setState({ symbol: 'MSFT', interval: '5m', activeIndicators: [] } as any);
});

describe('AlertRuleBuilder edit mode', () => {
  it('displays the rule\'s own symbol/interval, not the currently charted symbol', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={AAPL_RULE} />);
    expect(screen.getByText('Symbol: AAPL')).toBeInTheDocument();
    expect(screen.getByText('Interval: 1D')).toBeInTheDocument();
  });

  it('new-rule mode still uses the active chart symbol/interval', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} />);
    expect(screen.getByText('Symbol: MSFT')).toBeInTheDocument();
    expect(screen.getByText('Interval: 5m')).toBeInTheDocument();
  });

  it('saving an edit persists the rule\'s OWN symbol, not the active chart symbol', () => {
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={AAPL_RULE} />);
    fireEvent.click(screen.getByText('Save'));
    expect(updateRuleSpy).toHaveBeenCalledWith(
      'rule-1',
      expect.objectContaining({ symbol: 'AAPL', interval: '1D' }),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: FAIL — first and third tests show/save `symbol: 'MSFT'` instead of `'AAPL'` (current bug).

- [ ] **Step 3: Fix the component**

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, replace lines 57-71:

```tsx
export default function AlertRuleBuilder({ onClose, editRule, duplicateFrom, prefill }: Props) {
  const { symbol: chartSymbol, interval: chartInterval, activeIndicators } = useChartStore();
  const { addRule, updateRule } = useChartAlertStore();
  const seed = editRule ?? duplicateFrom ?? null;
  const symbol = seed?.symbol ?? chartSymbol;
  const interval = seed?.interval ?? chartInterval;
  const [name, setName] = useState(seed?.name ?? '');
  const [conditions, setConditions] = useState<Condition[]>(
    seed?.group.conditions
    ?? (prefill ? [{ kind: 'price', operator: 'crosses_above', value: prefill.price } as PriceCondition] : [emptyPriceCondition()]),
  );
  const [logic, setLogic] = useState<LogicOperator>(seed?.group.logic ?? 'AND');
  const [nOfMThreshold, setNOfMThreshold] = useState(seed?.group.n_of_m_threshold ?? 1);
  const [cooldown, setCooldown] = useState(seed?.cooldown_minutes ?? 60);
  const [expiryType, setExpiryType] = useState<'never' | 'custom'>(
    seed?.expiry_date ? 'custom' : 'never',
  );
  const [expiryDate, setExpiryDate] = useState(seed?.expiry_date ?? '');
  const [error, setError] = useState('');
```

Also update the `Props` interface (lines 10-14) to add `duplicateFrom` (needed by Task 2 too — add it now):

```tsx
interface Props {
  onClose: () => void;
  editRule?: AlertRule | null;
  duplicateFrom?: AlertRule | null;
  prefill?: { price: number } | null;
}
```

And update the `handleSave` rule construction (around line 101-112) — `symbol`/`interval` are now the derived consts above, not the raw hook values, so no change needed there since it already reads `symbol`/`interval` by name. Verify it still reads:

```tsx
const rule: AlertRule = {
  id: editRule?.id ?? makeId(),
  name: name.trim(),
  symbol,
  interval,
  enabled: editRule?.enabled ?? true,
  group: { logic, conditions, n_of_m_threshold: logic === 'N_OF_M' ? nOfMThreshold : undefined },
  cooldown_minutes: cooldown,
  expiry_date: expiryType === 'custom' && expiryDate ? expiryDate : null,
  created_at: editRule?.created_at ?? new Date().toISOString(),
  last_triggered_at: editRule?.last_triggered_at ?? null,
};
```

(unchanged — `symbol`/`interval` now resolve correctly because the const derivation above changed, not this block).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: PASS (all three tests in the `AlertRuleBuilder edit mode` describe block)

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no new errors (the `duplicateFrom` prop is unused until Task 2 wires it up — that's fine, it's optional and typed).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/index.tsx frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx
git commit -m "fix(alerts): lock Edit dialog to the rule's own symbol/interval instead of the active chart"
```

---

## Task 2: Fix "Duplicate" alert bug — open a pre-filled editor instead of a silent no-op re-add

**Files:**
- Modify: `frontend/app/(frame)/alerts/page.tsx:129-232, 490-495`
- Test: extend `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx`:

```tsx
describe('AlertRuleBuilder duplicate mode', () => {
  it('pre-fills from duplicateFrom but creates a new rule on save (not an update)', () => {
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} duplicateFrom={{ ...AAPL_RULE, name: 'AAPL breakout (copy)' }} />);
    expect(screen.getByText('Symbol: AAPL')).toBeInTheDocument();
    expect(screen.getByDisplayValue('AAPL breakout (copy)')).toBeInTheDocument();
    // Header must say "New Alert" (create path), not "Edit Alert" — duplicateFrom is not editRule.
    expect(screen.getByText('New Alert')).toBeInTheDocument();
  });

  it('saving a duplicate calls addRule with a NEW id, not updateRule on the original', () => {
    const addRuleSpy = jest.fn().mockReturnValue(true);
    const updateRuleSpy = jest.fn();
    useChartAlertStore.setState({ addRule: addRuleSpy, updateRule: updateRuleSpy } as any);
    render(<AlertRuleBuilder onClose={() => {}} editRule={null} duplicateFrom={{ ...AAPL_RULE, name: 'AAPL breakout (copy)' }} />);
    fireEvent.click(screen.getByText('Create Alert'));
    expect(updateRuleSpy).not.toHaveBeenCalled();
    expect(addRuleSpy).toHaveBeenCalledTimes(1);
    const savedRule = addRuleSpy.mock.calls[0][0];
    expect(savedRule.id).not.toBe('rule-1'); // must be a fresh id, not the original rule's id
    expect(savedRule.symbol).toBe('AAPL');
    expect(savedRule.name).toBe('AAPL breakout (copy)');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: FAIL — `duplicateFrom` prop doesn't exist yet as a prefill source (Task 1 added the type but this exercises actual prefill+header behavior which already works once Task 1's `seed` logic lands — if Task 1 is already committed this test should pass immediately; if not, do Task 1 first).

- [ ] **Step 3: Wire up `handleDuplicate` to open the editor instead of silently re-adding**

In `frontend/app/(frame)/alerts/page.tsx`, add a new state variable near line 133:

```tsx
const [showRuleBuilder, setShowRuleBuilder] = useState(false);
const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
const [duplicatingRule, setDuplicatingRule] = useState<AlertRule | null>(null);
```

Replace `handleCreate`, `handleDuplicate`, and `handleCloseBuilder` (lines 208-232):

```tsx
function handleCreate() {
  setEditingRule(null);
  setDuplicatingRule(null);
  setShowRuleBuilder(true);
}

function handleEdit(rule: AlertRule) {
  setEditingRule(rule);
  setDuplicatingRule(null);
  setShowRuleBuilder(true);
}

function handleDuplicate(rule: AlertRule) {
  setEditingRule(null);
  setDuplicatingRule({ ...rule, name: `${rule.name} (copy)` });
  setShowRuleBuilder(true);
}

function handleCloseBuilder() {
  setShowRuleBuilder(false);
  setEditingRule(null);
  setDuplicatingRule(null);
}
```

Update the render block (lines 490-495):

```tsx
{showRuleBuilder && (
  <AlertRuleBuilder
    onClose={handleCloseBuilder}
    editRule={editingRule}
    duplicateFrom={duplicatingRule}
  />
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=AlertRuleBuilder`
Expected: PASS

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add frontend/app/\(frame\)/alerts/page.tsx frontend/components/organisms/AlertRuleBuilder/__tests__/AlertRuleBuilder.test.tsx
git commit -m "fix(alerts): Duplicate now opens a pre-filled editor instead of silently no-op-ing"
```

**Why this is the right fix (not a cosmetic workaround):** the store's `addRule` correctly refuses to add two rules with identical `symbol`+`interval`+`conditions` — that guard is legitimate (prevents true duplicate rules). The bug was that `handleDuplicate` produced an *exact* duplicate and threw it at that guard with no way for the user to change anything first, and no error surfaced when it was silently rejected. Routing through the editor lets the user see the copy, change something (or intentionally hit the still-present "already exists" error if they save unchanged) — this preserves the guard's intent while fixing the broken UX.

---

## Task 3: Alert fired-reason names which structures/mean-reversion strategies matched

**Files:**
- Modify: `backend/app/services/composite_trigger_evaluator.py`
- Modify: `backend/app/routers/chart_alerts.py:451-499`
- Modify: `backend/app/services/strategy_watch_evaluator.py:159-200`
- Test: `backend/tests/test_composite_trigger.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_composite_trigger.py`:

```python
def test_describe_match_reports_matched_structure_names():
    from app.services.composite_trigger_evaluator import describe_match, format_composite_reason
    trigger = _make_trigger(
        min_confirmations=2,
        confirmations=[
            {"type": "structure", "signal_kind": "FVG", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "CHoCH", "direction": "Bullish", "min_confidence": 60},
        ],
    )
    structure_signals = [
        {"kind": "FVG", "direction": "bullish", "confidence": 80},
        {"kind": "BOS", "direction": "bullish", "confidence": 70},
    ]
    detail = describe_match(trigger, structure_signals=structure_signals)
    assert detail["structure_matched"] == ["FVG", "BOS"]
    assert detail["structure_total"] == 3
    reason = format_composite_reason("Choppy", detail)
    assert reason == "Composite Markov trigger: Choppy regime — 2/3 structures matched (FVG, BOS)"


def test_describe_match_reports_matched_strategy_names():
    from app.services.composite_trigger_evaluator import describe_match, format_composite_reason
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi", "mean_reversion_bb"],
        "min_strategy_confirmations": 1,
    }
    detail = describe_match(trigger, bars_daily=[], bars_intraday=[])
    assert detail["strategy_total"] == 2
    assert detail["strategy_matched"] == []  # empty bars → nothing can fire
    reason = format_composite_reason(None, detail)
    assert reason == "Composite Markov trigger: any regime"  # no matches to report yet


def test_format_composite_reason_combines_structure_and_strategy():
    from app.services.composite_trigger_evaluator import format_composite_reason
    detail = {
        "structure_matched": ["BOS"],
        "structure_total": 2,
        "strategy_matched": ["mean_reversion_vwap"],
        "strategy_total": 1,
    }
    reason = format_composite_reason("Bull", detail)
    assert reason == (
        "Composite Markov trigger: Bull regime — 1/2 structures matched (BOS) — "
        "1/1 mean-reversion strategies fired (mean_reversion_vwap)"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_composite_trigger.py -v`
Expected: FAIL with `ImportError: cannot import name 'describe_match'`

- [ ] **Step 3: Refactor the evaluator to expose match names, keeping bool-returning functions untouched**

In `backend/app/services/composite_trigger_evaluator.py`, replace `_count_confirmations` (lines 73-99) with:

```python
def _matched_confirmations(trigger_def: dict, structure_signals: list[dict], indicator_values: dict) -> list[str]:
    """Return the signal_kind of each confirmation condition that is met."""
    confirmations = trigger_def.get("confirmations", [])
    matched: list[str] = []
    for conf in confirmations:
        signal_kind = conf.get("signal_kind", "")
        direction = conf.get("direction")  # 'Bullish', 'Bearish', or None
        min_conf = conf.get("min_confidence", 60)
        conf_type = conf.get("type", "structure")

        if conf_type == "structure":
            for sig in structure_signals:
                kind_match = sig.get("kind", "") == signal_kind or sig.get("type", "") == signal_kind
                sig_dir = sig.get("direction", "")
                dir_match = direction is None or sig_dir.lower() == direction.lower()
                conf_match = sig.get("confidence", 0) >= min_conf
                if kind_match and dir_match and conf_match:
                    matched.append(signal_kind)
                    break
        elif conf_type == "momentum":
            val = indicator_values.get(signal_kind)
            if val is not None and val >= min_conf:
                matched.append(signal_kind)
    return matched


def _count_confirmations(trigger_def: dict, structure_signals: list[dict], indicator_values: dict) -> int:
    """Count how many confirmation conditions are met."""
    return len(_matched_confirmations(trigger_def, structure_signals, indicator_values))
```

Replace `_check_strategy_signals` (lines 105-142) with:

```python
def _matched_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
    direction: str = "Bullish",
) -> list[str]:
    """Return which of the given mean-reversion strategies fired within the last few bars."""
    from app.services.strategy_engine import (
        mean_reversion_rsi_signal,
        mean_reversion_bb_signal,
        mean_reversion_vwap_signal,
    )

    _FNS: dict[str, tuple] = {
        "mean_reversion_rsi":  (mean_reversion_rsi_signal,  "daily"),
        "mean_reversion_bb":   (mean_reversion_bb_signal,   "daily"),
        "mean_reversion_vwap": (mean_reversion_vwap_signal, "intraday"),
    }

    matched: list[str] = []
    for key in strategy_keys:
        entry = _FNS.get(key)
        if entry is None:
            continue
        fn, bar_type = entry
        bars = bars_intraday if bar_type == "intraday" else bars_daily
        if len(bars) < 60:
            logger.debug("_matched_strategy_signals: skipping %s — insufficient bars (%d)", key, len(bars))
            continue
        for i in range(len(bars) - _MR_STRATEGY_LOOKBACK, len(bars)):
            slice_bars = bars[max(0, i - 119): i + 1]
            try:
                if fn(slice_bars, direction=direction) is not None:
                    matched.append(key)
                    break
            except Exception:
                pass
    return matched


def _check_strategy_signals(
    strategy_keys: list[str],
    bars_daily: list[dict],
    bars_intraday: list[dict],
    direction: str = "Bullish",
) -> int:
    """Return how many of the given mean-reversion strategies fired within the last few bars."""
    return len(_matched_strategy_signals(strategy_keys, bars_daily, bars_intraday, direction))
```

Add two new public functions at the end of the file:

```python
def describe_match(
    trigger_def: dict,
    *,
    structure_signals: list[dict] | None = None,
    indicator_values: dict | None = None,
    bars_daily: list[dict] | None = None,
    bars_intraday: list[dict] | None = None,
    symbol: str = "",
    direction: str = "Bullish",
) -> dict:
    """Build a human-readable breakdown of which confirmations/strategies matched.

    Call this AFTER evaluate_from_context/evaluate_scheduled has already confirmed
    the rule fired, to build the alert notification text. Structure signals are
    recomputed from bars_daily+symbol if not passed explicitly (watch/scheduler path).
    """
    td = trigger_def if isinstance(trigger_def, dict) else trigger_def.model_dump()

    if structure_signals is None and bars_daily and td.get("confirmations"):
        try:
            from app.services.market_structure import compute_structure
            structure_signals = compute_structure(bars_daily, "1D", symbol) or []
        except Exception as exc:
            logger.warning("describe_match: structure recompute failed for %s — %s", symbol, exc)
            structure_signals = []

    structure_matched = _matched_confirmations(td, structure_signals or [], indicator_values or {})

    strategy_keys: list[str] = td.get("strategy_confirmations", [])
    strategy_matched: list[str] = []
    if strategy_keys and (bars_daily or bars_intraday):
        strategy_matched = _matched_strategy_signals(strategy_keys, bars_daily or [], bars_intraday or [], direction)

    return {
        "structure_matched": structure_matched,
        "structure_total": len(td.get("confirmations", [])),
        "strategy_matched": strategy_matched,
        "strategy_total": len(strategy_keys),
    }


def format_composite_reason(to_state: str | None, detail: dict) -> str:
    """Build the alert notification reason text from a describe_match() result."""
    parts = [f"Composite Markov trigger: {to_state or 'any'} regime"]
    if detail["structure_total"] and detail["structure_matched"]:
        names = ", ".join(detail["structure_matched"])
        parts.append(f"{len(detail['structure_matched'])}/{detail['structure_total']} structures matched ({names})")
    if detail["strategy_total"] and detail["strategy_matched"]:
        names = ", ".join(detail["strategy_matched"])
        parts.append(f"{len(detail['strategy_matched'])}/{detail['strategy_total']} mean-reversion strategies fired ({names})")
    return " — ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_composite_trigger.py -v`
Expected: PASS (all, including the pre-existing ones — `_count_confirmations`/`_check_strategy_signals` signatures are unchanged, so `evaluate_from_context`/`evaluate_scheduled` still return plain bools).

- [ ] **Step 5: Wire `describe_match`/`format_composite_reason` into the WebSocket alert path**

In `backend/app/routers/chart_alerts.py`, replace the composite-rule block (lines 451-476):

```python
        # ── Composite rule evaluation ─────────────────────────────────────────
        if composite_rows:
            from app.services.composite_trigger_evaluator import evaluate_from_context, describe_match, format_composite_reason
            from app.services.regime_omm import compute_omm
            _closes = [c["close"] for c in all_candles] if all_candles else []
            _omm = compute_omm(_closes) if len(_closes) >= 100 else None
            for _row, _rj in composite_rows:
                _td = {k: v for k, v in _rj.items() if k != "__type"}
                try:
                    _fired = evaluate_from_context(_td, _omm, signals, indicators)
                except Exception as _exc:
                    logger.warning("composite rule eval failed for %s: %s", symbol, _exc)
                    continue
                if not _fired:
                    continue
                # NOTE: evaluate_from_context (used to decide _fired above) does not gate on
                # strategy_confirmations at all — only evaluate_scheduled (the watch path) does.
                # We also have no bars_daily/bars_intraday available in this WebSocket context,
                # so describe_match() cannot evaluate mean-reversion strategies here even if we
                # wanted to describe them. This means the reason text for WebSocket-fired composite
                # alerts will only ever mention structure confirmations, never mean-reversion
                # strategies — strategy confirmations are fully supported only via the scheduled
                # watch path (strategy_watch_evaluator.py). This is a pre-existing evaluator gap,
                # not something this task fixes — flagged to the user as a known limitation.
                _detail = describe_match(_td, structure_signals=signals, indicator_values=indicators, symbol=symbol)
                _reason = format_composite_reason(_td.get('primary', {}).get('to_state'), _detail)
                _now = datetime.now().isoformat()
                _entry = {
                    "id": uuid.uuid4().hex,
                    "rule_id": _row.id,
                    "symbol": symbol,
                    "interval": interval,
                    "triggered_at": _now,
                    "candle": closed_candle,
                    "trigger_values": {
                        "composite": True,
                        "omm_state": _omm.state if _omm else None,
                        "structure_matched": _detail["structure_matched"],
                        "strategy_matched": _detail["strategy_matched"],
                    },
                    "reason": _reason,
                }
```

(the rest of the loop body — `_hist = AlertHistoryModel(...)` through the end of the `for` loop — is unchanged, keep it as-is).

- [ ] **Step 6: Wire into the scheduled watch path**

In `backend/app/services/strategy_watch_evaluator.py`, replace lines 184-200:

```python
        try:
            from app.services.composite_trigger_evaluator import evaluate_scheduled, describe_match, format_composite_reason
            fired = evaluate_scheduled(symbol, trigger_def, bars, bars_intraday)
        except Exception as exc:
            logger.warning("composite-watch: evaluate_scheduled failed for %s — %s", symbol, exc)
            continue
        if not fired:
            continue
        close = float(bars[-1]["close"])
        _detail = describe_match(
            trigger_def, bars_daily=bars, bars_intraday=bars_intraday, symbol=symbol, direction=wdir,
        )
        _reason = format_composite_reason((trigger_def.get("primary") or {}).get("to_state"), _detail)
        event = WatchEvent(
            watch_id=w["id"], symbol=symbol, strategy_key="composite",
            event_type="entry", direction=wdir,
            entry=None, stop=None, target=None, rr_ratio=None,
            close=close,
            reason=_reason,
        )
        events.append(event)
```

- [ ] **Step 7: Run the full backend alert/watch test suite**

Run: `cd backend && pytest tests/test_composite_trigger.py tests/test_alternatives.py -v`
Expected: PASS. Also run the broader suite to catch any import regressions:
Run: `cd backend && pytest -k "alert or watch or composite" -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/composite_trigger_evaluator.py backend/app/routers/chart_alerts.py backend/app/services/strategy_watch_evaluator.py backend/tests/test_composite_trigger.py
git commit -m "feat(alerts): name matched structures/mean-reversion strategies in fired-alert reason text"
```

---

## Task 4: Show live regime conviction/P(stay) in the "Set Regime Alert" dialog

**Files:**
- Create: `backend/app/routers/composite_watch.py` — add one endpoint (modify existing file)
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/organisms/CompositeAlertDialog/index.tsx`
- Modify: `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css`
- Test: `backend/tests/test_composite_watch_router.py` (new)

- [ ] **Step 1: Write the failing backend test**

Create `backend/tests/test_composite_watch_router.py`:

```python
"""Tests for the per-symbol regime snapshot endpoint used by the regime-alert dialog."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_regime_snapshot_omm_returns_state_and_conviction():
    """Mock compute_omm directly so the response shape is pinned down deterministically —
    do not rely on a synthetic bar series happening to classify a particular way."""
    fake_result = MagicMock()
    fake_result.state = "Bull"
    fake_result.p_stay = 0.7123
    fake_result.conviction_pct = 42
    fake_result.conviction_label = "Strong conviction"
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)), \
         patch("app.services.regime_omm.compute_omm", return_value=fake_result):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM", "direction": "Bullish"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "model": "OMM",
        "state": "Bull",
        "p_stay": 0.7123,
        "conviction_pct": 42,
        "conviction_label": "Strong conviction",
    }


@pytest.mark.asyncio
async def test_regime_snapshot_omm_insufficient_history_returns_422():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)), \
         patch("app.services.regime_omm.compute_omm", return_value=None):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM"},
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_regime_snapshot_unknown_model_rejected():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            "/api/composite-watches/regime-snapshot",
            params={"symbol": "AAPL", "model": "GARBAGE"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_regime_snapshot_invalid_direction_returns_400():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[{"close": 100.0}] * 300)):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "AAPL", "model": "OMM", "direction": "Sideways"},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_regime_snapshot_no_bars_returns_404():
    with patch("app.services.historical_store.get_bars", new=AsyncMock(return_value=[])):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.get(
                "/api/composite-watches/regime-snapshot",
                params={"symbol": "NOSUCHSYM", "model": "OMM"},
            )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_composite_watch_router.py -v`
Expected: FAIL with 404 (route doesn't exist) on all requests.

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/composite_watch.py`, add after the existing `get_defaults` endpoint (after line 28):

```python
@router.get("/regime-snapshot")
async def get_regime_snapshot(
    symbol: str,
    model: str = "OMM",
    direction: str = "Bullish",
    interval: str = "15m",
) -> dict:
    """Live OMM/HMM snapshot for a single symbol.

    Used by the regime-alert dialog to show the user the symbol's CURRENT
    conviction/P(stay) before they pick alert threshold sliders — the sliders
    themselves are thresholds, not live values, so without this the user is
    picking blind.
    """
    from datetime import date, timedelta
    from app.services.historical_store import get_bars
    from app.services.regime_omm import compute_omm

    if direction not in ("Bullish", "Bearish"):
        raise HTTPException(status_code=400, detail=f"direction must be 'Bullish' or 'Bearish', got {direction!r}")

    end = date.today()
    start = end - timedelta(days=400)
    bars = await get_bars(symbol, start, end)
    if not bars:
        raise HTTPException(status_code=404, detail=f"no price history for {symbol}")

    if model == "OMM":
        closes = [b["close"] for b in bars]
        result = compute_omm(closes, direction=direction)
        if result is None:
            raise HTTPException(status_code=422, detail="insufficient history to classify OMM regime")
        return {
            "model": "OMM",
            "state": result.state,
            "p_stay": result.p_stay,
            "conviction_pct": result.conviction_pct,
            "conviction_label": result.conviction_label,
        }

    if model in ("HMM_daily", "HMM_intraday"):
        from app.services.regime_hmm import compute_intraday_hmm
        if model == "HMM_intraday":
            from app.data.market import fetch_intraday_candles
            hmm_bars = fetch_intraday_candles(symbol, interval=interval, days=55)
        else:
            hmm_bars = bars
        result_hmm = compute_intraday_hmm(hmm_bars)
        if result_hmm is None:
            raise HTTPException(status_code=422, detail="insufficient history to classify HMM regime")
        return {
            "model": model,
            "state": result_hmm.state,
            "p_stay": result_hmm.p_stay,
            "p_transition": result_hmm.p_transition,
        }

    raise HTTPException(status_code=400, detail=f"unknown model {model!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_composite_watch_router.py -v`
Expected: PASS

- [ ] **Step 5: Add the frontend API call**

In `frontend/lib/api.ts`, add near `getCompositeWatchDefaults` (after line 499):

```ts
  getSymbolRegimeSnapshot: (symbol: string, model: string, direction: string = 'Bullish', interval: string = '15m') =>
    get<SymbolRegimeSnapshot>(
      `/api/composite-watches/regime-snapshot?symbol=${encodeURIComponent(symbol)}&model=${model}&direction=${direction}&interval=${interval}`,
    ),
```

Add the type near the other Composite watch types in the same file (find `CompositeWatchDefaults` and add alongside it):

```ts
export interface SymbolRegimeSnapshot {
  model: string;
  state: string;
  p_stay: number;
  conviction_pct?: number;
  conviction_label?: string;
  p_transition?: { to: string; prob: number }[];
}
```

- [ ] **Step 6: Display the snapshot in the dialog**

In `frontend/components/organisms/CompositeAlertDialog/index.tsx`, add state + effect after the existing `useEffect` (after line 54):

```tsx
  const [snapshot, setSnapshot] = useState<import('@/lib/api').SymbolRegimeSnapshot | null>(null);
  const [snapshotError, setSnapshotError] = useState(false);

  useEffect(() => {
    if (model === 'any') { setSnapshot(null); return; }
    let cancelled = false;
    setSnapshotError(false);
    setSnapshot(null);
    api.getSymbolRegimeSnapshot(symbol, model, direction, interval).then((s) => {
      if (!cancelled) setSnapshot(s);
    }).catch(() => {
      if (!cancelled) setSnapshotError(true);
    });
    return () => { cancelled = true; };
  }, [symbol, model, direction, interval]);
```

Insert a display block right after the "Target state" row (after line 169, before the Conviction slider row):

```tsx
            {model !== 'any' && (
              <div className={styles.snapshotBox}>
                {snapshot ? (
                  <Text size={11} tone="dim">
                    Currently: {snapshot.state}
                    {snapshot.conviction_pct !== undefined
                      ? ` · Conviction ${snapshot.conviction_pct}% (${snapshot.conviction_label})`
                      : ''}
                    {' '}· P(stay) {snapshot.p_stay.toFixed(2)}
                  </Text>
                ) : snapshotError ? (
                  <Text size={11} tone="dim">Live regime unavailable for {symbol}</Text>
                ) : (
                  <Text size={11} tone="dim">Loading current regime…</Text>
                )}
              </div>
            )}
```

- [ ] **Step 7: Add the CSS class**

In `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css`, add:

```css
.snapshotBox { padding: 6px 8px; background: var(--bg-surface-2); border-radius: 6px; }
```

- [ ] **Step 8: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/composite_watch.py backend/tests/test_composite_watch_router.py frontend/lib/api.ts frontend/components/organisms/CompositeAlertDialog/index.tsx frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css
git commit -m "feat(alerts): show live conviction/P(stay) snapshot in the regime-alert dialog"
```

---

## Task 5: Enlarge the two alert configuration panels

**Files:**
- Modify: `frontend/components/organisms/AlertRuleBuilder/AlertRuleBuilder.module.css`
- Modify: `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css`

No test needed — this is a pure CSS sizing change; verify visually per Step 3.

- [ ] **Step 1: Double `AlertRuleBuilder`'s raw CSS sizes**

In `frontend/components/organisms/AlertRuleBuilder/AlertRuleBuilder.module.css`, **replace the entire file contents** with the block below (every selector in the current file is represented — this is a full-file replacement, not a partial patch):

```css
.panel {
  position: absolute;
  top: 36px;
  right: 0;
  width: 720px;
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
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-subtle);
}

.close {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 32px;
  cursor: pointer;
  padding: 0 8px;
}
.close:hover { color: var(--text-primary); }

.body {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  flex: 1;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.input {
  padding: 8px 16px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 16px;
}

.select {
  padding: 6px 12px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 16px;
}

.numInput {
  width: 140px;
  padding: 6px 12px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 16px;
}

.meta {
  display: flex;
  gap: 32px;
  padding: 8px 0;
}

.logicToggle {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logicBtns {
  display: flex;
  gap: 4px;
}

.logicBtn {
  padding: 4px 16px;
  font-size: 16px;
  font-weight: 600;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
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
  gap: 12px;
}

.conditionRow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-surface-2);
  border-radius: 8px;
}

.removeBtn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 24px;
  cursor: pointer;
  padding: 0 8px;
  flex-shrink: 0;
}
.removeBtn:hover { color: var(--reject); }

.addRow {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.addBtn {
  padding: 8px 16px;
  font-size: 16px;
  background: transparent;
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}
.addBtn:hover { color: var(--text-primary); border-color: var(--border-strong); }

.footer {
  display: flex;
  justify-content: flex-end;
  gap: 16px;
  padding: 20px 24px;
  border-top: 1px solid var(--border-subtle);
}

.cancelBtn {
  padding: 8px 24px;
  font-size: 16px;
  background: transparent;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
}
.cancelBtn:hover { color: var(--text-primary); }

.saveBtn {
  padding: 8px 28px;
  font-size: 16px;
  font-weight: 500;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--accent-text);
  cursor: pointer;
}
.saveBtn:hover { background: var(--accent-hover); }

.nOfMRow {
  display: flex;
  align-items: center;
  gap: 12px;
}
```

(This doubles every raw CSS px value — width, padding, gaps, border-radius, raw `font-size` on plain `<input>`/`<select>`/`<button>` elements. The header title and field labels use the `<Text>` primitive, capped at `size=16` per the design-system constraint noted in the Investigation Summary — bump those inline in the component in Step 2.)

- [ ] **Step 2: Bump Text-primitive sizes to their max (16) in the component**

In `frontend/components/organisms/AlertRuleBuilder/index.tsx`, change every `<Text size={11}` and `<Text size={13}` to `<Text size={16}` (there is no `size=12`/`14` used in this file — verify with grep before editing: `grep -n "Text size=" frontend/components/organisms/AlertRuleBuilder/index.tsx`). Do not change `tone`/`weight` props, only `size`.

- [ ] **Step 2b: Fix the N-of-M threshold input's hardcoded inline width**

The `.numInput` CSS class doubling in Step 1 will NOT affect the N-of-M threshold input, because it has a hardcoded inline `style={{ width: 40 }}` in the JSX that overrides the CSS class (inline styles win). Find it around line 188-196 of `frontend/components/organisms/AlertRuleBuilder/index.tsx`:

```tsx
              <input
                className={styles.numInput}
                type="number"
                min={1}
                max={conditions.length}
                value={nOfMThreshold}
                onChange={(e) => setNOfMThreshold(Math.max(1, Math.min(conditions.length, Number(e.target.value))))}
                style={{ width: 40 }}
              />
```

Change `style={{ width: 40 }}` to `style={{ width: 80 }}` so this field doubles in step with everything else instead of staying small.

- [ ] **Step 3: Verify visually**

Start the dev server and open the Alerts page, click "Create Alert" (or Edit an existing rule):

Run: `cd frontend && npm run dev` (or use the already-running dev server)

Navigate to `/alerts`, click "Create Alert", confirm the panel is visibly larger and legible. Check it doesn't overflow the viewport at 1200px width (the project's min-width gate) — the panel is `position: absolute; right: 0`, so at 1200px viewport a 720px panel leaves 480px for the rest of the page, which is acceptable but verify nothing is clipped.

- [ ] **Step 4: Repeat for `CompositeAlertDialog`**

In `frontend/components/organisms/CompositeAlertDialog/CompositeAlertDialog.module.css`, **replace the entire file contents** with the block below (full-file replacement, same as Step 1):

```css
.overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.dialog {
  background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: 20px; padding: 40px; width: 800px; max-width: 95vw;
  display: flex; flex-direction: column; gap: 28px; max-height: 85vh; overflow-y: auto;
}
.header { display: flex; justify-content: space-between; align-items: center; }
.closeBtn { background: none; border: none; cursor: pointer; font-size: 28px; color: var(--text-dim); padding: 4px 12px; }
.row { display: flex; flex-direction: column; gap: 8px; }
.select {
  padding: 10px 16px; border: 1px solid var(--border-subtle); border-radius: 12px;
  background: var(--bg-surface-2); color: var(--text-primary); font-size: 16px;
}
.range { width: 100%; accent-color: var(--accent); }
.section { display: flex; flex-direction: column; gap: 16px; }
.confirmList { display: flex; flex-direction: column; gap: 8px; }
.confirmItem {
  display: flex; align-items: center; gap: 16px; padding: 12px 16px;
  border: 1px solid var(--border-subtle); border-radius: 12px; cursor: pointer;
}
.confirmItemSelected { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-surface)); }
.actions { display: flex; gap: 16px; justify-content: flex-end; padding-top: 8px; }
.cancelBtn {
  padding: 14px 28px; border: 1px solid var(--border-subtle); border-radius: 12px;
  background: transparent; cursor: pointer; font-size: 16px; color: var(--text-secondary);
}
.saveBtn {
  padding: 14px 28px; border: 1px solid var(--accent); border-radius: 12px;
  background: var(--accent); color: var(--accent-fg); cursor: pointer; font-size: 16px;
}
.saveBtn:disabled { opacity: 0.5; cursor: not-allowed; }
.doneMsg { padding: 32px; text-align: center; }
.snapshotBox { padding: 12px 16px; background: var(--bg-surface-2); border-radius: 12px; }
```

Then in `frontend/components/organisms/CompositeAlertDialog/index.tsx`, bump every `<Text size={12}`, `<Text size={14}` to `size={16}` (grep first: `grep -n "Text size=" frontend/components/organisms/CompositeAlertDialog/index.tsx`).

- [ ] **Step 5: Verify visually**

Open the Pre-Breakout scanner, click "Set Alert" on any row, confirm the dialog is visibly larger and legible, and still fits within `max-width: 95vw` on a 1200px viewport.

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add frontend/components/organisms/AlertRuleBuilder/ frontend/components/organisms/CompositeAlertDialog/
git commit -m "style(alerts): enlarge both alert configuration panels for readability"
```

---

## Task 6: Add "Open in Chart" button to the Pre-Breakout scanner (new tab)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.module.css`

No test needed — this mirrors an existing, unexercised UI pattern (per-row icon button) used elsewhere in the app without dedicated tests (`step-4-ranking`, `watchlist`). Verify visually per Step 4.

- [ ] **Step 1: Widen the icon column and add button/cell CSS**

In `frontend/app/(frame)/screener/step-4-prebreakout/page.module.css`, find the two column-grid rules and widen the first (icon) column from `24px` to `52px`:

```css
.tableHeader, .tableRow {
  /* ...existing declarations... */
  grid-template-columns: 52px 80px 32px 80px 80px 72px 90px 80px;
}
```

```css
.fibTableHeader,
.fibTableRow {
  /* ...existing declarations... */
  grid-template-columns: 52px 80px 32px 80px 72px 72px 72px 32px;
}
```

Add new classes (anywhere in the file):

```css
.iconCell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chartBtn {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
  line-height: 1;
}
.chartBtn:hover { opacity: 0.7; }
```

- [ ] **Step 2: Add the button to all three result tables**

In `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`, wrap `<WatchStar symbol={row.symbol} size="sm" />` with the new chart button in all three `.map()` blocks. There are three occurrences — pullback table (around line 326), fib table (around line 406), and the main prebreakout table (around line 490).

Pullback table (replace line 326):

```tsx
                  <div className={styles.iconCell}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={() => window.open(`/chart?symbol=${row.symbol}`, '_blank')}
                    >
                      📈
                    </button>
                  </div>
```

Fib table (replace line 406):

```tsx
                  <div className={styles.iconCell}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={() => window.open(`/chart?symbol=${row.symbol}`, '_blank')}
                    >
                      📈
                    </button>
                  </div>
```

Main prebreakout table (replace line 490):

```tsx
                  <div className={styles.iconCell}>
                    <WatchStar symbol={row.symbol} size="sm" />
                    <button
                      type="button"
                      className={styles.chartBtn}
                      title="Open in Chart"
                      onClick={() => window.open(`/chart?symbol=${row.symbol}`, '_blank')}
                    >
                      📈
                    </button>
                  </div>
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 4: Verify visually**

Run the dev server, navigate to the Pre-Breakout scanner (`/screener/step-4-prebreakout` in Stocks mode), run a scan (or use whatever produces results in your environment), confirm the 📈 button appears next to the star on each row in all three modes (Pre-Breakout / Pullback / Fib tabs) and opens `/chart?symbol=...` in a **new browser tab**, leaving the scanner tab untouched.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-prebreakout/page.tsx" "frontend/app/(frame)/screener/step-4-prebreakout/page.module.css"
git commit -m "feat(scanner): add per-row Open in Chart button to Pre-Breakout scanner (opens in new tab)"
```

---

## Task 7: Make all remaining "open in chart" links open in a new tab

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-ranking/page.tsx:259-266`
- Modify: `frontend/app/(frame)/watchlist/page.tsx:313-320`
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx:268-274`
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx:311-316`
- Modify: `frontend/components/organisms/ContextRail/QuickLook.tsx:68-75`

No test needed — mechanical navigation-target swap; verify visually per Step 6. **Do not touch** `frontend/app/(frame)/analysis/page.tsx:119` or `frontend/components/organisms/ChartTopBar/index.tsx:49` — both already correctly open in a new tab.

- [ ] **Step 1: `step-4-ranking/page.tsx`**

Replace line 262:

```tsx
                    onClick={(e) => { e.stopPropagation(); window.open(`/chart?symbol=${row.symbol}`, '_blank'); }}
```

- [ ] **Step 2: `watchlist/page.tsx`**

Replace line 317:

```tsx
                      onClick={(e) => { e.stopPropagation(); window.open(`/chart?symbol=${row.symbol}`, '_blank'); }}
```

- [ ] **Step 3: `step-6-contracts/page.tsx`**

Replace line 271:

```tsx
                    onClick={(e) => { e.stopPropagation(); window.open(`/chart?symbol=${candidate.symbol}`, '_blank'); }}
```

- [ ] **Step 4: `StockPositionCard/index.tsx`**

Replace lines 311-316 (the `<Link>` component) with a plain anchor that opens a new tab:

```tsx
        <a
          href={`/chart?symbol=${encodeURIComponent(card.symbol)}`}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.actionBtn}
        >
          <Text size={12}>View Chart</Text>
        </a>
```

Run `grep -n "Link" frontend/components/organisms/StockPositionCard/index.tsx` and inspect every match before deciding whether to remove the import — do not assume based on this plan. If the only remaining matches are the `import Link from 'next/link';` line itself and no other JSX uses `<Link>`, remove that import line. If any other `<Link>` usage remains in the file, leave the import in place.

- [ ] **Step 5: `ContextRail/QuickLook.tsx`**

Replace line 73:

```tsx
              onClick={() => window.open(`/chart?symbol=${r.symbol}`, '_blank')}
```

Check whether `router` (from `useRouter()`) is still used elsewhere in this file after this change (`grep -n "router\." frontend/components/organisms/ContextRail/QuickLook.tsx`) — if this was its only usage, remove the now-unused `useRouter()` call and its import.

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no unused-import errors from Steps 4/5 cleanup)

- [ ] **Step 7: Verify visually**

For each of the 5 spots, click the chart link/button and confirm a **new tab** opens with the correct symbol, and the original page stays where it was:
- Options-mode Step 4 ranking table → 📈 button
- Watchlist → Stocks tab → 📈 button
- Options-mode Step 6 contracts → 📈 button on a contract group header
- Any Stocks-mode Position Card → "View Chart" button
- ContextRail "Watchlist · Top 5" panel (visible on Dashboard/most pages) → click any symbol row

- [ ] **Step 8: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-ranking/page.tsx" "frontend/app/(frame)/watchlist/page.tsx" "frontend/app/(frame)/screener/step-6-contracts/page.tsx" frontend/components/organisms/StockPositionCard/index.tsx frontend/components/organisms/ContextRail/QuickLook.tsx
git commit -m "fix(nav): open all remaining chart links in a new tab for consistency"
```

---

## Task 8: IBKR session keep-alive — live + paper

**Files:**
- Create: `backend/app/services/ibkr_keepalive_scheduler.py`
- Modify: `backend/app/data/ibkr_paper.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_ibkr_paper.py` (existing `respx` mocks need the new auth pre-check added — see Step 4b)
- Test: `backend/tests/test_ibkr_keepalive_scheduler.py` (new)

- [ ] **Step 1: Write the failing test for the paper-gateway availability check**

Create `backend/tests/test_ibkr_keepalive_scheduler.py`:

```python
"""Tests for IBKR keep-alive: paper-gateway auth check and the scheduler wrapper."""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def test_paper_gateway_available_true_on_authenticated():
    from app.data import ibkr_paper

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"authenticated": True}

    with patch("httpx.get", return_value=mock_resp) as mock_get, \
         patch("httpx.post") as mock_post:
        ibkr_paper._auth_cache = None  # reset module cache between tests
        result = ibkr_paper.paper_gateway_available()

    assert result is True
    mock_get.assert_called_once()
    mock_post.assert_called_once()  # tickle fired on success


def test_paper_gateway_available_false_on_connection_error():
    from app.data import ibkr_paper

    with patch("httpx.get", side_effect=Exception("connection refused")):
        ibkr_paper._auth_cache = None
        result = ibkr_paper.paper_gateway_available()

    assert result is False


def test_keepalive_scheduler_start_and_shutdown_are_idempotent():
    from app.services import ibkr_keepalive_scheduler as sched

    sched.start()
    sched.start()  # must not raise or double-register the job
    assert sched._get().running is True
    sched.shutdown()
    sched.shutdown()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ibkr_keepalive_scheduler.py -v`
Expected: FAIL — `ibkr_paper.paper_gateway_available` and `ibkr_keepalive_scheduler` don't exist yet.

- [ ] **Step 3: Add `paper_gateway_available()` to `ibkr_paper.py`**

In `backend/app/data/ibkr_paper.py`, add after the imports (after line 12):

```python
import time
import threading

_PAPER_BASE = "https://localhost:7499/v1/api"
_PAPER_TIMEOUT = 8
_auth_cache: dict | None = None
_AUTH_TTL = 60.0
_auth_lock = threading.Lock()


def paper_gateway_available() -> bool:
    """Return True if the IBKR paper gateway is running and authenticated.

    Mirrors app.data.ibkr.ibkr_available() — separate cache because the paper
    and live gateways run as independent processes on different ports.
    Result is cached for 60 seconds. On success, also fires a POST /tickle
    keep-alive (fire-and-forget, errors ignored).
    """
    global _auth_cache
    now = time.monotonic()
    with _auth_lock:
        if _auth_cache is not None and now < _auth_cache["expires"]:
            return _auth_cache["result"]

    try:
        resp = httpx.get(f"{_PAPER_BASE}/iserver/auth/status", verify=False, timeout=_PAPER_TIMEOUT)
        resp.raise_for_status()
        authenticated = bool(resp.json().get("authenticated", False))
    except Exception as exc:
        logger.debug("IBKR paper auth check failed: %s", exc)
        with _auth_lock:
            _auth_cache = {"result": False, "expires": now + _AUTH_TTL}
        return False

    with _auth_lock:
        _auth_cache = {"result": authenticated, "expires": now + _AUTH_TTL}

    if authenticated:
        try:
            httpx.post(f"{_PAPER_BASE}/tickle", verify=False, timeout=_PAPER_TIMEOUT)
        except Exception:
            pass

    return authenticated
```

- [ ] **Step 4: Guard `place_order` with an explicit session check**

In `backend/app/data/ibkr_paper.py`, modify `place_order` (currently lines 69-88) to check the session first, so a stale session fails with a clear message instead of a confusing raw HTTP error:

```python
    def place_order(self, order: BrokerOrder) -> OrderResult:
        if not paper_gateway_available():
            raise RuntimeError(
                "IBKR paper order failed: gateway session is not authenticated. "
                "Re-login to the IBKR paper Client Portal Gateway and retry."
            )
        url = f"{self._base}/iserver/account/{self._account}/orders"
        payload = self._build_payload(order)
        try:
            resp = httpx.post(url, json=payload, verify=False, timeout=self._timeout)
        except Exception as exc:
            raise RuntimeError(f"IBKR paper order failed: connection error — {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"IBKR paper order failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        data = resp.json()
        if isinstance(data, list):
            data = data[0]
        return OrderResult(
            order_id=str(data.get("order_id", "")),
            status=str(data.get("order_status", "Unknown")),
            broker="ibkr_paper",
            message=str(data.get("message", "")),
        )
```

- [ ] **Step 4b: Update the existing `test_ibkr_paper.py` — the new guard WILL break it as-is**

`backend/tests/test_ibkr_paper.py` already has two `@respx.mock`-decorated tests (`test_adapter_place_order_success`, `test_adapter_place_order_failure_raises`) that only register a mock for the orders POST endpoint. `respx.mock` raises on any unmocked request by default. Since Step 4's guard now calls `paper_gateway_available()` — which hits `GET /iserver/auth/status` and, on success, `POST /tickle` — BEFORE the orders POST, both existing tests will fail with a respx "not mocked" error unless those two endpoints are also mocked. Read the current file (`backend/tests/test_ibkr_paper.py`) and update both tests:

```python
@respx.mock
def test_adapter_place_order_success():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True})
    )
    respx.post("https://localhost:7499/v1/api/tickle").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.post("https://localhost:7499/v1/api/iserver/account/DU123456/orders").mock(
        return_value=httpx.Response(200, json=[{"order_id": "987654", "order_status": "PreSubmitted"}])
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None  # avoid cross-test cache leakage
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = adapter.place_order(order)
    assert result.order_id == "987654"
    assert result.status == "PreSubmitted"
    assert result.broker == "ibkr_paper"


@respx.mock
def test_adapter_place_order_failure_raises():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": True})
    )
    respx.post("https://localhost:7499/v1/api/tickle").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.post("https://localhost:7499/v1/api/iserver/account/DU123456/orders").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="IBKR paper order failed"):
        adapter.place_order(order)
```

Also add a new test for the guard itself:

```python
@respx.mock
def test_adapter_place_order_raises_when_not_authenticated():
    respx.get("https://localhost:7499/v1/api/iserver/auth/status").mock(
        return_value=httpx.Response(200, json={"authenticated": False})
    )
    from app.data import ibkr_paper
    ibkr_paper._auth_cache = None
    adapter = _adapter()
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="gateway session is not authenticated"):
        adapter.place_order(order)
```

Run: `cd backend && pytest tests/test_ibkr_paper.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Run test to verify Steps 3-4 pass**

Run: `cd backend && pytest tests/test_ibkr_keepalive_scheduler.py::test_paper_gateway_available_true_on_authenticated tests/test_ibkr_keepalive_scheduler.py::test_paper_gateway_available_false_on_connection_error -v`
Expected: PASS

- [ ] **Step 6: Create the keep-alive scheduler**

Create `backend/app/services/ibkr_keepalive_scheduler.py`:

```python
"""APScheduler wrapper for periodic IBKR Client Portal Gateway keep-alive.

The IBKR Client Portal Gateway drops the session after ~5 minutes without a
/tickle call, independently of how often the app happens to fetch market data
or place orders. This ticks both the live and paper gateways every 45 seconds
so a dropped connection is caught within one interval instead of silently
going stale until the next scan or order attempt fails.

Known limitation (not automated here): IBKR also requires a fresh interactive
brokerage-session login (2FA) roughly once every 24h. That cannot be
automated without storing 2FA credentials, which this app does not do —
if the gateway shows "not authenticated" in logs, a manual re-login to the
Client Portal Gateway is required.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_JOB_ID = "ibkr_keepalive"
_INTERVAL_SECONDS = 45
_scheduler: AsyncIOScheduler | None = None


def _get() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def _tick() -> None:
    from app.data.ibkr import ibkr_available
    from app.data.ibkr_paper import paper_gateway_available

    if not ibkr_available():
        logger.warning("ibkr_keepalive: live gateway not authenticated")
    if not paper_gateway_available():
        logger.warning("ibkr_keepalive: paper gateway not authenticated")


def start() -> None:
    sched = _get()
    if not sched.running:
        sched.add_job(
            _tick,
            IntervalTrigger(seconds=_INTERVAL_SECONDS),
            id=_JOB_ID,
            replace_existing=True,
        )
        sched.start()
        logger.info("ibkr_keepalive_scheduler: started, interval=%ds", _INTERVAL_SECONDS)


def shutdown() -> None:
    global _scheduler
    sched = _get()
    if sched.running:
        sched.shutdown(wait=False)
    # APScheduler's AsyncIOScheduler cannot be restarted after shutdown() — drop the
    # cached instance so a later start() builds a fresh scheduler instead of trying
    # (and failing) to restart a shut-down one.
    _scheduler = None
```

- [ ] **Step 7: Extend the idempotency test to cover restart-after-shutdown**

`AsyncIOScheduler` instances generally cannot be restarted once shut down — add this to `test_ibkr_keepalive_scheduler.py` (after the existing `test_keepalive_scheduler_start_and_shutdown_are_idempotent` test) to lock in that `shutdown()` resets the cached instance so a subsequent `start()` works:

```python
def test_keepalive_scheduler_can_restart_after_shutdown():
    from app.services import ibkr_keepalive_scheduler as sched

    sched.start()
    sched.shutdown()
    sched.start()  # must build a fresh scheduler instance, not restart the shut-down one
    assert sched._get().running is True
    sched.shutdown()
```

- [ ] **Step 8: Run the full test file**

Run: `cd backend && pytest tests/test_ibkr_keepalive_scheduler.py -v`
Expected: PASS (all 4 tests: 2 `paper_gateway_available` tests from Step 1, the idempotency test from Step 1, and the restart test from Step 7)

- [ ] **Step 9: Wire the scheduler into app startup/shutdown**

In `backend/app/main.py`, add a new startup block after the "Strategy-watch scheduler" block (after line 166, before `yield`):

```python
    # ── IBKR keep-alive scheduler ──────────────────────────────────────────
    try:
        from app.services import ibkr_keepalive_scheduler as _ibkr_sched
        _ibkr_sched.start()
    except Exception as _exc:
        logger.warning("ibkr_keepalive_scheduler startup failed: %s", _exc)
```

Add a matching shutdown block after the "Strategy-watch scheduler" shutdown block (after line 193, before `if _scheduler._running:`):

```python
    try:
        from app.services import ibkr_keepalive_scheduler as _ibkr_sched
        _ibkr_sched.shutdown()
    except Exception:
        pass
```

- [ ] **Step 10: Run the backend test suite to confirm no regressions**

Run: `cd backend && pytest -v`
Expected: PASS (all tests, including the ones added in Tasks 3 and 4)

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/ibkr_keepalive_scheduler.py backend/app/data/ibkr_paper.py backend/app/main.py backend/tests/test_ibkr_keepalive_scheduler.py backend/tests/test_ibkr_paper.py
git commit -m "feat(ibkr): add periodic session keep-alive for live + paper gateways, guard paper orders on stale session"
```

---

## Self-review notes (already applied above)

- **Spec coverage:** structure/mean-reversion M-of-N UI (already existed, no task needed), regime confidence display (Task 4), alert reason text (Task 3), panel sizing (Task 5), Edit/Duplicate bugs (Tasks 1-2), Pre-Breakout chart button (Task 6), sitewide chart-link consistency (Task 7), IBKR keep-alive (Task 8). Dashboard Risk tab explanation and OMM/HMM state-naming question answered directly in chat (no code gap found). Every explicit ask is covered by a task or an explicit "already exists / working as intended" note in the Investigation Summary.
- **No placeholders:** every step above has literal code, exact file paths, and runnable commands — verified during authoring.
- **Type consistency:** `AlertRuleBuilder`'s `Props.duplicateFrom` (Task 1) is used consistently in Task 2's `alerts/page.tsx` wiring. `describe_match()`'s returned dict shape (`structure_matched`, `structure_total`, `strategy_matched`, `strategy_total`) is identical across Task 3's definition and its two call sites, and matches `format_composite_reason`'s expected input.

## Adversarial review — round 1 (applied)

An independent adversarial pass against the live codebase (not just the plan text) found and this document now incorporates fixes for:
1. Task 8's new `place_order()` guard would have broken the two existing `respx`-mocked tests in `backend/tests/test_ibkr_paper.py` — Step 4b now updates those tests and adds a third for the guard itself.
2. `evaluate_from_context` (WebSocket firing path) never gates on `strategy_confirmations` — documented inline (Task 3, Step 5) and in Investigation point 4 as a pre-existing, out-of-scope evaluator gap rather than silently shipping an inconsistent-looking fix.
3. Tasks 1-2's tests now click Save/Create Alert and assert on mocked `updateRule`/`addRule` call arguments, not just what's displayed.
4. Task 4's OMM snapshot test now mocks `compute_omm` directly for a deterministic assertion instead of accepting two possible status codes.
5. Task 5 now explicitly fixes the N-of-M threshold input's hardcoded inline `style={{ width: 40 }}`, which the CSS-only doubling couldn't reach.
6. Task 1's test no longer seeds `useChartAlertStore.rules` (dead setup — the component never reads it).
7. `ibkr_keepalive_scheduler.shutdown()` now resets its cached scheduler instance so a later `start()` doesn't try to restart an already-shut-down `AsyncIOScheduler`; a restart-after-shutdown test was added.
8. The generic `AlertRuleBuilder`/`alert_evaluator.py` regime-model bug (Investigation point 10) is now explicitly flagged as needing a tracked follow-up, not left as a passive comment.
9. Task 7's `next/link` import-removal step now requires an actual grep check before removing anything, instead of an unverified assumption.
10. Task 5's CSS blocks are now explicitly labeled as full-file replacements.
11. Task 4's endpoint now validates `direction` and returns 400 for invalid values instead of leaking an uncaught `ValueError` as a 500.

## Adversarial review — round 2 (applied)

A second pass re-verifying round 1's fixes against the live document found and fixed:
12. Task 8's steps were out of order — "Step 7: Run the full test file (expects 4 tests)" appeared *before* "Step 6b" (where the 4th test actually gets written), so an implementer following the document top-to-bottom would run the assertion before the test existed. Renumbered Steps 5-11 sequentially with the restart-after-shutdown test now at Step 7, before the "run the full file" step (now Step 8).
13. Task 1's setup prose said tests would mock the store "with `jest.spyOn`," but the actual test code replaces `updateRule`/`addRule` with `jest.fn()` via `useChartAlertStore.setState(...)` — wording corrected to match the code.
14. Task 1 Step 4 still said "Expected: PASS (both tests)" after a third test was added during round 1's fixes — corrected to reference all three tests.

Round 3 spot-check (numbering, PASS/FAIL claim counts, cross-references) found no further issues — clear.
