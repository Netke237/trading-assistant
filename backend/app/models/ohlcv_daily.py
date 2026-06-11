from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase


class OhlcvBase(DeclarativeBase):
    """Standalone base for the ohlcv_daily table."""
    pass


class OhlcvDailyModel(OhlcvBase):
    """Persistent daily OHLCV bars.

    Composite primary key: (symbol, date).
    open/high/low/close/volume store RAW (unadjusted) prices.
    adj_factor: fully-adjusted / raw  (multiply raw_close × adj_factor for scanner input).
    split_factor: split-only adjustment factor.
    div_cash: dividend cash amount at this bar date.
    source: which provider wrote this row ('alpaca', 'tiingo', 'yfinance', 'tiingo_legacy').
    """

    __tablename__ = "ohlcv_daily"

    symbol       = Column(String(10),                    primary_key=True, nullable=False)
    date         = Column(Date,                           primary_key=True, nullable=False)
    open         = Column(Numeric(precision=12, scale=4), nullable=False)
    high         = Column(Numeric(precision=12, scale=4), nullable=False)
    low          = Column(Numeric(precision=12, scale=4), nullable=False)
    close        = Column(Numeric(precision=12, scale=4), nullable=False)
    volume       = Column(BigInteger, nullable=False)
    adj_factor   = Column(Numeric(precision=12, scale=8), nullable=True)
    split_factor = Column(Numeric(precision=12, scale=8), nullable=True)
    div_cash     = Column(Numeric(precision=12, scale=4), nullable=True)
    source       = Column(String(20), nullable=True)
    fetched_at   = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
