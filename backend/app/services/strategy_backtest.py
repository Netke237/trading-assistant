from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd

logger = logging.getLogger(__name__)

Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap"]


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
) -> BacktestResult:
    """Run a full entry+stop+target backtest using backtesting.py."""
    from backtesting import Backtest, Strategy as BtStrategy
    from app.services.strategy_engine import (
        pullback_ema_signal, breakout_base_signal,
        ma_crossover_signal, mean_reversion_rsi_signal,
        mean_reversion_bb_signal, mean_reversion_vwap_signal,
    )

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
    fn = _signal_fn

    class _Strategy(BtStrategy):
        def init(self):
            pass

        def next(self):
            n = len(self.data.Close)
            if n < 60:
                return
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
                sig = fn(slice_bars, direction=direction, **(params or {}))
                if sig is not None:
                    side = _entry_side(direction, entry=sig.entry_price,
                                       sl=sig.stop_price, tp=sig.target_price)
                    if side == "buy":
                        self.buy(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)
                    elif side == "sell":
                        self.sell(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)

    try:
        bt = Backtest(df, _Strategy, cash=100_000, commission=0.0, exclusive_orders=True)
        stats = bt.run()
    except Exception as exc:
        logger.warning("Backtest failed for %s: %s", strategy, exc)
        return _empty_result(strategy, direction, str(exc))

    n_trades = int(stats.get("# Trades", 0))
    if n_trades < min_trades:
        return _empty_result(strategy, direction, f"Only {n_trades} trades — need {min_trades}")

    win_rate    = float(stats.get("Win Rate [%]", 0)) / 100.0
    total_ret   = float(stats.get("Return [%]", 0))
    max_dd      = float(stats.get("Max. Drawdown [%]", 0))
    sharpe      = float(stats.get("Sharpe Ratio", 0) or 0)

    wins  = round(win_rate * n_trades)
    losses = n_trades - wins
    avg_win  = abs(total_ret / wins)  if wins  > 0 else 0
    avg_loss = abs(max_dd   / losses) if losses > 0 else 1
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    confidence = min(100, max(0, round(win_rate * 100)))
    passes = win_rate >= min_win_rate and n_trades >= min_trades

    summary = (
        f"{n_trades} trades · Win {win_rate:.0%} · "
        f"Return {total_ret:.1f}% · MaxDD {max_dd:.1f}% · Sharpe {sharpe:.2f}"
    )
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=n_trades, win_rate=win_rate,
        total_return_pct=total_ret, max_drawdown_pct=max_dd,
        expectancy=round(expectancy, 3), sharpe=round(sharpe, 3),
        confidence=confidence, passes_gate=passes, summary_text=summary,
    )


def _empty_result(strategy: str, direction: str, reason: str) -> BacktestResult:
    return BacktestResult(
        strategy=strategy, direction=direction,
        n_trades=0, win_rate=0.0, total_return_pct=0.0,
        max_drawdown_pct=0.0, expectancy=0.0, sharpe=0.0,
        confidence=None, passes_gate=False, summary_text=reason,
    )
