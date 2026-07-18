# backend/tests/test_portfolio_concurrent_add.py
"""Regression: a unique-constraint race on POST /api/portfolio must return 409
(idempotent — 'already saved'), not a 500.

Two POSTs for the same contract can both pass the pre-check SELECT before
either commits — e.g. addPosition's own POST racing syncFromBackend's
pending-retry POST for the same optimistic row. The loser previously hit the
unpatched unique(contract) constraint and surfaced as a raw 500, which the
frontend classified as a hard rejection (dropping a position the winning POST
had actually just saved). It must now be treated the same as the pre-check
duplicate path: 409.
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
async def test_commit_race_on_duplicate_contract_returns_409_not_500(client):
    body = {
        "recId": "REC-RACE-1", "symbol": "ABT", "contract": "ABT|97|2027-01-15|C",
        "direction": "Bullish", "entryPrice": 10.45, "qty": 1, "entryDate": "2026-07-17",
        "stop": 89.89, "targets": [], "dteTotal": 547, "portfolioValue": 1_000_000,
    }
    # Simulate the race: db.commit() raises IntegrityError as if a concurrent
    # request for the same contract won the insert first. The pre-check SELECT
    # still reports "not found" (that's exactly how the race happens).
    from sqlalchemy.exc import IntegrityError

    with (
        patch("app.routers.portfolio.fetch_contract_quote_async",
              new=AsyncMock(return_value=None)),
        patch.object(AsyncSession, "commit",
                     new=AsyncMock(side_effect=IntegrityError("UNIQUE constraint failed", None, None))),
    ):
        r = await client.post("/api/portfolio", json=body)

    assert r.status_code == 409, r.text
    assert "already exists" in r.text
