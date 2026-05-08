from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Audit log path — relative to wherever uvicorn is started (project root or backend/).
# Writing to backend/ when started from backend/:
_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "audit.log")
_LOG_PATH = os.path.normpath(_LOG_PATH)


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
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # audit failures are non-fatal


# ── DB-backed audit helpers ───────────────────────────────────────────────────
# These write to the AuditEvent table AND call log_event() for JSONL
# dual-system traceability.  rec_id must use new_rec_id() format.

async def log_approval(rec_id: str, trade_card_data: dict, db: "AsyncSession") -> None:
    """Write approval event to AuditEvent table and JSONL audit.log."""
    from app.models.audit_event import AuditEventModel  # deferred to avoid circular import

    event = AuditEventModel(
        event_type="approval",
        rec_id=rec_id,
        recommendation_id=rec_id,
        payload=trade_card_data,
    )
    db.add(event)
    await db.commit()
    # Dual-system traceability: also write to JSONL
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
