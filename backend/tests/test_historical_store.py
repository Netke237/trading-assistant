"""Tests for historical_store.py — uses an in-memory SQLite DB via override."""
import asyncio
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services.historical_store import (
    _store_bars,
    _read_bars,
    get_prefetch_status,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def _bars(n: int, start: date = date(2024, 1, 2)) -> list[dict]:
    """Generate n synthetic daily bars starting from `start`."""
    return [
        {
            "time":   (start + timedelta(days=i)).isoformat(),
            "open":   100.0 + i,
            "high":   101.0 + i,
            "low":     99.0 + i,
            "close":  100.5 + i,
            "volume": 1_000_000,
        }
        for i in range(n)
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_bars_inserts_rows(db):
    bars = _bars(5)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    result = await db.execute(
        select(OhlcvDailyModel)
        .where(OhlcvDailyModel.symbol == "AAPL")
    )
    rows = result.scalars().all()
    assert len(rows) == 5
    assert rows[0].close == pytest.approx(100.5)


@pytest.mark.asyncio
async def test_store_bars_upsert_does_not_duplicate(db):
    bars = _bars(3)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    # Store the same bars again — should not create duplicates
    await _store_bars("AAPL", bars, db)
    await db.commit()
    from sqlalchemy import select, func
    result = await db.execute(
        select(func.count()).where(OhlcvDailyModel.symbol == "AAPL")
    )
    count = result.scalar_one()
    assert count == 3


@pytest.mark.asyncio
async def test_read_bars_returns_sorted_dicts(db):
    bars = _bars(5)
    await _store_bars("AAPL", bars, db)
    await db.commit()
    start = date(2024, 1, 2)
    end   = date(2024, 1, 6)
    result = await _read_bars("AAPL", start, end, db)
    assert len(result) == 5
    assert result[0]["time"] == "2024-01-02"
    assert result[-1]["time"] == "2024-01-06"
    # Each dict has the required OHLCV keys
    assert all(k in result[0] for k in ("time", "open", "high", "low", "close", "volume"))


@pytest.mark.asyncio
async def test_read_bars_filters_by_date(db):
    bars = _bars(10)  # 2024-01-02 to 2024-01-11
    await _store_bars("AAPL", bars, db)
    await db.commit()
    result = await _read_bars("AAPL", date(2024, 1, 5), date(2024, 1, 7), db)
    assert len(result) == 3


def test_get_prefetch_status_returns_dict():
    status = get_prefetch_status()
    assert "status" in status
    assert status["status"] in ("idle", "running", "completed", "error")
    assert "total" in status
    assert "done" in status
