# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-08 (updated same day — fix pass after round-1 adversarial audit)
**Method**: `.claude/skills/K-quality-benchmark` (first run, then fixed to a clean state within the same run)
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **PASS**

| Axis | Grade |
|---|---|
| 1. Code quality | PASS — CI gap fixed |
| 2. Trading-logic (algorithmic) soundness | PASS — both Medium caveats fixed |
| 3. Config / settings sanity ("as a trader", best-effort) | PASS — no Medium+ findings |

The first pass of this run graded CAUTION (see "Since last run" below) per the rubric in `.claude/skills/K-quality-benchmark/SKILL.md`: 3 open Medium-severity findings. All three were fixed and re-verified in the same run — see per-axis sections for what changed and the evidence.

---

## Since last run (this run's own fix pass)

| Item | Was | Now | Evidence |
|---|---|---|---|
| CI never runs the Jest suite | Medium, open | **Fixed** | `.github/workflows/ci.yml` — added a "Run frontend tests" step (`npm run test -- --ci`) before the build step |
| Grid search has no complexity penalty (curve-fit risk) | Medium, open | **Fixed** | `backend/app/services/walk_forward.py` — new `_complexity_penalty()`, wired into `train_fold()`; penalizes numeric params near the grid edge, skips categorical/boolean grids (no ordinal "center") |
| `signal_confidence.py`'s `payoff_ratio` is assumed, not empirically calibrated | Medium, open | **Fixed** | `backend/app/scoring/signal_confidence.py` — new `_measure_excursion()` measures realized max-favorable/max-adverse price movement per historical fire; `aggregate()` now derives `payoff_ratio` from that when available, falling back to the old assumed ratio only when there's no win/loss data to measure from |

12 new regression tests added across `test_walk_forward.py` and `test_signal_confidence.py` covering both fixes (tie-breaking toward grid center, a genuine edge-value win still passing through, categorical grids being skipped, and the empirical-vs-fallback payoff-ratio branches). Full suite verified green after the fix (see Axis 1 below).

A round-1 self-review of the code changes (in the same adversarial spirit as the skill's own audit loop) caught one real issue before it shipped: the first version of the complexity penalty applied "distance from grid center" to *every* parameter, including categorical ones like `ma_type: ["EMA","SMA"]`, where there's no ordinal center to measure distance from. Fixed by reusing the numeric/categorical split `consensus()` already establishes in the same file. No production search grid currently uses categorical/boolean values (all are numeric per `strategy_params.yaml`), so this didn't change today's behavior — it prevents a latent bug if one is added later.

---

## Does a GitHub skill already exist to benchmark this kind of app?

Yes — and it was already run on this exact repo once before.

`PRODUCTION_READINESS_AUDIT.md` (repo root, dated 2026-05-05) was produced by a different AI tool ("opencode") running the **`bmad-review-adversarial-general`** skill from **[bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)** (skill source: `src/core-skills/bmad-review-adversarial-general/SKILL.md`), a real, public, actively-maintained Claude/Codex skill for adversarial code review against a spec. This repo's own planning docs (`docs/superpowers/plans/*.md`) also repeatedly invoke a "K-adversarial-audit-loop" using that same skill, alongside the **[obra/superpowers](https://github.com/obra/superpowers)** plugin for review-driven implementation.

What it does **not** cover: whether the screener's trading edge is real. BMAD-style review checks code correctness and spec compliance — it has no concept of lookahead bias, walk-forward validity, or whether a YAML risk parameter is survivable. That's domain-specific to Bamendjou, which is why axes 2 and 3 below are first-party rather than borrowed from an external tool. See `.claude/skills/K-quality-benchmark/SKILL.md` for the reusable rubric this report was generated from.

---

## Axis 1 — Code quality — **PASS**

### Fresh verification (this run, after the fix pass)

| Check | Result |
|---|---|
| `npm run typecheck` (frontend) | **PASS** — exit 0, clean |
| `npm run test -- --ci` (frontend, Jest) | **PASS** — 61 suites, 490 tests, 0 failures |
| `pytest` (backend) | **PASS** — 1380 passed, 1 skipped, 1 xpassed, 0 failures (1368 baseline + 12 new tests from this run's fixes) |
| Quant-soundness regression suite (`test_data_leakage`, `test_regime_no_lookahead`, `test_walk_forward`, `test_signal_confidence`, `test_strategy_backtest`) | **PASS** — 56/56 (44 baseline + 12 new) |
| CI enforcement (`.github/workflows/ci.yml`) | **Fixed this run** — frontend job now runs `npm run test -- --ci` before `npm run build`; the 490-test Jest suite has real CI coverage for the first time |

Getting a clean run required working around real setup friction, which is itself a finding (see punch list): no committed `package-lock.json`/lockfile-equivalent in `frontend/` (gitignored), a gitignored `backend/config/settings.yaml` that several routers read at import time with no `.example` auto-copy step, and a `pytest` binary on this machine that resolves to an isolated `uv`-tool interpreter blind to the project's installed deps (`python3 -m pytest` is required instead).

### Prior audit (2026-05-05, BMAD) — all 6 findings now fixed

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Hardcoded `SEED_SYMBOLS` watchlist | **Fixed** | `frontend/lib/watchlistStore.ts:13` — empty array |
| 2 | Watchlist empty state | **Fixed** | `frontend/app/(frame)/watchlist/page.tsx:278-280` |
| 3 | Portfolio empty state | **Fixed** | `frontend/app/(frame)/portfolio/page.tsx:276-277` |
| 4 | Settings Save button unwired | **Fixed** | `frontend/app/(frame)/settings/page.tsx:126-144` |
| 5 | FR-07 CSV upload missing | **Fixed** | `frontend/app/(frame)/screener/step-2-universe/page.tsx:521-549` |
| 6 | FR-12 ranked-table columns missing | **Fixed** | `frontend/app/(frame)/screener/step-4-ranking/page.tsx:36-37,239-274` |

Note: `settingsStore.ts` weights/theme are still localStorage-only (`persist()`); risk/schedule/credentials/history-retention are API-backed via `frontend/lib/api.ts` + matching backend routers. Not a defect, just a scope boundary.

### New findings this run

| Severity | Finding | Evidence |
|---|---|---|
| Low | No committed frontend lockfile — `package-lock.json` is gitignored, so installs aren't pin-reproducible | `.gitignore:21`, `frontend/.gitignore` |
| Low | 4 high-severity `npm audit` findings (Next.js, postcss, sharp, xlsx transitive CVEs) | `npm audit` output, this run |
| Low | Local dev setup has two silent failure points not documented in a setup script: missing `backend/config/settings.yaml` (routers read it at import time) and the isolated `pytest` binary shadowing the project's Python env | this run |

(The CI-Jest-gap Medium finding from earlier in this run is fixed — see "Since last run" above.)

---

## Axis 2 — Trading-logic (algorithmic) soundness — **PASS**

This is unusually rigorous for a retail-facing screener — genuine walk-forward validation and explicit overfitting guards, not just a backtest number slapped on a UI.

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | Signal function only ever sees a truncated `bars[:n]` slice up to the current simulated bar; entries fill on subsequent bars via `backtesting.py`, not same-bar | `backend/app/services/strategy_backtest.py:96-119` |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0`, enforced via `passes_gate` | `strategy_backtest.py:23-25,146` |
| Walk-forward validity | Genuine non-overlapping in-sample/out-of-sample fold construction (rolling or anchored), not a repeated re-run on the same data | `backend/app/services/walk_forward.py:31-83` |
| Overfitting guard | OOS eligibility requires `n_trades>=20` and `consistency>=0.5`; verdict text explicitly downgrades to "Edge looks fake — consider dropping" below threshold; param stability enforced via fold-consensus (median/mode), not single-best-fold selection | `backend/app/services/strategy_param_optimizer.py:47,50-55`; `walk_forward.py:164-187` |
| In-sample regularization (**fixed this run**) | `train_fold()`'s grid search now subtracts a distance-from-grid-center penalty from pooled Sharpe before selecting a winner — numeric params only (categorical/boolean grids have no ordinal "center" so are skipped); a genuinely better edge value still wins if its Sharpe advantage exceeds the penalty | `walk_forward.py:_complexity_penalty()`, wired into `train_fold()` |
| Confidence calibration (**fixed this run**) | `signal_confidence.py`'s confidence is derived from an actual historical replay (correctly bar-truncated). `payoff_ratio` is now measured from realized max-favorable/max-adverse price excursion per historical fire (`_measure_excursion()`), not assumed from config ATR multiples — falls back to the old assumed ratio only when there's no win or no loss data to measure from | `backend/app/scoring/signal_confidence.py:_measure_excursion()`, `aggregate()` |
| Dedicated regression coverage | `test_data_leakage.py`, `test_regime_no_lookahead.py` explicitly test for lookahead; `test_walk_forward.py`, `test_strategy_backtest.py`, `test_signal_confidence.py` cover fold math, gate correctness, and confidence aggregation — now including the two fixes above | `backend/tests/` |

### Remaining caveats (not blockers, worth tracking)

| Severity | Finding | Evidence |
|---|---|---|
| Low | `signal_confidence.py` confidence is still a single in-sample replay per symbol/setup, not walk-forward validated (only the payoff-ratio *input* is now empirical — the replay methodology itself doesn't hold out an OOS period the way axis-2's strategy optimizer does) | `signal_confidence.py:compute_confidence()` |
| Low | The complexity-penalty weight (`0.05` per parameter) is a fixed constant, not config-driven or empirically tuned — reasonable default, but untested against real historical data for whether it's the right magnitude | `walk_forward.py:_complexity_penalty()` |

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort) — **PASS**

The user has their own bespoke trader-perspective settings-audit skill on their local machine, not yet committed to this repo — **this section is my own best-effort judgment as a stand-in, not a substitute for it.** Should defer to the user's skill once it's added here.

| File | Judgment | Evidence |
|---|---|---|
| `risk_rules.yaml` | Conservative, survivable numbers: 5% max single-trade exposure, 25% max aggregate, a real 2%-of-portfolio daily-loss circuit breaker, one position per symbol. Reads as risk-desk-considered, not backtest-optimized. | `backend/config/risk_rules.yaml:3-11,37` |
| `contract_rules.yaml` | Two-tier design (hard-reject vs soft-preference) for liquidity/spread/delta/DTE — hard reject at 20% spread but soft-preferred cutoff at 8%, which is the more realistic fill target. `max_iv_rank: 70` for long-premium is a sensible volatility-crush guard. | `backend/config/contract_rules.yaml:11-32` |
| `scoring_rules.yaml` | `pass:55 / caution:35` leaves a genuine middle band, not a near-binary gate. Event and IV-rank gates are differentiated by horizon (intraday vs swing vs position) rather than copy-pasted — matches the documented rationale in `SCORING_RULES.md`. One thing worth a human double-check rather than asserted as a defect: `intraday.vol.iv_rank_*` are all `null` (`scoring_rules.yaml:178-180`) — confirm the vol-rule scorer treats this as "gate disabled" intentionally, not an unhandled null. | `backend/config/scoring_rules.yaml:6-7,102-107,174-180`; `SCORING_RULES.md` |
| `strategy_params.yaml` | Per-strategy stop/target multiples are sane, not aggressive (e.g. `pullback_ema`: 1.5x ATR stop vs 2.0x R:R target — a standard ≥2:1 setup). WFO `windows` (12mo train / 3mo test) and `optimization` (`min_trades:20`, `min_consistency:0.5`) match exactly what axis 2 found enforced in code — config and implementation are in sync, not drifted. | `backend/config/strategy_params.yaml:1-4,18-20,27-40` |

No REJECT-level findings on this axis.

---

## Prioritized punch list

All three Medium items from this run's first pass are fixed (see "Since last run"). What's left is Low/polish:

| Priority | Item | Why |
|---|---|---|
| Low | Consider WFO-validating `signal_confidence.py`'s replay instead of a single in-sample pass | Would close the last gap between axis 2's two confidence-adjacent subsystems (the strategy optimizer already does real OOS; the confidence replay still doesn't) |
| Low | Confirm `intraday.vol.iv_rank_*: null` is deliberately "gate disabled," not an unhandled null path | Cheap to verify, avoids silent scoring bug |
| Low | Add a lockfile for `frontend/` (or document why it's intentionally excluded) | Non-reproducible installs risk a repeat of this run's TypeScript version mismatch (global v6.0.2 vs pinned `^5.7.0`) |
| Low | Bump `next`, `postcss`, `sharp`, `xlsx` to clear 4 high-severity `npm audit` findings | Standard hygiene, not exploitable in this app's context as far as this pass could tell |
| Low | Document the two local-setup gotchas (`cp config/settings.example.yaml config/settings.yaml`, use `python3 -m pytest` not bare `pytest`) somewhere onboarding-visible | Currently only known because this run hit both |
| Low | Empirically tune the complexity-penalty weight (currently a fixed `0.05`/param constant) against real historical optimizer runs | Untested magnitude — reasonable default, not validated |

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above instead of re-deriving everything from scratch.
