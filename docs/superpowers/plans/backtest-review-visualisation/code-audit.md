# Independent code audit — round 1

Phase `BACKTEST-REVIEW-VISUALISATION`; code stage round 1 of 3; continuous phase round 2. Date: 2026-11-15. Reviewer: fresh independent `gate-auditor` agent `backtest_code_audit_1` (Claude), applying `.claude/skills/bmad-review-adversarial-general/SKILL.md` under `.claude/skills/K-adversarial-audit-loop/SKILL.md`, briefed with the repo gate verbatim (wrong number in front of a user / on a broker order, corrupted persisted data, mechanism-misstating comments).

Exact scope: application diff `git diff e8eca1b60075701be75ea208894bfb1bf48f29bc..eecaa5c0dfb0c6d2e58c77639309faec071c5184` (e8eca1b6 = origin/main = merge-base). Covers T1 `690b034b`, T2 `1d168cb8`, T3 `454dd82b`, T4 `82e7275b`, verification `a68ba532` and the resize fix `eecaa5c0`.

**GATE FINDINGS: 0**, after a second pass over every numeric path.

Read in full: `CandidateBacktestWorkspace/index.tsx` (base and head), `presentation.ts`, `presentation.test.ts`, `paneSync.ts`, `chart.ts`, `molecules/BacktestTradeTable/index.tsx`, `CandidateChartWorkspace/index.tsx` diff and keying, `FreshBacktestControls/index.tsx` diff, `types/backtest.ts`, the plan. Engine semantics cross-checked against `backend/app/services/strategy_backtest.py` (370–511) and `strategy_backtest_details.py` (180–397): win_rate is a 0–1 fraction (card ×100), max_drawdown_pct is ≤0 and passed through unchanged, net_return_pct is already a percent and never recomputed, indices are `100*equity/baseline` and `100*close/first close` with `initial_equity = baseline`, return display `index − 100` without rebasing, difference from the same last equity sample before formatting, engine/index discrepancy disclosed (rounding-hidden gaps never presented as equality), sampled drawdown seeded from initial equity over full history. Readouts use exact timestamps only; original/fresh and candidate identity keyed; display controls make no fetch/run/persist.

Below gate (context only, not fixed): zero-trade runs show the engine's recorded win_rate 0.0 as "0.00%"; `presentation.test.ts` fixture uses a positive `max_drawdown_pct` (passed through, nothing displayed wrongly).

Not covered by the reviewer: running the Jest/Playwright suites (run separately by implementers and the coordinator), CSS modules, screenshot evidence.

Coordinator verified the exact range and file scope. Code stage closed clean in round 1 of 3. Clean audit does not mark the unmerged target shipped.
