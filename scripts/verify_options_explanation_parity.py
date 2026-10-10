import dataclasses, importlib.util, json, random, subprocess, sys, tempfile
from datetime import date, timedelta
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
from app.scoring.contract_validator import validate_contract, CONFIG_PATH
workspace = tempfile.TemporaryDirectory(prefix='options-parity-')
baseline = Path(workspace.name) / 'baseline_validator.py'
baseline.write_bytes(subprocess.check_output(['git','show','ac39b841:backend/app/scoring/contract_validator.py'],cwd=root))
spec = importlib.util.spec_from_file_location('options_baseline_validator',baseline)
module = importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
module.CONFIG_PATH=CONFIG_PATH
rng=random.Random(20261003)
for i in range(10000):
    days=rng.randrange(1,180); bid=rng.uniform(.01,8); ask=bid+rng.uniform(.001,2)
    c=dict(symbol='AAPL',strike=185,expiry=(date.today()+timedelta(days=days)).isoformat(),is_call=i%2==0,
           bid=bid,ask=ask,volume=rng.choice([0,1,20,50,200,500,5000,None]),open_interest=rng.choice([0,100,200,500,5000,None]),
           delta=rng.choice([None,rng.uniform(-1,1)]),iv_rank=rng.choice([None,rng.uniform(0,100)]),iv_basis=rng.choice(['rank','absolute','none']))
    overrides=rng.choice([None,{'preferred_spread_pct_max':.0555,'max_bid_ask_spread_pct':.04761},
                          {'preferred_volume_min':0,'preferred_oi_min':0,'preferred_delta_min':.45,'preferred_delta_max':.45},
                          {'min_dte':5,'max_dte':200,'min_delta':.200002,'max_delta':.899998}])
    stock=rng.randrange(0,101)
    old=dataclasses.asdict(module.validate_contract(c,stock,overrides)); new=dataclasses.asdict(validate_contract(c,stock,overrides))
    old.pop('explanation'); new.pop('explanation')
    assert old==new, (i,old,new)
print(json.dumps({'baseline':'ac39b841','fixtures':10000,'seed':20261003,'comparison':'exact full score card excluding additive explanation','result':'pass','python':sys.version.split()[0]},indent=2))
