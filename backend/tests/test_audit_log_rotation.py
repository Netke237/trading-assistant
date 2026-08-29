"""Tests for audit.log rotation/pruning (Part 2 of the scheduler-timezone plan).

Mirrors test_sent_log.py's structure — monkeypatch the module-level path
constant, exercise the pure functions directly.
"""
import json
import os
from datetime import datetime, timedelta, timezone


def test_rotate_creates_archive_and_empties_live_file(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    log.write_text(json.dumps({"ts": "x", "event": "scan_started"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))

    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    audit.rotate_audit_log(now)

    archive = tmp_path / "audit-2026-08.log"
    assert archive.exists()
    assert "scan_started" in archive.read_text(encoding="utf-8")
    # No prior archive for this month existed, so rotation is a plain rename
    # (os.replace) — the live file no longer exists at all afterward, rather
    # than existing-but-empty. A fresh audit.log is created lazily by the
    # next log_event() call.
    assert not log.exists()


def test_rotate_is_idempotent_within_same_month(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    log.write_text(json.dumps({"ts": "x", "event": "a"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))

    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    audit.rotate_audit_log(now)
    # audit.log is now empty; a second call the same month must not re-rotate
    # (the archive already exists and the empty live file is under the size cap).
    audit.rotate_audit_log(now)

    archive = tmp_path / "audit-2026-08.log"
    lines = archive.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_size_cap_rotation_mid_month_appends_not_overwrites(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    archive = tmp_path / "audit-2026-08.log"
    archive.write_text(json.dumps({"ts": "x", "event": "first"}) + "\n", encoding="utf-8")
    log.write_text(json.dumps({"ts": "y", "event": "second"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))
    monkeypatch.setattr(audit, "_ROTATE_SIZE_BYTES", 1)  # force the size-cap branch

    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    audit.rotate_audit_log(now)

    lines = archive.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "first"
    assert json.loads(lines[1])["event"] == "second"
    assert log.read_text(encoding="utf-8") == ""


def test_rotate_noop_when_no_live_file(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"  # doesn't exist
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))
    audit.rotate_audit_log()  # must not raise
    assert not log.exists()


def test_prune_archives_deletes_old_keeps_recent(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))

    old = tmp_path / "audit-2015-01.log"
    recent = tmp_path / "audit-2026-08.log"
    old.write_text("old\n", encoding="utf-8")
    recent.write_text("recent\n", encoding="utf-8")

    audit.prune_audit_log_archives(10)

    assert not old.exists()
    assert recent.exists()


def test_prune_disabled_when_retention_non_positive(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))

    old = tmp_path / "audit-2015-01.log"
    old.write_text("old\n", encoding="utf-8")

    audit.prune_audit_log_archives(0)
    assert old.exists()
    audit.prune_audit_log_archives(-5)
    assert old.exists()


def test_log_event_still_appends_after_lock_added(monkeypatch, tmp_path):
    import app.services.audit as audit

    log = tmp_path / "audit.log"
    monkeypatch.setattr(audit, "_LOG_PATH", str(log))
    audit.log_event("scan_started", "REC-1", {"x": 1})
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "scan_started"
    assert entry["rec_id"] == "REC-1"
