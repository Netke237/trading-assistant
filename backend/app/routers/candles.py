from fastapi import APIRouter
from app.schemas import Candle
from app.data.market import fetch_candles
import httpx

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/candles/{symbol}', response_model=list[Candle])
async def get_candles(symbol: str) -> list[Candle]:
    async with httpx.AsyncClient(http2=True) as client:
        return await fetch_candles(client, symbol.upper()) or []
