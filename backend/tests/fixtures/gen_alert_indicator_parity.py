"""Generate exact alert-reading fixtures with the Docker/CI Python 3.11 runtime.
Run from repository root with PYTHONPATH=backend and Python 3.11.
"""
import json
import random
import sys
from pathlib import Path

if sys.version_info[:2] != (3, 11):
    raise RuntimeError('Generate this fixture with the pinned Python 3.11 runtime')

from app.services.indicator_compute import compute_indicators_for_conditions

refs = ['EMA(7)', 'EMA(8)', 'SMA(8)', 'RSI(5)', 'ATR(6)', 'MACD(3,5,2)',
        'macd_signal(3,5,2)', 'MACD(12,26,9)', 'BB_MID(8,2.5)',
        'BB_UPPER(8,2.5)', 'BB_LOWER(8,2.5)', 'VWAP', 'volume']
rnd = random.Random(77)
histories = {
    'empty': [],
    'short': [100, 100.01],
    'seed_boundary': [99.57,99,99.57,100.89,100.37,100.57,99.64,100.58],
    'recurrence_boundary': [100.05,99.87,100.46,100.38,100.08,99.69,99.61,99.4,99.96],
    'cent_decay': [100]*7 + [100.01] + [100]*16,
    'flat': [100]*40,
    'random_cents': [round(99+rnd.random()*2, 2) for _ in range(40)],
}
cases = []
for name, closes in histories.items():
    bars = [dict(time=1720000000+i*3600, open=c, close=c, high=c+1, low=c-1, volume=100+i*10)
            for i,c in enumerate(closes)]
    conditions = [dict(kind='indicator', indicator=r) for r in refs]
    points = compute_indicators_for_conditions(bars, conditions)
    expected = {r: [[p['time'], p['value']] for p in series if p['value'] is not None]
                for r,series in points.items()}
    cases.append(dict(name=name, closes=closes, expected=expected))
path = Path('frontend/lib/__tests__/fixtures/alert_indicator_python311.json')
path.write_text('{"python":"3.11","cases":[\n' + ',\n'.join(json.dumps(c, separators=(',', ':'), allow_nan=False) for c in cases) + '\n]}\n')
