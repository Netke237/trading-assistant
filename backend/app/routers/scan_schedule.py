"""Part 3 — profile-based scan scheduling endpoints.

GET/POST/PUT/DELETE /api/scan-schedule[/{id}] manage the ScanScheduleEntry
list; POST .../run-now bypasses the schedule for a one-off test fire; GET
.../runs serves this entry's ScheduledScanRunModel history.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.scan_schedule import ScanScheduleEntry, ScanScheduleEntryCreate
from app.services.scan_schedule_store import (
    scan_schedule_store, delete_scheduled_scan_runs, list_scheduled_scan_runs,
)
from app.services.scan_schedule_scheduler import sync_fixed_time_jobs, _run_scheduled_entry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scan-schedule", tags=["scan-schedule"])


def _build_entry(entry_id: str, body: ScanScheduleEntryCreate) -> ScanScheduleEntry:
    """ScanScheduleEntryCreate (the request-body model FastAPI already
    validated) carries none of ScanScheduleEntry's cross-field validators
    (pattern-specific fields, resolved_request shape) — those only run when
    ScanScheduleEntry itself is constructed here, so a pydantic
    ValidationError at this point is a genuine 422, not a 500."""
    try:
        entry = ScanScheduleEntry(id=entry_id, **body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if entry.mode == "stocks":
        # STOCKS-HORIZON-T1 F1: the same merged-shape (profile + request)
        # mean_reversion_multi check run_stock_scan applies, so a schedule
        # that could never fire a candidate is refused at save time with the
        # scan's own 422 and reason. Local import, as in the scheduler.
        from app.schemas.stock_scan import StockScanRequest
        from app.routers.stock_scan import _reject_unsupported_multi_variants
        _reject_unsupported_multi_variants(StockScanRequest.model_validate(entry.resolved_request))
    return entry


@router.get("", response_model=list[ScanScheduleEntry])
async def list_scan_schedule_entries() -> list[ScanScheduleEntry]:
    """Every stored entry that still validates. NUMERIC-API-INPUTS T2: an entry
    that no longer does (e.g. a resolved_request stored with a non-finite
    number, which ScanRequest/StockScanRequest now refuse) is SKIPPED with a
    warning naming its id, rather than turning the whole list into a 500 --
    the drop-with-warning rule restore_stock_from_db already applies. It stays
    in the store: DELETE still removes it and the scheduler records its
    failed runs."""
    entries: list[ScanScheduleEntry] = []
    for e in scan_schedule_store.list():
        try:
            entries.append(ScanScheduleEntry.model_validate(e))
        except ValidationError as exc:
            logger.warning(
                "scan_schedule: entry %s no longer validates and is left out of "
                "the list: %s", e.get("id") if isinstance(e, dict) else None, exc,
            )
    return entries


@router.post("", response_model=ScanScheduleEntry)
async def create_scan_schedule_entry(body: ScanScheduleEntryCreate) -> ScanScheduleEntry:
    entry = _build_entry(str(uuid.uuid4()), body)
    scan_schedule_store.upsert(entry.model_dump())
    sync_fixed_time_jobs()
    return entry


@router.put("/{entry_id}", response_model=ScanScheduleEntry)
async def update_scan_schedule_entry(entry_id: str, body: ScanScheduleEntryCreate) -> ScanScheduleEntry:
    """Full replace by id. This is also the automatic re-sync path the
    frontend calls whenever a referenced profile is saved (3.4) — pushing a
    freshly re-resolved `resolved_request` keeps a schedule entry's request
    body always reflecting the profile's last explicit save."""
    if scan_schedule_store.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"schedule entry {entry_id} not found")
    entry = _build_entry(entry_id, body)
    scan_schedule_store.upsert(entry.model_dump())
    sync_fixed_time_jobs()
    return entry


@router.delete("/{entry_id}")
async def delete_scan_schedule_entry(entry_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    if scan_schedule_store.get(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"schedule entry {entry_id} not found")
    scan_schedule_store.delete(entry_id)
    sync_fixed_time_jobs()
    # Must also delete this entry's ScheduledScanRunModel rows — the YAML
    # store has no FK/cascade to rely on. Without this, a deleted entry's
    # rows (including the one row prune_scheduled_scan_runs's "latest
    # success" exclusion protects) would escape pruning forever.
    await delete_scheduled_scan_runs(db, entry_id)
    return {"deleted": True, "id": entry_id}


@router.post("/{entry_id}/run-now")
async def run_scan_schedule_entry_now(entry_id: str) -> dict:
    """Bypass the schedule, execute immediately — mirrors the existing
    run_now() pattern on strategy_watch_scheduler.py. Useful for testing a
    newly-created entry without waiting for its fire time.

    Rejects a disabled entry rather than reporting a false "triggered: true"
    — flagged by post-implementation adversarial review: _run_scheduled_entry
    itself silently no-ops on a disabled entry (by design, for the scheduler
    dispatch paths, where that's the correct behavior for a race against
    deletion/disabling), which without this check would let a user pause an
    entry, click "Run now" to test it, and see a false success with nothing
    actually run and no row written to ScheduledScanRunModel."""
    entry = scan_schedule_store.get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"schedule entry {entry_id} not found")
    if not entry.get("enabled"):
        raise HTTPException(status_code=409, detail=f"schedule entry {entry_id} is disabled — enable it first")
    await _run_scheduled_entry(entry_id)
    return {"triggered": True, "id": entry_id}


@router.get("/{entry_id}/runs")
async def get_scan_schedule_entry_runs(
    entry_id: str, limit: int = 20, db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await list_scheduled_scan_runs(db, entry_id, limit=limit)
    return [
        {
            "id": r.id,
            "schedule_entry_id": r.schedule_entry_id,
            "mode": r.mode,
            "fired_at": r.fired_at.isoformat() if r.fired_at else None,
            "status": r.status,
            "error": r.error,
            "candidate_count": _candidate_count(r.result_json),
        }
        for r in rows
    ]


def _candidate_count(result_json: str | None) -> int | None:
    if not result_json:
        return None
    try:
        import json
        return len(json.loads(result_json).get("candidates", []))
    except Exception:
        return None
