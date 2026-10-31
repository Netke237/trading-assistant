"""Read-only regime source tests with literal expected rows and dates."""
import asyncio
import copy
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services import daily_regime_history as history
from app.services.money_config import RegimeConfigError

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
DOC = {'regime': {
    'swing': {'timeframe': 'daily', 'lookback': 20, 'window': 500, 'min_obs': 100},
    'position': {'timeframe': 'daily', 'lookback': 50, 'window': 750, 'min_obs': 100},
}}


def test_uniform_count_and_growth():
    assert history.daily_regime_bar_count(DOC) == 800
    doc = copy.deepcopy(DOC)
    doc['regime']['position']['window'] = 1100
    assert history.daily_regime_bar_count(doc) == 1150
    doc['regime']['extra'] = dict(doc['regime']['swing'], window=1500)
    assert history.daily_regime_bar_count(doc) == 1520


@pytest.mark.parametrize('value', [None, True, 0, -1, 2.5, float('inf'), float('nan'), '750'])
def test_config_errors_are_typed(value):
    doc = copy.deepcopy(DOC)
    doc['regime']['position']['window'] = value
    with pytest.raises(RegimeConfigError):
        history.daily_regime_bar_count(doc)


@pytest.mark.parametrize('doc', [{}, {'regime': None}, {'regime': []}, {'regime': {'swing': {}}}, None])
def test_missing_config_is_not_defaulted(doc):
    with pytest.raises(RegimeConfigError):
        history.daily_regime_bar_count(doc)


@pytest.fixture
def stored(tmp_path):
    url = f'sqlite+aiosqlite:///{tmp_path / "history.db"}'
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(OhlcvBase.metadata.create_all)
        async with sessions() as db:
            db.add_all([OhlcvDailyModel(symbol='AAA', date=date(2020, 1, 1) + timedelta(days=i),
                        open=100, high=120, low=80, close=110, volume=123,
                        adj_factor=None if i % 2 else 0.5) for i in range(1000)])
            db.add_all([OhlcvDailyModel(symbol=symbol, date=day, open=1, high=2,
                        low=1, close=2, volume=1, adj_factor=1)
                        for symbol, day in [('OTHER', date(2022, 9, 26)), ('AAA', date(2026, 10, 26))]])
            await db.commit()
    asyncio.run(seed())
    yield url, engine, sessions
    asyncio.run(engine.dispose())


def test_latest_800_literal_dates_adjustments_and_read_only(stored):
    _, engine, sessions = stored
    statements = []
    event.listen(engine.sync_engine, 'before_cursor_execute', lambda conn, cursor, statement, parameters, context, executemany: statements.append((statement, parameters)))
    bars = asyncio.run(history.get_daily_regime_bars('AAA', 800, now=NOW, sessions=sessions))
    assert len(bars) == 800
    assert bars[0] == {'time': '2020-07-19', 'open': 50.0, 'high': 60.0, 'low': 40.0, 'close': 55.0, 'volume': 123}
    assert bars[-1] == {'time': '2022-09-26', 'open': 100.0, 'high': 120.0, 'low': 80.0, 'close': 110.0, 'volume': 123}
    assert all(a['time'] < b['time'] for a, b in zip(bars, bars[1:]))
    assert len(statements) == 1
    sql, params = statements[0]
    assert sql.lstrip().upper().startswith('SELECT')
    assert 'ORDER BY ohlcv_daily.date DESC' in sql and 'LIMIT' in sql
    assert params == ('AAA', '2026-10-23', 800, 0)


def test_stale_empty_and_independent_sync_parity(stored):
    url, _, sessions = stored
    bars = asyncio.run(history.get_daily_regime_bars('AAA', 800, now=NOW, sessions=sessions))
    for _ in range(3):
        assert json.dumps(history.get_daily_regime_bars_sync('AAA', 800, now=NOW, database_url=url)) == json.dumps(bars)
    assert asyncio.run(history.get_daily_regime_bars('ABSENT', 800, now=NOW, sessions=sessions)) == []
    assert history.get_daily_regime_bars_sync('ABSENT', 800, now=NOW, database_url=url) == []


@pytest.mark.parametrize('instant,end', [
    ('2026-10-23T19:59:59+00:00', '2026-10-22'),
    ('2026-10-23T21:59:59+00:00', '2026-10-22'),
    ('2026-10-23T22:00:00+00:00', '2026-10-23'),
    ('2026-10-25T01:00:00+00:00', '2026-10-23'),
    ('2026-03-09T21:59:59+00:00', '2026-03-06'),
    ('2026-03-09T22:00:00+00:00', '2026-03-09'),
    ('2026-11-02T22:59:59+00:00', '2026-10-30'),
    ('2026-11-02T23:00:00+00:00', '2026-11-02'),
])
def test_settlement_market_date_weekend_and_dst(instant, end):
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def execute(self, query):
            assert query.compile().params['date_1'].isoformat() == end
            raise RuntimeError('query reached')
    with pytest.raises(RuntimeError, match='query reached'):
        asyncio.run(history.get_daily_regime_bars('AAA', 800, now=datetime.fromisoformat(instant), sessions=Session))


@pytest.mark.parametrize('count', [True, 0, -1, 800.0, float('inf'), '800', None])
def test_invalid_effective_count_never_reads(count):
    with pytest.raises(ValueError):
        asyncio.run(history.get_daily_regime_bars('AAA', count, sessions=lambda: pytest.fail('opened session')))


def test_naive_time_and_running_loop_refused(stored):
    url, _, sessions = stored
    with pytest.raises(ValueError, match='aware'):
        asyncio.run(history.get_daily_regime_bars('AAA', 800, now=datetime(2026, 10, 25), sessions=sessions))
    async def running():
        with pytest.raises(RuntimeError, match='event loop'):
            history.get_daily_regime_bars_sync('AAA', 800, database_url=url)
    asyncio.run(running())


def test_sync_private_nullpool_disposed_on_query_failure(tmp_path, monkeypatch):
    created = []
    disposed = []
    original_dispose = AsyncEngine.dispose
    async def dispose(engine):
        disposed.append(engine)
        await original_dispose(engine)
    monkeypatch.setattr(AsyncEngine, 'dispose', dispose)
    def create(*args, **kwargs):
        assert kwargs['poolclass'] is NullPool
        engine = create_async_engine(*args, **kwargs)
        created.append(engine)
        return engine
    monkeypatch.setattr(history, 'create_async_engine', create)
    with pytest.raises(Exception, match='no such table'):
        history.get_daily_regime_bars_sync('AAA', 800, database_url=f'sqlite+aiosqlite:///{tmp_path / "empty.db"}')
    assert len(created) == 1
    assert disposed == created


def test_sparse_split_dividend_and_null_literal_adjustments(stored):
    _, _, sessions = stored
    async def exercise():
        async with sessions() as db:
            db.add_all([
                OhlcvDailyModel(symbol='SPARSE', date=date(2020, 2, 3), open=100.0001,
                    high=200.0002, low=50.0003, close=150.0004, volume=987654, adj_factor=0.12345678),
                OhlcvDailyModel(symbol='SPARSE', date=date(2024, 9, 5), open=100.1234,
                    high=102.3456, low=98.7654, close=101.2345, volume=345, adj_factor=None),
            ])
            await db.commit()
        return await history.get_daily_regime_bars('SPARSE', 800, now=NOW, sessions=sessions)
    assert asyncio.run(exercise()) == [
        {'time': '2020-02-03', 'open': 12.34569, 'high': 24.691381,
         'low': 6.172876, 'close': 18.518566, 'volume': 987654},
        {'time': '2024-09-05', 'open': 100.1234, 'high': 102.3456,
         'low': 98.7654, 'close': 101.2345, 'volume': 345},
    ]


def test_async_resolves_application_factory_at_call_time(stored, monkeypatch):
    from app import database
    _, _, sessions = stored
    monkeypatch.setattr(database, 'AsyncSessionLocal', sessions)
    assert len(asyncio.run(history.get_daily_regime_bars('AAA', 800, now=NOW))) == 800


def test_worker_threads_private_engine_success_cleanup(stored, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    url, _, _ = stored
    engines = []
    disposed = []
    original_dispose = AsyncEngine.dispose
    async def dispose(engine):
        disposed.append(engine)
        await original_dispose(engine)
    monkeypatch.setattr(AsyncEngine, 'dispose', dispose)
    def create(*args, **kwargs):
        assert kwargs['poolclass'] is NullPool
        engine = create_async_engine(*args, **kwargs)
        engines.append(engine)
        return engine
    monkeypatch.setattr(history, 'create_async_engine', create)
    with ThreadPoolExecutor(max_workers=1) as worker:
        for _ in range(3):
            bars = worker.submit(history.get_daily_regime_bars_sync, 'AAA', 800,
                                 now=NOW, database_url=url).result(timeout=10)
            assert len(bars) == 800 and bars[0]['time'] == '2020-07-19'
    assert len(engines) == 3
    assert disposed == engines
