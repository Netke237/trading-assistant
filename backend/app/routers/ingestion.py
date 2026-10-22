"""Ingestion router — manual trigger, status, and schedule endpoints.

POST /api/data/ingest          → trigger an ingestion run (fire-and-forget)
GET  /api/data/ingest/status   → current job state + single-provider symbols + Tiingo usage
GET  /api/data/ingest/schedule → nightly schedule config
POST /api/data/ingest/schedule → update nightly schedule config
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.data import tiingo_budget
from app.services.ingestion_job import (
    get_ingestion_state,
    single_provider_symbols,
    start_ingestion_task,
)
from app.services.ingestion_schedule_store import ingestion_schedule_store
from app.services import ingestion_scheduler
from app.services.history_retention import effective_years

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/data", tags=["ingestion"])

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class IngestRequest(BaseModel):
    symbols: list[str]
    years: int | None = Field(default=None, ge=1, le=20)
    force_backfill: bool = False
    # Rebuild every requested symbol from one provider (Tiingo, else yfinance)
    # instead of the normal Alpaca-suffix update.
    rebuild: bool = False


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
    years = effective_years(req.years)
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    started = start_ingestion_task(symbols, years=years, force_backfill=req.force_backfill,
                                   rebuild=req.rebuild)
    if started is False:
        raise HTTPException(status_code=409, detail="Ingestion already running")
    return {"status": "started", "total": len(symbols), "years": years, "rebuild": req.rebuild}


@router.get("/ingest/status")
async def ingest_status() -> dict:
    """Return the current ingestion job state and the persisted single-provider symbols."""
    try:
        singles = await single_provider_symbols()
    except Exception as exc:
        logger.warning("ingest status: single-provider symbols unavailable — %s", exc)
        singles = {}
    usage, usage_error = None, None
    try:
        usage = await tiingo_budget.usage_summary()
    except Exception as exc:
        logger.warning("ingest status: tiingo usage unavailable — %s", exc)
        usage_error = f"tiingo usage unavailable: {exc}"
    return {**get_ingestion_state(), "single_provider_symbols": singles,
            "tiingo_usage": usage, "tiingo_usage_error": usage_error}


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


# ── EDGAR fundamentals schedule ───────────────────────────────────────────────

@router.get("/edgar/schedule")
async def get_edgar_schedule() -> dict:
    from app.services.edgar_schedule_store import edgar_schedule_store
    from app.services import edgar_scheduler
    cfg = edgar_schedule_store.get()
    return {**cfg, "next_run": edgar_scheduler.next_run_time()}


@router.post("/edgar/schedule")
async def update_edgar_schedule(body: ScheduleUpdate) -> dict:
    if not _TIME_RE.match(body.time):
        raise HTTPException(status_code=422, detail="time must be HH:MM, e.g. '04:00'")
    hour, minute = int(body.time[:2]), int(body.time[3:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=422, detail="time out of range")
    from app.services.edgar_schedule_store import edgar_schedule_store
    from app.services import edgar_scheduler
    edgar_schedule_store.set(body.enabled, body.time)
    edgar_scheduler.configure(body.enabled, body.time)
    return {"ok": True, "enabled": body.enabled, "time": body.time, "next_run": edgar_scheduler.next_run_time()}


@router.post("/edgar/prefetch", status_code=202)
async def trigger_edgar_prefetch() -> dict:
    """Trigger an immediate EDGAR fundamentals prefetch in the background."""
    import threading
    from app.services.fundamentals_store import get_prefetch_status, prefetch_universe
    if get_prefetch_status()["in_progress"]:
        raise HTTPException(status_code=409, detail="Prefetch already running")
    try:
        from app.data.universe_presets import expand_universe
        symbols = list(dict.fromkeys(
            expand_universe(["SP500"]) + expand_universe(["NDX100"]) + expand_universe(["DOW30"])
        ))
    except Exception:
        symbols = ["SPY", "QQQ", "AAPL", "MSFT"]
    threading.Thread(target=prefetch_universe, args=(symbols,), daemon=True, name="edgar-prefetch-manual").start()
    return {"status": "started", "total": len(symbols)}


@router.get("/edgar/status")
async def edgar_prefetch_status() -> dict:
    from app.services.fundamentals_store import get_prefetch_status
    return get_prefetch_status()


# ── S&P 500 liquidity update schedule ────────────────────────────────────────

@router.get("/sp500/schedule")
async def get_sp500_schedule() -> dict:
    from app.services.sp500_schedule_store import sp500_schedule_store
    from app.services import sp500_scheduler
    cfg = sp500_schedule_store.get()
    return {**cfg, "next_run": sp500_scheduler.next_run_time()}


@router.post("/sp500/schedule")
async def update_sp500_schedule(body: ScheduleUpdate) -> dict:
    if not _TIME_RE.match(body.time):
        raise HTTPException(status_code=422, detail="time must be HH:MM, e.g. '16:30'")
    hour, minute = int(body.time[:2]), int(body.time[3:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=422, detail="time out of range")
    from app.services.sp500_schedule_store import sp500_schedule_store
    from app.services import sp500_scheduler
    sp500_schedule_store.set(body.enabled, body.time)
    sp500_scheduler.configure(body.enabled, body.time)
    return {"ok": True, "enabled": body.enabled, "time": body.time, "next_run": sp500_scheduler.next_run_time()}


@router.post("/sp500/update", status_code=202)
async def trigger_sp500_update() -> dict:
    """Trigger an immediate S&P 500 liquidity update in the background."""
    from app.services.sp500_update_service import start_update_task, get_update_state
    if get_update_state()["in_progress"]:
        raise HTTPException(status_code=409, detail="Update already running")
    started = start_update_task()
    if not started:
        raise HTTPException(status_code=409, detail="Update already running")
    return {"status": "started"}


@router.get("/sp500/status")
async def sp500_update_status() -> dict:
    from app.services.sp500_update_service import get_update_state
    return get_update_state()
