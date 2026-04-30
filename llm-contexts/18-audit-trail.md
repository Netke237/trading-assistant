# LLM Context — Audit Trail + Recommendation IDs (Workstream 18)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one file (`backend/app/services/audit.py`). It does not touch `frontend/`, any router, any fixture, any schema, or `main.py`.

**Goal:**
Provide a lightweight structured audit log and recommendation ID generator. Later workstreams (WS-25's scan endpoint, WS-27's RunScanButton) import these utilities to log every decision with a unique traceable ID. The log is written to `backend/audit.log` as newline-delimited JSON (JSONL).

**What NOT to touch:**
- Any file under `frontend/`
- Any existing router, fixture, schema, or model file
- `backend/app/main.py`
- `backend/app/services/alert_service.py` (created by WS-17)

**Conflict note with WS-17:**
WS-17 creates `backend/app/services/__init__.py`. If WS-17 has already run, that file exists and this workstream can skip creating it. If WS-17 has not run yet, create `backend/app/services/__init__.py` as an empty file alongside `audit.py`.

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/services/audit.py` | **Create** | `new_rec_id()`, `log_event()` |
| `backend/app/services/__init__.py` | **Create if absent** | Empty package init |

---

## Section 3 — Read-only references

None required. This module has no dependencies on project code beyond Python stdlib.

---

## Section 4 — Implementation

### `backend/app/services/audit.py`

```python
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
```

---

## Section 5 — Task spec

### Acceptance criteria

1. `new_rec_id()` returns a string matching the pattern `REC-YYYYMMDD-[A-F0-9]{8}`.
2. Two consecutive calls to `new_rec_id()` return different strings.
3. `log_event("scan_started", new_rec_id(), {"universe": ["AAPL", "NVDA"]})` writes one JSONL line to `backend/audit.log`.
4. The written line is valid JSON containing keys `ts`, `event`, `rec_id`, and `universe`.
5. `log_event(...)` called on a read-only filesystem (simulate with a bad path) does not raise — it silently fails.
6. `python -c "from app.services.audit import new_rec_id, log_event; print('OK')"` prints `OK`.

### Verify after implementation

```bash
cd backend
python -c "
from app.services.audit import new_rec_id, log_event
import re, json, os

rid = new_rec_id()
assert re.match(r'REC-\d{8}-[A-F0-9]{8}', rid), f'bad format: {rid}'

rid2 = new_rec_id()
assert rid != rid2, 'IDs must be unique'

log_event('scan_started', rid, {'universe': ['AAPL', 'NVDA'], 'direction': 'Bullish'})

# Verify the log file was written
log_path = os.path.normpath(os.path.join('app', 'services', '..', '..', 'audit.log'))
with open(log_path) as f:
    lines = f.readlines()
last = json.loads(lines[-1])
assert last['event'] == 'scan_started'
assert last['rec_id'] == rid
assert 'ts' in last

print('OK — rec_id:', rid)
print('log line:', last)
"
```

---

## Section 6 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify any existing file — only create `audit.py` (and `__init__.py` if absent).
3. `log_event` must NEVER raise — all I/O errors must be swallowed silently.
4. `new_rec_id()` must be importable without any side effects (no file creation on import).
5. The `audit.log` path must resolve correctly whether uvicorn is started from `backend/` or the project root. Use `os.path.dirname(__file__)` to anchor the path.
6. Do NOT add any new pip packages — Python stdlib only (`json`, `os`, `datetime`, `uuid`).

---

## Section 7 — Dev workflow

```bash
cd backend
python -c "from app.services.audit import new_rec_id, log_event; print('OK')"
# Run verification block from Section 5
```

---

## Section 8 — Copy/paste prompt

```
Read `llm-contexts/18-audit-trail.md` fully before writing any code.
It is your single source of truth.

You are implementing the audit trail for the Bamendjou options screener
(FastAPI / Python 3.11, stdlib only — no new packages).

Your owned files:
  - backend/app/services/audit.py           (CREATE)
  - backend/app/services/__init__.py        (CREATE only if it does not exist)

Do not modify any file outside this list.
Do not modify backend/app/main.py.

Task: Implement new_rec_id() and log_event() exactly as specified in Section 4.
log_event() must NEVER raise — silently swallow all I/O errors.

Run the verification block in Section 5 after implementation.
Commit after all checks pass.
```
