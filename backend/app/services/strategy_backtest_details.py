"""Detached, serializable evidence from backtesting.py 0.6.6.

Timestamps are epoch seconds UTC. Naive source timestamps are interpreted as
UTC, retaining their wall-clock value; timezone-aware times retain their instant.
The benchmark is a gross long close-price index, excluding fees. Equity includes
mark-to-market open positions, while summary trade counts include closed trades.
"""
from __future__ import annotations

import copy
import inspect
import math
from numbers import Real
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from app.services.strategy_backtest import BacktestResult

ENGINE_CONTRACT_VERSION = "backtesting-0.6.6-v2"

DetailStatus = Literal["success", "unsupported", "insufficient_history", "invalid_input", "failed", "invalid_evidence"]


@dataclass(frozen=True)
class BacktestCandle:
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class EquitySample:
    time: float
    equity: float
    strategy_index: float
    benchmark_index: float


@dataclass(frozen=True)
class DetailedTrade:
    id: str
    direction: str
    entry_time: float
    exit_time: float
    entry_price: float
    exit_price: float
    size: int
    net_return_pct: float
    commission: float
    exit_reason: Literal["time", "unknown"]


@dataclass(frozen=True)
class OpenPosition:
    """Engine trade.pl is gross unrealized P&L; equity includes entry fees."""
    id: str
    direction: str
    entry_time: float
    entry_price: float
    size: int
    unrealized_pnl: float


@dataclass(frozen=True)
class DetailedBacktestResult:
    summary: BacktestResult
    status: DetailStatus
    reason: str | None = None
    input_candles: tuple[BacktestCandle, ...] = ()
    candles: tuple[BacktestCandle, ...] = ()
    equity: tuple[EquitySample, ...] = ()
    trades: tuple[DetailedTrade, ...] = ()
    open_positions: tuple[OpenPosition, ...] = ()
    initial_equity: float | None = None
    configuration: dict = field(default_factory=dict)
    effective_params: dict = field(default_factory=dict)
    engine_contract_version: str = ENGINE_CONTRACT_VERSION
    time_basis: str = "UTC epoch seconds; naive input interpreted UTC"


def epoch(value) -> float:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("missing timestamp")
    return float(timestamp.tz_localize("UTC").timestamp() if timestamp.tzinfo is None else timestamp.timestamp())


def validate_frame(df: pd.DataFrame) -> None:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("detailed evidence needs dated bars")
    times = [epoch(t) for t in df.index]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("bar timestamps must be unique and chronological")
    if not all(math.isfinite(float(v)) for v in df.to_numpy().flat):
        raise ValueError("nonfinite OHLCV")
    if (df[["Open", "High", "Low", "Close"]] <= 0).any().any():
        raise ValueError("prices must be positive")
    if ((df.High < df[["Open", "Close", "Low"]].max(axis=1))
            | (df.Low > df[["Open", "Close", "High"]].min(axis=1))
            | (df.Volume < 0)).any():
        raise ValueError("invalid OHLCV range")


def source_frame(bars):
    """Validate source time independently of the unchanged legacy engine parser."""
    frame = pd.DataFrame(bars).rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume"})
    values = frame["time"].tolist()
    numeric = [isinstance(v, Real) and not isinstance(v, bool) for v in values]
    if any(numeric) and not all(numeric):
        raise ValueError("mixed numeric and dated source timestamps")
    if all(numeric):
        times = [float(v) for v in values]
        frame.index = pd.to_datetime(times, unit="s", utc=True)
    else:
        times = [epoch(v) for v in values]
        frame.index = pd.DatetimeIndex([pd.Timestamp(v) for v in values])
    if not all(math.isfinite(t) for t in times):
        raise ValueError("nonfinite source timestamps")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("source timestamps must be unique and chronological")
    frame = frame[["Open", "High", "Low", "Close", "Volume"]]
    validate_frame(frame)
    return frame, times, all(numeric)


def complete_effective_params(signal_fn, effective_params, *, variant_fns=None):
    """Freeze defaults actually used by the signal, without changing engine kwargs."""
    def resolved(fn, overrides):
        defaults = {
            name: parameter.default
            for name, parameter in inspect.signature(fn).parameters.items()
            if name not in {"bars", "direction"}
            and parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                   inspect.Parameter.KEYWORD_ONLY)
            and parameter.default is not inspect.Parameter.empty
        }
        return {**defaults, **overrides}

    if variant_fns is None:
        return copy.deepcopy(resolved(signal_fn, effective_params))
    # Multi's top-level configuration is explicit in the actual engine call;
    # only selected variants' function defaults supplement their frozen kwargs.
    result = copy.deepcopy(effective_params)
    variant_params = effective_params.get("variant_params") or {}
    result["variant_params"] = {
        name: (resolved(variant_fns[name], variant_params.get(name) or {})
               if name in variant_fns else dict(variant_params.get(name) or {}))
        for name in effective_params["variants"]
    }
    return copy.deepcopy(result)


def collect_details(summary, stats, df, *, source_bars, entry_start, entry_end, hold_max_days,
                    commission, effective_params, time_closed, signal_fn, variant_fns,
                    min_trades, min_win_rate, min_expectancy, signal_window_bars):
    """Read this run's real equity/fills; any invalid evidence fails as a unit."""
    source, source_times, numeric = source_frame(source_bars)
    input_candles = tuple(BacktestCandle(t, *(float(v) for v in row))
                          for t, row in zip(source_times, source.to_numpy()))
    eq = stats["_equity_curve"]["Equity"]
    if not eq.index.equals(df.index):
        raise ValueError("equity/candle timestamp mismatch")
    if len(source) != len(df):
        raise ValueError("source/engine bar count mismatch")
    if (numeric and any(v is not None for v in (entry_start, entry_end, hold_max_days))
            and list(source.index.date) != list(df.index.date)):
        raise ValueError("source/legacy engine timing guard mismatch")

    def fill_time(position):
        bar = int(position)
        if bar != position or not 0 <= bar < len(source_times):
            raise ValueError("invalid engine fill bar position")
        return source_times[bar]

    # Keep the engine index check above before replacing its display timestamps.
    # The engine itself still runs on its legacy index, preserving all statistics.
    eq = eq.copy()
    eq.index = source.index
    df = source
    visible_times = source_times
    if entry_start is not None:
        cutoff = pd.Timestamp(entry_start)
        if df.index.tz is not None:
            cutoff = cutoff.tz_localize(df.index.tz)
        mask = df.index >= cutoff
        visible_times = [t for t, keep in zip(source_times, mask) if keep]
        df, eq = df[mask], eq[mask]
    if not len(eq):
        raise ValueError("empty evaluation window")
    # Existing no-window engine Return[%] uses initial broker cash. Windowed
    # summaries use the first equity sample, exactly as _window_stats does.
    baseline = float(eq.iloc[0]) if entry_start is not None else 100_000.
    if baseline <= 0 or not all(math.isfinite(float(v)) for v in eq):
        raise ValueError("invalid equity baseline/samples")
    for key in ("win_rate", "total_return_pct", "max_drawdown_pct", "expectancy", "sharpe"):
        if not math.isfinite(getattr(summary, key)):
            raise ValueError("nonfinite summary")
    if not math.isclose((float(eq.iloc[-1]) / baseline - 1) * 100, summary.total_return_pct, abs_tol=1e-9):
        raise ValueError("equity does not reconcile with summary return")
    candles = tuple(BacktestCandle(t, *(float(v) for v in row))
                    for t, row in zip(visible_times, df.to_numpy()))
    benchmark_baseline = float(df.Close.iloc[0])
    equity = tuple(EquitySample(t, float(v), 100 * float(v) / baseline,
                               100 * float(close) / benchmark_baseline)
                   for t, v, close in zip(visible_times, eq, df.Close))
    if not all(math.isfinite(v) for sample in equity
               for v in (sample.time, sample.equity, sample.strategy_index, sample.benchmark_index)):
        raise ValueError("nonfinite indexed series")
    trades = []
    for i, row in enumerate(stats["_trades"].itertuples(index=False)):
        values = [row.EntryPrice, row.ExitPrice, row.ReturnPct, row.Commission, row.Size]
        if not all(math.isfinite(float(v)) for v in values):
            raise ValueError("nonfinite fill")
        trades.append(DetailedTrade(
            f"closed-{i}", summary.direction, fill_time(row.EntryBar), fill_time(row.ExitBar),
            float(row.EntryPrice), float(row.ExitPrice), int(row.Size), float(row.ReturnPct) * 100,
            float(row.Commission), "time" if int(row.EntryBar) in time_closed else "unknown"))
    positions = []
    for i, trade in enumerate(stats["_strategy"].trades):
        if not all(math.isfinite(float(v)) for v in (trade.entry_price, trade.size, trade.pl)):
            raise ValueError("nonfinite open position")
        positions.append(OpenPosition(f"open-{i}", summary.direction, fill_time(trade.entry_bar),
                                      float(trade.entry_price), int(trade.size), float(trade.pl)))
    from backtesting import Strategy
    return DetailedBacktestResult(
        copy.deepcopy(summary), "success", input_candles=input_candles,
        candles=candles, equity=equity, trades=tuple(trades),
        open_positions=tuple(positions), initial_equity=baseline,
        configuration=dict(initial_cash=100_000., commission=commission, commission_basis="per leg",
                           order_size=float(Strategy.buy.__kwdefaults__["size"]),
                           sizing="fraction of available equity; whole units", margin=1., spread=0.,
                           exclusive_orders=True, trade_on_close=False, finalize_trades=False,
                           hold_max_days=hold_max_days, min_trades=min_trades,
                           min_win_rate=min_win_rate, min_expectancy=min_expectancy,
                           signal_window_bars=signal_window_bars,
                           entry_start=entry_start.isoformat() if entry_start is not None else None,
                           entry_end=entry_end.isoformat() if entry_end is not None else None),
        effective_params=complete_effective_params(signal_fn, effective_params,
                                                  variant_fns=variant_fns),
        time_basis=("UTC epoch seconds from source bars; fills/equity mapped by actual engine bar position; "
                    "legacy engine timestamp interpretation unchanged; naive input interpreted UTC"))
