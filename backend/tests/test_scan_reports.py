"""Durable report ownership: identities and contents, including restart and overlap."""
import asyncio
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.scan_report import ScanReportBase, ScanReport
from app.models.scan_session import ScanSessionBase, ScanSession
from app.services.scan_reports import (
    begin_run, finish_run, get_latest, get_run, get_legacy, recover_interrupted,
    ScanReportStorageError,
)


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reports.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(ScanReportBase.metadata.create_all)
        await conn.run_sync(ScanSessionBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def start(factory, category='options', **kw):
    async with factory() as db:
        return await begin_run(db, category=category, trigger='manual', inputs={'symbols': ['AAPL'], 'horizon': 'swing', **kw})


async def finish(factory, run, **kw):
    async with factory() as db:
        return await finish_run(db, run['run_id'], status='complete', diagnostics={'scanned': 1, 'accepted': ['AAPL']}, result={'symbols': ['AAPL']}, **kw)


@pytest.mark.asyncio
async def test_five_categories_restart_and_frozen_inputs(store):
    saved = {}
    for category in ('options', 'stocks', 'prebreakout', 'pullback', 'fib'):
        run = await start(store, category, marker=category)
        saved[category] = await finish(store, run)
    await finish(store, await start(store, marker='replacement'))
    async with store() as db:
        for category, report in saved.items():
            latest = await get_latest(db, category)
            if category == 'options':
                assert latest['latest_attempt']['inputs']['marker'] == 'replacement'
            else:
                assert latest['latest_attempt'] == report
                assert await get_run(db, report['run_id']) == report


@pytest.mark.asyncio
async def test_late_completion_cannot_own_latest_or_previous(store):
    first = await start(store)
    await finish(store, first)
    old = await start(store)
    new = await start(store)
    await finish(store, old)
    async with store() as db:
        latest = await get_latest(db, 'options')
        assert latest['latest_attempt']['run_id'] == new['run_id']
        assert latest['previous_report']['run_id'] == first['run_id']
    await finish(store, new)
    async with store() as db:
        assert (await get_latest(db, 'options'))['previous_report'] is None
        rows = (await db.execute(select(ScanReport))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_failure_and_missing_diagnostics_preserve_previous(store):
    prior = await finish(store, await start(store))
    run = await start(store)
    async with store() as db:
        failed = await finish_run(db, run['run_id'], status='failed', error_code='scan_failed')
    assert failed['diagnostics_available'] is False
    assert failed['diagnostics'] is None
    async with store() as db:
        latest = await get_latest(db, 'options')
        assert latest['latest_attempt'] == failed
        assert latest['previous_report'] == prior


@pytest.mark.asyncio
async def test_zero_candidates_and_terminal_immutable(store):
    run = await start(store)
    async with store() as db:
        terminal = await finish_run(db, run['run_id'], status='complete', result={'symbols': []}, diagnostics={'scanned': 1, 'accepted': []})
    assert terminal['result']['symbols'] == []
    async with store() as db:
        with pytest.raises(ValueError, match='terminal'):
            await finish_run(db, run['run_id'], status='failed')
    async with store() as db:
        assert await get_run(db, run['run_id']) == terminal


@pytest.mark.asyncio
async def test_generation_transactional_parallel_and_retention(store):
    runs = await asyncio.gather(*(start(store) for _ in range(8)))
    assert sorted(r['generation'] for r in runs) == list(range(1, 9))
    async with store() as db:
        latest = await get_latest(db, 'options')
        assert latest['latest_attempt']['generation'] == 8
        assert len((await db.execute(select(ScanReport))).scalars().all()) == 8
    for run in runs:
        await finish(store, run)
    async with store() as db:
        assert len((await db.execute(select(ScanReport))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_recover_interrupted_and_legacy_preserved(store):
    run = await start(store)
    async with store() as db:
        db.add(ScanSession(id='stock-current', status='complete', last_request_json='{"strategy":"pullback"}', last_result_json='{"symbols":["OLD"]}'))
        await db.commit()
        assert await recover_interrupted(db) == 1
    async with store() as db:
        latest = await get_run(db, run['run_id'])
        assert latest['status'] == 'interrupted'
        assert latest['diagnostics_available'] is False
        legacy = await get_legacy(db)
        assert legacy[0]['category'] == 'legacy/unclassified'
        assert legacy[0]['result'] == {'symbols': ['OLD']}
        assert (await db.get(ScanSession, 'stock-current')).last_result_json == '{"symbols":["OLD"]}'


@pytest.mark.asyncio
async def test_secrets_and_exception_payloads_not_stored(store):
    with pytest.raises(ValueError):
        await start(store, api_token='secret')
    run = await start(store)
    async with store() as db:
        with pytest.raises(ValueError):
            await finish_run(db, run['run_id'], status='failed', error_code='https://secret:password@broker')
    async with store() as db:
        with pytest.raises(ValueError):
            await finish_run(db, run['run_id'], status='failed', diagnostics={'exception': 'secret token payload'})
    async with store() as db:
        assert (await get_run(db, run['run_id']))['status'] == 'running'


@pytest.mark.asyncio
async def test_storage_failure_is_visible(store):
    async with store() as db:
        from sqlalchemy import text
        await db.execute(text('DROP TABLE scan_report_heads'))
        await db.commit()
        with pytest.raises(ScanReportStorageError, match='storage unavailable'):
            await begin_run(db, category='options', trigger='manual', inputs={})


@pytest.mark.asyncio
async def test_terminal_observed_inputs_preserve_dispatch_snapshot(store):
    mutable = {'symbols': ['AAPL'], 'params': {'threshold': 3}}
    async with store() as db:
        run = await begin_run(db, category='stocks', trigger='scheduled', inputs=mutable)
    mutable['params']['threshold'] = 100
    resolved = {'symbols': ['AAPL', 'MSFT'], 'effective_params': {'threshold': 3}}
    async with store() as db:
        report = await finish_run(db, run['run_id'], status='complete', inputs=resolved,
                                 diagnostics={'scanned': 2}, result={'symbols': []})
    resolved['effective_params']['threshold'] = 200
    assert report['dispatch_inputs'] == {'symbols': ['AAPL'], 'params': {'threshold': 3}}
    assert report['inputs']['effective_params']['threshold'] == 3
    async with store() as db:
        assert await get_run(db, run['run_id']) == report


@pytest.mark.asyncio
async def test_readonly_api_has_matching_contents_and_storage_failure(store):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import get_db
    from app.routers.scan_reports import router
    app = FastAPI()
    app.include_router(router)
    async def override():
        async with store() as db:
            yield db
    app.dependency_overrides[get_db] = override
    report = await finish(store, await start(store))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        latest = await client.get('/api/scan-reports/latest/options')
        assert latest.json()['latest_attempt'] == report
        assert (await client.get(f"/api/scan-reports/runs/{report['run_id']}" )).json() == report
        assert (await client.get('/api/scan-reports/runs/missing')).status_code == 404
        assert (await client.get('/api/scan-reports/latest/invalid')).status_code == 422
        assert (await client.post('/api/scan-reports/latest/options')).status_code == 405
        async with store() as db:
            from sqlalchemy import text
            await db.execute(text('DROP TABLE scan_report_heads'))
            await db.commit()
        response = await client.get('/api/scan-reports/latest/options')
        assert response.status_code == 503
        assert response.json() == {'detail': 'Scan report storage unavailable'}


def test_additive_migration_preserves_legacy(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration_path = Path(__file__).parents[1] / 'migrations/versions/a93b8d24f760_add_isolated_scan_reports.py'
    spec = importlib.util.spec_from_file_location('scan_report_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        ScanSessionBase.metadata.create_all(conn)
        conn.execute(text("INSERT INTO scan_sessions (id,status,last_result_json) VALUES ('stock-current','complete','legacy untouched')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert {'scan_reports', 'scan_report_heads', 'scan_sessions'} <= set(inspect(conn).get_table_names())
        assert conn.execute(text('SELECT last_result_json FROM scan_sessions')).scalar_one() == 'legacy untouched'
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert conn.execute(text('SELECT last_result_json FROM scan_sessions')).scalar_one() == 'legacy untouched'
    engine.dispose()
