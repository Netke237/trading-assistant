# NO-LIVE-QUOTE NLQ-4 code audit

## Code round 1 — not clean, two gate findings

Fresh independent reviewer `/root/nlq4_audit1`; exact uncommitted frontend diff against `e92e8a30` and SHA-256 file manifest in `.scratch/no-live-quote/nlq4-reviewed.diff` / `nlq4-reviewed-files.json`. All added frontend files and tests included. Backend quote wire/recompute interactions traced. Independent baseline six NLQ cases passed; two additional race assertions failed. Reproduction retained as `.scratch/no-live-quote/nlq4-audit1-race-repro.test.tsx` outside the live suite.

1. Old card-open quote completing after a refused send-time quote overwrites fresh state: closed-market $9 becomes stale `Live mid: $1.00`, hiding warning. Fix: quote request generation so old open-time result cannot publish after fresh send probe.
2. User unticks during pending send-time fetch; captured closure still permits non-live order at $2.50. Fix: synchronously updated current confirmation ref, read after await.

Additional focused validation: 70 passed / 1 outdated same-contract identity assertion (helper now copies liveness onto card). This compatibility assertion is updated to verify preserved card data and copied liveness; not counted as a gate finding. No unrelated production fixes.

M9, M12, M13 caused named tests to fail. M14's isolated removal of the key comparison survived because the contract-change reset is redundant protection; removing both association and reset produced the intended A-confirms-B failure. Both results preserved; no false claim that the isolated comparison was caught. All original source bytes restored after mutations.

Round 2 must review only the two race fixes, their regression tests, and interactions. Overall feature remains not ready to merge.

## Code round 2 — not clean, one gate finding

Fresh independent reviewer (cloud board-worker session, general-purpose subagent applying bmad-review-adversarial-general), 2026-10-10. Exact scope: `845a8fea..25c2570e` on `step-7-trade-card/page.tsx` and `lib/__tests__/tradeCardOverride.test.ts` (845a8fea = e92e8a30 + `.scratch/no-live-quote/nlq4-reviewed.diff`, i.e. the tree round 1 reviewed), the new race regression cases in `step-7-trade-card/__tests__/no-live-quote.test.tsx`, and their interactions with the rest of page.tsx. Round 1's own repro plus the live file: 16/16 pass, so both round-1 races are fixed and pinned.

1. **NLQ4-R2-1.** Fix #1 (the quote request generation counter) increments at the top of the card-open effect, BEFORE the claimed-plan early return (`isOverrideAtRequest && requestedPlanKeysRef.current[symbol] === keyAtRequest`). An effect re-run that issues no request (e.g. an unrelated basket "Retry" bumping `recomputeTick` during a pending send probe) therefore supersedes the pending send probe. The probe's fresh non-live quote is then never published. The order is refused correctly, but the page keeps "Live mid: $1.00" and hides the closed-market warning and tick until a second click. That is round 1's gate symptom by a new path; reproduced with a scratch Jest test. Fix: increment only on runs that actually issue a request (below the early return); add a regression case.

Not findings, checked: the confirmation ref never grants consent the visible state lacks; Prev/Next or A→B→A during a pending probe cancels the send; Place Limit and Place Market share one path and the basket sends nothing; StrictMode only over-refuses (fails safe); the `applyPickedContract` liveness-copy change does not alter any identity-dependent effect.

Round 3 (NLQ-4's last under the scoped cap) must review only the NLQ4-R2-1 fix, its regression test and their interactions.

## Between rounds 2 and 3 — fixes

- `252ec0c4` — NLQ4-R2-1: the card-open effect increments the quote generation only when it actually issues a request (below the claimed-plan early return). A regression case was added; it was red before the fix.
- `fa91d789` — the first full Jest run on the branch (never run by the building session) found three tests that pass on main and at `e92e8a30` but fail from `25c2570e` on:
  - (a) Step 6 Recommended: the all-non-live fallback `?? byScore[0]` could recommend a rescued card contract. This was a code regression, now fixed to `?? byScore.find(c => !rescuedIds.includes(c.id))`.
  - (b) `edited-fields-sync` quote mock: given `quoteLive: true`, as plan §3e requires.
  - (c) `direct-send-save-first` #11: now ticks the contract-keyed confirmation, as plan §3e requires.
  - (d) Raw cp1252 0x97 bytes in user-facing strings (`step-7-trade-card/page.tsx`, `lib/quoteWarning.ts`) restored to UTF-8 em dashes.
  - Result: full Jest 212 suites / 4804 tests, 0 failures; typecheck clean.

## Code round 3 — CLEAN (NLQ-4's last round under the scoped cap)

Fresh independent reviewer (cloud board-worker session, general-purpose subagent applying bmad-review-adversarial-general), 2026-10-10. Scope: `git diff 25c2570e fa91d789 -- frontend` (both fix commits) and their interactions. Checked:
- the generation counter on every quote path (claimed-plan early return, StrictMode re-run, the top early return, Prev/Next incl. A→B→A, basket Retry/recomputeTick; the send decision reads the fresh probe result, never React state);
- the Recommended pick vs the chain list, the auto-pick and the Step 7 hand-off (it equals main's rule plus the plan's live-first preference);
- that the two test edits add exactly the plan's preconditions and keep their invariants (no cross-contract quote; entry limit stored with a 0 scan mid);
- that no code matches on the restored strings.
6 suites / 122 focused tests pass. **0 gate findings. NLQ-4 closed clean at code round 3.**
