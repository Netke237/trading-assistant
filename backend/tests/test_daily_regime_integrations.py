"""Actual callers use independently expected adjusted isolated DB rows."""
import asyncio
import dataclasses
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.routers import scan, stock_scan as ss
from app.services import daily_regime_history as history, auto_trader as at
from app.services.regime_omm import compute_omm
from app.schemas.stock_scan import StockAnalysisRequest, StockScanRequest
from tests.test_a4_intraday_regime_bars import _armed
from tests.test_a5_analysis_mirrors_scan import _offline, _BARS
NOW = datetime(2026,10,25,12,tzinfo=timezone.utc)
EXPECTED = [100.0+i/2 for i in range(200,1000)]
@pytest.fixture
async def source(tmp_path, monkeypatch):
    url=f'sqlite+aiosqlite:///{tmp_path / "regime.db"}'
    engine=create_async_engine(url,poolclass=NullPool)
    sessions=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
    async with sessions() as db:
        db.add_all([OhlcvDailyModel(symbol='TEST',date=date(2020,1,1)+timedelta(days=i),open=200+i,high=202+i,low=198+i,close=200+i,volume=1000,adj_factor=.5) for i in range(1000)])
        await db.commit()
    async def read(symbol,count):
        return await history.get_daily_regime_bars(symbol,count,now=NOW,sessions=sessions)
    def sync(symbol,count):
        return history.get_daily_regime_bars_sync(symbol,count,now=NOW,database_url=url)
    for module in (scan,ss):
        monkeypatch.setattr(module,'get_daily_regime_bars',read,raising=False)
    monkeypatch.setattr(at,'get_daily_regime_bars_sync',sync,raising=False)
    yield read
    await engine.dispose()
async def options(monkeypatch,direction,horizon,sem=None):
    for name,value in [('fetch_price_async',101.),('fetch_company_name_async','Test'),('fetch_fundamentals_calendar',{}),('fetch_calendar_dates_async',(None,None))]:
        monkeypatch.setattr(scan,name,AsyncMock(return_value=value))
    monkeypatch.setattr(scan,'_compute_dhmm',lambda bars:None)
    monkeypatch.setattr(scan,'log_event',lambda *a,**k:None)
    monkeypatch.setattr(scan,'_direction_conviction_drop',lambda *a,**k:None)
    monkeypatch.setattr(scan,'fetch_option_chain_async',AsyncMock(return_value=[{'strike':100,'ivRank':30}]))
    score=MagicMock(side_effect=[MagicMock(status='PASS'),MagicMock(status='REJECT',rules=[],score=20)])
    monkeypatch.setattr(scan,'score_stock',score)
    await scan._process_symbol(symbol='TEST',direction=direction,horizon=horizon,client=AsyncMock(),sem=sem if sem is not None else asyncio.Semaphore(1),scan_id='parity',bars_map={'TEST':_BARS})
    return score
@pytest.mark.asyncio
@pytest.mark.parametrize('horizon',['Swing','Position'])
@pytest.mark.parametrize('direction',['Bullish','Bearish'])
async def test_actual_callers_identical_adjusted_series(source,monkeypatch,horizon,direction):
    seen=[]
    def spy(closes,**kwargs):
        seen.append((list(closes),kwargs))
        return compute_omm(closes,**kwargs)
    monkeypatch.setattr(scan,'_compute_omm',spy)
    scores=await options(monkeypatch,direction,horizon)
    assert seen[0][0]==EXPECTED
    direct=compute_omm(EXPECTED,**seen[0][1])
    assert direct is not None
    assert scores.call_count==2
    for call in scores.call_args_list:
        assert call.args[3] is _BARS
        assert call.kwargs['regime_signal']['conviction_pct']==direct.conviction_pct
    _offline(monkeypatch)
    monkeypatch.setattr(ss,"get_daily_regime_bars",source)
    monkeypatch.setattr(ss,'compute_omm',spy)
    stock_score=MagicMock(return_value=MagicMock(status='REJECT',score=20))
    monkeypatch.setattr(ss,'score_stock',stock_score)
    await ss._process_stock('TEST',StockScanRequest(universe=['TEST'],strategy='pullback_ema',direction=direction,horizon=horizon),'parity',{'TEST':{'last':101}},[])
    assert seen[-1][0]==EXPECTED
    assert stock_score.call_args.kwargs['bars'] == _BARS[-120:]
    _offline(monkeypatch)
    monkeypatch.setattr(ss,"get_daily_regime_bars",source)
    monkeypatch.setattr(ss,'compute_omm',spy)
    core=await ss._analyze_core('TEST',StockAnalysisRequest(symbol='TEST',direction=direction,horizon=horizon))
    assert seen[-1][0]==EXPECTED
    assert core.daily_bars is _BARS
    for h in ('Swing','Position'):
        block=ss._regime_block_for_horizon('TEST',core.daily_regime_bars,h,direction)
        assert seen[-1][0]==EXPECTED
        assert block.conviction_pct==compute_omm(EXPECTED,**seen[-1][1]).conviction_pct
    monkeypatch.setattr('app.services.regime_omm.compute_omm',spy)
    measured=await asyncio.to_thread(at._measure_trade_regime,dataclasses.replace(_armed(horizon),symbol='TEST',direction=direction))
    assert seen[-1][0]==EXPECTED
    assert measured==(direct.conviction_pct,direct.stability)

@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['empty', 'failure', 'short', 'no_result'])
async def test_daily_abstentions_keep_history_and_warn(monkeypatch, caplog, outcome):
    async def read(symbol, count):
        if outcome == 'failure':
            raise RuntimeError('database unavailable')
        return [] if outcome == 'empty' else _BARS[:2] if outcome == 'short' else _BARS
    omm = MagicMock(return_value=None)
    monkeypatch.setattr(scan, 'get_daily_regime_bars', read)
    monkeypatch.setattr(scan, '_compute_omm', omm)
    scores = await options(monkeypatch, 'Bullish', 'Swing')
    assert scores.call_count == 2
    assert all(c.kwargs['regime_signal'] is None and c.kwargs['regime_gate'] is None for c in scores.call_args_list)
    _offline(monkeypatch)
    monkeypatch.setattr(ss, 'get_daily_regime_bars', read)
    monkeypatch.setattr(ss, 'compute_omm', omm)
    score = MagicMock(return_value=MagicMock(status='REJECT', score=20))
    monkeypatch.setattr(ss, 'score_stock', score)
    await ss._process_stock('TEST', StockScanRequest(universe=['TEST'], strategy='pullback_ema', direction='Bullish', horizon='Swing'), 'abstain', {'TEST': {'last': 101}}, [])
    assert score.call_args.kwargs['regime_signal'] is None
    assert score.call_args.kwargs['bars'] == _BARS[-120:]
    _offline(monkeypatch)
    monkeypatch.setattr(ss, 'get_daily_regime_bars', read)
    monkeypatch.setattr(ss, 'compute_omm', omm)
    core = await ss._analyze_core('TEST', StockAnalysisRequest(symbol='TEST'))
    assert core.daily_bars is _BARS and core.regime_signal is None
    for horizon in ('Swing','Position'):
        assert ss._regime_block_for_horizon('TEST', core.daily_regime_bars, horizon, 'Bullish').insufficient_data
    if outcome != 'no_result':
        omm.assert_not_called()
    assert 'Daily regime unmeasured for TEST/Swing' in caplog.text
    assert 'Daily regime unmeasured for TEST/Position' in caplog.text

@pytest.mark.asyncio
async def test_contributing_daily_config_errors_escape_callers(monkeypatch):
    import copy
    from app.services.money_config import RegimeConfigError
    cfg = copy.deepcopy(scan._load_scoring_cfg())
    cfg['regime']['position']['window'] = True
    monkeypatch.setattr(scan, '_load_scoring_cfg', lambda: cfg)
    monkeypatch.setattr(scan, 'get_daily_regime_bars', AsyncMock(side_effect=AssertionError('must validate before DB')))
    with pytest.raises(RegimeConfigError):
        await options(monkeypatch, 'Bullish', 'Swing')
    _offline(monkeypatch)
    monkeypatch.setattr(ss, '_load_full_scoring_cfg', lambda: cfg)
    monkeypatch.setattr(ss, 'get_daily_regime_bars', AsyncMock(side_effect=AssertionError('must validate before DB')))
    with pytest.raises(RegimeConfigError):
        await ss._process_stock('TEST', StockScanRequest(universe=['TEST'],strategy='pullback_ema',direction='Bullish',horizon='Swing'), 'config', {}, [])
    with pytest.raises(RegimeConfigError):
        await ss._analyze_core('TEST', StockAnalysisRequest(symbol='TEST'))
    monkeypatch.setattr(at, '_load_scoring_doc', lambda: cfg)
    with pytest.raises(at.RegimeGateConfigError):
        await asyncio.to_thread(at._measure_trade_regime, _armed('Swing'))

@pytest.mark.parametrize('outcome', ['empty','failure','short'])
def test_fire_db_refusals_and_short_abstention(monkeypatch, outcome):
    def read(symbol,count):
        assert symbol == 'AAPL' and count == 800
        if outcome == 'failure':
            raise RuntimeError('query failed')
        return [] if outcome == 'empty' else _BARS[:2]
    monkeypatch.setattr(at, 'get_daily_regime_bars_sync', read)
    if outcome == 'short':
        assert at._measure_trade_regime(_armed('Swing')) is None
    else:
        with pytest.raises(at.RegimeDataUnavailableError):
            at._measure_trade_regime(_armed('Swing'))

@pytest.mark.parametrize('warm', [False,True])
@pytest.mark.parametrize('failure', [False,True])
def test_fire_db_reader_never_touches_provider_or_cache(monkeypatch, warm, failure):
    from app.data import market
    cache = {'TEST': (_BARS,123.)} if warm else {}
    monkeypatch.setattr(market, '_candles_cache', cache)
    monkeypatch.setattr(market, 'fetch_candles', MagicMock(side_effect=AssertionError('provider used')))
    def read(symbol,count):
        assert (symbol,count) == ('TEST',800)
        if failure:
            raise RuntimeError('query failed')
        return _BARS
    monkeypatch.setattr(at, 'get_daily_regime_bars_sync', read)
    if failure:
        with pytest.raises(RuntimeError, match='query failed'):
            at._fetch_scan_window_bars('TEST')
    else:
        assert at._fetch_scan_window_bars('TEST') is _BARS
    assert market._candles_cache is cache
    assert cache == ({'TEST': (_BARS,123.)} if warm else {})
    market.fetch_candles.assert_not_called()

@pytest.mark.asyncio
async def test_analysis_endpoint_routes_preloaded_series_to_all_daily_blocks(source, monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setattr(ss, 'get_daily_regime_bars', source)
    seen=[]
    def spy(closes, **kwargs):
        seen.append((list(closes),kwargs))
        return compute_omm(closes, **kwargs)
    monkeypatch.setattr(ss, 'compute_omm', spy)
    monkeypatch.setattr(ss, '_sector_context', AsyncMock(return_value=(ss.SectorTileOut(name='Test'),ss.SectorRsOut(benchmark='SPY'))))
    monkeypatch.setattr(ss, '_market_backdrop', AsyncMock(return_value=None))
    monkeypatch.setattr(ss, '_stock_explanation_out', lambda *a: None)
    result=await ss.analyze_stock(StockAnalysisRequest(symbol='TEST'))
    assert len(seen)==3
    assert all(closes==EXPECTED for closes,kwargs in seen)
    assert result.regime_by_horizon['Intraday'].insufficient_data
    assert not result.regime_by_horizon['Swing'].insufficient_data
    assert not result.regime_by_horizon['Position'].insufficient_data

@pytest.mark.asyncio
async def test_stock_and_analysis_backtests_keep_full_original_history(source, monkeypatch):
    from types import SimpleNamespace
    from tests.test_a5c_analysis_scan_drop_flags import _bt
    _offline(monkeypatch)
    full = [dict(_BARS[i % len(_BARS)], time=1_600_000_000 + i*86400) for i in range(1200)]
    monkeypatch.setattr(ss,'get_historical_bars',AsyncMock(return_value=full))
    monkeypatch.setattr(ss,'get_daily_regime_bars',source)
    monkeypatch.setattr(ss,'_direction_conviction_drop',lambda *a,**k:None)
    monkeypatch.setattr(ss,'_regime_headwind',lambda *a,**k:False)
    signal=MagicMock(return_value=SimpleNamespace(strategy='pullback_ema',entry_price=101,stop_price=98,target_price=107,targets=[107],rr_ratio=2.,atr=1.,detail={}))
    monkeypatch.setitem(ss._SIGNAL_FNS,'pullback_ema',signal)
    monkeypatch.setattr(ss,'_get_backtest_cached',lambda key:None)
    monkeypatch.setattr(ss,'get_cached',lambda key:{'confidence':70,'sample_size':100})
    monkeypatch.setattr(ss,'_BACKTEST_CACHE',{})
    monkeypatch.setattr(ss,"_BACKTEST_POOL",None)
    stock_bt=MagicMock(return_value=(_bt(False),None))
    analyze_bt=MagicMock(return_value=_bt(False))
    monkeypatch.setattr(ss,'_run_backtest_with_details',stock_bt)
    monkeypatch.setattr(ss,'run_strategy_backtest',analyze_bt)
    await ss._process_stock('TEST', StockScanRequest(universe=['TEST'],strategy='pullback_ema',direction='Bullish',horizon='Swing'),'full',{'TEST':{'last':101}},[])
    assert stock_bt.call_args.args[0] is full
    core=await ss._analyze_core('TEST',StockAnalysisRequest(symbol='TEST'))
    assert analyze_bt.call_args.args[0] is full
    assert core.daily_bars is full and len(core.daily_regime_bars)==800
    assert all(call.args[0]==full[-ss.SIGNAL_WINDOW_BARS:] for call in signal.call_args_list)


@pytest.mark.asyncio
async def test_options_db_read_holds_existing_symbol_semaphore(source, monkeypatch):
    from tests.test_a4_intraday_regime_bars import _sem
    sem = _sem()
    async def read(symbol, count):
        assert sem.held
        return await source(symbol, count)
    monkeypatch.setattr(scan, "get_daily_regime_bars", read)
    monkeypatch.setattr(scan, "_compute_omm", compute_omm)
    await options(monkeypatch, "Bullish", "Swing", sem=sem)
