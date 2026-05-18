from fastapi import APIRouter, Query
from app.data.market import fetch_news
from app.schemas import NewsItem

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/news', response_model=list[NewsItem])
async def get_news(symbols: str = Query(default='')) -> list[NewsItem]:
    """
    Returns recent news headlines for the given comma-separated symbols.
    Falls back to [] if the Tradier call fails or no symbols provided.
    """
    if not symbols:
        return []
    sym_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not sym_list:
        return []
    return fetch_news(sym_list)
