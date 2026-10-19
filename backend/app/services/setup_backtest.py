"""Research-only setup backtests using confirmed events and market fills."""
from __future__ import annotations

import math
import pandas as pd
from app.services.strategy_backtest import BacktestResult, _empty_result, _window_stats, normalize_direction
from app.services.setup_entries import setup_params
from app.services.horizon_tuning.signals import signal_series
from app.services.horizon_tuning.simulate import simulate_trades


def run_setup_backtest(bars, *, strategy, direction, min_trades=10,
                       min_win_rate=.45, params=None, commission=0.,
                       entry_start=None, entry_end=None, hold_max_days=None):
    direction = normalize_direction(direction)
    p = setup_params(strategy, params)  # Malformed parameters fail explicitly.
    if len(bars) < 100:
        return _empty_result(strategy, direction, 'Insufficient bars — need 100'), []
    if not isinstance(commission, (int, float)) or not math.isfinite(commission) or not -.1 <= commission < .1:
        return _empty_result(strategy, direction, 'Invalid commission'), []
    if hold_max_days is not None and (type(hold_max_days) is not int or hold_max_days < 1):
        raise ValueError('hold_max_days must be a positive integer or None')
    if any('time' not in b for b in bars):
        raise ValueError('setup backtest requires dated daily bars')
    times = pd.DatetimeIndex(pd.to_datetime([b['time'] for b in bars]))
    if times.hasnans or not times.is_monotonic_increasing or len(set(times.date)) != len(times):
        raise ValueError('setup backtest requires ascending unique daily bars')
    signals = signal_series(bars, strategy, direction, p)
    trades = simulate_trades(bars, signals, direction=direction, commission=commission,
                             hold_max_days=hold_max_days, entry_start=entry_start,
                             entry_end=entry_end, dates=list(times.date))
    eq = pd.Series(trades.equity_curve, index=times)
    if entry_start is not None:
        cutoff = pd.Timestamp(entry_start)
        if eq.index.tz is not None:
            cutoff = cutoff.tz_localize(eq.index.tz)
        eq = eq[eq.index >= cutoff]
    total, dd, sharpe = _window_stats(eq)
    count = len(trades)
    win_rate = sum(t.net_return_pct > 0 for t in trades)/count if count else 0.
    expectancy = sum(t.net_return_pct for t in trades)/count if count else 0.
    passes = count >= min_trades and win_rate >= min_win_rate and expectancy >= 0.
    result = BacktestResult(strategy, direction, count, win_rate, total, dd,
                            round(expectancy, 3), round(sharpe, 3),
                            min(100, max(0, round(win_rate*100))) if count >= min_trades else None,
                            passes, f'{count} research trades; {trades.dropped_open} final open trades dropped',
                            sum(t.exit_reason == 'time' for t in trades))
    return result, trades
