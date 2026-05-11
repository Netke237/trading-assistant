from fastapi import APIRouter, Query
from app.data.market import fetch_news
import httpx

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/news')
async def get_news(symbols: str = Query(default='')) -> list[dict]:
    if not symbols:
        return []
    sym_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    async with httpx.AsyncClient(http2=True) as client:
        return await fetch_news(client, sym_list) or []
