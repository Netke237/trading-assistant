# backend/tests/test_chart_drawings.py
"""CRUD tests for /chart/drawings — mirroring test_alert_router.py harness."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.drawing import DrawingModel  # noqa: F401 — registers table with Base.metadata

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_drawings import router as chart_drawings_router

    app = FastAPI()
    app.include_router(chart_drawings_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_create_list_delete_drawing():
    app = await _make_app()
    payload = {
        'id': 'd1',
        'symbol': 'AAPL',
        'interval': '1D',
        'kind': 'hline',
        'points': [{'time': 0, 'price': 150.0}],
        'color': '#fff',
        'width': 1,
        'createdAt': '2026-06-04T00:00:00Z',
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        # POST → 200 or 201
        resp = await client.post('/chart/drawings', json=payload)
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()
        assert data['id'] == 'd1'
        assert data['symbol'] == 'AAPL'

        # GET ?symbol=AAPL&interval=1D → drawing is present
        resp2 = await client.get('/chart/drawings', params={'symbol': 'AAPL', 'interval': '1D'})
        assert resp2.status_code == 200
        drawings = resp2.json()
        assert any(d['id'] == 'd1' for d in drawings)

        # DELETE → 200 or 204
        resp3 = await client.delete('/chart/drawings/d1')
        assert resp3.status_code in (200, 204), resp3.text

        # Confirm gone
        resp4 = await client.get('/chart/drawings', params={'symbol': 'AAPL', 'interval': '1D'})
        assert resp4.status_code == 200
        assert not any(d['id'] == 'd1' for d in resp4.json())


@pytest.mark.asyncio
async def test_upsert_updates_existing():
    """POSTing the same id twice should update in place (upsert)."""
    app = await _make_app()
    payload = {
        'id': 'd2',
        'symbol': 'TSLA',
        'interval': '1H',
        'kind': 'trendline',
        'points': [{'time': 100, 'price': 200.0}, {'time': 200, 'price': 210.0}],
        'color': '#f00',
        'width': 2,
        'createdAt': '2026-06-04T00:00:00Z',
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp1 = await client.post('/chart/drawings', json=payload)
        assert resp1.status_code in (200, 201)

        # Upsert with changed color
        updated = {**payload, 'color': '#0f0'}
        resp2 = await client.post('/chart/drawings', json=updated)
        assert resp2.status_code in (200, 201)
        assert resp2.json()['color'] == '#0f0'

        # Only one row
        resp3 = await client.get('/chart/drawings', params={'symbol': 'TSLA', 'interval': '1H'})
        assert len(resp3.json()) == 1


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_404():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.delete('/chart/drawings/no-such-id')
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_filters_by_symbol_and_interval():
    app = await _make_app()
    drawings = [
        {'id': 'x1', 'symbol': 'AAPL', 'interval': '1D', 'kind': 'hline',
         'points': [{'time': 1, 'price': 100.0}], 'color': '#aaa', 'width': 1, 'createdAt': '2026-06-04T00:00:00Z'},
        {'id': 'x2', 'symbol': 'AAPL', 'interval': '1H', 'kind': 'hline',
         'points': [{'time': 2, 'price': 200.0}], 'color': '#bbb', 'width': 1, 'createdAt': '2026-06-04T00:00:00Z'},
        {'id': 'x3', 'symbol': 'TSLA', 'interval': '1D', 'kind': 'hline',
         'points': [{'time': 3, 'price': 300.0}], 'color': '#ccc', 'width': 1, 'createdAt': '2026-06-04T00:00:00Z'},
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for d in drawings:
            await client.post('/chart/drawings', json=d)

        resp = await client.get('/chart/drawings', params={'symbol': 'AAPL', 'interval': '1D'})
        ids = [d['id'] for d in resp.json()]
        assert ids == ['x1']
