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


def test_prefetch_warms_both_options_and_stock_cache_keys(monkeypatch):
    """The Load History prefetch job must warm BOTH the live options-path's cache key
    (atr_mult=1.5, scoring_mode='options' — the prefetch's pre-existing, correct
    behavior) AND the live stocks-path's cache key (atr_mult=None -> 'default'
    sentinel, scoring_mode='stock' — the bug this task fixes). Repointing the
    prefetch entirely to scoring_mode='stock' would silently regress the
    options path's warm-cache hit while fixing the stocks path — this test
    guards against that regression, not just the original bug."""
    import tempfile
    import os
    import app.data.confidence_cache as cc
    from app.services import historical_store as hs
    from unittest.mock import AsyncMock

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original_db_path = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc.clear_cache()

        seen_kwargs = []

        def _fake_compute_confidence(bars, **kwargs):
            seen_kwargs.append(kwargs)
            return type("R", (), {"confidence": 55, "sample_size": 40})()

        fake_bars = [{"time": f"2024-01-{i:02d}", "close": 100.0 + i} for i in range(1, 200)]

        monkeypatch.setattr(hs, "compute_confidence", _fake_compute_confidence)
        monkeypatch.setattr(hs, "get_bars", AsyncMock(return_value=fake_bars))

        asyncio.run(hs._run_prefetch(["AAPL"], years=1, delay_secs=0))

        assert seen_kwargs, "compute_confidence was never called — check the monkeypatch target"
        stock_calls = [kw for kw in seen_kwargs if kw.get("scoring_mode") == "stock"]
        options_calls = [kw for kw in seen_kwargs if kw.get("scoring_mode") != "stock"]
        assert stock_calls, "prefetch never computed a scoring_mode='stock' variant"
        assert options_calls, "prefetch stopped computing the options-path variant — regression"

        # Both live paths' actual key shapes must be warmed.
        stock_key = cc.cache_key("AAPL", "Bullish", "Swing", None, scoring_mode="stock")
        options_key = cc.cache_key("AAPL", "Bullish", "Swing", 1.5, scoring_mode="options")
        assert cc.get_cached(stock_key) is not None, "stocks-path key was not warmed"
        assert cc.get_cached(options_key) is not None, "options-path key was not warmed (regression)"
    finally:
        cc._DB_PATH = original_db_path
        os.unlink(db_path)
