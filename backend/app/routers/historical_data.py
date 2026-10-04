"""POST /api/historical-data/prefetch  — start background OHLCV prefetch.
GET  /api/historical-data/prefetch/status — return current job state.
POST /api/historical-data/refresh-adjustments — re-fetch symbols with stale adj factors.
"""
from __future__ import annotations

from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.historical_store import (
    get_prefetch_status, prefetch_universe, refresh_adjustments,
)
from app.data.universe_presets import expand_universe

router = APIRouter(prefix="/api/historical-data", tags=["historical-data"])


class PrefetchRequest(BaseModel):
    universe: list[str] = Field(..., description="Preset keys (e.g. ['SP500']) or ticker lists")
    years:    int        = Field(default=5, ge=1, le=10, description="Years of history to load")
    delay_secs: float    = Field(default=0.5, ge=0.05, le=10.0,
                                 description="Seconds between Tiingo requests (0.5 = 2 req/s, safe for free tier)")


class PrefetchStatus(BaseModel):
    status:         Literal["idle", "running", "completed", "error"]
    total:          int
    done:           int
    failed:         int
    current_symbol: Optional[str]
    elapsed_secs:   float
    started_at:     Optional[str]


@router.post("/prefetch")
async def start_prefetch(req: PrefetchRequest) -> dict:
    """Start a background job that pre-loads OHLCV history for a universe.

    Safe to call while a scan is running — the prefetch is a separate background task.
    Returns immediately; poll /prefetch/status to track progress.
    """
    try:
        symbols = expand_universe(req.universe)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not symbols:
        raise HTTPException(status_code=400, detail="Universe expanded to zero symbols")

    current = get_prefetch_status()
    if current["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail=f"Prefetch already running ({current['done']}/{current['total']} done). "
                   "Wait for it to complete or restart the backend to cancel."
        )

    prefetch_universe(symbols, years=req.years, delay_secs=req.delay_secs)
    return {
        "message": f"Prefetch started for {len(symbols)} symbols ({req.years}y history)",
        "total":   len(symbols),
    }


@router.get("/prefetch/status", response_model=PrefetchStatus)
def prefetch_status() -> dict:
    """Return the current state of the background prefetch job."""
    return get_prefetch_status()


class RefreshAdjustmentsRequest(BaseModel):
    symbols: list[str] = Field(
        default_factory=list,
        description="Symbols to check; an empty list means every symbol in ohlcv_daily",
    )


@router.post("/refresh-adjustments")
async def refresh_adjustments_endpoint(req: RefreshAdjustmentsRequest) -> dict:
    """Find symbols whose stored adj factors span stale fetch batches and re-fetch them.

    Runs inline (an operator call, TRADING-REVIEW-PHASE-C T3). Never deletes rows.
    Returns ``{checked, stale: [{symbol, reasons, earliest}], refreshed, failed}``.
    """
    return await refresh_adjustments([s.strip().upper() for s in req.symbols if s.strip()])
