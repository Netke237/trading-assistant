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
async def test_a_direct_call_persists_and_reports_what_it_did(Session, monkeypatch):
    """Called without the router -- the booking path's shape. The default
    fetchers are THIS module's, so patching them here is what keeps it offline."""
    from copy import deepcopy
    from app.services import portfolio_risk
    config = deepcopy(portfolio_risk._load_config())
    config.setdefault("portfolio", {})["portfolio_value"] = 1_000_000
    monkeypatch.setattr(portfolio_risk, "_load_config", lambda: config)
    quote = AsyncMock(return_value=None)
    with patch("app.services.position_writer.fetch_contract_quote_async", new=quote):
        async with Session() as db:
            outcome = await create_position(PortfolioPositionCreate(**_body()), db)

    # P1a: the defaults resolve at call time, so the patch above is what ran --
    # a default bound at import time would have gone to the network instead.
    quote.assert_awaited_once()
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
    # Asserted below, not relied on to raise: the writer runs its fetches
    # inside `except Exception`, so a side_effect here would be swallowed.
    writer_quote = AsyncMock(return_value=None)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=router_quote),
        patch("app.services.position_writer.fetch_contract_quote_async", new=writer_quote),
    ):
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
            r = await c.post("/api/portfolio", json=_body())

    assert r.status_code == 201, r.text
    writer_quote.assert_not_awaited()
    assert router_quote.await_count == 1
    assert r.json()["entryPrice"] == 11.11, "the live quote from the router's fetcher is stored"


# ── P1a: call-time defaults, and create serialised against create ───────────
# Plan: docs/superpowers/plans/2026-09-25-p1a-backend-contract-cap-plan.md s5 12-13b.

import asyncio  # noqa: E402

from unittest.mock import Mock  # noqa: E402


@pytest.mark.asyncio
async def test_p1a_12_the_price_fetcher_default_is_looked_up_at_call_time(Session):
    quote, price = AsyncMock(return_value=None), AsyncMock(return_value=None)
    with (
        patch("app.services.position_writer.fetch_contract_quote_async", new=quote),
        patch("app.services.position_writer.fetch_price_async", new=price),
    ):
        async with Session() as db:
            await create_position(PortfolioPositionCreate(**_body(stopIsUserSet=True)), db)
    price.assert_awaited_once()


@pytest.mark.asyncio
async def test_p1a_12_the_exit_plan_loader_default_is_looked_up_at_call_time(Session):
    loader = Mock(return_value={})
    with (
        patch("app.services.position_writer.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch("app.services.position_writer.load_exit_plan_cfg", new=loader),
    ):
        async with Session() as db:
            await create_position(PortfolioPositionCreate(**_body()), db)
    loader.assert_called_once()


@pytest_asyncio.fixture
async def FileSession(tmp_path):
    """A file-backed db, so two sessions are two real connections."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'p1a.db'}")
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


def _barrier_commit():
    """Hold every commit at a two-party barrier for up to 0.5s. With the
    booking lock the second create is still waiting on the lock, so the first
    times out alone and commits; without it both have judged the SAME portfolio
    by the time they meet here, so the interleaving is forced, not hoped for."""
    barrier = asyncio.Barrier(2)
    real_commit = AsyncSession.commit

    async def commit(self):
        try:
            await asyncio.wait_for(barrier.wait(), timeout=0.5)
        except (TimeoutError, asyncio.BrokenBarrierError):
            pass
        return await real_commit(self)

    return patch.object(AsyncSession, "commit", new=commit)


async def _create_in_own_session(maker, body):
    async with maker() as db:
        try:
            await create_position(
                PortfolioPositionCreate(**body), db,
                quote_fetcher=AsyncMock(return_value=None),
                price_fetcher=AsyncMock(return_value=None),
                exit_plan_cfg_loader=lambda: {},
            )
            return 201
        except HTTPException as exc:
            return (exc.status_code, exc.detail)


@pytest.mark.asyncio
async def test_p1a_13_two_creates_that_breach_the_total_cap_together_judge_in_turn(FileSession):
    """Seeded 18.9% of 100k; each create is 3.5% (1 x 35.00 x 100, inside the
    3.75% option premium cap, review fix #4 / D5), so each alone totals 22.4%
    (fits 25%) and both together 25.9%."""
    async with FileSession() as db:
        db.add(PortfolioPositionModel(
            rec_id="REC-SEED", symbol="ZZZ", contract="ZZZ|1|2027-01-15|C",
            direction="Bullish", entry_price=63.0, qty=3, entry_date="2026-07-17"))
        await db.commit()
    a = _body(recId="REC-A", symbol="AAA", contract="AAA|50|2027-01-15|C",
              entryPrice=35.0, qty=1, portfolioValue=100_000)
    b = _body(recId="REC-B", symbol="BBB", contract="BBB|50|2027-01-15|C",
              entryPrice=35.0, qty=1, portfolioValue=100_000)
    with _barrier_commit():
        results = await asyncio.gather(
            _create_in_own_session(FileSession, a), _create_in_own_session(FileSession, b))
    assert sorted(map(str, results)) == sorted(
        ["201", str((422, "total_exposure_limit_reached"))]), results


@pytest.mark.asyncio
async def test_p1a_13b_a_same_contract_race_answers_409_never_422(FileSession):
    a = _body(recId="REC-A", entryPrice=35.0, qty=1, portfolioValue=100_000)
    b = _body(recId="REC-B", entryPrice=35.0, qty=1, portfolioValue=100_000)
    with _barrier_commit():
        results = await asyncio.gather(
            _create_in_own_session(FileSession, a), _create_in_own_session(FileSession, b))
    assert 201 in results, results
    [other] = [r for r in results if r != 201]
    assert other[0] == 409 and "already exists" in other[1], results
