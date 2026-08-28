# backend/tests/test_symbol_notes.py
"""CRUD tests for /api/notes — mirroring test_chart_drawings.py's harness."""
from __future__ import annotations

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
