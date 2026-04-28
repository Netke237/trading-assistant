from fastapi import APIRouter
from app.schemas import MarketRegime
from app.fixtures.regime import MOCK_REGIME

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/regime', response_model=MarketRegime)
async def get_regime() -> MarketRegime:
    return MOCK_REGIME
