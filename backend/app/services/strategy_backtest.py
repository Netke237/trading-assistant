from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from app.services.strategy_backtest_details import (
    DetailedBacktestResult, DetailStatus, collect_details, source_frame,
)

logger = logging.getLogger(__name__)

Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap", "mean_reversion_vwap_daily", "mean_reversion_multi"]


def normalize_direction(direction: str | None) -> Literal["Bullish", "Bearish"]:
    """The one spelling the signal functions compare against.

    Every branch in strategy_engine and `_entry_side` tests ``== "Bullish"``
    and treats anything else as bearish, so a config value ``bullish`` silently
    ran the BEARISH branch in the WFO tuner (TRADING_REVIEW.md fix #1).
    Unknown values raise instead of falling through to bearish.
    """
    d = str(direction or "").strip().lower()
    if d == "bullish":
        return "Bullish"
    if d == "bearish":
        return "Bearish"
    raise ValueError(f"direction must be bullish|bearish, got {direction!r}")


def _entry_side(direction: str, *, entry: float, sl: float, tp: float) -> str | None:
    """Decide order side, or None if stop/target are on the wrong side of entry.
    Bullish: stop below entry, target above → 'buy'
    Bearish: stop above entry, target below → 'sell'
    """
    if direction == "Bullish":
        return "buy" if sl < entry < tp else None
    return "sell" if tp < entry < sl else None

_MIN_TRADES = 10
# The intraday mean_reversion_vwap backtest's per-bar window, unchanged by
# STOCKS-HORIZON-T1 H1: intraday paths keep their windows (its anchored VWAP
# is computed over the whole window, so the length moves its levels).
_INTRADAY_SIGNAL_WINDOW = 350
_MIN_WIN_RATE = 0.45
_MIN_EXPECTANCY = 0.0


@dataclass
class BacktestResult:
    strategy:          str
    direction:         str
    n_trades:          int
    win_rate:          float
    total_return_pct:  float
    max_drawdown_pct:  float
    expectancy:        float
    sharpe:            float
    confidence:        int | None
    passes_gate:       bool
    summary_text:      str
    # Trades closed by the hold_max_days time exit (STOCKS-HORIZON-T1 H2).
    n_time_exits:      int = 0


ExitReason = Literal["stop", "target", "time"]


@dataclass(frozen=True)
class TradeRecord:
    """One closed backtest trade (STOCKS-HORIZON-T1 H2).

    ``net_return_pct`` is backtesting.py's ``Trade.pl_pct`` x 100, net of the
    per-leg ``commission``. ``exit_reason`` is ``"time"`` when the hold_max_days
    time exit closed it; else read from the fill price against the trade's
    stop (so a gap fill through the stop at the open is a stop).
    """
    entry_date:     date
    exit_date:      date
    entry_price:    float
    exit_price:     float
    net_return_pct: float
    exit_reason:    ExitReason


def _bars_to_df(bars: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    if "time" in df.columns:
        df["Date"] = pd.to_datetime(df["time"])
        df = df.set_index("Date")
    else:
        df.index = pd.RangeIndex(len(df))
    return df[["Open", "High", "Low", "Close", "Volume"]]


def run_strategy_backtest(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int = _MIN_TRADES,
    min_win_rate: float = _MIN_WIN_RATE,
    params: dict | None = None,
    commission: float = 0.0,
    entry_start: date | None = None,
    hold_max_days: int | None = None,
    entry_end: date | None = None,
    detail_collector: list[DetailedBacktestResult] | None = None,
) -> BacktestResult:
    """Run a full entry+stop+target backtest using backtesting.py.

    ``entry_start`` (walk-forward, fix #2): bars before it only prime the
    indicators — no entry is placed on them — and the return / drawdown /
    Sharpe are computed over the equity curve from ``entry_start`` onward, so a
    warm-up prefix neither trades nor dilutes the window's statistics.

    ``hold_max_days`` (STOCKS-HORIZON-T1 H2): a trade filled on bar e is closed
    with a market order at the close of the first bar t dated at least
    ``hold_max_days`` calendar days after bar e. backtesting.py queues that
    close order ahead of the trade's stop and target, so it fills at bar t+1's
    open before either is checked. ``None`` = no time exit.

    ``entry_end``: no new entry on a bar dated on or after it; a trade already
    open still runs to its stop, target or time exit.

    ``detail_collector``: optionally append detached chart evidence from this
    same invocation. Evidence extraction failure preserves this aggregate.
    """
    return _run_backtest(
        bars, strategy=strategy, direction=direction, min_trades=min_trades,
        min_win_rate=min_win_rate, params=params, commission=commission,
        entry_start=entry_start, hold_max_days=hold_max_days, entry_end=entry_end,
        collect_trades=False,
        detail_collector=detail_collector,
    )[0]


def run_strategy_backtest_detailed(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int = _MIN_TRADES,
    min_win_rate: float = _MIN_WIN_RATE,
    params: dict | None = None,
    commission: float = 0.0,
    entry_start: date | None = None,
    hold_max_days: int | None = None,
    entry_end: date | None = None,
) -> DetailedBacktestResult:
    """One engine invocation with precise, detached chart evidence.

    Unlike legacy aggregate APIs, malformed input is an explicit non-success.
    Existing aggregate callers may pass ``detail_collector=[]`` to capture the
    same evidence without changing their return type or invoking the engine twice.
    """
    try:
        direction = normalize_direction(direction)
        if len(bars) < 100:
            reason = "Insufficient history (< 100 bars)"
            return DetailedBacktestResult(_empty_result(strategy, direction, reason), "insufficient_history", reason)
        source_frame(bars)
        if not math.isfinite(commission):
            raise ValueError("nonfinite commission")
    except Exception as exc:
        return DetailedBacktestResult(_empty_result(strategy, direction, str(exc)), "invalid_input", str(exc))
    details: list[DetailedBacktestResult] = []
    try:
        run_strategy_backtest(
            bars, strategy=strategy, direction=direction, min_trades=min_trades,
            min_win_rate=min_win_rate, params=params, commission=commission,
            entry_start=entry_start, hold_max_days=hold_max_days, entry_end=entry_end,
            detail_collector=details)
    except Exception as exc:
        return DetailedBacktestResult(_empty_result(strategy, direction, str(exc)), "failed", str(exc))
    return details[0]


def run_strategy_backtest_trades(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int = _MIN_TRADES,
    min_win_rate: float = _MIN_WIN_RATE,
    params: dict | None = None,
    commission: float = 0.0,
    entry_start: date | None = None,
    hold_max_days: int | None = None,
    entry_end: date | None = None,
) -> tuple[BacktestResult, list[TradeRecord]]:
    """``run_strategy_backtest`` plus its closed trades, in entry order.

    Trade records carry dates, so the bars must be dated (a ``time`` key).
    """
    result, trades = _run_backtest(
        bars, strategy=strategy, direction=direction, min_trades=min_trades,
        min_win_rate=min_win_rate, params=params, commission=commission,
        entry_start=entry_start, hold_max_days=hold_max_days, entry_end=entry_end,
        collect_trades=True,
    )
    return result, trades or []


def _run_backtest(
    bars: list[dict],
    *,
    strategy: str,
    direction: str,
    min_trades: int,
    min_win_rate: float,
    params: dict | None,
    commission: float,
    entry_start: date | None,
    hold_max_days: int | None,
    entry_end: date | None,
    collect_trades: bool,
    detail_collector: list[DetailedBacktestResult] | None = None,
) -> tuple[BacktestResult, list[TradeRecord] | None]:
    direction = normalize_direction(direction)

    def _empty(reason: str, status: DetailStatus = "failed") -> tuple[BacktestResult, list[TradeRecord]]:
        result = _empty_result(strategy, direction, reason)
        if detail_collector is not None:
            detail_collector.append(DetailedBacktestResult(result, status, reason))
        return result, []
    from backtesting import Backtest, Strategy as BtStrategy
    from app.services.strategy_engine import (
        pullback_ema_signal, breakout_base_signal,
        ma_crossover_signal, mean_reversion_rsi_signal,
        mean_reversion_bb_signal, mean_reversion_vwap_signal,
        mean_reversion_vwap_daily_signal, SIGNAL_WINDOW_BARS, multi_signal,
    )
    from app.services.strategy_param_store import get_exit

    _signal_fn = {
        "pullback_ema":          pullback_ema_signal,
        "breakout_base":         breakout_base_signal,
        "ma_crossover":          ma_crossover_signal,
        "mean_reversion_rsi":    mean_reversion_rsi_signal,
        "mean_reversion_bb":     mean_reversion_bb_signal,
        "mean_reversion_vwap":   mean_reversion_vwap_signal,
        "mean_reversion_vwap_daily": mean_reversion_vwap_daily_signal,
        # STOCKS-HORIZON-T1 H3: multi backtests its own vote at the combined
        # levels; `params` is the merged multi params shape.
        "mean_reversion_multi":
            lambda bars, *, direction, **shape: multi_signal(bars, direction=direction, params=shape),
    }.get(strategy)

    if not _signal_fn:
        return _empty(f"Unknown strategy '{strategy}'", "unsupported")

    if len(bars) < 100:
        return _empty("Insufficient history (< 100 bars)", "insufficient_history")

    df = _bars_to_df(bars)
    if not isinstance(df.index, pd.DatetimeIndex):
        for name, value in (("entry_start", entry_start), ("hold_max_days", hold_max_days),
                            ("entry_end", entry_end)):
            if value is not None:
                return _empty(f"{name} needs dated bars")
        if collect_trades:
            return _empty("trade records need dated bars")
    fn = _signal_fn
    _window = _INTRADAY_SIGNAL_WINDOW if strategy == "mean_reversion_vwap" else SIGNAL_WINDOW_BARS

    # WFO's train_fold (walk_forward.py:212) passes ONLY the search-grid combo as
    # `params` — never the `active:` block — so any exit parameter absent from the
    # grid would fall back to the Python default during tuning while the live scan
    # used the configured value. Merging the exit policy HERE (under `params`, so a
    # grid value still wins) is what keeps the tuner, the scan and the watch
    # evaluator all measuring the same exits.
    #
    # The live scan already merges `exit:` via _merge_strategy_params, so for that
    # caller this is a no-op re-application of identical values.
    #
    # mean_reversion_multi: `params` is already the effective multi shape
    # (merge_multi_params put each variant's exit block in), so no merge.
    effective_params = (dict(params or {}) if strategy == "mean_reversion_multi"
                        else {**get_exit(strategy), **(params or {})})

    # Entry bar of every trade the time exit closed; and the stop of the entry
    # placed on bar i-1, keyed by its only possible fill bar i (DAY orders: the
    # limit lives one bar).
    time_closed: set[int] = set()
    stops: dict[int, float] = {}

    class _Strategy(BtStrategy):
        def init(self):
            pass

        def next(self):
            # Live entries are DAY orders: an entry limit lives for the one bar after its signal (T6, M3).
            for o in list(self.orders):
                if not o.is_contingent:
                    o.cancel()
            n = len(self.data.Close)
            if n < 60:
                return
            if hold_max_days is not None:
                # Time exit (STOCKS-HORIZON-T1 H2), before the warm-up and
                # entry_end returns so an open trade always exits. Trade.close()
                # queues a market order at the front: it fills at the next bar's
                # open before the trade's stop and target are checked.
                bar_date = self.data.index[-1].date()
                for trade in list(self.trades):
                    if (trade.entry_bar not in time_closed
                            and (bar_date - trade.entry_time.date()).days >= hold_max_days):
                        time_closed.add(trade.entry_bar)
                        trade.close()
            if entry_start is not None and self.data.index[-1].date() < entry_start:
                return  # warm-up bar: indicators prime, no entry (fix #2)
            if entry_end is not None and self.data.index[-1].date() >= entry_end:
                return  # past the window: open trades run on, no new entry
            # A daily signal gets exactly the window the live scan, Analysis and
            # the watches give it: SIGNAL_WINDOW_BARS (STOCKS-HORIZON-T1 H1; was
            # 350 here and 120 live). The cap also avoids rebuilding the full
            # history every bar (was O(n²) over a 5-year scan per symbol); under
            # it the slice starts at bar 0, never a negative index.
            start = max(0, n - _window)
            slice_bars = [
                {"open": float(self.data.Open[i]), "high": float(self.data.High[i]),
                 "low": float(self.data.Low[i]),   "close": float(self.data.Close[i]),
                 "volume": float(self.data.Volume[i])}
                for i in range(start, n)
            ]
            if not self.position:
                sig = fn(slice_bars, direction=direction, **effective_params)
                if sig is not None:
                    side = _entry_side(direction, entry=sig.entry_price,
                                       sl=sig.stop_price, tp=sig.target_price)
                    if side == "buy":
                        self.buy(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)
                    elif side == "sell":
                        self.sell(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)
                    if side is not None:
                        stops[n] = float(sig.stop_price)

    try:
        bt = Backtest(df, _Strategy, cash=100_000, commission=commission, exclusive_orders=True)
        stats = bt.run()
    except Exception as exc:
        logger.warning("Backtest failed for %s: %s", strategy, exc)
        return _empty(str(exc))

    n_trades = int(stats.get("# Trades", 0))

    # A zero-trade window makes the underlying `backtesting` library return
    # NaN for Win Rate/Sharpe (division by zero trades internally) rather
    # than 0 — `stats.get(key, 0)`'s default only fires when the key is
    # absent, not when its value is present-but-NaN, so that default doesn't
    # help here. Left unguarded, NaN propagates into expectancy (nan*x is
    # nan) and reaches BacktestResult/the API response, where Python's
    # default JSON encoder emits the bare (invalid-JSON) token `NaN`,
    # breaking every caller's `response.json()`.
    _win_rate_raw = float(stats.get("Win Rate [%]", 0))
    win_rate    = 0.0 if math.isnan(_win_rate_raw) else _win_rate_raw / 100.0
    total_ret   = float(stats.get("Return [%]", 0))
    max_dd      = float(stats.get("Max. Drawdown [%]", 0))
    _sharpe_raw = float(stats.get("Sharpe Ratio", 0) or 0)
    sharpe      = 0.0 if math.isnan(_sharpe_raw) else _sharpe_raw
    if entry_start is not None:
        # Score only the fold itself; the warm-up prefix is flat (no entries).
        eq = stats["_equity_curve"]["Equity"]
        # tz-aware bar times (e.g. "...T00:00:00+00:00") make a naive cutoff raise
        # TypeError on comparison, which train_fold's broad except would swallow.
        cutoff = pd.Timestamp(entry_start)
        if getattr(eq.index, "tz", None) is not None:
            cutoff = cutoff.tz_localize(eq.index.tz)
        eq = eq[eq.index >= cutoff]
        total_ret, max_dd, sharpe = _window_stats(eq)

    # Use real per-trade returns (stats['_trades']['ReturnPct']) rather than deriving
    # avg_win/avg_loss from portfolio-level aggregates (total_return_pct, max_drawdown_pct).
    # Those aggregates are not trade-additive — e.g. total_return_pct is the compounded
    # equity-curve return and max_drawdown_pct is a peak-to-trough equity statistic — so
    # dividing them by win/loss counts produces avg_win/avg_loss with no correspondence to
    # actual trade P&L, and can yield negative expectancy for a net-profitable, high-win-rate
    # strategy.
    trades_df = stats["_trades"]
    n_time_exits = int(trades_df["EntryBar"].isin(time_closed).sum()) if time_closed else 0
    records = _trade_records(trades_df, direction, time_closed, stops) if collect_trades else None
    per_trade_pct = trades_df["ReturnPct"].to_numpy() * 100.0  # decimal → percent
    wins_pct  = per_trade_pct[per_trade_pct > 0]
    losses_pct = per_trade_pct[per_trade_pct <= 0]
    avg_win  = float(wins_pct.mean())        if len(wins_pct)   > 0 else 0.0
    avg_loss = float(abs(losses_pct.mean())) if len(losses_pct) > 0 else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    passes = win_rate >= min_win_rate and n_trades >= min_trades and expectancy >= _MIN_EXPECTANCY
    # Real n_trades/win_rate/sharpe/expectancy are always preserved, even when the
    # eligibility gate isn't met — callers that pool real backtest activity across
    # windows (WFO train_fold's grid search, its IS/OOS re-runs) key off n_trades>0
    # to decide whether a window "actually traded"; silently zeroing these fields
    # below the gate made every sub-`min_trades` window look identical to a window
    # with zero signals, which defeated the grid search whenever real trade counts
    # (the common case on realistic bar history) sat under the gate. Only the
    # UI-facing `confidence` score and `passes_gate` verdict are gated.
    confidence = min(100, max(0, round(win_rate * 100))) if n_trades >= min_trades else None

    if n_trades < min_trades:
        summary = f"Only {n_trades} trades — need {min_trades}"
    else:
        summary = (
            f"{n_trades} trades · Win {win_rate:.0%} · "
            f"Return {total_ret:.1f}% · MaxDD {max_dd:.1f}% · Sharpe {sharpe:.2f} · Expectancy ${expectancy:.2f}"
        )
    result = BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=n_trades, win_rate=win_rate,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        expectancy=round(expectancy, 3), sharpe=round(sharpe, 3),
        confidence=confidence, passes_gate=passes, summary_text=summary,
        n_time_exits=n_time_exits,
    )
    if detail_collector is not None:
        try:
            detail = collect_details(result, stats, df, source_bars=bars, entry_start=entry_start,
                                     entry_end=entry_end, hold_max_days=hold_max_days,
                                     commission=commission, effective_params=effective_params,
                                     time_closed=time_closed)
        except Exception as exc:
            # Optional evidence must never change ranking/gates/aggregate results.
            detail = DetailedBacktestResult(result, "invalid_evidence", str(exc))
        detail_collector.append(detail)
    return result, records


def _trade_records(
    trades_df: pd.DataFrame,
    direction: str,
    time_closed: set[int],
    stops: dict[int, float],
) -> list[TradeRecord]:
    """Closed trades as TradeRecords. A trade the time exit closed is "time";
    otherwise its fill against its stop decides (Bullish: at or below the stop
    is a stop; Bearish mirrored), which also classifies a gap fill at the open."""
    out: list[TradeRecord] = []
    for row in trades_df.itertuples(index=False):
        entry_bar = int(row.EntryBar)
        exit_price = float(row.ExitPrice)
        reason: ExitReason
        if entry_bar in time_closed:
            reason = "time"
        else:
            sl = stops[entry_bar]
            hit_stop = exit_price <= sl if direction == "Bullish" else exit_price >= sl
            reason = "stop" if hit_stop else "target"
        out.append(TradeRecord(
            entry_date=pd.Timestamp(row.EntryTime).date(),
            exit_date=pd.Timestamp(row.ExitTime).date(),
            entry_price=float(row.EntryPrice),
            exit_price=exit_price,
            net_return_pct=float(row.ReturnPct) * 100.0,
            exit_reason=reason,
        ))
    return out


def _window_stats(equity: pd.Series) -> tuple[float, float, float]:
    """Return %, max drawdown % (<= 0), annualised Sharpe of an equity slice."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0, 0.0, 0.0
    ret = (equity.iloc[-1] / equity.iloc[0] - 1.0) * 100.0
    dd = float(((equity / equity.cummax()) - 1.0).min() * 100.0)
    daily = equity.pct_change().dropna()
    sd = float(daily.std())
    sharpe = float(daily.mean() / sd * (252 ** 0.5)) if sd > 0 else 0.0
    return float(ret), dd, sharpe


def _empty_result(strategy: str, direction: str, reason: str) -> BacktestResult:
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=0, win_rate=0.0, total_return_pct=0.0,
        max_drawdown_pct=0.0, expectancy=0.0, sharpe=0.0,
        confidence=None, passes_gate=False, summary_text=reason,
    )
