from fastapi import APIRouter
from app.schemas import Candle
from app.fixtures.candles import candles_for
from app.data.market import fetch_candles

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/candles/{symbol}', response_model=list[Candle])
async def get_candles(symbol: str) -> list[Candle]:
    sym = symbol.upper()
    data = fetch_candles(sym)
    if not data:
        return candles_for(sym)
    return data
