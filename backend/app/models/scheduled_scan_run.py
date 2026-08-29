from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import DeclarativeBase


class ScheduledScanRunBase(DeclarativeBase):
    """Standalone base, mirroring ScanSession's own pattern — avoids conflict
    with the shared Base that injects a PostgreSQL UUID primary key."""
    pass


class ScheduledScanRunModel(ScheduledScanRunBase):
    """One row per completed (success or error) Part-3 scheduled-scan-entry
    fire. This is where a schedule entry's runtime state actually lives —
    ScanScheduleEntry (the YAML-backed config record) carries none, by
    design (see schemas/scan_schedule.py)."""
    __tablename__ = "scheduled_scan_runs"

    id                = Column(String, primary_key=True)              # uuid
    schedule_entry_id = Column(String, index=True, nullable=False)    # ScanScheduleEntry.id
    mode              = Column(String, nullable=False)                # 'options' | 'stocks'
    fired_at          = Column(DateTime(timezone=True), nullable=False)
    status            = Column(String, nullable=False)                # 'success' | 'error'
    error             = Column(Text, nullable=True)                   # populated only on status == 'error'
    result_json       = Column(Text, nullable=True)                   # full ScanResult/StockScanResult JSON, null on error
    created_at        = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
