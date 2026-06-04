from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, Date, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase


class OhlcvBase(DeclarativeBase):
    """Standalone base for the ohlcv_daily table.
    Uses a composite (symbol, date) primary key — no UUID needed."""
    pass


class OhlcvDailyModel(OhlcvBase):
    """Persistent daily OHLCV bars fetched from Tiingo.

    Composite primary key: (symbol, date).
    Bars are written once and never deleted — history only grows.
    Fetching uses adjusted prices (adjOpen / adjClose etc.).
    """

    __tablename__ = "ohlcv_daily"

    symbol     = Column(String(10), primary_key=True, nullable=False)
    date       = Column(Date,        primary_key=True, nullable=False)
    open       = Column(Float,  nullable=False)
    high       = Column(Float,  nullable=False)
    low        = Column(Float,  nullable=False)
    close      = Column(Float,  nullable=False)
    volume     = Column(BigInteger, nullable=False)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
