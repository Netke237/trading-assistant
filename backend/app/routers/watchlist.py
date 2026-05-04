from fastapi import APIRouter
from app.schemas import WatchlistRow

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/watchlist', response_model=list[WatchlistRow])
async def get_watchlist() -> list[WatchlistRow]:
    return []
