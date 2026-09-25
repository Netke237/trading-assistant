# K-Session: A5d — Step-5 scan failures show a readable message

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
Phase `A5D-STEP5-READABLE-SCAN-ERROR`. Step 5's `runScan` catch renders `String(e)`, so a
malformed saved `confidenceGate` shows "TypeError: Cannot read properties of null…". Build the
plan in `docs/superpowers/plans/2026-09-25-a5d-step5-readable-scan-error-plan.md`: a
pre-request failure shows `STOCK_SCAN_SETTINGS_INVALID`, a post-request failure shows
`stockScanFailureReason(e)`.

## Status
CLEAN at code round 4, status `shipped`, and state.py exits 0. Waiting on Kenneth's go to merge to main.

## Done
- c0937ad, c44e867, 956ad65: the A5d plan and its round-1 record, written on `claude/peaceful-ritchie-b59i77`.
- f319592: those commits merged onto main 489202d on this branch. The conflict in PROJECT_STATE.json was resolved by adding the A5d phase and the two A5d decisions to main's state. state.py exits 0.
- A previous session got further than this. It ran a clean plan round 2, built the change, wrote a 5-test file (17/17 green alongside the A5b suite) and started mutation checks. None of that was pushed and the container is gone, so it is **lost** and has to be redone.

## Next steps
- [x] Plan round 2: not clean, findings [R2-1..R2-10] folded into the plan.
- [x] Plan round 3: not clean, findings [R3-1..R3-5] folded in. Cap reached.
- [x] Kenneth decided: build now (decision A5D-BUILD-AFTER-PLAN-CAP-2026-09-25).
- [x] Build per plan §2. Add `STOCK_SCAN_SETTINGS_INVALID` to `frontend/lib/stockScan.ts`. In `frontend/app/(frame)/screener/step-5-strategy/page.tsx` `runScan`, add a `reachedRequest` flag, the catch mapping, and `console.error` for pre-request failures.
- [x] Tests T1–T5 in `frontend/app/(frame)/screener/step-5-strategy/__tests__/a5dReadableScanError.test.tsx`. Reuse the harness in the sibling `a5bSharedRequest.test.tsx`.
- [x] Mutation checks M1–M7 (plan §3). Each one must turn a test red, then be reverted.
- [x] Switch the phase's verify from `defect_marker` to a presence probe on `STOCK_SCAN_SETTINGS_INVALID` in the page. Set status to built.
- [x] Code audit round 4: CLEAN. Nits folded in; T5 now also checks navigation. Was: code audit round 4 (fresh subagent) on `git diff origin/main -- frontend/`, repeated until clean. The code stage allows rounds 4 to 6. When it is clean, set status `shipped` and `audit_clean: true`.
- [ ] Merge to main (`--no-ff`, with the main merge record written on the branch first), then `k_session.py finish`.

## Blockers / open questions
- None. The final message wording is "…(this also resets your broker accounts, regime and gate settings)." Kenneth re-chose it after round 2 showed that "scheduled scans" was false.

## Decisions
- A5B-KEEP-MAIN-2026-09-25: main's A5b stays. The other branch's A5b is archived at `archive/peaceful-ritchie-a5b-4796924`.
- A5D-READABLE-MESSAGE-2026-09-25: the fix is a readable message, on Step 5 only. There is no fallback to scanning without a gate, and no hydration repair (that one is logged).
- The message points at the Settings footer Reset, not Settings → Scan, because the Scan form crashes on the same null gate.
- This task is rebuilt on `claude/ecstatic-planck-qi9c39` (this session's assigned branch), not on peaceful-ritchie.

## Conventions
- Start with `python3 scripts/state.py`, which must exit 0. `docs/superpowers/PROJECT_STATE.json` is the single source of truth, so update the phase note there after every step.
- Commit style: descriptive subject prefixed with the phase (e.g. `A5d plan round 2: clean`, `A5d: …`). `wip(k-session):` is only for checkpoints.
- Before committing: `cd frontend && npm run typecheck && npx jest`. The backend is untouched.
- Integrate main with `git merge`. Never rebase or force-push.
- Nothing counts as done until an adversarial round comes back clean.

## Notes for the next agent
- Step-5 `runScan`'s catch is around page.tsx:246 on main 489202d.
