import json, sys, inspect
from dataclasses import asdict
from datetime import datetime, timezone, timedelta, date
from types import SimpleNamespace
from uuid import uuid4
from app.services.strategy_backtest import run_strategy_backtest_detailed
from app.services import strategy_engine

signal_signature = inspect.signature(strategy_engine.pullback_ema_signal)
result={}
for direction in ['Bullish','Bearish']:
 for interval in ['1d','15m']:
  base=datetime(2024,1,1,tzinfo=timezone.utc)
  bars=[dict(time=(base+timedelta(seconds=i*(86400 if interval=='1d' else 900))).isoformat(),open=100.,high=101.,low=99.,close=100.,volume=1000.) for i in range(150)]
  def signal(data,**kwargs):
   if len(data) not in [101,111]: return None
   return SimpleNamespace(entry_price=100.,stop_price=90. if direction=='Bullish' else 110.,target_price=110. if direction=='Bullish' else 90.)
  signal.__signature__ = signal_signature
  strategy_engine.pullback_ema_signal=signal
  bars[103].update(high=111.,low=89.)
  bars[113].update(high=111.,low=89.)
  bars[-1].update(close=105.,high=106.)
  detail=run_strategy_backtest_detailed(bars,strategy='pullback_ema',direction=direction,commission=.002,min_trades=1)
  assert detail.status=='success',detail.reason
  result[direction+'-'+interval]=dict(schema_version=1,artifact_id=str(uuid4()),provenance='original',identity=dict(scan_id='browser-fixture',report_run_id=None,symbol='AAA',strategy='pullback_ema',direction=direction,horizon='Swing',interval=interval,bars_basis_version='browser-frozen-fixture',input_hash='a'*64,engine_contract_version=detail.engine_contract_version),created_at=1780000000,expires_at=1990000000,currency=None,detail=asdict(detail))
fresh_bars = [{**b, 'time': (datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat()} for i,b in enumerate(bars)]
fresh = run_strategy_backtest_detailed(fresh_bars, strategy='pullback_ema', direction='Bearish', commission=.002, entry_start=date(2024,4,20), entry_end=date(2024,5,30), hold_max_days=10, min_trades=5, min_win_rate=.5, params=result['Bearish-15m']['detail']['effective_params'])
assert fresh.status == 'success', fresh.reason
result['fresh']={**result['Bearish-1d'], 'provenance':'fresh', 'artifact_id':str(uuid4()), 'detail':asdict(fresh)}
strategy_engine.pullback_ema_signal=lambda *a,**k:None
detail=run_strategy_backtest_detailed(bars,strategy='pullback_ema',direction='Bullish',commission=.002)
result['zero']={**result['Bullish-15m'],'artifact_id':str(uuid4()),'detail':asdict(detail)}
with open(sys.argv[1], 'w') as output:
 json.dump(result, output, allow_nan=False)
print({k:len(v['detail']['trades']) for k,v in result.items()})
