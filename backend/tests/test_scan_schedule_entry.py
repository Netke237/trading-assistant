"""Tests for ScanScheduleEntry validation (Part 3, §3.1) and ScanScheduleStore
(§3.2) — in-memory-canonical-state-under-lock, not reload-per-call."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.scan_schedule import ScanScheduleEntry


def _base_options_request() -> dict:
    return {
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
    }


def _base_stock_request(strategy: str = "pullback_ema") -> dict:
    return {
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "strategy": strategy,
    }


def _entry(**overrides) -> dict:
    base = dict(
        id="e1", label="Test entry", mode="options",
        profile_id="p1", profile_name="My profile", profile_synced_at="2026-01-01T00:00:00Z",
        resolved_request=_base_options_request(),
        pattern="fixed_time", enabled=True, days_of_week=[0, 1, 2, 3, 4],
        fire_time="09:00",
    )
    base.update(overrides)
    return base


# ── Pattern-specific field validation ────────────────────────────────────────

def test_fixed_time_requires_fire_time():
    with pytest.raises(ValidationError, match="fire_time is required"):
        ScanScheduleEntry(**_entry(fire_time=None))


def test_loop_requires_cadence_and_window():
    with pytest.raises(ValidationError, match="cadence_minutes/window_start_hour/window_end_hour required"):
        ScanScheduleEntry(**_entry(pattern="loop", fire_time=None))


def test_loop_window_order_rejected():
    with pytest.raises(ValidationError, match="window_start_hour must be less than window_end_hour"):
        ScanScheduleEntry(**_entry(
            pattern="loop", fire_time=None,
            cadence_minutes=15, window_start_hour=17, window_end_hour=9,
        ))


def test_loop_valid_entry_ok():
    entry = ScanScheduleEntry(**_entry(
        pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=9, window_end_hour=17,
    ))
    assert entry.pattern == "loop"


def test_fixed_time_valid_entry_ok():
    entry = ScanScheduleEntry(**_entry())
    assert entry.pattern == "fixed_time"
    assert entry.fire_time == "09:00"


# ── resolved_request shape validation ────────────────────────────────────────

def test_resolved_request_must_match_options_schema():
    with pytest.raises(ValidationError, match="does not match a valid request for mode=options"):
        ScanScheduleEntry(**_entry(resolved_request={"garbage": True}))


def test_resolved_request_must_match_stocks_schema_missing_strategy():
    """StockScanRequest.strategy is required — a stocks-mode entry pushed
    without it must be rejected at save time, not discovered at fire time."""
    bad = _base_stock_request()
    del bad["strategy"]
    with pytest.raises(ValidationError, match="does not match a valid request for mode=stocks"):
        ScanScheduleEntry(**_entry(mode="stocks", resolved_request=bad))


def test_resolved_request_stocks_valid_ok():
    entry = ScanScheduleEntry(**_entry(mode="stocks", resolved_request=_base_stock_request()))
    assert entry.mode == "stocks"


# ── ScanScheduleStore ─────────────────────────────────────────────────────────

def test_store_upsert_get_list_delete(tmp_path):
    from app.services.scan_schedule_store import ScanScheduleStore

    store = ScanScheduleStore(path=tmp_path / "scan_schedule.yaml")
    entry = _entry()
    store.upsert(entry)
    assert store.get("e1") == entry
    assert store.list() == [entry]

    store.delete("e1")
    assert store.get("e1") is None
    assert store.list() == []


def test_store_persists_across_instances(tmp_path):
    from app.services.scan_schedule_store import ScanScheduleStore

    path = tmp_path / "scan_schedule.yaml"
    store1 = ScanScheduleStore(path=path)
    store1.upsert(_entry())

    store2 = ScanScheduleStore(path=path)
    assert store2.get("e1") is not None
    assert store2.get("e1")["label"] == "Test entry"


def test_store_upsert_concurrent_writes_dont_lose_either(tmp_path):
    """in-memory-canonical-state-under-lock, not reload-per-call — two
    different entries upserted in sequence must both be retained."""
    from app.services.scan_schedule_store import ScanScheduleStore

    store = ScanScheduleStore(path=tmp_path / "scan_schedule.yaml")
    store.upsert(_entry(id="e1"))
    store.upsert(_entry(id="e2", label="Second"))
    ids = {e["id"] for e in store.list()}
    assert ids == {"e1", "e2"}


def test_store_load_drops_malformed_rows_not_fatal(tmp_path):
    from app.services.scan_schedule_store import ScanScheduleStore
    import yaml

    path = tmp_path / "scan_schedule.yaml"
    path.write_text(yaml.dump({"entries": [{"no_id_field": True}, _entry()]}))
    store = ScanScheduleStore(path=path)
    assert store.list() == [_entry()]
