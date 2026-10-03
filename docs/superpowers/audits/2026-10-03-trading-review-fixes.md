# TRADING-REVIEW-FIXES — Phase A completion

Code is built and independently audit-clean on `codex/trading-review-fixes`; not merged.

## Scope and decisions

The recovered implementation covers the six High findings in `TRADING_REVIEW.md`, with the user's amended decisions preserved: unknown next earnings on a single stock caps its card at CAUTION and refuses auto-fire; recognised ETFs are exempt. Vetoed cards refuse Arm and Fire now but keep Disarm reachable. The configurable pullback R/R floor remains **disabled (`0.0`)** until multi-year retuning. This builds the mechanism, not a claim that low-R/R signals or trading expectancy have improved.

Current main `6b065c38c6cc1936ec6c04153a02c6c1beeabac7` was integrated at `7743194393d3dd414659af51347f9df544de9163`. No merge conflicts occurred.

## Independent code audit

The gate is the PROJECT_STATE audit_rule: reachable wrong user/broker numbers, corrupted persisted data, and its bounded mechanism-comment exception. Reviewers applied the repository's bmad-review-adversarial-general and K-adversarial-audit-loop skills.

1. **Round 1 — not clean**. Fresh reviewer `/root/audit_round1` reviewed the full `6b065c38..77431943` diff. One gate finding: a fold with no trained winner was still tested OOS using default parameters. Its return/parameters were excluded later, but its 100 trades and metrics could inflate a valid one-trade proposal to 101 trades and falsely show eligible/safe to adopt. Independent focused backend validation: 63 passed. No other gate findings.
2. **Round 2 — interrupted, no final verdict available**. A fresh reviewer started reviewing the fix delta and confirmed its scope. The final report was unavailable after interruption. This attempt is retained in the counter and is never treated as clean.
3. **Round 3 — clean, final slot**. Fresh reviewer `/root/audit_round3` reviewed ONLY `7743194393d3dd414659af51347f9df544de9163..ce4cfc148372cd44f1d4cc3971c819d16de31e22`, two files/67 additions, plus interactions. Zero gate findings after re-check. Independently ran optimizer tests (3 passed), all six order permutations of empty/positive/negative folds, a zero-trade second contributor, and all-empty multiple folds. Checked consensus, eligibility, degradation, metric alignment, and actual empty-winner behavior. No fourth round.

Fix `ce4cfc14` skips OOS entirely without a training winner while keeping the parallel return arrays aligned. Two regressions failed before the fix (2 failed/1 passed), and passed afterward.

## Validation

- Python 3.11.16, matching the repository runtime pin.
- Full backend run on recovered integrated implementation `77431943`: **4,710 passed, 1 skipped, 1 failed**, 464.41 seconds. The failure is inherited `test_stock_shortlist.py::test_the_frontend_prefix_matches_the_backend_constant`: main's `frontend/lib/parsePipelineDiagnostics.ts` duplicates `Shortlist cap:`. Neither failing file changed in this task. This defect was already recorded against main; it was not hidden, disabled, or fixed outside scope.
- After `ce4cfc14`: **56 focused backend tests passed**, including optimizer, warmup, direction normalization, walk-forward, and tuning adoption. The full expensive suite was not rerun after this backend-only fix; impacted modules were rerun.
- Frontend **183 suites / 4,486 tests passed**, typecheck passed, production build passed. There were existing lint/backtesting warnings, not a warnings-free claim.
- `python3 scripts/state.py --quiet` succeeds, with inherited unaudited-target warnings. Nonquiet rendering still raises an inherited KeyError on a dictionary-valued open question. No claim that unrelated state targets were audited.

## Trading review follow-up (areas 2–4)

This is a scoped evidence review against the original report, not a new full trading panel or profitability verdict. The named `k-trading-software-reviewer` skill is absent from the checkout and available skill catalog; no invocation of that missing skill is claimed.

- Statistical evidence: direction reaches the proposal and adoption boundary; ordinary trading-day folds receive warmup, place no entries before the scored window, and exclude untrained-fold evidence. Existing numerical/quant modules ran in the full suite. Multi-year production-data retuning, overlapping confidence samples, and sparse regime transitions remain Phase B.
- Options selection: scan final status, direct sends, and automatic fire enforce the earnings decisions; the rail uses earnings distance rather than a nearer dividend and the scan's event window. Spread-leg liquidity, spread R/R/routing, and DTE policy remain Phase B. Fire uses the horizon's configured YAML window; scan-specific event overrides are not carried on the arm (existing recorded limitation).
- Risk sizing: long-option premium is capped by the smaller single-position/per-trade-loss fraction; stock caps are unchanged. The account value is still supplied by the client, and realised daily loss is not a persisted cross-path circuit breaker. Those remain Phase B.

Fresh fixture measurements (`commission=0.002`, Bullish pullback_ema, 251 daily bars) reproduce the disabled-floor decision:

| Symbol | Floor 0: trades / expectancy % | Floor 1: trades / expectancy % |
| --- | --- | --- |
| AAPL | 6 / +0.080 | 1 / -4.350 |
| NVDA | 4 / +0.415 | 3 / -2.342 |
| SPY | 11 / -0.524 | 1 / -3.784 |

These short fixtures do not establish a reliable edge. Phase A code audit is clean; Phase B and the original review's broader trading-quality limitations remain.
