"""Audit fixtures: real backend config resolution; fixed component outputs isolate weight units.
No API server, DB, provider, broker, notification, or config writes.
"""
import copy, hashlib, inspect, json, sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / 'backend'))
from app.scoring import stock_scorer as scorer
from app.scoring import contract_validator as contracts
from app.scoring.entry_quality import EntryConfig, assess_entry
from app.scoring.trade_plan import build_trade_plan
from app.services.config_loader import effective_rr_overrides, load_reward_risk_cfg, resolve_target_r_multiple
from app.schemas import ScanRequest
from app.schemas.stock_scan import StockScanRequest
OUT = {'source': '880c8441841cc22d5090cdc5f984e4cf7e3d9a8d', 'python': sys.version.split()[0], 'scope': 'real backend helpers and schema; mocked fixed component scores for weight-unit isolation; not provider integration', 'checks': [], 'effective': [], 'hashes': {}}
assert sys.version_info[:2] == (3, 11)
def check(key, expected, actual):
    OUT['checks'].append({'id': key, 'status': 'pass' if expected == actual else 'fail', 'expected': expected, 'actual': actual})
for f in ['backend/config/scoring_rules.yaml','backend/config/contract_rules.yaml','backend/config/risk_rules.yaml','backend/config/strategy_params.yaml','backend/app/scoring/stock_scorer.py','backend/app/scoring/trade_plan.py','backend/app/scoring/entry_quality.py','backend/app/schemas/stock_scan.py']:
    OUT['hashes'][f] = hashlib.sha256((ROOT / f).read_bytes()).hexdigest()
# Known inputs with component scores fixed separately from production indicator logic.
SCORES = {'trend':80, 'pullback':60, 'trigger':40, 'event':20, 'vol':100}
def rule(name):
    def f(*args, **kw):
        r = scorer.RuleResult(name,'PASS', SCORES[name], {})
        return (r, False) if name == 'trigger' else r
    return f
def score(overrides=None, horizon='Swing', mode='options'):
    with patch.multiple(scorer, **{'_rule_'+k:rule(k) for k in SCORES}):
        return scorer.score_stock('FIXTURE','Bullish',horizon,[{'close':100,'volume':100}],overrides=overrides,scoring_mode=mode)
base=score()
check('weight baseline independently summed',59,base.score)
changed=score({'weight_trend':40})
# 40% means 0.40, keeping the four other weights unchanged: 32+12+10+3+10=67.
check('40 percent trend weight unit',67,changed.score)
OUT['weightFixture']={'fixed_components':SCORES,'baseline':base.explanation,'panel40':changed.explanation,'independentExpected':67,'assumption':'UI percent 40 is 0.40; no recalibration of other weights'}
# Snapshot each scorer's final effective config, after real override application.
paths={**{'weight_'+k:['weights',k] for k in SCORES},'trend_method':['trend','method'],'fast_ema':['trend','crossover','fast_ema'],'slow_ema':['trend','crossover','slow_ema'],'ma_type':['trend','crossover','ma_type'],**{k:['trend','additive',v] for k,v in {'additive_ma_type':'ma_type','additive_ma_period':'ma_period','additive_slope_lookback':'slope_lookback','additive_adx_period':'adx_period','additive_adx_pass':'adx_pass','additive_adx_caution':'adx_caution','additive_price_max':'price_max','additive_slope_max':'slope_max','additive_adx_max':'adx_max'}.items()},**{k:['trend','relative_strength',v] for k,v in {'rs_period':'rs_period','rs_pass_threshold':'rs_pass_threshold','rs_caution_threshold':'rs_caution_threshold','rs_benchmark':'benchmark'}.items()},**{k:['trigger',k] for k in ['rsi_period','rsi_floor','macd_fast','macd_slow','macd_signal','volume_lookback_bars','volume_multiplier']},**{k:['pullback',k] for k in ['swing_high_lookback_bars','atr_caution_max']},'event_reject_days':['event','reject_days'],'event_caution_days':['event','caution_days'],'iv_abs_pass_max':['vol','iv_abs_pass_max'],'iv_rank_pass_max':['vol','iv_rank_pass_max']}
def config_path(result, path):
    if path[0]=='weights': return result.explanation['weights'][path[1]]
    x=result.explanation['components'][path[0]]['config']
    for key in path[1:]: x=x[key]
    return x
matrix=json.loads((Path(__file__).parent/'parameter-output.json').read_text())['matrix']
for d in matrix:
    key=d['key'];row={'key':key,'family':d['subGroup'],'effectiveReader':None}
    if key in paths:
        row['effectiveReader']='stock_scorer.score_stock explanation.'+'.'.join(paths[key]);row['horizonDefaults']={h:config_path(score(horizon=h),paths[key])for h in ['Intraday','Swing','Position']}
        custom=next((o['input'] for o in d['observations'] if o['kind']=='custom'), None)
        if custom is not None:
            row['customInput']=custom
            row['customEffective']=config_path(score({key:custom}),paths[key])
    elif key in contracts.CONTRACT_OVERRIDE_KEYS:
        row['effectiveReader']='contract_validator.effective_contract_overrides';row['observations']=[]
        for value in [0,d.get('min'),d.get('max'),0.5]:
            if value is None:continue
            row['observations'].append({'input':value,'effective':contracts.effective_contract_overrides({key:value})[key]})
    elif key.startswith('rr_'):
        row['effectiveReader']='config_loader.effective_rr_overrides / resolve_target_r_multiple';row['observations']=[]
        for value in [None,0,d.get('min'),d.get('max')]:
            try: val=effective_rr_overrides({key:value});row['observations'].append({'input':value,'effective':val})
            except (ValueError,TypeError)as exc: row['observations'].append({'input':value,'error':type(exc).__name__+': '+str(exc)})
    elif key.startswith('entry_'):
        row['effectiveReader']='NONE: Step 3 override keys have no backend consumer; trade_plan.build_trade_plan invokes assess_entry without config'
    elif key.startswith(('confidence_','regime_','fundamentals_')) or key in ['pullback_require_reversal','min_stock_score']:
        row['effectiveReader']='top-level request; see requestTrace and per-family source map in coverage.md'
    else:
        row['effectiveReader']='display only / redundant; not directly editable'
    OUT['effective'].append(row)
# Shared gates operate on top-level parsed fields; observe real zero/null/default behavior.
from app.services.regime_gate import resolve_regime_gate
from app.services.fundamentals_gate import resolve_fundamentals_gate
regimeBase={'enabled':True,'headwind_caution_pct':-15,'headwind_reject_pct':-40}
check('regime zero is explicit',0,resolve_regime_gate(regimeBase,0,None)['headwind_caution_pct'])
check('regime null follows config',-15,resolve_regime_gate(regimeBase,None,None)['headwind_caution_pct'])
req=ScanRequest(universe=['FIXTURE'],direction='Bearish',horizon='Swing',fundamentals_caution_above=0,fundamentals_reject_above=100)
check('bearish fundamentals zero explicit',0,resolve_fundamentals_gate(req)['cautionAbove'])
check('bearish fundamentals maximum explicit',100,resolve_fundamentals_gate(req)['rejectAbove'])
req.direction='Bullish'
check('bullish ignores bearish-only override',70,resolve_fundamentals_gate(req)['cautionAbove'])
# Representative independently specified effective boundaries
check('event zero overrides backend default',(0,0),scorer.effective_event_window('Swing',{'event_reject_days':0,'event_caution_days':0}))
check('event null follows config',(21,45),scorer.effective_event_window('Swing',{'event_reject_days':None,'event_caution_days':None}))
check('IV null preserves absent ceiling',None,config_path(score({'iv_abs_pass_max':None}),paths['iv_abs_pass_max']))
check('contract preferred 0.5 does not disable',1,contracts.effective_contract_overrides({'preferred_volume_min':0.5})['preferred_volume_min'])
check('contract zero retains off semantics',0,contracts.effective_contract_overrides({'min_volume':0})['min_volume'])
check('RR null means no override',{},effective_rr_overrides({'rr_bullish_invalidation_pct':None}))
check('RR custom fraction stays fraction',{'rr_bullish_invalidation_pct':0.05},effective_rr_overrides({'rr_bullish_invalidation_pct':0.05}))
# Entry quality comparison: request is valid yet the shared plan function cannot receive its overrides.
entryReq=next(p['request']for p in json.loads((Path(__file__).parent/'parameter-output.json').read_text())['payloads']if p['id']=='entry-quality-knobs')
validated=ScanRequest.model_validate(entryReq)
plan=build_trade_plan(direction='Bullish',stock_price=100,strike=100,dte=45,premium=1,entry_bid=.99,entry_ask=1.01,entry_mid=1,rr_cfg=load_reward_risk_cfg(),final_stop_price=97,target_price=106,stop_cost_fraction=None)
expectedEntry=assess_entry(.99,1.01,1,EntryConfig(spread_tolerance_pct=0,max_slippage_pct=0,min_premium=5))
check('entry minimum premium override changes verdict',expectedEntry.quality_status,plan.entry.quality_status)
check('entry zero slippage override changes max fill',expectedEntry.max_fill,plan.entry.max_fill)
OUT['entryFixture']={'wireOverrides':validated.overrides,'sharedPlanSignature':str(inspect.signature(build_trade_plan)),'actualDefaultConfig':asdict(EntryConfig()),'actualSharedPlanEntry':asdict(plan.entry),'expectedEditedConfigEntry':asdict(expectedEntry)}
OUT['requestTrace']=[]
for p in json.loads((Path(__file__).parent/'parameter-output.json').read_text())['payloads']:
    schema=StockScanRequest if p['id'].startswith('stocks-')else ScanRequest
    req=schema.model_validate(p['request']);OUT['requestTrace'].append({'id':p['id'],'validated':req.model_dump(exclude_none=True)})
# The source transport probe's strategy zero is intentionally not backend-valid.
from pydantic import ValidationError
zeroStock=next(p['request']for p in json.loads((Path(__file__).parent/'source-output.json').read_text())['payloads']if p['id']=='stocks-zero-false')
try:
    StockScanRequest.model_validate(zeroStock)
    rejected=[]
except ValidationError as exc:
    rejected=[list(e['loc']) for e in exc.errors()]
OUT['unsupportedStrategyZero']={'request':zeroStock,'rejectedFields':rejected}
check('zero strategy tolerance is rejected by schema',True,['pullback_tolerance_pct']in rejected)
check('backend map all definitions',66,len(OUT['effective']))
(Path(__file__).parent/'backend-parameters-output.json').write_text(json.dumps(OUT,indent=2,default=str)+'\n')
print(json.dumps({'checks':len(OUT['checks']),'failed':[c['id']for c in OUT['checks']if c['status']=='fail']}))
