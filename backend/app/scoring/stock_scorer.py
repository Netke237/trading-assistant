from __future__ import annotations
import math
import os
import yaml
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

Status = Literal["PASS", "CAUTION", "REJECT"]
Horizon = Literal["Intraday", "Swing", "Position"]
Direction = Literal["Bullish", "Bearish"]


@dataclass
class RuleResult:
    name: str           # "trend" | "pullback" | "trigger" | "event" | "vol"
    status: Status
    score: int          # 0–100 component score before weighting
    detail: dict        # arbitrary key-value pairs for UI explainability


@dataclass
class StockScoreCard:
    symbol: str
    direction: Direction
    horizon: Horizon
    score: int                          # 0–100 final weighted score
    status: Status                      # derived from score via thresholds
    rules: list[RuleResult] = field(default_factory=list)
    volume_bonus: bool = False          # True if volume confirmation earned


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _horizon_cfg(horizon: Horizon) -> dict:
    key = horizon.lower()   # "swing" | "intraday" | "position"
    return _load_config()["horizons"][key]


def _thresholds() -> dict:
    return _load_config()["score_thresholds"]


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


# ---------------------------------------------------------------------------
# Rule 1: Trend
# ---------------------------------------------------------------------------

def _rule_trend(closes: list[float], cfg: dict, direction: Direction = "Bullish") -> RuleResult:
    fast_p = cfg["trend"]["fast_ema"]
    slow_p = cfg["trend"]["slow_ema"]
    slow_required = cfg["trend"]["slow_slope_required"]
    fast_required = cfg["trend"]["fast_slope_required"]

    fast_ema = _ema(closes, fast_p)
    slow_ema = _ema(closes, slow_p)

    if not fast_ema or not slow_ema:
        return RuleResult("trend", "REJECT", 0, {"reason": "insufficient_data"})

    fast_val = fast_ema[-1]
    slow_val = slow_ema[-1]
    slow_slope = _slope(slow_ema)
    fast_slope = _slope(fast_ema)

    if direction == "Bearish":
        # Bearish: fast_ema must be BELOW slow_ema; slow must be declining for PASS
        above = fast_val < slow_val   # inverted: fast below slow
        slow_falling = slow_slope < 0
        fast_falling = fast_slope < 0

        if not above:
            return RuleResult("trend", "REJECT", 10,
                              {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                               "reason": "fast_above_slow_bearish"})

        if slow_required and not slow_falling:
            return RuleResult("trend", "REJECT", 20,
                              {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                               "reason": "slow_ma_rising_bearish"})

        if fast_required and not fast_falling:
            return RuleResult("trend", "REJECT", 20,
                              {"reason": "fast_ma_rising_required_bearish"})

        if not fast_falling:
            # Fast flat but not required — CAUTION
            return RuleResult("trend", "CAUTION", 60,
                              {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                               "reason": "fast_ma_flat_bearish"})

        return RuleResult("trend", "PASS", 90,
                          {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2)})

    # --- Bullish (original logic) ---
    above = fast_val > slow_val
    slow_rising = slow_slope > 0
    fast_rising = fast_slope > 0

    if not above:
        return RuleResult("trend", "REJECT", 10,
                          {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                           "reason": "fast_below_slow"})

    if slow_required and not slow_rising:
        return RuleResult("trend", "REJECT", 20,
                          {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                           "reason": "slow_ma_declining"})

    if fast_required and not fast_rising:
        return RuleResult("trend", "REJECT", 20,
                          {"reason": "fast_ma_declining_required_on_horizon"})

    if not fast_rising:
        # Fast flat but not required — CAUTION
        return RuleResult("trend", "CAUTION", 60,
                          {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2),
                           "reason": "fast_ma_flat"})

    return RuleResult("trend", "PASS", 90,
                      {"fast_ema": round(fast_val, 2), "slow_ema": round(slow_val, 2)})


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
        return RuleResult("pullback", status, score,
                          {"retracement_pct": round(retracement * 100, 1), "reason": reason,
                           "swing_low": round(swing_low, 2), "current": round(current_price, 2)})

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
    return RuleResult("pullback", status, score,
                      {"retracement_pct": round(retracement * 100, 1), "reason": reason,
                       "swing_high": round(swing_high, 2), "current": round(current_price, 2)})


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
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    rsi_vals = []
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
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


def _rule_trigger(bars: list[dict], cfg: dict, volumes: list[float], direction: Direction = "Bullish") -> tuple[RuleResult, bool]:
    """Returns (RuleResult, volume_bonus)."""
    tc = cfg["trigger"]
    closes = [b["close"] for b in bars]

    candle_found, candle_name = _detect_candle(bars, direction)

    # MACD
    hist = _macd_histogram(closes, tc["macd_fast"], tc["macd_slow"], tc["macd_signal"])
    macd_pass = (len(hist) >= 2 and hist[-2] < 0 and hist[-1] >= 0 and
                 (hist[-1] > hist[-2] if tc["macd_histogram_rising"] else True))

    # RSI
    rsi_vals = _rsi(closes, tc["rsi_period"])
    rsi_pass = False
    rsi_floor = tc["rsi_floor"]
    if len(rsi_vals) >= 2:
        rsi_pass = rsi_vals[-2] < rsi_floor <= rsi_vals[-1]
        # Divergence: price lower low, RSI higher low within window
        if not rsi_pass:
            div_win = tc["rsi_div_window_bars"]
            if len(closes) >= div_win and len(rsi_vals) >= div_win:
                price_low_now = min(closes[-div_win:])
                price_low_prev = min(closes[-2 * div_win: -div_win]) if len(closes) >= 2 * div_win else price_low_now
                rsi_low_now = min(rsi_vals[-div_win:])
                rsi_low_prev = min(rsi_vals[-2 * div_win: -div_win]) if len(rsi_vals) >= 2 * div_win else rsi_low_now
                if price_low_now < price_low_prev and rsi_low_now > rsi_low_prev:
                    rsi_pass = True

    # Stochastic
    stoch_k, stoch_d = _stoch(bars, tc["stoch_k"], tc["stoch_d"])
    oversold_threshold = tc["stoch_oversold"] * (1 + tc["stoch_tolerance_pct"] / 100)
    stoch_pass = (len(stoch_k) >= 2 and len(stoch_d) >= 2 and
                  stoch_k[-2] <= oversold_threshold and stoch_k[-1] > stoch_d[-1] and
                  stoch_k[-2] <= stoch_d[-2])

    momentum_count = sum([macd_pass, rsi_pass, stoch_pass])
    required = tc["momentum_signals_for_pass"]

    # Volume bonus
    vol_bonus = False
    if len(volumes) >= tc["volume_lookback_bars"] + 1:
        avg_vol = sum(volumes[-tc["volume_lookback_bars"] - 1: -1]) / tc["volume_lookback_bars"]
        vol_bonus = volumes[-1] > avg_vol * tc["volume_multiplier"]

    detail = {
        "candle": candle_name or "none",
        "macd_pass": macd_pass,
        "rsi_pass": rsi_pass,
        "stoch_pass": stoch_pass,
        "momentum_count": momentum_count,
        "volume_bonus": vol_bonus,
    }

    if not candle_found:
        return RuleResult("trigger", "REJECT", 5, detail), vol_bonus

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
) -> RuleResult:
    ec = cfg["event"]
    today = date.today()
    worst_days: int | None = None
    event_label = "none"

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
        return RuleResult("event", "PASS", 90, {"event": "none"})

    detail = {"event": event_label, "days_to_event": worst_days}
    if worst_days < ec["reject_days"]:
        return RuleResult("event", "REJECT", 5, detail)
    elif worst_days < ec["caution_days"]:
        return RuleResult("event", "CAUTION", 55, detail)
    return RuleResult("event", "PASS", 90, detail)


# ---------------------------------------------------------------------------
# Rule 5: Volatility Context
# ---------------------------------------------------------------------------

def _rule_vol(iv_rank: float | None, cfg: dict) -> RuleResult:
    vc = cfg["vol"]

    if vc["iv_rank_pass_max"] is None:
        # Intraday — not scored
        return RuleResult("vol", "PASS", 90, {"iv_rank": iv_rank, "scored": False})

    if iv_rank is None:
        return RuleResult("vol", "CAUTION", 50, {"reason": "no_iv_data"})

    compressed = vc["iv_rank_compressed_caution"]
    pass_max = vc["iv_rank_pass_max"]
    caution_max = vc["iv_rank_caution_max"]

    detail = {"iv_rank": round(iv_rank, 1)}
    if compressed is not None and iv_rank < compressed:
        return RuleResult("vol", "CAUTION", 50, {**detail, "reason": "compressed_vol"})
    if iv_rank <= pass_max:
        return RuleResult("vol", "PASS", 90, detail)
    if iv_rank <= caution_max:
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


def score_stock(
    symbol: str,
    direction: Direction,
    horizon: Horizon,
    bars: list[dict],
    earnings_date: date | None = None,
    dividend_date: date | None = None,
    iv_rank: float | None = None,
) -> StockScoreCard:
    """
    Score a stock for the given direction and horizon.

    Args:
        symbol:         Ticker symbol (e.g. "AAPL")
        direction:      "Bullish" or "Bearish"
        horizon:        "Intraday", "Swing", or "Position"
        bars:           List of OHLCV dicts from fetch_candles()
        earnings_date:  Next earnings date (None if unknown)
        dividend_date:  Next ex-dividend date (None if unknown)
        iv_rank:        Current IV rank 0–100 (None if unavailable)

    Returns:
        StockScoreCard with weighted score, status, and per-rule breakdown.
    """
    cfg = _horizon_cfg(horizon)
    thresholds = _thresholds()
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]

    trend_result = _rule_trend(closes, cfg, direction)
    pullback_result = _rule_pullback(bars, cfg, direction)
    trigger_result, vol_bonus = _rule_trigger(bars, cfg, volumes, direction)
    event_result = _rule_event(earnings_date, dividend_date, cfg)
    vol_result = _rule_vol(iv_rank, cfg)

    rules = [trend_result, pullback_result, trigger_result, event_result, vol_result]

    weights = cfg["weights"]
    name_to_weight = {
        "trend": weights["trend"],
        "pullback": weights["pullback"],
        "trigger": weights["trigger"],
        "event": weights["event"],
        "vol": weights["vol"],
    }

    weighted_score = sum(r.score * name_to_weight[r.name] for r in rules)
    final_score = round(weighted_score)
    final_status = _status_from_score(final_score, thresholds)

    return StockScoreCard(
        symbol=symbol,
        direction=direction,
        horizon=horizon,
        score=final_score,
        status=final_status,
        rules=rules,
        volume_bonus=vol_bonus,
    )
