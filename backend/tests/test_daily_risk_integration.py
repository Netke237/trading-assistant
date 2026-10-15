"""Actual dispatch/portfolio integration against an isolated durable ledger."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base, get_db
from app.models.daily_risk import DailyRiskBudget, DailyRiskAttempt
from app.services import daily_risk, daily_risk_hooks, portfolio_exposure, portfolio_risk
from app.services.auto_trader import AutoTradeService, ArmedStrategy
from app.data.ibkr_paper import OrderResult
from app.routers import broker, portfolio


@pytest_asyncio.fixture
async def rig(tmp_path, monkeypatch):
    import app.models
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "ledger.db"}')
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    cfg = portfolio_risk._load_config()
    cfg = {**cfg, 'portfolio': {**cfg['portfolio'], 'portfolio_value': 100000}, 'auto_trade': {'max_daily_loss_pct': .02}}
    monkeypatch.setattr(portfolio_risk, '_load_config', lambda: cfg)
    monkeypatch.setattr(portfolio_exposure.book, 'sessions', sessions)
    service = daily_risk.DailyRiskService(sessions, config_provider=lambda: cfg, history_provider=lambda: [])
    monkeypatch.setattr(daily_risk, 'reserve', service.reserve)
    monkeypatch.setattr(daily_risk, 'resolve', service.resolve)
    monkeypatch.setattr(daily_risk, 'record_realized_loss', service.record_realized_loss)
    broker._idempotency_cache.clear()
    broker._idempotency_inflight.clear()
    adapter = MagicMock()
    adapter.execute.return_value = OrderResult(order_id='placed', status='PreSubmitted', broker='ibkr_paper')
    adapter.resolve.side_effect = lambda key: SimpleNamespace(place_order=lambda order: adapter.execute(key, order))
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: adapter)
    app = FastAPI()
    app.include_router(broker.router)
    app.include_router(portfolio.router)
    async def db():
        async with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = db
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield SimpleNamespace(client=client, adapter=adapter, sessions=sessions, service=service, cfg=cfg)
    await engine.dispose()


def stock(symbol='AAPL', **kwargs):
    return dict(broker='ibkr_paper', symbol=symbol, action='BUY', effect='OPEN', quantity=10, order_type='LMT', limit_price=100, tif='DAY', **kwargs)

async def amounts(rig):
    async with rig.sessions() as db:
        rows = (await db.execute(select(DailyRiskBudget))).scalars().all()
        return sum(r.reserved_cents for r in rows), sum(r.loss_cents for r in rows)

@pytest.mark.asyncio
async def test_raw_manual_open_durable_budget_and_dedup(rig):
    first = await rig.client.post('/broker/stock-order', json=stock())
    assert first.status_code == 200
    repeat = await rig.client.post('/broker/stock-order', json=stock())
    assert repeat.json()['deduped']
    second = await rig.client.post('/broker/stock-order', json=stock('MSFT'))
    assert second.status_code == 200
    blocked = await rig.client.post('/broker/stock-order', json=stock('NVDA'))
    assert blocked.status_code == 422
    assert rig.adapter.execute.call_count == 2
    assert await amounts(rig) == (200000, 0)

@pytest.mark.asyncio
@pytest.mark.parametrize('status,released', [('Rejected', True), ('UnknownStatus', False), ('PreSubmitted', False)])
async def test_manual_result_release_only_definite_rejection(rig, status, released):
    rig.adapter.execute.return_value = OrderResult(order_id='x', status=status, broker='ibkr_paper')
    response = await rig.client.post('/broker/stock-order', json=stock())
    assert response.status_code == 200
    assert await amounts(rig) == (0 if released else 100000, 0)

@pytest.mark.asyncio
async def test_manual_error_retains_and_close_bypasses_broken_config(rig):
    rig.adapter.execute.side_effect = RuntimeError('ambiguous broker failure')
    response = await rig.client.post('/broker/stock-order', json=stock())
    assert response.status_code == 502
    assert await amounts(rig) == (100000, 0)
    rig.cfg['portfolio']['portfolio_value'] = float('nan')
    rig.adapter.execute.side_effect = None
    payload = stock()
    payload['effect'] = 'CLOSE'
    assert (await rig.client.post('/broker/stock-order', json=payload)).status_code == 200
    assert await amounts(rig) == (100000, 0)

@pytest.mark.asyncio
async def test_option_mkt_quote_failure_and_naked_short_never_dispatch(rig, monkeypatch):
    from app.data import market
    async def no_quote(*args):
        return None
    monkeypatch.setattr(market, 'fetch_contract_quote_async', no_quote)
    async def missing_exact_quote(*args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'quotes': {'quote': None}})
    monkeypatch.setattr(daily_risk_hooks.httpx.AsyncClient, 'get', missing_exact_quote)
    payload = dict(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', effect='OPEN', quantity=1, order_type='MKT', tif='DAY')
    assert (await rig.client.post('/broker/option-order', json=payload)).status_code == 422
    payload.update(action='SELL', order_type='LMT', limit_price=2)
    assert (await rig.client.post('/broker/option-order', json=payload)).status_code == 422
    rig.adapter.execute.assert_not_called()
    assert await amounts(rig) == (0, 0)

@pytest.mark.asyncio
async def test_auto_and_manual_compete_atomically_for_remaining_budget(rig, monkeypatch):
    from app.services import auto_trader as at
    monkeypatch.setattr(at, '_market_is_open', lambda *args: True)
    monkeypatch.setattr(at, '_apply_vol_sizing', lambda strategy: strategy)
    monkeypatch.setattr(at, '_apply_event_veto', lambda strategy: None)
    execute = MagicMock(return_value=OrderResult(order_id='auto', status='PreSubmitted', broker='ibkr_paper'))
    monkeypatch.setattr(at, 'execute_option_order', execute)
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=15, conid=None, entry_premium=1))
    hooks = daily_risk_hooks.capture_daily_risk_hooks()
    auto, manual = await asyncio.gather(asyncio.to_thread(svc.fire, daily_risk_hooks=hooks), rig.client.post('/broker/stock-order', json=stock('MSFT')), return_exceptions=True)
    assert execute.call_count + rig.adapter.execute.call_count == 1
    reserved, loss = await amounts(rig)
    assert reserved in (100000, 150000)
    assert loss == 0
    if execute.called:
        assert auto.result.order_id == 'auto'
        assert svc.get_state().history[-1]['premium_at_risk'] == 1500
        assert manual.status_code == 422
    else:
        assert isinstance(auto, RuntimeError)
        assert manual.status_code == 200

@pytest.mark.asyncio
async def test_cancelled_manual_worker_retains_until_worker_finishes(rig):
    started, finish = threading.Event(), threading.Event()
    def execute(*args):
        started.set()
        assert finish.wait(5)
        return OrderResult(order_id='landed', status='PreSubmitted', broker='ibkr_paper')
    rig.adapter.execute.side_effect = execute
    task = asyncio.create_task(rig.client.post('/broker/stock-order', json=stock()))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await amounts(rig) == (100000, 0)
    finish.set()
    # Drain a worker call, then wait for the durable reconciliation to complete.
    for _ in range(30):
        async with rig.sessions() as db:
            row = (await db.execute(select(DailyRiskAttempt))).scalar_one()
            if row.outcome:
                break
        await asyncio.sleep(.01)
    assert row.outcome == 'PreSubmitted'
    assert row.state == 'retained'

@pytest.mark.asyncio
@pytest.mark.parametrize('contract,direction,exit_price,pnl,loss', [
    ('AAPL|STOCK', 'Bearish', 110, -100, 10000),
    ('AAPL|STOCK', 'Bearish', 90, 100, 0),
    ('AAPL|185|2026-12-18|P', 'Bearish', 90, -10000, 1000000),
])
async def test_partial_close_gross_loss_correct_sign_and_delete_cannot_refund(rig, contract, direction, exit_price, pnl, loss):
    from app.models.portfolio import PortfolioPositionModel
    async with rig.sessions() as db:
        db.add(PortfolioPositionModel(rec_id='REC', symbol='AAPL', contract=contract, direction=direction, entry_price=100, qty=20, entry_date='2026-01-01'))
        await db.commit()
    response = await rig.client.post('/api/portfolio/REC/close', json={'exitPrice': exit_price, 'qtyToClose': 10, 'exitDate': '2000-01-01'})
    assert response.status_code == 201, response.text
    assert response.json()['realizedPnlDollar'] == pnl
    assert await amounts(rig) == (0, loss)
    history_id = response.json()['id']
    deleted = await rig.client.delete(f'/api/portfolio/history/{history_id}')
    assert deleted.status_code == 204, deleted.text
    assert await amounts(rig) == (0, loss)

@pytest.mark.asyncio
async def test_auto_requires_durable_hooks_and_ledger_failure_never_executes(rig, monkeypatch):
    from app.services import auto_trader as at
    monkeypatch.setattr(at, '_market_is_open', lambda *args: True)
    monkeypatch.setattr(at, '_apply_vol_sizing', lambda strategy: strategy)
    monkeypatch.setattr(at, '_apply_event_veto', lambda strategy: None)
    execute = MagicMock()
    monkeypatch.setattr(at, 'execute_option_order', execute)
    svc = AutoTradeService()
    strategy = ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=1, conid=None, entry_premium=1)
    svc.arm(strategy)
    with pytest.raises(RuntimeError, match='originating event-loop'):
        await asyncio.to_thread(svc.fire)
    execute.assert_not_called()
    assert svc.get_state().history[-1]['status'] == 'daily_loss_blocked'
    async def failed(*args, **kwargs):
        raise OSError('database unavailable')
    monkeypatch.setattr(daily_risk, 'reserve', failed)
    svc.arm(strategy)
    with pytest.raises(OSError, match='database unavailable'):
        await asyncio.to_thread(svc.fire, daily_risk_hooks=daily_risk_hooks.capture_daily_risk_hooks())
    execute.assert_not_called()
    assert svc.get_state().history[-1]['status'] == 'risk_check_failed'

@pytest.mark.asyncio
async def test_reconciliation_failure_keeps_actual_auto_result_and_history(rig, monkeypatch):
    from app.services import auto_trader as at
    monkeypatch.setattr(at, '_market_is_open', lambda *args: True)
    monkeypatch.setattr(at, '_apply_vol_sizing', lambda strategy: strategy)
    monkeypatch.setattr(at, '_apply_event_veto', lambda strategy: None)
    monkeypatch.setattr(at, 'execute_option_order', lambda strategy: OrderResult(order_id='actual', status='PreSubmitted', broker='ibkr_paper'))
    async def failed(*args, **kwargs):
        raise OSError('reconcile unavailable')
    monkeypatch.setattr(daily_risk, 'resolve', failed)
    svc = AutoTradeService()
    svc.arm(ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=1.001, conid=None, entry_premium=1))
    result = await asyncio.to_thread(svc.fire, daily_risk_hooks=daily_risk_hooks.capture_daily_risk_hooks())
    assert result.result.order_id == 'actual'
    assert svc.get_state().history[-1]['status'] == 'PreSubmitted'
    assert svc.get_state().history[-1]['premium_at_risk'] == 100.1
    assert await amounts(rig) == (10010, 0)

@pytest.mark.asyncio
async def test_market_option_uses_server_quote_and_ibkr_confirmation_releases(rig, monkeypatch):
    from app.data import market
    contracts = []
    async def quote(client, contract):
        contracts.append(contract)
        return {'price': 2.5}
    monkeypatch.setattr(market, 'fetch_contract_quote_async', quote)
    async def exact_quote(client, url, **kwargs):
        contracts.append(kwargs['params']['symbols'])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'quotes': {'quote': {'symbol': kwargs['params']['symbols'], 'ask': 2.5}}})
    monkeypatch.setattr(daily_risk_hooks.httpx.AsyncClient, 'get', exact_quote)
    rig.adapter.execute.return_value = OrderResult(order_id='', status='Pending', broker='ibkr_paper', awaiting_confirmation=True, message='Confirm?')
    payload = dict(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', effect='OPEN', quantity=1, order_type='MKT', tif='DAY')
    response = await rig.client.post('/broker/option-order', json=payload)
    assert response.status_code == 502
    assert contracts == ['AAPL261218C00185000']
    assert await amounts(rig) == (0, 0)
    async with rig.sessions() as db:
        attempt = (await db.execute(select(DailyRiskAttempt))).scalar_one()
        assert attempt.reserved_cents == 25000
        assert attempt.state == 'released'

@pytest.mark.asyncio
async def test_manual_database_failure_before_dispatch_refuses(rig, monkeypatch):
    async def failed(*args, **kwargs):
        raise OSError('ledger unavailable')
    monkeypatch.setattr(daily_risk, 'reserve', failed)
    response = await rig.client.post('/broker/stock-order', json=stock())
    assert response.status_code == 422
    rig.adapter.execute.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize('trigger', ['manual', 'scan'])
async def test_both_auto_triggers_apply_durable_budget(rig, monkeypatch, trigger):
    from app.services import auto_trader as at
    from app.routers import auto_trade
    monkeypatch.setattr(at, '_market_is_open', lambda *args: True)
    monkeypatch.setattr(at, '_apply_vol_sizing', lambda strategy: strategy)
    monkeypatch.setattr(at, '_apply_event_veto', lambda strategy: None)
    execute = MagicMock(return_value=OrderResult(order_id='triggered', status='PreSubmitted', broker='ibkr_paper'))
    monkeypatch.setattr(at, 'execute_option_order', execute)
    svc = AutoTradeService()
    monkeypatch.setattr(auto_trade, 'auto_trader', svc)
    svc.arm(ArmedStrategy(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185000', action='BUY', direction='Bullish', quantity=1, order_type='LMT', limit_price=1, conid=None, entry_premium=1))
    if trigger == 'manual':
        rig.client._transport.app.include_router(auto_trade.router)
        async def booking(*args, **kwargs):
            return SimpleNamespace(booked=True, rec_id='REC', error=None, over_exposure=False)
        monkeypatch.setattr(auto_trade, 'book_fired_order', booking)
        response = await rig.client.post('/auto-trade/fire')
        assert response.status_code == 200, response.text
    else:
        result = await asyncio.to_thread(svc.maybe_fire_on_scan, portfolio_snapshot=[], daily_risk_hooks=daily_risk_hooks.capture_daily_risk_hooks())
        assert result.result.order_id == 'triggered'
    execute.assert_called_once()
    assert await amounts(rig) == (10000, 0)

@pytest.mark.asyncio
async def test_fractional_strike_market_quote_reserves_exact_contract(rig, monkeypatch):
    from app.data import market
    async def chain(*args, **kwargs):
        return [dict(symbol='AAPL261218C00185000', strike=185, price=.5), dict(symbol='AAPL261218C00185500', strike=185.5, price=3)]
    monkeypatch.setattr(market, 'fetch_option_chain_async', chain)
    async def exact_quote(client, url, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'quotes': {'quote': {'symbol': 'AAPL261218C00185500', 'ask': 3}}})
    monkeypatch.setattr(daily_risk_hooks.httpx.AsyncClient, 'get', exact_quote)
    payload = dict(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185500', action='BUY', effect='OPEN', quantity=1, order_type='MKT', tif='DAY')
    response = await rig.client.post('/broker/option-order', json=payload)
    assert response.status_code == 200, response.text
    assert await amounts(rig) == (30000, 0)

@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['stock', 'option'])
async def test_missing_adapter_refuses_without_charging_budget(rig, monkeypatch, endpoint):
    from app.services.broker_router import BrokerRouter
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: BrokerRouter({}))
    payload = stock()
    if endpoint == 'option':
        payload.update(option_symbol='AAPL261218C00185000', quantity=1, limit_price=1)
    response = await rig.client.post(f'/broker/{endpoint}-order', json=payload)
    assert response.status_code == 400
    assert await amounts(rig) == (0, 0)

@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['stock', 'option'])
async def test_postdispatch_value_error_keeps_budget(rig, monkeypatch, endpoint):
    from app.services.broker_router import BrokerRouter
    adapter = MagicMock()
    adapter.place_order.side_effect = ValueError('broker may have accepted before malformed response')
    monkeypatch.setattr(broker, 'build_router_from_credentials', lambda: BrokerRouter({'ibkr_paper': adapter}))
    payload = stock()
    if endpoint == 'option':
        payload.update(option_symbol='AAPL261218C00185000', quantity=1, limit_price=1)
    response = await rig.client.post(f'/broker/{endpoint}-order', json=payload)
    assert response.status_code == 400
    adapter.place_order.assert_called_once()
    assert await amounts(rig) == (10000 if endpoint == 'option' else 100000, 0)

@pytest.mark.asyncio
async def test_exact_option_quote_mismatched_identity_refuses(rig, monkeypatch):
    async def wrong_quote(*args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'quotes': {'quote': {'symbol': 'AAPL261218C00185000', 'ask': .5}}})
    monkeypatch.setattr(daily_risk_hooks.httpx.AsyncClient, 'get', wrong_quote)
    payload = dict(broker='ibkr_paper', symbol='AAPL', option_symbol='AAPL261218C00185500', action='BUY', effect='OPEN', quantity=1, order_type='MKT', tif='DAY')
    response = await rig.client.post('/broker/option-order', json=payload)
    assert response.status_code == 422
    rig.adapter.execute.assert_not_called()
    assert await amounts(rig) == (0, 0)
