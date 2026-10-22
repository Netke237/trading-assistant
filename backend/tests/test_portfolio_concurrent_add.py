# backend/tests/test_portfolio_concurrent_add.py
"""Regression: a unique-constraint race on POST /api/portfolio must be resolved
correctly depending on WHICH constraint actually collided.

`PortfolioPositionModel` has two unique columns: `contract` and `rec_id`. Two
POSTs can both pass the pre-check SELECT (which only checks `contract`) before
either commits — e.g. addPosition's own POST racing syncFromBackend's
pending-retry POST for the same optimistic row.

- If the LOSING commit collided on `contract`, the row IS safely saved (under
  the winning request) — must return 409 "already exists" so the client treats
  it as a safe duplicate, not a hard rejection that drops a saved position.
- If the LOSING commit collided on `rec_id` instead, this row was genuinely
  NEVER persisted — treating that the same as a contract collision would have
  the client silently promote an unsaved row to "synced". Must return 500 so
  the client retries instead of losing the position.
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
from app.models.portfolio import PortfolioPositionModel
from app.routers.portfolio import router as portfolio_router


@pytest_asyncio.fixture
async def engine_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 connect_args={"check_same_thread": False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, Session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(engine_and_session) -> AsyncGenerator[AsyncClient, None]:
    _, Session = engine_and_session

    async def _get_db():
        async with Session() as s:
            yield s

    test_app = FastAPI()
    test_app.include_router(portfolio_router)
    test_app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://t") as c:
        yield c


async def _insert_raw(Session, **overrides) -> None:
    """Insert a position directly, bypassing the router — simulates a
    concurrent request that already committed. Symbol defaults to something
    OTHER than the test bodies' "ABT" so the risk engine's one-position-per-
    symbol rule doesn't reject the test POST before ever reaching commit —
    these tests isolate the unique-constraint race, not that unrelated rule."""
    defaults = dict(
        rec_id="REC-WINNER", symbol="ZZZZ", contract="WINNER|1|2027-01-01|C",
        direction="Bullish", entry_price=1.0, qty=1, entry_date="2026-07-17",
        stop=None, targets=[], dte_total=100,
    )
    defaults.update(overrides)
    async with Session() as s:
        s.add(PortfolioPositionModel(**defaults))
        await s.commit()


@pytest.mark.asyncio
async def test_contract_collision_race_returns_409_already_exists(client, engine_and_session):
    """Pre-check says 'not found' (patched to simulate the race timing), but the
    contract genuinely exists by commit time → 409, safe duplicate."""
    _, Session = engine_and_session
    await _insert_raw(Session, rec_id="REC-WINNER", contract="ABT|97|2027-01-15|C")

    body = {
        "recId": "REC-LOSER", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 1, "entryDate": "2026-07-17",
        "stop": 89.89, "targets": [], "dteTotal": 547, "portfolioValue": 1_000_000,
    }

    real_execute = AsyncSession.execute
    real_rollback = AsyncSession.rollback
    seen = {"rolled_back": False, "emptied": 0}

    # P1a: the writer now checks for the contract TWICE before the commit (once
    # before the live fetches, once again under the booking lock), so emptying
    # only the first SELECT by call count would let the in-lock re-check answer
    # the 409 itself and this test would never reach the IntegrityError branch
    # it exists to pin. So EVERY contract-existence SELECT is emptied -- matched
    # on the statement, not the call count -- until the IntegrityError branch's
    # rollback; after it, the branch's own re-check must see the row.
    async def _bypass_contract_prechecks(self, statement, *args, **kwargs):
        sql = str(statement)
        if (not seen["rolled_back"] and "WHERE" in sql
                and "portfolio_positions.contract =" in sql):
            # Simulate the race: at the moment of THIS request's pre-checks, the
            # concurrent winner hadn't committed yet.
            seen["emptied"] += 1
            class _Empty:
                def scalar_one_or_none(self):
                    return None
                def first(self):
                    return None
            return _Empty()
        return await real_execute(self, statement, *args, **kwargs)

    async def _rollback_spy(self, *args, **kwargs):
        # The exposure snapshot restart rolls back the pre-fetch read before
        # the in-lock re-check. The IntegrityError rollback is the one after
        # both contract pre-checks have been emptied.
        if seen["emptied"] >= 2:
            seen["rolled_back"] = True
        return await real_rollback(self, *args, **kwargs)

    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch.object(AsyncSession, "execute", new=_bypass_contract_prechecks),
        patch.object(AsyncSession, "rollback", new=_rollback_spy),
    ):
        r = await client.post("/api/portfolio", json=body)

    assert seen["emptied"] == 2, "both pre-commit contract checks were bypassed"
    assert seen["rolled_back"], "the 409 came from the IntegrityError branch"
    assert r.status_code == 409, r.text
    assert "already exists" in r.text


@pytest.mark.asyncio
async def test_rec_id_collision_race_returns_500_not_409(client, engine_and_session):
    """A different contract but a rec_id that collides — the row was NEVER
    persisted, so this must NOT be reported as a safe 409 duplicate."""
    _, Session = engine_and_session
    await _insert_raw(Session, rec_id="REC-DUPLICATE", contract="OTHER|1|2027-01-01|C")

    body = {
        "recId": "REC-DUPLICATE", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 1, "entryDate": "2026-07-17",
        "stop": 89.89, "targets": [], "dteTotal": 547, "portfolioValue": 1_000_000,
    }
    # No mocking needed: the contract-only pre-check naturally passes (different
    # contract), and the real commit fails for real on the rec_id unique constraint.
    with patch("app.routers.portfolio.fetch_contract_quote_async",
               new=AsyncMock(return_value=None)):
        r = await client.post("/api/portfolio", json=body)

    assert r.status_code == 500, r.text
    assert "already exists" not in r.text
    assert "rec_id" in r.text
