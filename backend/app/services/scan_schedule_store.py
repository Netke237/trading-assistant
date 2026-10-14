"""Part 3 — YAML-backed store for ScanScheduleEntry list, plus the DB-backed
ScheduledScanRunModel helpers (write/lookup/prune) that carry each entry's
actual runtime state.

ScanScheduleStore follows the same safety property as tuning_schedule_store.py
et al: the whole dataset is held in memory as canonical state under a lock,
mutated there, then persisted — not reloaded from disk per call (which would
reintroduce a lost-update race between concurrent requests).
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import delete, select

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "scan_schedule.yaml"

# File format version. 2 (STOCKS-HORIZON-T1 H4): every stocks entry's
# resolved_request has had its strategy fields stripped and its params_horizon
# set (horizon_profiles.migrate_saved_stock_request). A file without the key is
# version 1.
_SCHEMA_VERSION = 2


class ScanScheduleStore:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}  # id -> entry dict, the in-memory canonical state
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        try:
            raw = yaml.safe_load(self._path.read_text()) or {}
            entries = raw.get("entries", [])
            migrate = int(raw.get("version", 1) or 1) < _SCHEMA_VERSION
            if migrate:
                entries = [self._migrate_entry(e) for e in entries]
            loaded: dict[str, dict] = {}
            for entry in entries:
                try:
                    eid = entry["id"]
                    loaded[eid] = entry
                except Exception:
                    continue  # malformed rows are dropped, not fatal
            with self._lock:
                self._entries = loaded
                if migrate:
                    self._backup()
                    self._save_locked()
        except Exception:
            pass

    @staticmethod
    def _migrate_entry(entry: object) -> object:
        """v1 -> v2: a stocks entry's saved request loses its strategy fields
        (old clients always sent them at frozen defaults, which would override
        the backend profile forever) and gains params_horizon from its hold."""
        from app.services.horizon_profiles import migrate_saved_stock_request
        if (isinstance(entry, dict) and entry.get("mode") == "stocks"
                and isinstance(entry.get("resolved_request"), dict)):
            return {**entry, "resolved_request": migrate_saved_stock_request(entry["resolved_request"])}
        return entry

    def _backup(self) -> None:
        """Copy the file aside before a migration rewrites it (as
        strategy_param_store.adopt() does)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(self._path, self._path.with_suffix(f".bak.{stamp}-{uuid.uuid4().hex[:8]}.yaml"))

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._entries.values())

    def get(self, entry_id: str) -> dict | None:
        with self._lock:
            return self._entries.get(entry_id)

    def upsert(self, entry: dict) -> None:
        """Create or full-replace by id, then persist."""
        with self._lock:
            previous = self._entries
            self._entries = {**previous, entry["id"]: entry}
            try:
                self._save_locked()
            except Exception:
                self._entries = previous
                raise

    def delete(self, entry_id: str) -> None:
        with self._lock:
            previous = self._entries
            self._entries = {k: v for k, v in previous.items() if k != entry_id}
            try:
                self._save_locked()
            except Exception:
                self._entries = previous
                raise

    def _save_locked(self) -> None:
        """Must be called with self._lock already held."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".yaml.tmp")
        data = {"version": _SCHEMA_VERSION, "entries": list(self._entries.values())}
        tmp.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        os.replace(tmp, self._path)


_store_path = Path(os.getenv("BAMENDJOU_SCAN_SCHEDULE_PATH", str(_DEFAULT_PATH)))
scan_schedule_store = ScanScheduleStore(path=_store_path)


# ── ScheduledScanRunModel helpers ────────────────────────────────────────────

async def record_scheduled_scan_run(
    db, *, schedule_entry_id: str, mode: str, status: str,
    error: str | None = None, result_json: str | None = None,
) -> None:
    """Write one ScheduledScanRunModel row for a completed (success or error)
    scheduled-entry fire. This is the only place a schedule entry's runtime
    state is persisted — ScanScheduleEntry itself carries none."""
    from uuid import uuid4
    from app.models.scheduled_scan_run import ScheduledScanRunModel

    db.add(ScheduledScanRunModel(
        id=str(uuid4()),
        schedule_entry_id=schedule_entry_id,
        mode=mode,
        fired_at=datetime.now(timezone.utc),
        status=status,
        error=error,
        result_json=result_json,
    ))
    await db.commit()


async def get_latest_successful_run(db, schedule_entry_id: str):
    """Most recent status='success' ScheduledScanRunModel row for this entry,
    or None — the delta-computation baseline for that entry's next run."""
    from app.models.scheduled_scan_run import ScheduledScanRunModel

    result = await db.execute(
        select(ScheduledScanRunModel)
        .where(
            ScheduledScanRunModel.schedule_entry_id == schedule_entry_id,
            ScheduledScanRunModel.status == "success",
        )
        .order_by(ScheduledScanRunModel.fired_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_scheduled_scan_runs(db, schedule_entry_id: str, limit: int = 20):
    """Most-recent-first list of runs for one entry — backs GET
    /api/scan-schedule/{entry_id}/runs (delta baseline lookup + Settings UI
    last-run display share this one store)."""
    from app.models.scheduled_scan_run import ScheduledScanRunModel

    result = await db.execute(
        select(ScheduledScanRunModel)
        .where(ScheduledScanRunModel.schedule_entry_id == schedule_entry_id)
        .order_by(ScheduledScanRunModel.fired_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_scheduled_scan_runs(db, schedule_entry_id: str) -> None:
    """Delete every ScheduledScanRunModel row for a deleted schedule entry.

    scan_schedule_store is a YAML file, not a DB table, so there is no FK/
    cascade to rely on — this must be called explicitly by the DELETE
    endpoint. Without it, prune_scheduled_scan_runs's "keep the latest
    success row per schedule_entry_id" exclusion has no way to know the
    entry no longer exists, so a deleted entry's rows — including the one
    row the exclusion clause protects from age-based deletion — would
    escape pruning forever.
    """
    from app.models.scheduled_scan_run import ScheduledScanRunModel

    await db.execute(delete(ScheduledScanRunModel).where(
        ScheduledScanRunModel.schedule_entry_id == schedule_entry_id
    ))
    await db.commit()


async def prune_scheduled_scan_runs(db, retention_days: int) -> None:
    """Delete rows older than the retention cutoff, EXCEPT each
    schedule_entry_id's single most recent status='success' row, which
    survives regardless of age (it's the delta baseline for that entry's
    next run — an entry that fires monthly shouldn't lose its only baseline
    to a 90-day sweep). retention_days <= 0 disables pruning, matching every
    other prune_* function's convention in this codebase."""
    if retention_days <= 0:
        return
    from app.models.scheduled_scan_run import ScheduledScanRunModel
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # Build the "protected id" set (one latest-success row per
    # schedule_entry_id) explicitly rather than a correlated-subquery DELETE
    # — simplest portable approach (SQLite/Postgres) for a table this small,
    # bounded by number of distinct schedule entries.
    protect_result = await db.execute(
        select(
            ScheduledScanRunModel.schedule_entry_id,
            func.max(ScheduledScanRunModel.fired_at).label("max_fired_at"),
        )
        .where(ScheduledScanRunModel.status == "success")
        .group_by(ScheduledScanRunModel.schedule_entry_id)
    )
    protected_pairs = protect_result.all()
    protected_ids: set[str] = set()
    if protected_pairs:
        for entry_id, max_fired_at in protected_pairs:
            row_result = await db.execute(
                select(ScheduledScanRunModel.id)
                .where(
                    ScheduledScanRunModel.schedule_entry_id == entry_id,
                    ScheduledScanRunModel.status == "success",
                    ScheduledScanRunModel.fired_at == max_fired_at,
                )
                .limit(1)
            )
            row_id = row_result.scalar_one_or_none()
            if row_id:
                protected_ids.add(row_id)

    stmt = delete(ScheduledScanRunModel).where(ScheduledScanRunModel.fired_at < cutoff)
    if protected_ids:
        stmt = stmt.where(ScheduledScanRunModel.id.notin_(protected_ids))
    await db.execute(stmt)
    await db.commit()
