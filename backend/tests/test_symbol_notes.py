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
# connection), they produce unrelated cross-session transaction interference,
# not the race itself.
#
# test_upsert_note_recovers_when_insert_races_an_existing_row below instead
# calls upsert_note directly and forces the exact interleaving its
# IntegrityError branch exists to handle — this session's own read seeing no
# row despite one already existing, exactly what a genuinely concurrent
# request's SELECT would have seen before either INSERT committed — via a
# one-shot monkeypatch of AsyncSession.get, rather than hand-reproducing an
# equivalent sequence next to the router's real code.


@pytest.mark.asyncio
async def test_upsert_note_recovers_when_insert_races_an_existing_row():
    """Exercises upsert_note's own IntegrityError-retry branch directly."""
    from unittest.mock import patch
    from app.database import Base
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.symbol_note import SymbolNoteModel
    from app.routers.symbol_notes import upsert_note, NoteIn

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Simulate "another request already won the race": a row committed via
    # an independent session, before the session under test ever queries.
    async with Session() as winner_session:
        winner_session.add(SymbolNoteModel(symbol='RACE2', body='winner', updated_at=datetime.now(timezone.utc)))
        await winner_session.commit()

    async with Session() as db:
        real_get = AsyncSession.get
        first_call = {'seen': False}

        async def get_none_on_first_call(self, *args, **kwargs):
            # upsert_note's OWN db.get() call — the one whose real-world
            # equivalent raced the winner's insert and lost — is forced to
            # see nothing, exactly as it would have under true concurrency.
            # Every other call on this session (the retry branch's re-fetch,
            # the final db.refresh()) behaves normally.
            if not first_call['seen']:
                first_call['seen'] = True
                return None
            return await real_get(self, *args, **kwargs)

        with patch.object(AsyncSession, 'get', get_none_on_first_call):
            result = await upsert_note('RACE2', NoteIn(body='loser'), db)

    assert result['body'] == 'loser'

    async with Session() as verify:
        final = await verify.get(SymbolNoteModel, 'RACE2')
        assert final.body == 'loser'
