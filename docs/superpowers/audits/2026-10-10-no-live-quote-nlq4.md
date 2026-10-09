# NO-LIVE-QUOTE NLQ-4 code audit

## Code round 1 — not clean, two gate findings

Fresh independent reviewer `/root/nlq4_audit1`; exact uncommitted frontend diff against `e92e8a30` and SHA-256 file manifest in `.scratch/no-live-quote/nlq4-reviewed.diff` / `nlq4-reviewed-files.json`. All added frontend files and tests included. Backend quote wire/recompute interactions traced. Independent baseline six NLQ cases passed; two additional race assertions failed. Reproduction retained as `.scratch/no-live-quote/nlq4-audit1-race-repro.test.tsx` outside the live suite.

1. Old card-open quote completing after a refused send-time quote overwrites fresh state: closed-market $9 becomes stale `Live mid: $1.00`, hiding warning. Fix: quote request generation so old open-time result cannot publish after fresh send probe.
2. User unticks during pending send-time fetch; captured closure still permits non-live order at $2.50. Fix: synchronously updated current confirmation ref, read after await.

Additional focused validation: 70 passed / 1 outdated same-contract identity assertion (helper now copies liveness onto card). This compatibility assertion is updated to verify preserved card data and copied liveness; not counted as a gate finding. No unrelated production fixes.

M9, M12, M13 caused named tests to fail. M14's isolated removal of the key comparison survived because the contract-change reset is redundant protection; removing both association and reset produced the intended A-confirms-B failure. Both results preserved; no false claim that the isolated comparison was caught. All original source bytes restored after mutations.

Round 2 must review only the two race fixes, their regression tests, and interactions. Overall feature remains not ready to merge.
