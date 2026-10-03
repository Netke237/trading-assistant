import pytest
from app.services import portfolio_risk


def test_missing_account_defaults_to_100000():
    assert portfolio_risk.account_value({}) == 100000


@pytest.mark.parametrize('value', [True, False, None, '10000', float('nan'), float('inf'), float('-inf'), 0, -1])
def test_explicit_invalid_account_refuses(value):
    with pytest.raises(portfolio_risk.AccountValueError):
        portfolio_risk.account_value({'portfolio': {'portfolio_value': value}})


def test_account_reads_current_server_config(monkeypatch):
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: {'portfolio': {'portfolio_value': 10000}})
    assert portfolio_risk.account_value() == 10000


def test_unreadable_account_refuses(monkeypatch):
    def unreadable():
        raise OSError('unreadable')
    monkeypatch.setattr(portfolio_risk, '_load_config', unreadable)
    with pytest.raises(portfolio_risk.AccountValueError):
        portfolio_risk.account_value()

@pytest.mark.parametrize('endpoint', ['stock', 'option'])
def test_manual_open_refuses_invalid_account_but_close_bypasses(endpoint, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_broker_idempotency import _make_app, _mock_router
    from app.routers import broker
    router = _mock_router()
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: router)
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: {'portfolio': {'portfolio_value': float('nan')}})
    client = TestClient(_make_app())
    payload = dict(broker='ibkr_paper', symbol='AAPL', action='BUY', effect='OPEN', quantity=1, order_type='LMT', limit_price=2, tif='DAY')
    if endpoint == 'option':
        payload['option_symbol'] = 'AAPL260620C00185000'
    response = client.post(f'/broker/{endpoint}-order', json=payload)
    assert response.status_code == 422
    router.execute.assert_not_called()
    payload['effect'] = 'CLOSE'
    response = client.post(f'/broker/{endpoint}-order', json=payload)
    assert response.status_code == 200, response.text
    router.execute.assert_called_once()


def test_fire_ignores_arm_and_request_equity_and_reads_changed_configuration(mocker):
    from app.services.auto_trader import AutoTradeService, ArmedStrategy
    svc = AutoTradeService()
    mocker.patch('app.services.auto_trader._market_is_open', return_value=True)
    execute = mocker.patch('app.services.auto_trader.execute_option_order')
    mocker.patch('app.services.auto_trader._apply_event_veto')
    cfg = {'portfolio': {'portfolio_value': 1000000}}
    original = portfolio_risk._load_config()
    cfg = {**original, 'portfolio': {**original['portfolio'], 'portfolio_value': 1000000}}
    mocker.patch.object(portfolio_risk, '_load_config', side_effect=lambda: cfg)
    strategy = ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL260620C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=6, conid=None, entry_premium=6, portfolio_value=1000000)
    svc.arm(strategy)
    cfg['portfolio']['portfolio_value'] = 10000
    with pytest.raises(RuntimeError, match='Exposure cap'):
        svc.fire(portfolio_snapshot=[], portfolio_value=1000000000)
    execute.assert_not_called()


def test_invalid_fire_config_records_refusal_and_disarms(mocker):
    from app.services.auto_trader import AutoTradeService, ArmedStrategy
    svc = AutoTradeService()
    mocker.patch('app.services.auto_trader._market_is_open', return_value=True)
    mocker.patch('app.services.auto_trader._apply_event_veto')
    execute = mocker.patch('app.services.auto_trader.execute_option_order')
    mocker.patch.object(portfolio_risk, '_load_config', return_value={'portfolio': {'portfolio_value': False}})
    svc.arm(ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL260620C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=2, conid=None, entry_premium=2))
    with pytest.raises(portfolio_risk.AccountValueError):
        svc.fire()
    execute.assert_not_called()
    assert not svc.get_state().armed
    assert svc.get_state().history[-1]['status'] == 'risk_check_failed'

@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), 0, -1])
def test_risk_settings_cannot_accept_nonfinite_account(value):
    from app.routers.risk_settings import RiskConfig
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RiskConfig(portfolioValue=value)

@pytest.mark.asyncio
async def test_settings_get_matches_default_account(monkeypatch):
    from app.routers import risk_settings
    monkeypatch.setattr(risk_settings, '_load_risk', lambda **kwargs: {})
    assert (await risk_settings.get_risk_settings())['portfolioValue'] == portfolio_risk.account_value({})

@pytest.mark.parametrize('endpoint', ['stock', 'option'])
def test_manual_open_rechecks_account_after_worker_queue(endpoint, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.test_broker_idempotency import _make_app, _mock_router
    from app.routers import broker
    router = _mock_router()
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: router)
    cfg = {'portfolio': {'portfolio_value': 100000}}
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: cfg)
    async def delayed_worker(fn, *args, **kwargs):
        cfg['portfolio']['portfolio_value'] = float('nan')
        return fn(*args, **kwargs)
    monkeypatch.setattr(broker.asyncio, 'to_thread', delayed_worker)
    client = TestClient(_make_app())
    payload = dict(broker='ibkr_paper', symbol='AAPL', action='BUY', effect='OPEN', quantity=1, order_type='LMT', limit_price=2, tif='DAY')
    if endpoint == 'option':
        payload['option_symbol'] = 'AAPL260620C00185000'
    response = client.post(f'/broker/{endpoint}-order', json=payload)
    assert response.status_code == 422
    router.execute.assert_not_called()
    from app.routers.broker import _idempotency_inflight
    assert not _idempotency_inflight

@pytest.mark.asyncio
@pytest.mark.parametrize('document', [None, '', 'null\n', '[]\n'])
async def test_settings_get_refuses_unreadable_or_invalid_document(document, tmp_path, monkeypatch):
    from app.routers import risk_settings
    from fastapi import HTTPException
    path = tmp_path / 'risk.yaml'
    if document is not None:
        path.write_text(document)
    monkeypatch.setattr(risk_settings, '_RISK_PATH', path)
    with pytest.raises(HTTPException) as failure:
        await risk_settings.get_risk_settings()
    assert failure.value.status_code == 422
