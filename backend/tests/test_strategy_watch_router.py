# backend/tests/test_strategy_watch_router.py
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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
