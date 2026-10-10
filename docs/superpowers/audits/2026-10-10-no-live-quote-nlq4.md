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
