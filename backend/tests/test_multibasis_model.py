"""Smoke test: OhlcvDailyModel has multi-basis columns after migration."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    yield eng
    await eng.dispose()

@pytest.mark.asyncio
async def test_model_has_multibasis_columns(engine):
    cols = {c.key for c in OhlcvDailyModel.__table__.columns}
    assert "adj_factor"   in cols
    assert "split_factor" in cols
    assert "div_cash"     in cols
    assert "source"       in cols

@pytest.mark.asyncio
async def test_multibasis_columns_are_nullable(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        from datetime import date
        row = OhlcvDailyModel(
            symbol="TEST", date=date(2024, 1, 2),
            open=100, high=101, low=99, close=100.5, volume=1000,
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        assert row.adj_factor is None
        assert row.source is None
