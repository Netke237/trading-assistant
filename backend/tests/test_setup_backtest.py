"""Synthetic research machinery tests; these are not historical performance evidence."""
from datetime import date, timedelta
import math
import pytest
from app.services.horizon_tuning.signals import SignalPoint, signal_series
from app.services.horizon_tuning.simulate import simulate_trades
from app.services import strategy_engine as se


def bars(n=110):
    return [dict(time=str(date(2025, 1, 1)+timedelta(days=i)), open=100., high=101., low=99., close=100., volume=100.) for i in range(n)]


@pytest.mark.parametrize('direction,stop,target,high,low,expected', [('Bullish',90.,120.,125.,85.,90.), ('Bearish',110.,80.,115.,75.,110.)])
def test_market_fill_bar_stop_priority(direction,stop,target,high,low,expected):
    b=bars(); b[61].update(high=high,low=low)
    s=[None]*len(b); s[60]=SignalPoint(100.,stop,target,market=True,setup_age=1)
    trades=simulate_trades(b,s,direction=direction,commission=.002,hold_max_days=None)
    assert len(trades)==1
    assert trades[0].entry_date==trades[0].exit_date
    assert trades[0].exit_price==expected
    assert trades[0].exit_reason=='stop'
    sign=1 if direction=='Bullish' else -1
    assert trades[0].net_return_pct==pytest.approx((sign*(expected/100-1)-.002*(1+expected/100))*100)


def test_actual_fill_r():
    b=bars(); b[61].update(open=105.,high=140.,low=104.,close=130.)
    s=[None]*len(b); s[60]=SignalPoint(101.,95.,0.,market=True,rr_multiple=2.,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None)
    assert t[0].entry_price==105.
    assert t[0].exit_price==125.


def test_coil_frozen_expiry_and_prefix(monkeypatch):
    monkeypatch.setattr(se,'breakout_setup_signal',lambda *a,**kw: object())
    b=bars(); b[59]['high']=102.123456; b[60]['high']=150.; b[61]['close']=103.
    s=signal_series(b,'breakout_setup','Bullish',{'setup_expiry_bars':2,'require_trend':False})
    assert s[59] is None and s[60] is None
    assert s[61].entry==103. and s[61].setup_age==2
    assert s[61].stop==math.nextafter(99.,-math.inf)
    assert signal_series(b[:62],'breakout_setup','Bullish',{'setup_expiry_bars':2,'require_trend':False})==s[:62]


@pytest.mark.parametrize('direction', ['Bullish','Bearish'])
@pytest.mark.parametrize('trigger_age', [1,2,3])
def test_confirmation_expiry_inclusive(monkeypatch,direction,trigger_age):
    monkeypatch.setattr(se,'breakout_setup_signal',lambda w,*a,**kw: object() if len(w)==60 else None)
    b=bars(); b[59+trigger_age]['close']=102. if direction=='Bullish' else 98.
    s=signal_series(b,'breakout_setup',direction,{'setup_expiry_bars':2})
    assert (s[59+trigger_age] is not None)==(trigger_age<=2)
    if trigger_age<=2:
        assert s[59+trigger_age].setup_age==trigger_age
        assert s[59+trigger_age].stop==math.nextafter(99. if direction=='Bullish' else 101.,-math.inf if direction=='Bullish' else math.inf)


@pytest.mark.parametrize('volume,confirmed', [(149.999,False),(150.,True)])
def test_volume_threshold_excludes_trigger(monkeypatch,volume,confirmed):
    monkeypatch.setattr(se,'breakout_setup_signal',lambda w,*a,**kw: object() if len(w)==60 else None)
    b=bars(); b[60].update(close=102.,volume=volume)
    s=signal_series(b,'breakout_setup','bullish',{'volume_confirm':True})
    assert (s[60] is not None)==confirmed


@pytest.mark.parametrize('direction', ['Bullish','Bearish'])
@pytest.mark.parametrize('levels', [[38.2,61.8,78.6],[38.2]])
def test_fib_real_touch_frozen_depth_and_origin(direction,levels):
    b=bars(120)
    for row in b:
        row.update(high=110.,low=90.,close=105. if direction=='Bullish' else 95.)
    long=direction=='Bullish'
    touched=110.-.382*20 if long else 90.+.382*20
    b[99]['close']=touched
    b[100].update(close=104. if long else 96.,high=200.,low=1.)
    p={'ema_filter_period':0,'fib_levels':levels}
    s=signal_series(b,'fibonacci_pullback',direction,p)
    assert s[99] is None
    event=s[100]
    assert event is not None and event.market and event.setup_age==1
    boundary=(110.-.618*20 if long else 90.+.618*20) if len(levels)>1 else (90. if long else 110.)
    assert event.stop==math.nextafter(boundary,-math.inf if long else math.inf)
    assert event.target==(110. if long else 90.)
    assert event.rr_multiple is None
    assert signal_series(b[:101],'fibonacci_pullback',direction,p)==s[:101]


def test_fib_outside_tolerance_and_ema_filter():
    b=bars(120)
    for row in b:
        row.update(high=110.,low=90.,close=108.)
    # This near level is outside .001 tolerance, and its intrabar range crosses it.
    b[99]['close']=103.
    b[100]['close']=104.
    assert all(s is None for s in signal_series(b,'fibonacci_pullback','Bullish',{'ema_filter_period':0,'fib_tolerance_pct':.001}))
    b[99]['close']=102.36
    assert signal_series(b,'fibonacci_pullback','Bullish',{'fib_tolerance_pct':.001})[100] is None
    assert signal_series(b,'fibonacci_pullback','Bullish',{'ema_filter_period':0,'fib_tolerance_pct':.001})[100] is not None


@pytest.mark.parametrize('strategy,params', [('breakout_setup',{'typo':2}),('breakout_setup',{'setup_expiry_bars':True}),('breakout_setup',{'rr_multiple':float('nan')}),('breakout_setup',{'volume_confirm':1}),('breakout_setup',{'atr_avg_lookback':400}),('fibonacci_pullback',{'ema_filter_period':401}),('fibonacci_pullback',{'fib_levels':[100.]}),('fibonacci_pullback',{'fib_tolerance_pct':float('inf')}),('fibonacci_pullback',{'fib_swing_lookback':2.5})])
def test_invalid_params_raise(strategy,params):
    with pytest.raises(ValueError):
        signal_series(bars(),strategy,'Bullish',params)


@pytest.mark.parametrize('direction,open_price,stop,target', [('Bullish',90.,90.,120.),('Bullish',121.,90.,120.),('Bearish',110.,110.,80.),('Bearish',79.,110.,80.),('Bullish',100.,float('nan'),120.),('Bullish',100.,90.,float('inf'))])
def test_invalid_fill_rejected(direction,open_price,stop,target):
    b=bars(); b[61]['open']=open_price
    s=[None]*len(b); s[60]=SignalPoint(100.,stop,target,market=True,setup_age=1)
    t=simulate_trades(b,s,direction=direction,commission=0.,hold_max_days=None)
    assert not t and t.dropped_open==0
    assert t.equity_curve==[100000.]*len(b)


@pytest.mark.parametrize('direction,stop,target,gap,reason', [('Bullish',90.,120.,85.,'stop'),('Bullish',90.,120.,125.,'target'),('Bearish',110.,80.,115.,'stop'),('Bearish',110.,80.,75.,'target')])
def test_bracket_gap_open(direction,stop,target,gap,reason):
    b=bars(); b[62].update(open=gap,close=gap,high=gap+1,low=gap-1)
    s=[None]*len(b); s[60]=SignalPoint(100.,stop,target,market=True,setup_age=1)
    t=simulate_trades(b,s,direction=direction,commission=0.,hold_max_days=None)
    assert len(t)==1 and t[0].exit_price==gap and t[0].exit_reason==reason


def test_time_calendar_weekend_priority():
    b=bars()
    b[61]['time']='2025-03-07' # Friday; fill
    b[62]['time']='2025-03-10' # Monday due close
    for i in range(63,len(b)):
        b[i]['time']=str(date(2025,3,11)+timedelta(days=i-63))
    b[63].update(open=105.,high=130.,low=80.)
    s=[None]*len(b); s[60]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=3)
    assert t[0].exit_price==105. and t[0].exit_reason=='time'
    assert t[0].exit_date==date(2025,3,11)


@pytest.mark.parametrize('restriction', ['setup_gate','trigger_gate','start','end','sliced_origin'])
def test_setup_and_trigger_window_gates(restriction):
    b=bars(); s=[None]*len(b); s[60]=SignalPoint(100.,90.,120.,market=True,setup_age=2)
    allowed=[True]*len(b); kw={}
    if restriction=='setup_gate': allowed[58]=False
    if restriction=='trigger_gate': allowed[60]=False
    if restriction=='start': kw['entry_start']=date.fromisoformat(b[59]['time'])
    if restriction=='end': kw['entry_end']=date.fromisoformat(b[60]['time'])
    if restriction=='sliced_origin': s[60]=SignalPoint(100.,90.,120.,market=True,setup_age=61)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None,allowed=allowed,**kw)
    assert not t and t.dropped_open==0


def test_fill_after_entry_end_and_no_final_liquidation():
    b=bars(); s=[None]*len(b); s[60]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=.002,hold_max_days=None,entry_end=date.fromisoformat(b[61]['time']))
    assert not t and t.dropped_open==1
    assert t.equity_curve[61]<100000.
    s=[None]*len(b); s[-1]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None)
    assert not t and t.dropped_open==0


def test_confirmation_while_holding_never_resurrects():
    b=bars(); b[63]['low']=89.
    s=[None]*len(b)
    for i in (60,61): s[i]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None)
    assert len(t)==1 and t.dropped_open==0
    s[64]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None)
    assert len(t)==1 and t.dropped_open==1


def test_market_invalid_open_does_not_skip_new_confirmation():
    b=bars(); b[61]['open']=80.
    s=[None]*len(b)
    for i in (60,61): s[i]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=0.,hold_max_days=None)
    assert t.dropped_open==1


def test_adapter_window_equity_warmup_equality(monkeypatch):
    from app.services.strategy_backtest import run_strategy_backtest_trades
    monkeypatch.setattr(se,'breakout_setup_signal',lambda w,*a,**kw: object() if w[-1]['volume']==3 else None)
    def run(prefix):
        b=bars(prefix+40)
        start=date(2025,5,1)
        for i,row in enumerate(b): row['time']=str(start+timedelta(days=i-prefix))
        b[prefix]['volume']=3
        b[prefix+1]['close']=102.
        b[prefix+2].update(open=102.,high=120.,low=101.,close=110.)
        return run_strategy_backtest_trades(b,strategy='breakout_setup',direction='Bullish',commission=.002,entry_start=start,min_trades=1)
    a,ta=run(65); b,tb=run(95)
    assert ta==tb and a==b
    stop=math.nextafter(99.,-math.inf); target=102.+2*(102.-stop)
    assert ta[0].entry_price==102. and ta[0].exit_price==target
    units=int((100000.*(1-__import__('sys').float_info.epsilon))//(102.*1.002))
    expected=(units*(target-102.)-units*.002*(102.+target))/100000.*100
    assert a.total_return_pct==pytest.approx(expected)
    assert a.n_trades==1 and a.win_rate==1


@pytest.mark.parametrize('strategy,need', [('breakout_setup',50),('fibonacci_pullback',100)])
def test_bars_needed_explicit(strategy,need):
    assert se.bars_needed(strategy)==need


def test_adapter_empty_validation_and_legacy_unknown():
    from app.services.strategy_backtest import run_strategy_backtest
    assert run_strategy_backtest(bars(99),strategy='breakout_setup',direction='Bullish').n_trades==0
    assert run_strategy_backtest(bars(),strategy='breakout_setup',direction='Bullish',commission=float('nan')).n_trades==0
    assert run_strategy_backtest(bars(),strategy='unknown',direction='Bullish').n_trades==0
    bad=bars(); bad[5]['time']=bad[4]['time']
    with pytest.raises(ValueError,match='daily'):
        run_strategy_backtest(bad,strategy='breakout_setup',direction='Bullish')
    bad=bars(); del bad[0]['time']
    with pytest.raises(ValueError,match='dated'):
        run_strategy_backtest(bad,strategy='fibonacci_pullback',direction='Bullish')


@pytest.mark.parametrize('direction', ['Bullish','Bearish'])
def test_real_coil_detector_and_raw_geometry(direction):
    b=bars()
    p=dict(atr_compression_ratio=2., range_atr_mult=100.,
           vol_compression_ratio=2., resistance_proximity_pct=.5, require_trend=False)
    b[59]['high']=101.1234567
    if direction=='Bullish':
        b[60].update(close=102.,high=103.)
    else:
        b[59]['low']=98.8765432
        b[60].update(close=98.,low=97.)
    assert se.breakout_setup_signal(b[:60],'SYNTHETIC',direction=direction,**p) is not None
    s=signal_series(b,'breakout_setup',direction,p)
    assert s[60] is not None and s[60].setup_age==1
    assert s[60].entry==b[60]['close']
    boundary=99. if direction=='Bullish' else 101.1234567
    assert s[60].stop==math.nextafter(boundary,-math.inf if direction=='Bullish' else math.inf)


def test_coil_requested_range_warmup(monkeypatch):
    monkeypatch.setattr(se,'breakout_setup_signal',lambda *a,**kw: object())
    b=bars(180); b[60]['close']=102.
    s=signal_series(b,'breakout_setup','Bullish',{'range_lookback_bars':100})
    assert all(v is None for v in s[:100])


def test_equity_tracks_marked_open_position_and_entry_commission():
    b=bars(); b[61].update(open=100.,close=105.,high=106.,low=99.)
    s=[None]*len(b); s[60]=SignalPoint(100.,90.,120.,market=True,setup_age=1)
    t=simulate_trades(b,s,direction='Bullish',commission=.002,hold_max_days=None)
    units=int((100000.*(1-__import__('sys').float_info.epsilon))//100.2)
    assert t.dropped_open==1 and not t
    assert t.equity_curve[61]==pytest.approx(100000.-units*.2+units*5)
    assert t.equity_curve[62]==pytest.approx(100000.-units*.2)


def test_confirmation_uses_unrounded_strict_boundary(monkeypatch):
    monkeypatch.setattr(se,'breakout_setup_signal',lambda w,*a,**kw: object() if len(w)==60 else None)
    b=bars(); b[59]['high']=101.1234567
    b[60]['close']=101.122 # Above the rounded metric (101.12), below frozen raw level.
    b[61]['close']=101.1234567 # Equality is not a breakout.
    b[62]['close']=101.124
    s=signal_series(b,'breakout_setup','Bullish',{'setup_expiry_bars':3})
    assert s[60] is None and s[61] is None
    assert s[62] is not None and s[62].setup_age==3


@pytest.mark.parametrize('direction', ['Bullish','Bearish'])
def test_fib_deepest_default_level_uses_origin(direction):
    b=bars(120); long=direction=='Bullish'
    for row in b: row.update(high=110.,low=90.,close=105. if long else 95.)
    touched=110.-.618*20 if long else 90.+.618*20
    b[99]['close']=touched
    b[100]['close']=touched+(1 if long else -1)
    s=signal_series(b,'fibonacci_pullback',direction,{'ema_filter_period':0})
    assert s[100].stop==math.nextafter(90. if long else 110.,-math.inf if long else math.inf)


def test_fib_requires_requested_research_lookback():
    b=bars(120)
    for row in b: row.update(high=110.,low=90.,close=105.)
    b[59]['close']=102.36; b[60]['close']=104.
    s=signal_series(b,'fibonacci_pullback','Bullish',{'ema_filter_period':0})
    assert all(v is None for v in s[:100])
