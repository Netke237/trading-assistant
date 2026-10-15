from __future__ import annotations

import glob
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Audit log path — relative to wherever uvicorn is started (project root or backend/).
# Writing to backend/ when started from backend/:
_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "audit.log")
_LOG_PATH = os.path.normpath(_LOG_PATH)

_ROTATE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB safety cap between monthly rotations
# Shared by log_event(), rotate_audit_log(), and prune_audit_log_archives() —
# without this, a log_event() write landing between rotation's read and
# truncate would be silently dropped, for the one file whose entire purpose
# is "never lose a trade-rationale record."
_log_lock = threading.Lock()
_ARCHIVE_RE = re.compile(r"audit-(\d{4})-(\d{2})\.log$")


def new_rec_id() -> str:
    """
    Generate a unique, human-readable recommendation ID.
    Format: REC-YYYYMMDD-XXXXXXXX  (e.g. REC-20260430-A3F2B1C9)
    Guaranteed unique within a session; collisions across sessions are astronomically rare.
    """
    date_part = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    random_part = uuid4().hex[:8].upper()
    return f"REC-{date_part}-{random_part}"


def log_event(
    event_type: str,
    rec_id: str,
    payload: dict,
) -> None:
    """
    Append one structured event line to audit.log (JSONL format).

    Args:
        event_type: one of the event type constants below (any string is accepted)
        rec_id:     recommendation ID from new_rec_id()
        payload:    arbitrary dict of event-specific data

    Event types used across the codebase:
        "scan_started"          — a new scan run has begun
        "candidate_accepted"    — a stock passed all scoring gates
        "candidate_rejected"    — a stock was rejected at any gate
        "trade_card_created"    — a trade card was generated for a candidate
        "approval"              — a trade card was approved by the user

    The function silently ignores write errors (disk full, permissions, etc.)
    so audit failures never crash the scan pipeline.
    """
    entry = {
        "ts":        datetime.now(tz=timezone.utc).isoformat(),
        "event":     event_type,
        "rec_id":    rec_id,
        **payload,
    }
    try:
        with _log_lock:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit failures are non-fatal


def _archive_path_for(dt: datetime) -> str:
    return os.path.join(os.path.dirname(_LOG_PATH), f"audit-{dt:%Y-%m}.log")


def rotate_audit_log(now: datetime | None = None) -> None:
    """Rename audit.log to audit-YYYY-MM.log if the current month's archive
    doesn't exist yet, or if the live file has grown past the size cap.

    Archive, don't delete: the live file's content always survives (either as
    the freshly-renamed archive, or appended into an already-existing one).
    Called once nightly, piggybacked on the ingestion job's nightly tick
    (Part 1, Step 2's operator-timezone-anchored scheduler) — a few hundred
    lines/day doesn't need its own cadence.
    """
    now = now or datetime.now(timezone.utc)
    with _log_lock:
        if not os.path.exists(_LOG_PATH):
            return
        archive = _archive_path_for(now)
        needs_rotation = not os.path.exists(archive) or os.path.getsize(_LOG_PATH) > _ROTATE_SIZE_BYTES
        if not needs_rotation:
            return
        try:
            if os.path.exists(archive):
                # Mid-month size-triggered rotation into an archive that
                # already exists for this month — append, don't clobber.
                with open(_LOG_PATH, "r", encoding="utf-8") as src, open(archive, "a", encoding="utf-8") as dst:
                    dst.write(src.read())
                open(_LOG_PATH, "w", encoding="utf-8").close()
            else:
                os.replace(_LOG_PATH, archive)
        except Exception:
            pass  # rotation failures are non-fatal, same policy as log_event() itself


def prune_audit_log_archives(retention_years: int) -> None:
    """Delete archived audit-YYYY-MM.log files older than retention_years.

    Only ever touches archives, never the live audit.log — this is a prune
    of history, not of the current trade-rationale trail. Shares
    history_retention_years with history_cleanup.prune_old_history (the
    AuditEventModel DB-side counterpart) so both copies of the same data
    expire on the same clock. retention_years * 365 has no leap-year
    adjustment — inherited from that same function's arithmetic, deliberately
    left as-is so the two stay in sync rather than drifting apart at the
    margin.
    """
    if retention_years <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_years * 365)
    with _log_lock:
        for path in glob.glob(os.path.join(os.path.dirname(_LOG_PATH), "audit-*.log")):
            m = _ARCHIVE_RE.search(path)
            if not m:
                continue
            archived_month = datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=timezone.utc)
            if archived_month < cutoff:
                try:
                    os.remove(path)
                except Exception:
                    pass


# ── DB-backed audit helpers ───────────────────────────────────────────────────
# These write to the AuditEvent table AND call log_event() for JSONL
# dual-system traceability.  rec_id must use new_rec_id() format.

async def log_approval(rec_id: str, trade_card_data: dict, db: "AsyncSession") -> None:
    """Write one approval, or nothing if a hard delete already removed the trade.

    Callers commit the position first and treat a failure here as non-fatal.
    The insert takes the same exposure guard as DELETE. There is no foreign
    key: a retained closed-history row still gets the approval, and an open
    row does too. If neither row is left, skip the table and the JSONL line.
    """
    from sqlalchemy import select

    from app.models.audit_event import AuditEventModel  # deferred to avoid circular import
    from app.models.closed_position import ClosedPositionModel
    from app.models.portfolio import PortfolioPositionModel
    from app.services.portfolio_exposure import lock_exposure

    # The position refresh leaves a read snapshot. End it before the guard,
    # or this transaction can miss the delete it waited on. Rollback is not
    # usable here: it expires every object, including the position the caller
    # still reads after this returns.
    sync = db.sync_session
    if not (sync.new or sync.dirty or sync.deleted):
        await db.commit()

    await lock_exposure(db)
    open_row = (await db.execute(
        select(PortfolioPositionModel.id).where(PortfolioPositionModel.rec_id == rec_id)
    )).first()
    if open_row is None:
        closed_row = (await db.execute(
            select(ClosedPositionModel.id).where(ClosedPositionModel.rec_id == rec_id)
        )).first()
        if closed_row is None:
            await db.commit()
            return

    event = AuditEventModel(
        event_type="approval",
        rec_id=rec_id,
        recommendation_id=rec_id,
        payload=trade_card_data,
    )
    db.add(event)
    await db.commit()
    # JSONL only after the guarded row commits. log_event swallows its own errors.
    log_event("approval", rec_id, trade_card_data)


async def log_rejection(rec_id: str, reason: str, db: "AsyncSession") -> None:
    """Write rejection event to AuditEvent table and JSONL audit.log."""
    from app.models.audit_event import AuditEventModel

    payload = {"reason": reason}
    event = AuditEventModel(
        event_type="rejection",
        rec_id=rec_id,
        recommendation_id=rec_id,
        payload=payload,
    )
    db.add(event)
    await db.commit()
    log_event("rejection", rec_id, payload)


async def log_override(rec_id: str, override_data: dict, db: "AsyncSession") -> None:
    """Write override event to AuditEvent table and JSONL audit.log."""
    from app.models.audit_event import AuditEventModel

    event = AuditEventModel(
        event_type="override",
        rec_id=rec_id,
        recommendation_id=rec_id,
        payload=override_data,
    )
    db.add(event)
    await db.commit()
    log_event("override", rec_id, override_data)
