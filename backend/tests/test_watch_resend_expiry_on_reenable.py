"""Expire only a stale queue prefix when a disabled watch is re-enabled."""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.routers.composite_watch as composite_router
import app.routers.strategy_watch as strategy_router
import app.services.strategy_watch_evaluator as ev
import app.services.strategy_watch_store as store_module
from app.services.strategy_watch_store import StrategyWatchStore

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
OLD = (NOW - timedelta(days=6)).isoformat()
FRESH = (NOW - timedelta(days=4)).isoformat()


def entry(wid, fired_at=OLD, price=101.0):
    event = ev.WatchEvent(wid, "AAPL", "pullback_ema", "entry", "Bullish",
                          price, price - 5, price + 10, 2.0, price, "setup")
    return {"event": asdict(event), "fired_at": fired_at,
            "new_state": {"phase": "armed", "entry_price": price},
            "failures": 3, "last_failure_at": FRESH}


@pytest.fixture
def watch(tmp_path, monkeypatch):
    store = StrategyWatchStore(tmp_path / "watches.yaml")
    wid = store.add_watch("AAPL", "pullback_ema")["id"]
    store.set_enabled(wid, False)
    monkeypatch.setattr(ev, "_utcnow", lambda: NOW)
    return store, wid


def seed(store, wid, queue):
    store.update_state(wid, {"phase": "idle", "entry_price": 99.0,
                             "pending_events": copy.deepcopy(queue)})


def state(store):
    return store.list_watches()[0]["last_state"]


@pytest.mark.asyncio
async def test_expired_prefix_advances_state_and_preserves_tail_on_disk(watch, monkeypatch, caplog):
    store, wid = watch
    queue = [entry(wid, OLD, 101), entry(wid, OLD, 102), entry(wid, FRESH, 103)]
    seed(store, wid, queue)
    save = Mock(wraps=store.save)
    monkeypatch.setattr(store, "save", save)
    with caplog.at_level(logging.WARNING):
        assert await ev.set_enabled_and_expire(wid, True, store=store) == 2
    assert state(store) == {"phase": "armed", "entry_price": 102,
                            "pending_events": [queue[-1]]}
    assert store.list_watches()[0]["enabled"] is True
    reloaded = StrategyWatchStore(store._path).list_watches()[0]
    assert reloaded["last_state"] == state(store)
    assert reloaded["id"] == wid and reloaded["enabled"] is True
    assert len([r for r in caplog.records if "expired queued alert" in r.message]) == 2
    save.assert_called_once()
    assert queue[-1]["failures"] == 3


@pytest.mark.asyncio
async def test_all_expired_commits_last_state_and_removes_queue(watch):
    store, wid = watch
    seed(store, wid, [entry(wid, OLD, 101), entry(wid, OLD, 104)])
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 2
    assert state(store) == {"phase": "armed", "entry_price": 104}
    assert "pending_events" not in state(StrategyWatchStore(store._path))


@pytest.mark.asyncio
@pytest.mark.parametrize("stamp", [
    (NOW - timedelta(days=5)).isoformat(),
    (NOW - timedelta(days=5)).replace(tzinfo=None).isoformat(),
    (NOW - timedelta(days=5)).astimezone(timezone(timedelta(hours=2))).isoformat(),
    FRESH, (NOW + timedelta(days=1)).isoformat(),
])
async def test_boundary_fresh_and_future_stop_prefix_even_before_an_old_tail(watch, stamp):
    store, wid = watch
    queue = [entry(wid, stamp), entry(wid, OLD, 102)]
    seed(store, wid, queue)
    before = copy.deepcopy(state(store))
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 0
    assert state(store) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("stamp", [
    None, "", "not-a-date", 123, True,
    (NOW - timedelta(days=5, microseconds=1)).isoformat(),
    (NOW - timedelta(days=6)).replace(tzinfo=None).isoformat(),
    (NOW - timedelta(days=6)).astimezone(timezone(timedelta(hours=-4))).isoformat(),
])
async def test_old_or_invalid_time_expires_a_valid_event(watch, stamp):
    store, wid = watch
    seed(store, wid, [entry(wid, stamp, 107)])
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 1
    assert state(store) == {"phase": "armed", "entry_price": 107}


@pytest.mark.asyncio
async def test_missing_timestamp_expires(watch):
    store, wid = watch
    queued = entry(wid)
    del queued["fired_at"]
    seed(store, wid, [queued])
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 1
    assert state(store)["entry_price"] == 101


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [None, "broken", {"fired_at": FRESH},
    {"fired_at": FRESH, "event": {}, "new_state": {"entry_price": 999}}])
async def test_malformed_event_never_advances_to_untrusted_state(watch, malformed):
    store, wid = watch
    seed(store, wid, [entry(wid, OLD, 106), malformed, entry(wid, FRESH, 108)])
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 2
    assert state(store)["entry_price"] == 106
    assert state(store)["pending_events"] == [entry(wid, FRESH, 108)]


@pytest.mark.asyncio
async def test_only_malformed_queue_keeps_committed_state(watch):
    store, wid = watch
    seed(store, wid, [None])
    original = {k: v for k, v in state(store).items() if k != "pending_events"}
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 1
    assert state(store) == original


@pytest.mark.asyncio
async def test_disable_and_already_enabled_requests_leave_queue_untouched(watch):
    store, wid = watch
    seed(store, wid, [entry(wid)])
    before = copy.deepcopy(state(store))
    assert await ev.set_enabled_and_expire(wid, False, store=store) == 0
    assert state(store) == before
    store.set_enabled(wid, True)
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 0
    assert state(store) == before


@pytest.mark.asyncio
async def test_empty_queue_and_missing_id(watch):
    store, wid = watch
    before = copy.deepcopy(state(store))
    assert await ev.set_enabled_and_expire(wid, True, store=store) == 0
    assert state(store) == before
    assert await ev.set_enabled_and_expire("missing", True, store=store) is None


@pytest.mark.asyncio
async def test_failed_atomic_replace_preserves_disk_memory_and_no_expiry_log(watch, monkeypatch, caplog):
    store, wid = watch
    seed(store, wid, [entry(wid)])
    before = copy.deepcopy(store.list_watches())
    on_disk = store._path.read_bytes()
    monkeypatch.setattr(store_module.os, "replace", Mock(side_effect=OSError("disk full")))
    with caplog.at_level(logging.WARNING), pytest.raises(OSError, match="disk full"):
        await ev.set_enabled_and_expire(wid, True, store=store)
    assert store.list_watches() == before
    assert store._path.read_bytes() == on_disk
    assert not any("expired queued alert" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [strategy_router, composite_router])
async def test_both_patch_routes_use_their_actual_store_and_report_expiry(watch, monkeypatch, route):
    store, wid = watch
    if route is composite_router:
        store.remove_watch(wid)
        wid = store.add_composite_watch("AAPL", {"primary": {"model": "OMM"}})["id"]
        store.set_enabled(wid, False)
    seed(store, wid, [entry(wid)])
    monkeypatch.setattr(route, "strategy_watch_store", store)
    monkeypatch.setattr(ev, "strategy_watch_store", StrategyWatchStore(path=None))
    app = FastAPI()
    app.include_router(route.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"{route.router.prefix}/{wid}", json={"enabled": True})
        assert response.status_code == 200
        assert response.json() == {"id": wid, "enabled": True, "expired_alerts": 1}
        response = await client.patch(f"{route.router.prefix}/{wid}", json={"enabled": True})
        assert response.json()["expired_alerts"] == 0
        response = await client.patch(f"{route.router.prefix}/missing", json={"enabled": True})
        assert response.status_code == 404
    assert "pending_events" not in state(store)
    assert state(StrategyWatchStore(store._path))["entry_price"] == 101


@pytest.mark.asyncio
@pytest.mark.parametrize("runner", [ev.evaluate_and_notify, ev.evaluate_all])
async def test_enable_waits_for_the_whole_evaluation_run(watch, monkeypatch, runner):
    store, wid = watch
    seed(store, wid, [entry(wid)])
    collected, release = asyncio.Event(), asyncio.Event()

    async def collect(*args):
        collected.set()
        await release.wait()
        return []

    monkeypatch.setattr(ev, "_collect", collect)
    monkeypatch.setattr(ev, "_resend_pending", AsyncMock(return_value={}))
    monkeypatch.setattr(ev, "_channel_status", lambda: (False, True))
    running = asyncio.create_task(runner())
    await asyncio.wait_for(collected.wait(), timeout=2)
    enabling = asyncio.create_task(ev.set_enabled_and_expire(wid, True, store=store))
    try:
        await asyncio.sleep(0)
        assert not enabling.done()
        assert store.list_watches()[0]["enabled"] is False
    finally:
        release.set()
        await asyncio.wait_for(running, timeout=2)
    assert await asyncio.wait_for(enabling, timeout=2) == 1
    assert store.list_watches()[0]["enabled"] is True


@pytest.mark.asyncio
async def test_concurrent_enables_expire_once(watch):
    store, wid = watch
    seed(store, wid, [entry(wid)])
    result = await asyncio.gather(ev.set_enabled_and_expire(wid, True, store=store),
                                  ev.set_enabled_and_expire(wid, True, store=store))
    assert sorted(result) == [0, 1]
    assert state(store)["entry_price"] == 101


def test_save_holds_lock_through_replace_so_later_mutation_cannot_be_overwritten(watch, monkeypatch):
    store, wid = watch
    saving_snapshot, second_started, second_finished, release = (
        threading.Event() for _ in range(4)
    )
    original_replace = store_module.os.replace
    errors = []

    def replace(source, target):
        if threading.current_thread() is saving:
            saving_snapshot.set()
            assert release.wait(2), "save probe was not released"
        original_replace(source, target)

    def save():
        try:
            store.save()
        except Exception as error:
            errors.append(error)

    def update():
        second_started.set()
        try:
            store.update_state(wid, {"phase": "armed", "entry_price": 123})
        except Exception as error:
            errors.append(error)
        finally:
            second_finished.set()

    monkeypatch.setattr(store_module.os, "replace", replace)
    saving = threading.Thread(target=save)
    updating = threading.Thread(target=update)
    saving.start()
    try:
        assert saving_snapshot.wait(2)
        updating.start()
        assert second_started.wait(2)
        assert not second_finished.wait(0.05)
    finally:
        release.set()
        saving.join(2)
        if updating.ident is not None:
            updating.join(2)
    assert not saving.is_alive() and not updating.is_alive()
    assert not errors
    assert state(StrategyWatchStore(store._path))["entry_price"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("route", [strategy_router, composite_router])
async def test_patch_failure_is_error_and_watch_stays_disabled(watch, monkeypatch, route):
    store, wid = watch
    seed(store, wid, [entry(wid)])
    before = copy.deepcopy(store.list_watches())
    disk = store._path.read_bytes()
    monkeypatch.setattr(route, "strategy_watch_store", store)
    monkeypatch.setattr(store, "save", Mock(side_effect=OSError("disk full")))
    app = FastAPI()
    app.include_router(route.router)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        response = await client.patch(f"{route.router.prefix}/{wid}", json={"enabled": True})
    assert response.status_code == 500
    assert store.list_watches() == before
    assert store._path.read_bytes() == disk
