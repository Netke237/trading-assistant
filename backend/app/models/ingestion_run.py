"""Persisted summary of each ingestion run (HISTORY-INCREMENTAL-NIGHTLY C1b).

``ingestion_job._state`` lives in memory only; one row per run here lets the status
endpoint show the latest run after a backend restart. Written fail-open by
``app.services.ingestion_run_log``; the newest 50 rows (by ``id``) are kept.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class IngestionRunBase(DeclarativeBase):
    """Standalone base for the ingestion_run table."""
    pass


class IngestionRun(IngestionRunBase):
    __tablename__ = "ingestion_run"

    # Autoincrement: one run at a time, so id is the true start order (started_at, a wall
    # clock, can step backwards). "Latest" and retention are ordered by id only.
    id          = Column(Integer, primary_key=True, autoincrement=True)
    started_at  = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)   # NULL while running
    status      = Column(String(16), nullable=False)               # running | completed | error
    summary     = Column(Text, nullable=True)   # JSON of get_ingestion_state() at finish; NULL while running
