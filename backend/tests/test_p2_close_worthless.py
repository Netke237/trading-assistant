"""P2-01 (decision Q6): a position is marked worthless by CLOSING it at $0.

Self-contained, like test_portfolio_close_history.py: only the portfolio router,
an in-memory SQLite DB, and a stubbed quote. Writes no yaml.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

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


@pytest.mark.asyncio
async def test_close_at_zero_books_a_total_loss(client):
    body = {"recId": "REC-W", "symbol": "AAPL", "contract": "AAPL|185|2026-09-18|C",
            "direction": "Bullish", "entryPrice": 2.00, "qty": 3, "entryDate": "2026-05-01",
            "stop": None, "targets": [], "dteTotal": 140, "portfolioValue": 1_000_000}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    # A quote is available, so a null exitPrice WOULD be auto-filled -- an
    # explicit 0 must win over it (the router checks `is None`, not falsiness).
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value={"price": 1.80})):
        r = await client.post("/api/portfolio/REC-W/close",
                              json={"qtyToClose": None, "exitPrice": 0, "exitDate": "2026-05-31"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["exitPrice"] == 0
    assert rec["realizedPnlDollar"] == -600.0   # (0 - 2.00) * 100 * 3
    assert rec["realizedPnlPct"] == -100.0
