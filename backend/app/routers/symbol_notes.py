"""Per-symbol free-text notes — one overwritable note per symbol, shared
between the watchlist and portfolio (not per-position/per-contract). The
record is independent of whether the symbol is currently watchlisted or
held — the frontend gates *editing* on that, but the note itself is never
deleted just because a star or a position goes away."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.symbol_note import SymbolNoteModel

router = APIRouter(prefix='/api/notes', tags=['symbol-notes'])

# Matches the `symbol` column's String(10) width — reject early with a clean
# 422 instead of letting an oversized symbol reach the DB and blow up with a
# raw data-length error (Postgres) that upsert_note's IntegrityError retry
# doesn't handle, permanently stranding the note as unsavable.
MAX_SYMBOL_LEN = 10


class NoteOut(BaseModel):
    symbol: str
    body: str
    updatedAt: str | None


class NoteIn(BaseModel):
    body: str


def _row_to_dict(row: SymbolNoteModel) -> dict:
    return {
        'symbol': row.symbol,
        'body': row.body,
        'updatedAt': row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get('/{symbol}', response_model=NoteOut)
async def get_note(symbol: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Returns the note for a symbol, or an empty placeholder if none exists
    yet — a symbol with no note is a normal state, not a 404."""
    if len(symbol) > MAX_SYMBOL_LEN:
        raise HTTPException(status_code=422, detail=f'symbol must be at most {MAX_SYMBOL_LEN} characters')
    row = await db.get(SymbolNoteModel, symbol.upper())
    if row is None:
        return {'symbol': symbol.upper(), 'body': '', 'updatedAt': None}
    return _row_to_dict(row)


@router.put('/{symbol}', response_model=NoteOut)
async def upsert_note(symbol: str, body: NoteIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Create or overwrite the note for a symbol (upsert)."""
    if len(symbol) > MAX_SYMBOL_LEN:
        raise HTTPException(status_code=422, detail=f'symbol must be at most {MAX_SYMBOL_LEN} characters')
    sym = symbol.upper()
    now = datetime.now(timezone.utc)
    row = await db.get(SymbolNoteModel, sym)
    if row is None:
        row = SymbolNoteModel(symbol=sym, body=body.body, updated_at=now)
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # Concurrent duplicate: two PUTs for a symbol with no existing row
            # both pass the `db.get()` check above and both attempt an INSERT
            # — the loser trips the primary-key uniqueness constraint. Unlike
            # a POST, this is a benign race for an upsert (both calls just
            # want *some* value saved), so retry as the UPDATE it should have
            # been instead of surfacing a raw 500 for what the client sees as
            # a normal debounced save.
            await db.rollback()
            row = await db.get(SymbolNoteModel, sym)
            if row is None:
                raise
            row.body = body.body
            row.updated_at = now
            await db.commit()
    else:
        row.body = body.body
        row.updated_at = now
        await db.commit()
    await db.refresh(row)
    return _row_to_dict(row)
