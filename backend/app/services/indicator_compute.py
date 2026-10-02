# backend/app/services/indicator_compute.py
"""Compute indicator values from OHLCV candles — server-side equivalent of frontend getIndicatorPoints()."""
from __future__ import annotations

import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")


def compute_indicators_for_conditions(candles: list[dict], conditions: list) -> dict[str, list[dict]]:
    """Given alert conditions and candles, compute only the indicators referenced by conditions.
    Returns {indicator_name: [{time, value}, ...]} matching the TS Point[] shape.
    """
    needed: set[str] = set()
    for c in conditions:
        if hasattr(c, 'kind') and c.kind == 'indicator':
            needed.add(getattr(c, 'indicator', ''))
        elif isinstance(c, dict) and c.get('kind') == 'indicator':
            needed.add(c.get('indicator', ''))

    if not needed:
        return {}

    closes = [c['close'] for c in candles]
    times = [c['time'] for c in candles]
    highs = [c['high'] for c in candles]
    lows = [c['low'] for c in candles]
    volumes = [c['volume'] for c in candles]

    result: dict[str, list[dict]] = {}

    for indicator_name in needed:
        lower = indicator_name.lower()
        if lower in ('ema', 'ema20', 'ema(20)'):
            result[indicator_name] = _calc_ema(closes, times, 20)
        elif lower in ('ema9', 'ema(9)'):
            result[indicator_name] = _calc_ema(closes, times, 9)
        elif lower in ('ema50', 'ema(50)'):
            result[indicator_name] = _calc_ema(closes, times, 50)
        elif lower in ('sma', 'sma20', 'sma(20)'):
            result[indicator_name] = _calc_sma(closes, times, 20)
        elif lower in ('sma50', 'sma(50)'):
            result[indicator_name] = _calc_sma(closes, times, 50)
        elif lower in ('rsi', 'rsi(14)'):
            result[indicator_name] = _calc_rsi(closes, times, 14)
        elif lower in ('macd', 'macd_line'):
            macd_data = _calc_macd(closes, times, 12, 26, 9)
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(macd_data['times'], macd_data['macd'])]
        elif lower == 'macd_signal':
            macd_data = _calc_macd(closes, times, 12, 26, 9)
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(macd_data['times'], macd_data['signal'])]
        elif lower in ('atr', 'atr(14)'):
            result[indicator_name] = _calc_atr(highs, lows, closes, times, 14)
        elif lower in ('bb_upper', 'bollinger_upper'):
            bb = _calc_bb(closes, times, 20, 2)
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(bb['times'], bb['upper'])]
        elif lower in ('bb_lower', 'bollinger_lower'):
            bb = _calc_bb(closes, times, 20, 2)
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(bb['times'], bb['lower'])]
        elif lower in ('bb_mid', 'bollinger_mid'):
            bb = _calc_bb(closes, times, 20, 2)
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(bb['times'], bb['mid'])]
        elif lower == 'vwap':
            result[indicator_name] = _calc_vwap(highs, lows, closes, volumes, times)
        elif lower == 'volume':
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(times, volumes)]
        elif lower == 'close':
            result[indicator_name] = [{'time': t, 'value': v} for t, v in zip(times, closes)]

    return result


def _calc_ema(values: list[float], times: list[str], period: int) -> list[dict]:
    result = []
    if len(values) < period:
        return result
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for i, t in enumerate(times):
        if i < period:
            result.append({'time': t, 'value': None})
        else:
            ema = (values[i] - ema) * multiplier + ema
            result.append({'time': t, 'value': round(ema, 4)})
    return result


def _calc_sma(values: list[float], times: list[str], period: int) -> list[dict]:
    result = []
    for i, t in enumerate(times):
        if i < period - 1:
            result.append({'time': t, 'value': None})
        else:
            sma = sum(values[i - period + 1:i + 1]) / period
            result.append({'time': t, 'value': round(sma, 4)})
    return result


def _calc_rsi(closes: list[float], times: list[str], period: int = 14) -> list[dict]:
    result = [{'time': t, 'value': None} for t in times]
    if len(closes) < period + 1:
        return result
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        result[period] = {'time': times[period], 'value': 100.0}
    else:
        rs = avg_gain / avg_loss
        result[period] = {'time': times[period], 'value': round(100 - 100 / (1 + rs), 4)}
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = {'time': times[i + 1], 'value': 100.0}
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = {'time': times[i + 1], 'value': round(100 - 100 / (1 + rs), 4)}
    return result


def _calc_macd(closes: list[float], times: list[str], fast: int, slow: int, signal: int) -> dict:
    """MACD on the textbook EMA (_ema_seeded), as the frontend calcMACD draws it:
    None until both EMAs are seeded (index slow-1), the signal line None until
    `signal` MACD values exist. MACD-EMA-LAG: this used the lagged, zero-padded
    _ema_values, so the line equalled the price during warm-up and every value
    trailed the bar it was stamped on by one bar."""
    n = len(closes)
    ema_fast = _ema_seeded(closes, fast)
    ema_slow = _ema_seeded(closes, slow)
    macd_line: list[float | None] = [
        None if f is None or s is None else f - s for f, s in zip(ema_fast, ema_slow)
    ]
    start = next((i for i, m in enumerate(macd_line) if m is not None), n)
    signal_line: list[float | None] = [None] * start + _ema_seeded(macd_line[start:], signal)
    histogram = [None if m is None or s is None else m - s for m, s in zip(macd_line, signal_line)]
    return {'times': times, 'macd': macd_line, 'signal': signal_line, 'histogram': histogram}


def _calc_atr(highs: list[float], lows: list[float], closes: list[float], times: list[str], period: int = 14) -> list[dict]:
    result = [{'time': t, 'value': None} for t in times]
    if len(closes) < period + 1:
        return result
    tr_values = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_values.append(tr)
    atr = sum(tr_values[:period]) / period
    result[period] = {'time': times[period], 'value': round(atr, 4)}
    for i in range(period, len(tr_values)):
        atr = (atr * (period - 1) + tr_values[i]) / period
        result[i + 1] = {'time': times[i + 1], 'value': round(atr, 4)}
    return result


def _calc_bb(closes: list[float], times: list[str], period: int = 20, std_dev: float = 2.0) -> dict:
    mids = []
    uppers = []
    lowers = []
    for i in range(len(closes)):
        if i < period - 1:
            mids.append(None)
            uppers.append(None)
            lowers.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            sma = sum(window) / period
            variance = sum((x - sma) ** 2 for x in window) / period
            std = variance ** 0.5
            mids.append(round(sma, 4))
            uppers.append(round(sma + std_dev * std, 4))
            lowers.append(round(sma - std_dev * std, 4))
    return {'times': times, 'upper': uppers, 'mid': mids, 'lower': lowers}


def _session_key(t) -> str | None:
    """Eastern-market calendar date for an intraday bar — the VWAP session anchor.

    Returns None for date-string bars (daily/weekly), which have no intraday
    session to anchor to; those keep the running-total behaviour.
    """
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, _EASTERN).strftime('%Y-%m-%d')
    return None


def _calc_vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], times: list[str]) -> list[dict]:
    """Session-anchored VWAP: the accumulation resets at each Eastern trading day.

    It previously accumulated from candles[0] to the end with no anchor, which
    made the value a function of how many bars the caller happened to pass —
    so simply loading more history silently moved every VWAP reading and any
    alert compared against it. Anchoring per session matches the standard
    definition and makes the series independent of the loaded window.

    Daily/weekly bars carry date strings rather than timestamps and have no
    intraday session; they keep the original running-total behaviour.
    """
    result = []
    cum_pv = 0.0
    cum_vol = 0.0
    current_session: str | None = None
    for i in range(len(closes)):
        session = _session_key(times[i])
        if session is not None and session != current_session:
            current_session = session
            cum_pv = 0.0
            cum_vol = 0.0
        typical = (highs[i] + lows[i] + closes[i]) / 3
        cum_pv += typical * volumes[i]
        cum_vol += volumes[i]
        vwap = cum_pv / cum_vol if cum_vol > 0 else 0
        result.append({'time': times[i], 'value': round(vwap, 4)})
    return result


# ── COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD: composite 'momentum' confirmations ──
# Plan: docs/superpowers/plans/2026-09-29-composite-momentum-confirmations-plan.md
# (Q1-Q3, Q6, Q11). Additions only: _calc_rsi and compute_indicators_for_conditions
# stay byte-for-byte unchanged (standard rules keep their behaviour). The lagged
# _ema_values logged at Q9 is gone: MACD-EMA-LAG moved _calc_macd onto _ema_seeded.
# momentum_match judges the LAST bar of what it is given, on both the rule and
# the watch path, so the two cannot disagree on the same bars.
_momentum_logger = logging.getLogger(__name__)

MOMENTUM_KINDS = ("volume_spike", "rsi_cross", "macd_cross")
# Q6: RSI/MACD read the judged bar and the 200 regular bars before it (201).
MOMENTUM_RSI_MACD_HISTORY = 200
_RSI_PERIOD = 14
_MACD_FAST, _MACD_SLOW, _MACD_SIGNAL = 12, 26, 9
# Q3: volume_spike = judged volume >= 2x a baseline.
VOLUME_SPIKE_RATIO = 2.0
_DAILY_VOLUME_LOOKBACK = 20      # 1D/1W: mean of the 20 bars before the judged one
_SLOT_SESSIONS = 10              # intraday: same Eastern slot, previous 10 sessions
_SLOT_MIN_SESSIONS = 5           # ... at least 5 of them, else not matched
_DEFAULT_RSI_LEVEL = 60          # the schema's min_confidence default

# Nominal bar span per intraday interval (NOT market._INTERVAL_COMPLETION_SECONDS,
# whose 4h entry carries an extra hour of completion slack). Both spellings.
_MOMENTUM_BAR_SECONDS: dict[str, int] = {
    "1min": 60, "1m": 60, "5min": 300, "5m": 300, "15min": 900, "15m": 900,
    "30min": 1800, "30m": 1800, "1h": 3600, "60m": 3600, "4h": 4 * 3600,
}
_DAILY_SPELLINGS = frozenset({"1D", "1W", "daily", "weekly", "1d", "1w"})
_REGULAR_OPEN_MIN = 9 * 60 + 30      # 09:30 ET
_REGULAR_CLOSE_MIN = 16 * 60         # 16:00 ET

_momentum_warned: set[tuple[str, str]] = set()


def momentum_warn_once(log_key: object, reason: str, msg: str, *args: object) -> None:
    """One WARNING per (rule/watch id, reason) per process."""
    key = (str(log_key), reason)
    if key in _momentum_warned:
        return
    _momentum_warned.add(key)
    _momentum_logger.warning(msg, *args)


def _is_real(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _epoch(t: object) -> int | None:
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def _is_regular_bar(t: object, span: int) -> bool:
    """Q11 (r5): regular when the bar's SPAN [t, t+span) overlaps 09:30-16:00 ET
    on its Eastern date -- never by its start time alone: a 4h bucket is
    stamped 08:00 ET (EDT) / 07:00 ET (EST) while holding the morning bars."""
    ts = _epoch(t)
    if ts is None:
        return False
    local = datetime.fromtimestamp(ts, _EASTERN)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    open_ts = midnight.replace(hour=9, minute=30).timestamp()
    close_ts = midnight.replace(hour=16).timestamp()
    return ts < close_ts and ts + span > open_ts


def momentum_session_bars(bars: list[dict], interval: object) -> list[dict]:
    """The bars momentum reads (Q11): on an intraday interval only regular-
    session bars; 1D/1W unchanged. An unrecognised interval -> []."""
    if not isinstance(interval, str):
        return []
    if interval in _DAILY_SPELLINGS:
        return list(bars)
    span = _MOMENTUM_BAR_SECONDS.get(interval)
    if span is None:
        return []
    return [b for b in bars if isinstance(b, dict) and _is_regular_bar(b.get("time"), span)]


def _ema_seeded(values: list[float], period: int) -> list[float | None]:
    """A correct EMA: None for the warm-up, the SMA of the first `period`
    values at index period-1, then each value folded in at its own index."""
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    out[period - 1] = ema
    for i in range(period, len(values)):
        ema = (values[i] - ema) * k + ema
        out[i] = ema
    return out


def _wilder_rsi_last_two(closes: list[float], period: int = _RSI_PERIOD) -> tuple[float, float] | None:
    """(RSI of the bar before the last, RSI of the last) -- Wilder smoothing,
    the same arithmetic as _calc_rsi (copied, not shared). A window where both
    averages are 0 (a flat series) reads 50, not _calc_rsi's 100."""
    if len(closes) < period + 2:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    def _rsi(g: float, l: float) -> float:
        if l == 0:
            return 50.0 if g == 0 else 100.0
        return 100 - 100 / (1 + g / l)

    values = [_rsi(avg_g, avg_l)]
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        values.append(_rsi(avg_g, avg_l))
    return values[-2], values[-1]


def _macd_last_two(closes: list[float]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """((line, signal) of the bar before the last, (line, signal) of the last)."""
    fast = _ema_seeded(closes, _MACD_FAST)
    slow = _ema_seeded(closes, _MACD_SLOW)
    start = _MACD_SLOW - 1
    line = [f - s for f, s in zip(fast[start:], slow[start:])]  # both defined from `start`
    signal = _ema_seeded(line, _MACD_SIGNAL)
    if len(line) < 2 or signal[-2] is None or signal[-1] is None:
        return None
    return (line[-2], signal[-2]), (line[-1], signal[-1])


def _direction_of(direction: object) -> str | None:
    """'bullish' / 'bearish' / 'any'; None for a value that is not one of them."""
    if direction is None:
        return "any"
    if isinstance(direction, str) and direction.lower() in ("bullish", "bearish"):
        return direction.lower()
    return None


def rsi_level(min_confidence: object) -> int | None:
    """Q1: the rsi_cross level -- an int in 1..99 (bool excluded), else None."""
    if isinstance(min_confidence, int) and not isinstance(min_confidence, bool) and 1 <= min_confidence <= 99:
        return min_confidence
    return None


def _volume_baseline(bars: list[dict], interval: str, log_key: object) -> float | None:
    """Q3: the baseline the judged (last) bar's volume is compared with; None
    when there is not enough valid history."""
    judged = bars[-1]
    if interval in _DAILY_SPELLINGS:
        prior = bars[-1 - _DAILY_VOLUME_LOOKBACK:-1]
        if len(prior) < _DAILY_VOLUME_LOOKBACK or not all(_is_real(b.get("volume")) and b["volume"] >= 0 for b in prior):
            return None
        return sum(b["volume"] for b in prior) / _DAILY_VOLUME_LOOKBACK
    # Intraday: the same Eastern wall-clock slot over the previous sessions.
    jt = datetime.fromtimestamp(judged["time"], _EASTERN)
    slot, day = (jt.hour, jt.minute), jt.date()
    by_session: dict = {}
    for b in bars[:-1]:
        ts = _epoch(b.get("time"))
        if ts is None or not (_is_real(b.get("volume")) and b["volume"] >= 0):
            continue
        lt = datetime.fromtimestamp(ts, _EASTERN)
        if (lt.hour, lt.minute) == slot and lt.date() < day:
            by_session[lt.date()] = b["volume"]          # the last bar per session wins
    recent = [by_session[d] for d in sorted(by_session)[-_SLOT_SESSIONS:]]
    if len(recent) < _SLOT_MIN_SESSIONS:
        momentum_warn_once(
            log_key, "volume_slot_short",
            "momentum volume_spike [%s]: %d earlier session(s) at slot %02d:%02d ET (need %d); not matched",
            log_key, len(recent), slot[0], slot[1], _SLOT_MIN_SESSIONS,
        )
        return None
    return sum(recent) / len(recent)


def momentum_match(
    bars: list[dict], interval: object, kind: object, direction: object,
    min_confidence: object, log_key: object,
) -> bool:
    """Whether the momentum confirmation `kind` is met on the LAST bar of `bars`.

    - rsi_cross: RSI(14) crosses the level L = min_confidence (Bullish
      prev <= L < cur; Bearish prev >= 100-L > cur; direction None: either).
    - macd_cross: MACD(12,26,9) crosses its signal line (Bullish up, Bearish
      down, None either), from a correct seeded EMA.
    - volume_spike: volume >= 2x the baseline (1D/1W: the 20 bars before it;
      intraday: the same Eastern slot over the previous 10 sessions, >= 5) and
      the candle agrees with the direction.

    Intraday inputs are regular-session bars only; a judged bar outside regular
    hours is not matched. Every shortfall is a definite False. Never raises.
    """
    try:
        return _momentum_match(bars, interval, kind, direction, min_confidence, log_key)
    except Exception as exc:     # a guard: a bad row must never skip the rule
        momentum_warn_once(log_key, "error", "momentum %s [%s]: %s; not matched", kind, log_key, exc)
        return False


def _momentum_match(bars, interval, kind, direction, min_confidence, log_key) -> bool:
    if kind not in MOMENTUM_KINDS:
        momentum_warn_once(log_key, f"kind:{kind}", "momentum [%s]: unknown signal_kind %r; not matched", log_key, kind)
        return False
    d = _direction_of(direction)
    if d is None:
        momentum_warn_once(log_key, f"dir:{direction}", "momentum [%s]: direction %r not Bullish/Bearish/None; not matched",
                           log_key, direction)
        return False
    if not bars or not isinstance(bars[-1], dict):
        return False
    judged = bars[-1]
    if isinstance(interval, str) and interval not in _DAILY_SPELLINGS:
        span = _MOMENTUM_BAR_SECONDS.get(interval)
        if span is None:
            momentum_warn_once(log_key, f"iv:{interval}", "momentum [%s]: unknown interval %r; not matched", log_key, interval)
            return False
        if not _is_regular_bar(judged.get("time"), span):
            return False
    series = momentum_session_bars(bars, interval)
    if not series or series[-1] is not judged:
        return False

    if kind == "volume_spike":
        vol, o, c = judged.get("volume"), judged.get("open"), judged.get("close")
        if not (_is_real(vol) and vol > 0 and _is_real(o) and _is_real(c)):
            return False
        if (d == "bullish" and not c > o) or (d == "bearish" and not c < o):
            return False
        baseline = _volume_baseline(series, interval, log_key)
        return baseline is not None and baseline > 0 and vol >= VOLUME_SPIKE_RATIO * baseline

    level = None
    if kind == "rsi_cross":
        level = rsi_level(_DEFAULT_RSI_LEVEL if min_confidence is None else min_confidence)
        if level is None:
            momentum_warn_once(log_key, f"level:{min_confidence!r}",
                               "momentum rsi_cross [%s]: min_confidence %r is not an int in 1..99; not matched",
                               log_key, min_confidence)
            return False
    window = series[-(MOMENTUM_RSI_MACD_HISTORY + 1):]
    if len(window) < MOMENTUM_RSI_MACD_HISTORY + 1:
        momentum_warn_once(log_key, f"history:{kind}",
                           "momentum %s [%s]: %d bar(s) of history (need %d); not matched",
                           kind, log_key, len(window), MOMENTUM_RSI_MACD_HISTORY + 1)
        return False
    closes = [b.get("close") for b in window]
    if not all(_is_real(x) for x in closes):
        return False

    if kind == "rsi_cross":
        pair = _wilder_rsi_last_two(closes)
        if pair is None:
            return False
        prev, cur = pair
        up = prev <= level < cur
        down = prev >= 100 - level > cur
        return up if d == "bullish" else down if d == "bearish" else (up or down)

    pair2 = _macd_last_two(closes)
    if pair2 is None:
        return False
    (pl, ps), (cl, cs) = pair2
    up = pl <= ps and cl > cs
    down = pl >= ps and cl < cs
    return up if d == "bullish" else down if d == "bearish" else (up or down)
