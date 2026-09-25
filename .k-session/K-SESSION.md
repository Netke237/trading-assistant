# K-Session: P2 — premium stop, position editing & trade-card display

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Build work package P2 (see `docs/superpowers/plans/2026-09-25-work-packages.md`): 23 backlog entries + Kenneth's decisions Q6, Q7, Q8, Q9, Q15. Plan: `docs/superpowers/plans/2026-09-25-p2-premium-stop-position-editing-plan.md`.

## Status
BUILT, not yet code-audited. All 24 plan items built with tests; mutation checks done (see Done). origin/main (P3a, task claims, P3c decisions) merged in. Claim taken on P2-PREMIUM-STOP-POSITION-EDITING (scripts/claim.py). Full suites running; next: code round 1 (= round 6).

## Done
- fe495ca plan r0; c759fb1 r1 revisions (8 major/12 minor); 10630b7 r2 revisions (6 major/9 minor); 411d7e6 r3 revisions (2 major/7 minor, unaudited) — originally on `claude/quirky-pasteur-r1kt0v`, merged onto current main (which now carries P3b) in this branch.
- Baseline before any change (prior session, pre-P3b main): frontend 3680 tests, backend 3310 — both green. Re-baseline needed: P3b added backend tests.
- Kenneth's four answers recorded in plan section H.

## Next steps
- [x] PROJECT_STATE.json: phase P2-PREMIUM-STOP-POSITION-EDITING (audit_rounds 3, not clean, active_phase), decisions P2-*-2026-09-25, open questions Q-P2-1 + narrowed F2.
- [x] Plan rounds 4 and 5 (both not clean; Kenneth closed the plan stage and chose to build).
- [x] Re-baseline on main c05971a: frontend 3680, backend 3345 passed / 1 skipped.
- [x] Build per plan. One P1-owned TEST edited out of necessity: step-7 edited-fields-sync.test.tsx now reads the POSTED premiumStopDollar (P2-06 drops it from the synced row). No P1 app code touched.
- [ ] Code adversarial round 1 (= round 6; cap 3 code rounds, then ask Kenneth). Scope: `git diff origin/main HEAD` minus plan/state docs; gate-level only.
- [ ] Update PROJECT_STATE.json after each round (audit_rounds 4, ...); at the end close P2 backlog entries with evidence and set status shipped.
- [ ] Merge into main (--no-ff, state record written before the merge), then `k_session.py finish`.

## Blockers / open questions
- None blocking. Q-P2-1 logged-only (not built).

## Decisions
- P2, not P1 — the earlier "P1" mention was a typo.
- Q-P2-1: log only — relabel truthfully, no behaviour change.
- Q-P2-2: keep and show a cached typed dollar stop when the band offers none.
- Q-P2-3: sub-cent thresholds get a warning only; F2 stays open.
- 4th plan round allowed by Kenneth (one-off exception to the 3-round cap).

## Conventions
- Commit messages: repo style (`P2 plan …`, `P2 build: …`, `State: …`, `Merge: …`); `wip(k-session): …` for checkpoints.
- Branch: `claude/exciting-wozniak-dqdqy8` (base: `main`); integrate base with `git merge`, never rebase/force-push.
- Before pushing: `cd frontend && npm run typecheck && npm run test`; `cd backend && pytest`; `python3 scripts/state.py`.
- Rule: nothing is done until an adversarial round comes back clean.

## Notes for the next agent
- state.py's round probe cannot see P2 rounds 1-3 (they predate the entry's introducing commit); the count 3 is hand-recorded. Round 4's commit subject must say 'round 4' and PROJECT_STATE must declare 4 in the same commit.
- audit_rule (2): round 4 reviews only section G fixes + section H answers and their interactions, not the whole plan.
- P2 plan section E/F/G/H are cumulative revisions; read them all before building.
