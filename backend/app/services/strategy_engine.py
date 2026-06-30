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


def _bollinger(values: list[float], period: int, n_std: float) -> tuple[list[float], list[float], list[float]]:
    mid = _sma(values, period)
    if not mid:
        return [], [], []
    upper, lower = [], []
    for i, m in enumerate(mid):
        window = values[i : i + period]
        std = (sum((x - m) ** 2 for x in window) / period) ** 0.5
        upper.append(m + n_std * std)
        lower.append(m - n_std * std)
    return upper, mid, lower


def _vwap(bars: list[dict]) -> float:
    num = sum(((b["high"] + b["low"] + b["close"]) / 3) * b["volume"] for b in bars)
    den = sum(b["volume"] for b in bars)
    return num / den if den > 0 else 0.0


def _atr_series(bars: list[dict], period: int = 14) -> list[float]:
    if len(bars) < 2:
        return []
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    result = []
    for i in range(len(trs)):
        window = trs[max(0, i - period + 1): i + 1]
        result.append(sum(window) / len(window))
    return result


# ── Fibonacci retracement helper ──────────────────────────────────────────────

_FIB_RATIOS: dict[float, float] = {
    23.6: 0.236,
    38.2: 0.382,
    50.0: 0.500,
    61.8: 0.618,
    78.6: 0.786,
}


def _fibonacci_pullback_signal(
    bars: list[dict],
    direction: Literal["Bullish", "Bearish"],
    *,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
) -> tuple[bool, float | None, str | None]:
    """Check if close is near a Fibonacci retracement level of the dominant swing move.

    For Bullish: swing low → swing high within fib_swing_lookback bars.
    Retracement levels are measured downward from the swing high.
    For Bearish: swing high → swing low. Retracement levels measured upward from swing low.

    Returns:
        (at_level: bool, nearest_pct: float|None, level_label: str|None)
        nearest_pct is expressed as a percentage (e.g. 1.5 means 1.5% away).
    """
    if fib_levels is None:
        fib_levels = [23.6, 38.2, 50.0, 61.8]
    window = bars[-fib_swing_lookback:] if len(bars) >= fib_swing_lookback else bars
    if len(window) < 10:
        return False, None, None

    swing_high = max(b["high"] for b in window)
    swing_low  = min(b["low"]  for b in window)
    move = swing_high - swing_low
    if move <= 0:
        return False, None, None

    close = bars[-1]["close"]

    if direction == "Bullish":
        # Retracement levels from swing_high downward
        levels = {
            label: swing_high - _FIB_RATIOS[label] * move
            for label in fib_levels
            if label in _FIB_RATIOS
        }
    else:
        # Retracement levels from swing_low upward
        levels = {
            label: swing_low + _FIB_RATIOS[label] * move
            for label in fib_levels
            if label in _FIB_RATIOS
        }

    best_label: str | None = None
    best_dist_pct: float = float("inf")

    for label, level in levels.items():
        if level <= 0:
            continue
        dist_pct = abs(close - level) / level
        if dist_pct < best_dist_pct:
            best_dist_pct = dist_pct
            best_label = str(label)

    at_level = best_dist_pct <= fib_tolerance_pct
    return at_level, round(best_dist_pct * 100, 2), best_label


# Public alias so routers can import without depending on the private name
fibonacci_pullback_signal = _fibonacci_pullback_signal


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


@dataclass
class SetupSignal:
    strategy:   str
    direction:  Literal["Bullish", "Bearish"]
    symbol:     str
    confidence: int   # 0–100
    metrics:    dict  # atr_ratio, range_ratio, vol_ratio, proximity_pct, swing_level


# ── Strategy 1: Pullback to 20-EMA ───────────────────────────────────────────

def pullback_ema_signal(
    bars: list[dict],
    *,
    ema_period: int = 50,
    trend_ema: int = 100,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    tolerance: float = 0.04,
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

    # Volume contraction during pullback: 3-bar avg (excluding today) must be
    # below 90% of the 20-bar avg. Expanding volume on a pullback is not a clean re-test.
    if len(bars) >= 21:
        vols = [b["volume"] for b in bars]
        avg_vol_20 = sum(vols[-21:-1]) / 20
        avg_vol_3  = sum(vols[-4:-1]) / 3   # last 3 complete bars, mirrors -21:-1 convention
        if avg_vol_20 > 0 and avg_vol_3 >= 0.9 * avg_vol_20:
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
        stop = fast_val - atr * atr_stop_mult
        risk = current - stop
        if risk <= 0:
            return None
        target = current + risk * rr_target_mult
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
        stop = fast_val + atr * atr_stop_mult
        risk = stop - current
        if risk <= 0:
            return None
        target = current - risk * rr_target_mult

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
    require_choppy_regime: bool = False,
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
    if require_choppy_regime:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes, direction=direction)
        if omm is None or omm.state != "Choppy":
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


# ── Strategy 5: Mean reversion Bollinger Band ─────────────────────────────────

def mean_reversion_bb_signal(
    bars: list[dict],
    *,
    bb_period: int = 20,
    bb_std: float = 2.0,
    trend_sma: int = 200,
    stop_atr_mult: float = 0.5,
    rr_target_mult: float = 2.0,
    require_choppy_regime: bool = False,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """Bollinger Band mean-reversion signal.

    Bullish: price above trend SMA (uptrend context), prev bar low touched lower band,
             current close back inside band (above lower), and still below midline.
    Bearish: price below trend SMA (downtrend context), prev bar high touched upper band,
             current close back inside band (below upper), and still above midline.
    require_choppy_regime: when True, returns None unless OMM detects 'Choppy' state.
    """
    if len(bars) < trend_sma + bb_period + 5:
        return None
    closes = [b["close"] for b in bars]
    trend = _sma(closes, trend_sma)
    if not trend:
        return None
    upper, mid, lower = _bollinger(closes, bb_period, bb_std)
    if not upper:
        return None

    current = closes[-1]
    atr = _atr(bars)

    if require_choppy_regime:
        from app.services.regime_omm import compute_omm
        omm = compute_omm(closes, direction=direction)
        if omm is None or omm.state != "Choppy":
            return None

    if direction == "Bullish":
        if closes[-1] <= trend[-1]:
            return None  # must be above trend (uptrend context)
        if bars[-2]["low"] > lower[-2]:
            return None  # prev bar must have touched lower band
        if current <= lower[-1]:
            return None  # current close must be back inside band (above lower)
        if current >= mid[-1]:
            return None  # must still be below midline (not fully recovered)
        stop = lower[-1] - stop_atr_mult * atr
        risk = current - stop
        if risk <= 0:
            return None
        target = current + risk * rr_target_mult
    else:  # Bearish
        if closes[-1] >= trend[-1]:
            return None  # must be below trend (downtrend context)
        if bars[-2]["high"] < upper[-2]:
            return None  # prev bar must have touched upper band
        if current >= upper[-1]:
            return None  # current close must be back inside band (below upper)
        if current <= mid[-1]:
            return None  # must still be above midline
        stop = upper[-1] + stop_atr_mult * atr
        risk = stop - current
        if risk <= 0:
            return None
        target = current - risk * rr_target_mult

    return StrategySignal(
        strategy="mean_reversion_bb",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={
            "bb_upper": round(upper[-1], 2),
            "bb_mid": round(mid[-1], 2),
            "bb_lower": round(lower[-1], 2),
            f"sma_{trend_sma}": round(trend[-1], 2),
        },
    )


# ── Strategy 6: Mean reversion VWAP ──────────────────────────────────────────

def mean_reversion_vwap_signal(
    bars: list[dict],
    *,
    vwap_dev_pct: float = 1.5,
    reversal_pct: float = 0.3,
    stop_atr_mult: float = 0.5,
    rr_target_mult: float = 2.0,
    interval: str = "15m",
    direction: Literal["Bullish", "Bearish"] = "Bullish",
) -> StrategySignal | None:
    """VWAP mean-reversion signal (intraday only).

    Returns None if interval is not an intraday value.
    Bullish: price deviated vwap_dev_pct% below VWAP AND last bar reversed reversal_pct% back toward VWAP.
    Bearish: mirror logic above VWAP.
    """
    if interval not in ("1m", "5m", "15m", "30m", "1h"):
        return None
    if len(bars) < 30:
        return None

    vwap = _vwap(bars)
    if vwap <= 0:
        return None
    atr = _atr(bars)
    current = bars[-1]["close"]
    prev = bars[-2]["close"] if len(bars) >= 2 else current

    if direction == "Bullish":
        dev = (vwap - current) / vwap * 100
        if dev < vwap_dev_pct:
            return None   # not deviated enough below VWAP
        reversal = (current - prev) / prev * 100
        if reversal < reversal_pct:
            return None   # not reversing toward VWAP yet
        stop = current - stop_atr_mult * atr
        risk = current - stop
        if risk <= 0:
            return None
        target = current + risk * rr_target_mult
    else:  # Bearish
        dev = (current - vwap) / vwap * 100
        if dev < vwap_dev_pct:
            return None
        reversal = (prev - current) / prev * 100
        if reversal < reversal_pct:
            return None
        stop = current + stop_atr_mult * atr
        risk = stop - current
        if risk <= 0:
            return None
        target = current - risk * rr_target_mult

    return StrategySignal(
        strategy="mean_reversion_vwap",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"vwap": round(vwap, 2), "deviation_pct": round(dev, 2)},
    )


# ── Strategy 6b: Mean reversion VWAP (daily / rolling) ───────────────────────

def mean_reversion_vwap_daily_signal(
    bars: list[dict],
    *,
    vwap_lookback: int = 20,
    vwap_deviation_pct: float = 0.02,
    stop_atr_mult: float = 0.5,
    rr_target_mult: float = 2.0,
    direction: str = "Bullish",
) -> StrategySignal | None:
    """Rolling daily-VWAP mean-reversion signal (no intraday data needed).

    Bullish: bar[-2] closed >= vwap_deviation_pct below rolling VWAP,
             bar[-1] closes back above rolling VWAP.
    """
    if len(bars) < vwap_lookback + 2:
        return None

    window = bars[-(vwap_lookback + 2):-2]
    vwap = _vwap(window)
    if vwap <= 0:
        return None

    current = bars[-1]["close"]
    prev    = bars[-2]["close"]
    atr     = _atr(bars)
    if atr <= 0:
        return None

    if direction == "Bullish":
        if (vwap - prev) / vwap < vwap_deviation_pct:
            return None
        if current <= vwap:
            return None
        stop   = current - stop_atr_mult * atr
        risk   = current - stop
        if risk <= 0:
            return None
        target = current + risk * rr_target_mult
    else:
        if (prev - vwap) / vwap < vwap_deviation_pct:
            return None
        if current >= vwap:
            return None
        stop   = current + stop_atr_mult * atr
        risk   = stop - current
        if risk <= 0:
            return None
        target = current - risk * rr_target_mult

    dev_pct = abs(vwap - prev) / vwap
    return StrategySignal(
        strategy="mean_reversion_vwap_daily",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"rolling_vwap": round(vwap, 2), "deviation_pct": round(dev_pct * 100, 2)},
    )


# ── Strategy 7: Pre-breakout setup scanner ────────────────────────────────────

def breakout_setup_signal(
    bars: list[dict],
    symbol: str,
    *,
    atr_compression_ratio: float = 0.7,
    atr_avg_lookback: int = 20,
    range_atr_mult: float = 0.8,
    range_lookback_bars: int = 10,
    vol_compression_ratio: float = 0.8,
    resistance_proximity_pct: float = 0.05,
    swing_lookback: int = 50,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    # ── Fibonacci pullback ──
    fib_enabled: bool = False,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
) -> SetupSignal | None:
    """Pre-breakout setup scanner. Returns SetupSignal (NOT StrategySignal).

    Identifies stocks in consolidation near a key level, ready to break out.
    All four conditions must pass:
    1. ATR compression: current ATR < atr_compression_ratio × N-bar average ATR
    2. Range compression: range of last range_lookback_bars < range_atr_mult × current ATR
    3. Volume compression: last bar volume < vol_compression_ratio × 20-bar average
    4. Proximity: for Bullish, close within resistance_proximity_pct of swing_lookback-bar high from below
                  for Bearish, close within resistance_proximity_pct of swing_lookback-bar low from above
    """
    min_bars = max(atr_avg_lookback + 1, swing_lookback, 30)
    if len(bars) < min_bars:
        return None

    # ATR compression
    atr_series = _atr_series(bars, period=14)
    if len(atr_series) < atr_avg_lookback:
        return None
    current_atr = atr_series[-1]
    avg_atr = sum(atr_series[-atr_avg_lookback:]) / atr_avg_lookback
    if avg_atr <= 0 or current_atr >= atr_compression_ratio * avg_atr:
        return None
    atr_ratio = current_atr / avg_atr

    # Range compression
    recent = bars[-range_lookback_bars:]
    rng = max(b["high"] for b in recent) - min(b["low"] for b in recent)
    if current_atr <= 0 or rng >= range_atr_mult * current_atr:
        return None
    range_ratio = rng / current_atr if current_atr > 0 else 99

    # Volume compression
    vols = [b["volume"] for b in bars]
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else (vols[-1] if vols else 1)
    if avg_vol <= 0 or vols[-1] >= vol_compression_ratio * avg_vol:
        return None
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 99

    # Proximity to key level
    current = bars[-1]["close"]
    if direction == "Bullish":
        swing_level = _swing_high(bars, lookback=swing_lookback)
        prox = (swing_level - current) / swing_level if swing_level > 0 else 99
        if prox < 0 or prox > resistance_proximity_pct:
            return None   # must be below swing high but within tolerance
    else:
        swing_level = _swing_low(bars, lookback=swing_lookback)
        prox = (current - swing_level) / swing_level if swing_level > 0 else 99
        if prox < 0 or prox > resistance_proximity_pct:
            return None   # must be above swing low but within tolerance

    # Confidence score 0-100
    # Base weights: ATR 40%, vol 30%, prox 30%. When fib enabled: ATR 32%, vol 24%, prox 24%, fib 20%.
    atr_score  = max(0, 100 * (1 - atr_ratio / atr_compression_ratio))
    vol_score  = max(0, 100 * (1 - vol_ratio / vol_compression_ratio))
    prox_score = max(0, 100 * (1 - prox / resistance_proximity_pct)) if resistance_proximity_pct > 0 else 50

    fib_at_level: bool = False
    fib_dist_pct: float | None = None
    fib_label: str | None = None

    if fib_enabled:
        # Guard: if no valid fib levels are provided fall back to non-fib scoring
        # to avoid silently penalising the confidence score by 20 pts.
        _effective_fib_levels = [l for l in (fib_levels or []) if l in _FIB_RATIOS]
        if not _effective_fib_levels:
            fib_enabled = False
            fib_at_level = False
            fib_dist_pct = None
            fib_label = None

    if fib_enabled:
        fib_at_level, fib_dist_pct, fib_label = _fibonacci_pullback_signal(
            bars,
            direction,
            fib_swing_lookback=fib_swing_lookback,
            fib_levels=fib_levels,
            fib_tolerance_pct=fib_tolerance_pct,
        )
        # If fib helper returned None distance (insufficient bars), fall back to non-fib
        # rather than penalising the confidence score with a 0 fib_score.
        if fib_dist_pct is None and not fib_at_level:
            fib_enabled = False
        else:
            # fib_dist_pct is already in percent (e.g. 1.5 means 1.5% away).
            # Normalise against 2× tolerance expressed in the same percent scale.
            _tol_pct = fib_tolerance_pct * 100
            fib_score = 100 if fib_at_level else max(0, 100 * (1 - (fib_dist_pct or 100) / (_tol_pct * 2)))
            confidence = int(atr_score * 0.32 + vol_score * 0.24 + prox_score * 0.24 + fib_score * 0.20)

    if not fib_enabled:
        confidence = int(atr_score * 0.40 + vol_score * 0.30 + prox_score * 0.30)

    metrics: dict = {
        "atr_ratio":     round(atr_ratio, 3),
        "range_ratio":   round(range_ratio, 3),
        "vol_ratio":     round(vol_ratio, 3),
        "proximity_pct": round(prox * 100, 2),
        "swing_level":   round(swing_level, 2),
        "current_atr":   round(current_atr, 4),
    }
    if fib_enabled:
        metrics["fib_at_level"]  = fib_at_level
        metrics["fib_level_hit"] = fib_label
        metrics["fib_dist_pct"]  = fib_dist_pct

    return SetupSignal(
        strategy="breakout_setup",
        direction=direction,
        symbol=symbol,
        confidence=min(100, max(0, confidence)),
        metrics=metrics,
    )
