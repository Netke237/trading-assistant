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
async def test_read_bars_returns_adjusted_ohlc(session):
    """All four prices are scaled by adj_factor, not only close (Phase C T1, review H1)."""
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
    bar = result[0]
    assert abs(bar["open"] - 107.8) < 1e-6    # 98 × 1.1
    assert abs(bar["high"] - 112.2) < 1e-6    # 102 × 1.1
    assert abs(bar["low"] - 106.7) < 1e-6     # 97 × 1.1
    assert abs(bar["close"] - 110.0) < 1e-6   # 100 × 1.1


@pytest.mark.asyncio
@pytest.mark.parametrize("adj_factor", [0.5, 0.97, 1.0, 1.1, 8.0])
async def test_read_bars_basis_invariant(session, adj_factor):
    """Every returned bar keeps open and close inside its own [low, high]."""
    bars = [{
        "time": "2024-03-01",
        "open": 98.0, "high": 102.0, "low": 97.0, "close": 100.0,
        "volume": 400_000,
        "adj_factor": adj_factor, "split_factor": 1.0, "div_cash": 0.0, "source": "tiingo",
    }]
    await _store_bars("MSFT", bars, session)
    await session.commit()

    result = await _read_bars("MSFT", date(2024, 3, 1), date(2024, 3, 31), session)
    assert len(result) == 1
    for bar in result:
        assert bar["low"] <= min(bar["open"], bar["close"])
        assert max(bar["open"], bar["close"]) <= bar["high"]


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
    # NULL adj_factor: all four prices are returned raw, no multiplication.
    assert result[0]["open"] == 130.0
    assert result[0]["high"] == 131.0
    assert result[0]["low"] == 129.0
    assert result[0]["close"] == 130.5


@pytest.mark.asyncio
async def test_read_bars_volume_unscaled(session):
    """Volume stays raw (decision D3) even when adj_factor != 1."""
    bars = [{
        "time": "2024-01-02",
        "open": 98.0, "high": 102.0, "low": 97.0, "close": 100.0,
        "volume": 500_000,
        "adj_factor": 1.1, "split_factor": 1.0, "div_cash": 0.0, "source": "tiingo",
    }]
    await _store_bars("NVDA", bars, session)
    await session.commit()

    result = await _read_bars("NVDA", date(2024, 1, 1), date(2024, 1, 31), session)
    assert len(result) == 1
    assert result[0]["volume"] == 500_000
