---
name: K-quality-benchmark
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
skill (`K-quality-benchmark`, named after this repo's own `K-adversarial-audit-loop`
convention in `docs/superpowers/plans/*.md`) exists because axes 2 and 3 are
domain-specific to Bamendjou and no generic external tool grades them.

`bmad-review-adversarial-general` is installed at claude.ai account level (a
standalone port — the upstream ID is a v6 shim forwarding into installer-dependent
infrastructure this repo doesn't run; see that skill's own file for why). It lists
as `anthropic-skills:bmad-review-adversarial-general`. **Axis 1 must invoke it via
the `Skill` tool** (see Axis 1 below) instead of re-deriving code-quality findings by
hand.

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

### Axis 1 — Frontend/backend code quality

Two layers, both required — the review skill does not replace the gating commands,
and the gating commands don't catch what an adversarial read of the diff does:

1. **Adversarial code review.** Invoke `bmad-review-adversarial-general` via the
   `Skill` tool, pointed at what's being graded (the working-tree diff against the
   last commit `TRADING_QUALITY_BENCHMARK.md` was written for, or the whole repo on
   a first run with no prior benchmark to diff against). Fold its findings directly
   into axis 1's findings table — don't re-derive the same class of finding by hand
   first and treat the skill as a second pass; run it as the primary code-quality
   pass and add anything it plausibly missed.
2. **Gating commands** (below) — typecheck/test/build/audit, run from a genuine
   clean room. These catch what a diff-level review can't: whether the repo actually
   installs and builds from nothing, real test-suite pass/fail counts, dependency
   drift.

### Clean-room verification methodology — read before axis 1

A prior run of this skill graded axis 1 PASS twice while genuinely broken from a
clean checkout, because the checks ran against a polluted local environment rather
than a real clean room. Avoid repeating that:

- **This repo has a stray root-level `package.json`** (separate from
  `frontend/package.json`, unrelated placeholder scaffolding — check it hasn't
  regrown a dependency entry that masks a `frontend/`-scoped gap via Node's
  parent-directory module resolution walk-up). If `frontend/`'s own install is ever
  in doubt, verify with root `node_modules/` absent or renamed aside, not just
  `cd frontend && npx tsc`.
- **`npm run build` is a required check, not optional** — it catches ESLint errors
  `npm run typecheck`/`npm run test` don't (a prior run skipped it entirely and
  missed 47 real build-blocking errors, including a genuine React rules-of-hooks
  bug). Always run all three: typecheck, test, **and build**.
- **If you need a genuine "does this work from nothing installed" check**: apply
  any fixes, commit them locally first (a plain `git clone` of an uncommitted
  working tree silently tests the *previous* commit, not your fix), then `git
  clone` that commit into an isolated scratch directory and run the install/build
  there — never `rm -rf node_modules`/delete local config directly in the shared
  working tree, since a broken intermediate state left behind can be misread by a
  future session as a real regression. Delete the scratch clone when done.

```bash
cd frontend
npm install                    # no committed package-lock.json in this repo — always reinstall, don't trust a stale node_modules
npm run typecheck              # must exit 0
npm run test -- --ci           # capture "Test Suites: N passed" / "Tests: N passed" summary
npm run build                  # must exit 0 — this is the real CI gate; do not skip it
npm audit --json | jq '.metadata.vulnerabilities'   # note high/critical counts, don't block on them

cd ../backend
pip install -r requirements.txt
python3 -m pytest -q           # NOT the bare `pytest` binary — on some machines it resolves to an isolated uv-tool
                                # interpreter that never sees this repo's installed deps and fails with a misleading
                                # "No module named 'fastapi'" even though fastapi is installed.
                                # settings.yaml is no longer required for import — scan.py falls back to the
                                # committed settings.example.yaml when it's absent (fixed 2026-08).
```

Also check `.github/workflows/*.yml` for whether these commands are actually the
ones CI runs — a green CI badge only means what the workflow file says it means.
Re-verify current CI behavior each run rather than trusting a prior finding.

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

**This mechanism-correctness check alone is not a trader's opinion on code
quality** — it verifies the backtest/WFO infrastructure is implemented correctly,
using synthetic fake price data. It says nothing about whether the actual
strategies produce real edge. Always pair it with:

**Real-data evidence** — run `run_strategy_backtest()` (not synthetic bars) against
the real fixture data in `backend/tests/fixtures/{AAPL,MSFT,NVDA,SPY}_candles.json`
(~251 real daily bars each, currently spanning about one year) for every strategy
except `mean_reversion_vwap` (documented intraday-only — daily bars produce a
semantically meaningless result for it, exclude or label N/A). Report actual
`n_trades`/`win_rate`/`sharpe`/`expectancy`/`max_drawdown_pct` per strategy×symbol —
real numbers, not fabricated. Expect (and report honestly rather than paper over):
`mean_reversion_rsi`/`mean_reversion_bb` need ≥219–225 bars of warmup
(`trend_sma`+period from `strategy_params.yaml`) against ~251 total bars, leaving
too thin a tail to hit `_MIN_TRADES=10` — a near-certain empty result on this
fixture, which is itself a legitimate finding ("insufficient real historical data
in this environment to evaluate these strategies meaningfully"), not something to
hide. If *no* strategy×symbol combination reaches the gate, say so plainly — that's
a real, trader-relevant limitation of what this environment can validate, not a
verdict on the strategies themselves.

Grade PASS/CAUTION/REJECT. A REJECT here (e.g. a genuine lookahead bug, or WFO folds
that actually overlap) is more serious than any frontend finding — it means the
product's core promise is broken even if the UI is flawless. Insufficient real data
to validate strategy performance is a CAUTION-level finding (a real gap), not a
REJECT (the mechanism itself isn't shown broken).

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

## Grading rubric

Apply this per axis, then combine — don't eyeball it, since "PASS despite an open
Medium finding" is exactly the kind of drift this skill exists to catch:

- **REJECT** — a gating check actually fails (typecheck, test suite, or the quant
  regression suite is red), or you find a genuine soundness bug (real lookahead,
  WFO folds that actually overlap, a risk-config value with no cap where one is
  needed to survive a losing streak).
- **CAUTION** — every gating check is green, but at least one open finding in that
  axis is Medium severity or worse (a real gap, not polish) — e.g. a validated
  suite that CI never runs, an uncalibrated formula a trader would rely on, a
  curve-fitting exposure with only a post-hoc guard.
- **PASS** — no open Medium+ findings; only Low/polish items remain.

Overall grade = the worst of the three axis grades (REJECT > CAUTION > PASS),
mirroring `worstStatus()` in `frontend/lib/status.ts` — don't average, don't let a
strong axis 2 paper over a CAUTION-level axis 1.

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
