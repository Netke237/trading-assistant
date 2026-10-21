# backend/tests/test_strategy_watch_router.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.watch_notify_helpers import configured_channels_no_real_sends  # noqa: F401


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Point the store at a temp file so tests don't touch the real config.
    monkeypatch.setenv("BAMENDJOU_STRATEGY_WATCHES_PATH", str(tmp_path / "w.yaml"))
    import importlib
    import app.services.strategy_watch_store as sws
    importlib.reload(sws)
    import app.routers.strategy_watch as r
    importlib.reload(r)
    return create_app()


@pytest.mark.asyncio
async def test_add_list_remove_roundtrip(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        add = await ac.post("/api/strategy-watch/",
                            json={"symbol": "aapl", "strategy_key": "pullback_ema"})
        assert add.status_code == 201
        wid = add.json()["id"]
        lst = await ac.get("/api/strategy-watch/")
        assert lst.status_code == 200 and len(lst.json()) == 1
        rm = await ac.delete(f"/api/strategy-watch/{wid}")
        assert rm.status_code == 200
        lst2 = await ac.get("/api/strategy-watch/")
        assert lst2.json() == []


@pytest.mark.asyncio
async def test_add_watch_rejects_invalid_direction(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "pullback_ema", "direction": "sideways"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_add_rejects_invalid_direction(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/bulk",
                            json={"symbols": ["AAPL"], "strategy_key": "pullback_ema", "direction": "sideways"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_add_unknown_strategy_returns_400(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "nope"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_duplicate_returns_409(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/strategy-watch/", json={"symbol": "AAPL", "strategy_key": "ma_crossover"})
        dup = await ac.post("/api/strategy-watch/", json={"symbol": "AAPL", "strategy_key": "ma_crossover"})
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_add_same_symbol_strategy_different_direction_returns_201(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        bullish = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "ma_crossover", "direction": "Bullish"})
        bearish = await ac.post("/api/strategy-watch/",
                            json={"symbol": "AAPL", "strategy_key": "ma_crossover", "direction": "Bearish"})
    assert bullish.status_code == 201
    assert bearish.status_code == 201
    assert bullish.json()["id"] != bearish.json()["id"]


@pytest.mark.asyncio
async def test_bulk_add(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/bulk",
                            json={"symbols": ["AAPL", "MSFT"], "strategy_key": "breakout_base"})
    assert resp.status_code == 201
    assert resp.json()["added"] == 2


@pytest.mark.asyncio
async def test_schedule_get_and_put(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        get = await ac.get("/api/strategy-watch/schedule")
        assert get.json()["mode"] == "eod"
        put = await ac.put("/api/strategy-watch/schedule",
                          json={"enabled": True, "mode": "poll", "eod_time": "16:15", "poll_hours": 3})
        assert put.json()["mode"] == "poll"


@pytest.mark.asyncio
async def test_evaluate_returns_events(app):
    fake_event = {"symbol": "AAPL", "event_type": "entry"}
    with patch("app.routers.strategy_watch.strategy_watch_scheduler.run_now",
               new_callable=AsyncMock) as run:
        run.return_value = [type("E", (), fake_event)()]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            resp = await ac.post("/api/strategy-watch/evaluate")
    assert resp.status_code == 200
    assert resp.json()["fired"] == 1


@pytest.mark.asyncio
async def test_patch_enabled(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        add = await ac.post("/api/strategy-watch/",
                            json={"symbol": "TSLA", "strategy_key": "ma_crossover"})
        wid = add.json()["id"]
        patch_resp = await ac.patch(f"/api/strategy-watch/{wid}", json={"enabled": False})
        assert patch_resp.status_code == 200
        assert patch_resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_get_status(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.get("/api/strategy-watch/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data and "mode" in data


@pytest.mark.asyncio
async def test_bulk_unknown_strategy_returns_400(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        resp = await ac.post("/api/strategy-watch/bulk",
                            json={"symbols": ["AAPL"], "strategy_key": "nonexistent"})
    assert resp.status_code == 400


# ── COMPOSITE-WATCH-STRATEGY-KEY-CRASH ────────────────────────────────────────
# Seed composite rows directly on the RELOADED store. Never via
# POST /api/composite-watches/: the fixture does not reload that router, so it
# still holds the pre-reload store (pointing at the real config file) -- the
# write would miss this test's store and the test would pass vacuously on main.
_OMM_TD = {"primary": {"model": "OMM", "to_state": "Bull"}}


@pytest.mark.asyncio
async def test_add_strategy_watch_for_symbol_with_composite_watch_is_201(app):
    import app.services.strategy_watch_store as sws
    sws.strategy_watch_store.add_composite_watch("AAPL", _OMM_TD)
    assert len(sws.strategy_watch_store.list_watches()) == 1
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post("/api/strategy-watch/",
                          json={"symbol": "AAPL", "strategy_key": "pullback_ema"})
    assert r.status_code == 201
    assert len(sws.strategy_watch_store.list_watches()) == 2


@pytest.mark.asyncio
async def test_evaluate_now_with_enabled_composite_watch_is_200(app):
    import app.services.strategy_watch_store as sws
    sws.strategy_watch_store.add_composite_watch("AAPL", _OMM_TD)
    bars = [{"time": f"2024-01-{d:02d}", "open": 100.0, "high": 101.0, "low": 99.0,
             "close": 100.0, "volume": 1_000_000} for d in range(1, 29)]
    # The evaluator also captured the pre-reload store; point it at this test's store.
    # evaluate_scheduled -> False and notify patched: nothing can be sent for real.
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store",
               sws.strategy_watch_store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=bars), \
         patch("app.services.strategy_watch_evaluator.read_notification_config",
               return_value=({"telegram": {"enabled": True, "bot_token": "tok", "chat_id": "123"}}, ["telegram"])), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
               return_value=False), \
         patch("app.services.strategy_watch_evaluator.notify_channels",
               new_callable=AsyncMock) as notify:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post("/api/strategy-watch/evaluate")
    assert r.status_code == 200
    assert r.json()["fired"] == 0
    notify.assert_not_called()


@pytest.mark.asyncio
async def test_list_returns_strategy_watches_only(app):
    """P4b T7 (open_questions[65]): composites are /api/composite-watches/' to
    list; the strategy-watch page showed them with an empty Strategy cell."""
    import app.services.strategy_watch_store as sws
    sws.strategy_watch_store.add_composite_watch(
        "MSFT", {"primary": {"model": "OMM", "to_state": "bull_trend"}})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        add = await ac.post("/api/strategy-watch/",
                            json={"symbol": "aapl", "strategy_key": "pullback_ema"})
        assert add.status_code == 201
        lst = await ac.get("/api/strategy-watch/")
    assert [w["id"] for w in lst.json()] == [add.json()["id"]]
    assert len(sws.strategy_watch_store.list_watches()) == 2
