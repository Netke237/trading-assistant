import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.watchlist import WatchlistSymbolModel
from app.schemas import UpcomingEvent
from app.data.market import fetch_earnings_events

router = APIRouter(prefix='/api', tags=['trading'])


@router.get('/events', response_model=list[UpcomingEvent])
async def get_events(db: AsyncSession = Depends(get_db)) -> list[UpcomingEvent]:
    """
    Returns upcoming earnings events for all symbols in the watchlist.
    Uses yfinance (free). Returns [] if watchlist is empty.
    """
    result = await db.execute(select(WatchlistSymbolModel.symbol))
    symbols = list(result.scalars().all())
    if not symbols:
        return []
    events = await asyncio.to_thread(fetch_earnings_events, symbols)
    return events
