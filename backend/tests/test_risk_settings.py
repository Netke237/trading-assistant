"""Tests for GET/POST /settings/risk."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_get_risk_settings_returns_premium_stop():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.get('/settings/risk')
    assert resp.status_code == 200
    data = resp.json()
    assert 'premiumStopPct' in data
    assert isinstance(data['premiumStopPct'], float)
    assert 0.0 < data['premiumStopPct'] <= 1.0


@pytest.mark.asyncio
async def test_post_risk_settings_updates_premium_stop(tmp_path, monkeypatch):
    # Point the router at a temp yaml so we don't mutate the real config.
    import app.routers.risk_settings as rs
    fake_yaml = tmp_path / 'risk_rules.yaml'
    fake_yaml.write_text(
        'portfolio:\n  max_concurrent_positions: 10\n'
        'reward_risk:\n  premium_stop_pct: 0.60\n'
    )
    monkeypatch.setattr(rs, '_RISK_PATH', fake_yaml)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.post('/settings/risk', json={'premiumStopPct': 0.50})
    assert resp.status_code == 200
    assert resp.json()['premiumStopPct'] == 0.50

    import yaml
    saved = yaml.safe_load(fake_yaml.read_text())
    assert saved['reward_risk']['premium_stop_pct'] == 0.50


@pytest.mark.asyncio
async def test_get_risk_settings_returns_target_pcts():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.get('/settings/risk')
    assert resp.status_code == 200
    data = resp.json()
    for key in ('targetT1Pct', 'targetT2Pct', 'targetT3Pct'):
        assert key in data
        assert isinstance(data[key], float)
    assert data['targetT1Pct'] <= data['targetT2Pct'] <= data['targetT3Pct']


@pytest.mark.asyncio
async def test_post_risk_settings_updates_target_pcts(tmp_path, monkeypatch):
    import app.routers.risk_settings as rs
    fake_yaml = tmp_path / 'risk_rules.yaml'
    fake_yaml.write_text(
        'portfolio:\n  max_concurrent_positions: 10\n'
        'reward_risk:\n  premium_stop_pct: 0.60\n'
    )
    monkeypatch.setattr(rs, '_RISK_PATH', fake_yaml)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.post('/settings/risk', json={
            'premiumStopPct': 0.60, 'targetT1Pct': 0.15, 'targetT2Pct': 0.30, 'targetT3Pct': 0.45,
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body['targetT1Pct'] == 0.15
    assert body['targetT2Pct'] == 0.30
    assert body['targetT3Pct'] == 0.45

    import yaml
    saved = yaml.safe_load(fake_yaml.read_text())
    assert saved['reward_risk']['target_t1_pct'] == 0.15
    assert saved['reward_risk']['target_t2_pct'] == 0.30
    assert saved['reward_risk']['target_t3_pct'] == 0.45


@pytest.mark.asyncio
async def test_post_risk_settings_rejects_out_of_order_targets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.post('/settings/risk', json={
            'premiumStopPct': 0.60, 'targetT1Pct': 0.50, 'targetT2Pct': 0.35, 'targetT3Pct': 0.20,
        })
    assert resp.status_code == 422
