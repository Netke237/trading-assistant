from fastapi import APIRouter
from app.schemas import MarketRegime, RegimeMetric
from app.data.market import fetch_price

router = APIRouter(prefix='/api', tags=['trading'])


def _vix_status(vix: float) -> str:
    if vix < 20:
        return 'PASS'
    if vix <= 30:
        return 'CAUTION'
    return 'REJECT'


@router.get('/regime', response_model=MarketRegime)
async def get_regime() -> MarketRegime:
    try:
        vix = fetch_price('VIX')
    except Exception:
        vix = None

    if vix is None:
        return MarketRegime(
            overall='CAUTION',
            headline='VIX data unavailable',
            metrics=[],
        )

    status = _vix_status(vix)
    return MarketRegime(
        overall=status,
        headline=f'VIX {vix:.1f} — {status} environment',
        metrics=[
            RegimeMetric(
                label='VIX',
                value=f'{vix:.1f}',
                status=status,
            ),
        ],
    )
