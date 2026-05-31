# backend/app/models/closed_position.py
from sqlalchemy import Column, String, Float, Integer, DateTime
from datetime import datetime, timezone

from app.database import Base


class ClosedPositionModel(Base):
    """One row per sell event. A partial close creates a row for the closed
    portion and leaves the open position (with reduced qty) in place."""
    __tablename__ = "closed_positions"

    id = Column(String(36), primary_key=True)
    rec_id = Column(String, nullable=False, index=True)   # links to original open position; NOT unique
    symbol = Column(String, nullable=False)
    contract = Column(String, nullable=False, index=True)  # NOT unique (partials / re-buys)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_date = Column(String, nullable=True)
    exit_price = Column(Float, nullable=False)
    exit_date = Column(String, nullable=False)            # 'YYYY-MM-DD'
    qty_closed = Column(Integer, nullable=False)
    realized_pnl_dollar = Column(Float, nullable=False)
    realized_pnl_pct = Column(Float, nullable=False)
    source = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class EquitySnapshotModel(Base):
    """One total-account-value point per calendar day (upserted on portfolio read)."""
    __tablename__ = "equity_snapshots"

    id = Column(String(36), primary_key=True)
    snapshot_date = Column(String, nullable=False, unique=True, index=True)  # 'YYYY-MM-DD'
    realized_cumulative = Column(Float, nullable=False, default=0.0)
    open_value = Column(Float, nullable=False, default=0.0)
    total_value = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
