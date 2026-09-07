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


# ── Tests for /stock-scan/last-run and the running/idle status writes ────────

def test_last_run_carries_no_iv_thresholds(stock_client, monkeypatch):
    """Stock mode shares ScanSessionStatus with options mode, which added
    scan_id/iv_abs_threshold/iv_rank_threshold for the IV-basis measurement
    store. Stock scans have no IV cut-offs and pair no ScanResult here, so all
    three must stay None rather than defaulting to a number a reader could
    mistake for the line a scan ran with."""
    import app.routers.stock_scan as stock_scan_module
    monkeypatch.setattr(stock_scan_module, "_last_stock_request", None)
    monkeypatch.setattr(stock_scan_module, "_last_stock_status", "idle")
    body = stock_client.get("/api/stock-scan/last-run").json()
    assert body["scan_id"] is None
    assert body["iv_abs_threshold"] is None
    assert body["iv_rank_threshold"] is None


def test_last_run_idle_when_no_scan_yet(stock_client, monkeypatch):
    import app.routers.stock_scan as stock_scan_module
    monkeypatch.setattr(stock_scan_module, "_last_stock_request", None)
    monkeypatch.setattr(stock_scan_module, "_last_stock_status", "idle")
    monkeypatch.setattr(stock_scan_module, "_last_stock_updated_at", None)
    r = stock_client.get("/api/stock-scan/last-run")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "idle"
    assert body["updated_at"] is None
    assert body["strategy"] is None


def test_running_write_happens_before_complete_write_and_preserves_prior_result(stock_client):
    """The running-write at scan start must not null out the previously
    completed result — it should carry the prior result forward until the
    scan actually finishes and overwrites it with the new one."""
    import app.routers.stock_scan as stock_scan_module
    from app.schemas.stock_scan import StockScanResult

    prior_result = StockScanResult(
        scan_id="SSCAN-PRIOR", timestamp="2026-08-01T00:00:00", candidates=[], rejected=[],
    )
    prior_request = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )
    stock_scan_module._last_stock_request = prior_request
    stock_scan_module._last_stock_result = prior_result

    seen_statuses: list[str] = []
    orig_upsert = stock_scan_module._upsert_stock_session

    async def _spy_upsert(db, req, result, status="complete"):
        seen_statuses.append(status)
        if status == "running":
            # At the moment of the running-write, the prior result must still
            # be what gets persisted — not None.
            assert result is not None
            assert result.scan_id == "SSCAN-PRIOR"
        await orig_upsert(db, req, result, status)

    with (
        patch("app.data.universe_presets.expand_universe", return_value=[]),
        patch("app.routers.stock_scan.fetch_quotes", return_value={}),
        patch.object(stock_scan_module, "_upsert_stock_session", _spy_upsert),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "breakout_base",
        })
    assert r.status_code == 200
    assert seen_statuses == ["running", "complete"]
    assert stock_scan_module._last_stock_status == "complete"
    assert stock_scan_module._last_stock_request.strategy == "breakout_base"


def test_mid_scan_exception_reverts_to_idle_not_stuck_running(stock_client, monkeypatch):
    """A failure inside the scan body (e.g. an unavailable universe preset)
    must not leave the session stranded at status='running' forever — and
    with no prior scan, the revert target genuinely is 'idle'."""
    import app.routers.stock_scan as stock_scan_module
    from app.data.universe_presets import PresetUnavailableError

    stock_scan_module._last_stock_request = None
    stock_scan_module._last_stock_result = None
    monkeypatch.setattr(stock_scan_module, "_last_stock_status", "idle")

    with patch(
        "app.data.universe_presets.expand_universe",
        side_effect=PresetUnavailableError("SP500 preset unavailable"),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "pullback_ema",
        })
    assert r.status_code == 400
    assert stock_scan_module._last_stock_status == "idle"

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
    assert row.status == "idle"


def test_mid_scan_exception_after_a_completed_scan_reverts_to_complete_not_idle(stock_client):
    """A failed scan immediately after a genuinely completed one must not
    mislabel that still-valid prior result as 'idle' — the revert should
    restore the real prior status ('complete'), not hardcode 'idle'."""
    import app.routers.stock_scan as stock_scan_module
    from app.data.universe_presets import PresetUnavailableError
    from app.schemas.stock_scan import StockScanResult

    prior_result = StockScanResult(
        scan_id="SSCAN-PRIOR", timestamp="2026-08-01T00:00:00", candidates=[], rejected=[],
    )
    prior_request = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
    )
    stock_scan_module._last_stock_request = prior_request
    stock_scan_module._last_stock_result = prior_result
    stock_scan_module._last_stock_status = "complete"

    with patch(
        "app.data.universe_presets.expand_universe",
        side_effect=PresetUnavailableError("SP500 preset unavailable"),
    ):
        r = stock_client.post("/api/stock-scan", json={
            "universe": ["SP500"],
            "direction": "Bullish",
            "horizon": "Swing",
            "strategy": "breakout_base",
        })
    assert r.status_code == 400
    assert stock_scan_module._last_stock_status == "complete"
    assert stock_scan_module._last_stock_request.strategy == "pullback_ema"
    assert stock_scan_module._last_stock_result.scan_id == "SSCAN-PRIOR"
