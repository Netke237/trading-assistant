# backend/app/models/drawing.py
"""SQLAlchemy model for user chart drawings."""
from __future__ import annotations

from sqlalchemy import Column, String, Integer, Text, Index
from app.database import Base


class DrawingModel(Base):
    __tablename__ = 'drawings'

    id = Column(String(64), primary_key=True)
    symbol = Column(String(10), nullable=False)
    interval = Column(String(10), nullable=False)
    kind = Column(String(20), nullable=False)
    points_json = Column(Text(), nullable=False)   # JSON list of {time, price}
    color = Column(String(20), nullable=False)
    width = Column(Integer(), nullable=False, default=1)
    created_at = Column(Text(), nullable=False)

    __table_args__ = (
        Index('ix_drawings_symbol', 'symbol'),
        Index('ix_drawings_symbol_interval', 'symbol', 'interval'),
    )
