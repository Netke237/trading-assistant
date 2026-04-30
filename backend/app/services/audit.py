from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

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
