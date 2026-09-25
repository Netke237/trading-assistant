# P3a — Scan sizing & signal correctness — plan

Package: P3a in `docs/superpowers/plans/2026-09-25-work-packages.md`. Decisions implemented:
Q2, Q5, Q11 of BACKLOG-DECISIONS-2026-09-25. Branch `claude/wizardly-lovelace-cub58h`, off main 91e6725.

Every backlog entry was re-checked against 91e6725 before this plan. All eight are still open, with the
partial exceptions stated per item.

## Files touched

Owned by P3a: `backend/app/routers/stock_scan.py`, `backend/app/scoring/stock_scorer.py`,
`backend/app/services/strategy_engine.py` (`_build_target_ladder` only), `backend/app/routers/scan.py`
(one comment only), `frontend/lib/stockScan.ts`, `frontend/lib/analysisStore.ts`, screener step-3, step-4-prebreakout and
step-5 pages, `ScanFunnel`.

Not owned by ANY package (checked against every "Owned files" line), touched because the owned code
cannot change without them: `backend/app/schemas/stock_scan.py` (two request fields, two pipeline
fields), `frontend/lib/resolveStockScanRequest.ts` (one body field), `frontend/lib/executionParamDefaults.ts`
(one default per horizon), `frontend/types/stockDomain.ts` (two optional pipeline fields). Tests: new
test files plus edits to existing stock-scan tests and `tests/test_a4_intraday_regime_bars.py`.

NOT touched: auto_trader.py, conviction_sizing.py (P3b), scanStore.ts and schemas/__init__.py (P6),
config_loader.py (W2-DOCC), strategy_engine VWAP functions (P4b), tests/conftest.py (P4b),
tests/test_alternatives.py (P6).

## 1. Q2 — every manual scan path sizes from the user's risk settings

Today: `runStockScan` (Steps 3/4) and `analysisRequestFor` (Analysis, current-settings basis) send
`accountSize: 50_000, riskPct: 0.01`; Step 5 sends `portfolioValue` but `riskPct: 0.01`.

Change: one helper in `stockScan.ts`, `scanSizingFromRisk()`, returns
`{ accountSize: limits.portfolioValue, riskPct: limits.maxLossPerTradePct }` read from
`useRiskStore.getState()` at call time. All three paths call it. The Step 5 page stops subscribing to
`portfolioValue` through the hook and reads at click time like the other stores it reads.
The fourth manual path is the Step-4 Pre-Breakout **pullback** sub-mode
(`step-4-prebreakout/page.tsx`), which posts `/api/stock-scan` with no sizing, so the backend's 50k/1%
defaults apply and that result is persisted as the stock session other devices hydrate. It sends
`scanSizingFromRisk()` too. (The fib and prebreakout sub-modes call other endpoints that size nothing.)
The Analysis `last-scan` basis is unchanged: it replays the exact body the scan ran with, sizing included.
The stale "hardcoded here" comments are replaced.

Tests (jest): for each of the three paths, set riskStore to non-default values (73 000 / 0.02) and assert
the posted body carries `account_size: 73000, risk_pct: 0.02`. Mutation: revert any one site -> its test fails.

## 2. Q5 — `min_stock_score` in the Step-3 panel

Backend: `StockScanRequest.min_stock_score: Optional[float] = Field(None, ge=0, le=100)`. In
`_process_stock`, right after the existing `card.status == "REJECT"` drop:
`if req.min_stock_score is not None and card.score < req.min_stock_score` -> drop with reason
`REJECT score={score} < min {min:g}`. The `REJECT score=` prefix puts it in `failed_score`
(classify_stock_rejection unchanged; a test pins the bucket). `_analyze_core` adds the same check as a
REJECT `score` gate flag worded as a scan drop (StockAnalysisRequest inherits the field).

Frontend: new `PARAM_DEFS` row `min_stock_score`, section `stocks`, new subGroup `Score Gate`, number
**min 35, max 100**, step 1. The floor is 35 because any score below `stock_score_thresholds.caution` (35)
is already REJECT and dropped before this check — a lower value would display a gate the scan cannot
apply. The backend field is `Field(None, ge=0, le=100)` and the hint says values at or below 35 add
nothing beyond the existing REJECT drop. Default per horizon in `executionParamDefaults.ts` is 35 — `stock_score_thresholds.caution`,
the floor the scan already applies through the REJECT status — so an untouched field changes nothing and,
being equal to the default, is never sent. The hint says it applies to **Stocks-mode scans only** (the
Options scan does not read it). `buildStockScanRequestBody` sends `min_stock_score` only when the override
is a number. A jest test pins the default to `lib/status.ts`'s caution threshold so the two cannot drift.

## 3. Q11 — measured vs unmeasured trend score

Scorer: `RuleResult` gains `measured: bool = True` (defaulted, so every existing construction is
unchanged). Set `measured=False` on the three returns that have no measurement: crossover
`insufficient_data`, additive `insufficient_data`, relative_strength `no_benchmark_data`.

Gate (`_direction_conviction_drop`, shared by scan and Analysis): when the horizon is gated
(`min_trend is not None`) and the trend rule is missing or `measured is False`, drop with reason
`direction_conviction_unmeasured: no trend measurement for {direction} {horizon}`. Fail-closed, like
SIZING-4's unmeasured floor: an unmeasured name cannot show the conviction the gate requires. It is no
longer scored as a measured 0 (crossover) or a measured 50 (relative_strength, which PASSED a 30 floor).
Remove-vs-keep was put to Kenneth as a new question after plan round 1: **Remove** (decision
P3A-UNMEASURED-TREND-REMOVE-2026-09-25, recorded in PROJECT_STATE.json).

Relative strength must actually be measured, or the decision above empties every scan that selects it:
today no caller passes `benchmark_candles` to `score_stock`, so `relative_strength` is unmeasured on EVERY
card. New helper `_rs_benchmark_candles(req)` in stock_scan.py: when the effective trend method
(`req.overrides["trend_method"]` else `horizons.<h>.trend.method`) is `relative_strength`, it resolves the
effective benchmark (`req.overrides["rs_benchmark"]` else `horizons.<h>.trend.relative_strength.benchmark`)
to its ETF proxy (`SPX -> SPY`, `NDX -> QQQ`; an unknown name -> None, i.e. unmeasured, never a
substitute index) and fetches it with `get_historical_bars`. Called once per scan in
`_execute_stock_scan_core` (passed to every `_process_stock`) and once in `_analyze_core`; both pass it as
`score_stock(..., benchmark_candles=...)`. A fetch failure -> None -> unmeasured -> dropped as "no data",
never a fake 50. ROC over an ETF vs its index differs only by dividends over 20-50 days (well under the
RS thresholds' 0.5-point steps). Test: a relative_strength scan with benchmark bars yields a measured trend
and the fetch is asked for `QQQ` on an NDX config / override and `SPY` on SPX.

The `, 50` fallback for a missing rule is removed; the fixtures that built `rules=[]` for a PASS card that
reaches the gate get a real trend rule.

Funnel: `classify_stock_rejection` gets bucket `failed_direction_unmeasured`; `StockPipeline` gets
`failed_direction_unmeasured: int = 0`. The stock `ScanFunnel` Direction stage subtracts both and labels
them separately: `−N no conviction (trend < X)` and `−M no data`. The stage renders when
`failed_direction + failed_direction_unmeasured > 0` (today it renders only on `failed_direction > 0`, which
would hide an all-unmeasured drop). Jest test: `failed_direction: 0, failed_direction_unmeasured: 4` renders
the row with `−4 no data`.

Options gate (`routers/scan.py`) reads `stockBreakdown.trend`, an int on a schema owned by P6, and P3a may
only edit comments there. It gets a comment saying it cannot see `measured`; the gap is logged as an open
question (it needs a schemas/__init__.py field and scan.py code).

## 4. Backlog: direction-conviction threshold invisible (half b)

`StockPipeline.direction_min_trend: Optional[float] = None` — the floor THIS scan applied (resolved once in
`_execute_stock_scan_core`; `None` = exempt horizon). The funnel prints it: `no conviction (trend < 30)`.
Reading it from the result, not from a config fetch, shows the value the scan actually used.
Options half stays open (scan.py code, same reason as above); logged.

## 5. Backlog: negative bearish backtest price + misleading banner

(a) `_build_target_ladder`: the guaranteed fallback rung is the one value never checked for `> 0`
(`_valid` already drops non-positive primary/extension rungs). A bearish fallback at or below zero, and the
sub-cent one-tick nudge landing at or below zero, now return `[]`. Every one of the 8 callers already does
`if not targets: return None`, so the bar has no signal — honestly, since no positive short target exists
— instead of a signal whose `tp` makes backtesting.py assert and remove the name as `failed_backtest`.
Docstring's "guaranteed non-empty" corrected. Tests: bearish entry 10, stop 30 (risk 20) -> `[]`; the
public signal (pullback_ema) returns None on such a bar; bullish unchanged.

(b) Split hypothesis: verified only if bars are obtainable in this container; otherwise it stays an open
question (data-side, and it affects bullish targets silently). Not code in this package either way.

(c) `direction_banner` when a stock scan ends empty and the direction gate removed any name: replace the
causal claim ("market structure does not support ...") with counts:
`No {direction} candidates survived. The direction-conviction gate removed {n} of {scanned} (trend below {X}); the rest were removed by other gates — see the pipeline.`

## 6. Backlog: options-scan bar-window comment (scan.py)

Comment only: `1.75 * 252` = 441 calendar days ≈ 316 weekdays ≈ 306 trading days. The source-length
residual (DB ~306 / Tradier 252 / yfinance ~1250 bars) needs scan.py code and stays open.

## 7. Backlog: conviction input frame unpinned

New test driving `_process_stock` for a **Bearish** scan (harness from
`test_stock_scan_unmeasured_floor.py`): `compute_omm` is asserted to receive `direction="Bearish"` and
returns `conviction_pct=20`; the card's `dollar_risk` must equal `budget × conviction_mult(20)` and differ
from `conviction_mult(-20)`. Mutation: negate the conviction at the call site -> fails.

## 8. Backlog: risk_pct null loses the conviction multiplier

`_process_stock` resolves the base percentage before multiplying: no `risk_fixed_usd` and `risk_pct` None
-> base `_DEFAULT_RISK_PCT = 0.01`, then `× mult`. `_position_size` no longer hides a fallback (`or 0.01`);
it receives the already-sized figure. `risk_pct` gets `Field(0.01, gt=0, le=1)` (a 0 was silently turned
into 1% by the `or`) and `account_size` `gt=0`. Test: `risk_pct=None`, sizing on, conviction 20 ->
`dollar_risk == 50_000 × 0.01 × conviction_mult(20)`.

## 9. Backlog: A4 semaphore test gap

`test_a4_intraday_regime_bars.py` `_sem()` becomes a recording fake: `__aenter__` sets `held`,
`__aexit__` clears it; the intraday fetch's side effect records `held` at call time. New assertion: the
15-min fetch ran while the scan semaphore was held. The second half of that entry (the fire-path
sizing-floor test also passes without the timeframe branch) is already caught by
`test_fire_path_measures_intraday_on_the_same_15_minute_series`'s fetch-args assertion, as the entry itself
says; auto_trader.py is P3b's and is not touched.

## 10. Backlog: Analysis fetches 80 days of 15-min bars, the scans 55

One module constant `_INTRADAY_FETCH_DAYS = 55` used at all three `fetch_intraday_candles` calls in
stock_scan.py. Test: Analysis calls `fetch_intraday_candles(symbol, "15min", 55)`.

## 11. Entry "CORRECTED 2026-09-23" — the stock_scan.py items only

(6) the pre-check comment cites the gather by a line number that has drifted -> cite it by name.
(7) the pre-check calls `_load_full_scoring_cfg()` unguarded: a document that parses to a non-mapping
raises AttributeError past `except SizingConfigError` -> a bare 500 with no detail and no log line. The
pre-check now loads the document once in a `try` catching `(OSError, yaml.YAMLError)`, checks it is a
mapping, and raises the same logged `HTTPException(500, detail=...)` as its neighbours.
(9) a raised exception in the gather is recorded as `{'symbol': 'unknown'}`: results are zipped with
`symbols` so the real symbol is named.
Items (3)(4)(5)(10) are in conviction_sizing.py (P3b) and stay open; the entry is annotated, not closed.

## Out of scope, stated

Stock `direction_banner` is not rendered anywhere in the stocks UI today (only the options Step 4 shows its
own). Not changed. The backend's `account_size=50_000` default remains for any non-UI caller that omits it; every
manual UI path now sends the user's values.

## Verification

Backend `cd backend && .venv/bin/python -m pytest -q`; frontend `npx tsc --noEmit && npx jest`;
`python3 scripts/state.py` exit 0. Mutation checks listed per item. No test writes backend/config/*.yaml
or runs the app lifespan.

## PROJECT_STATE

One phase `P3A-SCAN-SIZING-SIGNALS`, verify probe `present` on `failed_direction_unmeasured` in
`backend/app/routers/stock_scan.py`. Finished entries move to closed_questions with evidence; the partial
ones (options halves, split hypothesis, P3b items) stay open with a note.
