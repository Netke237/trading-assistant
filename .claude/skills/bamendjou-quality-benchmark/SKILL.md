---
name: bamendjou-quality-benchmark
description: Grade Bamendjou (this repo) on three axes — frontend/backend code quality, algorithmic trading-logic soundness, and trading-config sanity — and write the result to TRADING_QUALITY_BENCHMARK.md at repo root. Use when asked to benchmark, audit, grade, or score the quality of this trading screener, or to check whether it's still production-ready / whether its trading logic is sound.
---

# Bamendjou quality benchmark

Bamendjou's core promise is not "the UI works" — it's that the screener surfaces
real, non-overfit, well-calibrated trade setups. A benchmark that only checks code
correctness (lint, types, tests passing) misses the half that actually matters to a
trader. This skill grades all three layers every time it runs, and diffs against the
previous run so drift gets caught instead of re-discovered from scratch.

Background: a prior audit (`PRODUCTION_READINESS_AUDIT.md`, 2026-05-05) was produced
by a different AI tool running the `bmad-review-adversarial-general` skill from
[bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) — a real,
public skill that already covers axis 1 well (PRD/code-correctness auditing). This
skill exists because axes 2 and 3 are domain-specific to Bamendjou and no generic
external tool grades them. If BMAD-METHOD or a similar skill is ever committed into
this repo's own `.claude/skills/`, prefer running it for axis 1 instead of
re-deriving code-quality findings by hand.

The user has their own bespoke trader-perspective settings-audit skill, built
locally on their machine, not (yet) committed to this repo. Axis 3 below is a
best-effort stand-in for that skill. If the user's own skill is ever added to this
repo's `.claude/skills/`, defer to it for axis 3 instead.

## How to run this

1. Read the previous `TRADING_QUALITY_BENCHMARK.md` (if it exists) to know what was
   previously flagged, so this run can report fixed / still-open / new instead of
   restating everything from zero.
2. Run the three axes below. Do not skip the "make it actually run" steps — this repo
   has real setup friction (no committed lockfiles, gitignored local config files,
   an isolated `pytest` binary on some machines) that silently produces false
   negatives if you don't get past it. Always run the *fixed* versions of any
   commands below, and note any friction you had to work around as its own finding
   (dependency/reproducibility issues are legitimate code-quality findings, not
   noise to hide).
3. Combine into one overall grade and write/update `TRADING_QUALITY_BENCHMARK.md`.

### Axis 1 — Code quality

```bash
cd frontend
npm install                    # no committed package-lock.json in this repo — always reinstall, don't trust a stale node_modules
npm run typecheck              # must exit 0
npm run test                   # capture "Test Suites: N passed" / "Tests: N passed" summary
npm audit --json | jq '.metadata.vulnerabilities'   # note high/critical counts, don't block on them

cd ../backend
pip install -r requirements.txt
cp -n config/settings.example.yaml config/settings.yaml   # gitignored local config; tests import routers that read it at import time
python3 -m pytest -q           # NOT the bare `pytest` binary — on some machines it resolves to an isolated uv-tool
                                # interpreter that never sees this repo's installed deps and fails with a misleading
                                # "No module named 'fastapi'" even though fastapi is installed
```

Also check `.github/workflows/*.yml` for whether these commands are actually the
ones CI runs — a green CI badge only means what the workflow file says it means.
(As of the 2026-08 run: CI's frontend job runs `npm run build` only — the Jest
suite is never executed in CI. Re-verify this hasn't changed before repeating the
finding.)

Grade PASS/CAUTION/REJECT using this project's own vocabulary
(`frontend/lib/status.ts`).

### Axis 2 — Trading-logic (algorithmic) soundness

Read and re-verify against current source (line numbers drift):

- `backend/app/services/strategy_backtest.py` — does the signal function only ever
  see bars up to the current simulated index (no lookahead)? What are the current
  `_MIN_TRADES` / `_MIN_WIN_RATE` / `_MIN_EXPECTANCY` gate values?
- `backend/app/services/walk_forward.py` — does `build_folds()` produce genuinely
  non-overlapping in-sample/out-of-sample windows, or overlapping re-runs dressed up
  as WFO? Do `degradation_pct()` / `consistency()` actually get used to reject
  curve-fit params downstream?
- `backend/app/services/strategy_param_optimizer.py` — is there a real overfitting
  guard (OOS trade-count + consistency minimums), or does the grid search just pick
  max in-sample Sharpe with no penalty?
- `backend/app/scoring/signal_confidence.py` — is "confidence" derived from an
  actual historical replay (bar-truncated, no lookahead) or a static weight? Is it
  WFO-validated or a single in-sample pass?
- Run the quant-specific regression suite and confirm it's still green:
  `python3 -m pytest -q tests/test_data_leakage.py tests/test_regime_no_lookahead.py tests/test_walk_forward.py tests/test_signal_confidence.py tests/test_strategy_backtest.py`

Grade PASS/CAUTION/REJECT. A REJECT here (e.g. a genuine lookahead bug, or WFO folds
that actually overlap) is more serious than any frontend finding — it means the
product's core promise is broken even if the UI is flawless.

### Axis 3 — Config / settings sanity, "as a trader" (best-effort)

Read the actual configured values — not just whether they parse — and judge them
the way a trader reviewing a risk desk's settings would:

- `backend/config/risk_rules.yaml` — is `max_daily_loss_pct` a real circuit
  breaker? Is `max_single_trade_exposure_pct` survivable across a losing streak?
  Any place a cap is missing where one obviously should exist?
- `backend/config/scoring_rules.yaml` — do `pass`/`caution` thresholds leave a real
  middle band, or is the gate effectively binary? Are IV-rank / event-proximity
  gates differentiated sensibly by horizon (intraday vs swing vs position), or
  copy-pasted?
- `backend/config/contract_rules.yaml` — are liquidity/spread/delta/DTE filters
  realistic for actual fills (not just theoretically scoreable)? Is there a
  two-tier hard-reject vs soft-preference split, or one blunt cutoff?
- `backend/config/strategy_params.yaml` — are per-strategy stop/target multiples
  (e.g. ATR stop vs R:R target) a sane risk/reward ratio, or curve-fit to a
  particular backtest window? Do WFO `windows` (train/test months) and
  `optimization` (min_trades, min_consistency) match what the code in axis 2
  actually enforces?
- Cross-check against `SCORING_RULES.md` and `PRD_HMM_Regime_Trading_Bot.md` at
  repo root — do the YAML values match the documented rationale, or has one
  drifted from the other?

Label this section explicitly as a best-effort pass, not a substitute for the
user's own settings-audit skill. Grade PASS/CAUTION/REJECT.

## Output

Write/update `TRADING_QUALITY_BENCHMARK.md` at repo root:

1. One-line overall grade (PASS/CAUTION/REJECT) at the top.
2. A "Since last run" section: what got fixed, what's still open, what's new —
   diffed against the previous version of this file if one exists.
3. One section per axis: findings table (file:line evidence, like
   `PRODUCTION_READINESS_AUDIT.md`'s format) + axis grade.
4. A prioritized punch list, ordered by severity, spanning all three axes.

Keep evidence concrete (file:line, actual command output, real pass/fail counts) —
never estimate a number that a command could just tell you.
