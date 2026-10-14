# STOCKS-HORIZON-T4 — setup backtests and per-horizon tuning

Tracking: #118. Branch: board/stocks-horizon-t4-a4153a02. Base: afbd292f.
Design input: closed #170, comment 6107671713 (2026-10-11); ADR 0001.
Scope: backend research/backtests and T1 CLI. Pullback sub-mode already uses
pullback_ema and is excluded. No adoption, broker, watch, alert or scanner UI
change. Existing scanner response and confidence formulas stay unchanged.
Historical evidence runs need the mini-PC database; fixtures verify machinery
only and cannot establish a profitable or adopted cell.

## Model

Add strategy identifiers `breakout_setup` and `fibonacci_pullback` to the research
machinery. Neither existing setup detector becomes a StrategySignal: introduce
an explicit setup-confirmation series, reused by the backtest and tuner.
Use the existing 400-bar window, direction normalization and float OHLCV,
with no current quote. Start detecting after 60 bars, as existing backtests;
tuning additionally requires its 400-bar warmup at BOTH setup and trigger.

Only one pending setup per symbol/strategy. Keep the earliest setup frozen;
later detections do not refresh its expiry or replace its geometry. After
confirmation or expiry, detection resumes on the next close. Never confirm on
the setup close: eligible trigger bars are s+1 through s+N inclusive. Expiry
at s+N with no confirmation produces no order. Every confirmed event includes
its setup age, order type, stop, target and optional R multiple. The series is
independent of holdings: a simulator ignores confirmations while positioned;
it never resurrects an ignored confirmation. New setups while holding may be
detected; any entry must be a NEW confirmation after the previous trade closes.

### Coil

Use breakout_setup_signal on the prefix window. Freeze unrounded swing high
(Bullish) / low (Bearish) from swing_lookback; do not use the rounded metrics
for execution levels. Freeze the coil low/high over range_lookback_bars.
Stop = math.nextafter(coil low, -inf) / math.nextafter(coil high, +inf): the
minimum representable offset beyond the boundary, not an invented ATR buffer.
This is a daily-bar research convention; real exchange tick rounding is out of
scope since there are no executable orders here. Confirmation = first close
strictly beyond frozen swing level. Optional volume confirmation on that same
bar: volume >= volume_confirm_mult * mean of PREVIOUS 20 volumes (excludes
trigger volume). Off by default, multiple 1.5. Target = actual fill plus/minus
rr_multiple * abs(fill-stop), default 2.0, frozen when filled.

### Fibonacci

Reuse fibonacci_pullback_detail to get the nearest configured level and frozen
swing extrema. Require at_level AND the existing Fib scanner EMA-side filter
at detection (period 20, zero disables); nearest-level research rows outside
tolerance are not touches. Defaults mirror the Fib scanner: lookback 100,
levels [38.2,61.8], tolerance .015, impulse .08, recency 40, EMA 20.
Touch is the detector's CLOSE within tolerance; do not silently replace its
close-based selection with an intrabar high/low rule. Confirmation is a later
close strictly above the frozen touched level for Bullish / below for Bearish.
Stop is nextafter of the next deeper configured valid Fib level; if touched
level is deepest configured, use swing origin (100%). Target is the frozen
swing extreme (0%). Geometry never follows a subsequent moving swing window.

### Fill and exits

Market entry at trigger+1 open, no limit condition. Reject an entry when the
open is not strictly between stop and target, or risk/levels are not positive
finite. Coil R target is computed from that open, not the trigger close.
Stop/target are active on the fill bar. Check stop before target, and fill a
gap through stop/target at open; both touched => stop. Time exit uses T1's
calendar-days holdMax, queued at the due close and filled next open with
priority over brackets. No intrabar time stop and no forced final liquidation.
One position at a time; whole-unit all-equity sizing and per-leg commission
match the existing simulator. Dropped final open trades remain counted.

Signals on the final bar cannot fill. Entry windows apply to setup and trigger
close; the next open may lie after entry_end as in existing T1 signal windows.
Before-entry_start setups must not cross into a scored window. Truncate at
train/heldout restrictions as T1 already does. Gates at setup AND confirmation
must allow entry. Store setup AGE, not absolute index, so sliced cached series
preserve original dates/geometry. Extra_allowed restrictions must also apply
to both setup and trigger to preserve the union-of-train-windows tie break.

## Backtest and compatibility

Extend SignalPoint with defaulted market/R/setup-age fields; legacy 3-field
points remain DAY limit orders with their existing fill-bar deferral. Extend
simulate_trades only behind the explicit market flag. Existing 864-case T1
parity product must still pass. Record equity through the simulator, using
cash and marked open positions (including entry commissions), for setup-only
BacktestResult return/drawdown/Sharpe via _window_stats; net expectancy and win
rate use CLOSED trades. Time-exit counts come from trade exit reasons.

strategy_backtest dispatches the two setup IDs to a small adapter using that
series and simulator. Keep unknown IDs' current empty-result behavior and
legacy code unchanged. Setup adapter requires dated ascending daily bars;
invalid commission / insufficient bars return explicit empty results as
legacy does; malformed setup parameters fail clearly, not fabricated trades.
Backtests are research measurements; no eligibility verdict is persisted or
adopted and no live PASS/broker behavior is added.

## Per-horizon integration

Add baseline blocks and `search_by_horizon` for both IDs, five horizons and
both directions; retain existing breakout_setup scanner baseline keys exactly.
Only new exit/confirmation tunables: setup_expiry_bars, volume_confirm,
volume_confirm_mult, rr_multiple (coil only). All existing detector values
remain fixed baseline values. Coil grid per horizon: expiry [3,5,8],
volume_confirm [false,true], multiple [1.5], rr [1.5,2,3] (18 combinations).
Fib grid per horizon: expiry [3,5,8] (3 combinations). These are research grids,
not adopted profiles. No active horizon keys or auto-adoption writes.

invalid_reason validates the two new strategies' keys/types/bounds and required
lookbacks <=400, including volume average and EMA; bars_needed must describe
them without falling through to another strategy. Reject unknown parameters
instead of silently ignoring misspellings. signal_series branches to the setup
state machine; TuningCache round-trips all additional fields and bumps version.
Fingerprint includes setup engine code / series code and order semantics, so
old cache files and CLI resume manifests cannot produce stale results.
CLI --cells accepts both IDs. Keep the existing default six strategies to
preserve existing default-run scope; explicit IDs select these research cells.
Update projection/probe and full-universe recheck to use their real signals.
T1 gate-mask exclusions and full-universe provenance/heldout/cost/CI thresholds
stay unchanged. Fire-rate for these cells means GATED CONFIRMED ENTRY EVENTS,
not raw setup scanner rows; use the same setup+trigger gate check in selection,
sample and full-universe counts. Label that distinction in reports and state
that their scanner UI has no backtest/adoption/entry/exit integration. At both
.0005 and .002 per leg, report real pooled trades, no-winner/thin data and
boundary dropped trades. No surrogate pullback_ema or breakout_base evidence.

## Tickets (cut only after independent plan audit is clean)

1. Setup event model and simulator/backtest (new setup_entries.py,
   setup_backtest.py, horizon_tuning/signals.py, simulate.py,
   strategy_backtest.py, strategy_engine.py bars_needed only;
   tests/test_setup_backtest.py). Test first: deterministic bullish/bearish
   fixtures for all design rows, expiry N/N+1, frozen levels, later swing
   mutation, volume threshold/excluded trigger volume, Fib depths/default
   100%, actual-open R and invalid fill gaps, immediate fill-bar both-hit,
   stop/target gaps, costs, time priority/weekends, last-bar/no liquidation,
   window isolation/setup gates and equity statistics. Independently calculated
   expected prices/returns; prefix-vs-full series test for no lookahead.
2. T1 integration (cache.py, walk_forward_cell.py, report.py, YAML,
   backend/scripts/tune_horizons.py; tests/test_setup_tuning.py). Test first:
   every direction/horizon grid valid <=150, exact baseline/profile defaults,
   full cache roundtrip/invalidation, CLI accepts IDs and resume identity,
   setup+trigger gate count consistency, short synthetic walk-forward with
   actual new signals/trades and heldout isolation. Existing T1 test modules
   and 864-case parity run green. Full-universe recheck must work for both
   market event series; fixture evidence clearly labelled synthetic.

Each ticket: fresh implementer, Python backend/.venv/bin/python 3.11.16;
frontend typecheck before committing, backend focused plus full suite.
Coordinator records exact audit scopes/counters and pushes each completed
build ticket before closing it. Before code round 1 merge current origin/main,
rerun appropriate checks, and independently audit the whole application diff.
Cap three rounds per stage; follow-up rounds only fixes/interactions. Use
numeric/persistence gate from PROJECT_STATE.json. Merge only after board.md
self-merge conditions including CI on exact head. If historical data unavailable,
report machinery validation and defer historical evidence to mini PC; never
claim measured adoption or profitability.
