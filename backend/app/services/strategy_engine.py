from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ── Helpers (reuse same helpers as stock_scorer to avoid duplication) ─────────

def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _sma(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    return [sum(values[i:i + period]) / period for i in range(len(values) - period + 1)]


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsi_vals = []
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        rs = avg_g / avg_l if avg_l > 0 else 100.0
        rsi_vals.append(100 - 100 / (1 + rs))
    return rsi_vals


def _atr(bars: list[dict], period: int = 14) -> float:
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    return sum(trs[-period:]) / min(len(trs), period)


def _swing_low(bars: list[dict], lookback: int = 20) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return min(b["low"] for b in window)


def _swing_high(bars: list[dict], lookback: int = 20) -> float:
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return max(b["high"] for b in window)


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class StrategySignal:
    strategy:    str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float
    stop_price:  float
    target_price: float
    atr:         float
    detail:      dict = field(default_factory=dict)

    @property
    def risk(self) -> float:
        return abs(self.entry_price - self.stop_price)

    @property
    def reward(self) -> float:
        return abs(self.target_price - self.entry_price)

    @property
    def rr_ratio(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


# ── Strategy 1: Pullback to 20-EMA ───────────────────────────────────────────

def pullback_ema_signal(
    bars: list[dict],
    *,
    ema_period: int = 20,
    trend_sma: int = 50,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
) -> StrategySignal | None:
    """Bullish: uptrend (price > rising 50-SMA) + pullback toward 20-EMA + reversal candle."""
    if len(bars) < trend_sma + 10:
        return None
    closes = [b["close"] for b in bars]
    ema20 = _ema(closes, ema_period)
    sma50 = _sma(closes, trend_sma)
    if not ema20 or not sma50:
        return None
    current = closes[-1]
    ema_val = ema20[-1]
    sma_val = sma50[-1]
    # Trend: price above rising 50-SMA
    if current <= sma_val:
        return None
    if len(sma50) >= 5 and sma50[-1] <= sma50[-5]:
        return None
    # Pullback: price within 1.5% of 20-EMA from above
    if not (0 <= (current - ema_val) / ema_val <= 0.04):
        return None
    # Reversal candle: close > open (bullish bar)
    last = bars[-1]
    if last["close"] <= last["open"]:
        return None
    atr = _atr(bars)
    stop = _swing_low(bars, lookback=10) - atr * 0.2
    target = current + atr * rr_target_mult * atr_stop_mult
    return StrategySignal(
        strategy="pullback_ema",
        direction="Bullish",
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"ema_20": round(ema_val, 2), "sma_50": round(sma_val, 2)},
    )


# ── Strategy 2: Breakout from tight base ─────────────────────────────────────

def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 1.5,
    volume_mult: float = 1.1,
    rr_target_mult: float = 2.0,
) -> StrategySignal | None:
    """Bullish: break above N-day high after a narrow (ATR-tight) base with volume expansion."""
    if len(bars) < base_lookback + 5:
        return None
    closes = [b["close"] for b in bars]
    vols   = [b["volume"] for b in bars]
    # Base: the last base_lookback bars excluding today
    base_bars = bars[-(base_lookback + 1):-1]
    if not base_bars:
        return None
    base_high = max(b["high"] for b in base_bars)
    base_low  = min(b["low"]  for b in base_bars)
    base_range_pct = (base_high - base_low) / base_low if base_low > 0 else 99
    atr = _atr(bars)
    # Tight base: range < atr_tight_max * ATR
    if atr > 0 and (base_high - base_low) > atr_tight_max * atr:
        return None
    current = closes[-1]
    # Breakout: today closes above the base high
    if current <= base_high:
        return None
    # Volume: today > 1.3× 20-day avg
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else vols[-1]
    if vols[-1] < avg_vol * volume_mult:
        return None
    stop  = base_low - atr * 0.2
    target = current + (current - stop) * rr_target_mult
    return StrategySignal(
        strategy="breakout_base",
        direction="Bullish",
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"base_high": round(base_high, 2), "base_range_pct": round(base_range_pct * 100, 1)},
    )


# ── Strategy 3: MA crossover 20/50 ───────────────────────────────────────────

def ma_crossover_signal(
    bars: list[dict],
    *,
    fast: int = 20,
    slow: int = 50,
) -> StrategySignal | None:
    """Bullish: 20-SMA crosses above 50-SMA within the last 3 bars."""
    if len(bars) < slow + 5:
        return None
    closes = [b["close"] for b in bars]
    fast_ma = _sma(closes, fast)
    slow_ma = _sma(closes, slow)
    if len(fast_ma) < 4 or len(slow_ma) < 4:
        return None
    # Recent cross: fast crossed above slow within last 3 bars
    for i in range(-10, 0):
        if fast_ma[i - 1] <= slow_ma[i - 1] and fast_ma[i] > slow_ma[i]:
            current = closes[-1]
            atr = _atr(bars)
            stop  = slow_ma[-1] - atr * 0.5
            target = current + atr * 3.0
            return StrategySignal(
                strategy="ma_crossover",
                direction="Bullish",
                entry_price=round(current, 2),
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr=round(atr, 2),
                detail={"fast_ma": round(fast_ma[-1], 2), "slow_ma": round(slow_ma[-1], 2)},
            )
    return None


# ── Strategy 4: Mean reversion RSI ───────────────────────────────────────────

def mean_reversion_rsi_signal(
    bars: list[dict],
    *,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    trend_sma: int = 200,
) -> StrategySignal | None:
    """Bullish: RSI < 30 while price is above 200-SMA (oversold in uptrend)."""
    if len(bars) < trend_sma + rsi_period + 5:
        return None
    closes = [b["close"] for b in bars]
    trend = _sma(closes, trend_sma)
    if not trend or closes[-1] <= trend[-1]:
        return None
    rsi = _rsi(closes, rsi_period)
    if not rsi or rsi[-1] >= rsi_oversold:
        return None
    # Confirm RSI is recovering (rising from the last bar)
    if len(rsi) < 2 or rsi[-1] <= rsi[-2]:
        return None
    current = closes[-1]
    atr = _atr(bars)
    stop  = _swing_low(bars, lookback=10) - atr * 0.2
    target = current + atr * 2.5
    return StrategySignal(
        strategy="mean_reversion_rsi",
        direction="Bullish",
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"rsi": round(rsi[-1], 1), "sma_200": round(trend[-1], 2)},
    )
