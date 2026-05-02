from fastapi import APIRouter
from app.schemas import MarketRegime
from app.fixtures.regime import MOCK_REGIME
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
        return MOCK_REGIME

    updated_metrics = [
        {**m.model_dump(), 'value': f'{vix:.1f}', 'status': _vix_status(vix)}
        if m.label == 'VIX' else m
        for m in MOCK_REGIME.metrics
    ]
    return MarketRegime(
        overall=MOCK_REGIME.overall,
        headline=MOCK_REGIME.headline,
        metrics=updated_metrics,
    )
