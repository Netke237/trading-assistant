# backend/app/services/indicator_compute.py
"""Compute indicator values from OHLCV candles — server-side equivalent of frontend getIndicatorPoints()."""
from __future__ import annotations


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
        elif lower in ('macd_signal'):
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
    ema_fast = _ema_values(closes, fast)
    ema_slow = _ema_values(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema_values(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return {'times': times, 'macd': macd_line, 'signal': signal_line, 'histogram': histogram}


def _ema_values(values: list[float], period: int) -> list[float]:
    result = [0.0] * len(values)
    if len(values) < period:
        return result
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = ema
        ema = (values[i] - ema) * multiplier + ema
    return result


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


def _calc_vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], times: list[str]) -> list[dict]:
    result = []
    cum_pv = 0.0
    cum_vol = 0.0
    for i in range(len(closes)):
        typical = (highs[i] + lows[i] + closes[i]) / 3
        cum_pv += typical * volumes[i]
        cum_vol += volumes[i]
        vwap = cum_pv / cum_vol if cum_vol > 0 else 0
        result.append({'time': times[i], 'value': round(vwap, 4)})
    return result
