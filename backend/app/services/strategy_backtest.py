from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap"]


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
) -> BacktestResult:
    """Run a full entry+stop+target backtest using backtesting.py.

    ``entry_start`` (walk-forward, fix #2): bars before it only prime the
    indicators — no entry is placed on them — and the return / drawdown /
    Sharpe are computed over the equity curve from ``entry_start`` onward, so a
    warm-up prefix neither trades nor dilutes the window's statistics.
    """
    direction = normalize_direction(direction)
    from backtesting import Backtest, Strategy as BtStrategy
    from app.services.strategy_engine import (
        pullback_ema_signal, breakout_base_signal,
        ma_crossover_signal, mean_reversion_rsi_signal,
        mean_reversion_bb_signal, mean_reversion_vwap_signal,
    )
    from app.services.strategy_param_store import get_exit

    _signal_fn = {
        "pullback_ema":          pullback_ema_signal,
        "breakout_base":         breakout_base_signal,
        "ma_crossover":          ma_crossover_signal,
        "mean_reversion_rsi":    mean_reversion_rsi_signal,
        "mean_reversion_bb":     mean_reversion_bb_signal,
        "mean_reversion_vwap":   mean_reversion_vwap_signal,
    }.get(strategy)

    if not _signal_fn:
        return _empty_result(strategy, direction, f"Unknown strategy '{strategy}'")

    if len(bars) < 100:
        return _empty_result(strategy, direction, "Insufficient history (< 100 bars)")

    df = _bars_to_df(bars)
    if entry_start is not None and not isinstance(df.index, pd.DatetimeIndex):
        return _empty_result(strategy, direction, "entry_start needs dated bars")
    fn = _signal_fn

    # WFO's train_fold (walk_forward.py:212) passes ONLY the search-grid combo as
    # `params` — never the `active:` block — so any exit parameter absent from the
    # grid would fall back to the Python default during tuning while the live scan
    # used the configured value. Merging the exit policy HERE (under `params`, so a
    # grid value still wins) is what keeps the tuner, the scan and the watch
    # evaluator all measuring the same exits.
    #
    # The live scan already merges `exit:` via _merge_strategy_params, so for that
    # caller this is a no-op re-application of identical values.
    effective_params = {**get_exit(strategy), **(params or {})}

    class _Strategy(BtStrategy):
        def init(self):
            pass

        def next(self):
            n = len(self.data.Close)
            if n < 60:
                return
            if entry_start is not None and self.data.index[-1].date() < entry_start:
                return  # warm-up bar: indicators prime, no entry (fix #2)
            # Only the trailing window is needed (mean_reversion_bb needs ~225+ bars
            # with trend_sma:200 headroom — the largest of the five strategies).
            # Capping at 350 avoids rebuilding the full history every bar (was O(n²)
            # over a 5-year scan per symbol).
            start = max(0, n - 350)
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

    try:
        bt = Backtest(df, _Strategy, cash=100_000, commission=commission, exclusive_orders=True)
        stats = bt.run()
    except Exception as exc:
        logger.warning("Backtest failed for %s: %s", strategy, exc)
        return _empty_result(strategy, direction, str(exc))

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
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=n_trades, win_rate=win_rate,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        expectancy=round(expectancy, 3), sharpe=round(sharpe, 3),
        confidence=confidence, passes_gate=passes, summary_text=summary,
    )


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
