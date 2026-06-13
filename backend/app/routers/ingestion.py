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


_UNIVERSE_PRESETS = {"SP500", "NDX100", "DOW30"}


@router.post("/ingest", status_code=202)
async def trigger_ingest(req: IngestRequest) -> dict:
    """Trigger a background ingestion run. Returns immediately.

    Symbols may include universe preset names (SP500, NDX100, DOW30) — these are
    expanded server-side before the job starts.
    """
    symbols = req.symbols
    if any(s in _UNIVERSE_PRESETS for s in symbols):
        try:
            from app.data.universe_presets import expand_universe
            expanded: list[str] = []
            for s in symbols:
                expanded.extend(expand_universe([s]) if s in _UNIVERSE_PRESETS else [s])
            symbols = list(dict.fromkeys(expanded))
        except Exception:
            pass
    start_ingestion_task(symbols, years=req.years)
    return {"status": "started", "total": len(symbols), "years": req.years}


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


@router.get("/ingest/last-refresh")
async def last_refresh() -> dict:
    """Return the UTC timestamp of the most recently written bar in ohlcv_daily.

    This is accurate regardless of what triggered the fill — nightly scheduler,
    manual prefetch from the Universe step, or on-demand get_bars() during a scan.
    Returns {"last_refresh": null} when the table is empty.
    """
    from sqlalchemy import func, select
    from app.models.ohlcv_daily import OhlcvDailyModel
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.max(OhlcvDailyModel.fetched_at)))
        ts = result.scalar_one_or_none()
    return {"last_refresh": ts.isoformat() if ts else None}


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
