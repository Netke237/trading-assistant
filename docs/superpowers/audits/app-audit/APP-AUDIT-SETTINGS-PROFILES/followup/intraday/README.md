# Real 15-minute regime fixture follow-up (#396 / #350)

This is new evidence for the real intraday fixture gap in the original audit.
The original `regime/` capture is historical evidence and remains unchanged.
This follow-up changes no product behavior or calibration. Its source baseline
is `4b1f6b86e8137f499da0c4c430f23b9c250fd8de`.

## Capture and provenance

The authorized read-only request was made against the configured Tradier
market-data endpoint `https://api.tradier.com/v1/markets/timesales`:

```json
{"symbol":"SPY","interval":"15min","start":"2026-09-01","end":"2026-10-15","session_filter":"all"}
```

The response was HTTP 200, received **2026-10-16 20:29:54.556538 UTC**
(22:29:54.556538 Europe/Berlin). `provenance.json` is the unchanged capture
receipt. The normalized `spy-15min-response.json` preserves every provider bar
field and value. Its SHA-256 is
`cc5f42354095d7f5374a1ab6a1c8206376ab25d084287ffe0bed36216732d709`.
This hashes sanitized, pretty-printed fixture bytes, not original HTTP transport
bytes. No credentials, account data or order data are included.

There are 2,480 SPY bars, from September 1 at 00:00 Eastern through **October 15
at 00:00 Eastern**. The `end` query does not imply a complete October 15 session:
only its midnight bar was returned. The fixture spans 44 calendar days, while
Step 1 requests 55; it is ample for the most-recent-800-bar HMM cap, but does not
certify missing historical days. This is configured-provider provenance, not
independent certification of exchange-feed accuracy or current market freshness.

## Reproduce offline

From the repository root, with the prepared Python 3.11 environment:

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 backend/.venv/bin/python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/intraday/replay.py
```

The command writes `output.json`. To retain the committed output, pass
`--output /tmp/audit350-intraday-replay.json`. It makes no provider requests and
boots no application, jobs, database or notification service. It injects all
router/adapter providers, and blocks external socket connections and DNS.
Local loopback sockets remain available for Python's `asyncio.to_thread` wakeups.
In this cloud execution environment the command needs network-enabled execution
permissions for those local wakeups; without them it stalls in the event loop,
not in model fitting. No such stalled run counts as passing evidence.

The successful capture uses Python **3.11.16**. The output records source/config
file hashes, dependency versions and installed dependency `RECORD` hashes.

Optional read-only capture code is provided for a separately authorized rerun:

```bash
# Uses the existing runtime TRADIER_API_TOKEN binding; do not copy/print secrets.
backend/.venv/bin/python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/intraday/replay.py --fetch /tmp/audit350-new-intraday-capture
```

`--fetch` permits only the fixed query above, rejects HTTP redirects, reads its
token only from the existing runtime `TRADIER_API_TOKEN` binding, preserves the
configured proxy and CA trust, and writes a new directory. It does not replace
the committed fixture or run the application. A new capture would require its
own provenance/review; the default replay continues using this committed one.
The follow-up did not need another fetch beyond the supplied receipt.

## Expected versus actual

The replay passes **30/30 named checks**, with zero numerical mismatches in this
scope. Full expected/actual records are in `output.json`; long arrays compare
canonical JSON SHA-256 fingerprints, counts and first/last elements. Original
observations remain in the fixture, and all expectations are recomputed.

| Measurement | Independent expectation | Actual application helper |
| --- | --- | --- |
| Eastern-naive time versus provider epoch | All 2,480 agree | Actual Tradier adapter produces identical normalized bars |
| Order, duplicates, finite values and OHLC bounds | Strictly ordered, unique, finite, valid | 2,480 valid bars; none removed by adapter |
| Completed cutoff at frozen receipt, live feed lag 0 | 2,480 complete, 0 dropped | Identical; final start is October 15 04:00 UTC |
| Completion boundary with feed lag 0 and 900 seconds | Exclude one second before; include exactly at/after completion | All six boundary checks pass |
| HMM cap and returns | Most recent 800 completed bars → 799 returns | Exact full fit-input fingerprint match |
| Real-fit terminal forward posterior | `[0.7933214460744222, 0.20667855392557788, 1.976839311317815e-17]` | Maximum absolute error `1.0436096431476471e-14` |
| Intraday HMM state / transition diagonal | Trending / `p_stay=0.0009` | Identical; transition to Choppy `0.9991` |
| Fallback OMM | Bear; row `[0.25,0.25,0.5]`; stay `0.25`; Fragile | Identical |
| OMM trailing age / average | 1 input bar / 1.3 transition strides of 26 bars | Identical; route echoes stride 26 |
| OMM default `min_obs=100` | Real prefixes at 99 observations fail, at 100 publish | Identical; full fixture has 123 current-state observations |
| OMM `.002` strict boundaries | Equality at ±`.002` is Choppy, beyond is Bull/Bear | Supplemental exact-threshold cases agree |
| Step 1 router request | SPY, 15min, 55 days | Both HMM and fallback paths agree |

The actual `GaussianHMM` fit is unmodified: seed 42, three states, full covariance,
100-iteration limit. A wrapper records its fit inputs and fitted parameters while
calling the original fit. It converged after six iterations. Independent scalar
Gaussian densities and scaled forward recursion on the last 30 returns reproduce
the fitted model's terminal inference; independent emission-label assignment and
transition lookup reproduce returned values. `p_stay` is the selected state's
transition diagonal, **not the terminal posterior probability**.

This independently checks inference conditional on fitted parameters. It does
not independently optimize those parameters or establish predictive accuracy,
state semantics, calibration, convergence quality, or out-of-sample performance.
The captured fit includes one effectively unused state with a very large
variance; the output preserves it without recalibration or a claim that the
model is statistically sound.

The independent OMM uses scalar rolling returns, smoothing `.2`, threshold
`.002`, lookback/stride 26, trailing window 500 and minimum 100 observations. It
reconstructs every label and the transition-count matrix, then compares the
actual service's state, row, age, duration, stability and conviction. Minimal
router calls confirm HMM wiring and real-bar OMM fallback when dependency
availability is injected as absent. The router uses the captured HMM result;
the separate service call performs the real optimizer fit.

## Units, defects and remaining limits

The current age is **one 15-minute input bar**. The average is **1.3 strides of
26 input bars**. There are 806 regular-session bars among 2,480 all-session bars.
Across this fixture, 26-bar intervals span 6.5 to 82.5 elapsed hours because of
session gaps and weekends. A 26-bar stride must not be described as one day or
one regular session. The current source formats bars and strides explicitly;
no rendered UI assertion is made by this Python replay.

No new numerical defect was found in these measurements. UI defects and their
remediation/retests remain separate from this fixture/inference result. This
follow-up closes only the real-intraday numerical evidence gap; it does not
close #350 or establish overall application acceptance. Live merged
Tradier/yfinance behavior, every historical missing bar, exchange accuracy,
predictive model quality, and account/order integrations remain untested here.

Independent review and its acceptance decision are recorded by the parent
workflow, not inferred from this implementer's passing replay.
