"""P0B B1 refuses bearish opens before reservation or adapter dispatch."""
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.data.ibkr_paper import OrderResult
from app.routers import broker
from app.services.broker_router import BrokerRouter

MESSAGE = ('Bearish setups are Unvalidated: no bearish strategy has passed validation yet '
           '(decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research; '
           'no PASS, no auto-trade, no opening order.')

@pytest.fixture
def endpoint(monkeypatch):
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()
    adapter = MagicMock()
    adapter.place_order.return_value = OrderResult(order_id='B1', status='ok', broker='ibkr_paper')
    router = BrokerRouter(adapters={'ibkr_paper': adapter})
    hooks, audit = MagicMock(), MagicMock()
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: router)
    monkeypatch.setattr('app.services.portfolio_risk.account_value', lambda: 100_000)
    monkeypatch.setattr('app.services.daily_risk_hooks.capture_daily_risk_hooks', lambda: hooks)
    monkeypatch.setattr(broker, 'log_event', audit)
    app = FastAPI()
    app.include_router(broker.router)
    with TestClient(app) as client:
        yield client, adapter, hooks, audit
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()

def payload(action='BUY', effect='OPEN', option_symbol=None):
    body = dict(broker='ibkr_paper', symbol='AAPL', action=action, effect=effect,
                quantity=1, order_type='LMT', limit_price=2.5)
    if option_symbol is not None:
        body['option_symbol'] = option_symbol
    return body

@pytest.mark.parametrize('path,body', [
    ('stock-order', payload(action='SELL')),
    ('option-order', payload(option_symbol='AAPL250516P00185000')),
    ('option-order', payload(option_symbol='AAPL|185|2025-05-16|P')),
    ('option-order', payload(action='SELL', option_symbol='AAPL250516C00185000')),
])
def test_bearish_open_refused_and_retry_claim_released(endpoint, path, body):
    client, adapter, hooks, audit = endpoint
    for _ in range(2):
        response = client.post(f'/broker/{path}', json=body)
        assert response.status_code == 422
        assert response.json() == {'detail': MESSAGE}
        assert not broker._idempotency_inflight
        assert not broker._idempotency_cache
    adapter.place_order.assert_not_called()
    hooks.reserve.assert_not_called()
    hooks.resolve.assert_not_called()
    refusals = [args for args, _ in audit.call_args_list if args[0] == 'broker_order_failed']
    assert len(refusals) == 2
    assert all(args[2]['http_status'] == 422 for args in refusals)
    assert all(args[2]['error'] == 'bearish unvalidated' for args in refusals)

@pytest.mark.parametrize('path,body', [
    ('stock-order', payload()),
    ('stock-order', payload(action='SELL', effect='CLOSE')),
    ('stock-order', payload(action='BUY', effect='CLOSE')),
    ('option-order', payload(option_symbol='AAPL250516C00185000')),
    ('option-order', payload(option_symbol='AAPL|185|2025-05-16|C')),
    ('option-order', payload(action='SELL', effect='CLOSE', option_symbol='AAPL250516P00185000')),
    ('option-order', payload(effect='CLOSE', option_symbol='AAPL250516P00185000')),
    ('option-order', payload(effect='CLOSE', option_symbol='not-an-option')),
])
def test_bullish_opens_and_all_closes_dispatch(endpoint, path, body):
    client, adapter, hooks, _ = endpoint
    response = client.post(f'/broker/{path}', json=body)
    assert response.status_code == 200
    adapter.place_order.assert_called_once()
    assert adapter.place_order.call_args.args[0].effect == body['effect']
    assert hooks.reserve.call_count == (1 if body['effect'] == 'OPEN' else 0)

BAD_SYMBOLS = ['not-an-option', 'AAPL|185|2025-05-16|X', 'AAPL250516P00185000junk', 'AAPL250516C00185000\n']
@pytest.mark.parametrize('symbol', BAD_SYMBOLS)
def test_unknown_open_option_symbol_fails_closed(endpoint, symbol):
    client, adapter, hooks, _ = endpoint
    response = client.post('/broker/option-order', json=payload(option_symbol=symbol))
    assert response.status_code == 422
    adapter.place_order.assert_not_called()
    hooks.reserve.assert_not_called()
    assert not broker._idempotency_inflight

@pytest.mark.parametrize('symbol,right', [
    ('AAPL250516P00185000', 'P'), ('AAPL250516C00185000', 'C'),
    ('AAPL|185|2025-05-16|P', 'P'), ('AAPL|185|2025-05-16|C', 'C'),
])
def test_option_right_formats(symbol, right):
    from app.data.option_symbol import option_right
    assert option_right(symbol) == right

@pytest.mark.parametrize('symbol', BAD_SYMBOLS)
def test_option_right_rejects_unknown_format(symbol):
    from app.data.option_symbol import option_right
    with pytest.raises(ValueError):
        option_right(symbol)
