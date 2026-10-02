"""Generate premium_stop_subcent.json: the sub-cent predicate and the short
threshold, computed by Python exactly as `backend/app/services/premium_stop.py`
does, for the TS twins in `lib/premiumStop.ts` to reproduce (STOP-SEMANTICS).

    python3 frontend/lib/__tests__/fixtures/gen_premium_stop_subcent.py

Every input is built from integers the same way in both languages
(`cents / 100`, `bp / 10000`, `d / e`), so the doubles are identical and any
disagreement is a real divergence, not test noise. Thresholds are written with
repr(), which round-trips to the identical double in JS.

Sections:
  long   [entry_cents, pct_bp, is_sub_cent]    entry $0.01-$2.00 x pct 10%-99%
         by 25 bp, kept only where |entry*(1-pct) - 0.01| < 0.005 (the boundary)
  dollar [entry_cents, dollar_cents, is_sub_cent]  the d = e - $0.01 family for
         every entry $0.02-$50.00, pct = d / e (the float-noise family)
  short  [entry_cents, pct_bp, threshold]      entry $0.01-$200.00 (stepped) x
         pct 10%-99% by 25 bp, kept where entry*(1+pct) is within 1e-6 of a
         whole cent -- the rows where float noise decides the firing cent
"""
import json
import pathlib


def is_sub_cent(entry: float, pct: float) -> bool:
    # Literally premium_stop_is_sub_cent(entry, pct, False).
    return entry > 0 and not (0.01 <= entry * (1 - pct))


long_rows = []
for ec in range(1, 201):
    for bp in range(1000, 9901, 25):
        e, p = ec / 100, bp / 10000
        if abs(e * (1 - p) - 0.01) < 0.005:
            long_rows.append([ec, bp, is_sub_cent(e, p)])

dollar_rows = []
for ec in range(2, 5001):
    e = ec / 100
    d = (ec - 1) / 100
    dollar_rows.append([ec, ec - 1, is_sub_cent(e, d / e)])

short_rows = []
for ec in list(range(1, 2001, 7)) + list(range(2000, 20001, 211)):
    for bp in range(1000, 9901, 25):
        e, p = ec / 100, bp / 10000
        t = e * (1 + p)
        if abs(t * 100 - round(t * 100)) < 1e-6:
            short_rows.append([ec, bp, t])

out = pathlib.Path(__file__).with_name("premium_stop_subcent.json")
out.write_text(json.dumps({"long": long_rows, "dollar": dollar_rows, "short": short_rows}) + "\n")
print(f"wrote long={len(long_rows)} dollar={len(dollar_rows)} short={len(short_rows)} to {out}")
