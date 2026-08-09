# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-09 (round 4)
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | PASS — all gating checks green, no open Medium+ findings |
| 2. Trading-logic (algorithmic) soundness | CAUTION — found and fixed a real bug that was silently corrupting the WFO optimizer's own evidence pipeline; real-data significance gap from round 3 persists |
| 3. Config / settings sanity ("as a trader", best-effort) | CAUTION — new: `breakout_base`'s default/grid `atr_tight_max` never fires on any of 4 real symbols across a full year |

---

## Since last run — round 4 changes

**Headline finding: `run_strategy_backtest()` was silently zeroing real trade data whenever a window fell under its `min_trades` gate — and two internal callers (`train_fold`'s grid search, the IS/OOS re-run in `strategy_param_optimizer.py`) depend on exactly that field to decide whether a window "traded at all."** This is more serious than anything found in rounds 1-3: it doesn't just misreport a number, it silently defeats the walk-forward optimizer's in-sample parameter search under realistic (low) trade-frequency conditions — which, per this round's own real-data re-verification, is the *common* case, not an edge case.

| Item | Was | Now | Evidence |
|---|---|---|---|
| `run_strategy_backtest()` collapsed real `n_trades`/`win_rate`/`sharpe`/`expectancy` to `0` whenever the count fell below `min_trades`, keeping the real number only in free-text `summary_text` | Broken | **Fixed** | `strategy_backtest.py:128-158`. Reproduced empirically: `train_fold("pullback_ema", "Bullish", <4 real symbols>, <full-year fold>, <96-combo grid>, costs)` returned `{}` (no winner) before the fix — every combo/symbol pairing produced fewer than the module's default `_MIN_TRADES=10`, so every one came back as `n_trades=0`, making `if res.n_trades > 0` (the check `train_fold` and the optimizer's IS/OOS re-run both use to decide "did this window trade") false across the board. Confirmed real trades existed all along: `run_strategy_backtest(..., min_trades=1)` on the identical bars returned real, non-zero `n_trades`/`sharpe` (e.g. AAPL: 3 trades, sharpe 0.146). After the fix, the same `train_fold` call returns a real winning param combo. Also fixes a secondary, user-visible symptom: Step 6's backtest table (`step-6-backtest/page.tsx:21` vs `:25`) rendered two different trade counts in the same row — the text column read the real number from `summary_text` ("Only 3 trades — need 5") while the adjacent data column read the zeroed `n_trades` field ("0") — now consistent. |
| No regression coverage existed for this exact failure mode | Missing | **Added** | `backend/tests/test_strategy_backtest.py::test_below_gate_result_preserves_real_trade_stats` (direct unit test: a below-gate result must keep real `n_trades`/`sharpe`, only null out `confidence` and flip `passes_gate`) and `backend/tests/test_walk_forward.py::test_train_fold_finds_a_winner_on_real_sub_gate_trade_counts` (integration regression using the real 4-symbol fixture basket — proves `train_fold` no longer degenerates to `{}` on realistic trade counts). |
| `breakout_base`'s real-data zero-trade result (flagged Low in round 3 as "worth a second look, not yet explained") | Unexplained | **Root-caused** | Directly measured the 20-day base range vs. `atr_tight_max × ATR` across all 226 checked bars for all 4 real fixture symbols (AAPL/MSFT/NVDA/SPY, 2024-04-30 → 2025-04-30): the tightness gate (`range ≤ 1.5 × ATR`) was **never once satisfied** — the closest any symbol ever got was a ratio of 2.77 (SPY), nearly double the 1.5 threshold; single names never got closer than 2.9-3.2. This isn't a data-insufficiency artifact like the mean-reversion strategies' warmup issue — it's the default `atr_tight_max: 1.5` (`strategy_params.yaml:52,57`) being tighter than any observed real 20-day consolidation, and even the grid search's *loosest* candidate value (`2.0`, `strategy_params.yaml:62`) would still never fire on this evidence. See axis 3. |

**Not fixed this round, deliberately**: the `atr_tight_max` calibration issue above is reported, not hand-tuned — changing a strategy's default/grid parameters based on a 4-symbol, 1-year audit fixture is exactly the kind of unvalidated, non-WFO-checked change this codebase's own architecture (and this skill's methodology) exists to prevent. It belongs in the punch list for a proper WFO-driven recalibration across a real basket, not a one-off edit.

---

## Does a GitHub skill already exist to benchmark this kind of app?

Unchanged from round 3 — see `PRODUCTION_READINESS_AUDIT.md` (BMAD-style axis-1 audit) and `.claude/skills/K-quality-benchmark/SKILL.md` for the reusable rubric. Axes 2-3 remain first-party since no generic tool grades lookahead safety, WFO validity, or YAML risk-parameter survivability.

---

## Axis 1 — Code quality — **PASS**

### Fresh clean-room verification (this run)

| Check | Result |
|---|---|
| `npm install` (frontend, no committed lockfile — reinstalled from scratch) | 689 packages, 0 errors |
| `npm run typecheck` | **PASS** — exit 0 |
| `npm run test -- --ci` | **PASS** — 62 suites, 494 tests, 0 failures |
| `npm run build` | **PASS** — exit 0, 44 non-blocking ESLint warnings (was 45 in round 3) |
| `npm audit` | 4 high, 0 critical (unchanged from round 3 — Next.js/postcss/sharp/xlsx transitive CVEs) |
| `pip install -r requirements.txt` (backend) | Clean install, 0 errors |
| `pytest --collect-only` | 1387 tests collected, 0 import errors (settings.yaml genuinely absent — fallback to `settings.example.yaml` confirmed still working) |
| `python3 -m pytest -q` (backend, full) | **PASS** — 1387 passed, 1 skipped, 1 xpassed (was 1385/1/1 in round 3; +2 = the two new regression tests added this round) |
| Quant-soundness regression suite | **PASS** — 57/57 (was 56/56; +1 new test) |
| `.github/workflows/ci.yml` / `playwright.yml` | Re-read both — commands match what's actually run in CI; no drift since round 3's fix (`npm install` not `npm ci`, matching the gitignored-lockfile situation) |

### Prior audits — all still fixed

Rounds 1-3's fixes (Playwright dependency masking, `scan.py` settings fallback, ScanLog rules-of-hooks bug, `playwright.yml` npm-ci gap, and the original 2026-05-05 BMAD findings) remain fixed — re-verified via the fresh clean-room checks above, not re-derived from the prior report.

### Open findings (Low only, unchanged from round 3)

| Severity | Finding | Evidence |
|---|---|---|
| Low | No committed frontend lockfile | `.gitignore:21` |
| Low | 4 high-severity `npm audit` findings | `npm audit` output |
| Low | 44 non-blocking ESLint warnings (`react-hooks/exhaustive-deps`, unused vars) | `npm run build` output |
| Low | Stray root-level `package.json` (unrelated placeholder scaffolding, still un-cleaned) | `package.json` (root) |

---

## Axis 2 — Trading-logic (algorithmic) soundness — **CAUTION**

### Mechanism correctness (re-verified against current source, not assumed from round 3)

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | `next()` still only ever builds `slice_bars` from `range(start, n)` where `n = len(self.data.Close)` at the current simulated bar — no future bars visible. A 350-bar trailing cap was added as a perf optimization at some point before this round; harmless here since it never triggers below 350 total bars, and doesn't change lookahead behavior either way | `strategy_backtest.py:96-119` |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0` (module defaults) — but see the axis-2 headline finding above: two internal callers reuse this default in a context where it was never meant to filter data, not just gate a verdict | `strategy_backtest.py:23-25` |
| Walk-forward validity | `build_folds()` still produces genuinely non-overlapping in-sample/out-of-sample windows (`test_start = train_end`, confirmed by direct read) | `walk_forward.py:31-83` |
| Overfitting guard | OOS eligibility still requires `n_trades>=min_trades` (config-driven, `20` in `strategy_params.yaml`) and `consistency>=0.5`; grid-edge complexity penalty still present and unit-tested | `strategy_param_optimizer.py:47`; `walk_forward.py:_complexity_penalty()` |
| Confidence calibration | `signal_confidence.py` still empirically measures `payoff_ratio` via `_measure_excursion()`, not a static weight | `signal_confidence.py:92-156` |
| Dedicated regression coverage | 57/57 green, +1 new test this round | `backend/tests/test_*.py` |

### Real-data evidence (re-run this round with the fix applied)

Ran `run_strategy_backtest()` against the same real fixture data as round 3 (`AAPL`/`MSFT`/`NVDA`/`SPY`, 251 real daily bars each, 2024-04-30 → 2025-04-30), bullish direction, default `strategy_params.yaml` params, gate bypassed (`min_trades=1`) to read the true underlying trade count rather than a gate-collapsed one.

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | 3 trades | 1 trade | 2 trades | 1 trade |
| `breakout_base` | 0 trades | 0 trades | 0 trades | 0 trades |
| `ma_crossover` | 5 trades | 3 trades | 4 trades | 4 trades |
| `mean_reversion_rsi` | 0 trades | 0 trades | 0 trades | 0 trades |
| `mean_reversion_bb` | 0 trades | 0 trades | 0 trades | 0 trades |

**Identical raw numbers to round 3** — confirms the underlying strategy-engine mechanics are stable and reproducible; nothing regressed. Zero of these 20 strategy×symbol combinations reach the WFO optimizer's own `min_trades=20` eligibility bar (or even the module's `_MIN_TRADES=10`), same conclusion as round 3: **this environment's ~1-year/4-symbol fixture set cannot yet give a real trader-quality opinion on whether any of these 5 strategies has edge.**

**What's different this round**: previously, this data limitation was compounded by the min_trades-zeroing bug making it impossible to tell whether the WFO *mechanism* even worked correctly under these conditions — `train_fold` returning `{}` looked, from the outside, exactly like "the mechanism correctly found no edge," when it actually meant "the mechanism never got to look." Ran the full `_optimize_strategy_sync()` pipeline post-fix on real data (`pullback_ema`, single fold, real train/test split): `train_fold` now returns a genuine winning combo (`{ema_period: 50, trend_ema: 100, atr_stop_mult: 1.0, rr_target_mult: 2.0, tolerance: 0.04}`) instead of `{}`, and the final eligibility check still correctly reports `eligible: false` / `recommendation: "Edge looks fake — consider dropping"` for this specific thin fixture — the honest verdict now comes from the OOS window genuinely being too short (real trade count 0 in a 3-month test slice), not from the earlier bug silently discarding real IS trade data before the pipeline could even reach that verdict.

### Remaining caveats

| Severity | Finding |
|---|---|
| Medium | No real-data evidence exists yet that any strategy reaches minimum trade-count significance (unchanged from round 3 — needs real multi-year, multi-symbol history) |
| Low | `signal_confidence.py` confidence replay is still a single in-sample pass, not walk-forward validated |
| Low | Complexity-penalty weight (`0.05`/param) is a fixed constant, untested against real historical optimizer runs |
| Low | `breakout_base` producing 0/4 trades — now root-caused (see axis 3), not an open question anymore |

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **CAUTION**

| File | Judgment |
|---|---|
| `risk_rules.yaml` | Unchanged from round 3 — conservative, survivable numbers: 5% max single-trade exposure, 25% max aggregate, a real 2%-of-portfolio daily-loss circuit breaker. No code changes since round 3 (`git log --since=2026-08-08` on this file: empty). |
| `contract_rules.yaml` | Unchanged — two-tier hard-reject vs soft-preference design; sensible IV-rank volatility-crush guard. |
| `scoring_rules.yaml` | Unchanged — `pass:55/caution:35` leaves a real middle band; gates differentiated by horizon. |
| `strategy_params.yaml` | **New finding this round**: `breakout_base.active.{bullish,bearish}.atr_tight_max: 1.5` (and its search grid, capped at `2.0`) requires a 20-day price range to sit within 1.5-2.0× a single bar's 14-day ATR to count as a "tight base." Measured directly against all 4 real fixture symbols across a full year (226 checked bars each): this condition was **never satisfied once**, anywhere — the closest observed ratio was 2.77 (SPY), meaning even the grid search's loosest candidate value would still never fire. A trader relying on `breakout_base`'s default or WFO-tuned params would see this strategy simply never generate a setup on typical large/mega-cap volatility, silently, with no error or warning surfaced anywhere in the product. This reads as a genuine calibration miss (comparing a 20-bar range to too small a multiple of single-bar ATR) rather than an intentionally strict filter — real "volatility contraction pattern" trading conventions typically use looser multiples for a lookback this long. Not hand-fixed this round (see "Since last run" — needs proper WFO-driven recalibration, not a one-off edit from a 4-symbol/1-year audit). |

Still labeled best-effort — defers to the user's own local settings-audit skill once it's committed to this repo.

---

## Prioritized punch list

| Priority | Item | Why |
|---|---|---|
| **Medium** | Recalibrate `breakout_base.atr_tight_max` (and its search grid) via a proper WFO run across a real, larger symbol basket | Confirmed via direct measurement: never fires on any of 4 real symbols across a full year, even at the grid's loosest value — the strategy is currently dead on arrival for realistic single-name volatility |
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Still zero evidence any strategy clears its own significance bar — now that the WFO pipeline itself is confirmed working correctly (this round's fix), this is a pure data-availability gap, not a mechanism question |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | |
| Low | Confirm `intraday.vol.iv_rank_*: null` is deliberately "gate disabled" (not yet checked this round) | |
| Low | Add a frontend lockfile or document why it's excluded | |
| Low | Clear 4 high-severity `npm audit` findings | |
| Low | Clean up or document the stray root-level `package.json` | |
| Low | Address the 44 remaining ESLint warnings | Non-blocking polish |

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next steps: (1) a real WFO recalibration pass on `breakout_base`'s tightness threshold, and (2) sourcing real multi-year historical data for a genuine axis-2 performance evaluation — both of which are now meaningful to pursue since this round confirmed the underlying WFO/backtest mechanism itself is sound.
