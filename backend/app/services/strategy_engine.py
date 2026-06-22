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
    ema_period: int = 50,
    trend_ema: int = 100,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    tolerance: float = 0.08,
    ma_type: str = "EMA",
    require_reversal: bool = False,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """Pullback to ema_period-MA in the direction of the trend.

    Bullish: uptrend + price pulling back toward ema_period-MA from above.
    Bearish: downtrend + price bouncing up toward ema_period-MA from below (mirror).
    Reversal candle optional (require_reversal).
    """
    if len(bars) < trend_ema + 10:
        return None
    closes = [b["close"] for b in bars]

    _ma = _sma if ma_type.upper() == "SMA" else _ema

    fast_ma = _ma(closes, ema_period)
    slow_ma = _ma(closes, trend_ema)
    if not fast_ma or not slow_ma:
        return None
    current  = closes[-1]
    fast_val = fast_ma[-1]
    slow_val = slow_ma[-1]
    last     = bars[-1]
    atr      = _atr(bars)

    if direction == "Bullish":
        # Trend: price above ema_period-MA, ema_period-MA above trend_ema-MA (two-MA stack)
        if current <= fast_val:
            return None
        if fast_val <= slow_val:
            return None
        # Pullback: price within `tolerance` of ema_period-MA from above
        if not (0 <= (current - fast_val) / fast_val <= tolerance):
            return None
        # Optional reversal candle gate: close > open (bullish bar)
        if require_reversal and last["close"] <= last["open"]:
            return None
        stop   = _swing_low(bars, lookback=10) - atr * 0.2
        target = current + atr * rr_target_mult * atr_stop_mult
    else:  # Bearish — mirror logic
        # Trend: price below ema_period-MA, ema_period-MA below trend_ema-MA (downtrend stack)
        if current >= fast_val:
            return None
        if fast_val >= slow_val:
            return None
        # Bounce: price within `tolerance` of ema_period-MA from below
        if not (0 <= (fast_val - current) / fast_val <= tolerance):
            return None
        # Optional reversal candle gate: close < open (bearish bar)
        if require_reversal and last["close"] >= last["open"]:
            return None
        stop   = _swing_high(bars, lookback=10) + atr * 0.2
        target = current - atr * rr_target_mult * atr_stop_mult

    ma_label = ma_type.upper()
    return StrategySignal(
        strategy="pullback_ema",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={
            f"{ma_label.lower()}_{ema_period}": round(fast_val, 2),
            f"{ma_label.lower()}_{trend_ema}":  round(slow_val, 2),
        },
    )


# ── Strategy 2: Breakout from tight base ─────────────────────────────────────

def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 1.5,
    volume_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """Break above/below a narrow (ATR-tight) base with volume expansion.

    Bullish: close above base high.
    Bearish: close below base low (breakdown mirror).
    """
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
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else vols[-1]
    if vols[-1] < avg_vol * volume_mult:
        return None
    if direction == "Bullish":
        if current <= base_high:
            return None
        stop   = base_low - atr * 0.2
        target = current + (current - stop) * rr_target_mult
        detail = {"base_high": round(base_high, 2), "base_range_pct": round(base_range_pct * 100, 1)}
    else:  # Bearish breakdown below base low
        if current >= base_low:
            return None
        stop   = base_high + atr * 0.2
        target = current - (stop - current) * rr_target_mult
        detail = {"base_low": round(base_low, 2), "base_range_pct": round(base_range_pct * 100, 1)}
    return StrategySignal(
        strategy="breakout_base",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail=detail,
    )


# ── Strategy 3: MA crossover 20/50 ───────────────────────────────────────────

def ma_crossover_signal(
    bars: list[dict],
    *,
    fast: int = 20,
    slow: int = 50,
    lookback: int = 10,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """Golden cross (Bullish) or death cross (Bearish) within the last `lookback` bars.

    Bullish: 20-SMA crosses above 50-SMA (golden cross).
    Bearish: 20-SMA crosses below 50-SMA (death cross mirror).
    """
    if len(bars) < slow + 5:
        return None
    closes = [b["close"] for b in bars]
    fast_ma = _sma(closes, fast)
    slow_ma = _sma(closes, slow)
    if len(fast_ma) < lookback + 1 or len(slow_ma) < lookback + 1:
        return None
    for i in range(-lookback, 0):
        if direction == "Bullish":
            crossed = fast_ma[i - 1] <= slow_ma[i - 1] and fast_ma[i] > slow_ma[i]
        else:  # Bearish — death cross
            crossed = fast_ma[i - 1] >= slow_ma[i - 1] and fast_ma[i] < slow_ma[i]
        if crossed:
            current = closes[-1]
            atr = _atr(bars)
            if direction == "Bullish":
                stop   = slow_ma[-1] - atr * 0.5
                target = current + atr * 3.0
            else:
                stop   = slow_ma[-1] + atr * 0.5
                target = current - atr * 3.0
            return StrategySignal(
                strategy="ma_crossover",
                direction=direction,
                entry_price=round(current, 2),
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr=round(atr, 2),
                detail={f"sma_{fast}": round(fast_ma[-1], 2), f"sma_{slow}": round(slow_ma[-1], 2)},
            )
    return None


# ── Strategy 4: Mean reversion RSI ───────────────────────────────────────────

def mean_reversion_rsi_signal(
    bars: list[dict],
    *,
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    trend_sma: int = 200,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """RSI mean-reversion signal in the direction of the trend.

    Bullish: RSI < rsi_oversold while price is above 200-SMA (oversold in uptrend).
    Bearish: RSI > rsi_overbought while price is below 200-SMA (overbought in downtrend).
    """
    if len(bars) < trend_sma + rsi_period + 5:
        return None
    closes = [b["close"] for b in bars]
    trend = _sma(closes, trend_sma)
    if not trend:
        return None
    rsi = _rsi(closes, rsi_period)
    if not rsi or len(rsi) < 2:
        return None
    current = closes[-1]
    atr = _atr(bars)
    if direction == "Bullish":
        if closes[-1] <= trend[-1]:        return None   # must be above trend (uptrend context)
        if rsi[-1] >= rsi_oversold:        return None   # must be oversold
        if rsi[-1] <= rsi[-2]:             return None   # RSI must be recovering (ticking up)
        stop   = _swing_low(bars, lookback=10) - atr * 0.2
        target = current + atr * 2.5
    else:  # Bearish — overbought in downtrend
        if closes[-1] >= trend[-1]:        return None   # must be below trend (downtrend context)
        if rsi[-1] <= rsi_overbought:      return None   # must be overbought
        if rsi[-1] >= rsi[-2]:             return None   # RSI must be rolling over (ticking down)
        stop   = _swing_high(bars, lookback=10) + atr * 0.2
        target = current - atr * 2.5
    return StrategySignal(
        strategy="mean_reversion_rsi",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"rsi": round(rsi[-1], 1), f"sma_{trend_sma}": round(trend[-1], 2)},
    )
