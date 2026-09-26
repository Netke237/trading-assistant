"""Generate python_round4.json: Python's own round(x, 4) for a fixed table.

The frontend's `pythonRound4` (lib/premiumStop.ts) must reproduce what
`alert_generator.py` stores as `reference_value=round(threshold_price, 4)`.
This script is the source of truth for that test; rerun it with the backend's
interpreter if the table changes:

    backend/.venv/bin/python frontend/lib/__tests__/fixtures/gen_python_round4.py

Values are written with repr(), which round-trips to the identical double in JS.
"""
import json
import pathlib
import random

named = [
    # near-halves that are NOT binary ties (decimal-looking, exact value off .5)
    0.00035, 0.00095, 0.00115, 2.00015, 1.00005, 0.12345, 3.14155,
    # true binary ties: odd multiples of 1/32 -> half-to-even
    0.03125, 0.09375, 0.40625, 1.03125, 2.53125, 7.96875, 1.09375,
    # ordinary thresholds: entry x (1 - pct)
    4.0 * (1 - 0.07), 5.2 * (1 - 0.6), 8.0 * (1 - 0.075), 2.6816400000000003,
    0.0, 1e-9, 12.5,
]
rng = random.Random(20260925)
sweep = []
for _ in range(5000):
    entry = rng.randint(1, 5000) / 100
    pct = rng.randint(1, 9999) / 10000
    sweep.append(entry * (1 - pct))
# every odd multiple of 1/32 up to $20 -- the complete set of 4dp ties there
ties = [m / 32 for m in range(1, 640, 2)]

rows = [[x, round(x, 4)] for x in named + sweep + ties]
out = pathlib.Path(__file__).with_name("python_round4.json")
out.write_text(json.dumps(rows) + "\n")
print(f"wrote {len(rows)} rows to {out}")
