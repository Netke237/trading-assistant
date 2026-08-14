import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.watchlist import WatchlistSymbolModel
from app.models.scan_session import ScanSession
from app.schemas import WatchlistRow, ScanResult, ScoreBreakdown
from app.data.market import fetch_price_async, fetch_company_name_async

router = APIRouter(prefix='/api', tags=['trading'])


class WatchlistAddRequest(BaseModel):
    symbol: str


@router.get('/watchlist', response_model=list[WatchlistRow])
async def get_watchlist(db: AsyncSession = Depends(get_db)) -> list[WatchlistRow]:
    wl_result = await db.execute(
        select(WatchlistSymbolModel).order_by(WatchlistSymbolModel.created_at)
    )
    wl_rows = wl_result.scalars().all()
    symbols = [r.symbol for r in wl_rows]
    if not symbols:
        return []

    # Load latest scan result to get live scores
    sess_result = await db.execute(select(ScanSession).where(ScanSession.id == "current"))
    sess_row = sess_result.scalar_one_or_none()
    scan_lookup: dict[str, object] = {}
    if sess_row and sess_row.last_result_json:
        try:
            scan = ScanResult.model_validate_json(sess_row.last_result_json)
            for c in scan.candidates:
                scan_lookup[c.symbol] = c
        except Exception:
            pass

    _empty_bd = ScoreBreakdown(trend=0, pullback=0, trigger=0, event=0, volatility=0)

    rows: list[WatchlistRow] = []
    async with httpx.AsyncClient(timeout=8) as client:
        for sym in symbols:
            if sym in scan_lookup:
                c = scan_lookup[sym]
                rows.append(WatchlistRow(
                    symbol=c.symbol,
                    company=c.company,
                    price=c.price,
                    direction=c.direction,
                    horizon="Swing",
                    score=c.stockScore,
                    rankDelta=0,
                    scoreDelta=None,
                    status=c.status,
                    breakdown=c.stockBreakdown,
                    nextEventDays=c.nextEventDays,
                    nextEventLabel=c.nextEventLabel,
                ))
            else:
                price = await fetch_price_async(client, sym) or 0.0
                company = await fetch_company_name_async(client, sym) or sym
                rows.append(WatchlistRow(
                    symbol=sym,
                    company=company,
                    price=price,
                    direction="Bullish",
                    horizon="Swing",
                    score=0,
                    rankDelta=0,
                    scoreDelta=None,
                    status="NO_DATA",
                    breakdown=_empty_bd,
                    nextEventDays=None,
                    nextEventLabel=None,
                ))
    return rows


@router.post('/watchlist', status_code=status.HTTP_201_CREATED)
async def add_symbol(
    body: WatchlistAddRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
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
        return  # Already removed — idempotent
    await db.delete(row)
    await db.commit()
