# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-08 (round 3 — clean-room fixes + real-data trader evidence)
**Method**: `.claude/skills/K-quality-benchmark`
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **CAUTION**

| Axis | Grade |
|---|---|
| 1. Code quality | PASS — genuinely clean this time (see "Since last run") |
| 2. Trading-logic (algorithmic) soundness | CAUTION — mechanism is sound, but real-data evidence shows this environment can't yet validate any strategy's actual edge |
| 3. Config / settings sanity ("as a trader", best-effort) | PASS — no Medium+ findings |

Per this skill's own rubric, insufficient real data to validate strategy performance is a CAUTION-level finding (a real gap), not a REJECT (the backtest/WFO *mechanism* isn't shown broken — see axis 2).

---

## Since last run — round 3 changes

**Round 2's axis-1 "PASS" was wrong**, caught by a second, independent skill run (a different session) plus a foreground adversarial-audit subagent this round (the first attempt at this audit, run in the background, died silently with no notification after ~2h40m — not the first time; background subagents have been unreliable for this kind of long verification work in this environment, so this round's audits ran synchronously instead):

| Item | Was | Now | Evidence |
|---|---|---|---|
| `@playwright/test` genuinely missing from `frontend/package.json` | Believed fixed, actually masked | **Fixed** | A stray, unrelated root-level `package.json` (placeholder scaffolding, unconnected to the real app) had it installed, and Node's module resolution walked up to find it — passing typecheck locally while CI (scoped strictly to `frontend/`) would still fail. Removed the stray root entry + root `node_modules`; added `@playwright/test: ^1.62.1` directly to `frontend/package.json`. Re-verified `npx tsc --noEmit` passes with the root masking gone. |
| `backend/app/routers/scan.py` crashes on a clean checkout | Broken | **Fixed** | Module-level `settings.yaml` read had no fallback; gitignored file, so any fresh clone failed to import the router, breaking collection of 22+ test modules. Now falls back to the committed `settings.example.yaml` when the local override is absent. Verified: `pytest --collect-only` succeeds with `settings.yaml` genuinely deleted (1383 tests collected, 0 errors). |
| `npm run build` never actually run in prior checks | Untested — 47 real errors hiding | **Fixed** | Real bug: `components/organisms/ScanLog/index.tsx` called `useState` after an early `return null` (genuine React rules-of-hooks violation — moved the hook above the return). Remaining 44 of 47 errors were `@typescript-eslint/no-explicit-any` inside test-mock code; added a scoped ESLint override for `__tests__/`/`*.test.{ts,tsx}` files only (production code still fully typed). Fixed the 3 real production-code `any`s properly: `IndicatorPanel`'s chart-data/series types, and `TradeCardData`'s `_userOverride` field (widened `mergePlan`'s return type instead of casting at the call site). Fixed one `require()`-style import in a test file. `npm run build` now exits 0. |

**Round-1 adversarial audit of the fix plan** (foreground/synchronous, before any code was touched) caught 2 blockers and 4 majors — corrected before implementing: the Playwright "reproducibility" claim was subtler than first stated (see above); the planned isolated-clone verification method would have tested stale pre-fix code (a plain `git clone` only sees committed history — now: commit fixes locally first, then clone); `mean_reversion_rsi`/`mean_reversion_bb` need ≥219–225 bars of warmup against only ~251 fixture bars (addressed below); `mean_reversion_vwap` is documented intraday-only and invalid on daily bars (excluded from the real-backtest run); the "48 ESLint errors" figure hadn't actually been measured yet (measured: 47, matches once the ScanLog fix is accounted for); and the plan's branch-reuse was ambiguous (resolved: worked directly on `main`, matching the established no-PR pattern).

**Round-2 adversarial audit of the actual code diff** (foreground/synchronous, after the fixes were committed locally, before pushing) independently re-verified every claim above by re-running the checks from scratch and re-deriving all 20 real-backtest cells — found the IndicatorPanel/mergePlan/scan.py/ESLint-override fixes all genuinely sound, but caught 2 more real issues:
- **`playwright.yml` used `npm ci` against a gitignored, uncommitted lockfile** — a hard CI failure on every clean checkout, unrelated to but adjacent to this round's Playwright fix, and never checked until this audit. Fixed above.
- **This round's own commit message overstated its test coverage** ("12 new/updated test files" — a stale figure copied from the prior round's commit, which actually had 12 *tests* across 2 *files*). This round genuinely touched only 1 test file directly, with no new regression coverage for `scan.py`'s settings fallback or the ScanLog hooks fix. Added both: `backend/tests/test_scan_settings_fallback.py` (4 tests covering the fallback logic directly) and `frontend/components/organisms/ScanLog/__tests__/ScanLog.hooksOrder.test.tsx` (4 tests, including a mount→re-render transition between zero and non-zero contract rejections — the exact scenario that would throw "Rendered fewer hooks than expected" if the bug recurred).
- Also caught a **minor factual slip**: this report previously said "1380 passed" for the backend suite; actual count was 1381 at that point (now 1385 after the new tests above) — corrected.

**New this round — real trader-quality evidence for axis 2** (see below): ran the actual `run_strategy_backtest()` against real historical data instead of only synthetic mechanics checks, per the user's direct feedback that axis 2 had never delivered an actual "experienced trader's opinion."

---

## Does a GitHub skill already exist to benchmark this kind of app?

Yes — and it was already run on this exact repo once before.

`PRODUCTION_READINESS_AUDIT.md` (repo root, dated 2026-05-05) was produced by a different AI tool ("opencode") running the **`bmad-review-adversarial-general`** skill from **[bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)** (skill source: `src/core-skills/bmad-review-adversarial-general/SKILL.md`), a real, public, actively-maintained Claude/Codex skill for adversarial code review against a spec. This repo's own planning docs (`docs/superpowers/plans/*.md`) also repeatedly invoke a "K-adversarial-audit-loop" using that same skill, alongside the **[obra/superpowers](https://github.com/obra/superpowers)** plugin for review-driven implementation. Neither BMAD-METHOD nor Superpowers is actually installed/committed in this repo — every "adversarial audit" mentioned in this report is a foreground subagent instructed to adopt that posture, not the real plugin.

What it does **not** cover: whether the screener's trading edge is real. BMAD-style review checks code correctness and spec compliance — it has no concept of lookahead bias, walk-forward validity, or whether a YAML risk parameter is survivable. That's domain-specific to Bamendjou, which is why axes 2 and 3 below are first-party rather than borrowed from an external tool. See `.claude/skills/K-quality-benchmark/SKILL.md` for the reusable rubric this report was generated from.

---

## Axis 1 — Code quality — **PASS**

### Fresh verification (this run, genuinely clean-room this time)

| Check | Result |
|---|---|
| `npm run typecheck` (frontend) | **PASS** — exit 0, with the stray root-level masking removed (proven self-contained) |
| `npm run test -- --ci` (frontend, Jest) | **PASS** — 62 suites, 494 tests, 0 failures |
| `npm run build` (frontend) | **PASS** — exit 0, 0 errors (was 47 errors, all fixed or scoped out as test-mock typing), 45 non-blocking warnings remain (pre-existing `exhaustive-deps`/unused-vars, not gating) |
| `pytest --collect-only` with `settings.yaml` genuinely absent | **PASS** — 1383 tests collected, 0 import errors |
| `pytest` (backend, full) | **PASS** — 1385 passed, 1 skipped, 1 xpassed, 0 failures |
| Quant-soundness regression suite | **PASS** — 56/56 |
| `.github/workflows/playwright.yml` | **Fixed this round (round-2 audit finding)** — at the time, used `npm ci`, which requires a committed lockfile; `frontend/package-lock.json` was gitignored, so this workflow hard-failed on every clean checkout regardless of the dependency fix above. Changed to `npm install` as a stopgap. **[Update, later session]**: a lockfile is now committed (see Open findings below) and this workflow has since been switched back to `npm ci` with `cache: 'npm'` / `cache-dependency-path: frontend/package-lock.json` — this row describes the state at the time of this round's audit, not the current file. |

### Prior audit (2026-05-05, BMAD) — all 6 findings still fixed

| # | Item | Status |
|---|---|---|
| 1 | Hardcoded `SEED_SYMBOLS` watchlist | **Fixed** |
| 2 | Watchlist empty state | **Fixed** |
| 3 | Portfolio empty state | **Fixed** |
| 4 | Settings Save button unwired | **Fixed** |
| 5 | FR-07 CSV upload missing | **Fixed** |
| 6 | FR-12 ranked-table columns missing | **Fixed** |

### Open findings (Low only)

| Severity | Finding | Evidence | Status |
|---|---|---|---|
| Low | No committed frontend lockfile — `package-lock.json` is gitignored, so installs aren't pin-reproducible | `.gitignore:21` | **Fixed, later session** — `frontend/package-lock.json` is now committed (`.gitignore` scoped to root-only) |
| Low | 4 high-severity `npm audit` findings (Next.js, postcss, sharp, xlsx transitive CVEs) | `npm audit` output | **Reduced to 1, later session** — next/postcss/sharp fixed (next bumped + postcss/sharp version overrides); only `xlsx` remains, no upstream fix exists (documented as low-risk: write-only usage in this codebase) |
| Low | 45 non-blocking ESLint warnings remain (`react-hooks/exhaustive-deps`, unused vars) — not gating, but real polish debt | `npm run build` output | Still open |
| Low | The two-package.json situation (root scaffolding + `frontend/`) is itself worth a cleanup or a comment explaining why the root one exists at all, to stop future confusion | `package.json` (root) | **Fixed, later session** — the root `package.json` was deleted entirely (it only ever supported an orphaned, unwired root-level e2e suite, which was deleted alongside it) |

---

## Axis 2 — Trading-logic (algorithmic) soundness — **CAUTION**

### Mechanism correctness (unchanged from round 2, still holds)

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | Signal function only ever sees a truncated `bars[:n]` slice up to the current simulated bar; entries fill on subsequent bars, not same-bar | `strategy_backtest.py:96-119` |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0` | `strategy_backtest.py:23-25,146` |
| Walk-forward validity | Genuine non-overlapping in-sample/out-of-sample fold construction | `walk_forward.py:31-83` |
| Overfitting guard | OOS eligibility requires `n_trades>=20` and `consistency>=0.5`; grid search now also penalizes grid-edge params (round 2 fix) | `strategy_param_optimizer.py:47,50-55`; `walk_forward.py:_complexity_penalty()` |
| Confidence calibration | Derived from historical replay; `payoff_ratio` now empirically measured (round 2 fix) | `signal_confidence.py:_measure_excursion()`, `aggregate()` |
| Dedicated regression coverage | `test_data_leakage.py`, `test_regime_no_lookahead.py`, `test_walk_forward.py`, `test_strategy_backtest.py`, `test_signal_confidence.py` | `backend/tests/` |

**This is still just mechanism correctness** — it verifies the backtest/WFO infrastructure is implemented right using synthetic fake price data. It is not a trader's opinion on whether the strategies actually work.

### Real-data evidence (new this round)

Ran `run_strategy_backtest()` — the actual production backtest function, not a mock — against real historical fixture data (`backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`, 251 real daily bars each, 2024-04-30 to 2025-04-30), bullish direction, default `strategy_params.yaml` params. `mean_reversion_vwap` excluded (documented intraday-only in `strategy_engine.py`; produces a semantically meaningless number on daily bars).

| Strategy | AAPL | MSFT | NVDA | SPY |
|---|---|---|---|---|
| `pullback_ema` | 3 trades | 1 trade | 2 trades | 1 trade |
| `breakout_base` | 0 trades | 0 trades | 0 trades | 0 trades |
| `ma_crossover` | 5 trades | 3 trades | 4 trades | 4 trades |
| `mean_reversion_rsi` | 0 trades | 0 trades | 0 trades | 0 trades |
| `mean_reversion_bb` | 0 trades | 0 trades | 0 trades | 0 trades |

**Finding**: zero of these 20 strategy×symbol combinations reach the system's own `_MIN_TRADES=10` eligibility gate. Best case is `ma_crossover`/AAPL at 5 trades. `mean_reversion_rsi` and `mean_reversion_bb` predictably hit zero everywhere — they need ≥219–225 bars of warmup (`trend_sma=200` + period, per `strategy_params.yaml`) against only 251 total bars, leaving a 26–32 bar tail with essentially no room to trade. `breakout_base` also produced zero trades on all four symbols, which is not explained by warmup alone and is worth a closer look at whether its entry conditions are simply rare, or the fixture period (a relatively calm, grinding-up year across large-caps) just didn't offer qualifying setups.

**What this means, honestly**: this is not evidence the strategies are bad — every single result the gate itself flags as "not enough trades" is correctly treated as `_empty_result` (win_rate/Sharpe/expectancy all reported as 0.0 placeholders, not real computed statistics). It means **this environment's fixture data (~1 year, 4 symbols) is insufficient to give any real trader-quality opinion on these strategies at all.** A genuine assessment needs multi-year history across a broader symbol basket — matching what `run_optimization()`'s real WFO windows (12mo train / 3mo test, needing 15+ months minimum) already assume. That's the honest axis-2 answer to "what do you think of my code as an experienced trader": *the mechanism is well-built, but I have no real evidence yet that any of the 5 testable strategies clears its own bar for statistical significance — and the reason is data availability in this environment, not a flaw found in the strategies themselves.*

### Remaining caveats

| Severity | Finding |
|---|---|
| Medium | No real-data evidence exists yet that any strategy reaches minimum trade-count significance — see above |
| Low | `signal_confidence.py` confidence replay is still a single in-sample pass, not walk-forward validated |
| Low | Complexity-penalty weight (`0.05`/param) is a fixed constant, untested against real historical optimizer runs |
| Low | `breakout_base` producing 0/4 trades on real data deserves a second look independent of the warmup-data explanation that covers the two mean-reversion strategies |

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **PASS**

Unchanged from round 2 — no code in this axis's scope was touched this round.

| File | Judgment |
|---|---|
| `risk_rules.yaml` | Conservative, survivable numbers: 5% max single-trade exposure, 25% max aggregate, a real 2%-of-portfolio daily-loss circuit breaker. |
| `contract_rules.yaml` | Two-tier hard-reject vs soft-preference design; sensible IV-rank volatility-crush guard. |
| `scoring_rules.yaml` | `pass:55/caution:35` leaves a real middle band; gates differentiated by horizon, matching `SCORING_RULES.md`. |
| `strategy_params.yaml` | Stop/target multiples sane; WFO windows/optimization config matches what axis 2 found enforced in code. |

Still labeled best-effort — defers to the user's own local settings-audit skill once it's committed to this repo.

---

## Prioritized punch list

| Priority | Item | Why |
|---|---|---|
| **Medium** | Get real multi-year historical data (more symbols, more years) into this environment and re-run the axis-2 real-data backtest | Currently zero evidence any strategy clears its own significance bar — this is the single biggest gap between "code looks right" and "this makes money" |
| Low | Investigate why `breakout_base` produced 0/4 trades on real data — confirm it's data-period luck, not an entry-condition bug | Not explained by the warmup-data issue covering the mean-reversion strategies |
| Low | WFO-validate `signal_confidence.py`'s replay instead of single in-sample pass | |
| Low | Empirically tune the complexity-penalty weight against real historical optimizer runs | |
| Low | Confirm `intraday.vol.iv_rank_*: null` is deliberately "gate disabled" | |
| ~~Low~~ | ~~Add a frontend lockfile or document why it's excluded~~ | **Fixed, later session** |
| ~~Low~~ | ~~Clear 4 high-severity `npm audit` findings~~ | **Reduced to 1 (xlsx, no fix exists), later session** |
| ~~Low~~ | ~~Clean up or document the stray root-level `package.json`~~ | **Fixed, later session** — deleted, along with the orphaned e2e suite it existed to support |
| Low | Address the 45 remaining ESLint warnings | Non-blocking polish |

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above. Most impactful next step: sourcing real multi-year historical data for a genuine axis-2 performance evaluation.
