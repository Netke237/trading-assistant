"""Ingestion router — manual trigger, status, and schedule endpoints.

POST /api/data/ingest          → trigger an ingestion run (fire-and-forget)
GET  /api/data/ingest/status   → current job state
GET  /api/data/ingest/schedule → nightly schedule config
POST /api/data/ingest/schedule → update nightly schedule config
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.ingestion_job import start_ingestion_task, get_ingestion_state
from app.services.ingestion_schedule_store import ingestion_schedule_store
from app.services import ingestion_scheduler

router = APIRouter(prefix="/api/data", tags=["ingestion"])

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class IngestRequest(BaseModel):
    symbols: list[str]
    years: int = Field(default=6, ge=1, le=10)


@router.post("/ingest", status_code=202)
async def trigger_ingest(req: IngestRequest) -> dict:
    """Trigger a background ingestion run. Returns immediately."""
    start_ingestion_task(req.symbols, years=req.years)
    return {"status": "started", "total": len(req.symbols), "years": req.years}


@router.get("/ingest/status")
async def ingest_status() -> dict:
    """Return the current ingestion job state."""
    return get_ingestion_state()


# ── Schedule endpoints ────────────────────────────────────────────────────────

class ScheduleUpdate(BaseModel):
    enabled: bool
    time: str = Field(description="HH:MM in 24-hour format, e.g. '03:00'")


@router.get("/ingest/schedule")
async def get_schedule() -> dict:
    """Return the current nightly ingestion schedule configuration."""
    cfg = ingestion_schedule_store.get()
    return {**cfg, "next_run": ingestion_scheduler.next_run_time()}


@router.post("/ingest/schedule")
async def update_schedule(body: ScheduleUpdate) -> dict:
    """Save schedule config and reconfigure the APScheduler job immediately."""
    if not _TIME_RE.match(body.time):
        raise HTTPException(status_code=422, detail="time must be HH:MM, e.g. '03:00'")
    hour, minute = int(body.time[:2]), int(body.time[3:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=422, detail="time out of range")
    ingestion_schedule_store.set(body.enabled, body.time)
    ingestion_scheduler.configure(body.enabled, body.time)
    return {"ok": True, "enabled": body.enabled, "time": body.time, "next_run": ingestion_scheduler.next_run_time()}
