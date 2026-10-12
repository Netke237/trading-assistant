# Project ticket reconciliation — review draft

Updated: 2026-10-09. All new bodies below are DRAFTS for the grilling/to-tickets review; none is ready-for-agent until its decisions, plan audit and actual blockers are settled. User explicitly selected Markdown files for this task; existing GitHub tickets remain authoritative for already-owned packages.

## Existing packages — reuse, do not duplicate

- T1: tracking #92, build #93–#103, coordinator #104; code audit clean on branch0eb74325, unmerged. Active owner retains control.
- Fire Hygiene: tracking #133, H1#134/H2#135/H3#136/coordinator#137; branch078a3c72 has H2 implementation; full code audit pending.
- NO-LIVE-QUOTE: existing NLQ-1–NLQ-5; branch215aeafe has NLQ-2 build, not proof of its audit clearance. CL-1/CL-2 remain its follow-on. TG-1 remains the owner's separate planned package.
- EXACT-STRIKE: existing plan clean, active owner; blocked NLQ merge and its Q1/Q2 decisions.
- HISTORY operation: existing D3#114 under tracker#123. Tiingo release: existing PR#132.

## Stale records resolved in this index

- P0A/P0B, Stocks S1/S2, HISTORY and Lane C are shipped; no new build tickets.
- STATE-BUILT-UNMERGED #78 shipped with P0A#88; retain its audit provenance.
- Original trade-card core/evidence/qualification code already integrated; only the separate follow-up release needs checking.
- isdigit/isdecimal defect already fixed; YAML recursion remains a separate residual.
- Original STOP-SEMANTICS and older S2 W1 build-needed notes are obsolete.
- Current claims and branches override older main backlog labels. No active owner's task files are changed by this preparation.

## Proposed numbered work units

1. [Verify and release the Tiingo governor](issues/01-tiingo-release.md) — blocked by PR #132 clean review and merge authorization; owner: coordinator.
2. [Deploy and verify historical backfill on the mini PC](issues/02-history-operation.md) — blocked by Existing D3 #114 / HISTORY tracker #123; Tiingo release if required by its runbook; owner: Kenneth operation.
3. [Run horizon tuning and preserve an adoption report](issues/03-tuning-run.md) — blocked by T1 #104 clearance and integrated machinery; populated historical data; owner: Kenneth operation.
4. [Specify pooled validation and adoption semantics](issues/04-t2-design.md) — blocked by 03 tuning-run results and T1 output schema; owner: agent design.
5. [Propose a complete per-cell validation slice](issues/05-t2-verdict.md) — blocked by 04 t2-design approved and plan clean; owner: agent implementation candidate.
6. [Propose explicit Adopt with authoritative opening-order guards](issues/06-t2-adopt.md) — blocked by 04 t2-design; 05 t2-verdict; owner: agent implementation candidate.
7. [Pre-register the scorer research protocol](issues/07-t3-protocol.md) — blocked by T2 implementation/code audit/integration complete (eventual build work from 05 and 06, not approval of these draft proposals); owner: agent research.
8. [Produce reproducible scorer research evidence](issues/08-t3-evidence.md) — blocked by 07 t3-protocol approval and historical data; owner: agent research / Kenneth operation.
9. [Decide and plan the measured score role](issues/09-t3-policy.md) — blocked by 08 t3-evidence; owner: Kenneth decision / agent plan.
10. [Specify Pre-Breakout exit semantics](issues/10-t4-exits.md) — blocked by Existing Pre-Breakout behaviour review; design owner available; owner: Kenneth decision / agent design.
11. [Plan a reproducible Pre-Breakout backtest slice](issues/11-t4-backtest.md) — blocked by 10 t4-exits approval; owner: agent design / implementation candidate.
12. [Plan per-horizon Pre-Breakout tuning and validation](issues/12-t4-tuning.md) — blocked by T1 integration; implemented, code-audited and integrated Pre-Breakout backtest from the plan in 11 t4-backtest; owner: agent research / Kenneth operation.
13. [Plan Tradier-wide rate-limiter coverage](issues/13-tradier-governor.md) — blocked by Existing TG-1 in NLQ map; NLQ-3 clearance; owner: agent design.
14. [Verify P0 safeguards during market hours](issues/14-p0-live-check.md) — blocked by Merged P0A/P0B; authorized configured runtime; owner: Kenneth verification.
15. [Collect the second valid market-data measurement day](issues/15-measurement-day2.md) — blocked by Existing MEAS protocol and frozen inputs; owner: Kenneth operation.
16. [Verify real provider bar-source alignment](issues/16-bar-alignment.md) — blocked by Authorized real-data/provider access; owner: Kenneth operation / agent analysis.
17. [Plan truthful post-submit broker error handling](issues/17-broker-errors.md) — blocked by Coordinate with FIRE and active broker-path owners; owner: agent design.
18. [Decide and plan unresolved-save UX](issues/18-save-unconfirmed.md) — blocked by 17 broker-errors scope reconciliation; owner: Kenneth decision / agent design.
19. [Align deciding-driver descriptions on screen](issues/19-ui-driver-labels.md) — blocked by Reproduce current banner/tooltip behaviour; owner: agent plan.
20. [Correct regime-duration units](issues/20-ui-duration-labels.md) — blocked by Reproduce current duration calculation/display; owner: agent plan.
21. [Reconcile watchlist validation and refresh residuals](issues/21-watchlist-residuals.md) — blocked by EXACT-STRIKE owner coordination and overlap clearance; owner: agent discovery.
22. [Plan isolation of Heston cached results](issues/22-heston-cache.md) — blocked by Check current cache users and existing pricing audits; owner: agent design.
23. [Reconcile Heston fit and no-arbitrage residuals](issues/23-heston-evidence.md) — blocked by Existing pricing contracts and Heston cache overlap; owner: agent discovery / Kenneth decision.
24. [Plan bounded deep-YAML handling](issues/24-yaml-recursion.md) — blocked by Existing configuration integrity contracts; owner: agent design.
25. [Decide disabled end-to-end coverage](issues/25-disabled-e2e.md) — blocked by Current disabled-spec review; owner: Kenneth decision / agent plan.
26. [Reproduce and isolate remaining flaky tests](issues/26-flaky-tests.md) — blocked by Exact current-main baseline and runtime; owner: agent evidence.
27. [Decide RANK-basis end-to-end coverage](issues/27-rank-coverage.md) — blocked by Current coverage inventory; owner: Kenneth decision / agent plan.
28. [Execute approved remote-branch cleanup safely](issues/28-branch-cleanup.md) — blocked by Current ancestry/ownership review and existing cleanup authorization; owner: Kenneth operation / agent verification.
29. [Decide remaining historical audit-checker gap](issues/29-state-probe-policy.md) — blocked by Current checker reproduction; completed Lane C preserved; owner: Kenneth decision / agent analysis.
30. [Reconcile trade-card follow-up release status](issues/30-trade-card-release.md) — blocked by Follow-up 55e08e55 and current main comparison; owner: agent release verification.
31. [Resolve existing exact-strike migration choices](issues/31-exact-strike-decisions.md) — blocked by Existing EXACT-STRIKE owner available (NLQ integration blocks implementation, not these decisions); owner: Kenneth decision / existing owner.
32. [Reconcile remaining position risk-boundary races](issues/32-position-risk-residuals.md) — blocked by FIRE H2 and broker-path ownership clearance; owner: agent discovery.
33. [Reconcile non-finite numeric API inputs](issues/33-numeric-api-residuals.md) — blocked by Current schema and existing numeric audit inventory; owner: agent discovery.
34. [Reconcile per-channel watch delivery and stuck-alert policy](issues/34-watch-delivery-residuals.md) — blocked by Existing completed resend phases and live-owner check; owner: agent discovery / Kenneth decision.
35. [Assess the remaining IV-score discontinuity](issues/35-iv-score-residual.md) — blocked by Existing scoring contracts and calibration decisions; owner: agent research / Kenneth decision.
36. [Specify delisted-universe and survivorship evidence expansion](issues/36-universe-bias.md) — blocked by HISTORY completed scope; data availability; owner: agent research / Kenneth decision.
37. [Decide intraday/VWAP tuning expansion](issues/37-intraday-scope.md) — blocked by Accepted daily-only tuning scope and new evidence proposal; owner: Kenneth decision / agent research.
