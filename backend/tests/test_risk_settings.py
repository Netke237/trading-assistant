"""Tests for GET/POST /settings/risk."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_get_risk_settings_returns_premium_stop():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.get('/api/settings/risk')
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
        resp = await ac.post('/api/settings/risk', json={'premiumStopPct': 0.50})
    assert resp.status_code == 200
    assert resp.json()['premiumStopPct'] == 0.50
