"""Tests for GET/POST /settings/risk."""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services import portfolio_risk


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
async def test_max_single_position_pct_is_actually_enforced(tmp_path, monkeypatch):
    """Regression test for the bug where `maxSinglePositionPct` (the setting the
    UI writes) and `max_single_trade_exposure_pct` (the key check_position_risk
    read) were two different, independently-drifting keys — saving the setting
    had zero effect on enforcement. Post a tightened maxSinglePositionPct via the
    settings endpoint, then confirm check_position_risk actually enforces it.
    """
    import app.routers.risk_settings as rs

    fake_yaml = tmp_path / 'risk_rules.yaml'
    fake_yaml.write_text(
        'portfolio:\n'
        '  max_concurrent_positions: 10\n'
        '  max_daily_recommendations: 5\n'
        '  max_same_symbol_positions: 1\n'
        '  min_portfolio_value: 5000.0\n'
        '  portfolio_value: 100000.0\n'
        '  max_total_exposure_pct: 0.25\n'
        '  max_single_position_pct: 0.05\n'
        'sizing:\n'
        '  default_contracts: 1\n'
        '  max_contracts_per_trade: 5\n'
        'reward_risk:\n'
        '  premium_stop_pct: 0.60\n'
    )
    # Point both the router and the enforcement module at the same temp file
    # so the test exercises the real end-to-end path: POST /settings/risk ->
    # yaml write -> cache clear -> check_position_risk reads the new value.
    monkeypatch.setattr(rs, '_RISK_PATH', fake_yaml)
    monkeypatch.setattr(portfolio_risk, 'CONFIG_PATH', fake_yaml)
    portfolio_risk._load_config.cache_clear()

    from app.services.portfolio_risk import check_position_risk

    try:
        # A trade sized so it fits under the default 5% single-position limit
        # but breaches a tightened 1% limit.
        request_kwargs = dict(
            symbol='TSLA',
            contract_id='TSLA|250|2026-05-16|C',
            proposed_contracts=1,
            entry_premium=20.0,
            current_price=20.0,
            portfolio=[],
            portfolio_value=100_000.0,
            daily_recommendation_count=0,
        )
        # capital_at_risk = 20 * 1 * 100 = 2_000 -> 2% of 100_000, passes the
        # 5% default
        baseline = check_position_risk(**request_kwargs)
        assert baseline.approved is True
        assert baseline.reasons == []

        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
            resp = await ac.post('/settings/risk', json={
                'premiumStopPct': 0.60,
                'maxSinglePositionPct': 0.01,
            })
        assert resp.status_code == 200
        assert resp.json()['maxSinglePositionPct'] == 0.01

        import yaml
        saved = yaml.safe_load(fake_yaml.read_text())
        assert saved['portfolio']['max_single_position_pct'] == 0.01

        # Same trade should now be rejected/reduced at the tightened 1% limit —
        # 2% exposure > 1% max, and 1_000 max premium / (20*100) = 0 contracts,
        # so it cannot even be size-reduced to a valid smaller quantity.
        tightened = check_position_risk(**request_kwargs)
        assert tightened.approved is False
        assert 'single_trade_exposure_too_high' in tightened.reasons
    finally:
        # The lru_cache holds the loaded dict independently of monkeypatch's
        # attribute restore — without this, the temp-file config (with the
        # 1% override) leaks into every other test in the session that calls
        # check_position_risk after this one runs.
        portfolio_risk._load_config.cache_clear()


@pytest.mark.asyncio
async def test_get_risk_settings_returns_max_loss_per_trade_pct():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.get('/settings/risk')
    assert resp.status_code == 200
    data = resp.json()
    assert 'maxLossPerTradePct' in data
    assert isinstance(data['maxLossPerTradePct'], float)
    assert 0.0 <= data['maxLossPerTradePct'] <= 1.0


@pytest.mark.asyncio
async def test_post_risk_settings_updates_max_loss_per_trade_pct(tmp_path, monkeypatch):
    import app.routers.risk_settings as rs
    fake_yaml = tmp_path / 'risk_rules.yaml'
    fake_yaml.write_text(
        'portfolio:\n  max_concurrent_positions: 10\n  max_loss_per_trade_pct: 0.0375\n'
        'reward_risk:\n  premium_stop_pct: 0.60\n'
    )
    monkeypatch.setattr(rs, '_RISK_PATH', fake_yaml)

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.post('/settings/risk', json={
            'premiumStopPct': 0.60, 'maxLossPerTradePct': 0.02,
        })
    assert resp.status_code == 200
    assert resp.json()['maxLossPerTradePct'] == 0.02

    import yaml
    saved = yaml.safe_load(fake_yaml.read_text())
    assert saved['portfolio']['max_loss_per_trade_pct'] == 0.02


@pytest.mark.asyncio
async def test_post_risk_settings_rejects_out_of_order_targets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as ac:
        resp = await ac.post('/settings/risk', json={
            'premiumStopPct': 0.60, 'targetT1Pct': 0.50, 'targetT2Pct': 0.35, 'targetT3Pct': 0.20,
        })
    assert resp.status_code == 422
