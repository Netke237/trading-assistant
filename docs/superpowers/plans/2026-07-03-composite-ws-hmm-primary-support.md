# Composite WS-Path HMM Primary Model Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make composite-watch alert rules whose `primary.model` is `"HMM_intraday"` or `"HMM_daily"` actually evaluate over the WebSocket (live candle-close) path instead of always failing closed with a warning — closing the gap flagged in the 2026-07-03 alert-evaluator-parity-fixes session as deliberately deferred.

**Architecture:** `composite_trigger_evaluator.py::evaluate_from_context()` (the WS path) currently only knows how to check `model == "OMM"`; for `"HMM_intraday"`/`"HMM_daily"` it unconditionally returns `False`. Its sibling, `evaluate_scheduled()` (the scheduled-watch path), already computes these correctly from raw bars via `regime_hmm.py::compute_intraday_hmm()` and `_check_primary_hmm()`. This plan ports that exact logic into `evaluate_from_context()`, and updates its sole caller — `chart_alerts.py::evaluate_and_notify_for_symbol()` — to supply `bars_daily` whenever a composite rule actually needs it (either for `strategy_confirmations`, as today, or now also for a `HMM_daily` primary condition), reusing `all_candles` directly when the rule's own interval is already daily/weekly instead of paying for an extra `get_bars()` round-trip.

**Tech Stack:** FastAPI, SQLAlchemy v2 (async, aiosqlite for tests), pytest + pytest-asyncio.

**Out of scope:** This plan does not change *which* model `evaluate_scheduled()`'s `"HMM_daily"` branch uses (it fits `compute_intraday_hmm` on daily bars, the session-state Trending/Choppy/Mean-reverting model, not `regime_hmm_daily.py`'s Bull/Bear/Sideways model) — that naming/semantics question belongs to the composite system's own `MarkovTriggerDef` design and is unrelated to whether the WS path can evaluate it at all. This plan is purely about closing the WS-vs-scheduled parity gap using the model choice that already exists today.

**Known limitation this plan introduces (flag, don't fix here):** once `evaluate_from_context` actually computes HMM results, a composite rule with an HMM primary condition will re-fit a 3-state `GaussianHMM` from scratch on **every WS candle-close event**, with no caching across ticks within the same interval. This is the same cost pattern the sibling `2026-07-04-test-rule-candle-cap.md` plan caps for the dry-run endpoint, but this plan does not add an equivalent cap or cache for the live path — doing so would require a caching layer (e.g. skip refit if the same symbol/interval/model was fit within the last N seconds) that's a meaningfully larger change than "make the WS path match the scheduled path's existing behavior." Flag this to the user as a follow-up if live HMM-primary composite rules become common enough for the per-tick refit cost to matter in practice.

---

## File Structure

- Modify: `backend/app/services/composite_trigger_evaluator.py` — `evaluate_from_context()` (currently lines 158-223): replace the always-fail `HMM_intraday`/`HMM_daily` branch with real computation from `bars_intraday`/`bars_daily`.
- Modify: `backend/app/routers/chart_alerts.py` — `evaluate_and_notify_for_symbol()` (currently lines 391-557): extend the `_needs_daily_bars` check to also cover a `HMM_daily` primary condition, and reuse `all_candles` as `bars_daily` when `interval` is already `"1D"`/`"1W"`.
- Test: `backend/tests/test_composite_trigger.py` — new tests for `evaluate_from_context()`'s HMM branches.
- Test: `backend/tests/test_chart_alerts_composite_ws.py` — new end-to-end WS tests proving HMM_intraday/HMM_daily composite rules actually fire.

---

## Task 1: Make `evaluate_from_context()` compute HMM_intraday/HMM_daily instead of always failing

**Files:**
- Modify: `backend/app/services/composite_trigger_evaluator.py:184-198`
- Test: `backend/tests/test_composite_trigger.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_composite_trigger.py`, after the existing `_make_omm` helper (around line 37):

```python
def _make_hmm_result(state="Trending", p_stay=0.8, p_transition=None):
    hmm = MagicMock()
    hmm.state = state
    hmm.p_stay = p_stay
    hmm.p_transition = p_transition or []
    return hmm
```

Then append these tests at the end of the file:

```python
def test_evaluate_from_context_hmm_intraday_computes_from_bars(monkeypatch):
    """HMM_intraday primary condition must actually be evaluated when bars_intraday
    is supplied, not unconditionally fail (the pre-fix behavior)."""
    import app.services.regime_hmm as regime_hmm

    trigger = _make_trigger(model="HMM_intraday", to_state="Trending", min_confirmations=0)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda bars: _make_hmm_result("Trending", 0.8))
    bars = [{"close": 100.0 + i} for i in range(210)]

    assert evaluate_from_context(trigger, None, [], {}, bars_intraday=bars) is True


def test_evaluate_from_context_hmm_intraday_wrong_state_fails(monkeypatch):
    import app.services.regime_hmm as regime_hmm

    trigger = _make_trigger(model="HMM_intraday", to_state="Choppy", min_confirmations=0)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda bars: _make_hmm_result("Trending", 0.8))
    bars = [{"close": 100.0 + i} for i in range(210)]

    assert evaluate_from_context(trigger, None, [], {}, bars_intraday=bars) is False


def test_evaluate_from_context_hmm_intraday_no_bars_fails_closed():
    """No bars_intraday supplied (or empty) — must fail closed, not raise."""
    trigger = _make_trigger(model="HMM_intraday", min_confirmations=0)
    assert evaluate_from_context(trigger, None, [], {}, bars_intraday=[]) is False
    assert evaluate_from_context(trigger, None, [], {}) is False  # kwarg omitted entirely


def test_evaluate_from_context_hmm_daily_computes_from_daily_bars(monkeypatch):
    """HMM_daily primary condition must be evaluated from bars_daily, mirroring
    evaluate_scheduled()'s existing HMM_daily branch (compute_intraday_hmm on daily bars)."""
    import app.services.regime_hmm as regime_hmm

    trigger = _make_trigger(model="HMM_daily", to_state="Choppy", min_confirmations=0)
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda bars: _make_hmm_result("Choppy", 0.9))
    bars = [{"close": 100.0 + i} for i in range(210)]

    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars) is True


def test_evaluate_from_context_hmm_daily_no_bars_fails_closed():
    trigger = _make_trigger(model="HMM_daily", min_confirmations=0)
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=[]) is False


def test_evaluate_from_context_hmm_daily_p_stay_below_threshold_fails(monkeypatch):
    """p_stay_min gate must still apply for the WS path exactly as it does for the
    scheduled path — proves this isn't just a state-match shortcut."""
    import app.services.regime_hmm as regime_hmm

    trigger = _make_trigger(model="HMM_daily", to_state="Choppy", min_confirmations=0)
    trigger["primary"]["p_stay_min"] = 0.9
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda bars: _make_hmm_result("Choppy", 0.5))
    bars = [{"close": 100.0 + i} for i in range(210)]

    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars) is False


def test_evaluate_from_context_hmm_intraday_p_transition_min_gate_applies(monkeypatch):
    """_check_primary_hmm's p_transition_min gate (max transition probability to any
    other state) must actually be reachable via this new code path, not just the
    state/p_stay checks — a trigger with real p_transition data below the configured
    p_transition_min must fail even though state and p_stay both pass."""
    import app.services.regime_hmm as regime_hmm

    trigger = _make_trigger(model="HMM_intraday", to_state="Trending", min_confirmations=0)
    trigger["primary"]["p_transition_min"] = 0.5
    hmm_result = _make_hmm_result(
        "Trending", 0.8,
        p_transition=[{"to": "Choppy", "prob": 0.2}, {"to": "Mean-reverting", "prob": 0.1}],
    )
    monkeypatch.setattr(regime_hmm, "compute_intraday_hmm", lambda bars: hmm_result)
    bars = [{"close": 100.0 + i} for i in range(210)]

    # Max transition prob (0.2) is below p_transition_min (0.5) → must fail.
    assert evaluate_from_context(trigger, None, [], {}, bars_intraday=bars) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_composite_trigger.py -v -k hmm`
Expected: FAIL — all new tests assert `True` where the current code always returns `False` for `HMM_intraday`/`HMM_daily`, or the `_make_hmm_result` helper doesn't exist yet.

- [ ] **Step 3: Implement**

First, update `evaluate_from_context`'s own docstring (currently lines 166-178), which currently says `bars_daily`/`bars_intraday` are "needed only if trigger_def sets strategy_confirmations" — after this task that claim is wrong, since they're now also required for HMM_intraday/HMM_daily primary conditions:

Before:
```python
    """Alert/WebSocket path. Receives pre-computed model outputs — no I/O for the
    primary/confirmations checks. bars_daily/bars_intraday are optional and, when
    supplied by the caller, let this path apply the same strategy_confirmations
    gate evaluate_scheduled() applies — keeping WS-fired and scheduled-fired
    composite alerts behaviorally consistent.

    trigger_def: CompositeTriggerDef serialized as dict (or the Pydantic model)
    omm_result: OmmResult dataclass from compute_omm() — attribute access (.state, .conviction_pct, .p_stay)
    structure_signals: list of market structure signal dicts from market_structure.py
    indicator_values: dict of indicator name → value for momentum confirmations
    bars_daily: OHLCV daily bars, needed only if trigger_def sets strategy_confirmations
    bars_intraday: OHLCV intraday bars, needed only if trigger_def sets strategy_confirmations
    """
```

After:
```python
    """Alert/WebSocket path. Receives pre-computed model outputs — no I/O for the
    OMM primary/confirmations checks. bars_daily/bars_intraday are optional and,
    when supplied by the caller, let this path apply the same strategy_confirmations
    gate and HMM_intraday/HMM_daily primary-condition checks evaluate_scheduled()
    applies — keeping WS-fired and scheduled-fired composite alerts behaviorally
    consistent.

    trigger_def: CompositeTriggerDef serialized as dict (or the Pydantic model)
    omm_result: OmmResult dataclass from compute_omm() — attribute access (.state, .conviction_pct, .p_stay);
        ignored unless primary.model == "OMM"
    structure_signals: list of market structure signal dicts from market_structure.py
    indicator_values: dict of indicator name → value for momentum confirmations
    bars_daily: OHLCV daily bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_daily" (used to fit the HMM directly)
    bars_intraday: OHLCV intraday bars — needed if trigger_def sets strategy_confirmations,
        OR if primary.model == "HMM_intraday" (used to fit the HMM directly)
    """
```

Then replace lines 184-198 (the `# Check primary Markov condition` block inside `evaluate_from_context`):

Before:
```python
    primary = td.get("primary", {})
    model = primary.get("model", "OMM")

    # Check primary Markov condition
    if model == "OMM":
        if not _check_primary_omm(td, omm_result):
            return False
    elif model in ("HMM_intraday", "HMM_daily"):
        # For the alert path, hmm result is passed via omm_result slot (caller must adapt)
        # In practice, alert path uses OMM only — HMM is for watch path
        logger.warning("evaluate_from_context: HMM model requested but only OMM result provided; skipping")
        return False
    elif model == "any":
        # 'any' means regime model doesn't matter — skip primary check
        pass
```

After:
```python
    primary = td.get("primary", {})
    model = primary.get("model", "OMM")

    # Check primary Markov condition
    if model == "OMM":
        if not _check_primary_omm(td, omm_result):
            return False
    elif model == "HMM_intraday":
        if not bars_intraday:
            logger.warning("evaluate_from_context: HMM_intraday requested but no intraday bars supplied; skipping")
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_intraday)
            if not _check_primary_hmm(td, hmm_result):
                return False
        except Exception as exc:
            logger.warning("evaluate_from_context: HMM_intraday failed — %s", exc)
            return False
    elif model == "HMM_daily":
        # compute_intraday_hmm works on any list[dict] with 'close' keys; use daily
        # bars — same model choice evaluate_scheduled()'s own HMM_daily branch makes.
        if not bars_daily:
            logger.warning("evaluate_from_context: HMM_daily requested but no daily bars supplied; skipping")
            return False
        try:
            from app.services.regime_hmm import compute_intraday_hmm
            hmm_result = compute_intraday_hmm(bars_daily)
            if not _check_primary_hmm(td, hmm_result):
                return False
        except Exception as exc:
            logger.warning("evaluate_from_context: HMM_daily failed — %s", exc)
            return False
    elif model == "any":
        # 'any' means regime model doesn't matter — skip primary check
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_composite_trigger.py -v`
Expected: all tests in the file PASS, including the 7 new ones (step 1's own code block lists 7 distinct test functions — don't trust a hardcoded count here over what step 1 actually shows).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/composite_trigger_evaluator.py backend/tests/test_composite_trigger.py
git commit -m "fix(alerts): evaluate HMM_intraday/HMM_daily primary conditions on the WS path"
```

---

## Task 2: Wire real bars into the WS caller for HMM_daily composite rules

**Files:**
- Modify: `backend/app/routers/chart_alerts.py:466-491`
- Test: `backend/tests/test_chart_alerts_composite_ws.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_chart_alerts_composite_ws.py`, after the existing `_HMM`-free trigger defs (near the top, after `_FLAT_CANDLES`):

```python
_HMM_TRIGGER_DAILY = {
    "primary": {"model": "HMM_daily", "to_state": "Trending", "p_stay_min": 0.5, "p_transition_min": 0.0},
    "confirmations": [],
    "min_confirmations": 0,
}

_HMM_TRIGGER_INTRADAY = {
    "primary": {"model": "HMM_intraday", "to_state": "Trending", "p_stay_min": 0.5, "p_transition_min": 0.0},
    "confirmations": [],
    "min_confirmations": 0,
}
```

Then append these test functions at the end of the file:

```python
@pytest.mark.asyncio
async def test_ws_composite_path_evaluates_hmm_daily_using_all_candles_when_interval_is_daily(monkeypatch):
    """A composite rule with primary.model='HMM_daily' saved on a '1D' rule must be
    evaluated over WS using all_candles directly as bars_daily (no extra get_bars()
    fetch needed, since all_candles already IS daily data for a '1D' rule) — instead
    of always failing closed as it did before this fix."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-6', 'AAPL', '1D', _HMM_TRIGGER_DAILY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '1D', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_not_called()


@pytest.mark.asyncio
async def test_ws_composite_path_evaluates_hmm_intraday_primary_condition(monkeypatch):
    """A composite rule with primary.model='HMM_intraday' on an intraday rule must
    actually be evaluated over WS using all_candles as bars_intraday."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(chart_alerts, 'get_bars', AsyncMock(return_value=_FLAT_BARS))

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-7', 'AAPL', '15min', _HMM_TRIGGER_INTRADAY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1


@pytest.mark.asyncio
async def test_ws_composite_path_hmm_daily_fetches_bars_when_rule_interval_is_intraday(monkeypatch):
    """When the rule's own interval is intraday but primary.model='HMM_daily', the WS
    path must fetch real daily bars via get_bars() (all_candles is intraday data and
    would be the wrong series to fit a daily HMM on) rather than failing closed."""
    from app.routers import chart_alerts
    import app.services.regime_hmm as regime_hmm

    Session = await _make_session_factory()
    monkeypatch.setattr(chart_alerts, 'AsyncSessionLocal', Session)
    get_bars_mock = AsyncMock(return_value=_FLAT_BARS)
    monkeypatch.setattr(chart_alerts, 'get_bars', get_bars_mock)

    hmm_result = MagicMock(state="Trending", p_stay=0.8, p_transition=[])
    monkeypatch.setattr(regime_hmm, 'compute_intraday_hmm', lambda bars: hmm_result)

    async with Session() as db:
        db.add(_make_composite_rule_row('rule-8', 'AAPL', '15min', _HMM_TRIGGER_DAILY))
        await db.commit()

    triggered = await chart_alerts.evaluate_and_notify_for_symbol(
        'AAPL', '15min', _FLAT_CANDLES[-1], _FLAT_CANDLES, [],
    )
    assert len(triggered) == 1
    get_bars_mock.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v -k hmm`
Expected: FAIL — `triggered` comes back `[]` for all three new tests, because `_needs_daily_bars` doesn't yet check for `HMM_daily` and `evaluate_from_context` (pre-Task-1) always failed for HMM models. (If Task 1 is already applied, only the `_needs_daily_bars`/bars-reuse gap remains, so `test_ws_composite_path_evaluates_hmm_daily_using_all_candles_when_interval_is_daily` fails because `_bars_daily` stays `[]`, not because `evaluate_from_context` fails.)

- [ ] **Step 3: Implement**

In `backend/app/routers/chart_alerts.py`, replace lines 472-491 (the daily-bars-fetch block inside the `if composite_rows:` section):

Before:
```python
            # Only fetch daily bars if some composite rule actually needs them —
            # most composite rules have no strategy_confirmations and should not
            # pay for an extra get_bars() round-trip on every candle close.
            _needs_daily_bars = any(_rj.get("strategy_confirmations") for _, _rj in composite_rows)
            _bars_daily: list[dict] = []
            if _needs_daily_bars:
                try:
                    _end = date.today()
                    _start = _end - timedelta(days=730)
                    _bars_daily = await get_bars(symbol, _start, _end)
                except Exception as _exc:
                    logger.warning("composite rule strategy-confirmation bars fetch failed for %s: %s", symbol, _exc)
                    _bars_daily = []

            # all_candles are only genuinely intraday when the rule's own interval is
            # intraday — chart.py's get_intraday(symbol, interval) returns daily candles
            # for '1D'/'1W' rules, so passing them as bars_intraday would mislabel daily
            # data as intraday to the VWAP mean-reversion check.
            _bars_intraday = all_candles if interval not in ("1D", "1W") else []
```

After:
```python
            # Only fetch daily bars if some composite rule actually needs them — either
            # for strategy_confirmations, or because a rule's primary condition targets
            # the HMM_daily model (which requires daily bars to fit against).
            _needs_daily_bars = any(
                _rj.get("strategy_confirmations") or _rj.get("primary", {}).get("model") == "HMM_daily"
                for _, _rj in composite_rows
            )
            _bars_daily: list[dict] = []
            if _needs_daily_bars:
                if interval in ("1D", "1W"):
                    # all_candles is already daily/weekly data for this rule's own
                    # interval — reuse it instead of paying for an extra get_bars()
                    # round-trip.
                    _bars_daily = all_candles
                else:
                    try:
                        _end = date.today()
                        _start = _end - timedelta(days=730)
                        _bars_daily = await get_bars(symbol, _start, _end)
                    except Exception as _exc:
                        logger.warning("composite rule strategy-confirmation bars fetch failed for %s: %s", symbol, _exc)
                        _bars_daily = []

            # all_candles are only genuinely intraday when the rule's own interval is
            # intraday — chart.py's get_intraday(symbol, interval) returns daily candles
            # for '1D'/'1W' rules, so passing them as bars_intraday would mislabel daily
            # data as intraday to the VWAP mean-reversion check.
            _bars_intraday = all_candles if interval not in ("1D", "1W") else []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest tests/test_chart_alerts_composite_ws.py -v`
Expected: all tests in the file PASS, including the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/chart_alerts.py backend/tests/test_chart_alerts_composite_ws.py
git commit -m "fix(alerts): fetch/reuse daily bars for HMM_daily composite rules on the WS path"
```

---

## Final verification (run once, after both tasks)

- [ ] Run the full backend test suite: `cd "F:\Git\GitHub\Trading assistant\backend" && venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (no regressions), new HMM tests included.

## Self-Review Notes

- **Spec coverage:** Task 1 closes the "HMM_intraday/HMM_daily can't fire over WS" gap for the composite evaluator itself; Task 2 closes it for the WS caller that must supply bars for `HMM_daily` (mirroring the existing `strategy_confirmations` bars-fetch pattern). Both were explicitly named in the deferred item.
- **No placeholders:** every step has literal code, exact before/after snippets, and runnable pytest commands.
- **Type/name consistency:** `bars_intraday`/`bars_daily` keyword names match `evaluate_from_context`'s existing signature (already accepts both as optional kwargs from the prior session's Bug 1 fix) — no signature change needed, only the body's model-branch logic changes.
