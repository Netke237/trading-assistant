# NO-LIVE-QUOTE then CONTRACT-LIQUIDITY-DTE — spec

Source of truth: `docs/superpowers/plans/2026-09-30-no-live-quote-plan.md` (plan r3, plan stage CLEAN 2026-10-05)
and, for the CL tickets, `docs/superpowers/plans/2026-09-30-contract-liquidity-dte-plan.md` (plan r5 on
`origin/claude/contract-liquidity-dte`, plan stage closed by Kenneth 2026-09-30, decision
CONTRACT-LIQUIDITY-DTE-MERGE-HOLD-2026-09-30).

Kenneth's answers (decision NO-LIVE-QUOTE-QA-QD-ANSWERS-2026-10-09): Q-A 30 min; Q-B warning + confirm
tick keyed to contractKey, decided on a fresh send-time quote; Q-C drop rows with ask <= 0; Q-D keep the
merge hold (NLQ merges first).

Goal: an option chain row whose quote is not live (market closed, stale, one-sided) is never graded or
traded as live: hard reject in the scan and at auto-trade fire time; label in Step 6 / Watchlist; warning
+ per-contract confirm tick on Step 7 direct send. Then volume < 50 stops being a hard reject (FR-25).

Gate (project audit_rule): a finding blocks only if it can put a WRONG NUMBER in front of a user or on a
broker order, or CORRUPT PERSISTED DATA (or a mechanism comment a reader would act on wrongly). Everything
else is logged, not fixed in-branch. Cap: 3 code rounds per ticket. Python 3.11 for all backend runs.
Line numbers in the plan are from main of 2026-10-05; main was merged in at 2051fa39 -- re-locate every
reference before editing.
