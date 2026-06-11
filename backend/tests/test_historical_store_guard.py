"""Guard tests: _store_bars writes multi-basis fields; _read_bars returns adjusted prices."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase
from app.services.historical_store import _read_bars, _store_bars


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_store_bars_writes_multi_basis_fields(session):
    bars = [{
        "time": "2024-01-02",
        "open": 185.0, "high": 186.0, "low": 184.0, "close": 185.5,
        "volume": 1_000_000,
        "adj_factor": 1.025, "split_factor": 1.0, "div_cash": 0.0, "source": "alpaca",
    }]
    await _store_bars("AAPL", bars, session)
    await session.commit()

    from sqlalchemy import select
    from app.models.ohlcv_daily import OhlcvDailyModel
    result = await session.execute(select(OhlcvDailyModel).where(OhlcvDailyModel.symbol == "AAPL"))
    row = result.scalars().first()
    assert row is not None
    assert float(row.close) == 185.5
    assert abs(float(row.adj_factor) - 1.025) < 1e-6
    assert row.source == "alpaca"


@pytest.mark.asyncio
async def test_read_bars_returns_adjusted_close(session):
    bars = [{
        "time": "2024-01-02",
        "open": 98.0, "high": 102.0, "low": 97.0, "close": 100.0,
        "volume": 500_000,
        "adj_factor": 1.1, "split_factor": 1.0, "div_cash": 0.0, "source": "tiingo",
    }]
    await _store_bars("TSLA", bars, session)
    await session.commit()

    result = await _read_bars("TSLA", date(2024, 1, 1), date(2024, 1, 31), session)
    assert len(result) == 1
    assert abs(result[0]["close"] - 110.0) < 0.01   # 100 × 1.1


@pytest.mark.asyncio
async def test_read_bars_legacy_row_uses_close_directly(session):
    bars = [{
        "time": "2023-01-03",
        "open": 130.0, "high": 131.0, "low": 129.0, "close": 130.5,
        "volume": 800_000,
        # no multi-basis keys → adj_factor stored as NULL
    }]
    await _store_bars("AAPL", bars, session)
    await session.commit()

    result = await _read_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31), session)
    assert len(result) == 1
    assert result[0]["close"] == 130.5   # no multiplication for NULL adj_factor
