# backend/app/routers/chart_drawings.py
"""Chart drawings CRUD endpoints — persist user-drawn annotations per symbol+interval."""
from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
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


class DrawingPointIn(DrawingPoint):
    """Request-only point (NUMERIC-API-INPUTS T2): a non-finite price is a 422.
    `DrawingPoint` stays unguarded because `DrawingOut` lists stored rows, and
    a drawing stored before this guard must still list."""
    model_config = ConfigDict(allow_inf_nan=False)


class DrawingIn(BaseModel):
    id: str
    symbol: str
    interval: str
    kind: Literal['trendline', 'hline', 'rect', 'text', 'arrow', 'arrow_up', 'arrow_down', 'circle', 'path']
    points: list[DrawingPointIn] = Field(default_factory=list)
    color: str
    width: int = 1
    text: str | None = None
    createdAt: str

    @model_validator(mode='after')
    def validate_point_count(self) -> 'DrawingIn':
        """Validate that point count matches the drawing kind."""
        ONE_POINT = {'hline', 'text', 'arrow_up', 'arrow_down'}
        TWO_POINT = {'trendline', 'rect', 'arrow', 'circle'}
        n = len(self.points)

        if self.kind in ONE_POINT and n != 1:
            raise ValueError(f'{self.kind} requires exactly 1 point, got {n}')
        if self.kind in TWO_POINT and n != 2:
            raise ValueError(f'{self.kind} requires exactly 2 points, got {n}')
        if self.kind == 'path' and n < 2:
            raise ValueError(f'path requires at least 2 points, got {n}')

        return self


class DrawingOut(BaseModel):
    id: str
    symbol: str
    interval: str
    kind: Literal['trendline', 'hline', 'rect', 'text', 'arrow', 'arrow_up', 'arrow_down', 'circle', 'path']
    points: list[DrawingPoint]
    color: str
    width: int
    text: str | None
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
        'text': row.text,
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
        existing.text = body.text
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
        text=body.text,
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
