"""Tests for stocks-mode scan persistence — _upsert_stock_session,
restore_stock_from_db(), and GET /api/stock-scan/last."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.scan_session import ScanSession
from app.routers.stock_scan import router as stock_scan_router
from app.schemas.stock_scan import StockScanRequest, StockScanResult

# Re-use the test engine / session factory from conftest so we can query
# the same in-memory SQLite DB that the stock_client fixture writes to.
from tests.conftest import _TestSession, _override_get_db


@pytest.fixture
def stock_client():
    """Minimal TestClient wiring only the stock-scan router — mirrors the
    identically-named fixture in test_stock_scan_router.py (pytest fixtures
    aren't shared across files without conftest.py, so this is duplicated
    rather than imported)."""
    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_get_last_stock_scan_returns_none_when_no_scan_yet(stock_client, monkeypatch):
    import app.routers.stock_scan as stock_scan_module
    monkeypatch.setattr(stock_scan_module, "_last_stock_result", None)
    r = stock_client.get("/api/stock-scan/last")
    assert r.status_code == 200
    assert r.json() is None


def test_get_last_stock_scan_returns_the_last_result(stock_client, monkeypatch):
    import app.routers.stock_scan as stock_scan_module
    fake = StockScanResult(scan_id="SSCAN-1", timestamp="2026-07-24T10:00:00", candidates=[], rejected=[])
    monkeypatch.setattr(stock_scan_module, "_last_stock_result", fake)
    r = stock_client.get("/api/stock-scan/last")
    assert r.status_code == 200
    assert r.json()["scan_id"] == "SSCAN-1"


def test_stock_scan_result_persisted_to_db(stock_client):
    """POST /api/stock-scan with empty universe still writes a scan_sessions row
    under id='stock-current' — distinct from the options-mode 'current' row."""
    with (
        patch("app.data.universe_presets.expand_universe", return_value=[]),
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })
    assert r.status_code == 200

    import asyncio
    from sqlalchemy import select

    async def _check():
        async with _TestSession() as session:
            result = await session.execute(
                select(ScanSession).where(ScanSession.id == "stock-current")
            )
            return result.scalar_one_or_none()

    row = asyncio.run(_check())
    assert row is not None
    assert row.status == "complete"
    assert row.last_result_json is not None
    parsed = json.loads(row.last_result_json)
    assert "scan_id" in parsed


@pytest.mark.asyncio
async def test_restore_stock_from_db_restores_globals():
    """Insert a synthetic row → restore_stock_from_db() repopulates module globals."""
    import app.routers.stock_scan as stock_scan_module

    orig_request = stock_scan_module._last_stock_request
    orig_result = stock_scan_module._last_stock_result
    orig_async_session_local = stock_scan_module.AsyncSessionLocal

    stock_scan_module._last_stock_request = None
    stock_scan_module._last_stock_result = None
    stock_scan_module.AsyncSessionLocal = _TestSession

    try:
        from sqlalchemy import delete
        async with _TestSession() as session:
            await session.execute(delete(ScanSession).where(ScanSession.id == "stock-current"))
            await session.commit()

        async with _TestSession() as session:
            session.add(
                ScanSession(
                    id="stock-current",
                    status="complete",
                    last_request_json=StockScanRequest(
                        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
                    ).model_dump_json(),
                    last_result_json=StockScanResult(
                        scan_id="SSCAN-2", timestamp="2026-07-24T10:00:00", candidates=[], rejected=[],
                    ).model_dump_json(),
                )
            )
            await session.commit()

        await stock_scan_module.restore_stock_from_db()

        assert stock_scan_module._last_stock_result is not None
        assert stock_scan_module._last_stock_result.scan_id == "SSCAN-2"
        assert stock_scan_module._last_stock_request is not None
        assert stock_scan_module._last_stock_request.universe == ["AAPL"]
    finally:
        stock_scan_module._last_stock_request = orig_request
        stock_scan_module._last_stock_result = orig_result
        stock_scan_module.AsyncSessionLocal = orig_async_session_local
