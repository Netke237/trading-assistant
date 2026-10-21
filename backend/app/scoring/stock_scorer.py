from __future__ import annotations
import copy
import logging
import math
import os
import yaml

logger = logging.getLogger(__name__)
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.services.config_health import config_health

Status = Literal["PASS", "CAUTION", "REJECT"]
Horizon = Literal["Intraday", "Swing", "Position"]
Direction = Literal["Bullish", "Bearish"]


@dataclass
class RuleResult:
    name: str           # "trend" | "pullback" | "trigger" | "event" | "vol"
    status: Status
    score: int          # 0–100 component score before weighting
    detail: dict        # arbitrary key-value pairs for UI explainability
    # False when the rule had nothing to measure (too few bars for its MA, no
    # benchmark series for relative strength) and `score` is a placeholder, not
    # a reading. The stock-scan direction gate removes such a name as "no data"
    # rather than judging the placeholder (decision
    # P3A-UNMEASURED-TREND-REMOVE-2026-09-25). Defaulted, so every existing
    # construction reads as measured.
    measured: bool = True


@dataclass
class StockScoreCard:
    symbol: str
    direction: Direction
    horizon: Horizon
    score: int                          # 0–100 final weighted score
    status: Status                      # derived from score via thresholds
    rules: list[RuleResult] = field(default_factory=list)
    volume_bonus: bool = False          # True if volume confirmation earned
    explanation: dict | None = None    # additive scan-time evidence, never a scoring input


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="scoring_rules.yaml",
    loader="stock_scorer._load_config",
    fn=_load_config,
    project=lambda doc: doc,
)


def _horizon_cfg(horizon: Horizon) -> dict:
    key = horizon.lower()   # "swing" | "intraday" | "position"
    return _load_config()["horizons"][key]


def resolve_rs_benchmark(horizon: Horizon, overrides: dict | None) -> str | None:
    """The benchmark name ("SPX", "NDX", ...) the trend rule will compare
    against for `horizon` with these `overrides`, or None when the effective
    trend method is not relative_strength (no benchmark series is needed).

    Mirrors score_stock's own resolution exactly: the `trend_method` and
    `rs_benchmark` override keys win over the horizon's config, and a config
    with no `method` is additive (see _rule_trend). The scan uses this to fetch
    the one benchmark series the scorer will read, so the two must not drift.
    """
    ov = overrides or {}
    tcfg = _horizon_cfg(horizon)["trend"]
    method = str(ov["trend_method"]) if "trend_method" in ov else tcfg.get("method", "additive")
    if method != "relative_strength":
        return None
    if "rs_benchmark" in ov:
        return str(ov["rs_benchmark"])
    return str(tcfg["relative_strength"].get("benchmark", "NDX"))


def effective_event_window(horizon: Horizon, overrides: dict | None) -> tuple[int, int]:
    """(reject_days, caution_days) that `_rule_event` applies for this horizon
    after the request's overrides -- the same int() coercion score_stock uses.
    Returned on ScanResult so the UI gates on the window the scan actually
    used, not on live Step-3 state that is neither persisted nor tied to the
    result it is displaying."""
    ec = _horizon_cfg(horizon)["event"]
    ov = overrides or {}
    reject = int(ov["event_reject_days"]) if ov.get("event_reject_days") is not None else int(ec["reject_days"])
    caution = int(ov["event_caution_days"]) if ov.get("event_caution_days") is not None else int(ec["caution_days"])
    return reject, caution


# Mirrors the scoring horizons' own hold presets in frontend/lib/horizonPresets.ts.
DEFAULT_HOLD_MAX: dict[Horizon, int] = {"Intraday": 2, "Swing": 15, "Position": 45}


def effective_veto_days(horizon: Horizon, overrides: dict | None, hold_max_days: int | None) -> int:
    """Earnings gate over the hold; the event rule's grading stays unchanged."""
    hold = hold_max_days if hold_max_days is not None else DEFAULT_HOLD_MAX[horizon]
    return max(effective_event_window(horizon, overrides)[0], hold)


def _thresholds() -> dict:
    return _load_config()["stock_score_thresholds"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    """Compute EMA series. Returns list same length as values (first period-1 values are SMA seed)."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _sma(values: list[float], period: int) -> list[float]:
    """Simple moving average series. Returns list of length len(values) - period + 1."""
    if len(values) < period:
        return []
    return [sum(values[i:i + period]) / period for i in range(len(values) - period + 1)]


def _slope(series: list[float], lookback: int = 5) -> float:
    """Linear regression slope over last `lookback` values. Positive = rising."""
    if len(series) < lookback:
        return 0.0
    y = series[-lookback:]
    n = len(y)
    x_mean = (n - 1) / 2
    y_mean = sum(y) / n
    num = sum((i - x_mean) * (y[i] - y_mean) for i in range(n))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def _wilder_smooth(data: list[float], period: int) -> list[float]:
    """Wilder's smoothing (running average form) — shared by _adx and _rsi.
    Returns a series of running averages, seeded by the simple average of the
    first `period` values."""
    if len(data) < period:
        return []
    avg = sum(data[:period]) / period
    result = [avg]
    for v in data[period:]:
        avg = (avg * (period - 1) + v) / period
        result.append(avg)
    return result


def _adx(bars: list[dict] | None, period: int = 14) -> float:
    """Average Directional Index using Wilder smoothing. Returns 0.0 if insufficient data."""
    if bars is None or len(bars) < period + 1:
        return 0.0

    tr_list: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []

    for i in range(1, len(bars)):
        h, l = bars[i]["high"], bars[i]["low"]
        pc = bars[i - 1]["close"]
        ph, pl = bars[i - 1]["high"], bars[i - 1]["low"]
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
        up_move = h - ph
        down_move = pl - l
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)

    atr_s = _wilder_smooth(tr_list, period)
    pdm_s = _wilder_smooth(plus_dm, period)
    mdm_s = _wilder_smooth(minus_dm, period)
    n = min(len(atr_s), len(pdm_s), len(mdm_s))
    if n == 0:
        return 0.0

    dx_vals: list[float] = []
    for i in range(n):
        atr_v = atr_s[i]
        if atr_v == 0:
            continue
        di_plus = 100.0 * pdm_s[i] / atr_v
        di_minus = 100.0 * mdm_s[i] / atr_v
        di_sum = di_plus + di_minus
        dx_vals.append(100.0 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0.0)

    adx_s = _wilder_smooth(dx_vals, period)
    return adx_s[-1] if adx_s else 0.0


def _relative_volume(volumes: list[float], lookback: int) -> float | None:
    """Ratio of the latest bar's volume to the mean of the preceding `lookback` bars.
    Returns None if there isn't enough history."""
    if len(volumes) < lookback + 1:
        return None
    avg_vol = sum(volumes[-lookback - 1: -1]) / lookback
    if avg_vol <= 0:
        return None
    return volumes[-1] / avg_vol


def _roc(closes: list[float], period: int) -> float:
    """Percent rate-of-change over last `period` bars. Returns 0.0 if insufficient data."""
    if len(closes) <= period:
        return 0.0
    base = closes[-(period + 1)]
    return (closes[-1] - base) / base * 100.0 if base != 0 else 0.0


# ---------------------------------------------------------------------------
# Rule 1: Trend — dispatcher + three methods
# ---------------------------------------------------------------------------

def _trend_crossover(
    closes: list[float],
    cfg: dict,
    direction: Direction,
    *,
    ma_func=None,
) -> RuleResult:
    if ma_func is None:
        ma_func = _ema
    cc = cfg["trend"]["crossover"]
    fast_p = cc["fast_ema"]
    slow_p = cc["slow_ema"]
    slow_required = cc["slow_slope_required"]
    fast_required = cc["fast_slope_required"]

    fast_ma = ma_func(closes, fast_p)
    slow_ma = ma_func(closes, slow_p)

    if not fast_ma or not slow_ma:
        return RuleResult("trend", "REJECT", 0, {"reason": "insufficient_data", "method": "crossover"},
                          measured=False)

    fast_val = fast_ma[-1]
    slow_val = slow_ma[-1]
    slow_slope = _slope(slow_ma)
    fast_slope = _slope(fast_ma)

    if direction == "Bearish":
        above = fast_val < slow_val
        slow_ok = slow_slope < 0
        fast_ok = fast_slope < 0
        if not above:
            return RuleResult("trend", "REJECT", 10,
                              {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                               "reason": "fast_above_slow_bearish", "method": "crossover"})
        if slow_required and not slow_ok:
            return RuleResult("trend", "REJECT", 20,
                              {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                               "reason": "slow_ma_rising_bearish", "method": "crossover"})
        if fast_required and not fast_ok:
            return RuleResult("trend", "REJECT", 20,
                              {"reason": "fast_ma_rising_required_bearish", "method": "crossover"})
        if not fast_ok:
            return RuleResult("trend", "CAUTION", 60,
                              {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                               "reason": "fast_ma_flat_bearish", "method": "crossover"})
        return RuleResult("trend", "PASS", 90,
                          {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2), "method": "crossover"})

    # Bullish
    above = fast_val > slow_val
    slow_ok = slow_slope > 0
    fast_ok = fast_slope > 0
    if not above:
        return RuleResult("trend", "REJECT", 10,
                          {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                           "reason": "fast_below_slow", "method": "crossover"})
    if slow_required and not slow_ok:
        return RuleResult("trend", "REJECT", 20,
                          {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                           "reason": "slow_ma_declining", "method": "crossover"})
    if fast_required and not fast_ok:
        return RuleResult("trend", "REJECT", 20,
                          {"reason": "fast_ma_declining_required", "method": "crossover"})
    if not fast_ok:
        return RuleResult("trend", "CAUTION", 60,
                          {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2),
                           "reason": "fast_ma_flat", "method": "crossover"})
    return RuleResult("trend", "PASS", 90,
                      {"fast_ma": round(fast_val, 2), "slow_ma": round(slow_val, 2), "method": "crossover"})


def _trend_additive(
    closes: list[float],
    cfg: dict,
    direction: Direction,
    *,
    bars: list[dict] | None = None,
) -> RuleResult:
    ac = cfg["trend"]["additive"]
    ma_type = str(ac.get("ma_type", "SMA")).upper()
    ma_func = _sma if ma_type == "SMA" else _ema
    period = int(ac["ma_period"])
    slope_lookback = int(ac["slope_lookback"])
    price_max = int(ac["price_max"])
    slope_max = int(ac["slope_max"])
    adx_max = int(ac["adx_max"])
    total_max = price_max + slope_max + adx_max

    ma_series = ma_func(closes, period)
    if not ma_series:
        return RuleResult("trend", "REJECT", 0, {"reason": "insufficient_data", "method": "additive"},
                          measured=False)

    current_close = closes[-1]
    current_ma = ma_series[-1]

    if direction == "Bullish":
        price_pts = price_max if current_close > current_ma else 0
    else:
        price_pts = price_max if current_close < current_ma else 0

    slope = _slope(ma_series, slope_lookback)
    if direction == "Bullish":
        slope_pts = slope_max if slope > 0 else 0
    else:
        slope_pts = slope_max if slope < 0 else 0

    adx_period = int(ac["adx_period"])
    adx_pass = float(ac["adx_pass"])
    adx_caution_thresh = float(ac["adx_caution"])
    adx_val = _adx(bars, adx_period) if bars is not None else 0.0

    if adx_val >= adx_pass:
        adx_pts = adx_max
    elif adx_val >= adx_caution_thresh:
        adx_pts = adx_max // 2
    else:
        adx_pts = 0

    raw = price_pts + slope_pts + adx_pts
    score = round(raw * 100 / total_max) if total_max > 0 else 0
    score = max(0, min(100, score))

    detail = {
        "method": "additive",
        "price_pts": price_pts,
        "slope_pts": slope_pts,
        "adx_pts": adx_pts,
        "adx_val": round(adx_val, 1),
        "price_max": price_max,
        "slope_max": slope_max,
        "adx_max": adx_max,
        "current_close": round(current_close, 2),
        "current_ma": round(current_ma, 2),
    }

    status_pass = float(ac.get("status_pass", 70))
    status_caution = float(ac.get("status_caution", 40))
    if score >= status_pass:
        status: Status = "PASS"
    elif score >= status_caution:
        status = "CAUTION"
    else:
        status = "REJECT"
    return RuleResult("trend", status, score, detail)


def _trend_relative_strength(
    closes: list[float],
    cfg: dict,
    direction: Direction,
    *,
    benchmark_closes: list[float] | None = None,
) -> RuleResult:
    rc = cfg["trend"]["relative_strength"]
    period = int(rc["rs_period"])
    pass_t = float(rc["rs_pass_threshold"])
    caution_t = float(rc["rs_caution_threshold"])
    benchmark = str(rc.get("benchmark", "NDX"))

    if benchmark_closes is None or len(benchmark_closes) <= period:
        logger.warning(
            "relative_strength trend method: no benchmark data for %s — falling back to CAUTION 50",
            benchmark,
        )
        return RuleResult(
            "trend", "CAUTION", 50,
            {"reason": "no_benchmark_data", "method": "relative_strength", "benchmark": benchmark},
            measured=False,
        )

    stock_roc = _roc(closes, period)
    bench_roc = _roc(benchmark_closes, period)
    rs = stock_roc - bench_roc
    if direction == "Bearish":
        rs = -rs

    detail = {
        "method": "relative_strength",
        "stock_roc": round(stock_roc, 2),
        "bench_roc": round(bench_roc, 2),
        "rs": round(rs, 2),
        "benchmark": benchmark,
        "period": period,
    }

    if rs > pass_t:
        return RuleResult("trend", "PASS", 90, detail)
    if rs >= caution_t:
        return RuleResult("trend", "CAUTION", 60, detail)
    return RuleResult("trend", "REJECT", 10, detail)


def _rule_trend(
    closes: list[float],
    cfg: dict,
    direction: Direction = "Bullish",
    *,
    ma_func=None,
    bars: list[dict] | None = None,
    benchmark_closes: list[float] | None = None,
) -> RuleResult:
    method = cfg["trend"].get("method", "additive")
    if method == "additive":
        return _trend_additive(closes, cfg, direction, bars=bars)
    if method == "relative_strength":
        return _trend_relative_strength(closes, cfg, direction, benchmark_closes=benchmark_closes)
    return _trend_crossover(closes, cfg, direction, ma_func=ma_func)


# ---------------------------------------------------------------------------
# Rule 2: Pullback — FVG helper
# ---------------------------------------------------------------------------

def _detect_fvg(bars: list[dict], direction: str) -> tuple[bool, float, float]:
    """
    Scan the last 30 bars for the most recent FVG that the current price falls inside.
    Returns (hit, gap_low, gap_high). gap_low/gap_high are 0.0 if no hit.

    Bullish FVG (for bullish direction):
        bar[i-1].high < bar[i+1].low  — upward gap left by bullish impulse
        gap = (bar[i-1].high, bar[i+1].low)

    Bearish FVG (for bearish direction):
        bar[i-1].low > bar[i+1].high  — downward gap left by bearish impulse
        gap = (bar[i+1].high, bar[i-1].low)
    """
    if len(bars) < 3:
        return False, 0.0, 0.0
    current_price = bars[-1]["close"]
    window = bars[-30:] if len(bars) >= 30 else bars
    # Scan from newest to oldest (skip first and last of window)
    for i in range(len(window) - 2, 0, -1):
        prev_bar  = window[i - 1]
        curr_bar  = window[i]      # noqa: F841 — middle candle (the gap candle)
        next_bar  = window[i + 1]
        if direction == "Bullish":
            # Bullish FVG: upward gap — prev_bar.high < next_bar.low
            gap_low  = prev_bar["high"]
            gap_high = next_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
        else:  # Bearish
            # Bearish FVG: downward gap — prev_bar.low > next_bar.high
            gap_low  = next_bar["high"]
            gap_high = prev_bar["low"]
            if gap_high > gap_low and gap_low <= current_price <= gap_high:
                return True, round(gap_low, 2), round(gap_high, 2)
    return False, 0.0, 0.0


# ---------------------------------------------------------------------------
# Rule 2: Pullback
# ---------------------------------------------------------------------------

def _atr(bars: list[dict], period: int) -> float:
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return 0.0
    trs = trs[-period:]
    return sum(trs) / len(trs)


def _rule_pullback(bars: list[dict], cfg: dict, direction: Direction = "Bullish") -> RuleResult:
    pc = cfg["pullback"]
    closes = [b["close"] for b in bars]

    lookback = pc["swing_high_lookback_bars"]
    min_ago = pc["swing_high_min_bars_ago"]
    window = bars[-(lookback + min_ago): -min_ago] if min_ago else bars[-lookback:]

    if not window:
        return RuleResult("pullback", "REJECT", 0, {"reason": "insufficient_data"})

    swing_high = max(b["high"] for b in window)
    swing_low = min(b["low"] for b in window)
    current_price = closes[-1]
    swing_range = swing_high - swing_low

    if swing_range <= 0:
        return RuleResult("pullback", "CAUTION", 50, {"reason": "flat_range"})

    if direction == "Bearish":
        # Bearish pullback: price bounced above swing_low toward resistance then rejected.
        # Retracement measured as how far price has risen from swing_low relative to the range.
        # Same fib thresholds apply but from the low side:
        #   shallow bounce (< fib_shallow_min) = no pullback yet, CAUTION
        #   golden zone = best entry signal, PASS
        retracement = (current_price - swing_low) / swing_range

        fib_result = None
        if retracement < pc["fib_shallow_min"]:
            fib_result = ("CAUTION", 45, "no_bounce_yet")
        elif retracement <= pc["fib_shallow_max"]:
            fib_result = ("CAUTION", 55, "shallow_bounce")
        elif retracement <= pc["fib_standard_max"]:
            fib_result = ("CAUTION", 65, "standard_bounce")
        elif retracement <= pc["fib_golden_max"]:
            fib_result = ("PASS", 88, "golden_zone")
        else:
            # Bounced too far — fall back to ATR before rejecting
            atr = _atr(bars, pc["atr_period"])
            if atr > 0:
                atr_mult = (current_price - swing_low) / atr
                if atr_mult < pc["atr_pass_min"]:
                    return RuleResult("pullback", "REJECT", 15,
                                      {"reason": "too_shallow_atr_bearish", "atr_mult": round(atr_mult, 2)})
                elif atr_mult <= pc["atr_pass_max"]:
                    return RuleResult("pullback", "PASS", 80,
                                      {"method": "atr_fallback", "atr_mult": round(atr_mult, 2)})
                elif atr_mult <= pc["atr_caution_max"]:
                    return RuleResult("pullback", "CAUTION", 55,
                                      {"method": "atr_fallback", "atr_mult": round(atr_mult, 2)})
            return RuleResult("pullback", "REJECT", 10,
                              {"reason": "bounce_too_deep", "retracement_pct": round(retracement * 100, 1)})

        status, score, reason = fib_result

        # FVG soft bonus: +8 pts when pullback has Fibonacci confluence AND price sits in an FVG
        fvg_hit, fvg_low, fvg_high = _detect_fvg(bars, direction)
        if fvg_hit and score >= 35:   # only boost CAUTION or better, not REJECT
            score = min(100, score + 8)

        detail: dict = {"retracement_pct": round(retracement * 100, 1), "reason": reason,
                        "swing_low": round(swing_low, 2), "current": round(current_price, 2)}
        detail["fvg_hit"]  = fvg_hit
        detail["fvg_gap"]  = [fvg_low, fvg_high] if fvg_hit else None
        return RuleResult("pullback", status, score, detail)

    # --- Bullish (original logic) ---
    retracement = (swing_high - current_price) / swing_range

    fib_result = None
    if retracement < pc["fib_shallow_min"]:
        fib_result = ("CAUTION", 45, "no_pullback_yet")
    elif retracement <= pc["fib_shallow_max"]:
        fib_result = ("CAUTION", 55, "shallow_pullback")
    elif retracement <= pc["fib_standard_max"]:
        fib_result = ("CAUTION", 65, "standard_pullback")
    elif retracement <= pc["fib_golden_max"]:
        fib_result = ("PASS", 88, "golden_zone")
    else:
        # Too deep — fall back to ATR check before rejecting
        atr = _atr(bars, pc["atr_period"])
        if atr > 0:
            atr_mult = (swing_high - current_price) / atr
            if atr_mult < pc["atr_pass_min"]:
                return RuleResult("pullback", "REJECT", 15,
                                  {"reason": "too_shallow_atr", "atr_mult": round(atr_mult, 2)})
            elif atr_mult <= pc["atr_pass_max"]:
                return RuleResult("pullback", "PASS", 80,
                                  {"method": "atr_fallback", "atr_mult": round(atr_mult, 2)})
            elif atr_mult <= pc["atr_caution_max"]:
                return RuleResult("pullback", "CAUTION", 55,
                                  {"method": "atr_fallback", "atr_mult": round(atr_mult, 2)})
        return RuleResult("pullback", "REJECT", 10,
                          {"reason": "too_deep", "retracement_pct": round(retracement * 100, 1)})

    status, score, reason = fib_result

    # FVG soft bonus: +8 pts when pullback has Fibonacci confluence AND price sits in an FVG
    fvg_hit, fvg_low, fvg_high = _detect_fvg(bars, direction)
    if fvg_hit and score >= 35:   # only boost CAUTION or better, not REJECT
        score = min(100, score + 8)

    detail: dict = {"retracement_pct": round(retracement * 100, 1), "reason": reason,
                    "swing_high": round(swing_high, 2), "current": round(current_price, 2)}
    detail["fvg_hit"]  = fvg_hit
    detail["fvg_gap"]  = [fvg_low, fvg_high] if fvg_hit else None
    return RuleResult("pullback", status, score, detail)


# ---------------------------------------------------------------------------
# Rule 3: Reversal Trigger
# ---------------------------------------------------------------------------

def _rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return []
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g_series = _wilder_smooth(gains, period)
    avg_l_series = _wilder_smooth(losses, period)
    # _wilder_smooth seeds its result with the un-incrementally-updated
    # starting average (element [0]) before any recursive Wilder update —
    # correct for _adx's own use (it only ever reads the last element, and
    # the seed row participates in the same running-average recurrence
    # either way). But _rule_trigger's divergence-window gates key off
    # len(rsi_vals) to decide whether enough history exists, and dropping
    # this seed keeps len(rsi_vals) — and therefore exactly which bar the
    # divergence check first activates on — identical to the pre-extraction
    # implementation, instead of one bar earlier at an exact
    # div_win/2*div_win boundary.
    rsi_vals = []
    for avg_g, avg_l in zip(avg_g_series[1:], avg_l_series[1:]):
        rs = avg_g / avg_l if avg_l > 0 else 100.0
        rsi_vals.append(100 - 100 / (1 + rs))
    return rsi_vals


def _macd_histogram(closes: list[float], fast: int, slow: int, signal: int) -> list[float]:
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    min_len = min(len(fast_ema), len(slow_ema))
    if min_len < signal:
        return []
    macd_line = [fast_ema[-(min_len - i)] - slow_ema[-(min_len - i)] for i in range(min_len)]
    signal_line = _ema(macd_line, signal)
    hist = [macd_line[-(len(signal_line) - i)] - signal_line[-(len(signal_line) - i)]
            for i in range(len(signal_line))]
    return hist


def _stoch(bars: list[dict], k: int = 14, d: int = 3) -> tuple[list[float], list[float]]:
    if len(bars) < k:
        return [], []
    k_vals = []
    for i in range(k - 1, len(bars)):
        window = bars[i - k + 1: i + 1]
        low_k = min(b["low"] for b in window)
        high_k = max(b["high"] for b in window)
        rng = high_k - low_k
        k_vals.append(100 * (bars[i]["close"] - low_k) / rng if rng > 0 else 50.0)
    d_vals = _ema(k_vals, d)
    return k_vals, d_vals


def _detect_candle(bars: list[dict], direction: Direction = "Bullish") -> tuple[bool, str]:
    """Check last bar(s) for a reversal candle matching direction. Returns (found, pattern_name)."""
    if not bars:
        return False, ""
    b = bars[-1]
    rng = b["high"] - b["low"]
    if rng < 1e-8:
        return False, ""
    body = abs(b["close"] - b["open"])
    body_top = max(b["close"], b["open"])
    body_bot = min(b["close"], b["open"])
    lower_wick = body_bot - b["low"]
    upper_wick = b["high"] - body_top

    if direction == "Bearish":
        # Shooting star: small body at bottom of range, large upper wick, close near low
        if (body >= 0.05 * rng and upper_wick >= 2 * body and
                lower_wick <= 0.10 * rng and (b["high"] - b["close"]) / rng >= 0.65):
            return True, "shooting_star"

        # Bearish Engulfing (needs prior bar)
        if len(bars) >= 2:
            prev = bars[-2]
            if (prev["close"] > prev["open"] and b["close"] < b["open"] and
                    b["open"] >= prev["close"] and b["close"] <= prev["open"] and
                    body >= 0.40 * rng):
                return True, "bearish_engulfing"

        # Evening Star (needs 3 bars)
        if len(bars) >= 3:
            b1, b2, b3 = bars[-3], bars[-2], bars[-1]
            b1_body = abs(b1["close"] - b1["open"])
            b2_body = abs(b2["close"] - b2["open"])
            b3_body = abs(b3["close"] - b3["open"])
            if (b1["close"] > b1["open"] and               # b1 bullish
                    b2_body < b1_body * 0.4 and             # b2 small body (doji/spinning top)
                    b3["close"] < b3["open"] and             # b3 bearish
                    b3_body >= b1_body * 0.5 and             # b3 substantial body
                    b3["close"] < (b1["open"] + b1["close"]) / 2):  # b3 closes into b1's body
                return True, "evening_star"

        return False, ""

    # --- Bullish patterns (original logic) ---
    # Hammer
    if (body >= 0.05 * rng and lower_wick >= 2 * body and
            upper_wick <= 0.10 * rng and (b["close"] - b["low"]) / rng >= 0.65):
        return True, "hammer"

    # Bullish Engulfing (needs prior bar)
    if len(bars) >= 2:
        prev = bars[-2]
        if (prev["close"] < prev["open"] and b["close"] > b["open"] and
                b["open"] <= prev["close"] and b["close"] >= prev["open"] and
                body >= 0.40 * rng):
            return True, "bullish_engulfing"

    # Morning Star (needs 2 prior bars)
    if len(bars) >= 3:
        c1, c2 = bars[-3], bars[-2]
        c1_body = abs(c1["close"] - c1["open"])
        c1_rng = c1["high"] - c1["low"]
        c2_body = abs(c2["close"] - c2["open"])
        c2_rng = c2["high"] - c2["low"] if c2["high"] - c2["low"] > 1e-8 else 1
        c3_close = b["close"]
        c1_mid = (c1["open"] + c1["close"]) / 2
        if (c1["close"] < c1["open"] and c1_body >= 0.40 * c1_rng and
                c2_body <= 0.20 * c2_rng and
                b["close"] > b["open"] and c3_close > c1_mid):
            return True, "morning_star"

    return False, ""


def _event_within(n: int, window: int, event) -> bool:
    """True if `event(i)` holds for some i in 1..window, where i names the event
    bar as series[-i] and its prior bar as series[-i - 1]. `n` is the length of the
    shortest series `event` reads, so the window is bounded by it (series[-n - 1]
    does not exist). window=1 tests only the last bar."""
    return any(event(i) for i in range(1, min(window, n - 1) + 1))


def _rule_trigger(
    bars: list[dict],
    cfg: dict,
    volumes: list[float],
    direction: Direction = "Bullish",
    scoring_mode: str = "options",
) -> tuple[RuleResult, bool]:
    """Returns (RuleResult, volume_bonus)."""
    tc = cfg["trigger"]
    closes = [b["close"] for b in bars]
    # setup_window_bars (TRADING-REVIEW-PHASE-C T7, review M4): a momentum event
    # counts if it happened on some bar k within the last W bars AND its state still
    # holds on the last bar. W=1 is the original last-bar-only behaviour. A value
    # below 1 would test no bar at all, so it reads as 1; config health warns
    # about it (Phase C hygiene T4).
    window = max(1, int(tc.get("setup_window_bars", 1)))

    candle_found, candle_name = _detect_candle(bars, direction)

    # ── MACD ──────────────────────────────────────────────────────────────────
    hist = _macd_histogram(closes, tc["macd_fast"], tc["macd_slow"], tc["macd_signal"])
    rising = tc["macd_histogram_rising"]
    if direction == "Bearish":
        # Histogram crosses DOWN at bar k (was positive, now zero/negative), with the
        # rising/falling confirmation applied at k; still <= 0 on the last bar.
        def _macd_event(i: int) -> bool:
            return (hist[-i - 1] > 0 and hist[-i] <= 0 and
                    (hist[-i] < hist[-i - 1] if rising else True))
        macd_pass = (len(hist) >= 2 and hist[-1] <= 0 and
                     _event_within(len(hist), window, _macd_event))
    else:
        def _macd_event(i: int) -> bool:
            return (hist[-i - 1] < 0 and hist[-i] >= 0 and
                    (hist[-i] > hist[-i - 1] if rising else True))
        macd_pass = (len(hist) >= 2 and hist[-1] >= 0 and
                     _event_within(len(hist), window, _macd_event))

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_vals = _rsi(closes, tc["rsi_period"])
    rsi_pass = False
    div_win = tc["rsi_div_window_bars"]

    if direction == "Bearish":
        rsi_ceiling = tc.get("rsi_ceiling", 60)
        if len(rsi_vals) >= 2:
            rsi_pass = (rsi_vals[-1] <= rsi_ceiling and _event_within(
                len(rsi_vals), window,
                lambda i: rsi_vals[-i - 1] > rsi_ceiling >= rsi_vals[-i]))
            if not rsi_pass and len(closes) >= div_win and len(rsi_vals) >= div_win:
                # Bearish divergence: price HH while RSI LH
                price_high_now  = max(closes[-div_win:])
                price_high_prev = max(closes[-2 * div_win:-div_win]) if len(closes) >= 2 * div_win else price_high_now
                rsi_high_now    = max(rsi_vals[-div_win:])
                rsi_high_prev   = max(rsi_vals[-2 * div_win:-div_win]) if len(rsi_vals) >= 2 * div_win else rsi_high_now
                if price_high_now > price_high_prev and rsi_high_now < rsi_high_prev:
                    rsi_pass = True
    else:
        rsi_floor = tc["rsi_floor"]
        if len(rsi_vals) >= 2:
            rsi_pass = (rsi_vals[-1] >= rsi_floor and _event_within(
                len(rsi_vals), window,
                lambda i: rsi_vals[-i - 1] < rsi_floor <= rsi_vals[-i]))
            if not rsi_pass and len(closes) >= div_win and len(rsi_vals) >= div_win:
                # Bullish divergence: price LL while RSI HL
                price_low_now  = min(closes[-div_win:])
                price_low_prev = min(closes[-2 * div_win:-div_win]) if len(closes) >= 2 * div_win else price_low_now
                rsi_low_now    = min(rsi_vals[-div_win:])
                rsi_low_prev   = min(rsi_vals[-2 * div_win:-div_win]) if len(rsi_vals) >= 2 * div_win else rsi_low_now
                if price_low_now < price_low_prev and rsi_low_now > rsi_low_prev:
                    rsi_pass = True

    # ── Stochastic ────────────────────────────────────────────────────────────
    stoch_k, stoch_d = _stoch(bars, tc["stoch_k"], tc["stoch_d"])
    # K and D are shorter than bars by different amounts but both end on the last
    # bar, so they are indexed from the end; the window is bounded by the shorter.
    stoch_n = min(len(stoch_k), len(stoch_d))
    if direction == "Bearish":
        # K exits overbought from above at bar k: was >= overbought, now K < D;
        # K still below D on the last bar.
        overbought = tc.get("stoch_overbought", 70) * (1 - tc.get("stoch_tolerance_pct", 5) / 100)
        stoch_pass = (stoch_n >= 2 and stoch_k[-1] < stoch_d[-1] and _event_within(
            stoch_n, window,
            lambda i: (stoch_k[-i - 1] >= overbought and stoch_k[-i] < stoch_d[-i] and
                       stoch_k[-i - 1] >= stoch_d[-i - 1])))
    else:
        oversold_threshold = tc["stoch_oversold"] * (1 + tc["stoch_tolerance_pct"] / 100)
        stoch_pass = (stoch_n >= 2 and stoch_k[-1] > stoch_d[-1] and _event_within(
            stoch_n, window,
            lambda i: (stoch_k[-i - 1] <= oversold_threshold and stoch_k[-i] > stoch_d[-i] and
                       stoch_k[-i - 1] <= stoch_d[-i - 1])))

    momentum_count = sum([macd_pass, rsi_pass, stoch_pass])
    required = tc["momentum_signals_for_pass"]

    # Volume bonus
    rvol = _relative_volume(volumes, tc["volume_lookback_bars"])
    vol_bonus = rvol is not None and rvol > tc["volume_multiplier"]

    detail = {
        "candle": candle_name or "none",
        "macd_pass": macd_pass,
        "rsi_pass": rsi_pass,
        "stoch_pass": stoch_pass,
        "momentum_count": momentum_count,
        "volume_bonus": vol_bonus,
        "setup_window_bars": window,
    }

    # ── Stock mode: candle = bonus (+15 pts), NOT a gate ─────────────────────
    if scoring_mode == "stock":
        if momentum_count >= required:
            base = 65
        elif momentum_count == 1:
            base = 40
        else:
            base = 10
            return RuleResult("trigger", "REJECT", base, detail), vol_bonus

        if candle_found:
            base = min(100, base + 15)
        if vol_bonus:
            base = min(100, base + tc["volume_bonus_pts"])

        status: Status = "PASS" if base >= 55 else "CAUTION"
        return RuleResult("trigger", status, base, detail), vol_bonus

    # ── Options mode: unchanged original logic ────────────────────────────────
    if not candle_found:
        if momentum_count >= required:
            return RuleResult("trigger", "CAUTION", 35, detail), vol_bonus
        elif momentum_count == 1:
            return RuleResult("trigger", "CAUTION", 20, detail), vol_bonus
        else:
            return RuleResult("trigger", "REJECT", 10, detail), vol_bonus

    base_score = 70 if momentum_count >= required else (45 if momentum_count == 1 else 20)
    if vol_bonus:
        base_score = min(100, base_score + tc["volume_bonus_pts"])

    if momentum_count >= required:
        return RuleResult("trigger", "PASS", base_score, detail), vol_bonus
    elif momentum_count == 1:
        return RuleResult("trigger", "CAUTION", base_score, detail), vol_bonus
    else:
        return RuleResult("trigger", "REJECT", base_score, detail), vol_bonus


# ---------------------------------------------------------------------------
# Rule 4: Event Context
# ---------------------------------------------------------------------------

def _rule_event(
    earnings_date: date | None,
    dividend_date: date | None,
    cfg: dict,
    scoring_mode: str = "options",
) -> RuleResult:
    ec = cfg["event"]
    today = date.today()
    worst_days: int | None = None
    event_label = "none"

    # Fix #3: the earnings distance is recorded on EVERY detail dict, even when
    # a nearer dividend names the event, so the options scan can veto on it.
    earnings_days = (earnings_date - today).days if earnings_date is not None else None
    if earnings_days is not None and earnings_days < 0:
        earnings_days = None
    base_detail: dict = {"earnings_days": earnings_days, "reject_days": int(ec["reject_days"])}
    if scoring_mode != "stock":
        # D4 (fix #3, amended 2026-10-03): unknown is surfaced, never SCORED --
        # ETFs have no earnings. The options scan caps a single stock's card at
        # CAUTION on it (routers/scan.py::_earnings_unknown_caps). A PAST date
        # means the next one is unknown, so it is flagged unknown too.
        base_detail["earnings_unknown"] = earnings_days is None

    for label, ev_date in [("earnings", earnings_date), ("dividend", dividend_date)]:
        if ev_date is None:
            continue
        days = (ev_date - today).days
        if days < 0:
            continue
        if worst_days is None or days < worst_days:
            worst_days = days
            event_label = label

    if worst_days is None:
        detail: dict = {"event": "none", **base_detail}
        if scoring_mode == "stock":
            detail["note"] = "Event weight is zero — shown for context only, does not affect stock score."
        return RuleResult("event", "PASS", 90, detail)

    detail = {
        "event": event_label,
        "days_to_event": worst_days,
        **base_detail,
    }

    if scoring_mode == "stock":
        # Apply thresholds for display — but weight is zero so score is unaffected.
        detail["note"] = "Event weight is zero — shown for context only, does not affect stock score."
        if worst_days < ec["reject_days"]:
            return RuleResult("event", "REJECT", 5, detail)
        elif worst_days < ec["caution_days"]:
            return RuleResult("event", "CAUTION", 55, detail)
        return RuleResult("event", "PASS", 90, detail)

    # ── Options mode ──────────────────────────────────────────────────────────
    if worst_days < ec["reject_days"]:
        return RuleResult("event", "REJECT", 5, detail)
    elif worst_days < ec["caution_days"]:
        return RuleResult("event", "CAUTION", 55, detail)
    return RuleResult("event", "PASS", 90, detail)


# ---------------------------------------------------------------------------
# Rule 5: Volatility Context
# ---------------------------------------------------------------------------

def _rule_vol(
    iv_rank: float | None,
    cfg: dict,
    *,
    # Which quantity iv_rank holds: "rank" (an IV rank),
    # "absolute" (IV 0-100), or "none". Defaults to "absolute" because that is
    # what every pre-2026-09-06 caller was in fact passing -- raw IV x 100
    # written into a field named for a percentile.
    iv_basis: str = "absolute",
    volumes: list[float] | None = None,
    scoring_mode: str = "options",
) -> RuleResult:
    # ── Stock mode: Relative Volume ───────────────────────────────────────────
    if scoring_mode == "stock":
        lookback = cfg["trigger"]["volume_lookback_bars"]
        rvol = _relative_volume(volumes or [], lookback)
        if rvol is None:
            return RuleResult("vol", "CAUTION", 45, {"rvol": None, "reason": "insufficient_volume_data"})
        detail = {"rvol": round(rvol, 2), "scored": True}
        if rvol >= 2.0:
            return RuleResult("vol", "PASS", 90, detail)
        if rvol >= 1.2:
            return RuleResult("vol", "PASS", 70, detail)
        if rvol >= 0.8:
            return RuleResult("vol", "CAUTION", 45, detail)
        return RuleResult("vol", "CAUTION", 20, detail)

    # ── Options mode: volatility ─────────────────────────────────────────────
    # `iv_basis` says WHICH QUANTITY `iv_rank` holds, and therefore which
    # thresholds may judge it (PHASE-A-NULL-IVRANK-2026-09-06):
    #   "rank"     -- an IV rank from IBKR/tastytrade -> iv_rank_* keys
    #   "absolute" -- absolute IV 0-100 from Tradier or the BS inversion
    #                 -> iv_abs_* keys, which carry the numbers this rule has
    #                    actually been applying all along
    # Judging an absolute level against percentile thresholds is the defect
    # this basis exists to prevent: a name at 45% IV is not at its own 45th
    # percentile, and one at 75% is not automatically expensive.
    vc = cfg["vol"]
    _rank = iv_basis == "rank"
    pass_key = "iv_rank_pass_max" if _rank else "iv_abs_pass_max"
    caution_key = "iv_rank_caution_max" if _rank else "iv_abs_caution_max"
    compressed_key = (
        "iv_rank_compressed_caution" if _rank else "iv_abs_compressed_caution"
    )
    if vc.get(pass_key) is None:
        # Threshold unset → skip vol scoring.
        # (Intraday always; Swing/Position in stock-scan path where no IV data is available)
        #
        # `iv_basis` is carried even here. Not scoring the figure does not stop
        # it being RENDERED: _safe(VolDetail, ...) keeps `iv_rank`, and
        # volDetailText prints it. Omitting the basis let VolDetail's default
        # answer instead, which reads "absolute" -- so an IV rank from a
        # rank source printed as "IV 45%" rather than "IV Rank 45" whenever the
        # horizon left iv_rank_pass_max unset. Same mislabel as
        # PHASE-A-NULL-IVRANK-2026-09-06, pointing the other way.
        return RuleResult("vol", "PASS", 90,
                          {"iv_rank": iv_rank, "iv_basis": iv_basis, "scored": False})
    if iv_rank is None:
        return RuleResult("vol", "CAUTION", 50, {"reason": "no_iv_data"})
    compressed = vc.get(compressed_key)
    pass_max = vc[pass_key]
    caution_max = vc[caution_key]
    detail = {"iv_rank": round(iv_rank, 1), "iv_basis": iv_basis}
    if compressed is not None and iv_rank < compressed:
        return RuleResult("vol", "CAUTION", 50, {**detail, "reason": "compressed_vol"})
    if iv_rank <= pass_max:
        return RuleResult("vol", "PASS", 90, detail)
    # ROUND 5 finding 8. `compressed` is guarded with `is not None` two lines up
    # and `caution_max` was not, so a config with a pass ceiling but a null
    # caution ceiling raised TypeError ('<=' between float and NoneType) -- a
    # 500 on the scan, not a scoring error. Currently unreachable through the UI
    # (handleHzChange replaces scanOverrides wholesale, so an IV ceiling cannot
    # survive a switch to Intraday), but the diff added two migrations that
    # SYNTHESISE iv_abs_pass_max into override dicts where it had never
    # appeared, so the shape is now constructible. A missing caution ceiling
    # means "no caution band", which is a REJECT above pass_max, not a crash.
    if caution_max is not None and iv_rank <= caution_max:
        return RuleResult("vol", "CAUTION", 55, detail)
    return RuleResult("vol", "REJECT", 10, {**detail, "reason": "iv_too_high"})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _status_from_score(score: int, thresholds: dict) -> Status:
    if score >= thresholds["pass"]:
        return "PASS"
    if score >= thresholds["caution"]:
        return "CAUTION"
    return "REJECT"


_STATUS_RANK = {"PASS": 2, "CAUTION": 1, "REJECT": 0}


def _worse(a: Status, b: Status) -> Status:
    return a if _STATUS_RANK[a] <= _STATUS_RANK[b] else b


def _regime_cap(conviction_pct: int, stability: str, gate: dict) -> Status:
    """Return the status cap imposed by the regime gate (demote-only, never adds points)."""
    if not gate.get("enabled", False):
        return "PASS"
    if conviction_pct <= gate["headwind_reject_pct"] and (
        not gate.get("require_stable_for_reject", True) or stability == "Stable"
    ):
        return "REJECT"
    if conviction_pct <= gate["headwind_caution_pct"]:
        return "CAUTION"
    return "PASS"


def _normalize_weight(val: float | int | None) -> float:
    """Normalize a score weight override to a canonical decimal fraction [0.0, 1.0].

    If a percentage value > 1.0 is passed (e.g. 40 or 100), converts it to a fraction
    (40 -> 0.40, 100 -> 1.0). Fractional values <= 1.0 (e.g. 0.01 for 1%, 0.40, 1.0)
    are returned directly.
    """
    if val is None:
        return 0.0
    f = float(val)
    if f > 1.0:
        return f / 100.0
    return max(0.0, f)


def score_stock(
    symbol: str,
    direction: Direction,
    horizon: Horizon,
    bars: list[dict],
    earnings_date: date | None = None,
    dividend_date: date | None = None,
    iv_rank: float | None = None,
    iv_basis: str = "absolute",
    overrides: dict | None = None,
    benchmark_candles: list[dict] | None = None,
    confidence: int | None = None,
    confidence_gate: dict | None = None,
    confidence_sample_size: int = 0,
    scoring_mode: Literal["stock", "options"] = "options",
    regime_signal: dict | None = None,
    regime_gate: dict | None = None,
    fundamentals: "FundamentalHealth | None" = None,
    fundamentals_gate: "dict | None" = None,
) -> StockScoreCard:
    """
    Score a stock for the given direction and horizon.

    Args:
        symbol:            Ticker symbol (e.g. "AAPL")
        direction:         "Bullish" or "Bearish"
        horizon:           "Intraday", "Swing", or "Position"
        bars:              List of OHLCV dicts from fetch_candles()
        earnings_date:     Next earnings date (None if unknown)
        dividend_date:     Next ex-dividend date (None if unknown)
        iv_rank:           The volatility figure, 0–100 (None if unavailable)
        iv_basis:          Which quantity iv_rank holds — "rank" (a true
                           percentile) or "absolute" (IV level). Decides
                           which threshold set judges it.
        overrides:         Optional dict of parameter overrides
        benchmark_candles: Optional OHLCV dicts for RS benchmark (e.g. NDX)

    Returns:
        StockScoreCard with weighted score, status, and per-rule breakdown.
    """
    cfg = copy.deepcopy(_horizon_cfg(horizon))
    ov = overrides or {}

    if ov:
        w = cfg["weights"]
        cc = cfg["trend"]["crossover"]
        ac = cfg["trend"]["additive"]
        rc = cfg["trend"]["relative_strength"]
        for key, val in ov.items():
            if   key == "weight_trend":            w["trend"]      = _normalize_weight(val)
            elif key == "weight_pullback":          w["pullback"]   = _normalize_weight(val)
            elif key == "weight_trigger":           w["trigger"]    = _normalize_weight(val)
            elif key == "weight_event":             w["event"]      = _normalize_weight(val)
            elif key == "weight_vol":               w["vol"]        = _normalize_weight(val)
            # crossover params
            elif key == "fast_ema":                cc["fast_ema"]   = int(val)
            elif key == "slow_ema":                cc["slow_ema"]   = int(val)
            # method selector
            elif key == "trend_method":            cfg["trend"]["method"] = str(val)
            # additive params
            elif key == "additive_ma_period":      ac["ma_period"]       = int(val)
            elif key == "additive_ma_type":        ac["ma_type"]         = str(val)
            elif key == "additive_slope_lookback": ac["slope_lookback"]  = int(val)
            elif key == "additive_adx_period":     ac["adx_period"]      = int(val)
            elif key == "additive_adx_pass":       ac["adx_pass"]        = float(val)
            elif key == "additive_adx_caution":    ac["adx_caution"]     = float(val)
            elif key == "additive_price_max":      ac["price_max"]       = int(val)
            elif key == "additive_slope_max":      ac["slope_max"]       = int(val)
            elif key == "additive_adx_max":        ac["adx_max"]         = int(val)
            # relative_strength params
            elif key == "rs_period":               rc["rs_period"]            = int(val)
            elif key == "rs_pass_threshold":       rc["rs_pass_threshold"]    = float(val)
            elif key == "rs_caution_threshold":    rc["rs_caution_threshold"] = float(val)
            elif key == "rs_benchmark":            rc["benchmark"]            = str(val)
            # other scoring params
            elif key == "rsi_period":              cfg["trigger"]["rsi_period"]              = int(val)
            elif key == "rsi_floor":               cfg["trigger"]["rsi_floor"]               = float(val)
            elif key == "macd_fast":               cfg["trigger"]["macd_fast"]               = int(val)
            elif key == "macd_slow":               cfg["trigger"]["macd_slow"]               = int(val)
            elif key == "macd_signal":             cfg["trigger"]["macd_signal"]             = int(val)
            elif key == "swing_high_lookback_bars": cfg["pullback"]["swing_high_lookback_bars"] = int(val)
            elif key == "atr_caution_max":         cfg["pullback"]["atr_caution_max"]        = float(val)
            # event_reject_days / event_caution_days: applied after this loop
            # through effective_event_window, the one function ScanResult's
            # echoed event_window also comes from, so the two cannot diverge.
            # Two thresholds, two quantities -- `_rule_vol` picks between them
            # by `iv_basis`, so an override that names only one of them can
            # only ever reach the basis it names
            # (PHASE-A-NULL-IVRANK-2026-09-06). Until this second handler
            # existed, `iv_rank_pass_max` was the sole knob and it wrote the
            # PERCENTILE key, which `_rule_vol` reads only when a rank source
            # answered -- so on the default path (no IBKR, no tastytrade, an
            # ABSOLUTE IV) the user's ceiling was silently inert: set it to 20
            # and a 30% absolute IV still returned PASS. Same shape as the
            # `max_iv_abs` handler added alongside `max_iv_rank` in
            # contract_validator.validate_contract.
            elif key == "iv_rank_pass_max":        cfg["vol"]["iv_rank_pass_max"]            = None if val is None else float(val)
            elif key == "iv_abs_pass_max":         cfg["vol"]["iv_abs_pass_max"]             = None if val is None else float(val)
            elif key == "volume_lookback_bars":    cfg["trigger"]["volume_lookback_bars"]    = int(val)
            elif key == "volume_multiplier":       cfg["trigger"]["volume_multiplier"]       = float(val)

    cfg["event"]["reject_days"], cfg["event"]["caution_days"] = effective_event_window(horizon, ov)

    ma_type = str(ov.get("ma_type", cfg["trend"]["crossover"].get("ma_type", "EMA"))).upper()
    ma_func = _sma if ma_type == "SMA" else _ema

    thresholds = _thresholds()
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    benchmark_closes = [b["close"] for b in benchmark_candles] if benchmark_candles else None

    trend_result            = _rule_trend(closes, cfg, direction, ma_func=ma_func, bars=bars, benchmark_closes=benchmark_closes)
    pullback_result         = _rule_pullback(bars, cfg, direction)
    trigger_result, vol_bonus = _rule_trigger(bars, cfg, volumes, direction, scoring_mode=scoring_mode)
    event_result            = _rule_event(earnings_date, dividend_date, cfg, scoring_mode=scoring_mode)
    vol_result              = _rule_vol(
        iv_rank, cfg,
        iv_basis=iv_basis,
        volumes=volumes,
        scoring_mode=scoring_mode,
    )

    rules = [trend_result, pullback_result, trigger_result, event_result, vol_result]

    weights = cfg["weights"]

    # Stock mode: event proximity is displayed but does not count toward score.
    # Zero the event weight and renormalize so other weights still sum to 1.0.
    if scoring_mode == "stock":
        weights = dict(weights)   # don't mutate the cached config
        weights["event"] = 0.0
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}

    name_to_weight = {
        "trend":    weights["trend"],
        "pullback": weights["pullback"],
        "trigger":  weights["trigger"],
        "event":    weights["event"],
        "vol":      weights["vol"],
    }

    weighted_score = sum(r.score * name_to_weight[r.name] for r in rules)
    final_score    = round(weighted_score)
    final_status   = _status_from_score(final_score, thresholds)
    raw_status = final_status
    caps: list[dict] = []

    def record_cap(name: str, cap: Status, before: Status, detail: dict, config: dict):
        caps.append({"name": name, "status": cap, "before": before,
                     "after": final_status, "detail": copy.deepcopy(detail),
                     "config": copy.deepcopy(config)})

    # Pullback timing veto: a REJECT pullback means the setup timing is wrong.
    # Cap at CAUTION so the candidate remains visible but cannot PASS.
    _pb = next((r for r in rules if r.name == "pullback"), None)
    if _pb is not None and _pb.status == "REJECT":
        before = final_status
        final_status = _worse(final_status, "CAUTION")
        record_cap("pullback_timing", "CAUTION", before, _pb.detail, {})

    # Confidence gate: demote-only. Append a confidence RuleResult and cap status.
    if confidence_gate is not None:
        from app.scoring.signal_confidence import status_cap, interpret, load_backtest_cfg
        cap = status_cap(confidence, confidence_gate)
        before = final_status
        final_status = _worse(final_status, cap)
        rules.append(RuleResult(
            name="confidence",
            status=cap,
            score=confidence if confidence is not None else 0,
            detail={
                "confidence": confidence,
                "sample_size": confidence_sample_size,
                "interpretation": interpret(
                    confidence, sample_size=confidence_sample_size, symbol=symbol,
                    min_samples=int(load_backtest_cfg(horizon)["min_samples"]),
                ),
            },
        ))
        record_cap("confidence", cap, before, rules[-1].detail, confidence_gate)

    # Regime gate: demote-only. Appends a regime RuleResult with score=0 and caps status.
    if regime_signal is not None and regime_gate is not None:
        cap = _regime_cap(regime_signal["conviction_pct"], regime_signal["stability"], regime_gate)
        before = final_status
        final_status = _worse(final_status, cap)
        rules.append(RuleResult(
            name="regime",
            status=cap,
            score=0,
            detail={**regime_signal},
        ))
        record_cap("regime", cap, before, rules[-1].detail, regime_gate)

    # Fundamentals gate (demote-only, Swing/Position only)
    if fundamentals is not None and fundamentals_gate is not None:
        from app.scoring.fundamentals_scorer import FundamentalHealth  # noqa: F401 (type used above)
        gate_enabled = fundamentals_gate.get("enabled", True)
        is_intraday = str(horizon).lower() == "intraday"

        if gate_enabled and not is_intraday:
            before = final_status
            health_score = fundamentals.score
            caution_below = fundamentals_gate.get("cautionBelow", 45)
            reject_below = fundamentals_gate.get("rejectBelow", 30)

            # Safety reject (both Bullish and Bearish)
            if fundamentals.safety_flags:
                final_status = _worse(final_status, "REJECT")
                fund_status: Status = "REJECT"
            # Soft demote (Bullish only)
            elif direction in ("Bullish", "bullish"):
                if health_score < reject_below:
                    final_status = _worse(final_status, "REJECT")
                    fund_status = "REJECT"
                elif health_score < caution_below:
                    final_status = _worse(final_status, "CAUTION")
                    fund_status = "CAUTION"
                else:
                    fund_status = "PASS"
            elif direction in ("Bearish", "bearish"):
                caution_above = fundamentals_gate.get("cautionAbove", 70)
                reject_above = fundamentals_gate.get("rejectAbove", 80)
                if health_score > reject_above:
                    final_status = _worse(final_status, "REJECT")
                    fund_status = "REJECT"
                elif health_score > caution_above:
                    final_status = _worse(final_status, "CAUTION")
                    fund_status = "CAUTION"
                else:
                    fund_status = "PASS"
            else:
                fund_status = "PASS"

            rules.append(RuleResult(
                name="fundamentals",
                status=fund_status,
                score=health_score,
                detail=fundamentals.detail,
            ))
            record_cap("fundamentals", fund_status, before,
                       {**fundamentals.detail, "score": health_score,
                        "safety_flags": list(fundamentals.safety_flags)}, fundamentals_gate)

    # Snapshot the resolved objects and RuleResults used above. Keep the
    # original weighted sum/rounding and all gate decisions authoritative.
    # Gate RuleResults are not weighted components, even when they have scores.
    components = {}
    for r in rules[:5]:
        rule_config = copy.deepcopy(cfg[r.name])
        if r.name == "trend":
            rule_config["crossover"]["ma_type"] = ma_type
        elif r.name == "vol" and scoring_mode == "stock":
            rule_config = {"volume_lookback_bars": cfg["trigger"]["volume_lookback_bars"],
                           "rvol_bands": [2.0, 1.2, 0.8]}
        components[r.name] = {
            "name": r.name, "wire_name": "volatility" if r.name == "vol" else r.name,
            "raw_score": r.score, "status": r.status, "measured": r.measured,
            "weight": name_to_weight[r.name],
            "contribution": r.score * name_to_weight[r.name],
            "detail": copy.deepcopy(r.detail), "config": rule_config,
        }
    explanation = {
        "version": 1, "symbol": symbol, "direction": direction, "horizon": horizon,
        "scoring_mode": scoring_mode, "iv_basis": iv_basis,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "score": final_score, "status": final_status, "raw_status": raw_status,
        "unrounded_score": weighted_score, "rounding": "python_round_ties_to_even",
        "pass_threshold": thresholds["pass"], "caution_threshold": thresholds["caution"],
        "weights": dict(name_to_weight), "components": components, "caps": caps,
        "gate_config": copy.deepcopy({"confidence": confidence_gate, "regime": regime_gate,
                                      "fundamentals": fundamentals_gate}),
    }

    return StockScoreCard(
        symbol=symbol,
        direction=direction,
        horizon=horizon,
        score=final_score,
        status=final_status,
        rules=rules,
        volume_bonus=vol_bonus,
        explanation=explanation,
    )
