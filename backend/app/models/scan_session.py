from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, Integer
from app.database import Base


class ScanSession(Base):
    __tablename__ = "scan_sessions"

    id                = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status            = Column(String, nullable=False, default="QUEUED")
    progress_scanned  = Column(Integer, default=0)
    progress_total    = Column(Integer, default=0)
    candidates_found  = Column(Integer, default=0)
    error_message     = Column(String, nullable=True)
    last_result_json  = Column(Text, nullable=True)
    last_request_json = Column(Text, nullable=True)
    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at      = Column(DateTime(timezone=True), nullable=True)
