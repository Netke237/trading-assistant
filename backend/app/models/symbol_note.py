"""SQLAlchemy model for per-symbol free-text notes."""
from __future__ import annotations

from sqlalchemy import Column, String, Text, DateTime
from datetime import datetime, timezone
from app.database import Base


class SymbolNoteModel(Base):
    __tablename__ = 'symbol_notes'

    symbol = Column(String(10), primary_key=True)
    body = Column(Text(), nullable=False, default='')
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
