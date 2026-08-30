"""SQLAlchemy model for the trading journal — trade-centric and freeform
('note') entries in one table, discriminated by `entry_type`."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, Float, Integer, DateTime, JSON
from app.database import Base


class JournalEntryModel(Base):
    __tablename__ = 'journal_entries'

    id = Column(String(36), primary_key=True)
    user_id = Column(String(64), nullable=False, default='default')
    entry_type = Column(String(10), nullable=False)
    entry_date = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String(10), nullable=True)
    instrument_type = Column(String(10), nullable=True)
    direction = Column(String(10), nullable=True)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    position_size = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    risk_dollars = Column(Float, nullable=True)
    net_pnl = Column(Float, nullable=True)
    thesis = Column(Text, nullable=True)
    strategy_tag = Column(String(64), nullable=True)
    mistake_tags = Column(JSON, nullable=True)
    execution_grade = Column(Integer, nullable=True)
    status = Column(String(10), nullable=True)
    lessons_learned = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    position_id = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
