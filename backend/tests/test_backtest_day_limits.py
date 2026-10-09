"""DAY semantics for backtest entry limits (TRADING-REVIEW-PHASE-C T6, review M3).

Live entries are DAY orders: a limit placed after bar t closes is working on
bar t+1 only. `backtesting` 0.6.6 keeps an unfilled limit alive until it fills
(with `exclusive_orders=True` it is cancelled only when a NEW order is placed),
so a stale limit from bar t could fill on bar t+5. These tests pin that the
backtest entry limit lives exactly one bar, and that the contingent SL/TP of an
open trade are never swept by that cancellation.

The signal function is monkeypatched on `app.services.strategy_engine`:
`run_strategy_backtest` imports the signal functions at call time, so the patched
attribute is what its strategy map picks up.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.services.strategy_engine as strategy_engine
from app.services.strategy_backtest import run_strategy_backtest
from app.services.strategy_engine import StrategySignal

_SIGNAL_BAR = 100      # 0-based index of the one bar whose close fires the signal
_CLOSE = 100.0
_ENTRY = 98.0          # 2% below the signal bar's close
_STOP = 95.0
_TARGET = 101.5


def _flat_bars(n: int = 150) -> list[dict]:
    """Flat bars on unique sequential dates; range 99.5-100.5 never reaches the
    entry limit, the stop or the target."""
    d0 = date(2022, 1, 3)
    return [
        {"time": (d0 + timedelta(days=i)).isoformat(),
         "open": _CLOSE, "high": 100.5, "low": 99.5, "close": _CLOSE,
         "volume": 1000.0}
        for i in range(n)
    ]


def _patch_signal(monkeypatch) -> None:
    """Fire one bullish limit signal after bar `_SIGNAL_BAR` closes, never again."""
    def _one_shot(bars, *, direction, **_kwargs):
        # With fewer than 350 bars the backtest passes the whole history, so
        # len(bars) - 1 is the index of the bar that just closed.
        if len(bars) - 1 != _SIGNAL_BAR:
            return None
        return StrategySignal(
            strategy="pullback_ema", direction=direction,
            entry_price=_ENTRY, stop_price=_STOP, target_price=_TARGET, atr=1.0,
        )
    monkeypatch.setattr(strategy_engine, "pullback_ema_signal", _one_shot)


def _run(bars):
    return run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish",
                                 min_trades=1)


def test_stale_entry_limit_does_not_fill_after_its_day(monkeypatch):
    _patch_signal(monkeypatch)
    bars = _flat_bars()
    # Bars 101-102 stay above the 98.0 limit (default low 99.5).
    # Bar 103 trades through it: without DAY semantics the stale limit fills here.
    bars[103].update(low=97.0)
    # Target reachable later, so a (wrong) stale fill would close as a counted trade.
    bars[108].update(high=102.0)

    result = _run(bars)

    assert result.n_trades == 0


def test_entry_limit_touched_on_next_bar_fills(monkeypatch):
    _patch_signal(monkeypatch)
    bars = _flat_bars()
    bars[101].update(low=97.5)     # the bar right after the signal touches the limit
    bars[108].update(high=102.0)   # target hit later, so the trade closes

    result = _run(bars)

    assert result.n_trades == 1


def test_contingent_sl_tp_of_open_trade_are_not_cancelled(monkeypatch):
    _patch_signal(monkeypatch)
    bars = _flat_bars()
    bars[101].update(low=97.5)     # entry fills at the 98.0 limit
    bars[106].update(high=102.0)   # target 101.5 hit 5 bars later

    result = _run(bars)

    # The trade closed (so its TP order survived the per-bar cancellation)
    # and it closed at the target, not the stop.
    assert result.n_trades == 1
    assert result.win_rate == 1.0
    assert result.expectancy == pytest.approx((_TARGET / _ENTRY - 1.0) * 100.0, abs=1e-3)
