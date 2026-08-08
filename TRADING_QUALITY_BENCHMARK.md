# Trading Quality Benchmark — Bamendjou

**Date**: 2026-08-08
**Method**: `.claude/skills/K-quality-benchmark` (first run)
**Standards**: code correctness, algorithmic trading-logic soundness, config/settings sanity — judged against what Bamendjou actually aims to be: a screener whose core promise is surfacing real, non-overfit, well-calibrated trade setups, not just a working UI.

---

## Overall grade: **PASS** (with a short punch list)

| Axis | Grade |
|---|---|
| 1. Code quality | PASS |
| 2. Trading-logic (algorithmic) soundness | PASS |
| 3. Config / settings sanity ("as a trader", best-effort) | PASS |

---

## Does a GitHub skill already exist to benchmark this kind of app?

Yes — and it was already run on this exact repo once before.

`PRODUCTION_READINESS_AUDIT.md` (repo root, dated 2026-05-05) was produced by a different AI tool ("opencode") running the **`bmad-review-adversarial-general`** skill from **[bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)** (skill source: `src/core-skills/bmad-review-adversarial-general/SKILL.md`), a real, public, actively-maintained Claude/Codex skill for adversarial code review against a spec. This repo's own planning docs (`docs/superpowers/plans/*.md`) also repeatedly invoke a "K-adversarial-audit-loop" using that same skill, alongside the **[obra/superpowers](https://github.com/obra/superpowers)** plugin for review-driven implementation.

What it does **not** cover: whether the screener's trading edge is real. BMAD-style review checks code correctness and spec compliance — it has no concept of lookahead bias, walk-forward validity, or whether a YAML risk parameter is survivable. That's domain-specific to Bamendjou, which is why axes 2 and 3 below are first-party rather than borrowed from an external tool. See `.claude/skills/K-quality-benchmark/SKILL.md` for the reusable rubric this report was generated from.

---

## Axis 1 — Code quality

### Fresh verification (this run)

| Check | Result |
|---|---|
| `npm run typecheck` (frontend) | **PASS** — exit 0, clean |
| `npm run test` (frontend, Jest) | **PASS** — 61 suites, 490 tests, 0 failures |
| `pytest` (backend) | **PASS** — 1368 passed, 1 skipped, 1 xpassed, 0 failures |
| Quant-soundness regression suite (`test_data_leakage`, `test_regime_no_lookahead`, `test_walk_forward`, `test_signal_confidence`, `test_strategy_backtest`) | **PASS** — 44/44 |

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
| Medium | CI's frontend job only runs `npm run build`; the 490-test Jest suite is never executed in CI | `.github/workflows/ci.yml` |
| Low | No committed frontend lockfile — `package-lock.json` is gitignored, so installs aren't pin-reproducible | `.gitignore:21`, `frontend/.gitignore` |
| Low | 4 high-severity `npm audit` findings (Next.js, postcss, sharp, xlsx transitive CVEs) | `npm audit` output, this run |
| Low | Local dev setup has two silent failure points not documented in a setup script: missing `backend/config/settings.yaml` (routers read it at import time) and the isolated `pytest` binary shadowing the project's Python env | this run |

---

## Axis 2 — Trading-logic (algorithmic) soundness

This is unusually rigorous for a retail-facing screener — genuine walk-forward validation and explicit overfitting guards, not just a backtest number slapped on a UI.

| Component | Finding | Evidence |
|---|---|---|
| Lookahead safety | Signal function only ever sees a truncated `bars[:n]` slice up to the current simulated bar; entries fill on subsequent bars via `backtesting.py`, not same-bar | `backend/app/services/strategy_backtest.py:96-119` |
| Backtest gates | `_MIN_TRADES=10`, `_MIN_WIN_RATE=0.45`, `_MIN_EXPECTANCY=0.0`, enforced via `passes_gate` | `strategy_backtest.py:23-25,146` |
| Walk-forward validity | Genuine non-overlapping in-sample/out-of-sample fold construction (rolling or anchored), not a repeated re-run on the same data | `backend/app/services/walk_forward.py:31-83` |
| Overfitting guard | OOS eligibility requires `n_trades>=20` and `consistency>=0.5`; verdict text explicitly downgrades to "Edge looks fake — consider dropping" below threshold; param stability enforced via fold-consensus (median/mode), not single-best-fold selection | `backend/app/services/strategy_param_optimizer.py:47,50-55`; `walk_forward.py:164-187` |
| Confidence calibration | `signal_confidence.py`'s confidence is derived from an actual historical replay (correctly bar-truncated), not a static weight | `backend/app/scoring/signal_confidence.py:153-207` |
| Dedicated regression coverage | `test_data_leakage.py`, `test_regime_no_lookahead.py` explicitly test for lookahead; `test_walk_forward.py`, `test_strategy_backtest.py`, `test_signal_confidence.py` cover fold math, gate correctness, and confidence aggregation | `backend/tests/` |

### Caveats (not blockers, worth tracking)

| Severity | Finding | Evidence |
|---|---|---|
| Medium | The inner grid search (`train_fold()`) still picks params by max in-sample Sharpe with no per-combination complexity penalty — the overfitting guard is post-hoc (OOS degradation/consistency check) rather than preventing the in-sample search itself from curve-fitting | `walk_forward.py:133-161` |
| Medium | `signal_confidence.py`'s confidence is a single in-sample replay per symbol/setup, not walk-forward validated; the `payoff_ratio` formula is commented "per spec; tunable" in the source — not empirically calibrated | `signal_confidence.py:92-113,109` |

---

## Axis 3 — Config / settings sanity, "as a trader" (best-effort)

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

| Priority | Item | Why |
|---|---|---|
| Medium | Wire the Jest suite into `.github/workflows/ci.yml` (currently only `npm run build` runs) | 490 tests currently provide zero CI protection against regressions |
| Medium | Empirically calibrate `signal_confidence.py`'s `payoff_ratio`, and consider WFO-validating confidence instead of a single in-sample replay | Confidence is the number a trader trusts most; it's currently the least rigorously validated part of the pipeline |
| Medium | Add a complexity penalty (or param-count cap) to the in-sample grid search in `strategy_param_optimizer.py`, rather than relying solely on post-hoc OOS degradation checks | Reduces the chance of a curve-fit param set even passing the eligibility gate on a lucky fold |
| Low | Confirm `intraday.vol.iv_rank_*: null` is deliberately "gate disabled," not an unhandled null path | Cheap to verify, avoids silent scoring bug |
| Low | Add a lockfile for `frontend/` (or document why it's intentionally excluded) | Non-reproducible installs risk a repeat of this run's TypeScript version mismatch (global v6.0.2 vs pinned `^5.7.0`) |
| Low | Bump `next`, `postcss`, `sharp`, `xlsx` to clear 4 high-severity `npm audit` findings | Standard hygiene, not exploitable in this app's context as far as this pass could tell |
| Low | Document the two local-setup gotchas (`cp config/settings.example.yaml config/settings.yaml`, use `python3 -m pytest` not bare `pytest`) somewhere onboarding-visible | Currently only known because this run hit both |

---

## Next run

Re-invoke `.claude/skills/K-quality-benchmark`. It will read this file first and report fixed/still-open/new against the punch list above instead of re-deriving everything from scratch.
