"""Real durable store with deterministic scan cores, including transport lists."""
import asyncio
import json
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI, Response
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.scan_report import ScanReportBase
from app.schemas import ScanRequest, ScanResult, OptionsPipeline
from app.schemas.stock_scan import StockScanRequest, StockScanResult, StockPipeline
from app.services.scan_reports import get_latest, get_run


@pytest.fixture
async def routes(tmp_path, monkeypatch):
    from app.services import scan_report_lifecycle as lc
    from app.routers import scan, stock_scan
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}")
    async with engine.begin() as db:
        await db.run_sync(ScanReportBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(lc, 'AsyncSessionLocal', factory)
    monkeypatch.setattr(scan, '_upsert_session', AsyncMock())
    monkeypatch.setattr(stock_scan, '_upsert_stock_session', AsyncMock())
    async def options(req, db, **kwargs):
        lc.observe_resolution(req.universe, req.universe, [])
        return ScanResult(scan_id='12345678', timestamp='2026-10-13T00:00:00Z', candidates=[],
                          rejected=[{'symbol': req.universe[0], 'reason': 'Score gate: score 23 rejected'}],
                          pipeline=OptionsPipeline(scanned=1, failed_data=0, failed_pre_screen=0, no_chain=0, failed_score=1, failed_contracts=0, candidates=0))
    async def stocks(req, db, **kwargs):
        lc.observe_resolution(req.universe, req.universe, [])
        return StockScanResult(scan_id='12345678', timestamp='2026-10-13T00:00:00Z', candidates=[],
                               rejected=[{'symbol': req.universe[0], 'reason': 'REJECT score=23'}],
                               pipeline=StockPipeline(scanned=1, failed_history=0, failed_score=1, failed_signal=0, failed_backtest=0, candidates=0))
    async def lists(body):
        lc.observe_resolution(body.symbols, body.symbols, [])
        return [{'symbol': body.symbols[0], 'score': 43.25}]
    monkeypatch.setattr(scan, '_execute_scan_core', options)
    monkeypatch.setattr(stock_scan, '_execute_stock_scan_core', stocks)
    monkeypatch.setattr(stock_scan, '_prebreakout_scan_core', lists)
    monkeypatch.setattr(stock_scan, '_fib_pullback_scan_core', lists)
    yield lc, scan, stock_scan, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_all_five_categories_and_replacement_do_not_cross_ownership(routes):
    lc, scan, stock, factory = routes
    saved = {}
    await scan.run_scan(ScanRequest(universe=['AAPL'], direction='Bullish', horizon='Swing'), object())
    for category, symbol in [('stocks', 'MSFT'), ('pullback', 'NVDA')]:
        result = await stock.run_stock_scan(StockScanRequest(universe=[symbol], direction='Bullish', horizon='Swing', strategy='pullback_ema', category=category), object())
        assert result.report_run_id
    for fn, schema, symbol in [(stock.prebreakout_scan, stock.PreBreakoutScanRequest, 'META'), (stock.fib_pullback_scan, stock.FibPullbackScanRequest, 'TSLA')]:
        response = Response()
        result = await fn(schema(symbols=[symbol]), response)
        assert result == [{'symbol': symbol, 'score': 43.25}]
        assert response.headers['X-Scan-Report-Persistence'] == 'saved'
        async with factory() as db:
            assert (await get_run(db, response.headers['X-Scan-Report-Run-Id']))['result']['candidates'] == result
    async with factory() as db:
        for category in ['options', 'stocks', 'pullback', 'prebreakout', 'fib']:
            saved[category] = (await get_latest(db, category))['latest_attempt']
            assert saved[category]['trigger'] == 'manual'
    assert saved['options']['diagnostics']['pipeline'].get('failed_data') is not None
    assert saved['stocks']['diagnostics']['pipeline'].get('failed_history') is not None
    await scan.run_scan(ScanRequest(universe=['AMD'], direction='Bearish', horizon='Swing'), object())
    async with factory() as db:
        for category in ['stocks', 'pullback', 'prebreakout', 'fib']:
            assert (await get_latest(db, category))['latest_attempt'] == saved[category]


@pytest.mark.asyncio
async def test_stock_defaults_and_http_list_shape_server_trigger(routes):
    lc, scan, stock, factory = routes
    req = StockScanRequest(universe=['AAPL'], direction='Bullish', horizon='Swing', strategy='pullback_ema')
    assert req.category == 'stocks'
    app = FastAPI()
    app.include_router(stock.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/api/scan/prebreakout', json={'symbols': ['AAPL'], 'trigger': 'scheduled'})
    assert result.status_code == 200
    assert isinstance(result.json(), list)
    assert result.headers['X-Scan-Report-Persistence'] == 'saved'
    async with factory() as db:
        assert (await get_run(db, result.headers['X-Scan-Report-Run-Id']))['trigger'] == 'manual'


@pytest.mark.asyncio
async def test_legacy_get_omits_secret_values_without_rewriting_rows(routes):
    from app.models.scan_session import ScanSessionBase, ScanSession
    from app.routers.scan_reports import router
    from app.database import get_db
    from sqlalchemy import select
    lc, scan, stock, factory = routes
    async with factory.kw['bind'].begin() as db:
        await db.run_sync(ScanSessionBase.metadata.create_all)
    secret = 'https://user:password@broker'
    raw = json.dumps({'symbols': ['AAPL'], 'pipeline': {'scanned': 1}, 'reason': secret, 'score': 23.5})
    async with factory() as db:
        db.add(ScanSession(id='stock-current', status='complete', last_result_json=raw))
        await db.commit()
    async def dependency():
        async with factory() as db:
            yield db
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = dependency
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.get('/api/scan-reports/legacy')
    assert response.status_code == 200
    assert secret not in response.text
    assert response.json()[0]['unavailable_fields'] == ['result']
    assert response.json()[0]['result']['symbols'] == ['AAPL']
    assert response.json()[0]['result']['score'] == 23.5
    assert response.json()[0]['result']['pipeline'] == {'scanned': 1}
    assert response.json()[0]['unavailable_field_paths']['result'] == ['result.reason']
    async with factory() as db:
        assert (await db.get(ScanSession, 'stock-current')).last_result_json == raw


@pytest.mark.asyncio
async def test_real_schema_manual_report_preserves_broker_callback(routes, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.fixtures.tradecards import MOCK_CANDIDATE_CARDS
    from app.services.auto_trader import auto_trader
    from app.schemas import TradeCardData
    lc, scan, stock, factory = routes
    card = TradeCardData.model_validate(MOCK_CANDIDATE_CARDS[0]).model_copy(update={'finalStatus': 'PASS'})
    async def core(req, db, **kwargs):
        lc.observe_resolution([card.symbol], [card.symbol], [])
        return ScanResult(scan_id='abcdef12', timestamp='2026-10-13T00:00:00Z', candidates=[card], rejected=[])
    monkeypatch.setattr(scan, '_execute_scan_core', core)
    monkeypatch.setattr(auto_trader, 'get_state', lambda: SimpleNamespace(armed=True))
    fired = Mock(return_value=None)
    monkeypatch.setattr(auto_trader, 'maybe_fire_on_scan', fired)
    class DB:
        async def execute(self, *args):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        async def rollback(self):
            pass
    result = await scan.run_scan(ScanRequest(universe=[card.symbol], direction='Bullish', horizon='Swing'), DB())
    assert result.report_persistence == 'saved'
    fired.assert_called_once()
    assert result.candidates[0] == card
    async with factory() as db:
        report = await get_run(db, result.report_run_id)
    assert report['result']['candidates'][0]['symbol'] == card.symbol
    assert report['result']['candidates'][0]['stockScore'] == card.stockScore
    # The safe scheduled-history projection remains loadable for rank deltas.
    from app.services.scan_report_lifecycle import persisted_result
    parsed = ScanResult.model_validate(persisted_result(result))
    assert parsed.candidates[0].stockScore == card.stockScore
