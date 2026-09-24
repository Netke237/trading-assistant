"""O4 step 1: `create_position` is add_position's body, moved verbatim.

The existing POST /api/portfolio suite, run UNEDITED, is the proof that the move
changed nothing on the card path. These tests cover what that suite cannot:
the writer called DIRECTLY (as the auto-trade booking path will call it), and
the router reading the resize from the writer's outcome rather than from a
`risk` it no longer holds.
"""
from __future__ import annotations

from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base, get_db
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router
from app.schemas import PortfolioPositionCreate
from app.services.portfolio_risk import RiskCheckResult
from app.services.position_writer import WriteOutcome, create_position


@pytest_asyncio.fixture
async def Session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


def _body(**overrides) -> dict:
    body = {
        "recId": "REC-W1", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 4,
        "entryDate": "2026-07-17", "stop": 89.89, "targets": [],
        "dteTotal": 547, "portfolioValue": 1_000_000,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_a_direct_call_persists_and_reports_what_it_did(Session):
    """Called without the router -- the booking path's shape. The default
    fetchers are THIS module's, so patching them here is what keeps it offline."""
    with patch("app.services.position_writer.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        async with Session() as db:
            outcome = await create_position(PortfolioPositionCreate(**_body()), db)

    assert isinstance(outcome, WriteOutcome)
    assert outcome.adjusted_size is None
    assert outcome.over_exposure is False, (
        "with the gate enforced an unapproved position raises; it never reaches a row"
    )
    async with Session() as db:
        rows = (await db.execute(select(PortfolioPositionModel))).scalars().all()
    assert [(r.rec_id, r.qty, r.entry_price) for r in rows] == [("REC-W1", 4, 10.45)]


@pytest.mark.asyncio
async def test_the_gate_still_refuses_on_a_direct_call(Session):
    """The 422 is part of the moved body, so a non-HTTP caller sees it too."""
    refused = RiskCheckResult(approved=False, reasons=["too much"], adjusted_size=None)
    with (
        patch("app.services.position_writer.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch("app.services.position_writer.check_position_risk", return_value=refused),
    ):
        async with Session() as db:
            with pytest.raises(HTTPException) as exc:
                await create_position(PortfolioPositionCreate(**_body()), db)
    assert exc.value.status_code == 422
    async with Session() as db:
        assert (await db.execute(select(PortfolioPositionModel))).first() is None


@pytest.mark.asyncio
async def test_the_router_reads_the_resize_from_the_writers_outcome(Session):
    """`adjustedQty` on the response and `qty` on the row must both be the
    gate's resize. The router no longer holds `risk`; it must read the outcome."""
    resized = RiskCheckResult(approved=True, adjusted_size=2)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch("app.services.position_writer.check_position_risk", return_value=resized),
    ):
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
            r = await c.post("/api/portfolio", json=_body())

    assert r.status_code == 201, r.text
    assert r.json()["adjustedQty"] == 2
    assert r.json()["qty"] == 2


@pytest.mark.asyncio
async def test_the_router_passes_its_own_fetchers_so_its_patches_land(Session):
    """Why the three callables are injected: the router suite patches names on
    `app.routers.portfolio`. If the router stopped passing them, those patches
    would miss and the suite would reach the network. Pinned here directly."""
    router_quote = AsyncMock(return_value={"price": 11.11})

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=router_quote),
        patch("app.services.position_writer.fetch_contract_quote_async",
              new=AsyncMock(side_effect=AssertionError("the writer's default was used"))),
    ):
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
            r = await c.post("/api/portfolio", json=_body())

    assert r.status_code == 201, r.text
    assert router_quote.await_count == 1
    assert r.json()["entryPrice"] == 11.11, "the live quote from the router's fetcher is stored"
