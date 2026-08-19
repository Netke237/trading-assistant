# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-19 (round 4, finalized)
**Branch**: `chore/consolidate-backend-venv` (finalized on `worktree-fix-strategy-scoring-findings` and merged in — see the implementation plan `docs/superpowers/plans/2026-08-19-round4-benchmark-sync-and-fix.md`)
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | **PASS** — 1526 passed, 3 skipped, 0 failures (backend); 77 suites / 611 tests, 0 failures (frontend); typecheck/build all green |
| 2. Trading-logic (algorithmic) soundness | **CAUTION** — mechanism sound; `breakout_base` calibration and the live-vs-WFO cost-modeling gap (this round's original findings) were already fixed on `worktree-fix-strategy-scoring-findings`, not re-derived (see "Since last run"). Real-data evidence re-measured post-fix (see axis 2) — a genuine data-availability gap, not a code defect, is what keeps this axis at CAUTION rather than PASS. |
| 3. Config / settings sanity ("as a trader", best-effort) | **PASS** — `SCORING_RULES.md` drift already fixed on `worktree-fix-strategy-scoring-findings`; the two remaining Low findings are closed (DTE: confirmed intentional design) or fixed (`min_stock_score` raised to 55) |

Overall = worst of the three (`worstStatus()`), per the skill's rubric. No axis hit REJECT this round — no lookahead bug, no overlapping WFO folds, no risk-config value missing a cap.

---

## Since last run (round 3, 2026-08-08) — fixed / still-open / new

### Root cause discovered mid-round: this round's three "new" Medium findings were a stale-branch artifact, not new bugs

The round-4 audit (first pass, run against `chore/consolidate-backend-venv` as it stood on 2026-08-18) flagged three "new this round" Medium findings: the `breakout_base` calibration bug, the live-vs-WFO cost-modeling gap, and `SCORING_RULES.md` drift. Before implementing fixes, `chore/consolidate-backend-venv` was compared against `main` and the `worktree-fix-strategy-scoring-findings` worktree:

- All three fixes were already committed on the `worktree-fix-strategy-scoring-findings` branch itself (`26068d5`, `d4d837c`, `a0cc6a3`, `edbe380`, `19fc720`), then independently re-verified sound through three completed rounds of adversarial audit (`b3707cc`, `d5bfd3d`, `b310106`) — that branch's current tip. `main` (and `origin/main`) also has them, but only because `main` later merged that branch in (commit `86c946d`, "Merge branch 'worktree-fix-strategy-scoring-findings'") — the fixes did not originate on `main`.
- `chore/consolidate-backend-venv` was branched before either of those things happened and never picked up the `worktree-fix-strategy-scoring-findings` branch's work — confirmed directly: its `strategy_engine.py:344` still read `atr_tight_max: float = 1.5` (the bug), its `strategy_backtest.py:123` still hardcoded `commission=0.0` with no parameter, and its `SCORING_RULES.md` still read `pass: 70` (all matching the pre-fix state that predates that branch's own work).

The mechanism/config fixes for these three findings already existed, already independently re-verified sound by three rounds of adversarial audit — they did not need to be re-derived. The actual round-4 work was: merge `worktree-fix-strategy-scoring-findings` (which already had the fixes) directly into `chore/consolidate-backend-venv`, without going through `main` at all — merging via `main` was considered and rejected, since `main` also carries unrelated commits (a separate code-review-artifact fix, CI/e2e changes) with nothing to do with strategy scoring, and pulling those in here would have been undisclosed scope creep.

### Fixed since round 3 (confirmed this round)
| Item | Status |
|---|---|
| Frontend lockfile committed, CI back on `npm ci` | **Confirmed** — `frontend/package-lock.json` tracked, `.github/workflows/ci.yml` uses `npm ci` with proper cache config |
| Stray root-level `package.json` removed | **Confirmed** — no root `package.json` exists |
| `npm audit` reduced to 1 high (xlsx, no upstream fix) | **Confirmed unchanged** — still exactly 1 high (`xlsx` ReDoS/prototype-pollution advisories, no fix available) |
| `iv_rank_*: null` for intraday — deliberate vs. accidental | **Resolved** — confirmed deliberate, explicitly coded (`stock_scorer.py:880-884`), not a silent gap. Closed. |
| `breakout_base_signal`'s tight-base gate unfireable on real data | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`26068d5`, `atr_tight_max` 1.5 → 4.0); brought into `chore/consolidate-backend-venv` by merging that branch directly, not re-derived |
| Live/UI-facing backtest ran cost-free while the WFO tuner netted out costs | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`d4d837c`, `a0cc6a3`); Step-6 backtest now takes a `commission` parameter and the cache key includes it |
| `SCORING_RULES.md` drifted from live `scoring_rules.yaml` | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`edbe380`, `19fc720`) |
| `contract_rules.yaml`'s DTE soft-preference floor duplicates the hard-reject floor (21==21) | **Investigated, not a bug** — see below |
| `contract_rules.yaml`'s `min_stock_score: 50` sits below the stock `pass` bar (55) | **Fixed this round** — raised to 55 |

### Still open (carried from round 3, re-confirmed)
| Item | Status |
|---|---|
| No real-data evidence any strategy clears `_MIN_TRADES=10` | **Still open** — zero of 20 real-data strategy×symbol combinations reach the gate (unchanged headline from rounds 3 and 4); requires multi-year historical data this environment does not have, not a code fix |
| `signal_confidence.py` single in-sample pass, not WFO-validated | Still open (Low) — out of scope for this round |
| Complexity-penalty weight (0.05/param) untested against real optimizer runs | Still open (Low) — out of scope for this round, blocked on the same real-data gap above |
| ESLint warnings | Re-measured this round (see axis 1) — 45, unchanged from round 3 |

### DTE soft-preference floor — investigated, confirmed intentional, not a bug

The round-4 first pass flagged `contract_rules.yaml`'s `soft_rank.preferred_dte_min` (21) exactly matching `hard_reject.min_dte` (21) as a "dead code branch." Tracing the actual live scan path (`backend/app/scoring/dte_window.py`'s `widen_contract_overrides_for_dte()`) shows this equality is deliberate: every horizon-derived DTE override sets `preferred_dte_min` and `min_dte` to the *same* widened value on purpose (see that function's docstring — it exists specifically so a contract the hard-reject check already forgives for landing near the window edge isn't then penalized by the soft-rank score as if it were far outside it). The static default in `contract_rules.yaml` mirrors that same intentional design for the no-override case. Spacing the two values apart, as the round-4 first pass suggested, would have reintroduced the double-penalty behavior `dte_window.py` was written to eliminate. Closed as "working as designed" — documented in place (config comment + code comment + a regression test asserting the equality is intentional) rather than changed, so a future edit that drifts them apart is a deliberate, reviewed choice.

### New this round

None of the three Medium/Low bug findings originally flagged "new this round" (`breakout_base` calibration, cost-modeling gap, `SCORING_RULES.md` drift) turned out to be genuinely new — all three were already-fixed findings this branch simply hadn't received yet (see "Root cause discovered" above). The sixth item from the original "new this round" table, the `backtesting.py` engine-swap discovery (severity N/A, re-verified sound, not a bug), stands on its own regardless of which branch has which fixes — it's still genuinely new information versus round 3's audit. See axis 2's "Mechanism correctness" section, which documents it in full.

---

## Axis 1 — Code quality — **PASS**

Clean-room methodology followed per the skill: fresh `npm install`, full `npm run build` (not skipped), backend run via `backend/.venv/Scripts/python.exe` (not bare `pytest`). This round's fixes (Tasks 3-4) were verified on the `worktree-fix-strategy-scoring-findings` branch first, then re-verified once more here after that branch was merged into `chore/consolidate-backend-venv` — the counts below are from that final, post-merge run on `chore/consolidate-backend-venv` itself, which is why they're higher than the pre-merge worktree numbers (`chore/consolidate-backend-venv` already carried its own additional tests from its own unrelated prior commits, e.g. `test_fundamentals_scorer.py`, `test_intraday_omm_fallback.py`, `ScreenerStepGate`'s test suite).

| Check | Result |
|---|---|
| `npm install` (frontend) | Clean — `up to date, audited 690 packages`, 0 vulnerabilities added |
| `npm run typecheck` | **PASS** — exit 0, 0 errors |
| `npm run test -- --ci` | **PASS** — 77 suites, 611 tests, 0 failures |
| `npm run build` | **PASS** — exit 0, 0 errors, 45 non-blocking ESLint warnings (fixed one real blocking error along the way — a leftover `require()` in `RunScanButton.test.tsx` was tripping `@typescript-eslint/no-require-imports` as a hard build failure, unrelated to this round's findings but blocking this verification gate; removed) |
| `npm audit` | 1 high (`xlsx` — Prototype Pollution + ReDoS, no fix available upstream; documented as low-risk write-only usage) |
| Backend `.venv` sanity | Python 3.12.13, `fastapi`/`hmmlearn` import cleanly — matches CLAUDE.md's post-migration `.venv` documentation |
| `pytest -q` (backend, full, via `.venv`) | **PASS** — 1526 passed, 3 skipped, 0 failures |
| Working tree after all checks | Clean — confirmed via `git status` |

CI workflow (`.github/workflows/ci.yml`) re-checked: backend job installs `backend/requirements.txt` and runs bare `pytest` on Python 3.11 (not 3.12, and not scoped to the `.venv`) — frontend job runs `npm ci` → `typecheck` → `test -- --ci` → `build`, matching what was verified above. This is the actual gate; not re-audited beyond confirming the commands match.

### Open findings (Low only)
| Severity | Finding | Status |
|---|---|---|
| Low | `xlsx` high-severity npm audit finding, no upstream fix | Unchanged |
| Low | 45 non-blocking ESLint warnings (`no-unused-vars`, `react-hooks/exhaustive-deps`, a couple of stale `eslint-disable` directives) | Unchanged from round 3's count; still polish-only |

No Medium+ findings open in this axis.

---

## Axis 2 — Trading-logic (algorithmic) soundness — **CAUTION**

### Mechanism correctness (re-verified from scratch — engine has changed since round 3)

`strategy_backtest.py`'s `run_strategy_backtest()` no longer uses the hand-rolled simulator round 3 evaluated — it now runs on the third-party `backtesting.py` library. This was independently re-verified for lookahead safety by reading the **installed library source**, not just its docs:

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | `backtesting.py`'s internal loop sets `data._set_length(i+1)` before calling `strategy.next()` (bars 0..i visible only); any order queued in `next()` fills at the **next** iteration's `broker.next()`, never retroactively on the current bar | `backend/.venv/Lib/site-packages/backtesting/backtesting.py:1327,1334,1339` |
| Signal function window | `_Strategy.next()` builds `slice_bars` from `range(start, n)` where `n = len(self.data.Close)` — exactly bars 0..current | `strategy_backtest.py:97-120` |
| Order fill realism | `commission` parameter defaults to `0.0` (`strategy_backtest.py:66`), passed through to `Backtest(...)` at the call site; `trade_on_close` defaults `False` (next-bar fill); limit/SL/TP fills use next-bar High/Low/Open | `strategy_backtest.py:66,124`; library `:915,883-938` |
| Cost modeling | Live/UI backtest path (`stock_scan.py` → Step-6) and the WFO tuner path now share the same cost model — `run_strategy_backtest()` accepts a `commission` parameter, applied and cache-keyed correctly | `strategy_backtest.py:66,123`; `strategy_param_optimizer.py:109-114` — **fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`d4d837c`, `a0cc6a3`), re-verified present |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0` | `strategy_backtest.py:24-26` |
| Walk-forward fold validity | Genuinely non-overlapping — rolling folds slide `train_start` by `test_months`, `test_start == train_end` always; anchored keeps `train_start` fixed | `walk_forward.py:70-81`; `tests/test_walk_forward.py` still passing |
| Overfitting guard | Grid search ranks combos by pooled in-sample Sharpe minus `_complexity_penalty()` (up to 0.05/param at grid edges); OOS eligibility requires `n_trades>=20` and `consistency>=0.5`, both wired into the recommendation verdict, not decorative | `walk_forward.py:136-176,179-223`; `strategy_param_optimizer.py:17-70,212,225` |
| Confidence calibration | `compute_confidence()` truncates to `bars[:i+1]` for the signal, uses `bars[i+1:i+1+n_days]` only to score the outcome — no lookahead, but still a single in-sample replay pass, not WFO-validated | `signal_confidence.py:256,264` |

### Regression suite
```
cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_data_leakage.py tests/test_regime_no_lookahead.py \
  tests/test_walk_forward.py tests/test_signal_confidence.py tests/test_strategy_backtest.py
→ 65 passed, 16 warnings in 102s
```
Confirmed `test_strategy_backtest.py` exercises the **real, current** `backtesting.py`-based engine (11 of 13 tests call the real `Backtest` object; only 2 narrowly mock it for post-hoc expectancy-formula math, not fill logic) — not stale coverage left over from the old simulator.

### Real-data evidence (re-derived from scratch, not reused from round 3)

`run_strategy_backtest()` re-run against real fixture data (`backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 daily bars, 2024-04-30 to 2025-04-30), bullish direction, default `strategy_params.yaml` params, against the already-fixed `worktree-fix-strategy-scoring-findings` branch (`atr_tight_max=4.0`, not the 1.5 this table showed when originally measured against `chore/consolidate-backend-venv`). `mean_reversion_vwap` excluded (documented intraday-only).

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | 3 trades (33% WR, exp +0.82) | 1 trade (0% WR, exp -3.37) | 2 trades (0% WR, exp -8.70) | 1 trade (0% WR, exp -4.29) |
| `breakout_base` | 0 | 0 | 0 | 1 trade (0% WR, exp -7.19) |
| `ma_crossover` | 5 trades (40% WR, exp -0.98) | 3 trades (0% WR, exp -2.72) | 4 trades (50% WR, exp +5.38) | 4 trades (25% WR, exp +0.39) |
| `mean_reversion_rsi` | 0 | 0 | 0 | 0 |
| `mean_reversion_bb` | 0 | 0 | 0 | 0 |

**Still 0 of 20 combinations reach `_MIN_TRADES=10`** — the calibration fix changed `breakout_base` from all-zero to firing once (on SPY), confirming the gate is no longer mathematically unfireable, but a single trade over a ~1-year window is nowhere near the 10-trade significance bar either way. `pullback_ema`/`ma_crossover`'s trade counts are unchanged from the pre-fix measurement (expected — the cost-modeling fix only added a `commission` *parameter*, still defaulting to `0.0`, so P&L math is unaffected at this layer). Best case remains `ma_crossover`/AAPL at 5 trades. `mean_reversion_rsi`/`bb` still need ≥219-225 bars warmup against 251 total (unchanged, expected, unaffected by this round's fixes).

### `breakout_base` investigation — **confirmed genuine bug, already fixed**

Round 3 flagged this as "worth a second look, unexplained by warmup." This round traced all three entry conditions bar-by-bar across all 226 evaluable bars per symbol:

| Symbol | `tight_base_ok` passes | min observed range/ATR ratio |
|---|---|---|
| AAPL | 0/226 | 3.22 |
| MSFT | 0/226 | 2.92 |
| NVDA | 0/226 | 3.02 |
| SPY | 0/226 | 2.77 |

`breakout_base_signal`'s `atr_tight_max` gate (`strategy_engine.py:344` default, `:372` conditional, was **1.5**) never once passed on any symbol over a full year — the observed minimum ratio (2.77) was nearly double the old ceiling. Even the WFO search grid for this parameter (`strategy_params.yaml`, `[1.0, 1.5, 2.0]`) topped out below the observed minimum, so no value the optimizer was even allowed to try could produce a signal on this data. Root cause: a 20-bar range (`base_lookback=20`) compared against a 1-bar ATR(14) with only a 1.5× multiplier — for a random walk, a 20-bar range scales roughly with `sqrt(20)×ATR ≈ 4.5×ATR`, so 1.5× was arithmetically near-impossible for this lookback length. Confirmed by contrast with the sibling `breakout_setup_signal` (used by the Step-4 pre-breakout scanner), which pairs a shorter 10-bar lookback with `range_atr_mult=3.0` — much closer to the `sqrt(10)≈3.16` sane heuristic.

**Status: fixed.** `worktree-fix-strategy-scoring-findings` already carries the fix (`26068d5`): `atr_tight_max` raised from 1.5 to 4.0, close to the `sqrt(20)≈4.47` heuristic. Brought into `chore/consolidate-backend-venv` by merging that branch directly (see "Since last run" above) and re-verified present (`strategy_engine.py:344` now reads `atr_tight_max: float = 4.0`). Re-measured against real data post-fix (see "Real-data evidence" above): the gate now fires occasionally (1 trade on SPY, still 0 on AAPL/MSFT/NVDA) — no longer mathematically impossible, though still far short of statistical significance on this ~1-year fixture set.

### Findings by severity

| Severity | Finding |
|---|---|
| Medium | Zero of 20 real-data strategy×symbol combinations reach `_MIN_TRADES=10` on the ~1-year fixture set (re-confirmed, rubric-designated CAUTION not REJECT; unchanged, blocked on real multi-year data) |
| Low | `signal_confidence.py` still a single in-sample pass, not WFO-validated |
| Low | `backtesting.py`'s own same-bar contingent SL/TP fill-order warning fires on this codebase's data — inherent daily-bar fidelity limit, not a defect introduced here |
| Low | `mean_reversion_rsi`/`bb` warmup vs. fixture length — expected, documented |
| Low | Complexity-penalty weight (0.05/param) untested against real historical optimizer runs |

Two Medium findings from the first pass of this round — `breakout_base_signal`'s tight-base gate and the live-vs-WFO cost-modeling gap — were already fixed on `worktree-fix-strategy-scoring-findings` (see "Since last run") and are removed from this table.

No REJECT-tier findings: lookahead safety, WFO fold non-overlap, and the overfitting guards were all independently re-verified against current source (including the newly-discovered `backtesting.py` engine swap) and remain sound.

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **PASS**

Best-effort stand-in for the user's own local settings-audit skill, not a substitute for it.

### Resolved this round: `iv_rank_*: null` for intraday

**Deliberate, correctly implemented — not an accidental gap.** `scoring_rules.yaml:188-190` sets `horizons.intraday.vol.{iv_rank_compressed_caution, iv_rank_pass_max, iv_rank_caution_max}` to `null`; `stock_scorer.py:880-884` explicitly checks for `None` and returns a fixed PASS with an inline comment explaining why (intraday holding periods are too short for IV-rank/vega-crush to be the dominant risk). Contrast with `swing` (34) and `position` (44), both real non-null thresholds — confirms intraday is the deliberate outlier. Closed.

### Findings table

| File:Line | Value | Judgment |
|---|---|---|
| `risk_rules.yaml:35` | `max_daily_loss_pct: 0.02` | Real circuit breaker, enforced in `auto_trader.py:348-370`, wired into the `/fire` path |
| `risk_rules.yaml:4,10` | `max_total_exposure_pct: 0.25`, `max_single_position_pct: 0.05` | Both enforced in `portfolio_risk.py:88-106`; aggregate cap binds correctly before 5 positions could exceed it |
| `scoring_rules.yaml:10-11` | `pass: 55, caution: 35` | Real 20-point middle band, live-enforced |
| `scoring_rules.yaml` event windows | Swing 21/45d, intraday 1/3d, position 30/60d | Genuinely horizon-differentiated, matches CLAUDE.md's current description |
| `contract_rules.yaml:23` vs `:38` | `hard_reject.min_dte: 21` == `soft_rank.preferred_dte_min: 21` | **Closed, not a bug** — deliberate: `dte_window.py`'s `widen_contract_overrides_for_dte()` always sets both to the same widened value on purpose, to avoid double-penalizing a contract the hard-reject check already forgave near the window edge. Documented in place (config + code comments, plus a regression test) rather than changed. |
| `contract_rules.yaml:27` | `hard_reject.min_stock_score: 55` (was 50) | **Fixed this round** — raised to match the stock `pass` bar exactly; options are no longer recommended on CAUTION-grade (35-54) underlyings |
| `strategy_params.yaml:19-20` | `optimization.min_trades: 20, min_consistency: 0.5` | Matches code defaults exactly (`strategy_param_optimizer.py:212-213`, `strategy_param_store.py:87`) — genuinely wired through, not a stale mirror |
| `strategy_params.yaml:1-4` | `windows: rolling, train_months: 12, test_months: 3` | Matches `strategy_param_store.get_windows()` fallback; `walk_forward.py` confirmed to use these as real parameters |
| `strategy_params.yaml` stop/target multiples | e.g. `pullback_ema` 1.5×ATR stop / 2.0 R:R; `breakout_base` uses a structure-based stop, not a blind multiple | Round, standard values, no curve-fit smell |
| `SCORING_RULES.md` vs `scoring_rules.yaml` | Was: doc pass/caution 70/50, RSI floors 44/44/48, swing event reject/caution 7d/21d, position swing-high lookback 15 bars. Actual (unchanged, was always correct): 55/35, 40/38/37, 21d/45d, 75 bars. | **Fixed** — already committed on `worktree-fix-strategy-scoring-findings` (`edbe380`, `19fc720`); doc now matches the live YAML on every figure |

### Why PASS now

Every genuine risk-control value (daily-loss circuit breaker, exposure caps, contract hard-reject filters) is present, sane, and actually enforced in code. The one Medium finding (`SCORING_RULES.md` drift) is already fixed on `worktree-fix-strategy-scoring-findings`; the two Low findings are closed (DTE: confirmed intentional, documented) or fixed (`min_stock_score` raised to 55). No Medium+ findings remain open in this axis.

---

## Prioritized punch list

| Priority | Item | Why | Axis |
|---|---|---|---|
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Still zero evidence any strategy clears its own significance bar — biggest gap between "code looks right" and "this makes money" | 2 |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | | 2 |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | | 2 |
| Low | Address the outstanding ESLint warnings | Non-blocking polish | 1 |
| Low | Clear the remaining `xlsx` npm audit finding if/when an upstream fix ships | No fix currently exists | 1 |

Resolved this round (removed from the list above — see "Since last run"): `breakout_base_signal` calibration, live-vs-WFO cost-modeling gap, `SCORING_RULES.md` drift (all three already fixed on `worktree-fix-strategy-scoring-findings`), `contract_rules.yaml`'s DTE two-tier (closed — confirmed intentional, not a bug), `min_stock_score` gate (raised 50 → 55).

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next step: sourcing real multi-year historical data for a genuine axis-2 performance evaluation — every other Medium finding from this round is now resolved.
