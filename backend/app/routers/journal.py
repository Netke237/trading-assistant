# backend/app/routers/journal.py
"""Trading journal CRUD endpoints — trade-centric and freeform ('note')
entries in one table, discriminated by `entry_type`. Manual create/edit/
delete only; no auto-stub creation on broker order execution, and no
retention/scheduler wiring (journal entries are a user-authored record,
never auto-deleted, like `alert_rules`)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.journal import JournalEntryModel

router = APIRouter(prefix='/journal', tags=['journal'])

# The 14 trade-only fields forbidden on a `note` entry (Core + Added fields
# that have no meaning without a trade — `thesis` included, since a
# one-liner "reason for the trade" doesn't apply to a general reflection).
# `mistake_tags` and `lessons_learned` are deliberately NOT in this list —
# general behavioral reflection isn't inherently tied to a single trade.
# Keep this list in sync with the model_validator below field-for-field.
_TRADE_ONLY_FIELDS = (
    'symbol', 'direction', 'entry_price', 'exit_price', 'position_size',
    'stop_loss', 'risk_dollars', 'net_pnl', 'status', 'instrument_type',
    'position_id', 'strategy_tag', 'execution_grade', 'thesis',
)


# ── Pydantic request/response models ─────────────────────────────────────────

class JournalEntryCreate(BaseModel):
    # NUMERIC-API-INPUTS T2: every float here is persisted; finite or a 422.
    model_config = ConfigDict(allow_inf_nan=False)

    # Literal, not `str` — a plain `str` let any value (e.g. 'garbage') fall
    # through both branches of the model_validator below with ZERO validation
    # applied, silently accepting a trade payload's full field set under a
    # bogus entry_type. Pydantic v2 422s automatically on anything outside
    # this set, closing that gap at the type level rather than relying on the
    # validator to reject an unrecognized value it was never written to check.
    entry_type: Literal['trade', 'note']
    entry_date: datetime
    symbol: Optional[str] = None
    instrument_type: Optional[str] = None  # 'stock' | 'option'
    direction: Optional[str] = None  # 'long' | 'short'
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    position_size: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_dollars: Optional[float] = None
    net_pnl: Optional[float] = None
    thesis: Optional[str] = None
    strategy_tag: Optional[str] = None
    mistake_tags: Optional[list[str]] = None
    execution_grade: Optional[int] = Field(default=None, ge=1, le=5)
    status: Optional[str] = None  # 'open' | 'closed'
    lessons_learned: Optional[str] = None
    notes: Optional[str] = None
    position_id: Optional[str] = None

    @model_validator(mode='after')
    def validate_entry_type_fields(self) -> 'JournalEntryCreate':
        """`entry_type == 'trade'` requires `symbol`; `entry_type == 'note'`
        forbids the full trade-only field set (_TRADE_ONLY_FIELDS) while
        permitting `mistake_tags`/`lessons_learned` on either entry_type."""
        if self.entry_type == 'trade':
            if not self.symbol:
                raise ValueError('symbol is required when entry_type is "trade"')
        elif self.entry_type == 'note':
            set_fields = [
                name for name in _TRADE_ONLY_FIELDS
                if getattr(self, name) is not None
            ]
            if set_fields:
                raise ValueError(
                    f'note entries cannot set trade-only field(s): {", ".join(set_fields)}'
                )
        return self


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    entry_type: str
    entry_date: datetime
    symbol: Optional[str] = None
    instrument_type: Optional[str] = None
    direction: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    position_size: Optional[float] = None
    stop_loss: Optional[float] = None
    risk_dollars: Optional[float] = None
    net_pnl: Optional[float] = None
    thesis: Optional[str] = None
    strategy_tag: Optional[str] = None
    mistake_tags: Optional[list[str]] = None
    execution_grade: Optional[int] = None
    status: Optional[str] = None
    lessons_learned: Optional[str] = None
    notes: Optional[str] = None
    position_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator('entry_date', 'created_at', 'updated_at', mode='after')
    @classmethod
    def _stamp_utc_if_naive(cls, value: datetime) -> datetime:
        # SQLAlchemy's DateTime(timezone=True) has no real timezone-aware
        # storage under this app's default sqlite+aiosqlite backend (see
        # config.py) — every value round-trips through the DB as naive, and
        # a naive ISO string (no 'Z'/offset) gets reinterpreted as LOCAL
        # time by the frontend's `new Date(iso)` calls, silently breaking
        # the UTC-normalized write path journalDate.ts was built to enforce.
        # These columns are always written as UTC-aware datetimes by this
        # router, so a naive value read back is always UTC, never truly
        # timezone-less — restamp it before it reaches the client.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @computed_field  # type: ignore[misc]
    @property
    def r_multiple(self) -> Optional[float]:
        # Guards BOTH operands: net_pnl is nullable and is null by design for
        # every status='open' entry (a trade with a stop/risk_dollars set at
        # entry but no realized P&L yet — the most common open-trade shape).
        # A guard that only checks risk_dollars would compute None / float
        # and raise TypeError here, 500ing GET /entries the first time any
        # open trade with a stop is journaled. risk_dollars == 0 must also
        # yield None, never ZeroDivisionError.
        if self.net_pnl is not None and self.risk_dollars:
            return self.net_pnl / self.risk_dollars
        return None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post('/entries', response_model=JournalEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(body: JournalEntryCreate, db: AsyncSession = Depends(get_db)):
    entry = JournalEntryModel(
        id=uuid.uuid4().hex,
        user_id='default',
        entry_type=body.entry_type,
        entry_date=body.entry_date,
        symbol=body.symbol,
        instrument_type=body.instrument_type,
        direction=body.direction,
        entry_price=body.entry_price,
        exit_price=body.exit_price,
        position_size=body.position_size,
        stop_loss=body.stop_loss,
        risk_dollars=body.risk_dollars,
        net_pnl=body.net_pnl,
        thesis=body.thesis,
        strategy_tag=body.strategy_tag,
        mistake_tags=body.mistake_tags,
        execution_grade=body.execution_grade,
        status=body.status,
        lessons_learned=body.lessons_learned,
        notes=body.notes,
        position_id=body.position_id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get('/entries', response_model=list[JournalEntryOut])
async def list_entries(
    symbol: Optional[str] = None,
    strategy_tag: Optional[str] = None,
    entry_status: Optional[str] = Query(default=None, alias='status'),
    entry_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    # `entry_status` (not `status`) to avoid shadowing the imported
    # `fastapi.status` module within this function's scope — the public
    # query param stays `?status=` via the alias.
    q = select(JournalEntryModel).where(JournalEntryModel.user_id == 'default')
    if symbol:
        q = q.where(JournalEntryModel.symbol == symbol.upper())
    if strategy_tag:
        q = q.where(JournalEntryModel.strategy_tag == strategy_tag)
    if entry_status:
        q = q.where(JournalEntryModel.status == entry_status)
    if entry_type:
        q = q.where(JournalEntryModel.entry_type == entry_type)
    if date_from:
        q = q.where(JournalEntryModel.entry_date >= date_from)
    if date_to:
        q = q.where(JournalEntryModel.entry_date <= date_to)
    result = await db.execute(q.order_by(JournalEntryModel.entry_date.desc()))
    return result.scalars().all()


@router.get('/entries/{entry_id}', response_model=JournalEntryOut)
async def get_entry(entry_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JournalEntryModel).where(
            JournalEntryModel.id == entry_id, JournalEntryModel.user_id == 'default'
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Journal entry not found')
    return row


@router.put('/entries/{entry_id}', response_model=JournalEntryOut)
async def replace_entry(entry_id: str, body: JournalEntryCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JournalEntryModel).where(
            JournalEntryModel.id == entry_id, JournalEntryModel.user_id == 'default'
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Journal entry not found')
    row.entry_type = body.entry_type
    row.entry_date = body.entry_date
    row.symbol = body.symbol
    row.instrument_type = body.instrument_type
    row.direction = body.direction
    row.entry_price = body.entry_price
    row.exit_price = body.exit_price
    row.position_size = body.position_size
    row.stop_loss = body.stop_loss
    row.risk_dollars = body.risk_dollars
    row.net_pnl = body.net_pnl
    row.thesis = body.thesis
    row.strategy_tag = body.strategy_tag
    row.mistake_tags = body.mistake_tags
    row.execution_grade = body.execution_grade
    row.status = body.status
    row.lessons_learned = body.lessons_learned
    row.notes = body.notes
    row.position_id = body.position_id
    await db.commit()
    await db.refresh(row)
    return row


@router.delete('/entries/{entry_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JournalEntryModel).where(
            JournalEntryModel.id == entry_id, JournalEntryModel.user_id == 'default'
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail='Journal entry not found')
    await db.delete(row)
    await db.commit()
