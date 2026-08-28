# backend/tests/test_symbol_notes.py
"""CRUD tests for /api/notes — mirroring test_chart_drawings.py's harness."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.symbol_note import SymbolNoteModel  # noqa: F401 — registers table with Base.metadata

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.symbol_notes import router as symbol_notes_router

    app = FastAPI()
    app.include_router(symbol_notes_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_get_note_missing_returns_empty_placeholder():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.get('/api/notes/AAPL')
        assert resp.status_code == 200
        data = resp.json()
        assert data == {'symbol': 'AAPL', 'body': '', 'updatedAt': None}


@pytest.mark.asyncio
async def test_upsert_then_get_note():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.put('/api/notes/aapl', json={'body': 'Watching for a breakout above 200.'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['symbol'] == 'AAPL'
        assert data['body'] == 'Watching for a breakout above 200.'
        assert data['updatedAt'] is not None

        resp2 = await client.get('/api/notes/AAPL')
        assert resp2.status_code == 200
        assert resp2.json()['body'] == 'Watching for a breakout above 200.'


@pytest.mark.asyncio
async def test_upsert_overwrites_existing_note():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.put('/api/notes/TSLA', json={'body': 'first draft'})
        resp = await client.put('/api/notes/TSLA', json={'body': 'revised note'})
        assert resp.status_code == 200
        assert resp.json()['body'] == 'revised note'

        resp2 = await client.get('/api/notes/TSLA')
        assert resp2.json()['body'] == 'revised note'


@pytest.mark.asyncio
async def test_upsert_empty_body_clears_note():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.put('/api/notes/MSFT', json={'body': 'something'})
        resp = await client.put('/api/notes/MSFT', json={'body': ''})
        assert resp.status_code == 200
        assert resp.json()['body'] == ''


@pytest.mark.asyncio
async def test_put_uppercase_then_get_lowercase_symbol():
    """The reverse of test_upsert_then_get_note's case-fold direction —
    upserting with an already-uppercase symbol must still be found by a
    lowercase GET."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.put('/api/notes/NVDA', json={'body': 'earnings next week'})
        resp = await client.get('/api/notes/nvda')
        assert resp.status_code == 200
        assert resp.json() == {'symbol': 'NVDA', 'body': 'earnings next week', 'updatedAt': resp.json()['updatedAt']}


# A genuine asyncio.gather()'d pair of concurrent PUTs is deliberately NOT
# tested at the HTTP layer here: this test module's engine (like every other
# router test in this suite) is `sqlite+aiosqlite:///:memory:`, which
# SQLAlchemy serves off a single shared connection (StaticPool) — two
# "concurrent" AsyncSession objects awaiting on that one connection at once
# don't reproduce the real Postgres/asyncpg race (each request its own
# connection), they produce unrelated cross-session transaction interference.
# test_insert_race_mechanics_are_recoverable_on_sqlite below instead drives
# the exact interleaving upsert_note's IntegrityError branch exists to
# handle, deterministically, without depending on asyncio scheduling luck
# or a test double for the real concurrency behavior.


@pytest.mark.asyncio
async def test_insert_race_mechanics_are_recoverable_on_sqlite():
    """Lower-level check that the exact interleaving upsert_note's
    IntegrityError branch exists to handle — session A reads no row, session
    B wins the insert first, session A's own insert then collides — is both
    real (aiosqlite does raise IntegrityError here) and recoverable via
    rollback + re-fetch + update, driven deterministically rather than
    depending on asyncio scheduling (see the comment above for why an
    HTTP-level asyncio.gather() test isn't reliable against this module's
    single-shared-connection sqlite test harness)."""
    from app.database import Base
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.symbol_note import SymbolNoteModel

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc)
    async with Session() as session_a, Session() as session_b:
        assert await session_a.get(SymbolNoteModel, 'RACE2') is None
        assert await session_b.get(SymbolNoteModel, 'RACE2') is None

        session_b.add(SymbolNoteModel(symbol='RACE2', body='winner', updated_at=now))
        await session_b.commit()

        session_a.add(SymbolNoteModel(symbol='RACE2', body='loser', updated_at=now))
        with pytest.raises(IntegrityError):
            await session_a.commit()
        await session_a.rollback()

        row = await session_a.get(SymbolNoteModel, 'RACE2')
        assert row is not None
        row.body = 'loser'
        await session_a.commit()

    async with Session() as verify:
        final = await verify.get(SymbolNoteModel, 'RACE2')
        assert final.body == 'loser'
