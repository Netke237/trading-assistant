# backend/tests/test_alert_router.py
from __future__ import annotations
import pytest
from datetime import datetime
from httpx import AsyncClient, ASGITransport


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router

    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_create_rule():
    app = await _make_app()
    body = {
        'name': 'Test Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100.0}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'Test Rule'
        assert data['symbol'] == 'AAPL'
        assert 'id' in data
        assert 'created_at' in data

        resp2 = await client.get('/alerts/rules')
        assert resp2.status_code == 200
        rules = resp2.json()
        assert len(rules) == 1


@pytest.mark.asyncio
async def test_update_rule():
    app = await _make_app()
    body = {
        'name': 'Original', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        update = {**body, 'name': 'Updated', 'enabled': False}
        resp2 = await client.put(f'/alerts/rules/{rule_id}', json=update)
        assert resp2.status_code == 200
        assert resp2.json()['name'] == 'Updated'
        assert resp2.json()['enabled'] is False


@pytest.mark.asyncio
async def test_delete_rule_cascades_history():
    app = await _make_app()
    body = {
        'name': 'ToDelete', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        history_body = {
            'rule_id': rule_id, 'symbol': 'AAPL', 'interval': '15min',
            'triggered_at': datetime.now().isoformat(),
            'candle': {'time': '2024-01-02T09:30', 'open': 100, 'high': 105, 'low': 99, 'close': 103, 'volume': 1000},
            'trigger_values': {'close': 103}, 'reason': 'Test trigger',
        }
        resp2 = await client.post('/alerts/history', json=history_body)
        assert resp2.status_code == 201

        resp3 = await client.delete(f'/alerts/rules/{rule_id}')
        assert resp3.status_code == 204

        resp4 = await client.get('/alerts/history')
        assert resp4.status_code == 200
        assert len(resp4.json()) == 0


@pytest.mark.asyncio
async def test_list_history_filtered_by_symbol():
    app = await _make_app()
    body = {
        'name': 'Rule1', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        for sym in ['AAPL', 'TSLA']:
            await client.post('/alerts/history', json={
                'rule_id': rule_id, 'symbol': sym, 'interval': '15min',
                'triggered_at': datetime.now().isoformat(),
                'candle': {'time': '2024-01-02T09:30', 'open': 100, 'high': 105, 'low': 99, 'close': 103, 'volume': 1000},
                'trigger_values': {'close': 103}, 'reason': 'Test',
            })

        resp2 = await client.get('/alerts/history', params={'symbol': 'AAPL'})
        assert resp2.status_code == 200
        data = resp2.json()
        assert len(data) == 1
        assert data[0]['symbol'] == 'AAPL'


@pytest.mark.asyncio
async def test_test_endpoint_returns_matches():
    app = await _make_app()
    body = {
        'name': 'Test Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        candles = [
            {'time': '2024-01-02T09:00', 'open': 95, 'high': 98, 'low': 94, 'close': 97, 'volume': 800},
            {'time': '2024-01-02T09:15', 'open': 98, 'high': 103, 'low': 97, 'close': 102, 'volume': 1200},
        ]
        resp2 = await client.post(f'/alerts/rules/{rule_id}/test', json={
            'candles': candles, 'indicators': {}, 'signals': [],
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert 'matches' in data


@pytest.mark.asyncio
async def test_regime_condition_round_trips_through_test_endpoint():
    """A saved regime condition must survive deserialization (previously silently
    dropped) and evaluate against real regime data built from the test candles."""
    app = await _make_app()
    body = {
        'name': 'Regime Rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
        'group': {'logic': 'AND', 'conditions': [
            {'kind': 'regime', 'model': 'OMM', 'state': 'any'},
        ]},
        'cooldown_minutes': 60, 'expiry_date': None,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/alerts/rules', json=body)
        rule_id = resp.json()['id']

        # 150 bars of a clear uptrend — enough for build_regime_snapshot's OMM branch to populate.
        candles = [
            {'time': f'2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T09:30',
             'open': 100 + i * 0.5, 'high': 101 + i * 0.5,
             'low': 99 + i * 0.5, 'close': 100 + i * 0.5, 'volume': 1000}
            for i in range(150)
        ]
        resp2 = await client.post(f'/alerts/rules/{rule_id}/test', json={
            'candles': candles, 'indicators': {}, 'signals': [],
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert len(data['matches']) >= 1
        assert len(data['matches']) >= 1
