# backend/tests/test_p1a_callers_through_source_cap.py
"""P1a: the source-level contract cap reaches the two callers whose files P1
does not own -- the auto-trader's pre-broker fire check (auto_trader.py, P3b)
and the drawer qty PATCH (routers/portfolio.py, P6) -- with no edit to them.

Plan: docs/superpowers/plans/2026-09-25-p1a-backend-contract-cap-plan.md s5 24-25.
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
from app.routers.auto_trade import ArmRequest
from app.routers.portfolio import router as portfolio_router
from app.services.auto_trader import ArmedStrategy, AutoTradeService


def _strategy(quantity: int) -> ArmedStrategy:
    body = {
        "broker": "ibkr_paper", "symbol": "AAPL", "option_symbol": "AAPL|185|2026-12-18|C",
        "action": "BUY", "direction": "Bullish", "horizon": "Swing", "hold_max_days": 15,
        "quantity": quantity, "order_type": "LMT", "limit_price": 1.0, "entry_premium": 1.0,
        "stop": 180.0, "conid": None,
    }
    return ArmedStrategy(**ArmRequest(**body).model_dump())


def test_24_the_fire_check_refuses_a_six_lot_before_the_broker():
    with pytest.raises(RuntimeError) as exc:
        AutoTradeService._check_exposure(_strategy(6), [], 100_000.0)
    assert "Exposure cap breach" in str(exc.value)
    assert "exceeds_max_contracts_per_trade" in str(exc.value)
    AutoTradeService._check_exposure(_strategy(5), [], 100_000.0)  # does not raise


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
async def test_25_a_drawer_qty_raise_past_the_cap_is_refused_and_the_stop_still_saves(client):
    body = {"recId": "REC-P", "symbol": "AAPL", "contract": "AAPL|185|2026-12-18|C",
            "direction": "Bullish", "entryPrice": 1.0, "qty": 3, "entryDate": "2026-05-01",
            "stop": 170.0, "targets": [], "dteTotal": 140, "portfolioValue": 1_000_000}
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)
    assert r.status_code == 201, r.text

    r = await client.patch("/api/portfolio/REC-P",
                           json={"qty": 6, "stop": 175.0, "portfolioValue": 1_000_000})
    assert r.status_code == 422, r.text
    assert "exceeds_max_contracts_per_trade" in r.text

    rows = (await client.get("/api/portfolio")).json()
    [row] = [p for p in rows if p["recId"] == "REC-P"]
    assert row["qty"] == 3
    assert row["stop"] == 175.0
