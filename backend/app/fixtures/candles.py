from datetime import date, timedelta
from app.schemas import Candle


def mulberry32(seed: int):
    """Yields floats in [0, 1). Mirrors the JavaScript Mulberry32 PRNG exactly."""
    t = seed & 0xFFFFFFFF
    while True:
        t = (t + 0x6D2B79F5) & 0xFFFFFFFF
        r = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        r = (r ^ (r + ((r ^ (r >> 7)) * (61 | r)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        yield ((r ^ (r >> 14)) & 0xFFFFFFFF) / 4294967296


def _iso_days_ago(days: int, anchor: str = '2026-04-18') -> str:
    anchor_date = date.fromisoformat(anchor)
    return (anchor_date - timedelta(days=days)).isoformat()


CANDLE_SEEDS: dict[str, dict] = {
    'AAPL':  {'seed': 11,  'base': 172,   'drift':  0.0008},
    'NVDA':  {'seed': 22,  'base': 820,   'drift':  0.0015},
    'MSFT':  {'seed': 33,  'base': 395,   'drift':  0.0006},
    'META':  {'seed': 44,  'base': 495,   'drift':  0.0005},
    'GOOGL': {'seed': 55,  'base': 148,   'drift':  0.0004},
    'AMZN':  {'seed': 66,  'base': 178,   'drift':  0.0004},
    'AMD':   {'seed': 77,  'base': 148,   'drift':  0.0007},
    'TSLA':  {'seed': 88,  'base': 190,   'drift': -0.0010},
    'NFLX':  {'seed': 99,  'base': 598,   'drift':  0.0003},
    'INTC':  {'seed': 111, 'base': 40,    'drift': -0.0006},
    'SPX':   {'seed': 201, 'base': 5180,  'drift':  0.0006},
    'NDX':   {'seed': 202, 'base': 18020, 'drift':  0.0009},
}

_DEFAULT_SEED = {'seed': 1, 'base': 100, 'drift': 0.0}


def make_candles(seed: int, base: float, bars: int = 120, drift: float = 0.0005) -> list[dict]:
    rand = mulberry32(seed)
    out: list[dict] = []
    close = base
    for i in range(bars - 1, -1, -1):
        open_ = close
        r1 = next(rand)
        r2 = next(rand)
        r3 = next(rand)
        r4 = next(rand)
        r5 = next(rand)
        vol = base * (0.012 + r1 * 0.018)
        dir_sign = 1 if r2 < 0.53 + drift * 40 else -1
        range_ = vol * (0.6 + r3 * 0.8)
        next_close = max(1.0, open_ + dir_sign * range_ + (r4 - 0.5) * vol * 0.5)
        high = max(open_, next_close) + r5 * range_ * 0.4
        r6 = next(rand)
        low = min(open_, next_close) - r6 * range_ * 0.4
        r7 = next(rand)
        volume = round(4_000_000 + r7 * 12_000_000)
        out.append({
            'time': _iso_days_ago(i),
            'open': round(open_, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'close': round(next_close, 2),
            'volume': volume,
        })
        close = next_close
    return out


def candles_for(symbol: str) -> list[Candle]:
    cfg = CANDLE_SEEDS.get(symbol, _DEFAULT_SEED)
    raw = make_candles(cfg['seed'], cfg['base'], 120, cfg['drift'])
    return [Candle(**r) for r in raw]
