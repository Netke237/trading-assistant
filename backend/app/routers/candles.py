import asyncio

from fastapi import APIRouter
from app.schemas import Candle
from app.data.market import fetch_candles

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/candles/{symbol}', response_model=list[Candle])
async def get_candles(symbol: str) -> list[Candle]:
    # Off the event loop (TRADIER-GOVERNOR T3): a sync Tradier fetch.
    return await asyncio.to_thread(fetch_candles, symbol.upper()) or []
