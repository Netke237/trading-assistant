"""Lifecycle identity, isolation and credential-free durable projections."""
import asyncio
import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.schemas import ScanResult
from app.services.scan_reports import get_latest, get_run
from app.models.scan_report import ScanReportBase


def test_scan_result_has_durable_identity():
    result = ScanResult(scan_id='legacy', timestamp='now', candidates=[], rejected=[])
    assert 'report_run_id' in result.model_dump()
    assert 'report_persistence' in result.model_dump()


@pytest.fixture
async def lifecycle(tmp_path, monkeypatch):
    from app.services import scan_report_lifecycle as lc
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}")
    async with engine.begin() as db:
        await db.run_sync(ScanReportBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(lc, 'AsyncSessionLocal', factory)
    yield lc, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_started_before_callback_and_zero_candidates_complete(lifecycle):
    lc, factory = lifecycle
    async def core():
        async with factory() as db:
            assert (await get_latest(db, 'options'))['latest_attempt']['status'] == 'running'
        lc.observe_resolution(['AAPL'], ['AAPL'], [])
        return ScanResult(scan_id='core', timestamp='now', candidates=[], rejected=[], pipeline=None)
    result = await lc.run_reported_scan({'universe': ['AAPL']}, category='options', trigger='manual', callback=core)
    async with factory() as db:
        run = await get_run(db, result.report_run_id)
    assert run['status'] == 'complete'
    assert run['inputs']['dispatched_symbols'] == ['AAPL']
    assert run['diagnostics_available'] is False


@pytest.mark.asyncio
async def test_context_isolation_and_observations_frozen(lifecycle):
    lc, factory = lifecycle
    async def run(category, symbol):
        settings = {'threshold': 23.5}
        async def core():
            lc.observe_resolution([symbol], [symbol], [])
            lc.observe_configuration('test_gate', settings, symbol=symbol)
            await asyncio.sleep(0)
            settings['threshold'] = 99
            return ScanResult(scan_id=symbol, timestamp='now', candidates=[], rejected=[])
        return await lc.run_reported_scan({'symbols': [symbol]}, category=category, trigger='manual', callback=core)
    results = await asyncio.gather(run('options', 'AAPL'), run('stocks', 'MSFT'))
    async with factory() as db:
        for result, symbol in zip(results, ['AAPL', 'MSFT']):
            report = await get_run(db, result.report_run_id)
            assert report['inputs']['dispatched_symbols'] == [symbol]
            assert report['inputs']['configuration_observations'][0]['values']['threshold'] == 23.5
            assert report['inputs']['configuration_observations'][0]['symbol'] == symbol


@pytest.mark.asyncio
async def test_secret_values_omitted_from_all_duplicate_paths(lifecycle):
    lc, factory = lifecycle
    secret = 'https://user:password@broker'
    req = {'universe': ['AAPL', secret], 'overrides': {'rsi_method': secret, 'rsi_period': 14, 'unknown': secret}}
    async def core():
        lc.observe_resolution(['AAPL'], [], [{'symbol': 'AAPL', 'reason': secret}])
        lc.observe_configuration('gate', {'method': secret, 'threshold': 25.3})
        return ScanResult(scan_id='core', timestamp='now', candidates=[], rejected=[{'symbol': 'AAPL', 'reason': 'Score gate: '+secret}])
    result = await lc.run_reported_scan(req, category='options', trigger='manual', callback=core)
    async with factory() as db:
        run = await get_run(db, result.report_run_id)
    assert secret not in json.dumps(run)
    assert run['dispatch_inputs']['request']['overrides']['rsi_period'] == 14
    assert run['inputs']['excluded'][0]['reason_unavailable']
    assert run['inputs']['effective_configuration_complete'] is False
    assert run['result']['rejected'][0]['reason_unavailable']


@pytest.mark.asyncio
async def test_cancellation_finishes_and_resets_collector(lifecycle):
    lc, factory = lifecycle
    async def core():
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await lc.run_reported_scan({}, category='fib', trigger='manual', callback=core)
    async with factory() as db:
        latest = await get_latest(db, 'fib')
    assert latest['latest_attempt']['status'] == 'cancelled'
    assert lc.current_collector() is None


@pytest.mark.asyncio
async def test_failure_keeps_previous_report_and_safe_code(lifecycle):
    from fastapi import HTTPException
    lc, factory = lifecycle
    async def success():
        lc.observe_resolution(['AAPL'], ['AAPL'], [])
        return []
    saved = await lc.run_reported_scan({}, category='prebreakout', trigger='manual', callback=success)
    async with factory() as db:
        previous = (await get_latest(db, 'prebreakout'))['latest_attempt']
    async def fail():
        raise RuntimeError('https://user:password@broker')
    with pytest.raises(HTTPException) as exc:
        await lc.run_reported_scan({}, category='prebreakout', trigger='manual', callback=fail)
    assert exc.value.detail == 'Scan failed'
    async with factory() as db:
        latest = await get_latest(db, 'prebreakout')
    assert latest['previous_report'] == previous
    assert latest['latest_attempt']['error_code'] == 'scan_failed'
    assert latest['latest_attempt']['diagnostics_available'] is False


@pytest.mark.asyncio
async def test_begin_failure_refuses_work_and_finish_failure_marks_current_result(lifecycle, monkeypatch):
    from app.services.scan_reports import ScanReportStorageError
    from fastapi import HTTPException
    lc, factory = lifecycle
    called = []
    async def core():
        called.append(True)
        return ScanResult(scan_id='current', timestamp='now', candidates=[], rejected=[])
    async def broken(*args, **kwargs):
        raise ScanReportStorageError('safe')
    begin = lc.scan_reports.begin_run
    monkeypatch.setattr(lc.scan_reports, 'begin_run', broken)
    with pytest.raises(HTTPException) as exc:
        await lc.run_reported_scan({}, category='options', trigger='manual', callback=core)
    assert exc.value.status_code == 503
    assert called == []
    monkeypatch.setattr(lc.scan_reports, 'begin_run', begin)
    monkeypatch.setattr(lc.scan_reports, 'finish_run', broken)
    result = await lc.run_reported_scan({}, category='options', trigger='manual', callback=core)
    assert result.scan_id == 'current'
    assert result.report_run_id
    assert result.report_persistence == 'unavailable'


@pytest.mark.asyncio
async def test_reverse_completion_and_scheduled_overlap(lifecycle):
    lc, factory = lifecycle
    started, release = asyncio.Event(), asyncio.Event()
    async def older_core():
        lc.observe_resolution(['AAPL'], ['AAPL'], [])
        started.set()
        await release.wait()
        return []
    older = asyncio.create_task(lc.run_reported_scan({}, category='stocks', trigger='scheduled', callback=older_core))
    await started.wait()
    async def newer_core():
        lc.observe_resolution(['MSFT'], ['MSFT'], [])
        return []
    await lc.run_reported_scan({}, category='stocks', trigger='manual', callback=newer_core)
    async with factory() as db:
        newer = (await get_latest(db, 'stocks'))['latest_attempt']
    release.set()
    await older
    async with factory() as db:
        assert (await get_latest(db, 'stocks'))['latest_attempt'] == newer
    assert newer['trigger'] == 'manual'
    assert newer['inputs']['dispatched_symbols'] == ['MSFT']


@pytest.mark.asyncio
async def test_returned_failed_state_and_proven_no_data(lifecycle):
    lc, factory = lifecycle
    async def core():
        return ScanResult(scan_id='failed', timestamp='now', candidates=[], rejected=[], state='FAILED')
    result = await lc.run_reported_scan({}, category='options', trigger='manual', callback=core)
    async with factory() as db:
        assert (await get_run(db, result.report_run_id))['status'] == 'failed'
    async def no_data():
        lc.observe_no_data()
        return []
    await lc.run_reported_scan({}, category='fib', trigger='manual', callback=no_data)
    async with factory() as db:
        assert (await get_latest(db, 'fib'))['latest_attempt']['status'] == 'no_data'


@pytest.mark.asyncio
async def test_interrupted_recovery(lifecycle):
    lc, factory = lifecycle
    async with factory() as db:
        await lc.scan_reports.begin_run(db, category='options', trigger='manual', inputs={})
    assert await lc.recover_interrupted() == 1
    async with factory() as db:
        assert (await get_latest(db, 'options'))['latest_attempt']['status'] == 'interrupted'
