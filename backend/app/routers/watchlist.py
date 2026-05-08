from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.watchlist import WatchlistSymbolModel

router = APIRouter(prefix='/api', tags=['trading'])


class WatchlistAddRequest(BaseModel):
    symbol: str


@router.get('/watchlist', response_model=list[str])
async def get_watchlist(db: AsyncSession = Depends(get_db)) -> list[str]:
    result = await db.execute(select(WatchlistSymbolModel).order_by(WatchlistSymbolModel.created_at))
    rows = result.scalars().all()
    return [row.symbol for row in rows]


@router.post('/watchlist', status_code=status.HTTP_201_CREATED)
async def add_symbol(
    body: WatchlistAddRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Idempotent: if already present return 201 silently
    existing = await db.execute(
        select(WatchlistSymbolModel).where(WatchlistSymbolModel.symbol == body.symbol)
    )
    if existing.scalar_one_or_none() is not None:
        return {"symbol": body.symbol}

    row = WatchlistSymbolModel(symbol=body.symbol)
    db.add(row)
    await db.commit()
    return {"symbol": body.symbol}


@router.delete('/watchlist/{symbol}', status_code=status.HTTP_204_NO_CONTENT)
async def remove_symbol(symbol: str, db: AsyncSession = Depends(get_db)) -> None:
    result = await db.execute(
        select(WatchlistSymbolModel).where(WatchlistSymbolModel.symbol == symbol)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol}' not found in watchlist.",
        )
    await db.delete(row)
    await db.commit()
