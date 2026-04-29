from fastapi import APIRouter
from app.schemas import Candle
from app.fixtures.candles import candles_for

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/candles/{symbol}', response_model=list[Candle])
async def get_candles(symbol: str) -> list[Candle]:
    return candles_for(symbol.upper())
