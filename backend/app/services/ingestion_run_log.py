"""Persisted ingestion run summaries (HISTORY-INCREMENTAL-NIGHTLY C1b).

``ingestion_job._state`` lives in memory only, so after a backend restart the status
endpoint had no run to show. ``run_ingestion`` records each run here:

- ``record_start`` inserts one ``running`` row at the run's start and, in the same
  transaction, keeps only the newest ``KEEP_ROWS`` rows by ``id``. ``id`` is autoincrement
  and runs never overlap, so ``id`` is the true start order; ``started_at`` is a wall clock
  that can step backwards and is never used for ordering.
- ``record_finish`` writes the finish (status, finished_at, the JSON state snapshot): an
  UPDATE of the start row, tried twice; or, when the start insert failed, one INSERT of the
  complete row with the same prune. A run leaves no row only when both its writes failed.
- ``latest_run`` reads the row with the highest ``id`` for the status endpoint.

Every write is bounded by ``RUN_LOG_WRITE_TIMEOUT_S`` and is fail-open: an exception or a
timeout (including a missing table on a SQLite dev/test database) is logged at error level
and swallowed, and never changes the run, its state, its counters or its return value. A
row whose finish was never written stays ``running`` with ``finished_at`` NULL.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select, update

from app.database import AsyncSessionLocal
from app.models.ingestion_run import IngestionRun

logger = logging.getLogger(__name__)

RUN_LOG_WRITE_TIMEOUT_S = 10.0     # per write attempt
KEEP_ROWS = 50
FINISH_UPDATE_ATTEMPTS = 2


def _parse_utc(iso: str) -> datetime:
    """An ISO timestamp from ``_state`` as an aware UTC datetime (naive is taken as UTC)."""
    value = datetime.fromisoformat(iso)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    """ISO 8601 with an explicit UTC offset; SQLite reads DateTime back naive (stored UTC)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _prune():
    """Delete every row except the KEEP_ROWS with the highest id."""
    keep = select(IngestionRun.id).order_by(IngestionRun.id.desc()).limit(KEEP_ROWS)
    return (delete(IngestionRun).where(IngestionRun.id.not_in(keep))
            .execution_options(synchronize_session=False))


async def _insert_row(**values: Any) -> int:
    async with AsyncSessionLocal() as db:
        row = IngestionRun(**values)
        db.add(row)
        await db.flush()
        run_id = row.id
        await db.execute(_prune())
        await db.commit()
        return run_id


async def _insert_start(started_at: datetime) -> int:
    return await _insert_row(started_at=started_at, status="running")


async def _insert_finished(status: str, started_at: datetime, finished_at: datetime,
                           summary: str) -> int:
    return await _insert_row(status=status, started_at=started_at, finished_at=finished_at,
                             summary=summary)


async def _update_finish(run_id: int, status: str, finished_at: datetime, summary: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(IngestionRun).where(IngestionRun.id == run_id)
            .values(status=status, finished_at=finished_at, summary=summary)
            .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise RuntimeError(f"ingestion_run row {run_id} not found")
        await db.commit()


async def _bounded(what: str, write: Callable[[], Awaitable[Any]]) -> tuple[bool, Any]:
    """Run one write under the timeout; (True, its result), or (False, None) after logging."""
    try:
        return True, await asyncio.wait_for(write(), RUN_LOG_WRITE_TIMEOUT_S)
    except Exception as exc:     # incl. TimeoutError and a missing table
        logger.error("ingestion run log: %s failed — %s: %s", what, type(exc).__name__, exc)
        return False, None


async def record_start(started_at: str) -> int | None:
    """Insert the run's ``running`` row; its id, or None when the insert failed."""
    try:
        when = _parse_utc(started_at)
    except Exception as exc:
        logger.error("ingestion run log: start insert failed — %s: %s", type(exc).__name__, exc)
        return None
    ok, run_id = await _bounded("start insert", lambda: _insert_start(when))
    return run_id if ok else None


async def record_finish(run_id: int | None, state: dict) -> None:
    """Write the run's finish from its final state snapshot (``get_ingestion_state()``)."""
    try:
        summary = json.dumps(state)      # no default=: a non-JSON value must fail loudly
        status = state["status"]
        started_at = _parse_utc(state["started_at"])
        finished_at = _parse_utc(state["finished_at"])
    except Exception as exc:
        logger.error("ingestion run log: finish write failed — %s: %s", type(exc).__name__, exc)
        return
    if run_id is None:
        await _bounded("finish insert",
                       lambda: _insert_finished(status, started_at, finished_at, summary))
        return
    for attempt in range(1, FINISH_UPDATE_ATTEMPTS + 1):
        ok, _ = await _bounded(f"finish update of row {run_id} (attempt {attempt})",
                               lambda: _update_finish(run_id, status, finished_at, summary))
        if ok:
            return
    logger.error("ingestion run log: finish of row %s given up; it stays 'running'", run_id)


async def latest_run() -> dict | None:
    """The row with the highest id, or None when the table is empty. Raises on a read error."""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(IngestionRun).order_by(IngestionRun.id.desc()).limit(1)
        )).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id":          row.id,
        "status":      row.status,
        "started_at":  _iso_utc(row.started_at),
        "finished_at": _iso_utc(row.finished_at),
        "summary":     json.loads(row.summary) if row.summary is not None else None,
    }
