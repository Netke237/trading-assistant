"""Frozen daily setup -> later confirmed research entry events (no live orders)."""
from __future__ import annotations

import math
from app.services.horizon_tuning.signals import MIN_SIGNAL_BARS, SignalPoint
from app.services.strategy_backtest import normalize_direction

SETUP_STRATEGIES = frozenset({'breakout_setup', 'fibonacci_pullback'})
FIB_DEFAULTS = dict(fib_swing_lookback=100, fib_levels=[38.2, 61.8],
                    fib_tolerance_pct=.015, impulse_min_pct=.08,
                    retracement_recency_bars=40, ema_filter_period=20)
RESEARCH_DEFAULTS = dict(setup_expiry_bars=5, volume_confirm=False,
                         volume_confirm_mult=1.5, rr_multiple=2.)


def setup_params(strategy: str, params: dict | None = None) -> dict:
    """Validate explicit research parameters; never ignore misspelled keys."""
    from app.services import strategy_engine as se
    if strategy not in SETUP_STRATEGIES:
        raise ValueError(f'unknown setup strategy {strategy!r}')
    if strategy == 'breakout_setup':
        defaults = dict(atr_compression_ratio=.85, atr_avg_lookback=20,
                        range_atr_mult=3., range_lookback_bars=10,
                        vol_compression_ratio=.9, resistance_proximity_pct=.05,
                        swing_lookback=50, require_trend=True, fib_enabled=False,
                        fib_swing_lookback=100, fib_levels=None, fib_tolerance_pct=.015)
        defaults.update(RESEARCH_DEFAULTS)
    else:
        defaults = {**FIB_DEFAULTS, 'setup_expiry_bars': 5}
    p = dict(params or {})
    if p.keys() - defaults.keys():
        raise ValueError(f'unknown setup parameters: {sorted(p.keys() - defaults.keys())}')
    p = {**defaults, **p}
    if strategy == 'breakout_setup' and p.get('fib_levels') is None:
        p['fib_levels'] = [23.6, 38.2, 50., 61.8]
    integer_keys = {'atr_avg_lookback', 'range_lookback_bars', 'swing_lookback',
                    'fib_swing_lookback', 'retracement_recency_bars', 'ema_filter_period', 'setup_expiry_bars'}
    bool_keys = {'require_trend', 'fib_enabled', 'volume_confirm'}
    for key, value in p.items():
        if key in integer_keys:
            minimum = 0 if key in ('ema_filter_period', 'retracement_recency_bars') else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f'{key} must be an integer >= {minimum}')
            if key != 'setup_expiry_bars' and value > se.SIGNAL_WINDOW_BARS:
                raise ValueError(f'{key} exceeds {se.SIGNAL_WINDOW_BARS}-bar window')
        elif key in bool_keys:
            if type(value) is not bool:
                raise ValueError(f'{key} must be boolean')
        elif key == 'fib_levels':
            if not isinstance(value, list) or not value or any(type(v) not in (int, float) or v not in se._FIB_RATIOS for v in value):
                raise ValueError('fib_levels must contain supported Fibonacci percentages')
        else:
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{key} must be finite and nonnegative')
            if key in ('rr_multiple', 'volume_confirm_mult', 'atr_compression_ratio', 'range_atr_mult', 'vol_compression_ratio') and value <= 0:
                raise ValueError(f'{key} must be positive')
            if key in ('fib_tolerance_pct', 'impulse_min_pct', 'resistance_proximity_pct') and value > 1:
                raise ValueError(f'{key} must be <= 1')
    if strategy == 'breakout_setup' and p['atr_avg_lookback'] + 1 > se.SIGNAL_WINDOW_BARS:
        raise ValueError('ATR average requires more than the signal window')
    return p


def setup_bars_needed(strategy: str, params: dict | None = None) -> int:
    # Research uses full requested windows, even where the scanner helper can
    # fall back to a shorter prefix. The 60-bar series floor is additional.
    p = setup_params(strategy, params)
    if strategy == 'breakout_setup':
        return max(30, p['atr_avg_lookback'] + 1, p['swing_lookback'], p['range_lookback_bars'],
                   p['fib_swing_lookback'] if p['fib_enabled'] else 0)
    return max(10, p['fib_swing_lookback'], p['ema_filter_period'], p['retracement_recency_bars'])


def event_allowed(signal: SignalPoint, i: int, dates, *, allowed=None,
                  entry_start=None, entry_end=None) -> bool:
    """Setup AND trigger belong to the entry window and pass the same gate mask.

    Relative setup age survives cached series slicing; negative origins fail.
    Callers may combine extra_allowed into allowed before using this helper.
    """
    origin = i - signal.setup_age if signal.market else i
    if origin < 0 or (signal.market and signal.setup_age < 1):
        return False
    return all((allowed is None or allowed[t]) and
               (entry_start is None or dates[t] >= entry_start) and
               (entry_end is None or dates[t] < entry_end) for t in (origin, i))


def setup_series(bars: list[dict], strategy: str, direction: str,
                 params: dict | None = None) -> list[SignalPoint | None]:
    from app.services import strategy_engine as se
    p = setup_params(strategy, params)
    direction = normalize_direction(direction)
    long = direction == 'Bullish'
    clean = [{k: float(b[k]) for k in ('open', 'high', 'low', 'close', 'volume')} for b in bars]
    if any(not math.isfinite(v) or v < 0 or (k != 'volume' and v == 0)
           for b in clean for k, v in b.items()):
        raise ValueError('setup bars require positive finite OHLC and nonnegative finite volume')
    out = [None] * len(bars)
    pending = None
    for t in range(MIN_SIGNAL_BARS - 1, len(bars)):
        window = clean[max(0, t + 1 - se.SIGNAL_WINDOW_BARS):t + 1]
        close = clean[t]['close']
        if pending is not None:
            s, level, stop, target, rr = pending
            confirmed = close > level if long else close < level
            if strategy == 'breakout_setup' and p['volume_confirm']:
                previous = clean[t-20:t]
                confirmed = confirmed and len(previous) == 20 and clean[t]['volume'] >= p['volume_confirm_mult'] * (sum(b['volume'] for b in previous) / 20)
            if confirmed:
                out[t] = SignalPoint(close, stop, target, market=True, rr_multiple=rr, setup_age=t-s)
                pending = None
            elif t - s >= p['setup_expiry_bars']:
                pending = None
            # Never detect a replacement on the confirmation or expiry close.
            continue
        if strategy == 'breakout_setup':
            if len(window) < setup_bars_needed(strategy, p):
                continue
            detector = {k: v for k, v in p.items() if k not in RESEARCH_DEFAULTS}
            if se.breakout_setup_signal(window, '', direction=direction, **detector) is None:
                continue
            swing = window[-p['swing_lookback']:]
            coil = window[-p['range_lookback_bars']:]
            level = max(b['high'] for b in swing) if long else min(b['low'] for b in swing)
            boundary = min(b['low'] for b in coil) if long else max(b['high'] for b in coil)
            stop = math.nextafter(boundary, -math.inf if long else math.inf)
            pending = (t, level, stop, 0., p['rr_multiple'])
        else:
            if len(window) < setup_bars_needed(strategy, p):
                continue
            detail = se.fibonacci_pullback_detail(window, direction, **{k: v for k, v in p.items() if k not in ('ema_filter_period', 'setup_expiry_bars')})
            if not detail['at_level']:
                continue
            period = p['ema_filter_period']
            if period:
                closes = [b['close'] for b in window]
                ema = sum(closes[:period]) / period
                k = 2 / (period + 1)
                for c in closes[period:]:
                    ema = c*k + ema*(1-k)
                if (close < ema if long else close > ema):
                    continue
            low, high = detail['swing_low'], detail['swing_high']
            touched = float(detail['label'])
            deeper = min((v for v in p['fib_levels'] if v > touched), default=100.)
            def level_at(depth):
                if depth == 100.:
                    return low if long else high
                # Match the detector's exact float arithmetic: depth / 100
                # can differ from its canonical ratio and invent a cross.
                ratio = se._FIB_RATIOS[depth]
                return high - ratio*(high-low) if long else low + ratio*(high-low)
            stop = math.nextafter(level_at(deeper), -math.inf if long else math.inf)
            pending = (t, level_at(touched), stop, high if long else low, None)
    return out
