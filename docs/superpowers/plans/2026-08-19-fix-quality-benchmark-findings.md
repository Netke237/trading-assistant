# Fix Quality-Benchmark Medium Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three Medium-severity findings from the 2026-08-18 `TRADING_QUALITY_BENCHMARK.md` run: a genuinely dead `breakout_base` entry condition, a cost-modeling gap between the trader-facing backtest and the WFO tuner, and stale numbers in `SCORING_RULES.md`.

**Architecture:** Three independent, narrowly-scoped fixes touching disjoint files (`strategy_engine.py`+`strategy_params.yaml`; `strategy_backtest.py`+`stock_scan.py`; `SCORING_RULES.md`). No shared state between them — implement and commit in any order, each is safe to land alone.

**Tech Stack:** Python 3.12 / FastAPI backend, pytest, `backtesting.py` third-party library, YAML config.

---

## Background (read this before starting)

This plan fixes findings confirmed by two independent audit passes on 2026-08-18 against `backend/` on `origin/main` (verified identical on this worktree's base commit `d6f5a43`):

1. **`breakout_base_signal`'s tight-base gate is mathematically unfireable on real data.** `backend/app/services/strategy_engine.py:368`'s `atr_tight_max` default (1.5) requires a 20-bar price range to be ≤1.5×ATR(14). A 20-bar range on a random walk scales roughly with `sqrt(20)×ATR ≈ 4.5×ATR` — traced bar-by-bar across 4 real symbols over a full year, the tightest base ever observed was 2.77×ATR (SPY), still nearly double the 1.5 ceiling. The WFO search grid (`backend/config/strategy_params.yaml`, `[1.0, 1.5, 2.0]`) can't reach a passing value either — the strategy is dead at every value the optimizer is allowed to try.

2. **The live/UI-facing backtest (Step-6 confidence gate) runs cost-free.** `run_strategy_backtest()` (`backend/app/services/strategy_backtest.py:123`) calls `Backtest(df, _Strategy, cash=100_000, commission=0.0, ...)` — zero commission, zero slippage. The separate WFO tuning path (`backend/app/services/strategy_param_optimizer.py:109-114,133-137`) nets out `fee_pct`+`slippage_pct` via `apply_costs()` before scoring proposals — but only for its own internal fold-consistency scoring, and only against `total_return_pct`, not `win_rate`/`expectancy`. The two call sites in `backend/app/routers/stock_scan.py` (`_analyze_core` at line 379, `_process_stock` at line 793) that feed the trader-facing Step-6 gate never apply any cost model at all, so the number a trader sees is the optimistic, friction-free one.

3. **`SCORING_RULES.md` has drifted from the live `backend/config/scoring_rules.yaml`.** The doc self-labels as "Source of truth" with no staleness disclaimer, and materially understates the screener's strictness: documents a PASS/CAUTION gate of 70/50 when the live gate is 55/35, documents RSI-floor/event-window/swing-high-lookback numbers that no longer match any of the three horizon configs.

Each task below is independently testable and independently committable.

---

## Task 1: Fix `breakout_base_signal`'s dead entry condition

**Files:**
- Modify: `backend/app/services/strategy_engine.py:346` (function signature default)
- Modify: `backend/config/strategy_params.yaml:53-69` (`breakout_base` active + search config)
- Test: `backend/tests/test_strategy_engine.py` (new test)

- [ ] **Step 1: Write the failing test proving the current default is dead**

Add to `backend/tests/test_strategy_engine.py` (append at end of file):

```python
def _breakout_base_bars_with_ratio(base_range_over_atr: float):
    """26 bars: 5 flat warmup + 20-bar base whose (high-low) range is
    `base_range_over_atr` * ATR(14), + 1 breakout bar on 2x volume.

    Each bar has a fixed 1.0 high-low span (keeps true-range ~= 1.0 per bar,
    so ATR(14) ~= 1.0), while the 20 base-bar closes drift by
    `(base_range_over_atr - 1.0)` total across the window — so
    base_high - base_low = drift + 1.0 = base_range_over_atr * ATR.
    """
    bars = []
    for _ in range(5):
        bars.append({"open": 100.0, "high": 100.5, "low": 99.5,
                      "close": 100.0, "volume": 1_000_000})
    drift = base_range_over_atr - 1.0
    step = drift / 19
    for i in range(20):
        close = 100.0 + step * i
        bars.append({"open": close, "high": close + 0.5, "low": close - 0.5,
                      "close": close, "volume": 1_000_000})
    base_high = max(b["high"] for b in bars[-20:])
    bars.append({"open": base_high + 0.5, "high": base_high + 1.5,
                 "low": base_high - 0.1, "close": base_high + 1.0,
                 "volume": 2_000_000})
    return bars


def test_breakout_base_signal_fires_at_realistic_base_tightness():
    """A base range of ~3.3x ATR is what real 20-bar consolidations actually
    look like (2026-08-18 audit: observed minimum 2.77x-3.22x across 4 real
    symbols over a full year). breakout_base_signal must be able to fire on
    a base this tight — if this test fails with signal is None, atr_tight_max
    has regressed back to a value real data can never satisfy."""
    bars = _breakout_base_bars_with_ratio(3.3)
    signal = breakout_base_signal(bars, direction="Bullish")
    assert signal is not None, (
        "breakout_base_signal returned None on a 3.3x-ATR base — this is "
        "within the range real market data actually produces (2.77x-3.22x "
        "observed), so atr_tight_max must be loose enough to admit it."
    )


def test_breakout_base_signal_still_rejects_a_genuinely_wide_base():
    """Sanity check the gate still rejects a base that is NOT tight by any
    reasonable definition (10x ATR)."""
    bars = _breakout_base_bars_with_ratio(10.0)
    signal = breakout_base_signal(bars, direction="Bullish")
    assert signal is None
```

- [ ] **Step 2: Run the new tests to verify they fail against the current default**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_strategy_engine.py -k breakout_base_signal_fires_at_realistic -v`
Expected: FAIL — `assert signal is not None` fails because `signal` is `None` (the default `atr_tight_max=1.5` rejects a 3.3x-ATR base).

- [ ] **Step 3: Fix the default in `strategy_engine.py`**

In `backend/app/services/strategy_engine.py`, find the `breakout_base_signal` signature (currently at line 346):

```python
def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 1.5,
    volume_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (breakout uses close)
) -> StrategySignal | None:
```

Change `atr_tight_max: float = 1.5` to `atr_tight_max: float = 4.0`:

```python
def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 4.0,
    volume_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (breakout uses close)
) -> StrategySignal | None:
```

Then find the comment above the gate check a few lines down:

```python
    atr = _atr(bars)
    # Tight base: range < atr_tight_max * ATR
    if atr > 0 and (base_high - base_low) > atr_tight_max * atr:
        return None
```

Replace the comment to record why 4.0, not 1.5 (2026-08-18 audit, `strategy_engine.py:368`):

```python
    atr = _atr(bars)
    # Tight base: range < atr_tight_max * ATR. A 20-bar range scales roughly
    # with sqrt(base_lookback) ~= 4.5x ATR on a random walk — 1.5 (the old
    # default) was unfireable on any real data (2026-08-18 audit: observed
    # minimum 2.77x-3.22x across 4 real symbols over a full year). 4.0 keeps
    # this selective while staying reachable.
    if atr > 0 and (base_high - base_low) > atr_tight_max * atr:
        return None
```

- [ ] **Step 4: Fix the config default and search grid in `strategy_params.yaml`**

In `backend/config/strategy_params.yaml`, find:

```yaml
  breakout_base:
    active:
      bullish:
        base_lookback: 20
        atr_tight_max: 1.5
        volume_mult: 1.5
        rr_target_mult: 2.0
      bearish:
        base_lookback: 20
        atr_tight_max: 1.5
        volume_mult: 1.5
        rr_target_mult: 2.0
    search:
      base_lookback: [15, 20, 30]
      atr_tight_max: [1.0, 1.5, 2.0]
      volume_mult: [1.1, 1.3, 1.5]
      rr_target_mult: [1.5, 2.0, 2.5, 3.0]
```

Replace with:

```yaml
  breakout_base:
    active:
      bullish:
        base_lookback: 20
        atr_tight_max: 4.0
        volume_mult: 1.5
        rr_target_mult: 2.0
      bearish:
        base_lookback: 20
        atr_tight_max: 4.0
        volume_mult: 1.5
        rr_target_mult: 2.0
    search:
      base_lookback: [15, 20, 30]
      atr_tight_max: [3.0, 3.5, 4.0, 4.5]
      volume_mult: [1.1, 1.3, 1.5]
      rr_target_mult: [1.5, 2.0, 2.5, 3.0]
```

(The old search grid `[1.0, 1.5, 2.0]` was entirely below the observed real-data minimum of 2.77 — the optimizer could never find a passing value. The new grid brackets the realistic range with headroom on both sides.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_strategy_engine.py -k breakout_base_signal -v`
Expected: PASS — all `breakout_base_signal` tests pass, including the two new ones.

- [ ] **Step 6: Run the full strategy_engine + strategy_param_store test files to confirm no regression**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_strategy_engine.py tests/test_strategy_engine_bearish.py tests/test_strategy_param_store.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py -v`
Expected: PASS — all tests green. (`test_strategy_param_store.py::test_get_active_multiple_strategies` asserts against its own fixture YAML in `conftest.py`, unaffected by the real-config change made in Step 4.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/config/strategy_params.yaml backend/tests/test_strategy_engine.py
git commit -m "fix(strategy): un-block breakout_base's dead tight-base gate (atr_tight_max 1.5 -> 4.0)"
```

---

## Task 2: Wire real transaction-cost modeling into the live/UI-facing backtest path

**Files:**
- Modify: `backend/app/services/strategy_backtest.py:58-123` (add `commission` parameter)
- Modify: `backend/app/routers/stock_scan.py:48` (import), `:142` area (new helper), `:379-381` and `:793-798` (call sites)
- Test: `backend/tests/test_strategy_backtest.py` (new test)
- Test: `backend/tests/test_stock_scan_backtest_commission.py` (new file)

- [ ] **Step 1: Write the failing test for `run_strategy_backtest`'s new `commission` parameter**

Add to `backend/tests/test_strategy_backtest.py` (append at end of file):

```python
def test_commission_reduces_return_versus_zero_commission():
    """A non-zero commission must actually drag down the backtest's reported
    return relative to commission=0.0 — proves the parameter is threaded
    into backtesting.py's Backtest(...) call, not just accepted and ignored."""
    bars = _synth_bars(500, trend=True)
    free = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.0)
    costly = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.01)
    assert free.n_trades >= 10, "fixture must produce enough trades for this comparison to be meaningful"
    assert costly.n_trades == free.n_trades, "commission must not change which trades fire, only their P&L"
    assert costly.total_return_pct < free.total_return_pct
    assert costly.expectancy < free.expectancy


def test_commission_defaults_to_zero():
    """Backward compatibility: existing callers that don't pass commission=
    must see identical behavior to before this change."""
    bars = _synth_bars(500, trend=True)
    default = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish")
    explicit_zero = run_strategy_backtest(bars, strategy="ma_crossover", direction="Bullish", commission=0.0)
    assert default.total_return_pct == explicit_zero.total_return_pct
    assert default.n_trades == explicit_zero.n_trades
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_strategy_backtest.py -k commission -v`
Expected: FAIL with `TypeError: run_strategy_backtest() got an unexpected keyword argument 'commission'`.

- [ ] **Step 3: Add the `commission` parameter to `run_strategy_backtest`**

In `backend/app/services/strategy_backtest.py`, find the function signature (currently lines 58-66):

```python
def run_strategy_backtest(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int = _MIN_TRADES,
    min_win_rate: float = _MIN_WIN_RATE,
    params: dict | None = None,
) -> BacktestResult:
```

Add `commission: float = 0.0` after `params`:

```python
def run_strategy_backtest(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int = _MIN_TRADES,
    min_win_rate: float = _MIN_WIN_RATE,
    params: dict | None = None,
    commission: float = 0.0,
) -> BacktestResult:
```

Then find the `Backtest(...)` construction (currently line 123):

```python
    try:
        bt = Backtest(df, _Strategy, cash=100_000, commission=0.0, exclusive_orders=True)
        stats = bt.run()
```

Replace `commission=0.0` with `commission=commission`:

```python
    try:
        bt = Backtest(df, _Strategy, cash=100_000, commission=commission, exclusive_orders=True)
        stats = bt.run()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_strategy_backtest.py -k commission -v`
Expected: PASS.

- [ ] **Step 5: Write the failing router-integration test**

Create `backend/tests/test_stock_scan_backtest_commission.py`:

```python
import asyncio
from unittest.mock import MagicMock, patch


def _fake_signal():
    sig = MagicMock()
    sig.entry_price = 150.0
    sig.stop_price = 145.0
    sig.target_price = 160.0
    sig.rr_ratio = 2.0
    sig.atr = 3.0
    sig.detail = {}
    return sig


def _fake_bt_result():
    bt = MagicMock()
    bt.passes_gate = True
    bt.n_trades = 10
    bt.win_rate = 0.6
    bt.total_return_pct = 5.0
    bt.max_drawdown_pct = 2.0
    bt.expectancy = 1.5
    bt.sharpe = 1.2
    bt.summary_text = "ok"
    return bt


def test_process_stock_passes_commission_from_get_costs():
    """_process_stock's run_strategy_backtest call (stock_scan.py ~line 793)
    must pass commission= sourced from strategy_param_store.get_costs(),
    not the previous hardcoded commission-free default."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockScanRequest

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run_strategy_backtest(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )
    fake_bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
                  "volume": 1_000_000, "date": "2024-01-01", "time": i} for i in range(130)]

    card = MagicMock()
    card.status = "PASS"
    card.score = 70
    card.rules = []

    async def run():
        with patch("app.routers.stock_scan.score_stock", return_value=card), \
             patch("app.routers.stock_scan.get_historical_bars", return_value=fake_bars), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan.compute_confidence", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run_strategy_backtest), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=None), \
             patch("app.routers.stock_scan.get_active", return_value={}), \
             patch("app.routers.stock_scan.get_costs", return_value={"fee_pct": 0.002, "slippage_pct": 0.003}), \
             patch("app.routers.stock_scan.get_cached", return_value={"confidence": None, "sample_size": 0}), \
             patch("app.routers.stock_scan.set_cached", return_value=None), \
             patch.dict(ss._SIGNAL_FNS, {"pullback_ema": lambda *a, **k: _fake_signal()}):
            await ss._process_stock("AAPL", req, "test-scan-id", {}, [])

    asyncio.run(run())
    assert "commission" in captured, "run_strategy_backtest was not called with a commission= kwarg"
    assert captured["commission"] == 0.005, (
        f"expected commission = fee_pct(0.002) + slippage_pct(0.003) = 0.005, got {captured['commission']}"
    )


def test_analyze_core_passes_commission_from_get_costs():
    """_analyze_core's run_strategy_backtest call (stock_scan.py ~line 379)
    must pass the same commission= as _process_stock."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    ss._BACKTEST_CACHE.clear()
    captured: dict = {}

    def fake_run_strategy_backtest(*args, **kwargs):
        captured.update(kwargs)
        return _fake_bt_result()

    req = StockAnalysisRequest(symbol="AAPL", direction="Bullish", horizon="Swing", strategy="pullback_ema")
    fake_bars = [{"close": 150.0, "open": 148.0, "high": 152.0, "low": 147.0,
                  "volume": 1_000_000, "time": i} for i in range(130)]

    card = MagicMock()
    card.status = "PASS"
    card.score = 70
    card.rules = []

    async def run():
        with patch("app.routers.stock_scan.get_historical_bars", return_value=fake_bars), \
             patch("app.routers.stock_scan.fetch_quotes", return_value={}), \
             patch("app.routers.stock_scan.fetch_price_async", return_value=150.0), \
             patch("app.routers.stock_scan.fetch_company_name_async", return_value="Apple Inc"), \
             patch("app.routers.stock_scan.fetch_intraday_candles", return_value=[]), \
             patch("app.routers.stock_scan.score_stock", return_value=card), \
             patch("app.routers.stock_scan._get_fundamentals", return_value=None), \
             patch("app.routers.stock_scan.run_strategy_backtest", side_effect=fake_run_strategy_backtest), \
             patch("app.routers.stock_scan.get_costs", return_value={"fee_pct": 0.002, "slippage_pct": 0.003}), \
             patch.dict(ss._SIGNAL_FNS, {"pullback_ema": lambda *a, **k: _fake_signal()}):
            await ss._analyze_core("AAPL", req)

    asyncio.run(run())
    assert "commission" in captured, "run_strategy_backtest was not called with a commission= kwarg"
    assert captured["commission"] == 0.005
```

- [ ] **Step 6: Run the new tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_stock_scan_backtest_commission.py -v`
Expected: FAIL — `AssertionError: run_strategy_backtest was not called with a commission= kwarg` (or an import error for `get_costs` not yet imported into `stock_scan.py`).

- [ ] **Step 7: Add the `get_costs` import and a `_backtest_commission()` helper to `stock_scan.py`**

In `backend/app/routers/stock_scan.py`, find the import (currently line 48):

```python
from app.services.strategy_param_store import get_active
```

Change to:

```python
from app.services.strategy_param_store import get_active, get_costs
```

Then find `_merge_strategy_params` (currently starting at line 142):

```python
def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
```

Add a new helper function immediately above it:

```python
def _backtest_commission() -> float:
    """Per-leg cost drag sourced from the same strategy_params.yaml `costs`
    block the WFO tuner (strategy_param_optimizer.py) already uses — keeps
    the Step-6 trader-facing backtest gate cost-aware instead of the
    commission-free number it showed before (2026-08-18 audit finding)."""
    costs = get_costs()
    return costs.get("fee_pct", 0.001) + costs.get("slippage_pct", 0.001)


def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
```

- [ ] **Step 8: Wire `commission=_backtest_commission()` into both call sites**

In `backend/app/routers/stock_scan.py`, find the `_analyze_core` call site (currently lines 376-381):

```python
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, _bt_bars, strategy=req.strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate, params=signal_kwargs))
```

Replace with:

```python
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, _bt_bars, strategy=req.strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate, params=signal_kwargs,
                                  commission=_backtest_commission()))
```

Then find the `_process_stock` call site (currently lines 789-798):

```python
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bt_bars,
                        strategy=_bt_strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                        params=_bt_params,
                    ),
                )
```

Replace with:

```python
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bt_bars,
                        strategy=_bt_strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                        params=_bt_params, commission=_backtest_commission(),
                    ),
                )
```

- [ ] **Step 9: Run the new tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_stock_scan_backtest_commission.py -v`
Expected: PASS.

- [ ] **Step 10: Run the full stock_scan + strategy_backtest test files to confirm no regression**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_stock_scan_router.py tests/test_stock_scan_overrides.py tests/test_stock_scan_persistence.py tests/test_stock_scan_regime.py tests/test_analyze_stock.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py tests/test_stock_scan_backtest_commission.py -v`
Expected: PASS — all green, including the pre-existing `test_score_stock_receives_overrides_from_request` (unaffected — it only asserts on `score_stock` kwargs, called before the signal/backtest branch).

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/strategy_backtest.py backend/app/routers/stock_scan.py backend/tests/test_strategy_backtest.py backend/tests/test_stock_scan_backtest_commission.py
git commit -m "fix(backtest): apply real transaction costs to the trader-facing Step-6 backtest gate"
```

---

## Task 3: Refresh `SCORING_RULES.md` to match live `scoring_rules.yaml`

**Files:**
- Modify: `SCORING_RULES.md`

No automated test is possible for a markdown doc's prose accuracy — this task is verified by manual diff against `backend/config/scoring_rules.yaml`, not pytest. Each step below is a direct text replacement; use the Edit tool with the exact old/new text shown.

- [ ] **Step 1: Fix the header staleness**

Find (line 1-5):

```
# Bamendjou — Stock Scoring Rules

> **Source of truth for WS-20.** All numeric thresholds, weights, and decision boundaries are defined here.
> Values are seeded into `backend/config/scoring_rules.yaml`. Do not hardcode any of these numbers in Python.
> Last updated: 2026-04-30.
```

Replace with:

```
# Bamendjou — Stock Scoring Rules

> **Source of truth for WS-20.** All numeric thresholds, weights, and decision boundaries are defined here.
> Values are seeded into `backend/config/scoring_rules.yaml`. Do not hardcode any of these numbers in Python.
> Last updated: 2026-08-19. If a number here and in `backend/config/scoring_rules.yaml` ever
> disagree, the YAML file is authoritative — this doc had drifted materially out of sync with
> it for several months before this update (see `TRADING_QUALITY_BENCHMARK.md`).
```

- [ ] **Step 2: Fix the Swing-default RSI trigger value**

Find (line 96, in the "Momentum signals" table):

```
| RSI | Period 14 | Crosses above 44 from below OR bullish divergence: price lower low + RSI higher low within 15-bar window |
```

Replace with:

```
| RSI | Period 14 | Crosses above 38 from below OR bullish divergence: price lower low + RSI higher low within 15-bar window |
```

- [ ] **Step 3: Fix the Section 4 event-window prose table**

Find (lines 124-129):

```
### Thresholds (earnings and dividends treated identically)
| Days to event | Status |
|---|---|
| > 21 days (or no event) | PASS |
| 7–21 days | CAUTION |
| < 7 days | REJECT |
```

Replace with:

```
### Thresholds (earnings and dividends treated identically; Swing horizon shown — see Section 8 for the full per-horizon matrix)
| Days to event | Status |
|---|---|
| > 45 days (or no event) | PASS |
| 21–45 days | CAUTION |
| < 21 days | REJECT |
```

- [ ] **Step 4: Fix the Section 7 score-interpretation table**

Find (lines 166-170):

```
| Score | Status |
|---|---|
| ≥ 70 | PASS — strong setup, proceed to contract evaluation |
| 50–69 | CAUTION — proceed with awareness, consider smaller size |
| < 50 | REJECT — skip |
```

Replace with:

```
| Score | Status |
|---|---|
| ≥ 55 | PASS — strong setup, proceed to contract evaluation |
| 35–54 | CAUTION — proceed with awareness, consider smaller size |
| < 35 | REJECT — skip |
```

- [ ] **Step 5: Fix the Section 8 horizon-matrix table**

Find (lines 183, 187, 193-194):

```
| Swing high lookback (bars) | 20 | 40 | 15 |
```

Replace with:

```
| Swing high lookback (bars) | 20 | 40 | 75 |
```

Find:

```
| RSI floor | 44 | 44 | 48 |
```

Replace with:

```
| RSI floor | 40 | 38 | 37 |
```

Find:

```
| Earnings/dividend REJECT | < 1 day | < 7 days | < 30 days |
| Earnings/dividend CAUTION | 1–3 days | 7–21 days | 30–60 days |
```

Replace with:

```
| Earnings/dividend REJECT | < 1 day | < 21 days | < 30 days |
| Earnings/dividend CAUTION | 1–3 days | 21–45 days | 30–60 days |
```

- [ ] **Step 6: Fix the Section 8 YAML-seed block's header comment and score threshold**

Find (lines 230-236):

```yaml
```yaml
# backend/config/scoring_rules.yaml
# Generated from SCORING_RULES.md — 2026-04-30

score_thresholds:
  pass: 70
  caution: 50
```

Replace with:

```yaml
```yaml
# Abbreviated illustration of backend/config/scoring_rules.yaml's shape —
# NOT a complete copy (the real file additionally nests trend scoring under
# method: additive/crossover/relative_strength, and has rsi_ceiling /
# stoch_overbought fields for bearish signals not shown here). See that file
# for the authoritative, complete structure. Numbers below last synced 2026-08-19.

stock_score_thresholds:
  pass: 55
  caution: 35
```

- [ ] **Step 7: Fix the swing block's `rsi_floor`, `event`, and `volume_multiplier` values**

Find (in the swing block, `trigger:` section):

```
      rsi_floor: 44
      rsi_div_window_bars: 15
```

Replace with:

```
      rsi_floor: 38
      rsi_div_window_bars: 15
```

Find (still in the swing block):

```
      setup_window_bars: 8
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.20
      volume_bonus_pts: 10
    event:
      reject_days: 7
      caution_days: 21
```

Replace with:

```
      setup_window_bars: 8
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.50
      volume_bonus_pts: 10
    event:
      reject_days: 21
      caution_days: 45
```

- [ ] **Step 8: Fix the intraday block's `rsi_floor`**

Find (in the intraday block, `trigger:` section):

```
      rsi_floor: 44
      rsi_div_window_bars: 10
```

Replace with:

```
      rsi_floor: 40
      rsi_div_window_bars: 10
```

(The intraday block's `event.reject_days: 1` / `caution_days: 3`, `swing_high_lookback_bars: 20`, and `volume_multiplier: 1.20` already match the live config — no change needed there.)

- [ ] **Step 9: Fix the position block's `swing_high_lookback_bars`, `rsi_floor`, and `volume_multiplier`**

Find (in the position block, `pullback:` section):

```
      swing_high_lookback_bars: 15
      swing_high_min_bars_ago: 3
```

Replace with:

```
      swing_high_lookback_bars: 75
      swing_high_min_bars_ago: 3
```

Find (in the position block, `trigger:` section):

```
      rsi_floor: 48
      rsi_div_window_bars: 20
```

Replace with:

```
      rsi_floor: 37
      rsi_div_window_bars: 20
```

Find (still in the position block):

```
      setup_window_bars: 5
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.20
      volume_bonus_pts: 10
    event:
      reject_days: 30
      caution_days: 60
```

Replace with:

```
      setup_window_bars: 5
      momentum_signals_for_pass: 2
      volume_lookback_bars: 20
      volume_multiplier: 1.50
      volume_bonus_pts: 10
    event:
      reject_days: 30
      caution_days: 60
```

(The `reject_days`/`caution_days` values for position were already correct — this replacement is a no-op on those two lines, included only because `volume_multiplier` in the same block needed fixing and the surrounding context must stay unique for the edit.)

- [ ] **Step 10: Verify every numeric fix against the live YAML**

Run this from the repo root to diff the specific values fixed above against the live config, confirming no transcription errors:

```bash
grep -n "stock_score_thresholds\|pass: 55\|caution: 35" backend/config/scoring_rules.yaml | head -5
grep -n "rsi_floor\|swing_high_lookback_bars\|reject_days\|caution_days\|volume_multiplier" backend/config/scoring_rules.yaml
```

Manually compare the output against what was just written into `SCORING_RULES.md`'s Section 8 block (swing/intraday/position, in that order in the file). Every `rsi_floor`, `swing_high_lookback_bars` (position only), `reject_days`/`caution_days` (swing only), and `volume_multiplier` value in the doc must now match the corresponding value in this grep output exactly.

- [ ] **Step 11: Commit**

```bash
git add SCORING_RULES.md
git commit -m "docs(scoring): sync SCORING_RULES.md numbers with live scoring_rules.yaml (drifted since 2026-04-30)"
```

---

## Final verification (after all three tasks)

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (1511+ passed at baseline, plus 6 new tests added in Tasks 1-2 = 1517+ passed), 0 failures.

- [ ] **Step 2: Run the quant regression suite specifically**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_data_leakage.py tests/test_regime_no_lookahead.py tests/test_walk_forward.py tests/test_signal_confidence.py tests/test_strategy_backtest.py`
Expected: all pass (65+ passed).

- [ ] **Step 3: Confirm working tree is clean and all three commits are present**

Run: `git log --oneline -4 && git status --short`
Expected: 3 new commits on top of the worktree's base, clean working tree.

---

## Self-review notes (completed during planning, not a task to execute)

- **Spec coverage:** Task 1 = breakout_base bug, Task 2 = cost-modeling gap, Task 3 = SCORING_RULES.md drift — all three user-selected Medium findings covered.
- **No placeholders:** every step has exact file:line refs and complete before/after code or exact grep/pytest commands.
- **Type/name consistency:** `_backtest_commission()` is defined once (Task 2, Step 7) and referenced identically at both call sites (Step 8); `get_costs` import added once and used only inside the new helper, matching `strategy_param_store.py`'s actual exported signature (`get_costs() -> dict`, keys `fee_pct`/`slippage_pct`, verified against source).
- **Verified against source, not assumed:** all line numbers, function signatures, and current file contents in this plan were read directly from this worktree's checkout (base commit `d6f5a43` on `origin/main`) before writing the plan — not carried over from the audit's `chore/consolidate-backend-venv`-branch line numbers, which could have drifted.
