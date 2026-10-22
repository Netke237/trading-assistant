"""Time exit at hold_max_days (STOCKS-HORIZON-T1 H2).

A trade filled on bar e (date d_e) is closed with a market order at the close of
the first bar t with (d_t - d_e).days >= hold_max_days. `backtesting` 0.6.6
puts a Trade.close() order at the FRONT of the order queue, so it fills at bar
t+1's open before the trade's stop and target are checked. Exit reason "time".

The signal function is monkeypatched on `app.services.strategy_engine` (see
tests/test_backtest_day_limits.py for why that reaches the backtest).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

import app.services.strategy_engine as strategy_engine
from app.services.strategy_backtest import (
    TradeRecord,
    run_strategy_backtest,
    run_strategy_backtest_trades,
)
from app.services.strategy_engine import StrategySignal

_SIGNAL_BAR = 100      # 0-based index of the bar whose close fires the signal
_FILL_BAR = 101        # the entry limit fills on the next bar
_CLOSE = 100.0
_ENTRY = 98.0
_STOP = 95.0
_TARGET = 104.0


def _business_days(start: date, n: int, holidays: set[date]) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bars(dates: list[date]) -> list[dict]:
    """Flat bars (99.5-100.5) that never touch the entry, the stop or the target."""
    return [
        {"time": d.isoformat(), "open": _CLOSE, "high": 100.5, "low": 99.5,
         "close": _CLOSE, "volume": 1000.0}
        for d in dates
    ]


def _patch_signal(monkeypatch, signal_bar: int = _SIGNAL_BAR) -> None:
    def _one_shot(bars, *, direction, **_kwargs):
        # Under 400 bars the backtest passes the whole history.
        if len(bars) - 1 != signal_bar:
            return None
        return StrategySignal(
            strategy="pullback_ema", direction=direction,
            entry_price=_ENTRY, stop_price=_STOP, target_price=_TARGET, atr=1.0,
        )
    monkeypatch.setattr(strategy_engine, "pullback_ema_signal", _one_shot)


def _fixture(holidays: set[date] | None = None, n: int = 150):
    # 2022-01-03 is a Monday.
    dates = _business_days(date(2022, 1, 3), n, holidays or set())
    bars = _bars(dates)
    bars[_FILL_BAR].update(low=97.5)   # the limit fills on the bar after the signal
    return dates, bars


def _run(bars, **kw):
    return run_strategy_backtest_trades(
        bars, strategy="pullback_ema", direction="Bullish", min_trades=1, **kw)


def _first_bar_at_or_after(dates: list[date], target: date) -> int:
    return next(i for i, d in enumerate(dates) if d >= target)


# (1) -----------------------------------------------------------------------

def test_time_exit_at_next_open_across_weekend_and_holiday(monkeypatch):
    _patch_signal(monkeypatch)
    base = _business_days(date(2022, 1, 3), 150, set())
    d_e = base[_FILL_BAR]
    # d_e is a Tuesday; d_e + 15 calendar days (two weekends later) is a Wednesday.
    # Make that Wednesday a holiday so the first bar dated >= it is Thursday and
    # the exit fills at Friday's open: 15 calendar days, not 15 trading bars.
    holiday = d_e + timedelta(days=15)
    dates, bars = _fixture({holiday} if holiday.weekday() < 5 else set())
    assert dates[_FILL_BAR] == d_e
    assert d_e.weekday() == 1 and holiday.weekday() == 2
    t = _first_bar_at_or_after(dates, d_e + timedelta(days=15))
    assert dates[t] > holiday            # the holiday is skipped
    exit_bar = t + 1
    bars[exit_bar].update(open=99.75)    # a distinct open to pin the fill price

    result, trades = _run(bars, hold_max_days=15)

    assert len(trades) == 1
    tr = trades[0]
    assert isinstance(tr, TradeRecord)
    assert tr.exit_reason == "time"
    assert tr.entry_date == d_e
    assert tr.exit_date == dates[exit_bar]
    assert tr.entry_price == pytest.approx(_ENTRY)
    assert tr.exit_price == pytest.approx(99.75)
    assert tr.net_return_pct == pytest.approx((99.75 / _ENTRY - 1) * 100)
    assert result.n_trades == 1
    assert result.n_time_exits == 1


def test_time_exit_dates_weekend_crossing(monkeypatch):
    """The hold counts calendar days: a fill on a Tuesday with hold 5 reaches
    Sunday; the first bar dated >= it is Monday, so the exit is Tuesday's open."""
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    d_e = dates[_FILL_BAR]
    t = _first_bar_at_or_after(dates, d_e + timedelta(days=5))
    assert d_e.weekday() == 1 and dates[t].weekday() == 0

    _, trades = _run(bars, hold_max_days=5)

    assert [tr.exit_reason for tr in trades] == ["time"]
    assert trades[0].exit_date == dates[t + 1]
    assert (dates[t] - d_e).days >= 5 > (dates[t - 1] - d_e).days


# (2) -----------------------------------------------------------------------

def _pin_bars() -> list[dict]:
    d = date(2020, 1, 1)
    out = []
    for i in range(500):
        c = 50 + i * 0.05 + 3 * math.sin(i / 6.0)
        out.append({"time": (d + timedelta(days=i)).isoformat(), "open": c * 0.998,
                    "high": c * 1.012, "low": c * 0.988, "close": c, "volume": 1000 + i})
    return out


# Values recorded with the pre-H2 code (no time exit) on _pin_bars(), commission 0.002.
_PRE_H2_PINS = {
    "mean_reversion_bb": (17, 0.4117647058823529, 19.660598754634208, -2.199281353469318, 1.102, 2.273),
    "mean_reversion_rsi": (8, 1.0, 29.57626744794728, -0.0, 3.299, 4.142),
}


@pytest.mark.parametrize("strategy", sorted(_PRE_H2_PINS))
def test_no_hold_matches_pre_h2_trades(strategy):
    for kw in ({}, {"hold_max_days": None}):
        r = run_strategy_backtest(_pin_bars(), strategy=strategy, direction="Bullish",
                                  commission=0.002, min_trades=1, **kw)
        got = (r.n_trades, r.win_rate, r.total_return_pct, r.max_drawdown_pct,
               r.expectancy, r.sharpe)
        assert got == pytest.approx(_PRE_H2_PINS[strategy], rel=1e-12, abs=1e-12)
        assert r.n_time_exits == 0


def test_no_hold_trade_records_match_result():
    result, trades = run_strategy_backtest_trades(
        _pin_bars(), strategy="mean_reversion_bb", direction="Bullish",
        commission=0.002, min_trades=1)
    assert len(trades) == result.n_trades == 17
    assert {t.exit_reason for t in trades} <= {"stop", "target"}
    wins = sum(1 for t in trades if t.net_return_pct > 0)
    assert wins / len(trades) == pytest.approx(result.win_rate)


# (3) -----------------------------------------------------------------------

def test_stop_before_limit_is_stop_not_time(monkeypatch):
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    bars[_FILL_BAR + 3].update(low=94.0)       # stop (95) hit 3 bars after the fill

    result, trades = _run(bars, hold_max_days=15)

    assert [t.exit_reason for t in trades] == ["stop"]
    assert trades[0].exit_price == pytest.approx(_STOP)
    assert trades[0].exit_date == dates[_FILL_BAR + 3]
    assert result.n_time_exits == 0


def test_target_before_limit_is_target(monkeypatch):
    _patch_signal(monkeypatch)
    _, bars = _fixture()
    bars[_FILL_BAR + 2].update(high=105.0)

    result, trades = _run(bars, hold_max_days=15)

    assert [t.exit_reason for t in trades] == ["target"]
    assert trades[0].exit_price == pytest.approx(_TARGET)
    assert result.n_time_exits == 0


# (4) -----------------------------------------------------------------------

def test_time_close_fills_before_stop_on_next_bar(monkeypatch):
    """The exit bar opens below the stop: the close order fills first, at the open."""
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    t = _first_bar_at_or_after(dates, dates[_FILL_BAR] + timedelta(days=15))
    bars[t + 1].update(open=93.0, low=92.5, high=100.5)

    result, trades = _run(bars, hold_max_days=15)

    assert [tr.exit_reason for tr in trades] == ["time"]
    assert trades[0].exit_price == pytest.approx(93.0)
    assert trades[0].exit_date == dates[t + 1]
    assert result.n_time_exits == 1


@pytest.mark.parametrize("extreme", [{"low": 94.0}, {"high": 105.0}])
def test_stop_and_target_cannot_fire_on_the_time_exit_bar(monkeypatch, extreme):
    """The exit bar trades through the stop (95) or the target (104) after
    opening at 100: the close order fills at the open first, so the fill is
    100, not the stop or target price."""
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    t = _first_bar_at_or_after(dates, dates[_FILL_BAR] + timedelta(days=15))
    bars[t + 1].update(**extreme)

    _, trades = _run(bars, hold_max_days=15)

    assert [tr.exit_reason for tr in trades] == ["time"]
    assert trades[0].exit_price == pytest.approx(_CLOSE)
    assert trades[0].exit_date == dates[t + 1]


# (5) -----------------------------------------------------------------------

def test_gap_through_stop_is_stop(monkeypatch):
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    bars[_FILL_BAR + 4].update(open=93.0, low=92.5, high=94.0)

    result, trades = _run(bars, hold_max_days=15)

    assert [t.exit_reason for t in trades] == ["stop"]
    assert trades[0].exit_price == pytest.approx(93.0)   # filled at the gap open
    assert result.n_time_exits == 0


def test_bearish_gap_through_stop_is_stop(monkeypatch):
    def _one_shot(bars, *, direction, **_kwargs):
        if len(bars) - 1 != _SIGNAL_BAR:
            return None
        return StrategySignal(strategy="pullback_ema", direction=direction,
                              entry_price=102.0, stop_price=105.0, target_price=96.0, atr=1.0)
    monkeypatch.setattr(strategy_engine, "pullback_ema_signal", _one_shot)
    dates = _business_days(date(2022, 1, 3), 150, set())
    bars = _bars(dates)
    bars[_FILL_BAR].update(high=102.5)
    bars[_FILL_BAR + 4].update(open=107.0, high=107.5, low=106.0)

    _, trades = run_strategy_backtest_trades(
        bars, strategy="pullback_ema", direction="Bearish", min_trades=1, hold_max_days=15)

    assert [t.exit_reason for t in trades] == ["stop"]
    assert trades[0].exit_price == pytest.approx(107.0)


# (6) -----------------------------------------------------------------------

def test_trade_open_at_entry_end_still_time_exits(monkeypatch):
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    entry_end = dates[_FILL_BAR + 2]
    t = _first_bar_at_or_after(dates, dates[_FILL_BAR] + timedelta(days=15))

    result, trades = _run(bars, hold_max_days=15, entry_end=entry_end)

    assert [tr.exit_reason for tr in trades] == ["time"]
    assert trades[0].exit_date == dates[t + 1] > entry_end
    assert result.n_time_exits == 1


def test_no_entry_on_or_after_entry_end(monkeypatch):
    _patch_signal(monkeypatch)
    dates, bars = _fixture()
    bars[_FILL_BAR + 2].update(high=105.0)    # would close the trade at target

    result, trades = _run(bars, hold_max_days=15, entry_end=dates[_SIGNAL_BAR])

    assert trades == []
    assert result.n_trades == 0

    # One bar later than the signal bar: the entry is placed (control).
    result, trades = _run(bars, hold_max_days=15, entry_end=dates[_SIGNAL_BAR + 1])
    assert [t.exit_reason for t in trades] == ["target"]
