"""Frozen server evidence is fetched only by its original opaque identity."""
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import get_db
from app.models.scan_report import ScanReportBase
from app.services.strategy_backtest import run_strategy_backtest_detailed
from app.services.strategy_backtest_details import ENGINE_CONTRACT_VERSION
from tests.test_strategy_backtest_details import bars


@pytest.fixture
async def store(tmp_path):
    from app.models.backtest_artifact import BacktestArtifact  # noqa: F401
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'artifacts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(ScanReportBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def detail(direction='Bullish'):
    return run_strategy_backtest_detailed(bars(), strategy='pullback_ema', direction=direction,
                                         params={'tolerance': 0}, commission=.002)


def identity(direction='Bullish'):
    return dict(scan_id=str(uuid4()), report_run_id=str(uuid4()), symbol='AAPL',
                strategy='pullback_ema', direction=direction, horizon='Swing', interval='1d',
                bars_basis_version='test-basis', input_hash='a' * 64,
                engine_contract_version=ENGINE_CONTRACT_VERSION)


@pytest.mark.asyncio
async def test_roundtrip_detaches_all_evidence_and_new_run_ids(store):
    from app.services import backtest_artifacts as artifacts
    evidence, ident = detail(), identity()
    async with store() as db:
        first = await artifacts.save_artifact(db, detail=evidence, identity=ident)
    evidence.configuration['commission'] = .9
    ident['direction'] = 'Bearish'
    first['detail']['equity'][0]['equity'] = -1
    async with store() as db:
        frozen = await artifacts.get_artifact(db, first['artifact_id'], 'AAPL')
    assert frozen['schema_version'] == 1 and frozen['provenance'] == 'original'
    assert frozen['identity']['direction'] == 'Bullish'
    assert frozen['detail']['configuration']['commission'] == .002
    assert frozen['detail']['equity'][0]['equity'] == 100000
    assert frozen['detail']['input_candles'] == frozen['detail']['candles']
    assert frozen['currency'] is None
    async with store() as db:
        second = await artifacts.save_artifact(db, detail=detail(), identity=identity())
    assert second['artifact_id'] != first['artifact_id']


@pytest.mark.asyncio
async def test_finiteness_rejects_without_partial_write(store):
    from app.services import backtest_artifacts as artifacts
    from app.models.backtest_artifact import BacktestArtifact
    evidence = detail()
    evidence.configuration['commission'] = float('nan')
    async with store() as db:
        with pytest.raises(ValueError):
            await artifacts.save_artifact(db, detail=evidence, identity=identity())
        assert not (await db.execute(select(BacktestArtifact))).scalars().all()


@pytest.mark.asyncio
async def test_expiry_tombstone_distinguishes_missing_and_symbol_mismatch(store, monkeypatch):
    from app.services import backtest_artifacts as artifacts
    from app.models.backtest_artifact import BacktestArtifact
    now = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(artifacts.time, 'time', lambda: now)
    async with store() as db:
        saved = await artifacts.save_artifact(db, detail=detail(), identity=identity())
    now += 30 * 86400 + 1
    async with store() as db:
        await artifacts.cleanup_expired(db)
    async with store() as db:
        row = await db.get(BacktestArtifact, saved['artifact_id'])
        assert row.payload_json is None
        with pytest.raises(artifacts.ArtifactExpired):
            await artifacts.get_artifact(db, saved['artifact_id'], 'AAPL')
        assert await artifacts.get_artifact(db, saved['artifact_id'], 'MSFT') is None
        assert await artifacts.get_artifact(db, str(uuid4()), 'AAPL') is None


@pytest.mark.asyncio
async def test_api_exact_identity_statuses_and_safe_failure(store, monkeypatch):
    from app.routers.backtest_artifacts import router
    from app.services import backtest_artifacts as artifacts
    app = FastAPI()
    app.include_router(router)
    async def db_override():
        async with store() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    async with store() as db:
        saved = await artifacts.save_artifact(db, detail=detail(), identity=identity())
    path = '/api/backtest-artifacts/' + saved['artifact_id']
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get(path, params={'symbol': 'AAPL'})).json() == saved
        assert (await client.get(path, params={'symbol': 'MSFT'})).status_code == 404
        assert (await client.get('/api/backtest-artifacts/not-uuid', params={'symbol': 'AAPL'})).status_code == 422
        assert (await client.get('/api/backtest-artifacts/' + str(uuid4()), params={'symbol': 'AAPL'})).status_code == 404
        monkeypatch.setattr(artifacts.time, 'time', lambda: saved['expires_at'] + 1)
        assert (await client.get(path, params={'symbol': 'AAPL'})).status_code == 410
        async def fail(*args):
            raise artifacts.ArtifactStorageError('safe')
        monkeypatch.setattr(artifacts, 'get_artifact', fail)
        response = await client.get(path, params={'symbol': 'AAPL'})
        assert response.status_code == 503 and response.json() == {'detail': 'Backtest artifact storage unavailable'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['unsupported', 'insufficient_history', 'invalid_input', 'failed', 'invalid_evidence'])
async def test_non_success_never_persists_a_fake_curve(store, status):
    from app.services import backtest_artifacts as artifacts
    from app.models.backtest_artifact import BacktestArtifact
    async with store() as db:
        with pytest.raises(ValueError):
            await artifacts.save_artifact(db, detail=replace(detail(), status=status), identity=identity())
        assert not (await db.execute(select(BacktestArtifact))).scalars().all()


@pytest.mark.asyncio
async def test_zero_trade_curve_roundtrip_is_real_and_finite(store):
    from app.services import backtest_artifacts as artifacts
    evidence = detail()
    assert evidence.status == 'success' and evidence.summary.n_trades == 0
    async with store() as db:
        saved = await artifacts.save_artifact(db, detail=evidence, identity=identity())
    assert len(saved['detail']['equity']) == 150
    assert saved['detail']['equity'][-1]['strategy_index'] == 100
    assert saved['detail']['trades'] == []
