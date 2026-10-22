"""One signal series per (bars, strategy, direction, params) — STOCKS-HORIZON-T1 H8.

Signals do not depend on the hold or the cost, so the tuner computes each
series once and simulates trades per horizon and cost (``simulate.py``).
``signal_series`` reproduces exactly what ``strategy_backtest._run_backtest``'s
``next()`` hands the signal function on every bar: nothing before the 60th
bar, the last ``SIGNAL_WINDOW_BARS`` bars (350 for the intraday
``mean_reversion_vwap``), float OHLCV dicts without a ``time`` key, and the
``exit:`` block merged under ``params`` (``mean_reversion_multi``: ``params`` is
already the merged multi shape, H3). The parity test is the judge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.services.strategy_backtest import normalize_direction

# strategy_backtest._run_backtest: `if n < 60: return` before any signal.
MIN_SIGNAL_BARS = 60
# strategy_backtest._INTRADAY_SIGNAL_WINDOW (mean_reversion_vwap only).
_INTRADAY_WINDOW = 350


@dataclass(frozen=True)
class SignalPoint:
    entry: float
    stop: float
    target: float
    market: bool = False
    rr_multiple: float | None = None
    setup_age: int = 0


def effective_params(strategy: str, params: dict | None) -> dict:
    """The params the signal function actually receives, as the backtest
    builds them: ``get_exit(strategy)`` under ``params``; for
    ``mean_reversion_multi`` ``params`` itself (the merged shape)."""
    if strategy in ("breakout_setup", "fibonacci_pullback"):
        from app.services.setup_entries import setup_params
        return setup_params(strategy, params)
    from app.services.strategy_param_store import get_exit
    if strategy == "mean_reversion_multi":
        return dict(params or {})
    return {**get_exit(strategy), **(params or {})}


def _signal_fn(strategy: str) -> Callable:
    """The backtest's strategy -> function map, looked up at call time (a
    monkeypatched strategy_engine function reaches both)."""
    from app.services import strategy_engine as se
    if strategy == "mean_reversion_multi":
        return lambda bars, *, direction, **shape: se.multi_signal(bars, direction=direction, params=shape)
    fns = {
        "pullback_ema":              se.pullback_ema_signal,
        "breakout_base":             se.breakout_base_signal,
        "ma_crossover":              se.ma_crossover_signal,
        "mean_reversion_rsi":        se.mean_reversion_rsi_signal,
        "mean_reversion_bb":         se.mean_reversion_bb_signal,
        "mean_reversion_vwap":       se.mean_reversion_vwap_signal,
        "mean_reversion_vwap_daily": se.mean_reversion_vwap_daily_signal,
    }
    if strategy not in fns:
        raise ValueError(f"signal_series: unknown strategy {strategy!r}")
    return fns[strategy]


def signal_series(bars: list[dict], strategy: str, direction: str,
                  params: dict | None) -> list[SignalPoint | None]:
    """One entry per bar: the signal the backtest would compute at that bar's
    close (``None`` = no signal). A signal function that raises propagates
    (the backtest would fail the whole run)."""
    if strategy in ("breakout_setup", "fibonacci_pullback"):
        from app.services.setup_entries import setup_series
        return setup_series(bars, strategy, direction, params)
    from app.services.strategy_engine import SIGNAL_WINDOW_BARS
    direction = normalize_direction(direction)
    fn = _signal_fn(strategy)
    eff = effective_params(strategy, params)
    window = _INTRADAY_WINDOW if strategy == "mean_reversion_vwap" else SIGNAL_WINDOW_BARS
    # The backtest rebuilds these dicts every bar from its float arrays; the
    # signal functions do not mutate their input, so one list is sliced.
    clean = [
        {"open": float(b["open"]), "high": float(b["high"]), "low": float(b["low"]),
         "close": float(b["close"]), "volume": float(b["volume"])}
        for b in bars
    ]
    out: list[SignalPoint | None] = [None] * len(bars)
    for t in range(MIN_SIGNAL_BARS - 1, len(bars)):
        n = t + 1
        sig = fn(clean[max(0, n - window):n], direction=direction, **eff)
        if sig is not None:
            out[t] = SignalPoint(float(sig.entry_price), float(sig.stop_price), float(sig.target_price))
    return out
