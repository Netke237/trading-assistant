"""Per-symbol free-text notes — one overwritable note per symbol, shared
between the watchlist and portfolio (not per-position/per-contract). The
record is independent of whether the symbol is currently watchlisted or
held — the frontend gates *editing* on that, but the note itself is never
deleted just because a star or a position goes away."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.symbol_note import SymbolNoteModel

router = APIRouter(prefix='/api/notes', tags=['symbol-notes'])


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
    row = await db.get(SymbolNoteModel, symbol.upper())
    if row is None:
        return {'symbol': symbol.upper(), 'body': '', 'updatedAt': None}
    return _row_to_dict(row)


@router.put('/{symbol}', response_model=NoteOut)
async def upsert_note(symbol: str, body: NoteIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Create or overwrite the note for a symbol (upsert)."""
    sym = symbol.upper()
    row = await db.get(SymbolNoteModel, sym)
    if row is None:
        row = SymbolNoteModel(symbol=sym, body=body.body, updated_at=datetime.now(timezone.utc))
        db.add(row)
    else:
        row.body = body.body
        row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _row_to_dict(row)
