# backend/tests/test_portfolio_close_history.py
"""Integration tests for the portfolio close/history/performance endpoints.

Self-contained: builds a small app with ONLY the portfolio router, backed by an
in-memory SQLite DB with the real Base metadata, and stubs the live Tradier quote
so exit-price auto-fill is deterministic.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c
    await engine.dispose()


async def _add(client, contract="AAPL|185|2026-09-18|C", qty=5, entry=1.00, rec="REC-1"):
    # Avoid the risk-engine 422 by using a large portfolio value.
    body = {"recId": rec, "symbol": "AAPL", "contract": contract, "direction": "Bullish",
            "entryPrice": entry, "qty": qty, "entryDate": "2026-05-01",
            "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 1_000_000}
    r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_full_close_records_history_and_removes_open(client):
    await _add(client, qty=3, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": None, "exitPrice": 1.50, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["qtyClosed"] == 3
    assert rec["realizedPnlDollar"] == 150.0   # (1.50-1.00)*100*3
    assert rec["realizedPnlPct"] == 50.0
    # open position gone
    assert (await client.get("/api/portfolio")).json() == []  # type: ignore
    # history has the one record
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["recId"] == "REC-1"


@pytest.mark.asyncio
async def test_partial_close_reduces_qty_and_keeps_open(client):
    await _add(client, qty=5, entry=1.00)
    r = await client.post("/api/portfolio/REC-1/close",
                          json={"qtyToClose": 2, "exitPrice": 2.00, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    assert r.json()["qtyClosed"] == 2
    open_positions = (await client.get("/api/portfolio")).json()
    assert len(open_positions) == 1
    assert open_positions[0]["qty"] == 3        # 5 - 2 remaining
    hist = (await client.get("/api/portfolio/history")).json()
    assert len(hist) == 1 and hist[0]["qtyClosed"] == 2


@pytest.mark.asyncio
async def test_close_auto_fills_exit_price_from_quote(client):
    await _add(client, qty=1, entry=1.00)
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               return_value={"price": 1.80}):
        r = await client.post("/api/portfolio/REC-1/close", json={})
    assert r.status_code == 201, r.text
    assert r.json()["exitPrice"] == 1.80
    assert r.json()["realizedPnlDollar"] == 80.0


@pytest.mark.asyncio
async def test_close_missing_position_404(client):
    r = await client.post("/api/portfolio/NOPE/close", json={"exitPrice": 1.0})
    assert r.status_code == 404
