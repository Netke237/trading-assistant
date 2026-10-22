# Code Audit Round 1 — DECISION-34-WATCH-DELIVERY-RESIDUALS

**Reviewer:** Subagent `d5e31692-f131-4831-a642-7d88c8bb2fc1`  
**Target:** `git diff origin/main..HEAD` on branch `board/decision-34-watch-delivery-residuals-ee173a25` (commit `923d34fa`)  
**Date:** 2026-10-21  
**Status:** CLEAN (0 gate findings)

## Scope Reviewed
- `backend/app/services/notifications/dispatch.py`
- `backend/app/services/strategy_watch_evaluator.py`
- `backend/tests/test_strategy_watch_router.py`
- `backend/tests/test_watch_resend_per_channel.py`
- `backend/tests/watch_notify_helpers.py`
- `docs/superpowers/PROJECT_STATE.json`

## Audit Verification Summary
1. **Gmail Recipient Check in `ready_channels` (`dispatch.py`):**
   - Correctly enforces `(gmail.get('to') or os.getenv('BAMENDJOU_GMAIL_TO', ''))`, aligning with `_send_channels`.
   - Prevents spurious send attempts and false-ready states when recipient address is missing.
2. **Cross-Watch Delivery Proof (`strategy_watch_evaluator.py`):**
   - `_apply_cross_watch_proof` correctly resolves pending stuck probes on proven channels across earlier watches.
   - Accurately marks stuck heads as `"dropped"` and increments probe failure counts when spaced.
   - Prunes queues via `_pop_complete` and persists updated state with `_write`.
   - Records `run.proven_watches.add(w_id)` so `_deliver_or_queue` re-reads fresh state from the store.
3. **Resend and Evaluation Engine Flow (`_resend_watch` & `_deliver_or_queue`):**
   - Immediate cross-watch proof execution when any channel delivers.
   - Defers stuck probes when channel is not yet proven, resolving them immediately if an earlier watch in the run delivered on that channel.
   - Outage safety verified: real outages drop no alerts; lone eligible heads without probes are not dropped.
   - M25 mutation pin verified: delivered probe clears stuck before subsequent entry.
   - M33 mutation pin verified: commit mode queues fresh events behind non-empty queues rather than committing directly.
4. **Test Hygiene and Gaps:**
   - 7 new focused unit tests (`test_17` through `test_23`) in `test_watch_resend_per_channel.py` pass cleanly.
   - `test_strategy_watch_router.py:176` patched with an enabled ready channel to ensure `notify.assert_not_called()` guards against unexpected deliveries.

## Gate Findings
GATE FINDINGS: 0
