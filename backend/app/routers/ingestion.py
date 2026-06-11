"""Ingestion router — manual trigger and status endpoint.

POST /api/data/ingest        → trigger an ingestion run (fire-and-forget)
GET  /api/data/ingest/status → current job state
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.ingestion_job import start_ingestion_task, get_ingestion_state

router = APIRouter(prefix="/api/data", tags=["ingestion"])


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
