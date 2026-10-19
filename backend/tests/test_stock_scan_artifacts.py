"""Original evidence must match the exact aggregate invocation."""
import concurrent.futures
from dataclasses import asdict
from uuid import uuid4
from app.routers import stock_scan as scan
from app.services.strategy_backtest import run_strategy_backtest
from tests.test_strategy_backtest_details import bars


def inputs():
    return dict(strategy='pullback_ema', direction='Bullish', params={'tolerance': 0},
                commission=.002, min_trades=0, min_win_rate=0, hold_max_days=None)


def test_full_identity_covers_old_ohlcv_and_every_effective_input():
    data = bars()
    base = scan._detail_key('AAPL', data, inputs())
    for field in ('open', 'high', 'low', 'close', 'volume', 'time'):
        changed = [dict(b) for b in data]
        changed[0][field] = str(changed[0][field]) + 'x' if field == 'time' else changed[0][field] + 1
        assert scan._detail_key('AAPL', changed, inputs()) != base
    for key, value in dict(direction='Bearish', params={'tolerance': .1}, commission=.003,
                           min_trades=1, min_win_rate=.5, hold_max_days=7).items():
        assert scan._detail_key('AAPL', data, {**inputs(), key: value}) != base


def test_wrapper_once_and_detached_identity_cache(monkeypatch):
    calls = []
    def existing(*args, **kwargs):
        calls.append(1)
        return run_strategy_backtest(*args, **kwargs)
    monkeypatch.setattr(scan, 'run_strategy_backtest', existing)
    summary, detail = scan._run_backtest_with_details(bars(), **inputs())
    assert len(calls) == 1 and asdict(detail.summary) == asdict(summary)
    key = scan._detail_key('AAPL', bars(), inputs())
    scan._remember_detail(key, summary, detail)
    frozen = scan._cached_detail(key, summary)
    detail.configuration['commission'] = .9
    assert frozen.configuration['commission'] == .002
    assert scan._cached_detail(key, run_strategy_backtest(bars(), **inputs())) is None
    scan.evict_backtest_cache(['AAPL'])
    assert scan._cached_detail(key, summary) is None


def test_detail_cache_bounded_and_expired(monkeypatch):
    scan._BACKTEST_DETAILS.clear()
    summary, detail = scan._run_backtest_with_details(bars(), **inputs())
    for i in range(129):
        scan._remember_detail(f'AAPL|{i}', summary, detail)
    assert len(scan._BACKTEST_DETAILS) == 128
    monkeypatch.setattr(scan.time, 'time', lambda: 10**12)
    assert scan._cached_detail('AAPL|128', summary) is None


def test_process_pool_wrapper_picklable_and_aggregate_parity():
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
        summary, detail = pool.submit(scan._run_backtest_with_details, bars(), **inputs()).result(timeout=30)
    assert asdict(summary) == asdict(run_strategy_backtest(bars(), **inputs()))
    assert detail.status == 'success'


def test_report_projection_preserves_only_valid_artifact_reference():
    from app.services.scan_report_lifecycle import project
    identity = str(uuid4())
    assert project({'backtest_artifact_id': identity, 'backtest_artifact_status': 'available'}) == {
        'backtest_artifact_id': identity, 'backtest_artifact_status': 'available'}
    assert 'backtest_artifact_id' not in project({'backtest_artifact_id': 'not a uuid', 'backtest_artifact_status': 'secret'})


import asyncio
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch
import pytest


@pytest.fixture
def linked_scan(monkeypatch):
    from app.schemas.stock_scan import StockScanRequest
    from tests.test_stock_scan_time_exits import _card, _signal
    scan._BACKTEST_CACHE.clear()
    scan._BACKTEST_DETAILS.clear()
    with ExitStack() as stack:
        for name, value in dict(
            score_stock=_card(), get_historical_bars=bars(), fetch_intraday_candles=bars(),
            compute_omm=None, _get_fundamentals=None, fetch_company_name_async='Apple Inc',
            fetch_price_async=None, get_active={}, get_cached={'confidence': 80, 'sample_size': 50},
            _earnings_days_for=None, _backtest_drop=None,
        ).items():
            stack.enter_context(patch.object(scan, name, return_value=value))
        stack.enter_context(patch.dict(scan._SIGNAL_FNS, {'pullback_ema': lambda *a, **k: _signal('pullback_ema')}))
        pool = stack.enter_context(concurrent.futures.ThreadPoolExecutor(max_workers=2))
        stack.enter_context(patch.object(scan, '_BACKTEST_POOL', pool))
        async def run(direction='Bullish', scan_id='scan-1'):
            req = StockScanRequest(universe=['AAPL'], direction=direction, horizon='Swing', strategy='pullback_ema')
            return await scan._process_stock('AAPL', req, scan_id, {}, [])
        yield run


@pytest.mark.asyncio
async def test_original_linkage_cache_hit_and_old_bar_collision(linked_scan, monkeypatch):
    saved, calls = [], []
    async def save(db, *, detail, identity):
        saved.append((detail, identity))
        return {'artifact_id': str(uuid4())}
    monkeypatch.setattr('app.services.backtest_artifacts.save_artifact', save)
    real = scan.run_strategy_backtest
    def counted(*a, **kw):
        calls.append(1)
        return real(*a, **kw)
    monkeypatch.setattr(scan, 'run_strategy_backtest', counted)
    first = await linked_scan(scan_id='one')
    second = await linked_scan(scan_id='two')
    assert first.backtest_artifact_status == second.backtest_artifact_status == 'available'
    assert first.backtest_artifact_id != second.backtest_artifact_id
    assert [ident['scan_id'] for _, ident in saved] == ['one', 'two']
    assert len(calls) == 1
    assert first.backtest == second.backtest
    assert saved[0][0].summary.n_trades == 0 and saved[0][0].equity
    changed = bars()
    changed[0]['volume'] += 1  # legacy last-20 close key collides
    monkeypatch.setattr(scan, 'get_historical_bars', AsyncMock(return_value=changed))
    collision = await linked_scan(scan_id='three')
    assert collision.backtest == first.backtest
    assert collision.backtest_artifact_status == 'original_unavailable'
    assert len(calls) == 1 and len(saved) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['save', 'cache_read', 'cache_write'])
async def test_optional_failure_preserves_all_numeric_and_trading_fields(linked_scan, monkeypatch, fault):
    async def save(db, *, detail, identity):
        return {'artifact_id': str(uuid4())}
    monkeypatch.setattr('app.services.backtest_artifacts.save_artifact', save)
    baseline = await linked_scan()
    def fail(*a, **kw):
        raise RuntimeError('injected optional evidence failure')
    if fault == 'save':
        async def fail_save(*a, **kw):
            raise RuntimeError('injected storage failure')
        monkeypatch.setattr('app.services.backtest_artifacts.save_artifact', fail_save)
    else:
        monkeypatch.setattr(scan, '_cached_detail' if fault == 'cache_read' else '_remember_detail', fail)
    if fault == 'cache_write':
        scan._BACKTEST_CACHE.clear()
    result = await linked_scan()
    for key in ['backtest_artifact_id', 'backtest_artifact_status']:
        baseline = baseline.model_copy(update={key: None})
        result = result.model_copy(update={key: None})
    assert result == baseline


@pytest.mark.asyncio
async def test_same_symbol_opposite_direction_concurrent_scan_ids(linked_scan, monkeypatch):
    captured = []
    async def save(db, *, detail, identity):
        captured.append((detail.summary.direction, identity.copy()))
        await asyncio.sleep(0)
        return {'artifact_id': str(uuid4())}
    monkeypatch.setattr('app.services.backtest_artifacts.save_artifact', save)
    results = await asyncio.gather(linked_scan('Bullish', 'bull'), linked_scan('Bearish', 'bear'))
    assert all(r.backtest_artifact_status == 'available' for r in results)
    assert {r.backtest_artifact_id for r in results}.__len__() == 2
    assert {(d, ident['direction'], ident['scan_id']) for d, ident in captured} == {
        ('Bullish', 'Bullish', 'bull'), ('Bearish', 'Bearish', 'bear')}
    assert len({ident['input_hash'] for _, ident in captured}) == 2


@pytest.mark.asyncio
async def test_legacy_summary_does_not_recompute(linked_scan, monkeypatch):
    first = await linked_scan()
    scan._BACKTEST_DETAILS.clear()
    def forbidden(*a, **kw):
        raise AssertionError('legacy cache must not be upgraded by recomputation')
    monkeypatch.setattr(scan, 'run_strategy_backtest', forbidden)
    result = await linked_scan()
    assert result.backtest == first.backtest
    assert result.backtest_artifact_id is None
    assert result.backtest_artifact_status == 'original_unavailable'


@pytest.mark.asyncio
async def test_original_identity_uses_active_report_run(linked_scan, monkeypatch):
    from app.services.scan_report_lifecycle import Collector, _collector
    collector = Collector(request={})
    collector.report_run_id = str(uuid4())
    captured = []
    async def save(db, *, detail, identity):
        captured.append(identity)
        return {'artifact_id': str(uuid4())}
    monkeypatch.setattr('app.services.backtest_artifacts.save_artifact', save)
    token = _collector.set(collector)
    try:
        result = await linked_scan()
    finally:
        _collector.reset(token)
    assert result.backtest_artifact_status == 'available'
    assert captured[0]['report_run_id'] == collector.report_run_id


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['unsupported', 'insufficient_history', 'invalid_input', 'failed', 'invalid_evidence'])
async def test_non_success_status_without_storage(status):
    from dataclasses import replace
    _, detail = scan._run_backtest_with_details(bars(), **inputs())
    result = await scan._original_artifact(replace(detail, status=status), scan_id='s', symbol='AAPL',
                strategy='pullback_ema', direction='Bullish', horizon='Swing', interval='1d', detail_key='AAPL|hash')
    assert result == {'backtest_artifact_status': status}
