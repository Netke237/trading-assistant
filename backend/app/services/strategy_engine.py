from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# STOCKS-HORIZON-T1 H1: every caller of a DAILY-bar strategy signal function
# (live scan single + multi, Analysis, strategy watch entry and reversal, daily
# composite confirmations, the backtest's per-bar slice, the tuner) hands it at
# most the last SIGNAL_WINDOW_BARS bars ending at the evaluated bar. One number,
# so a live signal and the backtest that validates it read the same window
# (`_ema` seeds and `_rsi` smooths from the window start, so the window length
# moves their values). Intraday paths keep their own windows. Every current
# search-grid combination needs at most this many bars (`bars_needed`).
SIGNAL_WINDOW_BARS = 400

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


def _fibonacci_pullback_detail(
    bars: list[dict],
    direction: Literal["Bullish", "Bearish"],
    *,
    current_price: float | None = None,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
    impulse_min_pct: float = 0.0,
    retracement_recency_bars: int = 0,
) -> dict:
    """Check if close is near a Fibonacci retracement level of the dominant swing move.

    For Bullish: swing low → swing high within fib_swing_lookback bars.
    Retracement levels are measured downward from the swing high.
    For Bearish: swing high → swing low. Retracement levels measured upward from swing low.

    impulse_min_pct: minimum (swing_high - swing_low) / swing_low to qualify as a
                     real impulse. 0.0 disables (backward compatible).
    retracement_recency_bars: for Bullish, the swing high must fall within the most
                              recent N bars; for Bearish, the swing low. 0 disables.

    Returns a dict:
        at_level:   bool
        dist_pct:   float|None — nearest level distance as a percentage
                    (e.g. 1.5 means 1.5% away)
        label:      str|None — nearest level label
        swing_low / swing_high: float|None — the window low/high the levels are
                    measured from; None only when the window has < 10 bars.
        at_level/dist_pct/label are (False, None, None) when impulse/recency
        checks fail. ``_fibonacci_pullback_signal`` returns the first three as
        the historical tuple.
    """
    if fib_levels is None:
        fib_levels = [23.6, 38.2, 50.0, 61.8]
    window = bars[-fib_swing_lookback:] if len(bars) >= fib_swing_lookback else bars
    if len(window) < 10:
        return {"at_level": False, "dist_pct": None, "label": None,
                "swing_low": None, "swing_high": None}

    swing_high = max(b["high"] for b in window)
    swing_low  = min(b["low"]  for b in window)

    def _out(at_level: bool, dist_pct: float | None, label: str | None) -> dict:
        return {"at_level": at_level, "dist_pct": dist_pct, "label": label,
                "swing_low": swing_low, "swing_high": swing_high}

    move = swing_high - swing_low
    if move <= 0:
        return _out(False, None, None)

    # Impulse size gate: skip trivial drifts that just cross a fib line.
    # Guard swing_low > 0 before division to avoid ZeroDivisionError on bad data.
    if impulse_min_pct > 0:
        if swing_low <= 0 or (move / swing_low) < impulse_min_pct:
            return _out(False, None, None)

    # Recency gate: the swing extreme (peak for bullish, trough for bearish) must
    # have occurred within the most recent N bars, confirming an active retracement.
    if retracement_recency_bars > 0:
        recent = bars[-retracement_recency_bars:] if len(bars) >= retracement_recency_bars else bars
        if direction == "Bullish":
            recent_high = max(b["high"] for b in recent)
            # Allow 0.5% slop: the peak may not be at exactly the lookback max
            if swing_high > 0 and abs(recent_high - swing_high) / swing_high > 0.005:
                return _out(False, None, None)
        else:
            recent_low = min(b["low"] for b in recent)
            if swing_low > 0 and abs(recent_low - swing_low) / swing_low > 0.005:
                return _out(False, None, None)

    close = (current_price if current_price is not None and current_price > 0
             else bars[-1]["close"])

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

    if best_label is None:
        return _out(False, None, None)

    at_level = best_dist_pct <= fib_tolerance_pct
    return _out(at_level, round(best_dist_pct * 100, 2), best_label)


def _fibonacci_pullback_signal(
    bars: list[dict],
    direction: Literal["Bullish", "Bearish"],
    *,
    current_price: float | None = None,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
    impulse_min_pct: float = 0.0,
    retracement_recency_bars: int = 0,
) -> tuple[bool, float | None, str | None]:
    """Tuple form of ``_fibonacci_pullback_detail``:
    (at_level: bool, nearest_pct: float|None, level_label: str|None).
    Returns (False, None, None) when impulse/recency checks fail.
    """
    d = _fibonacci_pullback_detail(
        bars,
        direction,
        current_price=current_price,
        fib_swing_lookback=fib_swing_lookback,
        fib_levels=fib_levels,
        fib_tolerance_pct=fib_tolerance_pct,
        impulse_min_pct=impulse_min_pct,
        retracement_recency_bars=retracement_recency_bars,
    )
    return d["at_level"], d["dist_pct"], d["label"]


# Public aliases so routers can import without depending on the private names
fibonacci_pullback_signal = _fibonacci_pullback_signal
fibonacci_pullback_detail = _fibonacci_pullback_detail


# ── Exit-target ladder ────────────────────────────────────────────────────────

_LADDER_MAX_RUNGS = 3
_LADDER_MIN_FALLBACK_R = 0.5


def _build_target_ladder(
    *,
    entry: float,
    stop: float,
    direction: str,
    primary: float | None,
    extensions: list[float | None],
    fallback_mult: float,
    min_rung_r: float = 0.0,
) -> list[float]:
    """Turn a strategy's exit thesis into a validated, nearest-first ladder.

    Single place where every degenerate case is handled, so no individual signal
    function has to. Callers pass their own objective as ``primary`` and their
    outward continuations as ``extensions`` — including ``None`` and values that
    may land on the wrong side of entry — and get back a ladder that is
    strictly on the profitable side of entry, strictly positive, strictly
    monotonic, and ordered nearest-first — or empty when no such rung exists
    (see Returns).

    WHY ``primary`` IS A SEPARATE ARGUMENT — the one thing not to "simplify".
    Pooling every candidate into one list and sorting by distance would let a
    generic R/ATR extension become ``ladder[0]`` whenever it happens to be
    nearer than the strategy's own objective, which is exactly the thing this
    rework exists to stop: ``ladder[0]`` is ``target_price``, and
    ``target_price`` is the only exit ``strategy_backtest`` can observe (it
    issues ``tp=sig.target_price``). It is not hypothetical — for
    ``mean_reversion_vwap`` the entry gate puts VWAP >= 1.5% away while
    ``risk = 0.5 ATR``, so ``entry + 2R`` is almost always nearer than VWAP.
    The primary leads whenever it is valid; an extension that is not strictly
    beyond the rung before it is DROPPED, never reordered ahead of it.

    Nearest-first is load-bearing, not cosmetic: ``alert_generator.py`` fires
    ``TP_HIT`` against ``targets[0]`` and nothing else.

    Rungs are DROPPED, never clamped, when they fail a test. Clamping a
    wrong-side value into place would manufacture a target the strategy never
    claimed; dropping it lets the next rung — or the fallback — take over
    honestly.

    WHY THERE IS NO R-RELATIVE FLOOR BY DEFAULT. The only thing ``_entry_side``
    and ``TP_HIT`` require is that a rung is finite, positive and *strictly*
    beyond entry after rounding. An R-relative "must be at least 0.5R away"
    floor sounds prudent and is actively harmful applied to a primary:
    ``ma_crossover``'s stop sits at the slow MA, which right after a fast cross
    can be far below price, so 0.5R there can exceed its 3-ATR objective — the
    floor would silently drop the one rung this rework leaves numerically
    unchanged and promote a 6-ATR extension instead. A poor reward:risk on a
    strategy's declared objective is real information; ``rr_ratio`` and the
    backtest are where it belongs. ``min_rung_r`` therefore defaults to 0 and
    has exactly one caller: ``resolve_multi_signal``, where a rung genuinely IS
    being re-used against a stop no variant derived it with.

    Args:
        entry:  signal entry price (> 0, caller-guaranteed).
        stop:   signal stop price. ``risk = abs(entry - stop)`` must be > 0;
                every caller already returns None before reaching here otherwise.
        direction: "Bullish" or "Bearish".
        primary: the strategy's own exit objective, or ``None`` when it is
                unavailable on this bar (e.g. too few bars for the short SMA).
        extensions: outward continuations, in the caller's own order; they are
                sorted nearest-first among themselves. ``None`` entries are
                ignored so a caller can pass an optional level unconditionally.
        fallback_mult: R multiple used for the guaranteed rung when every
                supplied rung is dropped. Floored at 0.5R.
        min_rung_r: optional minimum distance from entry, in R, applied to every
                supplied rung (primary included). Defaults to 0 — see above.

    Returns:
        1..3 prices, rounded to 2dp, strictly ordered away from entry. Empty
        when the inputs are degenerate (``risk <= 0`` or ``entry <= 0``), or on
        a BEARISH ladder whose every rung, the fallback included, lands at or
        below zero (risk larger than ~entry / fallback_mult). Every caller turns
        empty into "no signal on this bar": no positive short target exists, and
        emitting one anyway handed backtesting.py a negative ``tp`` that it
        asserts on, so the whole symbol was removed as a failed backtest.
    """
    sign = 1.0 if direction == "Bullish" else -1.0
    risk = abs(entry - stop)
    if risk <= 0 or not math.isfinite(risk) or entry <= 0 or not math.isfinite(entry):
        # Unreachable via the signal functions (each returns None on risk <= 0),
        # but this helper is public enough to be called from a future consumer.
        return []

    entry_r = round(entry, 2)
    floor = entry + sign * min_rung_r * risk

    def _valid(value: float | None) -> float | None:
        """Round to 2dp and keep only if strictly beyond entry (and the floor)."""
        if value is None or not math.isfinite(value) or value <= 0:
            return None
        if min_rung_r > 0 and sign * (value - floor) < 0:
            return None
        rounded = round(value, 2)
        # Positivity is re-tested AFTER rounding: a bearish rung in (0, 0.005)
        # rounds to 0.0, and as targets[0] that is a short with no take-profit
        # (backtesting.py skips a falsy tp) -- open question #49.
        if rounded <= 0:
            return None
        # A rung that rounds onto (or behind) entry is dropped rather than
        # nudged: _entry_side needs a strict inequality, and a one-cent target
        # would be worse than letting the next rung or the fallback take over.
        if sign * (rounded - entry_r) <= 0:
            return None
        return rounded

    ladder: list[float] = []

    head = _valid(primary)
    if head is not None:
        ladder.append(head)

    ext = sorted(
        (v for v in (_valid(e) for e in extensions) if v is not None),
        key=lambda v: sign * (v - entry),
    )
    for value in ext:
        if len(ladder) >= _LADDER_MAX_RUNGS:
            break
        if ladder:
            prev = ladder[-1]
            # Strictly beyond the previous rung — an extension that is nearer
            # than the primary is dropped, never reordered ahead of it.
            if sign * (value - prev) <= 0:
                continue
            # Dedupe within 0.1% of the previous rung: a squeezed mid-band and a
            # 2R extension really can coincide on some bars, and two
            # indistinguishable rungs in the UI is noise.
            if prev > 0 and abs(value - prev) / prev < 0.001:
                continue
        ladder.append(value)

    if not ladder:
        fallback = entry + sign * risk * max(fallback_mult, _LADDER_MIN_FALLBACK_R)
        rounded = round(fallback, 2)
        if sign * (rounded - entry_r) <= 0:
            # Sub-cent risk. One tick is the smallest thing _entry_side accepts.
            rounded = round(entry_r + sign * 0.01, 2)
        if rounded <= 0:
            # Only a bearish fallback can get here (bullish rungs sit above a
            # positive entry). Never clamped to a token positive price: that
            # would be a target the strategy never derived.
            return []
        ladder.append(rounded)

    return ladder


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
    #: Full nearest-first exit ladder. ``target_price`` is always ``targets[0]``
    #: — every existing consumer (strategy_backtest's ``tp=``, the strategy-watch
    #: evaluator, the composite trigger evaluator) reads ``target_price`` and is
    #: unaffected; ``targets`` is additive. Defaults to ``[]`` so a directly
    #: constructed signal (several tests do this) stays valid.
    targets:     list[float] = field(default_factory=list)

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
    # STOCK-PRES-P1: evidence behind `confidence` (sub-scores, weights,
    # contributions, unrounded sum) and the Fib swing low/high the Fib levels
    # were measured from (None when Fib was not used). Send-only.
    confidence_breakdown: dict | None = None
    fib_swing:            dict | None = None


# ── Strategy 1: Pullback to 20-EMA ───────────────────────────────────────────

def pullback_ema_signal(
    bars: list[dict],
    *,
    current_price: float | None = None,
    ema_period: int = 50,
    trend_ema: int = 100,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    exit_swing_lookback: int = 20,
    tolerance: float = 0.04,
    ma_type: str = "EMA",
    require_reversal: bool = False,
    min_signal_rr: float = 0.0,
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
    current  = (current_price if current_price is not None and current_price > 0
                else closes[-1])
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

    # Exit thesis: "prior high / trailing stop under higher lows" — the exit the
    # Step-4 picker has always shown the user. Rung 1 is the prior swing extreme
    # the pullback interrupted; rungs 2 and 3 are R extensions past it, which is
    # where rr_target_mult now lives (it no longer sets the only target, so it is
    # no longer in the WFO grid — see the plan's coupling section).
    #
    # _swing_high/_swing_low look at bars[-lookback:], which includes today. In a
    # valid pullback today's high is at or below the prior high by construction,
    # so including it is harmless; in the edge case where the swing extreme
    # equals the entry close (or a live current_price has already exceeded it)
    # the rung rounds onto/behind entry, is dropped, and the R extensions carry
    # the ladder.
    prior_extreme = (_swing_high(bars, lookback=exit_swing_lookback) if direction == "Bullish"
                     else _swing_low(bars, lookback=exit_swing_lookback))
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=prior_extreme,
        extensions=[
            current + _sign * risk * rr_target_mult,
            current + _sign * risk * rr_target_mult * 1.5,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]

    # Fix #6 / D7: SKIP, never clamp. A first target nearer than min_signal_rr R
    # needs a >90% win rate to pay costs; clamping would invent a target the
    # strategy never claimed (Chair, TRADING_REVIEW.md). D7 AMENDED 2026-10-03
    # (Kenneth): the mechanism ships DISABLED -- strategy_params.yaml sets
    # min_signal_rr 0.0 until the Phase B re-tune -- so by default this skips
    # nothing and fix #6 is mechanism-only.
    if min_signal_rr > 0 and abs(target - current) < min_signal_rr * risk:
        return None

    ma_label = ma_type.upper()
    return StrategySignal(
        strategy="pullback_ema",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
        detail={
            f"{ma_label.lower()}_{ema_period}": round(fast_val, 2),
            f"{ma_label.lower()}_{trend_ema}":  round(slow_val, 2),
            "prior_swing_extreme": round(prior_extreme, 2),
        },
    )


# ── Strategy 2: Breakout from tight base ─────────────────────────────────────

def breakout_base_signal(
    bars: list[dict],
    *,
    base_lookback: int = 20,
    atr_tight_max: float = 4.0,
    volume_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    measured_move_mult: float = 1.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (breakout uses close)
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
    # Pre-breakout ATR — excludes today's bar, same as base_bars above. A
    # second independent audit round caught the previous `_atr(bars)` (which
    # includes today): on a wide-range/gap breakout bar, that single bar can
    # dominate a 14-period ATR average (a 30-point range against a sub-1-point
    # base pushed ATR to 2.3+ in a reproduced case), inflating BOTH the tight-
    # base gate's denominator and the stop's `atr * 0.2` buffer with the very
    # volatility event the strategy is trying to trade — collapsing R:R back
    # below 1 even after the base_high/base_low anchor fix. Every other
    # reference level in this function (base_high, base_low) already excludes
    # today's bar; ATR was the one inconsistent scale.
    atr = _atr(bars[:-1])
    # Tight base: range < atr_tight_max * ATR. A 20-bar range scales roughly
    # with sqrt(base_lookback) ~= 4.5x ATR on a random walk — 1.5 (the old
    # default) was unfireable on any real data (2026-08-18 audit: observed
    # minimum 2.77x-3.22x across 4 real symbols over a full year). 4.0 keeps
    # this selective while staying reachable.
    if atr > 0 and (base_high - base_low) > atr_tight_max * atr:
        return None
    current = closes[-1]
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else vols[-1]
    if vols[-1] < avg_vol * volume_mult:
        return None
    if direction == "Bullish":
        if current <= base_high:
            return None
        # Stop anchored just under the BREAKOUT LEVEL (base_high), not the far
        # side of the base (base_low) — an adversarial audit round proved the
        # base_low anchor makes R:R < 1 for every possible input once the
        # target became the measured move instead of entry + risk*rr_mult:
        # risk = (base_high-base_low) + overshoot + buffer, reward =
        # (base_high-base_low) - overshoot, so risk > reward for any
        # overshoot > 0, which the entry gate above (current > base_high)
        # guarantees. Anchoring at base_high — "back inside the level that
        # was just broken" — is the classic breakout-invalidation pairing:
        # risk becomes just the overshoot plus a small ATR buffer, so it
        # scales with how far the breakout has already run rather than with
        # the whole base's width, and the measured-move target is reachable
        # at a real R:R again.
        #
        # A large GAP on the breakout bar itself (current far above base_high)
        # still produces a low R:R here on purpose, not as an unfixed bug: the
        # risk genuinely is entry-back-to-the-breakout-level, and a big gap has
        # already spent a chunk of the measured move before this signal even
        # fires. That is real information about a breakout that has already
        # run, the same "no R-relative floor by default" philosophy
        # _build_target_ladder documents elsewhere (see also ma_crossover's
        # stop, which can be several ATR wide by the same reasoning). What is
        # NOT acceptable — and is what `atr = _atr(bars[:-1])` above fixes — is
        # a wide-range/wick bar inflating ATR (and therefore the stop buffer)
        # with volatility from the very bar this signal is trying to trade.
        stop = base_high - atr * 0.2
        risk = current - stop
        if risk <= 0:
            return None
        detail = {"base_high": round(base_high, 2), "base_range_pct": round(base_range_pct * 100, 1)}
    else:  # Bearish breakdown below base low
        if current >= base_low:
            return None
        # Mirror of the Bullish fix above: anchored at base_low (the
        # breakdown level), not base_high (the far side of the base).
        stop = base_low + atr * 0.2
        risk = stop - current
        if risk <= 0:
            return None
        detail = {"base_low": round(base_low, 2), "base_range_pct": round(base_range_pct * 100, 1)}

    # Exit thesis: the MEASURED MOVE the Step-4 picker has always promised —
    # project the base height off the breakout LEVEL (base_high for a breakout,
    # base_low for a breakdown), not off entry. Projecting off entry would let a
    # gapping open inflate the target by the size of the gap, which is the
    # opposite of what a measured move means.
    #
    # base_high/base_low are already computed above and were previously used only
    # for the stop and the detail blob.
    base_height = base_high - base_low
    # A perfectly flat base gives height 0; one ATR is the natural stand-in for
    # "how far this thing travels". A gapping open can also put `current` above
    # anchor + height, in which case that rung is behind entry and is dropped.
    # If ATR is also 0 (degenerate data) every measured-move rung collapses onto
    # the breakout level and is dropped, leaving the rr_target_mult fallback.
    height = base_height if base_height > 0 else atr
    _sign = 1 if direction == "Bullish" else -1
    anchor = base_high if direction == "Bullish" else base_low
    farthest = anchor + _sign * height * (measured_move_mult + 1.0)
    # breakout_base is the only one of the seven strategies whose ENTIRE ladder
    # (primary and both extensions) is anchored to a fixed price level rather
    # than to entry — every other strategy's ATR/R extensions are entry-
    # relative and so can never fall behind entry no matter how far price has
    # already moved. A big enough gap on the breakout bar can outrun even the
    # farthest measured-move extension, dropping all three rungs and falling
    # through to `_build_target_ladder`'s generic degenerate-input fallback
    # (entry + risk*rr_target_mult) — which a third independent audit round
    # caught fabricating a plausible-looking, exactly-2.0x R:R target with zero
    # connection to the measured-move thesis this strategy exists to trade,
    # for a breakout that has already run ~24x past its own stated objective
    # in the reported repro. That fallback exists for genuinely degenerate
    # inputs (NaN, zero ATR) — not for "the thesis is already exhausted, so
    # invent a different one." Bail out here instead, matching every other
    # strategy's `return None` when its own objective is unavailable.
    #
    # Gated on `height > 0`: a zero-height base with zero pre-breakout ATR
    # (`height` itself is then 0, so `farthest == anchor`) has no real
    # measured-move distance to outrun in the first place — that IS the
    # genuinely degenerate case the generic fallback exists for, and
    # test_breakout_base_survives_a_zero_height_base pins exactly this.
    #
    # Rounded to 2dp before comparing: a fourth independent audit round found
    # that comparing raw floats here, while `_build_target_ladder` rounds
    # every candidate (and entry) to 2dp before its own strict-inequality
    # test, reopens this exact fabrication bug in a sub-cent band just below
    # the boundary — close enough that this pre-check says "proceed" but the
    # ladder builder then rounds `farthest` down onto (or behind) entry and
    # drops it too, falling through to the same fabricated fallback this
    # guard exists to prevent. Real (split/dividend-adjusted) prices are not
    # reliably clean to 2dp, so this band is reachable on real data, not just
    # a hand-picked test input.
    if height > 0 and _sign * (round(farthest, 2) - round(current, 2)) <= 0:
        return None
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=anchor + _sign * height * measured_move_mult,
        extensions=[
            anchor + _sign * height * (measured_move_mult + 0.5),
            farthest,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
    detail["base_height"] = round(base_height, 2)
    detail["measured_move_anchor"] = round(anchor, 2)

    return StrategySignal(
        strategy="breakout_base",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
        detail=detail,
    )


# ── Strategy 3: MA crossover 20/50 ───────────────────────────────────────────

def ma_crossover_signal(
    bars: list[dict],
    *,
    fast: int = 20,
    slow: int = 50,
    lookback: int = 10,
    atr_target_mult: float = 3.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (crossover uses close)
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
                risk   = current - stop
                if risk <= 0:
                    return None
            else:
                stop   = slow_ma[-1] + atr * 0.5
                risk   = stop - current
                if risk <= 0:
                    return None
            # A moving-average cross has no natural PRICE objective — its thesis
            # exit is a condition ("cross back"), not a level. So rung 1 keeps
            # the multiple this strategy has always used (3.0 ATR, now tunable as
            # atr_target_mult) and the ladder extends outward from there, rather
            # than inventing a nearer price target with no thesis behind it.
            #
            # This is the one strategy whose primary target is numerically
            # unchanged by this rework — which is only true because
            # _build_target_ladder applies no R-relative floor by default. This
            # strategy's stop sits at the slow MA, so right after a fast cross
            # `risk` can be several times ATR and a 0.5R floor would exceed the
            # 3-ATR objective, dropping it and promoting the 6-ATR extension.
            _sign = 1 if direction == "Bullish" else -1
            targets = _build_target_ladder(
                entry=current, stop=stop, direction=direction,
                primary=current + _sign * atr * atr_target_mult,
                extensions=[
                    current + _sign * atr * atr_target_mult * 1.5,
                    current + _sign * atr * atr_target_mult * 2.0,
                ],
                # atr == 0 drops every rung; fall back to the R multiple the
                # other strategies use so a degenerate series still trades.
                fallback_mult=2.0,
            )
            if not targets:
                return None
            target = targets[0]
            return StrategySignal(
                strategy="ma_crossover",
                direction=direction,
                entry_price=round(current, 2),
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr=round(atr, 2),
                targets=targets,
                detail={
                    f"sma_{fast}": round(fast_ma[-1], 2),
                    f"sma_{slow}": round(slow_ma[-1], 2),
                    # The "cross back down" exit the Step-4 picker promises is a
                    # CONDITION, not a price, and evaluating it needs per-bar
                    # state this stateless signal_fn(bars) -> levels shape does
                    # not have. The level is emitted for display so the card can
                    # show it; acting on it is Approach E's job (the strategy-
                    # watch state machine), explicitly deferred by this plan.
                    "cross_back_level": round(slow_ma[-1], 2),
                    "exit_rule": "cross_back",
                },
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
    exit_sma_period: int = 20,
    atr_target_mult: float = 2.5,
    require_choppy_regime: bool = False,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (mean-rev uses close)
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
        stop = _swing_low(bars, lookback=10) - atr * 0.2
        risk = current - stop
        if risk <= 0:
            return None
    else:  # Bearish — overbought in downtrend
        if closes[-1] >= trend[-1]:        return None   # must be below trend (downtrend context)
        if rsi[-1] <= rsi_overbought:      return None   # must be overbought
        if rsi[-1] >= rsi[-2]:             return None   # RSI must be rolling over (ticking down)
        stop = _swing_high(bars, lookback=10) + atr * 0.2
        risk = stop - current
        if risk <= 0:
            return None

    # Exit thesis: "RSI returns to mid". The price proxy for that is the SHORT-term
    # mean, NOT the trend SMA. The Bullish gate above requires close > trend[-1]
    # (oversold WITHIN an uptrend), so the 200-SMA sits BELOW entry — targeting it
    # would be targeting a loss. RSI is low precisely because price is stretched
    # below its short mean, so that mean is the level the snap-back reaches for.
    short_mean_series = _sma(closes, exit_sma_period)
    short_mean = short_mean_series[-1] if short_mean_series else None
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        # None when there are fewer bars than exit_sma_period — the helper
        # ignores it and the ATR extensions carry the ladder.
        primary=short_mean,
        extensions=[
            current + _sign * atr * atr_target_mult,
            current + _sign * atr * atr_target_mult * 1.5,
        ],
        fallback_mult=2.0,
    )
    if not targets:
        return None
    target = targets[0]

    return StrategySignal(
        strategy="mean_reversion_rsi",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
        detail={
            "rsi": round(rsi[-1], 1),
            f"sma_{trend_sma}": round(trend[-1], 2),
            **({f"sma_{exit_sma_period}": round(short_mean, 2)} if short_mean is not None else {}),
        },
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
    current_price: float | None = None,  # accepted for router compat; not used (mean-rev uses close)
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

    # Exit thesis: "return to mid-band / opposite band" — literally what the
    # Step-4 picker tells the user, and both levels are already computed above by
    # `upper, mid, lower = _bollinger(closes, bb_period, bb_std)`.
    #
    # The entry gates guarantee the mid-band is on the profitable side: Bullish
    # requires lower[-1] < current < mid[-1], Bearish requires
    # mid[-1] < current < upper[-1]. So the primary is always valid unless a
    # squeeze puts the mid within half a cent of entry, in which case it rounds
    # onto entry, is dropped, and the opposite band leads.
    #
    # Note the 2R extension is deliberately an EXTENSION, not a co-equal rung:
    # with stop_atr_mult 0.5 the risk here is small, so entry + 2R is routinely
    # NEARER than the mid-band. Pooling and sorting would make an arbitrary R
    # multiple the target again, which is exactly what this rework removes.
    _sign = 1 if direction == "Bullish" else -1
    opposite_band = upper[-1] if direction == "Bullish" else lower[-1]
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=mid[-1],
        extensions=[
            opposite_band,
            current + _sign * risk * rr_target_mult,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]

    return StrategySignal(
        strategy="mean_reversion_bb",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
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
    vwap_extension_atr: float = 0.5,
    interval: str = "15m",
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    current_price: float | None = None,  # accepted for router compat; not used (VWAP mean-rev uses close)
) -> StrategySignal | None:
    """VWAP mean-reversion signal (intraday only).

    Returns None if interval is not an intraday value.
    Bullish: price deviated vwap_dev_pct% below VWAP AND last bar reversed reversal_pct% back toward VWAP.
    Bearish: mirror logic above VWAP.
    """
    if interval not in ("1m", "5m", "15m", "30m", "1h", "4h"):  # "4h": decision P4B D2
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

    # Exit thesis: VWAP itself, then an extension past it. Valid here — and ONLY
    # here — because this variant's entry gate requires price to still be
    # DEVIATED from VWAP by vwap_dev_pct, so VWAP sits on the profitable side of
    # entry. Its daily sibling has the opposite gate; see below.
    #
    # This is THE strategy that proves why `primary` must be a separate argument:
    # the gate puts VWAP at least vwap_dev_pct (1.5%) away, while
    # risk = stop_atr_mult * atr (0.5 ATR on 15-minute bars). `entry + 2R` is
    # therefore almost always NEARER than VWAP, and a pooled nearest-first sort
    # would silently make an arbitrary 1-ATR multiple the target again — leaving
    # this strategy's exits exactly as they were before the rework.
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=vwap,
        extensions=[
            vwap + _sign * atr * vwap_extension_atr,
            current + _sign * risk * rr_target_mult,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]

    return StrategySignal(
        strategy="mean_reversion_vwap",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
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
    current_price: float | None = None,  # accepted for router compat; not used (VWAP mean-rev uses close)
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
    else:
        if (prev - vwap) / vwap < vwap_deviation_pct:
            return None
        if current >= vwap:
            return None
        stop   = current + stop_atr_mult * atr
        risk   = stop - current
        if risk <= 0:
            return None

    dev_pct = abs(vwap - prev) / vwap
    # Exit thesis: a RECLAIM-and-overshoot, NOT "return to VWAP".
    #
    # This variant's Bullish gate is `current > vwap` — the bar has already closed
    # back ABOVE the rolling VWAP, so VWAP is BELOW entry and the "return to VWAP"
    # target is achieved at entry. What the thesis actually says is that a
    # deviation of dev_pct below VWAP should mean-revert to a mirror deviation
    # above it. That mirror level is rung 1; R extensions follow.
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=vwap * (1 + _sign * dev_pct),
        extensions=[
            current + _sign * risk * rr_target_mult,
            current + _sign * risk * rr_target_mult * 1.5,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]

    return StrategySignal(
        strategy="mean_reversion_vwap_daily",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
        detail={"rolling_vwap": round(vwap, 2), "deviation_pct": round(dev_pct * 100, 2)},
    )


# ── Multi-signal resolution ──────────────────────────────────────────────────

def resolve_multi_signal(
    fired: list[StrategySignal],
    *,
    strategy: str = "mean_reversion_multi",
    fallback_mult: float = 2.0,
) -> StrategySignal | None:
    """Combine several confirming variant signals into one, deterministically.

    Replaces ``dataclasses.replace(fired[0], ...)``, which took its entry, stop
    and target from whichever variant the CALLER happened to list first. That is
    not non-deterministic — the same request always produced the same answer —
    but it is arbitrary: reordering the variant checkboxes in the UI silently
    moved every stop and every target. This function's answer depends only on the
    SET of fired variants, never on their order.

    Resolution rule (the conservative pairing):
      * stop   = the WIDEST of the variants' stops (furthest from entry). If any
                 one variant's invalidation has not been hit, the thesis is
                 intact, so the position should not already be stopped out.
      * ladder = every variant's rungs pooled as ``extensions`` (there is no
                 ``primary`` here — no single variant's objective outranks
                 another's) and re-sanitized against the resolved entry/stop,
                 which yields the TIGHTEST surviving rung first. Taking the
                 tightest target with the widest stop is deliberately the low-R:R
                 pairing: for a multi-confirmation entry the edge is the
                 confirmation count, not the R:R, and the alternative (tight stop
                 + far target) would flatter the numbers by pairing two levels no
                 single variant ever claimed together.
      * entry  = the anchor variant's. All variants that can appear here read the
                 same last close, so entries agree; the anchor is chosen by
                 alphabetical strategy name purely so the tie-break is stable.

    This is the ONE caller that passes a non-zero ``min_rung_r``. Everywhere else
    a rung is the strategy's own objective measured against its own stop, and the
    ladder builder deliberately does not second-guess it. Here a rung derived
    against one variant's tight stop is being re-used against a stop that may be
    many times wider, so a 0.6R target can become a 0.06R target that no variant
    ever proposed. Half an R is the floor for a rung to survive that transplant.

    The backtest measures this resolution (STOCKS-HORIZON-T1 H3): it runs
    ``multi_signal`` per bar, so the Step-6 win rate is the vote's own trades at
    these combined levels. Before H3 it used ``mean_reversion_rsi`` as a stand-in,
    so the RSI variant's own ladder was what the gate measured; that limitation
    is closed. The rule stays conservative rather than optimised.

    Returns None when ``fired`` is empty or the resolved risk is non-positive.
    """
    if not fired:
        return None

    ordered = sorted(fired, key=lambda s: s.strategy)
    anchor = ordered[0]
    direction = anchor.direction
    entry = anchor.entry_price

    if direction == "Bullish":
        stop = min(s.stop_price for s in ordered)
    else:
        stop = max(s.stop_price for s in ordered)

    if abs(entry - stop) <= 0:
        return None

    if len(ordered) == 1:
        # Nothing to merge: entry/stop above are exactly this variant's own, so
        # the 0.5R floor below — there to stop a rung transplanted from one
        # variant's tight stop surviving against another's much wider one — has
        # no transplant to guard against here. Applying it anyway would silently
        # discard this variant's own thesis rung (e.g. mean_reversion_bb's
        # mid-band, routinely well inside 0.5R of its own 0.5-ATR stop) in favor
        # of a generic R-multiple extension it never actually proposed as its
        # target. Keep its own ladder unchanged.
        targets = list(anchor.targets or [anchor.target_price])
    else:
        pooled: list[float | None] = []
        for s in ordered:
            pooled.extend(s.targets or [s.target_price])

        targets = _build_target_ladder(
            entry=entry, stop=stop, direction=direction,
            primary=None, extensions=pooled,
            fallback_mult=fallback_mult, min_rung_r=0.5,
        )
        if not targets:
            return None

    detail = {
        **anchor.detail,
        "confirmations": len(ordered),
        # Sorted, so this field is order-independent too — it was previously the
        # caller's request order.
        "fired": [s.strategy for s in ordered],
        # Single-variant calls skip the merge entirely (see above), so the
        # "widest_stop_tightest_target" label would be describing a resolution
        # that never ran.
        "resolution": "widest_stop_tightest_target" if len(ordered) > 1 else "single_variant_passthrough",
    }

    return StrategySignal(
        strategy=strategy,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=targets[0],
        atr=anchor.atr,
        targets=targets,
        detail=detail,
    )


# ── mean_reversion_multi: one params shape (STOCKS-HORIZON-T1 H3) ────────────
# {"variants": [...], "min_confirmations": n, "variant_params": {"<variant>": {...}}}
# — the same object for the live loop, the backtest, the profile and the tuner.

def _multi_variant_fns() -> dict:
    """The daily signal functions a multi variant can name, looked up at call
    time (the same set the scan's _SIGNAL_FNS names)."""
    return {
        "pullback_ema":              pullback_ema_signal,
        "breakout_base":             breakout_base_signal,
        "ma_crossover":              ma_crossover_signal,
        "mean_reversion_rsi":        mean_reversion_rsi_signal,
        "mean_reversion_bb":         mean_reversion_bb_signal,
        "mean_reversion_vwap":       mean_reversion_vwap_signal,
        "mean_reversion_vwap_daily": mean_reversion_vwap_daily_signal,
    }


def merge_multi_params(direction: str, profile: dict | None, request_overrides: dict | None) -> dict:
    """The effective multi params shape. ``variants`` / ``min_confirmations``:
    the request's when set, else the profile's. ``variant_params[v]`` = the
    variant's ``exit:`` block, then its DIRECTION BASELINE ``active:`` params,
    then the multi profile's ``variant_params[v]``, then the request's
    (``None`` = not set). The variant base is always the direction baseline,
    never a tuned profile of the standalone strategy. Inputs are not mutated.
    """
    from app.services import strategy_param_store as store
    profile = profile or {}
    req = request_overrides or {}
    out: dict = {}
    for key in ("variants", "min_confirmations"):
        value = req.get(key) if req.get(key) is not None else profile.get(key)
        if value is not None:
            out[key] = list(value) if key == "variants" else value
    prof_vp = profile.get("variant_params") or {}
    req_vp = req.get("variant_params") or {}
    variant_params: dict = {}
    for v in out.get("variants") or []:
        merged = store.get_exit(v)
        merged.update(store.get_active(v, direction))
        merged.update(prof_vp.get(v) or {})
        merged.update({k: val for k, val in (req_vp.get(v) or {}).items() if val is not None})
        variant_params[v] = merged
    out["variant_params"] = variant_params
    return out


def multi_signal(
    bars: list[dict],
    *,
    direction: Literal["Bullish", "Bearish"],
    params: dict,
    signal_fns: dict | None = None,
    fired_out: list | None = None,
) -> StrategySignal | None:
    """mean_reversion_multi's vote over the (already merged) params shape: each
    variant runs on ``bars`` with ``variant_params[v]``; when at least
    ``min_confirmations`` fire, ``resolve_multi_signal`` combines them.

    A variant that raises counts as not fired; a name with no signal function
    is skipped. ``mean_reversion_vwap`` (intraday) raises ``ValueError``: the
    loop only evaluates daily bars. ``signal_fns`` overrides the name -> function
    map (the scan passes its own); ``fired_out`` receives the fired signals.
    """
    variants = list(params["variants"])
    if "mean_reversion_vwap" in variants:
        raise ValueError("mean_reversion_vwap (intraday) is not supported in mean_reversion_multi")
    fns = signal_fns if signal_fns is not None else _multi_variant_fns()
    vparams = params.get("variant_params") or {}
    fired: list[StrategySignal] = []
    for v in variants:
        fn = fns.get(v)
        if fn is None:
            continue
        try:
            sig = fn(bars, direction=direction, **(vparams.get(v) or {}))
        except Exception:
            sig = None
        if sig is not None:
            fired.append(sig)
    if fired_out is not None:
        fired_out.extend(fired)
    if len(fired) < params["min_confirmations"]:
        return None
    return resolve_multi_signal(fired, strategy="mean_reversion_multi")


# ── Bars needed (STOCKS-HORIZON-T1 H1) ───────────────────────────────────────

# mean_reversion_multi's variants when params name none (the request default).
_MULTI_DEFAULT_VARIANTS = ("mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap_daily")


def _param(fn, params: dict, name: str):
    """params[name], else the signal function's own default for it."""
    if name in params and params[name] is not None:
        return params[name]
    import inspect
    return inspect.signature(fn).parameters[name].default


def _omm_bars_needed() -> int:
    """compute_omm (require_choppy_regime) at its defaults: `len(closes) <
    lookback + 2` returns None, and the current state ('Choppy', the only one
    that passes) must have at least min_obs labels."""
    from app.services.regime_omm import MIN_OBS, RETURN_LOOKBACK
    return max(RETURN_LOOKBACK + 2, MIN_OBS)


def bars_needed(strategy: str, params: dict | None = None) -> int:
    """The smallest bar count at which EVERY length guard of ``strategy``'s
    signal function can pass with ``params`` (missing keys = the function's
    defaults). One bar fewer and the signal is always None. Read from the
    guards themselves:

    * pullback_ema: ``len(bars) < trend_ema + 10``; both MAs need their period.
    * breakout_base: ``len(bars) < base_lookback + 5``.
    * ma_crossover: ``len(bars) < slow + 5``, and each SMA series needs
      ``lookback + 1`` values (``n - period + 1 >= lookback + 1``).
    * mean_reversion_rsi: ``len(bars) < trend_sma + rsi_period + 5`` (the RSI
      series' own ``>= 2`` values need only ``rsi_period + 3``).
    * mean_reversion_bb: ``len(bars) < trend_sma + bb_period + 5``.
    * mean_reversion_vwap_daily: ``len(bars) < vwap_lookback + 2``.
    * mean_reversion_vwap (intraday): ``len(bars) < 30``.
    * rsi / bb with ``require_choppy_regime``: also compute_omm's floor.
    * mean_reversion_multi: the max over its variants (``params["variants"]``,
      default the request's three), each with ``params["variant_params"][v]``.
    """
    if strategy in ("breakout_setup", "fibonacci_pullback"):
        from app.services.setup_entries import setup_bars_needed
        return setup_bars_needed(strategy, params)
    p = dict(params or {})
    if strategy == "pullback_ema":
        fn = pullback_ema_signal
        return max(_param(fn, p, "trend_ema") + 10, _param(fn, p, "ema_period"))
    if strategy == "breakout_base":
        return _param(breakout_base_signal, p, "base_lookback") + 5
    if strategy == "ma_crossover":
        fn = ma_crossover_signal
        slow, fast, lookback = (_param(fn, p, k) for k in ("slow", "fast", "lookback"))
        return max(slow + 5, fast + lookback, slow + lookback)
    if strategy == "mean_reversion_rsi":
        fn = mean_reversion_rsi_signal
        rsi_period = _param(fn, p, "rsi_period")
        need = max(_param(fn, p, "trend_sma") + rsi_period + 5, rsi_period + 3)
        return max(need, _omm_bars_needed()) if _param(fn, p, "require_choppy_regime") else need
    if strategy == "mean_reversion_bb":
        fn = mean_reversion_bb_signal
        need = _param(fn, p, "trend_sma") + _param(fn, p, "bb_period") + 5
        return max(need, _omm_bars_needed()) if _param(fn, p, "require_choppy_regime") else need
    if strategy == "mean_reversion_vwap_daily":
        return _param(mean_reversion_vwap_daily_signal, p, "vwap_lookback") + 2
    if strategy == "mean_reversion_vwap":
        return 30
    if strategy == "mean_reversion_multi":
        variants = p.get("variants") or _MULTI_DEFAULT_VARIANTS
        vparams = p.get("variant_params") or {}
        return max(bars_needed(v, vparams.get(v) or {}) for v in variants)
    raise ValueError(f"bars_needed: unknown strategy {strategy!r}")


# ── Strategy 7: Pre-breakout setup scanner ────────────────────────────────────

def breakout_setup_signal(
    bars: list[dict],
    symbol: str,
    *,
    current_price: float | None = None,
    atr_compression_ratio: float = 0.85,
    atr_avg_lookback: int = 20,
    range_atr_mult: float = 3.0,
    range_lookback_bars: int = 10,
    vol_compression_ratio: float = 0.9,
    resistance_proximity_pct: float = 0.05,
    swing_lookback: int = 50,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    require_trend: bool = True,
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
    current = (current_price if current_price is not None and current_price > 0
               else bars[-1]["close"])
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

    # Trend filter: coil must be on the right side of the trend MA.
    # Guards against surfacing bearish consolidations near resistance as bullish setups.
    if require_trend:
        closes_all = [b["close"] for b in bars]
        ema20 = _ema(closes_all, 20)
        if ema20:
            ema20_val = ema20[-1]
            if direction == "Bullish" and current < ema20_val:
                return None
            if direction == "Bearish" and current > ema20_val:
                return None

    # Confidence score 0-100
    # Base weights: ATR 30%, vol 25%, prox 45%. When fib enabled: ATR 24%, vol 20%, prox 36%, fib 20%.
    atr_score  = max(0, 100 * (1 - atr_ratio / atr_compression_ratio))
    vol_score  = max(0, 100 * (1 - vol_ratio / vol_compression_ratio))
    prox_score = max(0, 100 * (1 - prox / resistance_proximity_pct)) if resistance_proximity_pct > 0 else 50

    fib_at_level: bool = False
    fib_dist_pct: float | None = None
    fib_label: str | None = None
    fib_swing_low: float | None = None
    fib_swing_high: float | None = None

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
        _fib = _fibonacci_pullback_detail(
            bars,
            direction,
            fib_swing_lookback=fib_swing_lookback,
            fib_levels=fib_levels,
            fib_tolerance_pct=fib_tolerance_pct,
        )
        fib_at_level, fib_dist_pct, fib_label = _fib["at_level"], _fib["dist_pct"], _fib["label"]
        fib_swing_low, fib_swing_high = _fib["swing_low"], _fib["swing_high"]
        # If fib helper returned None distance (insufficient bars), fall back to non-fib
        # rather than penalising the confidence score with a 0 fib_score.
        if fib_dist_pct is None and not fib_at_level:
            fib_enabled = False
        else:
            # fib_dist_pct is already in percent (e.g. 1.5 means 1.5% away).
            # Normalise against 2× tolerance expressed in the same percent scale.
            _tol_pct = fib_tolerance_pct * 100
            fib_score = 100 if fib_at_level else max(0, 100 * (1 - (fib_dist_pct or 100) / (_tol_pct * 2)))
            unrounded = atr_score * 0.24 + vol_score * 0.20 + prox_score * 0.36 + fib_score * 0.20
            confidence = int(unrounded)
            weights = {"atr": 0.24, "vol": 0.20, "proximity": 0.36, "fib": 0.20}
            scores = {"atr": atr_score, "vol": vol_score, "proximity": prox_score, "fib": fib_score}

    if not fib_enabled:
        unrounded = atr_score * 0.30 + vol_score * 0.25 + prox_score * 0.45
        confidence = int(unrounded)
        weights = {"atr": 0.30, "vol": 0.25, "proximity": 0.45}
        scores = {"atr": atr_score, "vol": vol_score, "proximity": prox_score}

    # STOCK-PRES-P1: send the evidence behind `confidence` (no formula change).
    confidence_breakdown: dict = {
        "fib_used":   fib_enabled,
        "weights":    weights,
        "components": {
            name: {"score": scores[name], "weight": w, "contribution": scores[name] * w}
            for name, w in weights.items()
        },
        "unrounded":  unrounded,
        "confidence": min(100, max(0, confidence)),
    }
    fib_swing = {"low": fib_swing_low, "high": fib_swing_high} if fib_enabled else None

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
        confidence_breakdown=confidence_breakdown,
        fib_swing=fib_swing,
    )
