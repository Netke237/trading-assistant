"""Unique, typed terminal evidence is separate from scan lifecycle success."""
from app.services import scan_report_lifecycle as lc
from app.services import scan_reports


def test_collector_counts_and_conflicts():
    c = lc.Collector(request={}, terminal_enabled=True)
    token = lc._collector.set(c)
    try:
        lc.observe_resolution(['AAPL', 'MSFT'], ['MSFT'], [{'symbol': 'AAPL'}])
        lc.observe_evaluation('MSFT')
        lc.observe_terminal('MSFT', 'error', 'history_fetch_failed')
        result = c.terminal_snapshot()
        assert result['complete']
        assert result['counts'] == dict(input=2, evaluated=1, accepted=0, excluded=1,
                                       no_data=0, error_count=1, no_setup=0, filtered=0)
        assert scan_reports._encode(result)
        lc.observe_terminal('MSFT', 'accepted', 'candidate_returned')
        result = c.terminal_snapshot()
        assert not result['complete']
        assert result['unknown_symbols'] == ['MSFT']
        assert result['diagnostic_unavailable']
    finally:
        lc._collector.reset(token)


def test_unresolved_unavailable_and_empty_honest():
    c = lc.Collector(request={}, terminal_enabled=True)
    assert c.terminal_snapshot() is None
    token = lc._collector.set(c)
    try:
        lc.observe_resolution([], [], [])
        result = c.terminal_snapshot()
        assert result['complete'] and result['counts']['input'] == 0
    finally:
        lc._collector.reset(token)


def test_typed_projection_refuses_free_text_and_nonfinite():
    assert lc.project_terminal_record('AAPL', 'error', 'secret') is None
    record = lc.project_terminal_record('AAPL', 'filtered', 'ema_side',
        observations={'current_close': 0, 'ema_value': float('inf'), 'direction': 'Bullish', 'reason': 'secret'},
        thresholds={'ema_period': 20, 'password': 'secret'})
    assert record == dict(symbol='AAPL', terminal='filtered', code='ema_side',
                         observations={'current_close': 0, 'direction': 'Bullish'}, thresholds={'ema_period': 20})

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import Response, HTTPException
from app.routers import stock_scan as ss
from app.routers.stock_scan import PreBreakoutScanRequest, FibPullbackScanRequest, StockScanRequest
from app.services.scan_reports import get_run, get_latest
from tests.test_scan_report_lifecycle import lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['prebreakout', 'fib'])
async def test_same_run_mixed_outcomes_dedup_and_list_parity(lifecycle, monkeypatch, mode):
    lc, factory = lifecycle
    from app.services import strategy_engine
    bars = [{'close': 100, 'high': 101, 'low': 99, 'volume': 1000}] * 60
    async def history(symbol, *_):
        if symbol == 'MISS': return []
        if symbol == 'FAIL': raise RuntimeError('secret provider token')
        return bars
    fetch = AsyncMock(side_effect=history)
    monkeypatch.setattr(ss, 'get_historical_bars', fetch)
    monkeypatch.setattr(ss, 'filter_symbols', lambda symbols, **_: (
        [x for x in symbols if x != 'EXCL'], [SimpleNamespace(symbol='EXCL', reason='secret')]))
    def signal(_bars, symbol, **_):
        if symbol == 'NONE': return None
        if symbol == 'BROKE': raise ValueError('secret')
        return SimpleNamespace(confidence=0, direction='Bullish', metrics={'value': 0, 'missing': None}, confidence_breakdown=None, fib_swing=None)
    monkeypatch.setattr(ss, 'breakout_setup_signal', signal)
    calls = []
    def detail(_bars, *_args, **_kwargs):
        # Identify symbol from the latest history call, without a second scan.
        symbol = fetch.call_args.args[0]
        calls.append(symbol)
        if symbol == 'BROKE': raise ValueError('secret')
        return dict(at_level=False, dist_pct=None, label=None if symbol == 'NONE' else '38.2', swing_low=0, swing_high=100)
    monkeypatch.setattr(strategy_engine, 'fibonacci_pullback_detail', detail)
    cls, core = (PreBreakoutScanRequest, ss._prebreakout_scan_core) if mode == 'prebreakout' else (FibPullbackScanRequest, ss._fib_pullback_scan_core)
    symbols = [' KEEP ', 'NONE', 'MISS', 'FAIL', 'BROKE', 'EXCL', 'keep', 'EXCL', 'NEXT']
    req = cls(symbols=symbols)
    response = Response()
    rows = await lc.run_reported_scan(req, category=mode, trigger='manual', response=response, callback=lambda: core(req))
    assert [x['symbol'] for x in rows] == ['KEEP', 'NEXT']
    assert fetch.await_count == 6
    async with factory() as db:
        run = await get_run(db, response.headers[lc.HEADERS[0]])
    assert [r['symbol'] for r in run['result']['candidates']] == [r['symbol'] for r in rows]
    assert [r['confidence'] for r in run['result']['candidates']] == [r['confidence'] for r in rows]
    terminal = run['diagnostics']['terminal_outcomes']
    assert terminal['complete']
    assert terminal['input_symbols'] == ['KEEP', 'NONE', 'MISS', 'FAIL', 'BROKE', 'EXCL', 'NEXT']
    assert terminal['evaluated_symbols'] == ['KEEP', 'NONE', 'MISS', 'FAIL', 'BROKE', 'NEXT']
    assert terminal['counts'] == dict(input=7, evaluated=6, accepted=2, excluded=1, no_data=1, error_count=2, no_setup=1, filtered=0)
    assert 'secret' not in str(run)
    by_symbol = {r['symbol']: r for r in terminal['outcomes']}
    assert by_symbol['FAIL']['code'] == 'history_fetch_failed'
    assert by_symbol['BROKE']['code'] == 'signal_processing_failed'
    # Same input baseline produces exactly the same numerical fields/order.
    fetch.reset_mock()
    baseline = await core(cls(symbols=terminal['input_symbols']))
    assert baseline == rows and fetch.await_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('direction,closes,period,filtered', [
    ('Bullish', [100, 90], 2, True), ('Bearish', [90, 100], 2, True),
    ('Bullish', [100, 100], 2, False), ('Bearish', [100, 100], 2, False),
    ('Bullish', [100, 90], 0, False), ('Bearish', [90, 100], 3, False),
])
async def test_fib_actual_ema_branch(lifecycle, monkeypatch, direction, closes, period, filtered):
    lc, factory = lifecycle
    from app.services import strategy_engine
    monkeypatch.setattr(ss, 'get_historical_bars', AsyncMock(return_value=[{'close': x} for x in closes]))
    monkeypatch.setattr(strategy_engine, 'fibonacci_pullback_detail', lambda *a, **k: dict(at_level=True, dist_pct=0, label='38.2', swing_low=90, swing_high=100))
    req = FibPullbackScanRequest(symbols=['AAA'], direction=direction, params_override={'ema_filter_period': period})
    response = Response()
    rows = await lc.run_reported_scan(req, category='fib', trigger='manual', response=response, callback=lambda: ss._fib_pullback_scan_core(req))
    async with factory() as db:
        run = await get_run(db, response.headers[lc.HEADERS[0]])
    outcome = run['diagnostics']['terminal_outcomes']['outcomes'][0]
    assert outcome['terminal'] == ('filtered' if filtered else 'accepted')
    assert bool(rows) is not filtered
    if filtered:
        assert outcome['thresholds']['ema_period'] == period
        assert outcome['observations']['current_close'] == closes[-1]
        assert outcome['observations']['ema_value'] == 95


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_partial_failure_persists_matching_attempt_and_no_provisional_acceptance(lifecycle, cancel):
    lc, factory = lifecycle
    response = Response()
    async def good():
        lc.observe_resolution(['OLD'], ['OLD'], [])
        lc.observe_evaluation('OLD')
        lc.observe_terminal('OLD', 'accepted', 'candidate_returned')
        return [{'symbol': 'OLD'}]
    await lc.run_reported_scan({}, category='fib', trigger='manual', response=response, callback=good)
    prior_id = response.headers[lc.HEADERS[0]]
    async def fail():
        lc.observe_resolution(['AAA', 'BBB', 'CCC'], ['AAA', 'BBB', 'CCC'], [])
        lc.observe_evaluation('AAA')
        lc.observe_terminal('AAA', 'no_data', 'missing_history')
        lc.observe_evaluation('BBB')
        lc.observe_terminal('BBB', 'accepted', 'candidate_returned')
        raise asyncio.CancelledError if cancel else RuntimeError('secret')
    with pytest.raises(asyncio.CancelledError if cancel else HTTPException):
        await lc.run_reported_scan({}, category='fib', trigger='manual', callback=fail)
    async with factory() as db:
        latest = await get_latest(db, 'fib')
        assert latest["latest_attempt"]["run_id"] != prior_id
    attempt = latest['latest_attempt']
    terminal = attempt['diagnostics']['terminal_outcomes']
    assert not terminal['complete']
    assert terminal['counts']['accepted'] == 0
    assert terminal['unknown_symbols'] == ['BBB', 'CCC']
    assert terminal['counts']['no_data'] == 1
    assert lc.current_collector() is None

@pytest.mark.asyncio
@pytest.mark.parametrize('category', ['pullback', 'stocks'])
async def test_stock_cap_dedup_scope_full_candidate_parity(lifecycle, monkeypatch, category):
    lc, factory = lifecycle
    from tests.test_stock_shortlist import _pc
    cards = {x: _pc(x, 80, confidence=None if x == 'NONE' else 0) for x in ['AAA', 'BBB', 'NONE']}
    calls = []
    async def worker(symbol, *_a, **_kw):
        calls.append(symbol)
        lc.observe_evaluation(symbol)
        if symbol == 'UNKNOWN': return {'symbol': symbol, 'reason': 'unrecognized provider rejection'}
        return cards[symbol]
    monkeypatch.setattr(ss, '_process_stock', worker)
    monkeypatch.setattr(ss, 'fetch_quotes', lambda _: {})
    monkeypatch.setattr(ss, 'get_historical_bars', AsyncMock(return_value=[]))
    async def run(symbols):
        req = StockScanRequest(symbols=symbols, universe=[], category=category, direction='Bullish', horizon='Swing', strategy='breakout_base', shortlist_max_candidates=2, account_size=10000, risk_pct=1)
        async with factory() as db:
            return await lc.run_reported_scan(req, category=category, trigger='manual', callback=lambda: ss._execute_stock_scan_core(req, db))
    inputs = ['AAA', 'BBB', 'AAA', 'NONE', 'UNKNOWN']
    rows = await run(inputs)
    async with factory() as db:
        report = await get_run(db, rows.report_run_id)
    if category == 'pullback':
        assert calls == ['AAA', 'BBB', 'NONE', 'UNKNOWN']
        terminal = report['diagnostics']['terminal_outcomes']
        assert not terminal['complete'] and terminal['unknown_symbols'] == ['UNKNOWN']
        assert terminal['counts'] == dict(input=4, evaluated=4, accepted=2, excluded=0, no_data=0, error_count=0, no_setup=0, filtered=1)
        trimmed = next(x for x in terminal['outcomes'] if x['terminal'] == 'filtered')
        assert trimmed['symbol'] == 'NONE' and trimmed['code'] == 'shortlist_cap'
        assert trimmed['thresholds']['cap'] == 2 and trimmed['observations']['rank'] == 3
        assert trimmed['observations']['strategy'] == 'breakout_base'
        baseline = await run(['AAA', 'BBB', 'NONE', 'UNKNOWN'])
        assert [x.model_dump() for x in rows.candidates] == [x.model_dump() for x in baseline.candidates]
        assert rows.pipeline == baseline.pipeline
    else:
        assert calls == inputs
        assert 'terminal_outcomes' not in report['diagnostics']
        assert rows.pipeline.scanned == 5


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,expected', [
    ('history', ('no_data', 'insufficient_history')),
    ('history_exception', ('error', 'data_processing_failed')),
    ('price_min', ('filtered', 'price_min')), ('price_max', ('filtered', 'price_max')),
    ('missing_price', ('no_data', 'missing_price')), ('score_status', ('filtered', 'score_status')),
    ('score_min', ('filtered', 'score_min')), ('trend_unmeasured', ('no_data', 'trend_unmeasured')),
    ('direction', ('filtered', 'direction_conviction')), ('signal', ('no_setup', 'setup_not_returned')),
    ('multi_signal', ('no_setup', 'setup_not_returned')), ('unsupported', ('error', 'unsupported_strategy')),
    ('intraday', ('no_data', 'insufficient_intraday_history')),
    ('regime_missing', ('no_data', 'regime_data_unavailable')),
    ('regime_exception', ('error', 'regime_fetch_failed')),
    ('headwind', ('filtered', 'regime_headwind')),
    ('backtest', ('filtered', 'backtest_gate')), ('confidence', ('filtered', 'confidence_gate')),
])
async def test_actual_pullback_worker_terminal_sites(monkeypatch, stage, expected):
    from tests.test_stock_scan_funnel import _card
    bars = [{'time': '2026-01-01', 'close': 100, 'high': 102, 'low': 98, 'volume': 1000}] * 60
    if stage == 'history': bars = []
    if stage == 'missing_price': bars = [{**b, 'close': 0} for b in bars]
    card = _card(10 if stage == 'direction' else 100)
    if stage == 'trend_unmeasured': card.rules[0].measured = False
    if stage == 'score_status': card.status = 'REJECT'
    monkeypatch.setattr(ss, 'get_historical_bars', AsyncMock(side_effect=RuntimeError('secret') if stage == 'history_exception' else None, return_value=bars))
    monkeypatch.setattr(ss, 'fetch_company_name_async', AsyncMock(return_value='Company'))
    monkeypatch.setattr(ss, 'fetch_price_async', AsyncMock(return_value=None))
    monkeypatch.setattr(ss, 'score_stock', lambda **_: card)
    monkeypatch.setattr(ss, 'load_direction_conviction_min_trend', lambda *_: 40)
    monkeypatch.setattr(ss, '_load_regime_cfg', lambda _: dict(timeframe='15min' if stage.startswith('regime_') else 'daily', min_obs=100))
    monkeypatch.setattr(ss, 'fetch_intraday_candles', lambda *_: (_ for _ in ()).throw(RuntimeError('secret')) if stage == 'regime_exception' else [])
    monkeypatch.setattr(ss, '_regime_data_drop', lambda *args: {'symbol': 'AAA', 'reason': 'secret'} if stage.startswith('regime_') else None)
    monkeypatch.setattr(ss, '_regime_headwind', lambda *_: stage == 'headwind')
    monkeypatch.setattr(ss, '_get_backtest_cached', lambda *_: SimpleNamespace(passes_gate=stage != 'backtest', summary_text='secret', win_rate=0, n_trades=0))
    monkeypatch.setattr(ss, 'get_cached', lambda *_: {'confidence': 0, 'sample_size': 100})
    monkeypatch.setattr(ss, 'interpret', lambda *a, **k: '')
    monkeypatch.setattr(ss, '_multi_signal', lambda *a, **k: (None, {'symbol': 'AAA', 'reason': 'secret'}))
    signal = SimpleNamespace()
    monkeypatch.setattr(ss, '_SIGNAL_FNS', {'pullback_ema': lambda *a, **k: None if stage == 'signal' else signal})
    strategy = 'mean_reversion_multi' if stage == 'multi_signal' else 'mean_reversion_vwap' if stage == 'intraday' else 'breakout_base' if stage == 'unsupported' else 'pullback_ema'
    req = StockScanRequest(symbols=['AAA'], universe=[], category='pullback', direction='Bullish', strategy=strategy, horizon='Swing', account_size=10000, risk_pct=1,
        min_price=110 if stage == 'price_min' else None, max_price=90 if stage == 'price_max' else None,
        min_stock_score=90 if stage == 'score_min' else None, confidence_reject_below=50 if stage == 'confidence' else None,
        regime_filter=stage == 'headwind')
    c = lc.Collector(request=req.model_dump(), terminal_enabled=True)
    token = lc._collector.set(c)
    try:
        lc.observe_resolution(['AAA'], ['AAA'], [])
        result = await ss._process_stock('AAA', req, 'run', {}, [], veto_days=0)
        assert isinstance(result, dict)
        terminal = c.terminal_snapshot()
        assert terminal['complete'], (stage, result, terminal)
        outcome = terminal['outcomes'][0]
        assert (outcome['terminal'], outcome['code']) == expected
        assert outcome['observations']['strategy'] == strategy
        assert 'secret' not in str(terminal)
    finally:
        lc._collector.reset(token)

@pytest.mark.asyncio
@pytest.mark.parametrize('category', ['prebreakout', 'fib', 'pullback'])
async def test_empty_resolution_complete_and_unresolved_failure_unavailable(lifecycle, category):
    lc, factory = lifecycle
    response = Response()
    async def empty():
        lc.observe_resolution([], [], [])
        return []
    await lc.run_reported_scan({}, category=category, trigger='manual', response=response, callback=empty)
    prior_id = response.headers[lc.HEADERS[0]]
    async def unresolved():
        raise RuntimeError('secret configuration')
    with pytest.raises(HTTPException):
        await lc.run_reported_scan({}, category=category, trigger='manual', callback=unresolved)
    async with factory() as db:
        latest = await get_latest(db, category)
        prior = await get_run(db, prior_id)
    assert latest['latest_attempt']['diagnostics_available'] is False
    assert latest['previous_report']['run_id'] == prior_id
    terminal = prior['diagnostics']['terminal_outcomes']
    assert terminal['complete'] and terminal['resolution_available']
    assert terminal['counts'] == dict(input=0, evaluated=0, accepted=0, excluded=0, no_data=0, error_count=0, no_setup=0, filtered=0)


@pytest.mark.asyncio
async def test_terminal_worker_overlap_keeps_category_run_identity(lifecycle):
    lc, factory = lifecycle
    started, release = asyncio.Event(), asyncio.Event()
    async def scan(symbol, blocked=False):
        lc.observe_resolution([symbol], [symbol], [])
        async def worker():
            lc.observe_evaluation(symbol)
            if blocked:
                started.set()
                await release.wait()
            lc.observe_terminal(symbol, 'no_setup', 'setup_not_returned')
        await asyncio.gather(worker())
        return []
    response = Response()
    older = asyncio.create_task(lc.run_reported_scan({}, category='fib', trigger='manual', callback=lambda: scan('OLD', True)))
    await started.wait()
    await lc.run_reported_scan({}, category='fib', trigger='manual', response=response, callback=lambda: scan('NEW'))
    other_response = Response()
    await lc.run_reported_scan({}, category='prebreakout', trigger='manual', response=other_response, callback=lambda: scan('OTHER'))
    release.set()
    await older
    async with factory() as db:
        latest = await get_latest(db, 'fib')
        other = await get_run(db, other_response.headers[lc.HEADERS[0]])
    assert latest['latest_attempt']['run_id'] == response.headers[lc.HEADERS[0]]
    assert latest['latest_attempt']['diagnostics']['terminal_outcomes']['input_symbols'] == ['NEW']
    assert other['diagnostics']['terminal_outcomes']['input_symbols'] == ['OTHER']


@pytest.mark.asyncio
async def test_terminal_save_failure_keeps_list_and_reports_unsaved(lifecycle, monkeypatch):
    lc, factory = lifecycle
    response = Response()
    async def core():
        lc.observe_resolution(['AAA'], ['AAA'], [])
        lc.observe_evaluation('AAA')
        lc.observe_terminal('AAA', 'accepted', 'candidate_returned')
        return [{'symbol': 'AAA', 'confidence': 0}]
    async def broken(*a, **k):
        raise scan_reports.ScanReportStorageError('safe')
    monkeypatch.setattr(lc.scan_reports, 'finish_run', broken)
    rows = await lc.run_reported_scan({}, category='fib', trigger='manual', response=response, callback=core)
    assert rows == [{'symbol': 'AAA', 'confidence': 0}]
    assert response.headers[lc.HEADERS[2]] == 'unavailable'
    assert response.headers[lc.HEADERS[0]]
    async with factory() as db:
        latest = await get_latest(db, 'fib')
    assert latest['latest_attempt']['status'] == 'running'
    assert latest['latest_attempt']['diagnostics_available'] is False


def test_unsafe_resolved_symbols_cannot_claim_complete_zero_and_integer_threshold_is_safe():
    c = lc.Collector(request={}, terminal_enabled=True)
    token = lc._collector.set(c)
    try:
        lc.observe_resolution(['AAA', 'https://secret-provider'], ['AAA', 'https://secret-provider'], [])
        assert c.terminal_snapshot() is None
        lc.observe_evaluation('AAA')
        lc.observe_terminal('AAA', 'filtered', 'shortlist_cap', thresholds={'cap': 10**400})
        snapshot = c.terminal_snapshot()
        assert not snapshot['complete'] and not snapshot['resolution_available']
        assert snapshot['counts']['input'] is None and snapshot['counts']['evaluated'] is None
        assert 'secret-provider' not in str(snapshot)
        assert scan_reports._encode(snapshot)
    finally:
        lc._collector.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('category', ['prebreakout', 'fib', 'pullback'])
async def test_partial_failed_or_cancelled_run_keeps_previous_usable_report(lifecycle, category, cancel):
    """#266 R3-1: partial terminal outcomes stay on the failed/cancelled attempt,
    but that attempt never replaces (and so never prunes) the last usable report."""
    from app.models.scan_report import ScanReportHead
    lc, factory = lifecycle
    async def good(symbol):
        lc.observe_resolution([symbol], [symbol], [])
        lc.observe_evaluation(symbol)
        lc.observe_terminal(symbol, 'accepted', 'candidate_returned')
        return [{'symbol': symbol}]
    response = Response()
    await lc.run_reported_scan({}, category=category, trigger='manual', response=response, callback=lambda: good('OLD'))
    old_id = response.headers[lc.HEADERS[0]]
    async def fail():
        lc.observe_resolution(['AAA', 'BBB', 'EXCL'], ['AAA', 'BBB'], [{'symbol': 'EXCL'}])
        lc.observe_evaluation('AAA')
        lc.observe_terminal('AAA', 'accepted', 'candidate_returned')
        raise asyncio.CancelledError if cancel else RuntimeError('secret')
    with pytest.raises(asyncio.CancelledError if cancel else HTTPException):
        await lc.run_reported_scan({}, category=category, trigger='manual', callback=fail)
    async with factory() as db:
        old = await get_run(db, old_id)
        latest = await get_latest(db, category)
        head = await db.get(ScanReportHead, category, populate_existing=True)
    assert old is not None and old['status'] == 'complete', 'prior complete report deleted'
    assert latest['previous_report'] is not None, 'previous_report lost'
    assert latest['previous_report']['run_id'] == old_id
    assert head.usable_id == old_id
    attempt = latest['latest_attempt']
    assert attempt['run_id'] != old_id and head.latest_id == attempt['run_id']
    assert attempt['status'] == ('cancelled' if cancel else 'failed')
    assert attempt['diagnostics_available'] is True
    terminal = attempt['diagnostics']['terminal_outcomes']
    assert terminal['complete'] is False
    assert terminal['counts']['accepted'] == 0
    assert terminal['counts']['excluded'] == 1
    assert terminal['unknown_symbols'] == ['AAA', 'BBB']
    failed_id = attempt['run_id']
    # A later complete run still promotes itself and prunes as before.
    response = Response()
    await lc.run_reported_scan({}, category=category, trigger='manual', response=response, callback=lambda: good('NEW'))
    new_id = response.headers[lc.HEADERS[0]]
    async with factory() as db:
        latest = await get_latest(db, category)
        head = await db.get(ScanReportHead, category, populate_existing=True)
        assert await get_run(db, old_id) is None
        assert await get_run(db, failed_id) is None
    assert head.latest_id == head.usable_id == new_id
    assert latest['latest_attempt']['run_id'] == new_id
    assert latest['previous_report'] is None
