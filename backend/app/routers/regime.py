from fastapi import APIRouter
from app.schemas import MarketRegime, RegimeMetric
from app.data.market import fetch_candles, fetch_quotes
import httpx

router = APIRouter(prefix='/api', tags=['trading'])

_PRIORITY = {"REJECT": 0, "CAUTION": 1, "PENDING": 2, "NO_DATA": 2, "PASS": 3}


def _ema(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _vix_status(vix: float) -> str:
    if vix < 20:
        return 'PASS'
    if vix <= 30:
        return 'CAUTION'
    return 'REJECT'


async def _spx_ndx_metric(client: httpx.AsyncClient, symbol: str, label: str) -> RegimeMetric | None:
    try:
        candles = await fetch_candles(client, symbol, bars=200)
    except Exception:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    if not candles:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    closes = [c["close"] for c in candles]
    ema_200 = _ema(closes, 200)
    if ema_200 is None or len(closes) == 0:
        return RegimeMetric(label=label, value='—', status='PENDING', trend=None)

    price = closes[-1]
    if price > ema_200:
        return RegimeMetric(label=label, value='Above', status='PASS', trend='up')
    if price >= 0.97 * ema_200:
        return RegimeMetric(label=label, value='Near', status='CAUTION', trend='flat')
    return RegimeMetric(label=label, value='Below', status='REJECT', trend='down')


@router.get('/regime', response_model=MarketRegime)
async def get_regime() -> MarketRegime:
    async with httpx.AsyncClient(http2=True) as client:
        spx = await _spx_ndx_metric(client, 'SPX', 'SPX trend (200 EMA)')
        ndx = await _spx_ndx_metric(client, 'NDX', 'NDX trend (200 EMA)')

        try:
            quotes = await fetch_quotes(client, ['VIX'])
            vix = quotes.get('VIX', {}).get('last', None)
        except Exception:
            vix = None

    if vix is not None:
        vix_status = _vix_status(vix)
        vix_metric = RegimeMetric(
            label='VIX',
            value=f'{vix:.1f}',
            status=vix_status,
            trend='down' if vix_status == 'PASS' else ('up' if vix_status == 'REJECT' else 'flat'),
        )
    else:
        vix_metric = RegimeMetric(label='VIX', value='—', status='PENDING', trend=None)

    metrics: list[RegimeMetric] = [m for m in (spx, ndx, vix_metric) if m is not None]
    statuses = [m.status for m in metrics]

    if not statuses:
        return MarketRegime(
            overall='CAUTION',
            headline='Market data unavailable',
            metrics=[],
        )

    overall = min(statuses, key=lambda s: _PRIORITY.get(s, 2))

    parts: list[str] = []
    for m in metrics:
        if m.status == 'PENDING':
            parts.append(f'{m.label} unavailable')
        elif m.label == 'VIX':
            parts.append(f'VIX {m.value} — {m.status}')
        else:
            parts.append(f'{m.label} {m.value} 200 EMA · {m.status}')

    headline = ' · '.join(parts)

    return MarketRegime(
        overall=overall,
        headline=headline,
        metrics=metrics,
    )
