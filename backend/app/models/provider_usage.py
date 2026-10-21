"""Persisted per-attempt provider request ledger (HISTORY-INCREMENTAL-NIGHTLY A1).

One row per HTTP attempt that reached the provider; `app.data.tiingo_budget`
reads it to enforce Tiingo's free-tier limits across restarts.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase


class ProviderUsageBase(DeclarativeBase):
    """Standalone base for the provider_request_log table."""
    pass


class ProviderRequestLog(ProviderUsageBase):
    __tablename__ = "provider_request_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    provider       = Column(String(20), nullable=False)
    requested_at   = Column(DateTime(timezone=True), nullable=False)
    symbol         = Column(String(16), nullable=True)      # provider spelling; NULL for the probe
    response_bytes = Column(BigInteger, nullable=False)     # len(resp.content), uncompressed body
    status_code    = Column(Integer, nullable=False)
    caller         = Column(String(16), nullable=False)     # nightly | on_demand | probe

    __table_args__ = (
        Index("ix_provider_request_log_provider_requested_at", "provider", "requested_at"),
    )
