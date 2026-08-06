from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase


class ScanSessionBase(DeclarativeBase):
    """Standalone base for ScanSession — avoids conflict with the shared Base
    that injects a PostgreSQL UUID primary key and timestamp columns."""
    pass


class ScanSession(ScanSessionBase):
    __tablename__ = "scan_sessions"

    id               = Column(String, primary_key=True)   # UUID string
    status           = Column(String, nullable=False, default="idle")
    # "idle" | "running" | "complete" | "stopped"
    last_result_json  = Column(Text, nullable=True)         # JSON-serialized ScanResult
    last_request_json = Column(Text, nullable=True)         # JSON-serialized ScanRequest
    created_at        = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at       = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
