# backend/tests/test_portfolio_entry_stock_price.py
"""Tests for entryStockPrice in GET /api/portfolio and PortfolioPositionSchema (#630)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionSchema


@pytest_asyncio.fixture
async def app_fixture() -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _get_db():
        async with session_factory() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_portfolio_returns_entry_stock_price_for_option_legacy_and_stock(app_fixture):
    client, session_factory = app_fixture

    async with session_factory() as db:
        # 1. Option position with recorded entry_stock_price
        pos_option_recorded = PortfolioPositionModel(
            id=uuid.uuid4(),
            rec_id="rec-opt-1",
            symbol="AAPL",
            contract="AAPL|220|2026-12-18|C",
            direction="Bullish",
            entry_price=3.00,
            entry_stock_price=215.50,
            qty=2,
            entry_date="2026-11-12",
            stop=205.00,
            structural_stop=210.00,
            created_at=datetime.now(timezone.utc),
        )

        # 2. Legacy option position with NULL entry_stock_price
        pos_option_legacy = PortfolioPositionModel(
            id=uuid.uuid4(),
            rec_id="rec-opt-legacy",
            symbol="MSFT",
            contract="MSFT|400|2026-12-18|P",
            direction="Bearish",
            entry_price=5.20,
            entry_stock_price=None,
            qty=1,
            entry_date="2026-11-10",
            stop=415.00,
            created_at=datetime.now(timezone.utc),
        )

        # 3. Stock position
        pos_stock = PortfolioPositionModel(
            id=uuid.uuid4(),
            rec_id="rec-stock-1",
            symbol="NVDA",
            contract="NVDA|STOCK",
            direction="Bullish",
            entry_price=120.75,
            entry_stock_price=None,  # may be None in DB for stock positions
            qty=50,
            entry_date="2026-11-12",
            stop=115.00,
            created_at=datetime.now(timezone.utc),
        )

        db.add_all([pos_option_recorded, pos_option_legacy, pos_stock])
        await db.commit()

    with patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value={"price": 3.10})), \
         patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=216.00)):
        resp = await client.get("/api/portfolio")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    by_rec = {row["recId"]: row for row in data}

    # Option with recorded entry stock price
    assert by_rec["rec-opt-1"]["entryPrice"] == 3.00
    assert by_rec["rec-opt-1"]["entryStockPrice"] == 215.50

    # Legacy option position has null
    assert by_rec["rec-opt-legacy"]["entryPrice"] == 5.20
    assert by_rec["rec-opt-legacy"]["entryStockPrice"] is None

    # Stock position mirrors entryPrice
    assert by_rec["rec-stock-1"]["entryPrice"] == 120.75
    assert by_rec["rec-stock-1"]["entryStockPrice"] == 120.75


def test_portfolio_position_schema_from_orm_model_direct():
    # Direct test of PortfolioPositionSchema.from_orm_model
    class DummyOrmOption:
        id = uuid.uuid4()
        rec_id = "rec-1"
        symbol = "XYZ"
        contract = "XYZ|100|2026-12-18|C"
        direction = "Bullish"
        entry_price = 2.50
        entry_stock_price = 98.25
        qty = 1
        entry_date = "2026-11-12"
        stop = 95.0
        structural_stop = None
        targets = []
        dte_total = 30
        created_at = datetime.now(timezone.utc)
        exit_plan = None
        max_loss_override = None
        active_tp_method = "ladder"
        resolved_tp_price = None
        resolved_tp_updated_at = None
        alert_overrides = {}
        premium_stop_pct = 0.5
        picked_method = None
        picked_row_stock_price = None
        picked_row_option_price = None
        picked_stop_basis = None
        picked_at = None
        hold_max_days = None

    schema = PortfolioPositionSchema.from_orm_model(DummyOrmOption())
    assert schema.entryStockPrice == 98.25
    assert schema.entryPrice == 2.50

    # Stock position
    DummyOrmOption.contract = "XYZ|STOCK"
    DummyOrmOption.entry_stock_price = None
    schema_stock = PortfolioPositionSchema.from_orm_model(DummyOrmOption())
    assert schema_stock.entryStockPrice == 2.50
