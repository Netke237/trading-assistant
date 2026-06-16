"""Integration tests for fundamentals_store — in-memory SQLite via monkeypatching."""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.fundamentals import FundamentalsModel


# ── In-memory DB fixture ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_model(symbol: str = "AAPL", *, fetched_at=None, **overrides) -> FundamentalsModel:
    defaults: dict = dict(
        symbol=symbol,
        fiscal_period_end=date(2023, 9, 30),
        filed_date=date(2023, 11, 3),
        cik="0000320193",
        revenue=Decimal("383285000000"),
        net_income=Decimal("96995000000"),
        eps_diluted=Decimal("6.13"),
        gross_profit=Decimal("169148000000"),
        operating_income=Decimal("114301000000"),
        op_cash_flow=Decimal("110543000000"),
        capex=Decimal("10959000000"),
        total_debt=Decimal("95000000000"),
        stockholders_eq=Decimal("62146000000"),
        current_assets=Decimal("143566000000"),
        current_liab=Decimal("145308000000"),
        shares_diluted=Decimal("15697000000"),
        revenue_growth_yoy=-0.028,
        eps_growth_yoy=0.013,
        share_growth_yoy=-0.037,
        source="sec_edgar",
        fetched_at=fetched_at or datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return FundamentalsModel(**defaults)


# ── Pure-function tests (no DB needed) ────────────────────────────────────────

def test_row_to_snapshot_preserves_growth_rates():
    """Cache hit must not zero out growth rates stored in the DB row."""
    from app.services.fundamentals_store import _row_to_snapshot

    row = _make_model(revenue_growth_yoy=-0.028, eps_growth_yoy=0.013, share_growth_yoy=-0.037)
    snap = _row_to_snapshot(row)

    assert snap.revenue_growth_yoy == pytest.approx(-0.028)
    assert snap.eps_growth_yoy == pytest.approx(0.013)
    assert snap.share_growth_yoy == pytest.approx(-0.037)


def test_row_to_snapshot_none_growth_stays_none():
    """NULL growth columns (legacy rows) must round-trip as None, not 0."""
    from app.services.fundamentals_store import _row_to_snapshot

    row = _make_model(revenue_growth_yoy=None, eps_growth_yoy=None, share_growth_yoy=None)
    snap = _row_to_snapshot(row)

    assert snap.revenue_growth_yoy is None
    assert snap.eps_growth_yoy is None
    assert snap.share_growth_yoy is None


def test_row_to_snapshot_recomputes_margins():
    """Margins are computed from stored raw fields, not fetched from a 'margin' column."""
    from app.services.fundamentals_store import _row_to_snapshot

    row = _make_model()
    snap = _row_to_snapshot(row)

    assert snap.gross_margin == pytest.approx(169148000000 / 383285000000, rel=1e-4)
    assert snap.current_ratio == pytest.approx(143566000000 / 145308000000, rel=1e-4)


def test_snapshot_to_model_stores_growth_rates():
    """Growth rates computed at EDGAR fetch time must be persisted to DB."""
    from app.services.fundamentals_store import _snapshot_to_model
    from app.data.edgar import FundamentalsSnapshot

    snap = FundamentalsSnapshot(
        symbol="AAPL",
        fiscal_period_end=date(2023, 9, 30),
        filed_date=date(2023, 11, 3),
        cik="0000320193",
        revenue_growth_yoy=-0.028,
        eps_growth_yoy=0.013,
        share_growth_yoy=-0.037,
    )
    model = _snapshot_to_model(snap)

    assert model.revenue_growth_yoy == pytest.approx(-0.028)
    assert model.eps_growth_yoy == pytest.approx(0.013)
    assert model.share_growth_yoy == pytest.approx(-0.037)
    assert model.source == "sec_edgar"


# ── DB-layer tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_fundamentals_cache_hit_skips_edgar(session_factory):
    """Fresh DB row must short-circuit; EDGAR must not be called."""
    import app.services.fundamentals_store as store

    async with session_factory() as s:
        s.add(_make_model(fetched_at=datetime.now(timezone.utc)))
        await s.commit()

    edgar_calls: list[str] = []

    async def _fake_to_thread(fn, *args, **kwargs):
        edgar_calls.append(args[0] if args else "unknown")
        return None

    with patch.object(store, "AsyncSessionLocal", session_factory), \
         patch("app.services.fundamentals_store.asyncio.to_thread", side_effect=_fake_to_thread):
        snap = await store.get_fundamentals("AAPL")

    assert snap is not None, "fresh row should be returned"
    assert snap.revenue_growth_yoy == pytest.approx(-0.028)
    assert edgar_calls == [], "EDGAR must not be called on fresh cache hit"


@pytest.mark.asyncio
async def test_get_fundamentals_stale_row_calls_edgar(session_factory):
    """Row older than staleness_days must trigger an EDGAR re-fetch."""
    import app.services.fundamentals_store as store

    stale_time = datetime.now(timezone.utc) - timedelta(days=100)
    async with session_factory() as s:
        s.add(_make_model(fetched_at=stale_time))
        await s.commit()

    edgar_calls: list[str] = []

    async def _fake_to_thread(fn, symbol):
        edgar_calls.append(symbol)
        return None  # EDGAR returns nothing

    with patch.object(store, "AsyncSessionLocal", session_factory), \
         patch("app.services.fundamentals_store.asyncio.to_thread", side_effect=_fake_to_thread):
        result = await store.get_fundamentals("AAPL")

    assert "AAPL" in edgar_calls, "stale row must trigger EDGAR fetch"
    assert result is None


@pytest.mark.asyncio
async def test_get_fundamentals_upserts_on_miss(session_factory):
    """Cache miss should upsert fresh data and return the snapshot."""
    import app.services.fundamentals_store as store
    from app.data.edgar import FundamentalsSnapshot

    fresh_snap = FundamentalsSnapshot(
        symbol="MSFT",
        fiscal_period_end=date(2023, 6, 30),
        filed_date=date(2023, 8, 1),
        cik="0000789019",
        revenue_growth_yoy=0.07,
        eps_growth_yoy=0.12,
        share_growth_yoy=-0.01,
    )

    async def _fake_to_thread(fn, symbol):
        return fresh_snap

    with patch.object(store, "AsyncSessionLocal", session_factory), \
         patch("app.services.fundamentals_store.asyncio.to_thread", side_effect=_fake_to_thread):
        result = await store.get_fundamentals("MSFT")

    assert result is not None
    assert result.symbol == "MSFT"
    assert result.revenue_growth_yoy == pytest.approx(0.07)

    # Verify row was persisted
    async with session_factory() as s:
        row = (await s.execute(
            select(FundamentalsModel).where(FundamentalsModel.symbol == "MSFT")
        )).scalar_one_or_none()
    assert row is not None
    assert row.revenue_growth_yoy == pytest.approx(0.07)
    assert row.source == "sec_edgar"
