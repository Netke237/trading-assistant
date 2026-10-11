"""STOCKS-HORIZON-T1 H1: one 400-bar signal window everywhere a daily-bar
strategy signal is computed (live scan single + multi, strategy watch entry and
reversal, daily composite confirmations, the backtest's per-bar slice), and
`bars_needed`, the smallest bar count at which a signal's length guards pass.

Before H1 the live paths handed a strategy only 120 bars, so
`mean_reversion_rsi` (needs 219 at defaults) and `mean_reversion_bb` (225)
could never fire live while Step 6 showed backtest trades for them.
"""
from __future__ import annotations

import asyncio
import itertools
import math
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

import app.services.strategy_engine as se
from app.schemas.stock_scan import StockScanRequest

_SERIES_LEN = 600


# ── synthetic series ─────────────────────────────────────────────────────────

def _mk(closes: list[float], vols: list[float] | None = None) -> list[dict]:
    d0 = date(2022, 1, 3)
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append({"time": (d0 + timedelta(days=i)).isoformat(), "open": o,
                    "high": max(o, c) * 1.002, "low": min(o, c) * 0.998,
                    "close": c, "volume": vols[i] if vols else 1_000_000.0})
    return out


def _mean_reversion_series(n: int = _SERIES_LEN) -> list[dict]:
    """A zig-zag uptrend, a sharp pullback, a big drop on bar -2 (its low pierces
    the lower Bollinger band) and an uptick on the last bar: both
    mean_reversion_rsi (RSI14 < 30 and ticking up, close > SMA200) and
    mean_reversion_bb (close back inside the lower band, below the mid-band)
    fire Bullish at defaults on the last bar — given at least 219 / 225 bars."""
    closes, p = [], 100.0
    for i in range(n - 8):
        p *= 1.004 if i % 3 else 0.999
        closes.append(p)
    for _ in range(6):
        p *= 0.985
        closes.append(p)
    p *= 0.97
    closes.append(p)
    p *= 1.016
    closes.append(p)
    return _mk(closes)


def _pullback_series(n: int = 300) -> list[dict]:
    closes, p = [], 100.0
    for i in range(n - 4):
        p *= 1.004 if i % 3 else 0.999
        closes.append(p)
    for _ in range(4):
        p *= 0.99
        closes.append(p)
    vols = [1_000_000.0] * n
    for j in range(1, 5):
        vols[-j] = 500_000.0       # volume contracts on the pullback
    return _mk(closes, vols)


def _breakout_series(n: int = 60) -> list[dict]:
    closes = [100.0 + (0.3 if i % 2 else -0.3) for i in range(n - 1)] + [100.9]
    vols = [1_000_000.0] * (n - 1) + [3_000_000.0]
    return _mk(closes, vols)


def _cross_series(n: int = 120) -> list[dict]:
    closes, p = [], 100.0
    for _ in range(n - 14):
        p *= 0.997
        closes.append(p)
    for _ in range(14):
        p *= 1.03
        closes.append(p)
    return _mk(closes)


def _vwap_daily_series(n: int = 40) -> list[dict]:
    return _mk([100.0 + (0.2 if i % 2 else -0.2) for i in range(n - 2)] + [97.0, 100.5])


# ── (5) bars_needed both ways ────────────────────────────────────────────────

_BOTH_WAYS = [
    ("pullback_ema", _pullback_series, se.pullback_ema_signal, {}),
    ("breakout_base", _breakout_series, se.breakout_base_signal, {}),
    ("ma_crossover", _cross_series, se.ma_crossover_signal, {}),
    ("mean_reversion_rsi", _mean_reversion_series, se.mean_reversion_rsi_signal, {}),
    ("mean_reversion_bb", _mean_reversion_series, se.mean_reversion_bb_signal, {}),
    ("mean_reversion_vwap_daily", _vwap_daily_series, se.mean_reversion_vwap_daily_signal, {}),
]


@pytest.mark.parametrize("strategy,build,fn,params", _BOTH_WAYS, ids=[c[0] for c in _BOTH_WAYS])
def test_bars_needed_is_exactly_the_length_guard(strategy, build, fn, params):
    need = se.bars_needed(strategy, params)
    bars = build()
    assert len(bars) > need
    assert fn(bars[-need:], direction="Bullish", **params) is not None, (
        f"{strategy}: with exactly bars_needed={need} bars the signal must be able to fire")
    assert fn(bars[-(need - 1):], direction="Bullish", **params) is None, (
        f"{strategy}: with bars_needed-1={need - 1} bars a length guard must refuse")


def test_bars_needed_at_defaults():
    assert se.SIGNAL_WINDOW_BARS == 400
    assert se.bars_needed("pullback_ema", {}) == 110
    assert se.bars_needed("breakout_base", {}) == 25
    assert se.bars_needed("ma_crossover", {}) == 60          # slow + max(5, lookback)
    assert se.bars_needed("mean_reversion_rsi", {}) == 219
    assert se.bars_needed("mean_reversion_bb", {}) == 225
    assert se.bars_needed("mean_reversion_vwap_daily", {}) == 22
    assert se.bars_needed("ma_crossover", {"slow": 100, "lookback": 3}) == 105
    assert se.bars_needed("pullback_ema", {"trend_ema": 200}) == 210


def test_bars_needed_multi_is_the_max_over_its_variants():
    params = {"variants": ["mean_reversion_rsi", "mean_reversion_bb"],
              "variant_params": {"mean_reversion_rsi": {"trend_sma": 100}}}
    assert se.bars_needed("mean_reversion_multi", params) == 225   # bb at 200+20+5
    params["variant_params"]["mean_reversion_bb"] = {"trend_sma": 100}
    assert se.bars_needed("mean_reversion_multi", params) == 125   # bb 100+20+5 > rsi 100+14+5


def test_bars_needed_multi_both_ways_through_the_scan_loop():
    """`_multi_signal` with rsi + bb, both required: fires on exactly
    bars_needed bars, not on one fewer."""
    from app.routers.stock_scan import _multi_signal

    req = StockScanRequest(universe=["AAA"], direction="Bullish", horizon="Swing",
                           strategy="mean_reversion_multi",
                           mean_reversion_variants=["mean_reversion_rsi", "mean_reversion_bb"],
                           mean_reversion_min_confirmations=2)
    need = se.bars_needed("mean_reversion_multi",
                          {"variants": ["mean_reversion_rsi", "mean_reversion_bb"]})
    bars = _mean_reversion_series()
    sig, drop = _multi_signal("AAA", req, bars[-need:])
    assert drop is None and sig is not None
    sig, drop = _multi_signal("AAA", req, bars[-(need - 1):])
    assert sig is None and drop is not None


# ── (6) every current search combination fits the window ─────────────────────

def test_every_search_combination_fits_the_signal_window():
    doc = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "strategy_params.yaml")
                         .read_text(encoding="utf-8"))
    checked = 0
    for strategy, block in doc["strategies"].items():
        search = (block or {}).get("search")
        if not search:
            continue
        keys = list(search)
        for combo in itertools.product(*(search[k] for k in keys)):
            for direction in ("bullish", "bearish"):
                params = {**(block.get("active", {}).get(direction) or {}), **dict(zip(keys, combo))}
                need = se.bars_needed(strategy, params)
                assert need <= se.SIGNAL_WINDOW_BARS, (strategy, params, need)
                checked += 1
    assert checked > 0


# ── (1)/(2) the live scan fires on the 600-bar series ────────────────────────

def _pass_card():
    from app.scoring.stock_scorer import RuleResult, StockScoreCard
    return StockScoreCard(symbol="AAA", direction="Bullish", horizon="Swing", score=72,
                          status="PASS", rules=[RuleResult("trend", "PASS", 90, {})])


def _pass_bt(strategy: str):
    from app.services.strategy_backtest import BacktestResult
    return BacktestResult(strategy=strategy, direction="Bullish", n_trades=12, win_rate=0.6,
                          total_return_pct=10.0, max_drawdown_pct=5.0, expectancy=0.5,
                          sharpe=1.0, confidence=60, passes_gate=True, summary_text="PASS")


def _scan_one(strategy: str, bars: list[dict]):
    from app.routers import stock_scan as ss

    req = StockScanRequest(universe=["AAA"], direction="Bullish", horizon="Swing", strategy=strategy)

    async def run():
        with patch.object(ss, "get_historical_bars", AsyncMock(return_value=bars)), \
             patch.object(ss, "score_stock", MagicMock(return_value=_pass_card())), \
             patch.object(ss, "compute_omm", return_value=None), \
             patch.object(ss, "run_strategy_backtest", return_value=_pass_bt(strategy)), \
             patch.object(ss, "_get_backtest_cached", return_value=None), \
             patch.object(ss, "_BACKTEST_POOL", None), \
             patch.object(ss, "fetch_company_name_async", AsyncMock(return_value="Test")), \
             patch.object(ss, "fetch_price_async", AsyncMock(return_value=None)), \
             patch.object(ss, "_earnings_days_for", AsyncMock(return_value=None)), \
             patch.object(ss, "get_cached", return_value={"confidence": 60, "sample_size": 40}), \
             patch.object(ss, "set_cached", AsyncMock(return_value=None)):
            return await ss._process_stock("AAA", req, "scan-h1", {}, [])

    return asyncio.run(run())


@pytest.mark.parametrize("strategy", ["mean_reversion_rsi", "mean_reversion_bb"])
def test_live_scan_fires_mean_reversion_at_defaults(strategy):
    bars = _mean_reversion_series()
    result = _scan_one(strategy, bars)
    assert not isinstance(result, dict), f"{strategy} was dropped: {result}"
    assert result.strategy.strategy == strategy


# ── (3) composite confirmations: daily keys get the window, intraday keeps 120 ─

def test_composite_daily_rsi_and_bb_match_on_the_series():
    from app.services.composite_trigger_evaluator import _matched_strategy_signals

    bars = _mean_reversion_series()
    seen: list[int] = []
    real = se.mean_reversion_rsi_signal

    def spy(b, **kw):
        seen.append(len(b))
        return real(b, **kw)

    with patch.object(se, "mean_reversion_rsi_signal", spy):
        matched = _matched_strategy_signals(
            ["mean_reversion_rsi", "mean_reversion_bb"], bars, [], "Bullish")
    assert matched == ["mean_reversion_rsi", "mean_reversion_bb"]
    assert seen and max(seen) == se.SIGNAL_WINDOW_BARS


def _intraday_vwap_series() -> list[dict]:
    """15-min bars where a 120-bar anchored VWAP sits ~2% above the last close
    (fires Bullish) but a 400-bar one sits below it (would not fire)."""
    closes = [90.0] * 280 + [100.0] * 118 + [97.5, 97.9]
    out = []
    t0 = 1_700_000_000
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append({"time": t0 + 900 * i, "open": o, "high": max(o, c) + 0.05,
                    "low": min(o, c) - 0.05, "close": c, "volume": 10_000.0})
    return out


def test_composite_intraday_vwap_keeps_its_120_bar_window():
    from app.services.composite_trigger_evaluator import _matched_strategy_signals

    bars = _intraday_vwap_series()
    seen: list[int] = []
    real = se.mean_reversion_vwap_signal

    def spy(b, **kw):
        seen.append(len(b))
        return real(b, **kw)

    with patch.object(se, "mean_reversion_vwap_signal", spy):
        matched = _matched_strategy_signals(
            ["mean_reversion_vwap"], [], bars, "Bullish", interval="15m")
    # Pinned before H1 and unchanged after it.
    assert matched == ["mean_reversion_vwap"]
    assert seen and max(seen) == 120


# ── (4) backtest under 350 bars: unchanged, never a negative index ───────────

def _wave(n: int = 150) -> list[dict]:
    d0 = date(2022, 1, 3)
    out = []
    for i in range(n):
        c = 100 + 8 * math.sin(i / 5.0) + 0.05 * i
        o = 100 + 8 * math.sin((i - 1) / 5.0) + 0.05 * (i - 1) if i else c
        out.append({"time": (d0 + timedelta(days=i)).isoformat(), "open": round(o, 4),
                    "high": round(max(o, c) + 0.6, 4), "low": round(min(o, c) - 0.6, 4),
                    "close": round(c, 4), "volume": 1_000_000.0})
    return out


def test_short_backtest_is_unchanged_and_slices_from_bar_zero():
    from app.services.strategy_backtest import run_strategy_backtest

    seen: list[int] = []
    real = se.ma_crossover_signal

    def spy(b, **kw):
        seen.append(len(b))
        return real(b, **kw)

    with patch.object(se, "ma_crossover_signal", spy):
        r = run_strategy_backtest(_wave(), strategy="ma_crossover", direction="Bullish",
                                  min_trades=1, params={"fast": 3, "slow": 10, "lookback": 2})
    # Every call saw exactly the history so far (bars 60..150, one call per bar
    # at most): a negative slice start would have handed it more than n bars.
    assert seen and seen[0] == 60
    assert all(60 <= n <= 150 for n in seen)
    assert seen == sorted(set(seen))
    # Pinned from the pre-H1 code (350-bar cap): identical trades.
    assert r.n_trades == 3
    assert r.win_rate == 1.0
    assert r.total_return_pct == pytest.approx(20.8473751)
    assert r.expectancy == 6.518
    assert r.sharpe == 4.426


def test_long_backtest_slices_at_most_the_signal_window():
    from app.services.strategy_backtest import run_strategy_backtest

    seen: list[int] = []

    def spy(b, **kw):
        seen.append(len(b))
        return None

    with patch.object(se, "mean_reversion_rsi_signal", spy):
        run_strategy_backtest(_mean_reversion_series(), strategy="mean_reversion_rsi",
                              direction="Bullish", min_trades=1)
    assert max(seen) == se.SIGNAL_WINDOW_BARS


# ── (7) strategy watch entry and reversal receive at most 400 bars ───────────

def _watch(phase: str, **state):
    base = {"phase": phase, "direction": None, "entry_price": None, "stop_price": None,
            "target_price": None, "last_event": None, "last_event_at": None}
    base.update(state)
    return {"id": "wch_h1", "symbol": "AAA", "strategy_key": "mean_reversion_rsi",
            "params_override": {}, "enabled": True, "last_state": base}


@pytest.mark.parametrize("phase", ["idle", "armed"])
def test_watch_entry_and_reversal_calls_receive_the_signal_window(phase):
    from app.services.strategy_watch_evaluator import evaluate_all

    bars = _mean_reversion_series()
    last_close = bars[-1]["close"]
    calls: list[tuple[str, int, dict]] = []

    def spy(b, direction, **kw):
        calls.append((direction, len(b), b[-1]))
        return None

    state = {} if phase == "idle" else {
        "direction": "Bullish", "entry_price": last_close,
        "stop_price": last_close * 0.5, "target_price": last_close * 2}
    store = MagicMock()
    store.list_watches.return_value = [_watch(phase, **state)]

    async def run():
        with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
             patch("app.services.strategy_watch_evaluator.get_bars",
                   new_callable=AsyncMock, return_value=bars), \
             patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                        {"mean_reversion_rsi": spy}):
            return await evaluate_all()

    asyncio.run(run())
    directions = {d for d, _, _ in calls}
    assert directions == ({"Bullish"} if phase == "idle" else {"Bullish", "Bearish"})
    for _, n, last in calls:
        assert n == se.SIGNAL_WINDOW_BARS
        assert last is bars[-1]
