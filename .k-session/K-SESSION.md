# K-Session: P3a scan sizing & signal correctness

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Finish work package P3a (docs/superpowers/plans/2026-09-25-work-packages.md): plan round 3 clean,
frontend half built, plan item 12 (intraday regime-fetch refusal) built, code review until a round is
clean, PROJECT_STATE entry, merge to main. Plan: docs/superpowers/plans/2026-09-25-p3a-scan-sizing-signals-plan.md

## Status
Plan round 4 in review (Kenneth allowed it past the cap; B1/B2 answered and folded in)

## Done
- 29b548e plan after round 1 + decision P3A-UNMEASURED-TREND-REMOVE (on the old branch claude/wizardly-lovelace-cub58h)
- bdfe8b1 plan round 2 fix (pre-breakout pullback sends account_size/risk_pct explicitly)
- a2365a3 backend half: plan items 3-11 + item 8 (the 1% sizing fallback P3b handed over)
- c79bf96 old P3a branch merged onto main after P3b (c05971a); clean, backend 3383 passed / 1 skipped, state.py 0
- plan item 12 + decision P3A-INTRADAY-REGIME-FETCH-REFUSES-2026-09-25 recorded (this checkpoint)

## Next steps
- [x] Plan review round 3: NOT CLEAN (B1 item-12 condition misses YAML regime_gate; B2 risk_pct=0 -> 422). See plan 'Review log'.
- [x] Kenneth answered B1 (match the fire: gate/filter/sizing), B2 (0% stops with a message), round 4 allowed; all findings folded into the plan
- [ ] Plan review round 4 (fresh subagent); build only if clean
- [ ] Build item 12 (backend/app/routers/stock_scan.py `_process_stock` + `_analyze_core`, classify_stock_rejection) + tests
- [ ] Build frontend half: item 1 (scanSizingFromRisk, 4 paths), item 2 (min_stock_score PARAM_DEFS + default 35 + body), item 3 funnel "no data" line + direction_min_trend label
- [ ] Mutation checks per plan; full backend + frontend suites
- [ ] Code review rounds until clean
- [ ] PROJECT_STATE: phase P3A-SCAN-SIZING-SIGNALS (probe `failed_direction_unmeasured` in stock_scan.py), close finished entries with evidence
- [ ] Merge origin/main, rerun checks, merge --no-ff to main, push; `k_session.py finish`

## Blockers / open questions
- none open (state.py shows the hard-cap drift by design until round 4 is clean)

## Decisions
- Continue on claude/cool-allen-5ih4v0 (Kenneth), old P3a branch left as-is.
- Item 12 added to P3a (Kenneth): scan drops where the fire would refuse, only when the regime measurement is used (filter on or sizing on).
- B1: scan drops on YAML gate OR filter OR sizing (P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25).
- B2: 0% max loss stops the scan with a message (P3A-SCAN-RISK-ZERO-STOPS-2026-09-25).
- Round 4 allowed (P3A-PLAN-ROUND-4-ALLOWED-2026-09-25).
- Unmeasured trend -> removed, funnel "no data" (P3A-UNMEASURED-TREND-REMOVE).

## Conventions
- Commit messages: plain descriptive subject, prefixed with the package ("P3a build: ...", "State: ..."), `wip(k-session):` for checkpoints
- Branch: `claude/cool-allen-5ih4v0` (base: `main`); integrate base with `git merge`, never rebase/force-push
- Before pushing: `cd backend && .venv/bin/python -m pytest -q tests`; `cd frontend && npx tsc --noEmit && npx jest`; `python3 scripts/state.py` exit 0
- Rule: nothing is done until an adversarial round comes back clean; 3-round cap per stage.
- Touch only P3a-owned files (plan "Files touched").

## Notes for the next agent
- P3b residuals not ours: 25s event-loop block in routers/auto_trade.py (P6).
