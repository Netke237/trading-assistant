from fastapi import APIRouter
from app.schemas import WatchlistRow
from app.fixtures.watchlist import MOCK_WATCHLIST

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/watchlist', response_model=list[WatchlistRow])
async def get_watchlist() -> list[WatchlistRow]:
    return MOCK_WATCHLIST
