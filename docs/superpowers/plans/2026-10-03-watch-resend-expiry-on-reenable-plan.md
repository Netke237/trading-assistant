# WATCH-RESEND-EXPIRY-ON-REENABLE

Own piece 2 of WATCH-RESEND-SPLIT-2026-10-02. Plan stage starts at round 1;
code stage starts after a clean plan. Each stage has a three-round cap.

## Behavior

`_REENABLE_MAX_AGE = timedelta(days=5)` in strategy_watch_evaluator.py.
Only a disabled -> enabled PATCH expires queued events; disabling or PATCHing
an already enabled watch does not change its state/queue. Both strategy-watch
and composite-watch PATCH routes return id, enabled, and expired_alerts (0
for an unchanged enable flag or a disable); missing ids retain each route's 404.
The existing strategy route continues to accept either watch type.

Use one UTC now for the change. Drop only the leading queue entries whose
fired_at is strictly older than now minus five days. Exactly five days old,
future timestamps, and newer entries stop the prefix; later entries retain
their content and order even if their timestamps are older. Naive timestamps
mean UTC; timezone offsets normalize through datetime comparisons. Missing,
non-string, or invalid timestamps count as expired. A malformed event counts
as expired, but its state is not trusted. For each dropped entry accepted by
the existing _parse_entry, advance committed state to its new_state; malformed
entries leave the last valid committed state intact. Store the retained queue
over that committed state, or remove pending_events when no entries remain.
No resend, market-data query, or notification happens in the PATCH. Log each
dropped entry at WARNING after successful persistence, identifying the watch
and fired_at. Expiration is an accepted loss of old undelivered notifications,
not a replay of their transitions.

## Atomicity and implementation

Add async set_enabled_and_expire(watch_id, enabled, *, store=None) in the
evaluator, using _run_lock() shared with evaluate_and_notify. Both routers pass
their actual imported store explicitly, so module reloads and existing router
test fixtures do not silently mutate a different singleton. Resolve the normal
evaluator store when called directly without an override.

Extend StrategyWatchStore.set_enabled with an optional on_reenable(state)
transform, called ONLY for false -> true under the store lock. Preserve its
bool found result and existing two-argument callers. The transform returns the
replacement last_state and does not mutate its input or queued entries. The
evaluator captures expired entries/count during that transform. Enabled and
last_state are written together with one save. Upgrade the lock to RLock and
hold it for the whole save (snapshot + serialization + atomic replace), so
concurrent store saves cannot replace the file with an older snapshot. Roll
back the watch in memory on a save failure and propagate the error; do not
enable the watch or report expiration after a failed state write. Existing
path=None in-memory stores remain supported. Do not use the evaluator's _write
helper, which logs and swallows persistence failures.

Put evaluate_all's complete resend/collect/commit sequence under the same
_run_lock(), since it is another public mutation path. Private helpers remain
unlocked and are called inside these top-level transactions. Neither PATCH
can race a pending drain or transition collected before re-enable. DELETE
continues using the store lock; it may remove a watch before the PATCH
transaction starts, yielding 404. This scope does not redesign notification
timeouts or make multi-process evaluation safe; keep the documented single
Uvicorn worker restriction.

## Tests and review

New test_watch_resend_expiry_on_reenable.py uses real temporary YAML stores,
patched UTC clock and no real data/notification calls. Pin both PATCH routes,
missing ids, false -> true only, five-day boundary, naive/offset/invalid/missing
timestamps, expired prefix with fresh tail (all payload/counter fields
retained), malformed entries with no state advancement, final valid dropped
state committed when queue empties, no-queue behavior, and disk reload parity.
Prove that persistence failure leaves both disk and memory disabled/unexpired
and returns an error, and that a PATCH waits for both evaluate_and_notify and
evaluate_all holding the shared run lock. Check two concurrent enable requests
expire exactly once. Count one save per update and assert warnings only after
successful expiration. Include a store save serialization probe if needed to
pin the older-snapshot race prevention. Mutation checks target omitted route
wiring, lost retained queue, wrong cutoff inclusivity, omitted enable-transition
guard, omitted locking, and swallowed persistence failures.

Run affected watch/store/router/resend suites and the existing backend suite,
plus frontend typecheck for the additive response field. No frontend behavior
change is required. Update the phase and audit_rounds/audit_clean in
PROJECT_STATE.json in the same commits as plan/code/audit updates. Each clean
audit must be an independent reviewer applying PROJECT_STATE.json's gate;
later rounds review only the preceding fixes and their interactions.

## Audit results

- Plan round 1: CLEAN, zero gate-level findings. Independent reviewer traced
  the complete plan against both routes, store persistence, scheduler and
  evaluator, including a second pass over failure and concurrency semantics.
- Code round 1 (overall round 2): CLEAN, zero gate-level findings on
  `94873792..7904d552`. Independent reviewer traced the complete implementation,
  including adjacent state writers, and independently ran all 32 new tests.
  No code fixes or further audit round required.
- Focused watch/store/router/resend suites: 111 passed. Frontend typecheck
  passed. First full run from the repo root: 4588 passed, 1 skipped,
  3 failed. Two cwd-dependent failures pass from backend; the remaining
  failure is pre-existing SHORTLIST-PREFIX-DRIFT (another branch owns it).
  Final integrated validation will run from backend.
- Six process-local mutants killed by the new tests: cutoff `>=` -> `>`,
  discard retained queue, omit false -> true guard, omit PATCH evaluation lock,
  swallow save failure, and bypass both PATCH routes' expiry helper. Mutation
  runs changed only isolated pytest-process function objects; repository source
  and running services were not mutated.
