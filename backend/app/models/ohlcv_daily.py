from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import BigInteger, Column, Date, DateTime, Numeric, String
from sqlalchemy.orm import DeclarativeBase


class OhlcvBase(DeclarativeBase):
    """Standalone base for the ohlcv_daily table."""
    pass


class OhlcvDailyModel(OhlcvBase):
    """Persistent daily OHLCV bars.

    Composite primary key: (symbol, date).
    Tiingo/Alpaca store raw OHLC and volume; yfinance stores adjusted OHLC with factor 1.
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
    )


class OhlcvHistoryStateModel(OhlcvBase):
    """Observed provider floor and exact seam verification, committed with daily bars.

    basis_provider set ('tiingo' / 'yfinance') = the symbol's whole retained series comes
    from that one provider and is routed away from the Alpaca seam path; NULL = normal path.

    window_verified_through / window_verified_at = the nightly window anchor: the newest date
    the last nightly single-provider write fetched and verified together with the rows before
    it, and when that write committed. Written only by the single-provider writer (nightly and
    ``rebuild_single_provider``), never by on-demand ``get_bars``; NULL = no anchor.
    """
    __tablename__ = "ohlcv_history_state"

    symbol = Column(String(10), primary_key=True)
    floor_requested_start = Column(Date, nullable=True)
    floor_date = Column(Date, nullable=True)
    floor_provider = Column(String(20), nullable=True)
    floor_checked_at = Column(DateTime(timezone=True), nullable=True)
    seam_date = Column(Date, nullable=True)
    old_source = Column(String(20), nullable=True)
    seam_signature = Column(String(64), nullable=True)
    basis_provider = Column(String(20), nullable=True)
    basis_rebuilt_at = Column(DateTime(timezone=True), nullable=True)
    window_verified_through = Column(Date, nullable=True)
    window_verified_at = Column(DateTime(timezone=True), nullable=True)

    def verified_seam(self) -> dict:
        return {"seam_date": self.seam_date, "old_source": self.old_source,
                "seam_signature": self.seam_signature}
