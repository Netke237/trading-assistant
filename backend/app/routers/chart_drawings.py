# backend/app/routers/chart_drawings.py
"""Chart drawings CRUD endpoints — persist user-drawn annotations per symbol+interval."""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.drawing import DrawingModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/chart/drawings', tags=['chart-drawings'])


# ── Pydantic request/response models ─────────────────────────────────────────

class DrawingPoint(BaseModel):
    time: int
    price: float


class DrawingIn(BaseModel):
    id: str
    symbol: str
    interval: str
    kind: str
    points: list[DrawingPoint] = Field(default_factory=list)
    color: str
    width: int = 1
    createdAt: str


class DrawingOut(BaseModel):
    id: str
    symbol: str
    interval: str
    kind: str
    points: list[DrawingPoint]
    color: str
    width: int
    created_at: str


# ── Helper ────────────────────────────────────────────────────────────────────

def _row_to_dict(row: DrawingModel) -> dict:
    return {
        'id': row.id,
        'symbol': row.symbol,
        'interval': row.interval,
        'kind': row.kind,
        'points': json.loads(row.points_json),
        'color': row.color,
        'width': row.width,
        'created_at': row.created_at,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post('', status_code=status.HTTP_200_OK)
async def upsert_drawing(body: DrawingIn, db: AsyncSession = Depends(get_db)):
    """Create or replace a drawing by id (upsert)."""
    existing = await db.get(DrawingModel, body.id)
    if existing:
        existing.symbol = body.symbol.upper()
        existing.interval = body.interval
        existing.kind = body.kind
        existing.points_json = json.dumps([p.model_dump() for p in body.points])
        existing.color = body.color
        existing.width = body.width
        existing.created_at = body.createdAt
        await db.commit()
        return _row_to_dict(existing)

    drawing = DrawingModel(
        id=body.id,
        symbol=body.symbol.upper(),
        interval=body.interval,
        kind=body.kind,
        points_json=json.dumps([p.model_dump() for p in body.points]),
        color=body.color,
        width=body.width,
        created_at=body.createdAt,
    )
    db.add(drawing)
    await db.commit()
    return _row_to_dict(drawing)


@router.get('')
async def list_drawings(
    symbol: Optional[str] = None,
    interval: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List drawings, optionally filtered by symbol and/or interval."""
    q = select(DrawingModel)
    if symbol:
        q = q.where(DrawingModel.symbol == symbol.upper())
    if interval:
        q = q.where(DrawingModel.interval == interval)
    result = await db.execute(q.order_by(DrawingModel.created_at.asc()))
    return [_row_to_dict(r) for r in result.scalars().all()]


@router.delete('/{drawing_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_drawing(drawing_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a drawing by id."""
    row = await db.get(DrawingModel, drawing_id)
    if not row:
        raise HTTPException(status_code=404, detail='Drawing not found')
    await db.delete(row)
    await db.commit()
