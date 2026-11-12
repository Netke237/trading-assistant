# Backtest review implementation handoff

The user requested ticket creation only. Application implementation has not started. The tracking issue is authoritative for live ticket progress; PROJECT_STATE.json retains phase/audit status.

- [Tracking issue #631](https://github.com/Netke237/trading-assistant/issues/631).
- [T1 #632: recorded numerical presentation](https://github.com/Netke237/trading-assistant/issues/632).
- [T2 #633: performance summary and drawdown](https://github.com/Netke237/trading-assistant/issues/633).
- [T3 #634: price styles and trade inspection](https://github.com/Netke237/trading-assistant/issues/634).
- [T4 #635: original/fresh report navigation](https://github.com/Netke237/trading-assistant/issues/635).
- [T5 #636: integrated verification, independent code audit and PR](https://github.com/Netke237/trading-assistant/issues/636).

Dependencies are sequential T1 → T2 → T3 → T4 → T5; T5 also explicitly depends on T1–T3. T1 is the initial frontier. Tickets are build units; the integrated phase is the independent code audit target.

Read `../2026-11-12-backtest-review-visualisation-plan.md`, `plan-audit.md` and the live issues before resuming. `tickets.json` retains verified publication ids, labels and dependency readback. Native GitHub links are authoritative. The permanent preview is in `../../specs/2026-11-12-backtest-chart-preview/`; do not copy its synthetic data or renderer into production.

## Resume prompt

```text
Use the k-ticket-coordinator skill in RESUME mode.
Repository: Netke237/trading-assistant
Branch: codex/backtest-review-implementation-plan
Tracking issue: #631
Phase / claim: BACKTEST-REVIEW-VISUALISATION
Plan: docs/superpowers/plans/2026-11-12-backtest-review-visualisation-plan.md
Read docs/agents/ticket-orchestration.md, task-ratings.md and issue-tracker.md.
Follow all repository runtime, task ownership, session and audit instructions.
Acquire the phase claim before changes; no takeover of another live owner.
The exact plan is approved by one independent clean round; code audit is unstarted.
Start with #632, then dependencies #633 → #634 → #635; coordinator #636 last.
Use a fresh implementer per build ticket and a fresh independent reviewer per audit round.
Preserve recorded indices, raw fill precision, timestamps and original/fresh provenance.
Do not run against real broker accounts or replace recorded evidence with live prices.
Follow the repo's merge gates; queued tickets are not authorization to bypass them.
```
