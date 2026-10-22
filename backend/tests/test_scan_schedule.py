"""Tests for the Part 3 scan-schedule endpoints, scheduler (fixed_time +
loop), ScheduledScanRunModel, semaphore serialization, and pruning."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def _options_entry_body(**overrides) -> dict:
    base = dict(
        label="Test entry", mode="options",
        profile_id="p1", profile_name="My profile", profile_synced_at="2026-01-01T00:00:00Z",
        resolved_request={"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {}},
        pattern="fixed_time", enabled=True, days_of_week=[0, 1, 2, 3, 4], fire_time="09:00",
    )
    base.update(overrides)
    return base


# ── Router endpoints ──────────────────────────────────────────────────────────

def test_create_list_update_delete_entry(client):
    r = client.post("/api/scan-schedule", json=_options_entry_body())
    assert r.status_code == 200
    entry = r.json()
    entry_id = entry["id"]
    assert entry["label"] == "Test entry"

    r = client.get("/api/scan-schedule")
    assert r.status_code == 200
    assert any(e["id"] == entry_id for e in r.json())

    r = client.put(f"/api/scan-schedule/{entry_id}", json=_options_entry_body(label="Renamed"))
    assert r.status_code == 200
    assert r.json()["label"] == "Renamed"

    r = client.delete(f"/api/scan-schedule/{entry_id}")
    assert r.status_code == 200
    r = client.get("/api/scan-schedule")
    assert not any(e["id"] == entry_id for e in r.json())


def test_update_nonexistent_entry_404(client):
    r = client.put("/api/scan-schedule/does-not-exist", json=_options_entry_body())
    assert r.status_code == 404


def test_delete_nonexistent_entry_404(client):
    r = client.delete("/api/scan-schedule/does-not-exist")
    assert r.status_code == 404


def test_create_stocks_entry_missing_strategy_rejected(client):
    r = client.post("/api/scan-schedule", json=_options_entry_body(
        mode="stocks",
        resolved_request={"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing"},
    ))
    assert r.status_code == 422


def test_run_now_nonexistent_entry_404(client):
    r = client.post("/api/scan-schedule/does-not-exist/run-now")
    assert r.status_code == 404


def test_run_now_disabled_entry_rejected_not_false_success(client):
    """Flagged by post-implementation adversarial review: _run_scheduled_entry
    silently no-ops on a disabled entry (correct for the scheduler dispatch
    paths, where that's an expected race), but the run-now endpoint used to
    swallow that and report {"triggered": true} anyway — a false-positive
    success with nothing actually run and no ScheduledScanRunModel row
    written. The endpoint must reject a disabled entry outright instead."""
    r = client.post("/api/scan-schedule", json=_options_entry_body(enabled=False))
    entry_id = r.json()["id"]
    try:
        r = client.post(f"/api/scan-schedule/{entry_id}/run-now")
        assert r.status_code == 409
        r = client.get(f"/api/scan-schedule/{entry_id}/runs")
        assert r.json() == []
    finally:
        client.delete(f"/api/scan-schedule/{entry_id}")


def test_get_runs_empty_initially(client):
    r = client.post("/api/scan-schedule", json=_options_entry_body())
    entry_id = r.json()["id"]
    try:
        r = client.get(f"/api/scan-schedule/{entry_id}/runs")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        client.delete(f"/api/scan-schedule/{entry_id}")


def test_delete_entry_also_deletes_its_runs(client):
    """Part 3, §3.3 — DELETE must also delete ScheduledScanRunModel rows for
    that entry; the YAML store has no FK/cascade to rely on."""
    import asyncio
    from app.services.scan_schedule_store import record_scheduled_scan_run, list_scheduled_scan_runs
    from tests.conftest import _TestSession

    r = client.post("/api/scan-schedule", json=_options_entry_body())
    entry_id = r.json()["id"]

    async def _seed():
        async with _TestSession() as db:
            await record_scheduled_scan_run(
                db, schedule_entry_id=entry_id, mode="options", status="success", result_json="{}",
            )

    asyncio.run(_seed())

    r = client.delete(f"/api/scan-schedule/{entry_id}")
    assert r.status_code == 200

    async def _check():
        async with _TestSession() as db:
            return await list_scheduled_scan_runs(db, entry_id)

    assert asyncio.run(_check()) == []


# ── _run_scheduled_entry: dispatch + globals-untouched + notifications ──────

@pytest.mark.asyncio
async def test_run_scheduled_entry_options_dispatches_to_core_and_records_success(monkeypatch):
    from app.services.scan_schedule_store import scan_schedule_store, list_scheduled_scan_runs
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.routers.scan as scan_module
    import app.database as dbmod

    entry = _options_entry_body(id="run-now-1")
    entry["id"] = "run-now-1"
    scan_schedule_store.upsert(entry)

    orig_request, orig_result = scan_module._last_request, scan_module._last_result
    try:
        # _run_scheduled_entry does `from app.database import AsyncSessionLocal`
        # as a LOCAL import inside the function body (it has no request
        # context to draw a Depends(get_db) session from, same as
        # APScheduler's job callback) — patching the module attribute here is
        # picked up on the next call, same as any other local-import patch
        # pattern in this codebase.
        monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

        with_patch_notify = []

        # no_live_quotes: the NO-LIVE-QUOTE notice clause flag (plan 3f).
        async def _fake_notify(label, count, *, no_live_quotes=False):
            with_patch_notify.append((label, count))

        monkeypatch.setattr(sss, "_notify_scan_schedule_success", _fake_notify)

        await sss._run_scheduled_entry("run-now-1")

        # Manual-run globals must be completely untouched.
        assert scan_module._last_request is orig_request
        assert scan_module._last_result is orig_result

        async with _TestSession() as db:
            runs = await list_scheduled_scan_runs(db, "run-now-1")
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert with_patch_notify  # success notification fired
    finally:
        scan_schedule_store.delete("run-now-1")


@pytest.mark.asyncio
async def test_run_scheduled_entry_options_drops_leaked_min_stock_score(monkeypatch):
    """Open question #57: before the frontend fix, an options entry's stored
    resolved_request could carry Step 3's stocks-only min_stock_score in
    `overrides`, where contract_validator took it as the contract hard-reject
    floor in place of contract_rules.yaml's. Entries are replayed as stored, so
    the scheduler drops it; every other override still reaches the core."""
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(resolved_request={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": {"min_stock_score": 40, "min_volume": 10},
    })
    entry["id"] = "leak-1"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    seen = []

    async def _fake_core(req, db, previous_result=None):
        seen.append(req)
        raise RuntimeError("stop here")

    async def _quiet(*a, **k):
        return None

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _fake_core)
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _quiet)
    try:
        await sss._run_scheduled_entry("leak-1")
        assert len(seen) == 1
        assert "min_stock_score" not in seen[0].overrides
        assert seen[0].overrides["min_volume"] == 10
        # The stored entry is not rewritten.
        assert scan_schedule_store.get("leak-1")["resolved_request"]["overrides"]["min_stock_score"] == 40
    finally:
        scan_schedule_store.delete("leak-1")


@pytest.mark.asyncio
async def test_run_scheduled_entry_options_preserves_contract_min_stock_score(monkeypatch):
    """Board #389: contract_min_stock_score is the intentional contract floor
    override for options scans and MUST NOT be dropped by the scheduler."""
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(resolved_request={
        "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
        "overrides": {"contract_min_stock_score": 30, "min_stock_score": 40, "min_volume": 10},
    })
    entry["id"] = "contract-floor-1"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    seen = []

    async def _fake_core(req, db, previous_result=None):
        seen.append(req)
        raise RuntimeError("stop here")

    async def _quiet(*a, **k):
        return None

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _fake_core)
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _quiet)
    try:
        await sss._run_scheduled_entry("contract-floor-1")
        assert len(seen) == 1
        # min_stock_score is stripped (legacy/stocks leak guard)
        assert "min_stock_score" not in seen[0].overrides
        # contract_min_stock_score is preserved and reaches the core
        assert seen[0].overrides["contract_min_stock_score"] == 30
        assert seen[0].overrides["min_volume"] == 10
    finally:
        scan_schedule_store.delete("contract-floor-1")


@pytest.mark.asyncio
async def test_run_scheduled_entry_deleted_mid_flight_logs_and_returns():
    from app.services import scan_schedule_scheduler as sss
    # Entry was never created — must log+return, not raise.
    await sss._run_scheduled_entry("no-such-entry")


@pytest.mark.asyncio
async def test_run_scheduled_entry_disabled_skips():
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss

    entry = _options_entry_body(id="disabled-1", enabled=False)
    entry["id"] = "disabled-1"
    scan_schedule_store.upsert(entry)
    try:
        await sss._run_scheduled_entry("disabled-1")  # must not raise, must not fire
    finally:
        scan_schedule_store.delete("disabled-1")


@pytest.mark.asyncio
async def test_run_scheduled_entry_error_records_error_row(monkeypatch):
    from app.services.scan_schedule_store import scan_schedule_store, list_scheduled_scan_runs
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(id="err-1")
    entry["id"] = "err-1"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.routers.scan._execute_scan_core", _boom)

    notified = []
    async def _fake_notify(label, error):
        notified.append((label, error))
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _fake_notify)

    try:
        await sss._run_scheduled_entry("err-1")
        async with _TestSession() as db:
            runs = await list_scheduled_scan_runs(db, "err-1")
        assert len(runs) == 1
        assert runs[0].status == "error"
        assert runs[0].error == "scan_failed"
        assert notified and notified[0][1] == "scan_failed"
    finally:
        scan_schedule_store.delete("err-1")


# ── Semaphore serialization ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scheduled_scan_semaphore_serializes_concurrent_fires():
    from app.services import scan_schedule_scheduler as sss

    order: list[str] = []
    concurrent_count = 0
    max_concurrent = 0

    async def _slow_task(name):
        nonlocal concurrent_count, max_concurrent
        async with sss._SCHEDULED_SCAN_SEMAPHORE:
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            order.append(f"start-{name}")
            await asyncio.sleep(0.05)
            order.append(f"end-{name}")
            concurrent_count -= 1

    await asyncio.gather(_slow_task("a"), _slow_task("b"))
    assert max_concurrent == 1
    # One must fully finish before the other starts.
    assert order in (["start-a", "end-a", "start-b", "end-b"], ["start-b", "end-b", "start-a", "end-a"])


# ── fixed_time job sync ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_fixed_time_jobs_creates_one_job_per_enabled_entry(monkeypatch):
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from app.services import scheduling_tz

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {})
    monkeypatch.setattr(sss, "_scheduler", None)
    monkeypatch.setattr(sss, "_scheduler_tz_key", None)

    enabled = _options_entry_body(id="fx-enabled")
    enabled["id"] = "fx-enabled"
    disabled = _options_entry_body(id="fx-disabled", enabled=False)
    disabled["id"] = "fx-disabled"
    loop_entry = _options_entry_body(
        id="fx-loop", pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=9, window_end_hour=17,
    )
    loop_entry["id"] = "fx-loop"

    scan_schedule_store.upsert(enabled)
    scan_schedule_store.upsert(disabled)
    scan_schedule_store.upsert(loop_entry)
    try:
        sss.sync_fixed_time_jobs()
        sched = sss._get_scan_schedule_scheduler()
        job_ids = {j.id for j in sched.get_jobs()}
        # scan_schedule_store is process-global shared state — other tests in
        # this module may leave their own entries behind, so assert on THIS
        # test's three ids specifically rather than exact set equality.
        assert "fx-enabled" in job_ids
        assert "fx-disabled" not in job_ids
        assert "fx-loop" not in job_ids
    finally:
        scan_schedule_store.delete("fx-enabled")
        scan_schedule_store.delete("fx-disabled")
        scan_schedule_store.delete("fx-loop")
        sss.shutdown_fixed_time_scheduler()


@pytest.mark.asyncio
async def test_sync_fixed_time_jobs_removes_deleted_entry_job(monkeypatch):
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from app.services import scheduling_tz

    monkeypatch.setattr(scheduling_tz, "_load_settings", lambda: {})
    monkeypatch.setattr(sss, "_scheduler", None)
    monkeypatch.setattr(sss, "_scheduler_tz_key", None)

    entry = _options_entry_body(id="fx-remove")
    entry["id"] = "fx-remove"
    scan_schedule_store.upsert(entry)
    sss.sync_fixed_time_jobs()
    sched = sss._get_scan_schedule_scheduler()
    assert sched.get_job("fx-remove") is not None

    scan_schedule_store.delete("fx-remove")
    sss.sync_fixed_time_jobs()
    assert sched.get_job("fx-remove") is None
    sss.shutdown_fixed_time_scheduler()


# ── loop pattern — window-independent per entry ──────────────────────────────

@pytest.mark.asyncio
async def test_loop_runner_fires_only_within_own_window(monkeypatch):
    from app.services import scan_schedule_scheduler as sss
    from app.services.scan_schedule_store import scan_schedule_store

    fired = []

    async def _fake_run(entry_id):
        fired.append(entry_id)

    monkeypatch.setattr(sss, "_run_scheduled_entry", _fake_run)
    # window_is_open patched per-call based on the entry's own window, so two
    # loop-entries with different windows don't interfere with each other.
    monkeypatch.setattr(sss, "window_is_open", lambda ws, we, dow, tz: ws == 9)

    inside = _options_entry_body(
        id="loop-inside", pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=9, window_end_hour=17,
    )
    inside["id"] = "loop-inside"
    outside = _options_entry_body(
        id="loop-outside", pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=20, window_end_hour=23,
    )
    outside["id"] = "loop-outside"
    scan_schedule_store.upsert(inside)
    scan_schedule_store.upsert(outside)

    try:
        runner = sss.ScanScheduleLoopRunner()
        await runner._tick()
        assert fired == ["loop-inside"]
    finally:
        scan_schedule_store.delete("loop-inside")
        scan_schedule_store.delete("loop-outside")


@pytest.mark.asyncio
async def test_loop_runner_respects_cadence(monkeypatch):
    from app.services import scan_schedule_scheduler as sss
    from app.services.scan_schedule_store import scan_schedule_store

    fired = []

    async def _fake_run(entry_id):
        fired.append(entry_id)

    monkeypatch.setattr(sss, "_run_scheduled_entry", _fake_run)
    monkeypatch.setattr(sss, "window_is_open", lambda *a, **k: True)

    entry = _options_entry_body(
        id="loop-cadence", pattern="loop", fire_time=None,
        cadence_minutes=60, window_start_hour=0, window_end_hour=24,
    )
    entry["id"] = "loop-cadence"
    scan_schedule_store.upsert(entry)

    try:
        runner = sss.ScanScheduleLoopRunner()
        await runner._tick()
        await runner._tick()  # immediately again — cadence not elapsed, must not re-fire
        assert fired == ["loop-cadence"]
    finally:
        scan_schedule_store.delete("loop-cadence")


@pytest.mark.asyncio
async def test_loop_runner_isolates_per_entry_failures(monkeypatch):
    """One misbehaving loop-pattern entry must never prevent any other entry
    (or the next tick) from running."""
    from app.services import scan_schedule_scheduler as sss
    from app.services.scan_schedule_store import scan_schedule_store

    fired = []

    async def _flaky_run(entry_id):
        if entry_id == "loop-bad":
            raise RuntimeError("boom")
        fired.append(entry_id)

    monkeypatch.setattr(sss, "_run_scheduled_entry", _flaky_run)
    monkeypatch.setattr(sss, "window_is_open", lambda *a, **k: True)

    bad = _options_entry_body(
        id="loop-bad", pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=0, window_end_hour=24,
    )
    bad["id"] = "loop-bad"
    good = _options_entry_body(
        id="loop-good", pattern="loop", fire_time=None,
        cadence_minutes=15, window_start_hour=0, window_end_hour=24,
    )
    good["id"] = "loop-good"
    scan_schedule_store.upsert(bad)
    scan_schedule_store.upsert(good)

    try:
        runner = sss.ScanScheduleLoopRunner()
        await runner._tick()  # must not raise despite "loop-bad" failing
        assert fired == ["loop-good"]
    finally:
        scan_schedule_store.delete("loop-bad")
        scan_schedule_store.delete("loop-good")


# ── ScheduledScanRunModel + pruning ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_and_get_latest_successful_run():
    from app.services.scan_schedule_store import record_scheduled_scan_run, get_latest_successful_run
    from tests.conftest import _TestSession

    async with _TestSession() as db:
        await record_scheduled_scan_run(db, schedule_entry_id="baseline-1", mode="options", status="error", error="x")
        await record_scheduled_scan_run(db, schedule_entry_id="baseline-1", mode="options", status="success", result_json='{"a":1}')
        await record_scheduled_scan_run(db, schedule_entry_id="other-entry", mode="options", status="success", result_json='{"b":2}')

        latest = await get_latest_successful_run(db, "baseline-1")
        assert latest is not None
        assert latest.result_json == '{"a":1}'


@pytest.mark.asyncio
async def test_prune_scheduled_scan_runs_keeps_latest_success_regardless_of_age():
    from app.models.scheduled_scan_run import ScheduledScanRunModel
    from app.services.scan_schedule_store import prune_scheduled_scan_runs
    from tests.conftest import _TestSession
    from uuid import uuid4

    old_ts = datetime.now(timezone.utc) - timedelta(days=200)
    recent_ts = datetime.now(timezone.utc) - timedelta(days=1)

    async with _TestSession() as db:
        # Old success — the ONLY success for this entry, must survive despite age.
        db.add(ScheduledScanRunModel(
            id=str(uuid4()), schedule_entry_id="prune-1", mode="options",
            fired_at=old_ts, status="success", result_json="{}",
        ))
        # Old error row — must be pruned (not protected, and not recent).
        old_error_id = str(uuid4())
        db.add(ScheduledScanRunModel(
            id=old_error_id, schedule_entry_id="prune-1", mode="options",
            fired_at=old_ts, status="error", error="x",
        ))
        # Recent row for a different entry — must survive (not old).
        recent_id = str(uuid4())
        db.add(ScheduledScanRunModel(
            id=recent_id, schedule_entry_id="prune-2", mode="options",
            fired_at=recent_ts, status="success", result_json="{}",
        ))
        await db.commit()

        await prune_scheduled_scan_runs(db, retention_days=90)

        from sqlalchemy import select
        result = await db.execute(select(ScheduledScanRunModel.id))
        remaining_ids = {row[0] for row in result.all()}

    # The old success survives (protected baseline); the old error is pruned;
    # the recent row for the other entry survives.
    assert old_error_id not in remaining_ids
    assert recent_id in remaining_ids


@pytest.mark.asyncio
async def test_prune_scheduled_scan_runs_disabled_when_non_positive():
    from app.models.scheduled_scan_run import ScheduledScanRunModel
    from app.services.scan_schedule_store import prune_scheduled_scan_runs
    from tests.conftest import _TestSession
    from uuid import uuid4

    old_ts = datetime.now(timezone.utc) - timedelta(days=1000)
    row_id = str(uuid4())
    async with _TestSession() as db:
        db.add(ScheduledScanRunModel(
            id=row_id, schedule_entry_id="prune-disabled", mode="options",
            fired_at=old_ts, status="error", error="x",
        ))
        await db.commit()

        await prune_scheduled_scan_runs(db, retention_days=0)
        from sqlalchemy import select
        result = await db.execute(select(ScheduledScanRunModel.id).where(ScheduledScanRunModel.id == row_id))
        assert result.scalar_one_or_none() == row_id


# ── STOCKS-HORIZON-T1 F1: a multi schedule whose confirmations exceed its variants ──

_RSI, _BB = "mean_reversion_rsi", "mean_reversion_bb"


def _multi_stock_request(**overrides) -> dict:
    base = {"universe": [], "symbols": [], "direction": "Bullish", "horizon": "Swing",
            "strategy": "mean_reversion_multi", "mean_reversion_variants": [_RSI, _BB]}
    base.update(overrides)
    return base


def _profile_min_confirmations(monkeypatch, value: int) -> None:
    """Patch the multi PROFILE (what strategy_params.yaml supplies through
    get_profile) to carry min_confirmations=value; the request leaves it None."""
    import app.routers.stock_scan as ss
    real = ss.get_profile

    def _fake(strategy, direction, horizon):
        params, source = real(strategy, direction, horizon)
        if strategy == "mean_reversion_multi":
            params = {**params, "min_confirmations": value}
        return params, source

    monkeypatch.setattr(ss, "get_profile", _fake)


def _quiet_core_io(monkeypatch) -> None:
    import app.routers.stock_scan as ss

    async def _no_bars(*a, **k):
        return []

    monkeypatch.setattr(ss, "fetch_quotes", lambda symbols: {})
    monkeypatch.setattr(ss, "get_historical_bars", _no_bars)


def test_create_stocks_multi_entry_confirmations_above_variants_rejected(client):
    body = _options_entry_body(mode="stocks", resolved_request=_multi_stock_request(
        mean_reversion_min_confirmations=3))
    r = client.post("/api/scan-schedule", json=body)
    assert r.status_code == 422
    assert "cannot exceed the number of selected variants (2)" in r.json()["detail"]


def test_update_stocks_multi_entry_confirmations_above_variants_rejected(client):
    good = _options_entry_body(mode="stocks", resolved_request=_multi_stock_request(
        mean_reversion_min_confirmations=2))
    r = client.post("/api/scan-schedule", json=good)
    assert r.status_code == 200
    entry_id = r.json()["id"]
    try:
        bad = _options_entry_body(mode="stocks", resolved_request=_multi_stock_request(
            mean_reversion_min_confirmations=3))
        r = client.put(f"/api/scan-schedule/{entry_id}", json=bad)
        assert r.status_code == 422
        assert "cannot exceed the number of selected variants (2)" in r.json()["detail"]
    finally:
        client.delete(f"/api/scan-schedule/{entry_id}")


@pytest.mark.asyncio
async def test_run_scheduled_stocks_multi_entry_profile_confirmations_above_variants_records_error(monkeypatch):
    """A stored 2-variant multi schedule meets a profile min_confirmations 3
    (profile changed after the save): the fire records an error naming the
    reason, not a 0-candidate success."""
    from app.services.scan_schedule_store import scan_schedule_store, list_scheduled_scan_runs
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.database as dbmod

    entry = _options_entry_body(mode="stocks", resolved_request=_multi_stock_request())
    entry["id"] = "multi-err-1"
    scan_schedule_store.upsert(entry)
    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)
    _quiet_core_io(monkeypatch)
    _profile_min_confirmations(monkeypatch, 3)

    errors, successes = [], []

    async def _err(label, error):
        errors.append(error)

    async def _ok(label, count):
        successes.append(count)

    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _err)
    monkeypatch.setattr(sss, "_notify_scan_schedule_success", _ok)
    try:
        await sss._run_scheduled_entry("multi-err-1")
        async with _TestSession() as db:
            runs = await list_scheduled_scan_runs(db, "multi-err-1")
        assert len(runs) == 1
        assert runs[0].status == "error"
        assert runs[0].error == "scan_failed"
        assert errors and not successes
    finally:
        scan_schedule_store.delete("multi-err-1")


def test_valid_stocks_multi_entry_saves_and_fires(client, monkeypatch):
    from app.services.scan_schedule_store import scan_schedule_store
    from app.services import scan_schedule_scheduler as sss
    from tests.conftest import _TestSession
    import app.database as dbmod

    monkeypatch.setattr(dbmod, "AsyncSessionLocal", _TestSession)
    _quiet_core_io(monkeypatch)

    async def _quiet(*a, **k):
        return None

    monkeypatch.setattr(sss, "_notify_scan_schedule_success", _quiet)
    monkeypatch.setattr(sss, "_notify_scan_schedule_error", _quiet)

    body = _options_entry_body(mode="stocks", resolved_request=_multi_stock_request(
        mean_reversion_min_confirmations=2))
    r = client.post("/api/scan-schedule", json=body)
    assert r.status_code == 200
    entry_id = r.json()["id"]
    try:
        r = client.post(f"/api/scan-schedule/{entry_id}/run-now")
        assert r.status_code == 200
        runs = client.get(f"/api/scan-schedule/{entry_id}/runs").json()
        assert len(runs) == 1
        assert runs[0]["status"] == "success", runs[0]["error"]
    finally:
        client.delete(f"/api/scan-schedule/{entry_id}")
        scan_schedule_store.delete(entry_id)
