"""WATCH-RESEND-EXPIRY-ON-REENABLE (piece 2 of 3; decisions WATCH-RESEND-SPLIT-2026-10-02,
WATCH-RESEND-REENABLE-MAX-AGE-2026-10-02).

When a disabled watch is re-enabled, its queued alerts older than 5 days are
dropped (a prefix, oldest first) instead of being sent as Delayed. Plan:
docs/superpowers/plans/2026-10-02-watch-resend-expiry-on-reenable-plan.md."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.services.strategy_watch_evaluator as ev_mod
from app.services.strategy_watch_evaluator import set_enabled_and_expire
from app.services.strategy_watch_store import StrategyWatchStore
from tests.test_watch_resend_skip_on_proof import IDLE, T0, _CfgEnv, _e, _Notify
from tests.test_watch_undelivered_resend import _ARMED, _Store, _sw

_EV = "app.services.strategy_watch_evaluator"
D = timedelta(days=1)


class _EStore(_Store):
    """_Store with set_enabled; records every state write."""

    def __init__(self, watches):
        super().__init__(watches)
        self.writes: list = []

    def update_state(self, watch_id, new_state):
        super().update_state(watch_id, new_state)
        self.writes.append(watch_id)

    def set_enabled(self, watch_id, enabled):
        for w in self.watches:
            if w["id"] == watch_id:
                w["enabled"] = bool(enabled)
                return True
        return False

    def enabled(self, wid="a"):
        return next(w for w in self.watches if w["id"] == wid)["enabled"]


def _old(reason, age, new_state=None, **extra) -> dict:
    return _e(reason, new_state, fired_at=(T0 - age).isoformat(), **extra)


async def _reenable(store, wid="a", enabled=True):
    with patch(f"{_EV}._utcnow", return_value=T0):
        return await set_enabled_and_expire(store, wid, enabled)


def _reasons(store, wid="a"):
    return [p["event"]["reason"] for p in store.pending(wid)]


# ── 1-2: the drop and what is committed ───────────────────────────────────────

@pytest.mark.asyncio
async def test_1_old_head_dropped_young_kept_untouched(caplog):
    s6 = {**IDLE, "marker": "6d"}
    young = _old("r4", 4 * D, failures=2, last_failure_at=(T0 - D).isoformat())
    store = _EStore([_sw("a", enabled=False, pending=[_old("r6", 6 * D, s6), young])])
    with caplog.at_level(logging.WARNING, logger=_EV):
        n = await _reenable(store)
    assert n == 1 and store.enabled()
    assert store.pending("a") == [young]                      # counters kept, byte-identical
    assert store.committed("a") == s6                         # the dropped entry's new_state
    recs = [r for r in caplog.records if r.levelno == logging.WARNING and "r6" in r.getMessage()]
    assert len(recs) == 1 and "a" in recs[0].getMessage()


@pytest.mark.asyncio
async def test_2_all_old_dropped_commits_the_newest_dropped_state():
    store = _EStore([_sw("a", enabled=False,
                         pending=[_old("r7", 7 * D, _ARMED), _old("r6", 6 * D, IDLE)])])
    n = await _reenable(store)
    assert n == 2
    assert store.state("a") == IDLE                           # no pending_events; = effective before


# ── 3-6: when it applies ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_3_boundary_exactly_five_days_kept_one_second_more_dropped():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r5", 5 * D)])])
    assert await _reenable(store) == 0 and _reasons(store) == ["r5"]
    store = _EStore([_sw("a", enabled=False, pending=[_old("r5+", 5 * D + timedelta(seconds=1))])])
    assert await _reenable(store) == 1 and store.pending("a") == []


@pytest.mark.asyncio
async def test_4_already_enabled_nothing_dropped_no_write():
    store = _EStore([_sw("a", enabled=True, pending=[_old("r9", 9 * D)])])
    assert await _reenable(store) == 0
    assert _reasons(store) == ["r9"] and store.writes == [] and store.enabled()


@pytest.mark.asyncio
@pytest.mark.parametrize("was_enabled", [True, False])
async def test_5_disable_drops_nothing(was_enabled):
    store = _EStore([_sw("a", enabled=was_enabled, pending=[_old("r9", 9 * D)])])
    assert await _reenable(store, enabled=False) == 0
    assert _reasons(store) == ["r9"] and store.writes == [] and not store.enabled()


@pytest.mark.asyncio
async def test_6_unknown_id_returns_none():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r9", 9 * D)])])
    assert await _reenable(store, wid="zz") is None
    assert store.writes == [] and not store.enabled()


# ── 7-10: reading fired_at ───────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("fired_at", [None, "garbage", 123])
async def test_7_unreadable_fired_at_is_expired(fired_at):
    head = _old("rX", 0 * D, {**IDLE, "marker": "x"})
    if fired_at is None:
        del head["fired_at"]
    else:
        head["fired_at"] = fired_at
    store = _EStore([_sw("a", enabled=False, pending=[head, _old("r4", 4 * D)])])
    assert await _reenable(store) == 1
    assert _reasons(store) == ["r4"] and store.committed("a") == {**IDLE, "marker": "x"}


@pytest.mark.asyncio
async def test_7b_non_dict_entry_expired_committed_state_kept():
    store = _EStore([_sw("a", enabled=False, pending=["junk", _old("r4", 4 * D)])])
    assert await _reenable(store) == 1
    assert _reasons(store) == ["r4"] and store.committed("a") == {"phase": "idle"}


@pytest.mark.asyncio
async def test_8_naive_fired_at_read_as_utc():
    naive6 = _old("n6", 6 * D)
    naive6["fired_at"] = (T0 - 6 * D).replace(tzinfo=None).isoformat()
    naive4 = _old("n4", 4 * D)
    naive4["fired_at"] = (T0 - 4 * D).replace(tzinfo=None).isoformat()
    store = _EStore([_sw("a", enabled=False, pending=[naive6, naive4])])
    assert await _reenable(store) == 1 and _reasons(store) == ["n4"]


@pytest.mark.asyncio
async def test_9_prefix_only():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r4", 4 * D), _old("r6", 6 * D)])])
    assert await _reenable(store) == 0
    assert _reasons(store) == ["r4", "r6"] and store.writes == [] and store.enabled()


@pytest.mark.asyncio
async def test_10_future_fired_at_kept():
    store = _EStore([_sw("a", enabled=False, pending=[_old("rF", -timedelta(hours=1))])])
    assert await _reenable(store) == 0 and _reasons(store) == ["rF"]


# ── 11-12: failure and concurrency ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_11_expiry_write_failure_raises_and_leaves_watch_disabled():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r6", 6 * D), _old("r4", 4 * D)])])
    store.raise_on("a")
    with pytest.raises(OSError):
        await _reenable(store)
    assert not store.enabled() and _reasons(store) == ["r6", "r4"]


@pytest.mark.asyncio
async def test_12_waits_for_a_running_evaluation():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r6", 6 * D)])])
    lock = ev_mod._run_lock()
    await lock.acquire()
    try:
        task = asyncio.create_task(_reenable(store))
        for _ in range(5):
            await asyncio.sleep(0)
        assert not task.done() and store.writes == [] and not store.enabled()
    finally:
        lock.release()
    assert await task == 1 and store.enabled() and store.pending("a") == []


# ── 13: end to end with a run ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_13_next_run_sends_only_the_young_alert():
    store = _EStore([_sw("a", enabled=False, pending=[_old("r6", 6 * D), _old("r4", 4 * D)])])
    await _reenable(store)
    n = _Notify()
    env = _CfgEnv(store, n)
    await env.run()
    assert n.reasons() == ["r4"]
    assert n.sent[0][1].startswith("Delayed:")
    assert store.pending("a") == []


# ── 14-15: both PATCH routes, real store on disk ──────────────────────────────

async def _patch_route(path, router_mod, store, wid, enabled=True):
    from app.main import create_app
    with patch(f"{router_mod}.strategy_watch_store", store), \
            patch(f"{_EV}._utcnow", return_value=T0):
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as ac:
            return await ac.patch(f"{path}/{wid}", json={"enabled": enabled})


def _seed(store, wid):
    store.update_state(wid, {"phase": "idle",
                             "pending_events": [_old("r6", 6 * D), _old("r4", 4 * D)]})
    store.set_enabled(wid, False)


@pytest.mark.asyncio
async def test_14_strategy_route(tmp_path):
    path = tmp_path / "w.yaml"
    store = StrategyWatchStore(path=path)
    wid = store.add_watch("AAPL", "pullback_ema")["id"]
    _seed(store, wid)
    r = await _patch_route("/api/strategy-watch", "app.routers.strategy_watch", store, wid)
    assert r.status_code == 200
    assert r.json() == {"id": wid, "enabled": True, "expired_alerts": 1}
    w = StrategyWatchStore(path=path).list_watches()[0]
    assert w["enabled"] is True
    assert [p["event"]["reason"] for p in w["last_state"]["pending_events"]] == ["r4"]
    r404 = await _patch_route("/api/strategy-watch", "app.routers.strategy_watch", store, "nope")
    assert r404.status_code == 404


@pytest.mark.asyncio
async def test_15_composite_route(tmp_path):
    path = tmp_path / "w.yaml"
    store = StrategyWatchStore(path=path)
    wid = store.add_composite_watch("AAPL", {"primary": {"model": "OMM"}})["id"]
    _seed(store, wid)
    r = await _patch_route("/api/composite-watches", "app.routers.composite_watch", store, wid)
    assert r.status_code == 200
    assert r.json() == {"id": wid, "enabled": True, "expired_alerts": 1}
    w = StrategyWatchStore(path=path).list_watches()[0]
    assert w["enabled"] is True
    assert [p["event"]["reason"] for p in w["last_state"]["pending_events"]] == ["r4"]
    r404 = await _patch_route("/api/composite-watches", "app.routers.composite_watch", store, "nope")
    assert r404.status_code == 404
