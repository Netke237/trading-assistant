"""The tuner's trade simulator equals ``run_strategy_backtest_trades`` (STOCKS-HORIZON-T1 H8).

The tuner computes each signal series once (``horizon_tuning.signals``) and
simulates trades per horizon and cost (``horizon_tuning.simulate``). This file
is the gate that ties that simulator to the backtest the app runs
(``backtesting`` 0.6.6): same entry/exit dates, prices and returns within 1e-9,
same exit reasons, same count of trades still open at the end (dropped).

Two layers:

* Fast (default suite): a pairwise-covering matrix over strategy x direction x
  hold x commission x entry window x series, plus two edge series (one ending
  with a trade open, one of 99 bars).
* Full (``@pytest.mark.slow``, run by the coordinator before closing H8 with
  ``TUNING_PARITY_FULL=1``): the full product on 1,500-bar series.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import random
import warnings
from datetime import date, timedelta
from pathlib import Path

import pytest

import backtesting

from app.services.strategy_backtest import run_strategy_backtest_trades
from app.services.strategy_engine import merge_multi_params
from app.services.strategy_param_store import get_active, get_profile
from app.services.horizon_tuning.signals import signal_series
from app.services.horizon_tuning.simulate import simulate_trades

_FIXTURES = Path(__file__).parent / "fixtures"

STRATEGIES = ("pullback_ema", "breakout_base", "ma_crossover",
              "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_multi")
DIRECTIONS = ("Bullish", "Bearish")
HOLDS = (None, 15, 200)
COMMISSIONS = (0.0, 0.0005, 0.002)
WINDOWS = ("unset", "mid")
SERIES = ("trending", "choppy", "gappy", "fixture")

_TOL = 1e-9


def test_backtesting_is_the_pinned_version():
    assert backtesting.__version__ == "0.6.6"


# ── synthetic series ─────────────────────────────────────────────────────────

def _business_days(start: date, n: int, holidays: set[date] = frozenset()) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def _ohlc(dates: list[date], closes: list[float], opens: list[float], rng: random.Random) -> list[dict]:
    bars = []
    for d, o, c in zip(dates, opens, closes):
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.008)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.008)))
        bars.append({"time": d.isoformat(), "open": round(o, 4), "high": round(hi, 4),
                     "low": round(lo, 4), "close": round(c, 4),
                     "volume": float(rng.randint(500_000, 3_000_000))})
    return bars


def _trending(n: int) -> list[dict]:
    """Up for the first half, down for the second (both directions trade), in
    38-bar cycles: 25 quiet trend days, a 6-day counter-move of 2%/day, one
    small with-trend day (RSI turning while still stretched), then a 6-day
    recovery. The counter-moves are what make the mean-reversion strategies
    fire at their YAML baselines."""
    rng = random.Random(11)
    dates = _business_days(date(2015, 1, 5), n)
    closes, opens, c = [], [], 50.0
    for i in range(n):
        sign = 1 if i < n // 2 else -1
        k = i % 38
        if k < 25:
            move = sign * 0.0015
        elif k < 31:
            move = -sign * 0.02
        elif k == 31:
            move = sign * 0.003
        else:
            move = sign * 0.022
        o = c * (1 + rng.gauss(0, 0.002))
        c = o * (1 + move + rng.gauss(0, 0.006))
        opens.append(o)
        closes.append(c)
    return _ohlc(dates, closes, opens, rng)


def _choppy(n: int) -> list[dict]:
    """Mean-reverting around 100 with a slow cycle."""
    rng = random.Random(23)
    dates = _business_days(date(2015, 1, 5), n)
    closes, opens, c = [], [], 100.0
    for i in range(n):
        centre = 100 + 8 * math.sin(i / 40.0)
        o = c * (1 + rng.gauss(0, 0.003))
        c = o + 0.12 * (centre - o) + o * rng.gauss(0, 0.02)
        opens.append(o)
        closes.append(c)
    return _ohlc(dates, closes, opens, rng)


def _gappy(n: int) -> list[dict]:
    """Random walk with opening gaps of 3-8% and missing weekdays (holidays)."""
    rng = random.Random(37)
    holidays = {date(2015, 1, 5) + timedelta(days=k) for k in range(0, 4000, 23)}
    dates = _business_days(date(2015, 1, 5), n, holidays)
    closes, opens, c = [], [], 80.0
    for i in range(n):
        gap = rng.choice((-1, 1)) * rng.uniform(0.03, 0.08) if rng.random() < 0.06 else rng.gauss(0, 0.004)
        o = c * (1 + gap)
        c = o * (1 + 0.0004 * math.sin(i / 90.0) + rng.gauss(0, 0.018))
        opens.append(o)
        closes.append(c)
    return _ohlc(dates, closes, opens, rng)


def _fixture() -> list[dict]:
    return json.loads((_FIXTURES / "AAPL_candles.json").read_text(encoding="utf-8"))


def _series(name: str, n: int) -> list[dict]:
    return {"trending": _trending, "choppy": _choppy, "gappy": _gappy}[name](n) if name != "fixture" else _fixture()


# ── params, reference and simulator runs ─────────────────────────────────────

def _params(strategy: str, direction: str) -> dict:
    """The direction baseline, as the scan passes it. Multi: its merged shape
    with ``min_confirmations`` 1 -- the baseline's 2-of-3 vote almost never
    fires on these synthetic series, and the vote count is only an input of
    the shape both sides consume (two variants firing together still go
    through resolve_multi_signal's combined levels)."""
    if strategy == "mean_reversion_multi":
        return merge_multi_params(direction, get_profile(strategy, direction, None)[0],
                                  {"min_confirmations": 1})
    return get_active(strategy, direction)


def _window(bars: list[dict], window: str) -> tuple[date | None, date | None]:
    if window == "unset":
        return None, None
    n = len(bars)
    return date.fromisoformat(bars[n // 3]["time"][:10]), date.fromisoformat(bars[2 * n // 3]["time"][:10])


def _reference(bars, strategy, direction, params, *, commission, hold, entry_start, entry_end):
    """run_strategy_backtest_trades plus its dropped-open count: backtesting
    0.6.6 (finalize_trades=False) leaves a trade open at the end out of the
    stats and warns about it; one position at a time, so the count is 0 or 1."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _, trades = run_strategy_backtest_trades(
            bars, strategy=strategy, direction=direction, min_trades=1, params=params,
            commission=commission, entry_start=entry_start, hold_max_days=hold, entry_end=entry_end,
        )
    dropped = sum(1 for w in caught if "Some trades remain open" in str(w.message))
    return trades, dropped


def _assert_same(ref_trades, ref_dropped, sim, label):
    assert sim.dropped_open == ref_dropped, f"{label}: dropped-open {sim.dropped_open} != {ref_dropped}"
    assert len(sim) == len(ref_trades), f"{label}: {len(sim)} trades != reference {len(ref_trades)}"
    for k, (a, b) in enumerate(zip(sim, ref_trades)):
        where = f"{label} trade {k}"
        assert a.entry_date == b.entry_date, where
        assert a.exit_date == b.exit_date, where
        assert a.exit_reason == b.exit_reason, where
        assert math.isclose(a.entry_price, b.entry_price, rel_tol=0, abs_tol=_TOL), where
        assert math.isclose(a.exit_price, b.exit_price, rel_tol=0, abs_tol=_TOL), where
        assert math.isclose(a.net_return_pct, b.net_return_pct, rel_tol=0, abs_tol=_TOL), where


_SIG_CACHE: dict[tuple, list] = {}


def _check(series_name, n, strategy, direction, hold, commission, window, stats=None):
    bars = _series(series_name, n)
    params = _params(strategy, direction)
    key = (series_name, n, strategy, direction)
    if key not in _SIG_CACHE:
        _SIG_CACHE[key] = signal_series(bars, strategy, direction, params)
    sigs = _SIG_CACHE[key]
    assert len(sigs) == len(bars)
    entry_start, entry_end = _window(bars, window)
    ref, dropped = _reference(bars, strategy, direction, params, commission=commission, hold=hold,
                              entry_start=entry_start, entry_end=entry_end)
    sim = simulate_trades(bars, sigs, direction=direction, commission=commission, hold_max_days=hold,
                          entry_start=entry_start, entry_end=entry_end, allowed=None)
    _assert_same(ref, dropped, sim,
                 f"{series_name}/{strategy}/{direction}/hold={hold}/c={commission}/{window}")
    if stats is not None:
        stats.setdefault(strategy, 0)
        stats[strategy] += len(ref)
        for t in ref:
            stats[t.exit_reason] = stats.get(t.exit_reason, 0) + 1
    return ref


# ── pairwise-covering matrix (fast) ──────────────────────────────────────────

_FACTORS = (STRATEGIES, DIRECTIONS, HOLDS, COMMISSIONS, WINDOWS, SERIES)


def _pairs(row) -> set:
    return {(i, row[i], j, row[j]) for i, j in itertools.combinations(range(len(row)), 2)}


def _pairwise_rows() -> list[tuple]:
    """Greedy all-pairs cover, deterministic (ties: product order)."""
    candidates = list(itertools.product(*_FACTORS))
    uncovered = set().union(*(_pairs(r) for r in candidates))
    rows: list[tuple] = []
    while uncovered:
        best = max(candidates, key=lambda r: len(_pairs(r) & uncovered))
        rows.append(best)
        uncovered -= _pairs(best)
    return rows


_FAST_ROWS = _pairwise_rows()
_FAST_N = 600


def test_pairwise_rows_cover_every_pair():
    covered = set().union(*(_pairs(r) for r in _FAST_ROWS))
    full = set().union(*(_pairs(r) for r in itertools.product(*_FACTORS)))
    assert covered == full


def test_simulator_matches_backtest_pairwise():
    stats: dict = {}
    for strategy, direction, hold, commission, window, series in _FAST_ROWS:
        _check(series, _FAST_N, strategy, direction, hold, commission, window, stats)
    # Not vacuous: every strategy trades, and every exit kind occurs.
    for s in STRATEGIES:
        assert stats.get(s, 0) > 0, f"{s} produced no trades in the fast matrix"
    for reason in ("stop", "target", "time"):
        assert stats.get(reason, 0) > 0, f"no {reason} exit in the fast matrix"


def test_simulator_matches_backtest_series_ending_with_a_trade_open():
    """Cut a series inside a trade: both drop that trade and count it."""
    bars = _series("choppy", _FAST_N)
    ref, dropped = _reference(bars, "mean_reversion_bb", "Bullish", _params("mean_reversion_bb", "Bullish"),
                              commission=0.0005, hold=None, entry_start=None, entry_end=None)
    assert ref, "the series must trade for the edge case to mean anything"
    last = ref[-1]
    entry_i = next(i for i, b in enumerate(bars) if b["time"][:10] == last.entry_date.isoformat())
    cut = bars[: entry_i + 2]           # filled on entry_i, still open two bars later
    exit_i = next(i for i, b in enumerate(bars) if b["time"][:10] == last.exit_date.isoformat())
    assert exit_i > entry_i + 1, "pick a trade that lasts more than one bar"
    params = _params("mean_reversion_bb", "Bullish")
    ref2, dropped2 = _reference(cut, "mean_reversion_bb", "Bullish", params,
                                commission=0.0005, hold=None, entry_start=None, entry_end=None)
    assert dropped2 == 1
    sim = simulate_trades(cut, signal_series(cut, "mean_reversion_bb", "Bullish", params),
                          direction="Bullish", commission=0.0005, hold_max_days=None,
                          entry_start=None, entry_end=None, allowed=None)
    _assert_same(ref2, dropped2, sim, "open-at-end")
    assert sim.dropped_open == 1


def test_simulator_matches_backtest_on_99_bars():
    bars = _series("trending", 99)
    params = _params("pullback_ema", "Bullish")
    ref, dropped = _reference(bars, "pullback_ema", "Bullish", params,
                              commission=0.0, hold=15, entry_start=None, entry_end=None)
    sim = simulate_trades(bars, signal_series(bars, "pullback_ema", "Bullish", params),
                          direction="Bullish", commission=0.0, hold_max_days=15,
                          entry_start=None, entry_end=None, allowed=None)
    assert ref == [] and dropped == 0
    _assert_same(ref, dropped, sim, "99 bars")
    assert list(sim) == [] and sim.dropped_open == 0


def test_allowed_mask_blocks_entries_on_its_false_bars():
    bars = _series("choppy", _FAST_N)
    params = _params("mean_reversion_bb", "Bullish")
    sigs = signal_series(bars, "mean_reversion_bb", "Bullish", params)
    kw = dict(direction="Bullish", commission=0.0005, hold_max_days=15, entry_start=None, entry_end=None)
    free = simulate_trades(bars, sigs, allowed=None, **kw)
    assert free
    assert list(simulate_trades(bars, sigs, allowed=[True] * len(bars), **kw)) == list(free)
    assert list(simulate_trades(bars, sigs, allowed=[False] * len(bars), **kw)) == []
    # Block the signal bar of the first trade (the bar before its fill): that trade is gone.
    fill_i = next(i for i, b in enumerate(bars) if b["time"][:10] == free[0].entry_date.isoformat())
    allowed = [True] * len(bars)
    allowed[fill_i - 1] = False
    blocked = simulate_trades(bars, sigs, allowed=allowed, **kw)
    assert all(t.entry_date != free[0].entry_date for t in blocked)


# ── full product (slow) ──────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("TUNING_PARITY_FULL") != "1",
                    reason="full parity product: set TUNING_PARITY_FULL=1 (coordinator, before closing H8)")
def test_simulator_matches_backtest_full_product():
    stats: dict = {}
    for strategy, direction, hold, commission, window, series in itertools.product(*_FACTORS):
        _check(series, 1500, strategy, direction, hold, commission, window, stats)
    for s in STRATEGIES:
        assert stats.get(s, 0) > 0
