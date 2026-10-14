# SCREEN-LABELS-19-20 discovery

Board item: #163. Baseline: origin/main 13c8b52c.
Status: reproduction complete. Kenneth's untagged reply on #163 accepts
1 = B and 2 = A from the 2026-10-11 question comment. The plan is
docs/superpowers/plans/2026-10-14-screen-labels-19-20-plan.md.
No plan or code audit has run yet. The record below is the reproduction.

## Deciding drivers

The original finding is recorded in PROJECT_STATE.json's open questions under
`BANNER vs TOOLTIP DISAGREE ABOUT 'Driven by'`.

One Swing row, no IV reading, event in 30 days, reject window 21 and caution
window 45: IV side CAUTION; event side CAUTION; combined gate CAUTION.
`gateDrivers` returns both deciding sides, including `ivMissing: true`.

The Step 5 banner excludes missing-reading causes from its sorted cause list
and displays `Driven by: 1 on an event inside this horizon's window.`
The same row's tooltip says `Driven by: no volatility reading and event
proximity.` The banner's trailing sentence discloses missing data separately,
regardless of whether it decided the verdict. These are deliberately different
enumerations, not different status calculations.

An event-REJECT row with missing IV has only the event as a deciding driver;
missing data still needs its separate disclosure. Any change must retain that
distinction and the existing overlap-count semantics.

Presentation decision: preserve the prominent trailing missing-data sentence
and distinguish measured from missing-data deciding causes, or include missing
data in the unified deciding-driver list while retaining its disclosure.
No gate policy change is proposed.

## Duration units

`regime_omm.build_transition_matrix_stride` samples transitions every `lookback`
input bars. `compute_omm` calculates average duration as `1 / (1 - p_stay)`;
its unit is transition strides. `_regime_age` counts consecutive input bars.
Step 1 labels both as days, and shared MarketSentiment appends `d` to the average.

Deterministic Python reproduction patches state labels and the transition
matrix while executing the real `compute_omm`: 40 trailing Bull labels,
p_stay=0.8, min_obs=1, lookback 20/26/50. All three return age 40 and average
5.0. Their average durations correspond respectively to 100/130/250 input
bars. The intraday lookback is 26 fifteen-minute bars per stride. Neither age
40 nor average 5.0 is a measured calendar-day duration.

Daily lookback is configurable on Step 1; stock sentiments use per-horizon
configuration. Do not infer a universal stride from horizon alone. Conversion
or a displayed stride size needs metadata from the actual computation. Older
payloads without provenance must not receive a guessed conversion.

Presentation decision: show age in input bars and average in strides with
actual stride size, or convert average to input bars and label daily/15-minute
bars. Do not convert accumulated trading-bar time into elapsed calendar time.

## Validation required after decisions

Plan audit by a fresh independent auditor before tickets. Rendered regression
cases must cover missing-IV/event CAUTION tie, missing-IV/event REJECT,
missing-IV-only CAUTION, mixed scans and overlap counts. Duration cases must
cover configurable daily lookbacks, intraday lookback 26 and old payloads
without metadata. Preserve model probabilities, statuses and gate decisions.
Run required typecheck/full suites and integrated independent code audit.
