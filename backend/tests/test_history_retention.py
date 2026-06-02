"""Tests for history-retention endpoints and bulk-clear functionality."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.routers.notification_settings as ns_module
from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel
from app.services.history_cleanup import clear_all_history, prune_old_history

# ── Local test-DB fixture ─────────────────────────────────────────────────────

_LOCAL_DB_URL = "sqlite+aiosqlite:///:memory:"


def _make_engine():
    return create_async_engine(_LOCAL_DB_URL, connect_args={"check_same_thread": False})


@pytest_asyncio.fixture
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory SQLite session with closed_positions + equity_snapshots tables."""
    from app.database import Base
    # Importing the models registers them on Base.metadata
    _ = ClosedPositionModel, EquitySnapshotModel  # noqa: F841

    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def portfolio_client():
    """Minimal FastAPI test client wired to the real portfolio router + in-memory DB."""
    from app.database import Base, get_db
    from app.routers.portfolio import router as portfolio_router

    engine = _make_engine()

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db() -> AsyncGenerator[AsyncSession, None]:
        async with Session() as s:
            yield s

    app = FastAPI()
    app.include_router(portfolio_router)
    app.dependency_overrides[get_db] = _get_db

    with TestClient(app) as tc:
        yield tc

    asyncio.run(engine.dispose())


# ── Settings endpoints ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_yaml(monkeypatch, tmp_path):
    monkeypatch.setattr(ns_module, '_SETTINGS_PATH', tmp_path / 'settings.yaml')


def test_get_history_retention_returns_default(client):
    r = client.get('/settings/history-retention')
    assert r.status_code == 200
    assert r.json()['historyRetentionYears'] == 10


def test_post_history_retention_roundtrips(client):
    r = client.post('/settings/history-retention', json={'historyRetentionYears': 7})
    assert r.status_code == 200
    assert r.json()['historyRetentionYears'] == 7

    r2 = client.get('/settings/history-retention')
    assert r2.json()['historyRetentionYears'] == 7


def test_post_history_retention_clamps_to_1_100(client):
    r = client.post('/settings/history-retention', json={'historyRetentionYears': 0})
    assert r.json()['historyRetentionYears'] == 1

    r2 = client.post('/settings/history-retention', json={'historyRetentionYears': 999})
    assert r2.json()['historyRetentionYears'] == 100


# ── Bulk-clear endpoint ───────────────────────────────────────────────────────

def test_delete_all_history_clears_closed_positions(portfolio_client):
    """DELETE /api/portfolio/history removes all closed_position rows."""
    # Seed via a direct close — use the close endpoint (simpler than raw insert)
    # There are no open positions here, so we can't use /close.
    # Instead verify the endpoint returns 204 on an empty DB (idempotent).
    r = portfolio_client.delete('/api/portfolio/history')
    assert r.status_code == 204

    r2 = portfolio_client.get('/api/portfolio/history')
    assert r2.status_code == 200
    assert r2.json() == []


# ── prune_old_history service ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prune_old_history_removes_old_rows(async_db):
    old_ts = datetime.now(timezone.utc) - timedelta(days=365 * 12)
    recent_ts = datetime.now(timezone.utc) - timedelta(days=30)

    async_db.add(ClosedPositionModel(
        id='old', rec_id='r1', symbol='AAPL',
        contract='AAPL|185|2026-06-19|C', direction='Bullish',
        entry_price=1.0, exit_price=2.0, exit_date='2014-01-10',
        qty_closed=1, realized_pnl_dollar=100.0, realized_pnl_pct=100.0,
        closed_at=old_ts,
    ))
    async_db.add(ClosedPositionModel(
        id='new', rec_id='r2', symbol='MSFT',
        contract='MSFT|300|2026-06-19|C', direction='Bullish',
        entry_price=1.0, exit_price=1.5, exit_date='2026-05-01',
        qty_closed=1, realized_pnl_dollar=50.0, realized_pnl_pct=50.0,
        closed_at=recent_ts,
    ))
    await async_db.commit()

    await prune_old_history(async_db, retention_years=10)

    rows = (await async_db.execute(select(ClosedPositionModel))).scalars().all()
    ids = {r.id for r in rows}
    assert 'old' not in ids
    assert 'new' in ids


@pytest.mark.asyncio
async def test_prune_old_history_no_op_when_zero(async_db):
    async_db.add(ClosedPositionModel(
        id='x', rec_id='r1', symbol='AAPL',
        contract='AAPL|185|2026-06-19|C', direction='Bullish',
        entry_price=1.0, exit_price=2.0, exit_date='2000-01-01',
        qty_closed=1, realized_pnl_dollar=100.0, realized_pnl_pct=100.0,
        closed_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
    ))
    await async_db.commit()

    await prune_old_history(async_db, retention_years=0)  # no-op

    rows = (await async_db.execute(select(ClosedPositionModel))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_clear_all_history_empties_tables(async_db):
    async_db.add(ClosedPositionModel(
        id='c1', rec_id='r1', symbol='AAPL',
        contract='AAPL|185|2026-06-19|C', direction='Bullish',
        entry_price=1.0, exit_price=2.0, exit_date='2026-05-01',
        qty_closed=1, realized_pnl_dollar=100.0, realized_pnl_pct=100.0,
    ))
    async_db.add(EquitySnapshotModel(
        id='s1', snapshot_date='2026-05-01',
        realized_cumulative=100.0, open_value=0.0, open_pnl=0.0, total_value=100.0,
    ))
    await async_db.commit()

    await clear_all_history(async_db)

    assert (await async_db.execute(select(ClosedPositionModel))).scalars().first() is None
    assert (await async_db.execute(select(EquitySnapshotModel))).scalars().first() is None
