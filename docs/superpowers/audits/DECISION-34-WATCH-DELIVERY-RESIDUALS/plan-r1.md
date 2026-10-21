# DECISION-34-WATCH-DELIVERY-RESIDUALS Plan Audit Round 1

- **Date:** 2026-10-21
- **Reviewer:** Fresh Independent Gate Auditor (`0085d9cc-f68c-4359-8c99-41fda1ce869e`)
- **Reviewed:** `docs/superpowers/plans/2026-10-21-decision-34-watch-delivery-residuals-plan.md@bbc005ed`
- **Result:** NOT CLEAN (4 gate findings)

### Findings
1. [FINDING-1] `StrategyWatchStore` has no `get_watch(w_id)` method in `_apply_cross_watch_proof`.
2. [FINDING-2] Stale snapshot in `_deliver_or_queue` corrupts persisted state and resurrects dropped heads.
3. [FINDING-3] `_deliver_or_queue` fails to record counted failure on new head when probe fails and head is dropped via cross-watch proof.
4. [FINDING-4] Plan Section 2.2 pseudocode for `_resend_watch` omits `stuck.pop(c)` on successful probe delivery.
