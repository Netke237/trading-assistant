"""Synthetic setup research integration; no historical profitability evidence."""
from datetime import date, timedelta
import importlib.util
from pathlib import Path
import pytest
from app.services import strategy_param_store as store
from app.services.horizon_profiles import TUNED_HORIZONS
from app.services.horizon_tuning import cache, signals, walk_forward_cell as wfc, report
from app.services.setup_entries import setup_params
from app.services.walk_forward import param_combos

STRATEGIES = ('breakout_setup', 'fibonacci_pullback')


def cli():
    spec = importlib.util.spec_from_file_location('setup_tune_cli', Path(__file__).parents[1] / 'scripts/tune_horizons.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('strategy,count', [('breakout_setup',18),('fibonacci_pullback',3)])
@pytest.mark.parametrize('direction', ['Bullish','Bearish'])
@pytest.mark.parametrize('horizon', TUNED_HORIZONS)
def test_research_grids_and_baseline(strategy,count,direction,horizon):
    store._CACHE = None
    grid = store.get_search_by_horizon(strategy,direction,horizon)
    combos = param_combos(grid)
    assert len(combos) == count
    assert set(grid) == ({'setup_expiry_bars','volume_confirm','volume_confirm_mult','rr_multiple'} if strategy=='breakout_setup' else {'setup_expiry_bars'})
    assert all(wfc.invalid_reason(strategy,direction,c) is None for c in combos)
    baseline, source = store.get_profile(strategy,direction,horizon)
    assert source == 'baseline'
    effective = signals.effective_params(strategy,baseline)
    assert effective['setup_expiry_bars']==5
    if strategy=='breakout_setup':
        assert baseline['resistance_proximity_pct']==.08
        assert effective['volume_confirm'] is False and effective['rr_multiple']==2.
    else:
        assert baseline == setup_params(strategy)


@pytest.mark.parametrize('strategy',STRATEGIES)
@pytest.mark.parametrize('bad',[{'typo':1},{'setup_expiry_bars':True},{'fib_swing_lookback':401},{'fib_tolerance_pct':float('nan')}])
def test_shared_validation(strategy,bad):
    assert wfc.invalid_reason(strategy,'Bullish',bad) is not None


def test_cli_explicit_scope_and_identity():
    mod=cli()
    assert len(mod.select_cells(None,None))==60
    cells=mod.select_cells('breakout_setup:Swing,fibonacci_pullback','Bullish')
    assert len(cells)==6 and {c.strategy for c in cells}==set(STRATEGIES)
    a=mod.run_identity(wfc.Cell('breakout_setup','Bullish','Swing'),{}, {}, 'bars')
    original=cache._source_text
    # Changes to order semantics must invalidate cache and resume, without a version bump.
    cache._source_text=lambda p: original(p)+(b' changed' if p.name=='simulate.py' else b'')
    try:
        assert mod.run_identity(wfc.Cell('breakout_setup','Bullish','Swing'),{}, {}, 'bars')!=a
    finally:
        cache._source_text=original


def test_cache_all_fields_and_sources(tmp_path,monkeypatch):
    b=synthetic_bars('fibonacci_pullback')[:110]
    event=signals.SignalPoint(104.,97.,110.,True,2.5,2)
    monkeypatch.setattr(signals,'signal_series',lambda *a: [None]*100+[event]+[None]*9)
    c=cache.TuningCache(tmp_path)
    first=c.signal_series('X',b,'fibonacci_pullback','Bullish',{})
    assert c.signal_series('X',b,'fibonacci_pullback','Bullish',{})==first
    assert c.hits==1 and first[100]==event
    key=cache.signal_key('X',b,'fibonacci_pullback','Bullish',{})
    old=cache._source_text
    monkeypatch.setattr(cache,'_source_text',lambda p: old(p)+b'changed' if p.name=='setup_entries.py' else old(p))
    assert cache.signal_key('X',b,'fibonacci_pullback','Bullish',{})!=key
    assert c.signal_series('X',b,'fibonacci_pullback','Bullish',{})==first
    assert c.misses==2


def test_gated_fire_count_setup_trigger_window_and_warmup():
    b=synthetic_bars('fibonacci_pullback')[:450]
    st=wfc.SymbolState.build('X',b,[True]*len(b))
    sig=[None]*len(b)
    sig[400]=signals.SignalPoint(104.,97.,110.,True,None,2) # setup before warmup
    sig[405]=signals.SignalPoint(104.,97.,110.,True,None,2)
    assert wfc.count_fires(st,sig,st.dates[400],st.dates[410])==1
    st.allowed[403]=False
    assert wfc.count_fires(st,sig,st.dates[400],st.dates[410])==0
    st.allowed[403]=True
    assert wfc.count_fires(st,sig,st.dates[404],st.dates[410])==0
    extra=[True]*len(b); extra[403]=False
    assert wfc.count_fires(st,sig,st.dates[400],st.dates[410],extra_allowed=extra)==0


def synthetic_bars(strategy,n=1050,direction='Bullish'):
    out=[]
    for i in range(n):
        k=i%100
        if strategy=='fibonacci_pullback':
            close=102.36 if k==50 else 104. if k==51 else 100.
            row=dict(open=104.,high=110.,low=90.,close=close,volume=100.)
        else:
            # Real coil: contracting ATR, tight 10-bar range and low volume;
            # then close above the frozen swing and a next-open R target hit.
            if k<70:
                row=dict(open=100.,high=103.,low=97.,close=100.,volume=200.)
            elif k<88:
                row=dict(open=102.,high=102.4,low=101.6,close=102.,volume=50.)
            elif k==88:
                row=dict(open=103.,high=104.5,low=102.5,close=104.,volume=200.)
            else:
                row=dict(open=104.,high=120.,low=103.5,close=108.,volume=200.)
        if direction=='Bearish':
            row={**row,'open':200-row['open'],'close':200-row['close'],'high':200-row['low'],'low':200-row['high']}
        out.append(dict(time=str(date(2020,1,1)+timedelta(days=i)),**row))
    return out


@pytest.mark.parametrize('strategy', STRATEGIES)
@pytest.mark.parametrize('direction',['Bullish','Bearish'])
def test_real_setup_walkforward_full_universe_both_costs(strategy,direction,monkeypatch,tmp_path):
    b=synthetic_bars(strategy,direction=direction)
    # Isolate existing scoring gates only; real detector, confirmation, simulator and WFO run.
    monkeypatch.setattr(wfc._gates,'gate_mask',lambda bars,*a,**kw: [True]*len(bars))
    cfg=store.get_tuning_config()
    cfg.update(held_out_months=6,exit_buffer_days=0,min_train_trades=1,min_folds_not_thin=1)
    cfg['windows']['Swing']={'train_months':3,'test_months':2}
    cfg['fire_rate_floor_per_day']['Swing']=0.
    grid={'setup_expiry_bars':[5]}
    result=wfc.tune_cell(wfc.Cell(strategy,direction,'Swing'),wfc.CellData({'X':b},{'X':'Tech'},{'Tech':1},config=cfg,grid=grid,cache=cache.TuningCache(tmp_path)))
    assert result.final_params is not None
    for cost in (wfc.COST,wfc.STRESS):
        assert result.oos[cost].n_trades>0 and result.heldout[cost].n_trades>0
        assert all(t.trade.exit_date<result.calendar.heldout_start for t in result.oos_trades[cost])
        assert all(t.trade.entry_date>=result.calendar.heldout_start for t in result.heldout_trades[cost])
    full=report.full_universe_recheck(result,report.UniverseData({'X':b,'Y':b},['X','Y'],['X','Y']),cfg)
    assert full.fire_rate==pytest.approx(result.fire_rate*2)
    for cost in (wfc.COST,wfc.STRESS):
        assert full.oos[cost].n_trades==result.oos[cost].n_trades*2
        assert full.heldout[cost].n_trades==result.heldout[cost].n_trades*2
    assert full.heldout[wfc.STRESS].net_expectancy<full.heldout[wfc.COST].net_expectancy
    row=report.cell_row(result,full,report.adoption_verdict(result.cell,full,cfg),cfg)
    assert row['fire_rate_basis']=='gated confirmed entry events'
    assert row['research_only'] is True


@pytest.mark.parametrize('strategy',STRATEGIES)
def test_no_winner_thin_real_signals(strategy,monkeypatch):
    b=synthetic_bars(strategy,n=450)
    monkeypatch.setattr(wfc._gates,'gate_mask',lambda bars,*a,**kw: [False]*len(bars))
    result=wfc.tune_cell(wfc.Cell(strategy,'Bullish','Swing'),wfc.CellData({'X':b},{'X':'Tech'},{'Tech':1},grid={'setup_expiry_bars':[5]}))
    assert result.thin and result.final_params is None
    assert result.oos[wfc.COST].n_trades==result.heldout[wfc.STRESS].n_trades==0


def test_resume_invalidates_and_probe_explicit_cells(tmp_path,monkeypatch,capsys):
    import json
    mod=cli()
    cells=mod.select_cells('breakout_setup:Swing,fibonacci_pullback:Swing','Bullish')
    key=mod.run_identity(cells[0],{}, {}, 'bars')
    report.write_cell(tmp_path,cells[0],{'run_key':key,'row':{'synthetic':True}})
    assert report.load_finished(tmp_path,cells[0],key)=={'synthetic':True}
    old=cache._source_text
    monkeypatch.setattr(cache,'_source_text',lambda p: old(p)+(b'changed' if p.name=='setup_entries.py' else b''))
    assert report.load_finished(tmp_path,cells[0],mod.run_identity(cells[0],{}, {}, 'bars')) is None
    (tmp_path/'X_candles.json').write_text(json.dumps(synthetic_bars('fibonacci_pullback',n=110)))
    monkeypatch.setattr(mod._basket,'universe_union',lambda: ['X'])
    mod.probe(['X'],tmp_path,1,500,cells)
    output=capsys.readouterr().out
    assert 'breakout_setup' in output and 'fibonacci_pullback' in output
    assert '(2 cells,' in output


@pytest.mark.parametrize('bad_field,bad_value',[('market',1),('market',None),('setup_age',1.5),('rr_multiple','2'),('entry',float('nan'))])
def test_malformed_cache_event_recomputed(tmp_path,monkeypatch,bad_field,bad_value):
    import json
    b=synthetic_bars('fibonacci_pullback',n=110)
    event=signals.SignalPoint(104.,97.,110.,True,None,2)
    series=[None]*100+[event]+[None]*9
    monkeypatch.setattr(signals,'signal_series',lambda *a: series)
    c=cache.TuningCache(tmp_path)
    c.signal_series('X',b,'fibonacci_pullback','Bullish',{})
    path=next((tmp_path/'signals').glob('*.json'))
    payload=json.loads(path.read_text());payload[100][bad_field]=bad_value
    path.write_text(json.dumps(payload))
    assert c.signal_series('X',b,'fibonacci_pullback','Bullish',{})==series
    assert c.misses==2 and c.hits==0


@pytest.mark.parametrize('strategy',STRATEGIES)
def test_real_event_window_extra_gates_and_boundary_drops(strategy):
    b=synthetic_bars(strategy,n=600)
    p=wfc.combo_params(strategy,'Bullish',{})
    sig=signals.signal_series(b,strategy,'Bullish',p)
    t=next(i for i in range(410,len(b)-2) if sig[i] is not None)
    origin=t-sig[t].setup_age
    state=wfc.SymbolState.build('X',b,[True]*len(b))
    span=(state.dates[origin],state.dates[t+1])
    args=dict(entry=span,restriction=state.dates[t+2],inclusive=True,commission=.0005,hold_max_days=20)
    trade=wfc.simulate_window(state,sig,**args)
    assert len(trade.trades)==1
    fill=b[t+1]['open']
    target=fill+2*(fill-sig[t].stop) if strategy=='breakout_setup' else sig[t].target
    expected=target if strategy=='breakout_setup' else sig[t].stop
    assert trade.trades[0].exit_price==pytest.approx(expected)
    assert trade.trades[0].net_return_pct==pytest.approx(((expected/fill-1)-.0005*(1+expected/fill))*100)
    extra=[True]*len(b);extra[origin]=False
    assert not wfc.simulate_window(state,sig,extra_allowed=extra,**args).trades
    assert wfc.count_fires(state,sig,*span,extra_allowed=extra)==0
    assert not wfc.simulate_window(state,sig,**{**args,'entry':(state.dates[origin+1],span[1])}).trades
    # Keep the real confirmation, but make its fill bar miss both brackets.
    b[t+1].update(high=fill+.01,low=fill-.01,close=fill)
    state=wfc.SymbolState.build('X',b,[True]*len(b))
    dropped=wfc.simulate_window(state,sig,**{**args,'restriction':state.dates[t+1]})
    assert dropped.boundary_dropped==1 and not dropped.trades
    short=wfc.SymbolState.build('X',b[:t+2],[True]*(t+2))
    dropped=wfc.simulate_window(short,sig[:t+2],**{**args,'restriction':state.dates[t+1]})
    assert dropped.end_dropped==1 and not dropped.trades
