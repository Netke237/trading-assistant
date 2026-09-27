"""Market structure detection -- FVG, BOS, CHoCH, Order Blocks, divergence, Fibonacci, confluence, MTF alignment.

Pure functions only. No I/O. Candles are list[dict] with
{"time", "open", "high", "low", "close", "volume"}.
"""
from __future__ import annotations

import math
from typing import Union


FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calc_atr(candles: list[dict], period: int = 14) -> float:
    """Compute ATR (Average True Range) over the last `period` candles."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    window = trs[-period:]
    return sum(window) / len(window)


def _is_zone_signal(s: dict) -> bool:
    return s.get("kind") in ("FVG", "OrderBlock")


def _is_line_signal(s: dict) -> bool:
    return s.get("kind") in ("BOS", "CHoCH")


def _overlap(zone1: dict, zone2: dict) -> bool:
    """Check if two price zones overlap. Handles zone and line signals correctly."""
    if _is_line_signal(zone1):
        lo1 = hi1 = zone1.get("price", 0)
    else:
        lo1 = zone1.get("price_low", 0)
        hi1 = zone1.get("price_high", 0)
    if _is_line_signal(zone2):
        lo2 = hi2 = zone2.get("price", 0)
    else:
        lo2 = zone2.get("price_low", 0)
        hi2 = zone2.get("price_high", 0)
    return not (hi1 < lo2 or hi2 < lo1)


# ---------------------------------------------------------------------------
# Swing detection
# ---------------------------------------------------------------------------

def find_swings(candles: list[dict], lookback: int = 5) -> tuple[list[dict], list[dict]]:
    """Returns (swing_highs, swing_lows) -- each a list of {index, time, price}."""
    highs: list[dict[str, Union[int, str, float]]] = []
    lows: list[dict[str, Union[int, str, float]]] = []
    for i in range(lookback, len(candles) - lookback):
        window_h = [c["high"] for c in candles[i - lookback : i + lookback + 1]]
        if candles[i]["high"] == max(window_h):
            highs.append({"index": i, "time": candles[i]["time"], "price": candles[i]["high"]})
        window_l = [c["low"] for c in candles[i - lookback : i + lookback + 1]]
        if candles[i]["low"] == min(window_l):
            lows.append({"index": i, "time": candles[i]["time"], "price": candles[i]["low"]})
    return highs, lows


# ---------------------------------------------------------------------------
# FVG
# ---------------------------------------------------------------------------

def detect_fvg(candles: list[dict]) -> list[dict]:
    """Detect Fair Value Gaps (3-candle pattern) with mitigation tracking."""
    signals: list[dict] = []
    atr = _calc_atr(candles)
    for i in range(2, len(candles)):
        c0, c2 = candles[i - 2], candles[i]
        # Bullish FVG: c0.high < c2.low
        if c0["high"] < c2["low"]:
            gap = c2["low"] - c0["high"]
            confidence = min(100, int(gap / max(atr, 0.01) * 50))
            signals.append({
                "kind": "FVG", "direction": "bullish",
                "time_start": c0["time"], "time_end": None,
                "confirmed_at": c2["time"],
                "price_low": c0["high"], "price_high": c2["low"],
                "mitigated": False, "confidence": confidence,
                "mtf_aligned": False,
                "multi_tf": False,
            })
        # Bearish FVG: c0.low > c2.high
        elif c0["low"] > c2["high"]:
            gap = c0["low"] - c2["high"]
            confidence = min(100, int(gap / max(atr, 0.01) * 50))
            signals.append({
                "kind": "FVG", "direction": "bearish",
                "time_start": c0["time"], "time_end": None,
                "confirmed_at": c2["time"],
                "price_low": c2["high"], "price_high": c0["low"],
                "mitigated": False, "confidence": confidence,
                "mtf_aligned": False,
                "multi_tf": False,
            })
    # Mark mitigated: price returns to gap after pattern completes (skip c0, c1, c2)
    for sig in signals:
        start_idx = None
        for i, c in enumerate(candles):
            if c["time"] == sig["time_start"]:
                start_idx = i
                break
        if start_idx is not None:
            for c in candles[start_idx + 3:]:
                if c["low"] <= sig["price_high"] and c["high"] >= sig["price_low"]:
                    sig["mitigated"] = True
                    sig["time_end"] = c["time"]
                    break
    return signals


# ---------------------------------------------------------------------------
# BOS / CHoCH
# ---------------------------------------------------------------------------

def _is_duplicate_bos(signals: list[dict], new_price: float, direction: str) -> bool:
    """Return True if a same-direction BOS at a similar price (within 0.5%) was already emitted."""
    recent = [s for s in signals if s.get("kind") == "BOS" and s.get("direction") == direction]
    if not recent:
        return False
    last_price = recent[-1].get("price", 0)
    if last_price == 0:
        return False
    return abs(new_price - last_price) / last_price * 100 < 0.5


def detect_bos_choch(candles: list[dict], lookback: int = 5) -> list[dict]:
    """Detect Break of Structure and Change of Character."""
    highs, lows = find_swings(candles, lookback)
    signals: list[dict] = []
    trend: Union[str, None] = None

    for i in range(1, len(candles)):
        c = candles[i]
        # Bullish BOS: close above most recent swing high
        recent_high = None
        for h in reversed(highs):
            if h["index"] < i:
                recent_high = h
                break
        if recent_high and c["close"] > recent_high["price"]:
            kind = "CHoCH" if trend == "down" else "BOS"
            confidence = _bos_confidence(candles, i)
            if kind != "BOS" or not _is_duplicate_bos(signals, recent_high["price"], "bullish"):
                _end_idx = min(i + 30, len(candles) - 1)
                signals.append({
                    "kind": kind, "direction": "bullish",
                    "time": c["time"], "confirmed_at": c["time"], "price": recent_high["price"],
                    "confidence": confidence, "mtf_aligned": False,
                    "time_end": candles[_end_idx]["time"],
                })
            trend = "up"

        # Bearish BOS: close below most recent swing low
        recent_low = None
        for lval in reversed(lows):
            if lval["index"] < i:
                recent_low = lval
                break
        if recent_low and c["close"] < recent_low["price"]:
            kind = "CHoCH" if trend == "up" else "BOS"
            confidence = _bos_confidence(candles, i)
            if kind != "BOS" or not _is_duplicate_bos(signals, recent_low["price"], "bearish"):
                _end_idx = min(i + 30, len(candles) - 1)
                signals.append({
                    "kind": kind, "direction": "bearish",
                    "time": c["time"], "confirmed_at": c["time"], "price": recent_low["price"],
                    "confidence": confidence, "mtf_aligned": False,
                    "time_end": candles[_end_idx]["time"],
                })
            trend = "down"

    return signals


def _bos_confidence(candles: list[dict], idx: int) -> int:
    """BOS/CHoCH confidence: 70 base +15 if close at extreme +15 if volume above avg."""
    c = candles[idx]
    score = 70
    if c["close"] == c["high"] or c["close"] == c["low"]:
        score += 15
    if idx >= 20:
        avg_vol = sum(candles[j]["volume"] for j in range(idx - 20, idx)) / 20
        if c["volume"] > avg_vol:
            score += 15
    return min(score, 100)


# ---------------------------------------------------------------------------
# Order Blocks
# ---------------------------------------------------------------------------

def detect_order_blocks(candles: list[dict], bos_signals: list[dict] | None = None) -> list[dict]:
    """Detect Order Blocks: last bearish candle before bullish BOS, last bullish before bearish BOS.

    Accepts pre-computed BOS signals to avoid re-computation in the entry point.
    """
    if bos_signals is None:
        bos_signals = detect_bos_choch(candles)
    if not bos_signals:
        return []

    signals: list[dict] = []
    candle_index: dict[str, int] = {c["time"]: i for i, c in enumerate(candles)}
    bos_index: dict[str, int] = {}
    for bs in bos_signals:
        idx = candle_index.get(bs["time"])
        if idx is not None:
            bos_index[bs["time"]] = idx

    for bs in bos_signals:
        idx = bos_index.get(bs["time"])
        if idx is None or idx < 1:
            continue
        prev = candles[idx - 1]
        confidence = bs["confidence"]
        if bs["direction"] == "bullish":
            if prev["close"] < prev["open"]:
                signals.append({
                    "kind": "OrderBlock", "direction": "bullish",
                    "time_start": prev["time"], "time_end": None,
                    "confirmed_at": bs["time"],
                    "price_high": prev["high"], "price_low": prev["low"],
                    "mitigated": False, "confidence": confidence,
                    "mtf_aligned": False,
                })
        else:
            if prev["close"] > prev["open"]:
                signals.append({
                    "kind": "OrderBlock", "direction": "bearish",
                    "time_start": prev["time"], "time_end": None,
                    "confirmed_at": bs["time"],
                    "price_high": prev["high"], "price_low": prev["low"],
                    "mitigated": False, "confidence": confidence,
                    "mtf_aligned": False,
                })

    # Mark mitigated order blocks.
    # A bullish OB is mitigated when a candle closes below its low (price breaks through).
    # A bearish OB is mitigated when a candle closes above its high.
    # Merely touching the zone does not count — that is a normal OB interaction.
    for sig in signals:
        start_idx = None
        for i, c in enumerate(candles):
            if c["time"] == sig["time_start"]:
                start_idx = i
                break
        if start_idx is not None:
            for c in candles[start_idx + 1:]:
                if sig["direction"] == "bullish" and c["close"] < sig["price_low"]:
                    sig["mitigated"] = True
                    sig["time_end"] = c["time"]
                    break
                if sig["direction"] == "bearish" and c["close"] > sig["price_high"]:
                    sig["mitigated"] = True
                    sig["time_end"] = c["time"]
                    break

    return signals


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def _calc_rsi_values(candles: list[dict], period: int = 14) -> list[float]:
    """Returns RSI values aligned with candle indices (None for first `period`)."""
    rsi_vals: list[Union[float, None]] = [None] * period
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        change = candles[i]["close"] - candles[i - 1]["close"]
        if change > 0:
            gains += change
        else:
            losses += abs(change)
    avg_gain = gains / period
    avg_loss = losses / period
    rs = avg_gain / max(avg_loss, 0.0001)
    rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(period + 1, len(candles)):
        change = candles[i]["close"] - candles[i - 1]["close"]
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / max(avg_loss, 0.0001)
        rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    return rsi_vals  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def _calc_macd_histogram(candles: list[dict]) -> list[float]:
    """Returns MACD histogram values aligned with candle indices."""
    close_prices = [c["close"] for c in candles]
    ema12 = _calc_ema(close_prices, 12)
    ema26 = _calc_ema(close_prices, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(ema12))]
    signal_line = _calc_ema(macd_line, 9)
    hist = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]
    return hist


def _calc_ema(data: list[float], period: int) -> list[float]:
    multiplier = 2.0 / (period + 1)
    ema: list[float] = []
    for i, val in enumerate(data):
        if i == 0:
            ema.append(val)
        else:
            ema.append((val - ema[-1]) * multiplier + ema[-1])
    return ema


# ---------------------------------------------------------------------------
# Divergence detection (RSI + MACD)
# ---------------------------------------------------------------------------

def _divergence_confidence(is_regular: bool, bar_count: int) -> int:
    """Divergence confidence: 60 base +20 for regular +20 for multi-bar (>=3)."""
    score = 60
    if is_regular:
        score += 20
    if bar_count >= 3:
        score += 20
    return min(score, 100)


def detect_rsi_divergence(candles: list[dict]) -> list[dict]:
    """Detect regular + hidden RSI divergence."""
    if len(candles) < 30:
        return []
    rsi_vals = _calc_rsi_values(candles)
    return _detect_divergence(candles, rsi_vals, "RSI")


def detect_macd_divergence(candles: list[dict]) -> list[dict]:
    """Detect regular + hidden MACD divergence."""
    if len(candles) < 30:
        return []
    hist = _calc_macd_histogram(candles)
    return _detect_divergence(candles, hist, "MACD")


def _detect_divergence(candles: list[dict], indicator_vals: list[Union[float, None]], indicator: str) -> list[dict]:
    """Generic divergence detector: price vs indicator on swing points."""
    signals: list[dict] = []
    if len(candles) < 30:
        return signals

    # W2-STRUCT: a swing at index i exists only once `lookback` bars to its right
    # have closed, so a divergence is confirmed at candles[second_swing + lookback].
    lookback = 5
    price_swing_highs, price_swing_lows = find_swings(candles, lookback=lookback)
    ind_swing_highs = _find_indicator_swings(candles, indicator_vals, price_swing_highs, "high")
    ind_swing_lows = _find_indicator_swings(candles, indicator_vals, price_swing_lows, "low")

    # Regular bearish divergence: price HH, indicator LH
    for i in range(1, len(price_swing_highs)):
        ph0, ph1 = price_swing_highs[i - 1], price_swing_highs[i]
        if ph1["price"] > ph0["price"]:
            ih0 = _closest_indicator_swing(ind_swing_highs, ph0)
            ih1 = _closest_indicator_swing(ind_swing_highs, ph1)
            if ih0 and ih1 and ih1["value"] < ih0["value"]:
                bar_count = abs(ph1["index"] - ph0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bearish",
                    "indicator": indicator, "divergence_type": "regular",
                    "time_start": ph0["time"], "time_end": ph1["time"],
                    "confirmed_at": candles[ph1["index"] + lookback]["time"],
                    "price_start": ph0["price"], "price_end": ph1["price"],
                    "confidence": _divergence_confidence(True, bar_count),
                    "mtf_aligned": False,
                })

    # Regular bullish divergence: price LL, indicator HL
    for i in range(1, len(price_swing_lows)):
        pl0, pl1 = price_swing_lows[i - 1], price_swing_lows[i]
        if pl1["price"] < pl0["price"]:
            il0 = _closest_indicator_swing(ind_swing_lows, pl0)
            il1 = _closest_indicator_swing(ind_swing_lows, pl1)
            if il0 and il1 and il1["value"] > il0["value"]:
                bar_count = abs(pl1["index"] - pl0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bullish",
                    "indicator": indicator, "divergence_type": "regular",
                    "time_start": pl0["time"], "time_end": pl1["time"],
                    "confirmed_at": candles[pl1["index"] + lookback]["time"],
                    "price_start": pl0["price"], "price_end": pl1["price"],
                    "confidence": _divergence_confidence(True, bar_count),
                    "mtf_aligned": False,
                })

    # Hidden bullish divergence: price HL (higher low), indicator LL (lower low)
    for i in range(1, len(price_swing_lows)):
        pl0, pl1 = price_swing_lows[i - 1], price_swing_lows[i]
        if pl1["price"] > pl0["price"]:   # price makes higher low
            il0 = _closest_indicator_swing(ind_swing_lows, pl0)
            il1 = _closest_indicator_swing(ind_swing_lows, pl1)
            if il0 and il1 and il1["value"] < il0["value"]:  # indicator makes lower low
                bar_count = abs(pl1["index"] - pl0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bullish",
                    "indicator": indicator, "divergence_type": "hidden",
                    "time_start": pl0["time"], "time_end": pl1["time"],
                    "confirmed_at": candles[pl1["index"] + lookback]["time"],
                    "price_start": pl0["price"], "price_end": pl1["price"],
                    "confidence": _divergence_confidence(False, bar_count),
                    "mtf_aligned": False,
                })

    # Hidden bearish divergence: price LH (lower high), indicator HH (higher high)
    for i in range(1, len(price_swing_highs)):
        ph0, ph1 = price_swing_highs[i - 1], price_swing_highs[i]
        if ph1["price"] < ph0["price"]:   # price makes lower high
            ih0 = _closest_indicator_swing(ind_swing_highs, ph0)
            ih1 = _closest_indicator_swing(ind_swing_highs, ph1)
            if ih0 and ih1 and ih1["value"] > ih0["value"]:  # indicator makes higher high
                bar_count = abs(ph1["index"] - ph0["index"]) + 1
                signals.append({
                    "kind": "Divergence", "direction": "bearish",
                    "indicator": indicator, "divergence_type": "hidden",
                    "time_start": ph0["time"], "time_end": ph1["time"],
                    "confirmed_at": candles[ph1["index"] + lookback]["time"],
                    "price_start": ph0["price"], "price_end": ph1["price"],
                    "confidence": _divergence_confidence(False, bar_count),
                    "mtf_aligned": False,
                })

    return signals


def _find_indicator_swings(candles: list[dict], ind_vals: list[Union[float, None]],
                            price_swings: list[dict], direction: str) -> list[dict]:
    """For each price swing, find the indicator peak/trough within +/-2 candles."""
    result: list[dict] = []
    for ps in price_swings:
        idx = ps["index"]
        window_slice = ind_vals[max(0, idx - 2):min(len(ind_vals), idx + 3)]
        valid = [(i, v) for i, v in enumerate(window_slice) if v is not None]
        if not valid:
            continue
        if direction == "high":
            best = max(valid, key=lambda x: x[1])
        else:
            best = min(valid, key=lambda x: x[1])
        result_idx = max(0, idx - 2) + best[0]
        result.append({"index": result_idx, "value": best[1], "time": candles[result_idx]["time"]})
    return result


def _closest_indicator_swing(ind_swings: list[dict], price_swing: dict) -> Union[dict, None]:
    """Find the closest indicator swing to a price swing."""
    best = None
    best_dist = float("inf")
    for ins in ind_swings:
        dist = abs(ins["index"] - price_swing["index"])
        if dist < best_dist:
            best_dist = dist
            best = ins
    return best


# ---------------------------------------------------------------------------
# Fibonacci
# ---------------------------------------------------------------------------

def compute_fibonacci(candles: list[dict], lookback: int = 100) -> dict:
    """Auto-anchor Fibonacci retracement levels."""
    window = candles[-lookback:] if len(candles) > lookback else candles
    high = max(c["high"] for c in window)
    low = min(c["low"] for c in window)
    high_time = next(c["time"] for c in window if c["high"] == high)
    low_time = next(c["time"] for c in window if c["low"] == low)
    rng = high - low
    levels = [{"pct": p, "price": round(low + p * rng, 4)} for p in FIB_LEVELS]
    return {
        "kind": "Fibonacci",
        "swing_high_time": high_time,
        "swing_high_price": high,
        "swing_low_time": low_time,
        "swing_low_price": low,
        "levels": levels,
    }


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------

def compute_confluence(signals: list[dict]) -> list[dict]:
    """Compute confluence scores for overlapping signal zones. Score capped at 100.

    Formula: 30 FVG + 25 OB + 20 BOS/CHoCH + 15 Fib + 10 per divergence.
    """
    zone_signals = [s for s in signals if _is_zone_signal(s) or _is_line_signal(s)]
    if len(zone_signals) < 2:
        return []

    zones: list[dict] = []
    checked: set[int] = set()

    for i in range(len(zone_signals)):
        if i in checked:
            continue
        cluster = [zone_signals[i]]
        checked.add(i)
        lo = zone_signals[i].get("price_low", zone_signals[i].get("price", 0))
        hi = zone_signals[i].get("price_high", zone_signals[i].get("price", 0))

        for j in range(i + 1, len(zone_signals)):
            if j in checked:
                continue
            if _overlap({"price_low": lo, "price_high": hi}, zone_signals[j]):
                cluster.append(zone_signals[j])
                checked.add(j)
                p_lo = zone_signals[j].get("price_low", zone_signals[j].get("price", 0))
                p_hi = zone_signals[j].get("price_high", zone_signals[j].get("price", 0))
                lo = min(lo, p_lo)
                hi = max(hi, p_hi)

        if len(cluster) >= 2:
            score = 0
            for s in cluster:
                if s["kind"] == "FVG":
                    score += 30
                elif s["kind"] == "OrderBlock":
                    score += 25
                elif s["kind"] in ("BOS", "CHoCH"):
                    score += 20

            # Fibonacci levels within 0.5% of zone
            fib = next((s for s in signals if s["kind"] == "Fibonacci"), None)
            if fib:
                for lvl in fib["levels"]:
                    if abs(lvl["price"] - lo) / max(lo, 0.01) < 0.005 or abs(lvl["price"] - hi) / max(hi, 0.01) < 0.005:
                        score += 15
                        break

            # Per divergence signal in same bar range
            divergences = [s for s in signals if s["kind"] == "Divergence"]
            for div in divergences:
                div_lo = div.get("price_start", div.get("price", 0))
                div_hi = div.get("price_end", div.get("price", 0))
                if not (max(div_lo, div_hi) < lo or hi < min(div_lo, div_hi)):
                    score += 10

            zones.append({
                "kind": "Confluence",
                "price_high": hi,
                "price_low": lo,
                "score": min(score, 100),
                "components": list(set(s["kind"] for s in cluster)),
            })

    return zones


# ---------------------------------------------------------------------------
# MTF alignment
# ---------------------------------------------------------------------------

def _mtf_align(signals: list[dict], ht_candles: list[dict] | None) -> list[dict]:
    """Set mtf_aligned=True when signal direction matches higher-timeframe trend.
    Also set multi_tf=True for FVG signals whose price range overlaps an HTF FVG.

    Higher timeframe trend: close[-1] > SMA(20) = bullish, else bearish.
    """
    if not ht_candles or len(ht_candles) < 21:
        return signals

    # Existing SMA20 trend logic (unchanged)
    close_prices = [c["close"] for c in ht_candles[-20:]]
    sma20 = sum(close_prices) / 20
    ht_trend = "up" if close_prices[-1] > sma20 else "down"
    for s in signals:
        s_direction = s.get("direction")
        if s_direction == "bullish" and ht_trend == "up":
            s["mtf_aligned"] = True
        elif s_direction == "bearish" and ht_trend == "down":
            s["mtf_aligned"] = True

    # NEW: Multi-timeframe FVG overlap detection
    if len(ht_candles) >= 3:
        ht_fvgs = detect_fvg(ht_candles)
        for s in signals:
            if s.get("kind") != "FVG":
                continue
            s_low = s.get("price_low", 0)
            s_high = s.get("price_high", 0)
            s_direction = s.get("direction")
            for ht_fvg in ht_fvgs:
                if ht_fvg.get("mitigated"):
                    continue   # skip already-mitigated HTF FVGs
                if ht_fvg.get("direction") != s_direction:
                    continue   # must be same direction
                ht_low = ht_fvg.get("price_low", 0)
                ht_high = ht_fvg.get("price_high", 0)
                # Price range overlap: ranges overlap if max(low) < min(high)
                if max(s_low, ht_low) < min(s_high, ht_high):
                    s["multi_tf"] = True
                    break       # one overlap is enough

    return signals


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compute_structure(candles: list[dict], interval: str, symbol: str,
                      ht_candles: list[dict] | None = None) -> list[dict]:
    """Entry point. Returns list of signal dicts matching the structure message schema."""
    if len(candles) < 10:
        return []

    bos_sigs = detect_bos_choch(candles)
    signals: list[Union[dict, None]] = []
    signals.extend(detect_fvg(candles))
    signals.extend(bos_sigs)
    signals.extend(detect_order_blocks(candles, bos_sigs))
    signals.extend(detect_rsi_divergence(candles))
    signals.extend(detect_macd_divergence(candles))
    signals.append(compute_fibonacci(candles))

    all_signals = [s for s in signals if s is not None]
    confluence = compute_confluence(all_signals)
    all_signals.extend(confluence)

    all_signals = _mtf_align(all_signals, ht_candles)

    return all_signals
