# Regime series implementation verification

phaseID: `REGIME-SERIES-LENGTH` (tracking #534; build units #563–#565).

This note records local implementation evidence for the approved [implementation plan](../../plans/2026-10-25-regime-series-length-implementation-plan.md). It does not replace the historical measurement report or an independent code audit. Integrated independent code review remains pending with the coordinator.

The daily per-symbol regime source is now the settled database history, with a uniform minimum of 800 bars and growth for larger effective daily configurations. Options, Stocks, Analysis daily summaries and Fire use that source; their other candle inputs and Intraday paths remain separate. Unavailable or insufficient sentiment now visibly says “Regime: Unmeasured” and “Insufficient history or unavailable data.” in the shared molecule used by both cards. Measured zero remains a measured value. TradeCard's explicit presentation control retains its meaning.

## Deterministic database evidence

`backend/tests/test_daily_regime_integrations.py` seeds an isolated SQLite database with 1,000 dated TEST rows, raw closes `200 + i`, and adjustment factor `0.5`. Its independently specified expected latest 800 closes are `100 + i / 2` for `i = 200..999`: 200 through 599.5 in ascending order. Spies at the real computation calls assert exact arrays for Options, Stocks, Analysis and worker-thread Fire, for Bullish/Bearish and Swing/Position. Both Options scorer passes carry the same measured signal; Analysis's daily blocks and Fire results agree with direct computation over the expected series. Additional checks retain the original non-regime scorer/backtest histories, semaphore behavior, config failures, abstentions and warnings, cache isolation and Intraday handling. Provider/scorer dependencies are isolated; this evidence does not exercise broker submission.

`backend/tests/test_daily_regime_history.py` independently pins literal 800-of-1,000 dates and adjustments, stale/empty/sparse results, settlement/weekend/DST cutoffs, SQL limit and symbol/end isolation, count validation/growth, async/sync JSON parity, repeated worker-loop private NullPool engines and cleanup on query failure. These tests use local isolated databases, not the deployed historical store.

## Verification record

Unit 2's recorded source commit is `25fb450f158417fd10cd7ed3893fcc8d8cc27a7d`; its exact backend tree is `9e782b4aea2dcc19c357e2d581beea99101c1fea`. The full backend log records Python 3.11.16, **10,118 passed, 9 skipped, 2,499 warnings in 942.88s**, exit 0. The focused backend log records **543 passed in 41.77s**, exit 0. Unit 3 inspected these actual logs and the handoff, and verified the same backend tree before and after its frontend-only work. It carries that unchanged-tree result forward; it did not rerun the backend suite.

Unit 3 runtime: Node v24.19.0, npm 11.9.0. Tests were changed before source: the focused RED run had **8 failed / 92 passed**, all failures at the missing “Regime: Unmeasured” notice in the molecule and real cards. The minimal source change then passed **3 focused suites / 100 tests**. Coverage includes absent/null/insufficient sentiment, stale numbers, measured zero and normal measured output, compact/default rendering, candidate changes, real TradeCard and embedded/position StockPositionCard, and the TradeCard presentation control. The target molecule is not mocked in these integration tests.

Frontend `npm run typecheck` passed. Production `npm run build` passed (Next.js 15.5.23; 30/30 static pages generated). Complete Jest passed: **320 suites / 6,017 tests in 223.763s**, exit 0. An initial full run was stopped after finding an existing TradeCard presentation test that asserted the superseded empty-state wording; its two string expectations were updated and the complete suite restarted. Persistent execution evidence uses the `unit3-` prefix in the coordinator's recovery log directory; unit 2's full/focused backend logs and acceptance/handoff are retained alongside it.

## Limits

No live mini-PC, deployed database, provider/broker credentials, orders, notifications, calibration or ingestion jobs were exercised by this verification. Local isolated database parity and UI tests establish the tested contracts; live data availability and deployment behavior remain unverified here. This implementation evidence does not declare the independent audit or merge gates complete.
