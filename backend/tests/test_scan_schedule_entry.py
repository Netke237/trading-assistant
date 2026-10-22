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


# ── NO-LIVE-QUOTE (plan 3f, test T10): the off-hours options run ─────────────
#
# Off hours every chain row is session_closed, the scan rejects every contract
# for no_live_quote and each name's reason reads
# "contracts rejected: no_live_quote(N)". The scan core counts those names into
# ScanResult.noLiveQuoteNames; the scheduler reads that number (it parses no
# reason) and adds a clause to the success notice.

_NLQ_CLAUSE = "ran outside market hours — no live option quotes"


def _rejected(symbol: str, reason: str):
    from app.schemas import RejectedCandidate
    return RejectedCandidate(symbol=symbol, reason=reason)


@pytest.mark.asyncio
async def test_execute_scan_core_counts_no_live_quote_names():
    """Only a name whose EVERY contract was rejected for no_live_quote counts;
    a mixed contract rejection, another reason or an exception does not."""
    from contextlib import ExitStack
    from unittest.mock import patch, AsyncMock
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession

    outcomes = {
        "AAA": _rejected("AAA", "contracts rejected: no_live_quote(12)"),
        "BBB": _rejected("BBB", "contracts rejected: no_live_quote(3)"),
        "CCC": _rejected("CCC", "contracts rejected: no_live_quote(4), spread_too_wide(2)"),
        "DDD": _rejected("DDD", "contracts rejected: no_live_quote(5); best contract score 40 < caution 45"),
        "EEE": _rejected("EEE", "Pre-screen: score 20 rejected"),
        "FFF": RuntimeError("boom"),
    }

    async def _fake_process(symbol, *_a, **_kw):
        out = outcomes[symbol]
        if isinstance(out, Exception):
            raise out
        return out

    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._process_symbol", _fake_process))
        stack.enter_context(patch("app.routers.scan.get_tradier_creds",
                                  return_value=("tok", "https://example.invalid")))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
        stack.enter_context(patch("app.routers.scan.get_fundamentals", AsyncMock(return_value=None)))
        async with _TestSession() as db:
            req = scan_module.ScanRequest(universe=list(outcomes), direction="Bullish",
                                          horizon="Swing", overrides={})
            result = await scan_module._execute_scan_core(req, db, previous_result=None)

    assert len(result.rejected) == 6
    assert result.noLiveQuoteNames == 2
    # Still counted under failed_contracts: no new funnel row.
    assert result.pipeline.failed_contracts == 4
    # Persisted results from before the field read 0.
    from app.schemas import ScanResult
    assert ScanResult(scan_id="x", timestamp="t", candidates=[], rejected=[]).noLiveQuoteNames == 0


def test_ran_without_live_quotes_rule():
    from app.services.scan_schedule_scheduler import _ran_without_live_quotes
    assert _ran_without_live_quotes(0, 3, 3) is True
    assert _ran_without_live_quotes(0, 3, 2) is False   # one name failed for another reason
    assert _ran_without_live_quotes(1, 3, 3) is False   # a candidate: a live quote existed
    assert _ran_without_live_quotes(0, 0, 0) is False   # nothing rejected


async def _run_options_entry(monkeypatch, entry_id, result):
    """Run one options entry through _run_scheduled_entry with the core stubbed
    to return `result`; returns the (plain, html) notice bodies sent."""
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from app.services.notifications import dispatch
    from tests.conftest import _TestSession
    import app.database as dbmod

    scan_schedule_store.upsert(_entry(id=entry_id))
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    async def _fake_core(req, db, previous_result=None):
        return result

    sent = []

    async def _fake_send(subject, plain, html_body):
        sent.append((plain, html_body))

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _fake_core)
    monkeypatch.setattr(dispatch, "notify_enabled_channels", _fake_send)
    try:
        await sss._run_scheduled_entry(entry_id)
    finally:
        scan_schedule_store.delete(entry_id)
    assert len(sent) == 1
    return sent[0]


def _scan_result(rejected, no_live_quote_names, candidates=()):
    from app.schemas import ScanResult
    return ScanResult(scan_id="s1", timestamp="2026-10-09T22:00:00+00:00",
                      candidates=list(candidates), rejected=rejected,
                      noLiveQuoteNames=no_live_quote_names)


@pytest.mark.asyncio
async def test_all_no_live_quote_options_run_notice_carries_the_clause(monkeypatch):
    result = _scan_result([
        _rejected("AAA", "contracts rejected: no_live_quote(12)"),
        _rejected("BBB", "contracts rejected: no_live_quote(3)"),
    ], 2)
    plain, html_body = await _run_options_entry(monkeypatch, "nlq-all", result)
    assert plain == f"Scan entry 'Test entry': 0 candidate(s) found — {_NLQ_CLAUSE}"
    assert html_body.endswith(f"0 candidate(s) found — {_NLQ_CLAUSE}")


@pytest.mark.asyncio
async def test_mixed_options_run_notice_has_no_clause(monkeypatch):
    result = _scan_result([
        _rejected("AAA", "contracts rejected: no_live_quote(12)"),
        _rejected("BBB", "Pre-screen: score 20 rejected"),
    ], 1)
    plain, html_body = await _run_options_entry(monkeypatch, "nlq-mixed", result)
    assert plain == "Scan entry 'Test entry': 0 candidate(s) found"
    assert _NLQ_CLAUSE not in html_body
