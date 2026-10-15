"""Explicit simulations create separate frozen evidence, never scan mutations."""
import inspect
from copy import deepcopy
from datetime import date

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.database import get_db
from tests.test_backtest_artifacts import store
from tests.test_strategy_backtest_details import bars


def request_body():
    from app.services.strategy_engine import pullback_ema_signal
    params = {k: v.default for k, v in inspect.signature(pullback_ema_signal).parameters.items()
              if k not in {'bars', 'direction'}}
    params['tolerance'] = 0
    return dict(symbol='AAPL', strategy='pullback_ema', direction='Bearish',
                params=params, start='2024-04-20', end='2024-05-30', commission=.002,
                hold_max_days=10, min_trades=5, min_win_rate=.5,
                initial_cash=100000, order_size=.9999999999999998, margin=1, spread=0,
                exclusive_orders=True, trade_on_close=False, finalize_trades=False,
                sizing='fraction of available equity; whole units', confirmed=True)


@pytest.fixture
async def client(store, monkeypatch):
    from app.routers.backtest_artifacts import router
    from app.services import fresh_backtest
    app = FastAPI()
    app.include_router(router)
    async def db_override():
        async with store() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    async def history(symbol, start, end):
        assert symbol == 'AAPL' and start < date(2024, 1, 1) and end == date(2024, 5, 30)
        return bars()
    monkeypatch.setattr(fresh_backtest, 'get_historical_bars', history)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as c:
        yield c


@pytest.mark.asyncio
async def test_explicit_fresh_separate_ids_window_costs_direction_and_original_immutable(client, store):
    from app.services.backtest_artifacts import save_artifact, get_artifact
    from tests.test_backtest_artifacts import detail, identity
    async with store() as db:
        original = await save_artifact(db, detail=detail(), identity=identity())
    first = await client.post('/api/backtest-artifacts/fresh', json=request_body())
    assert first.status_code == 200, first.text
    artifact = first.json()['artifact']
    assert artifact['provenance'] == 'fresh'
    assert artifact['identity']['direction'] == 'Bearish'
    assert artifact['detail']['configuration']['commission'] == .002
    assert artifact['detail']['configuration']['entry_start'] == '2024-04-20'
    assert artifact['detail']['configuration']['entry_end'] == '2024-05-30'
    assert artifact['identity']['report_run_id'] is None
    assert artifact['detail']['configuration']['order_size'] == request_body()['order_size']
    assert artifact['detail']['candles'][0]['time'] >= 1713571200
    assert artifact['detail']['candles'][-1]['time'] < 1717027200
    assert len(artifact['detail']['input_candles']) > len(artifact['detail']['candles'])
    assert artifact['artifact_id'] != original['artifact_id']
    second = (await client.post('/api/backtest-artifacts/fresh', json=request_body())).json()
    assert second['artifact']['artifact_id'] != artifact['artifact_id']
    async with store() as db:
        assert await get_artifact(db, original['artifact_id'], 'AAPL') == original


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    {'confirmed': False}, {'direction': 'sideways'}, {'strategy': 'fibonacci_pullback'},
    {'strategy': 'mean_reversion_vwap'}, {'params': {}}, {'initial_cash': 1},
    {'commission': -.1}, {'end': '2024-04-01'}, {'hold_max_days': 0},
])
async def test_rejects_incomplete_or_unconfirmed_configuration_before_data(client, change):
    body = request_body(); body.update(change)
    assert (await client.post('/api/backtest-artifacts/fresh', json=body)).status_code == 422


@pytest.mark.asyncio
async def test_no_unknown_params_no_missing_params_and_no_ambient_exit_substitution(client, monkeypatch):
    from app.services import strategy_param_store
    monkeypatch.setattr(strategy_param_store, 'get_exit', lambda s: {'atr_stop_mult': 99})
    body = request_body(); body['params']['surprise'] = 2
    assert (await client.post('/api/backtest-artifacts/fresh', json=body)).status_code == 422
    body = request_body(); del body['params']['ema_period']
    assert (await client.post('/api/backtest-artifacts/fresh', json=body)).status_code == 422
    body = request_body()
    result = (await client.post('/api/backtest-artifacts/fresh', json=body)).json()
    assert result['artifact']['detail']['effective_params'] == body['params']


@pytest.mark.asyncio
async def test_failure_and_short_history_are_explicit_without_artifact(client, monkeypatch):
    from app.services import fresh_backtest
    async def short(*a): return []
    monkeypatch.setattr(fresh_backtest, 'get_historical_bars', short)
    result = (await client.post('/api/backtest-artifacts/fresh', json=request_body())).json()
    assert result == {'status': 'insufficient_history', 'artifact': None}
    async def failure(*a): raise RuntimeError('private provider info')
    monkeypatch.setattr(fresh_backtest, 'get_historical_bars', failure)
    result = (await client.post('/api/backtest-artifacts/fresh', json=request_body())).json()
    assert result == {'status': 'failed', 'artifact': None}


@pytest.mark.asyncio
async def test_contract_is_types_only_and_all_six_daily_strategies_are_explicit(client):
    result = (await client.get('/api/backtest-artifacts/fresh/configuration')).json()
    assert len(result['strategies']) == 6
    assert 'mean_reversion_vwap' not in result['strategies']
    assert result['parameters']['pullback_ema']['current_price'] == 'null'
    assert 'mean_reversion_vwap_daily' in result['parameters']


def test_multi_requires_every_selected_variant_parameter_and_no_intraday():
    from app.schemas.fresh_backtest import FreshBacktestRequest, signal_functions
    body = request_body()
    params = lambda fn: {k:v.default for k,v in inspect.signature(fn).parameters.items() if k not in {'bars','direction'}}
    variant = 'mean_reversion_vwap_daily'
    body.update(strategy='mean_reversion_multi', params={'variants':[variant], 'min_confirmations':1,
                'variant_params':{variant:params(signal_functions()[variant])}})
    assert FreshBacktestRequest(**body).params == body['params']
    broken = deepcopy(body); broken['params']['variant_params'][variant].pop('vwap_lookback')
    with pytest.raises(ValueError): FreshBacktestRequest(**broken)
    broken = deepcopy(body); broken['params']['variants'] = ['mean_reversion_vwap']
    with pytest.raises(ValueError): FreshBacktestRequest(**broken)


@pytest.mark.asyncio
async def test_storage_failure_returns_no_fake_result(client, monkeypatch):
    from app.services import backtest_artifacts
    async def fail(*args, **kwargs): raise backtest_artifacts.ArtifactStorageError()
    monkeypatch.setattr(backtest_artifacts, 'save_artifact', fail)
    result = (await client.post('/api/backtest-artifacts/fresh', json=request_body())).json()
    assert result == {'status': 'storage_unavailable', 'artifact': None}
