# WATCH-RESEND-HEAD-OF-LINE, piece 1: skip on proof — plan (v2; round 3 NOT clean 0B/2S/10N, all addressed)

- **Phase:** `WATCH-RESEND-HEAD-OF-LINE`, now piece 1 of 3 (decision `WATCH-RESEND-SPLIT-2026-10-02`).
  Pieces 2 (`WATCH-RESEND-EXPIRY-ON-REENABLE`) and 3 (`WATCH-RESEND-PER-CHANNEL`) are separate phases,
  each with its own plan and rounds. The combined plan
  (`2026-10-01-watch-resend-head-of-line-plan.md`, v2) is superseded; its rounds 1-2 count on this phase,
  and Kenneth gave this piece three fresh plan rounds (cap after round 5).
- **Decisions:** `WATCH-RESEND-HEAD-OF-LINE-2026-10-01` (skip on proof, only after 3 failed runs, an
  outage drops nothing), as narrowed by `WATCH-RESEND-SPLIT-2026-10-02`: once the next alert of the
  watch gets through, the stuck one is DROPPED AT ONCE (ERROR log). No retry; nothing is ever delivered
  out of order. `WATCH-RESEND-QUEUE-2026-09-27` (queue, oldest first, Delayed label, disabled watches
  keep theirs) stays the rule otherwise.
- **Branch:** `claude/youthful-carson-82x23x`.

## 1. What is true on main (7ef06a0)

`backend/app/services/strategy_watch_evaluator.py`:

1. `evaluate_and_notify` (:781-797), under `_run_lock()`: `any_channel = _any_channel_enabled()`, then
   `_resend_pending(any_channel)`, then `_collect(...)`, then `_deliver_or_queue(t, any_channel)` for each
   transition.
2. `_resend_watch` (:727-748) walks `last_state.pending_events` oldest first. A malformed head is dropped
   (ERROR) and the walk continues. With `any_channel`, the first failed `_send` `return`s and keeps the
   queue as it is (nothing written). Each delivered entry: `committed = new_state`, written after every
   entry (at most one event sent-but-unwritten).
3. `_deliver_or_queue` (:763-779): with `t.pending` non-empty the new event is queued (`_queue`) and NOT
   sent. `t.pending`/`t.committed` come from `_collect`, which calls `list_watches()` after the resend
   pass (:550, :571), so they reflect the resend pass's writes.
4. `_send` (:717-724) returns `notify_enabled_channels(...)`'s single bool: True when at least one enabled
   channel delivered. An exception is "not delivered".
5. `_queue` (:195-206) appends and evicts the oldest above `_QUEUE_CAP = 20`, copying older entries as
   they are (extra keys survive). `_write_effective` (:142-151) rewrites only the newest entry's
   `new_state` and keeps its other keys.
6. The scheduler polls every `poll_hours` (default 4 h, `strategy_watch_scheduler.py:73`); a manual
   `/evaluate` runs the same `evaluate_and_notify`.

**The defect:** a queued alert that delivery always rejects (all channels fail on that message, every run)
stays at the head forever, and every later alert of that watch, stop hits included, waits behind it.

## 2. Design

### 2.1 Stored counters on a pending entry (backward compatible)

An entry `{"event", "new_state", "fired_at"}` gains two optional keys, absent on entries written by
today's code:

- `"failures": int` — counted failed runs as the head.
- `"last_failure_at": iso` — the time of the last COUNTED failure.

A failure of the head counts only if it is at least `_FAILURE_SPACING = timedelta(hours=1)` after
`last_failure_at` (absent, unparseable or non-string → counts; a naive datetime is read as UTC). Three
manual `/evaluate`s in a minute count once. A `last_failure_at` in the FUTURE (clock jump) counts as
absent, so the counter cannot freeze. Malformed values (`failures` not a non-negative int, bool
included) read as 0 / absent. Only the HEAD's counters are ever changed, on a COPY of the head entry (the real `list_watches` is a
shallow copy, so changing the entry in place would change the store's memory without a write).
Nothing run-local is stored.

No failure counts on a run whose notification config is unreadable (`read_notification_config` reports
not readable, or raises): that run is a known outage, and counting there would make every watch's head
eligible together after recovery. `evaluate_and_notify` computes `count_failures` once per run from the
same read `_any_channel_enabled` already makes.

Time comes from one helper `_utcnow() -> datetime` (aware UTC) so tests can patch it.

### 2.2 The head fails: count, then probe (in `_resend_watch`, notify path only)

When the head `h` fails to send:

1. If the failure counts (2.1): `h.failures += 1`, `h.last_failure_at = now`.
2. ELIGIBLE = `h.failures >= _UNDELIVERABLE_AFTER = 3` (after step 1; an already-eligible head that fails
   inside the spacing is still eligible — the probe does not need this run's failure to count). Not
   eligible → write the queue if it changed, stop this watch (today's behaviour plus the counter write).

WRITE RULE: whenever the walk changed the queue — counters, a malformed entry dropped, a head dropped —
the queue is written before the next send and before stopping (the existing write-after-every-entry
rule, :746-748).
3. Eligible, and an entry stands behind `h` → PROBE: send that next entry (labelled Delayed with its own
   `fired_at`). A malformed entry met here is dropped (ERROR, as at the head) and the next one is probed
   instead.
   - Probe DELIVERED → `h` is dropped: ERROR `"strategy-watch: undeliverable alert dropped for <id> after
     <n> failed runs; a later alert was delivered: <reason>"`. `committed = probe.new_state`; the queue
     becomes everything after the probe; written at once (before any further send — at most one event
     sent-but-unwritten). The walk then CONTINUES normally with the next entry as the new head (sent in
     order; its own counters start from what it has stored, normally none). No retry of `h`.
   - Probe FAILED → write the queue if it changed (counters, malformed drops), stop this watch. Nothing is
     dropped (an outage, or a second undeliverable alert right behind — see 4.1).
4. Eligible and NOTHING valid behind `h` (nothing at all, or only malformed entries, all dropped in step
   3) → write the queue if it changed, stop, and report the watch as PROBE-READY for this run (2.3). The
   stored queue is then exactly `[h]`, so `_effective_view` never sees a malformed tail.

Every entry is sent at most once per run.

### 2.3 A fresh event as the probe (in `_deliver_or_queue`)

`_resend_pending` returns the set of probe-ready watch ids (2.2 step 4). In `_deliver_or_queue`, for a
transition `t` whose watch is probe-ready and whose `t.pending` is exactly that one head:

- send `t.event` now (not labelled Delayed — it fired this run);
- delivered → drop the head (same ERROR line) and `_commit(t)` (writes `t.new_state` with no queue;
  `t.new_state` was evaluated from the head's `new_state`, so nothing is lost);
- failed → `_queue(t)` as today (behind the head; head counters already written).

A watch is probe-ready only from step 4, so a watch whose probe (an older queued entry) failed this run
is NOT probe-ready: its fresh transition is queued unsent behind `[h, P]`, as today. The 2.3 branch and
each `_deliver_or_queue` call in `evaluate_and_notify` get a per-watch `try`/ERROR log, so a failure
there cannot stop later watches' alerts (Q17).

Without this, a stop hit firing behind a stuck head would wait a full poll (4 h by default) to become the
probe. Any other transition behind a non-empty queue is queued unsent, exactly as today.

### 2.4 Unchanged

- `any_channel` False (nothing enabled) and `evaluate_all`: queues committed unsent, counters ignored.
- Unreadable config: `_any_channel_enabled` is True, every send fails, counters may count, probes fail —
  nothing is dropped (a probe must DELIVER to drop anything).
- `_queue`'s cap, disabled watches (not resent, keep everything), `notify_enabled_channels`, dispatch,
  routers, frontend.

## 3. Files

- `backend/app/services/strategy_watch_evaluator.py` (constants `_FAILURE_SPACING`,
  `_UNDELIVERABLE_AFTER`, helper `_utcnow`, counter helpers, `_resend_watch` returns probe-ready,
  `_resend_pending` collects it, `_deliver_or_queue` takes it, `evaluate_and_notify` wires it).
- New `backend/tests/test_watch_resend_skip_on_proof.py`. Existing resend tests stay unchanged and must
  still pass (`test_watch_undelivered_resend.py`, `test_p4b_watch_isolation_and_delivery.py`,
  `test_composite_watch_keyerror.py`, `test_strategy_watch_evaluator.py`, `test_strategy_watch_router.py`):
  they patch `{_EV}.notify_enabled_channels`, which this piece keeps.

## 4. Behaviour changes and residuals (stated)

- A queued alert that has failed on 3 runs at least 1 h apart is dropped the first time the next alert of
  the same watch is delivered after that. Everything behind it then flows in order.
- Cost Kenneth accepted: a stuck alert that would have gone through later is lost. In particular, a head
  that failed 3 spaced runs during an outage and fails once more at recovery while the alert right
  behind it delivers is dropped. This needs every channel to fail on the head and at least one to deliver
  the next alert in the same run.
- "Delivered" is today's single result: at least one enabled channel. Until piece 3, a probe delivered on
  Gmail drops a head even if Telegram never had either.
- In an outage, an eligible watch makes one extra send per run (the probe): at most 2 notify calls per
  watch per run instead of 1.

### 4.1 Residuals (logged, not fixed here)

1. Two undeliverable alerts in a row: the probe (the second) fails too, which reads as an outage; the
   watch stays blocked. Using another watch's delivery as proof would go beyond the decision's "the next
   alert"; logged as open question WATCH-RESEND-TWO-STUCK-IN-A-ROW for Kenneth (round 2 rated it gate).
4. A crash between a delivered probe and the drop write: the next run sends `h` again after the probe —
   out of order, and the probe is sent twice. This is the existing one-sent-but-unwritten window.
2. A send that timed out client-side may have delivered; it counts as failed (pre-existing).
3. Gmail SMTP has no timeout (pre-existing, `gmail.py`); a hung Gmail send blocks the run as today.

## 5. Tests (`backend/tests/test_watch_resend_skip_on_proof.py`)

Harness: the in-memory `_Store` of `test_watch_undelivered_resend.py` (:26-55, deepcopy) for most tests,
and test 1 ALSO on the real YAML store (its `list_watches` is a shallow copy, which catches in-place
mutation); `{_EV}.notify_enabled_channels` patched with a fake that decides and counts on the event's
REASON line in the body (head and probe can share a subject), `{_EV}._utcnow` patched, `{_EV}._any_channel_enabled` patched True,
`_collect` patched where a test needs a fresh transition.

1. Poison head + a queued entry behind it, delivery otherwise up: runs at t0, t0+1h, t0+2h → failures 1,
   2, 3; run 3 probes, probe delivered → head dropped, ERROR logged, committed = probe's new_state, queue
   empty. Runs 1-2 send the head only (the entry behind is never sent). *Kills probe-before-3 and
   drop-without-probe.*
2. Stored failures 2 and this run inside the spacing (not counted) → no probe; stored 2 and this run
   counted → probe. *Kills `>=` → `>` and off-by-one.*
2b. Stored failures 3, this run inside the spacing → still probes. *Kills "probe only when this run's
   failure counted".*
2c. Unreadable config for 3 spaced runs → failures stay 0 (and nothing sent is delivered); a `last_failure_at`
   in the future counts as absent.
3. Spacing: three runs within 10 minutes → failures 1; a run at +61 min → 2. *Kills spacing removed.*
4. Outage: every send fails for 6 spaced runs → failures reach 6, probes from run 3 fail, nothing dropped,
   committed state unchanged, order intact. *Kills dropping on a failed probe.*
5. After the drop, the walk continues: head poison, behind it A then B; A delivers as probe, B delivered
   in the same run, in order; queue empty.
6. Head drop then a NEW stuck head: behind the poison, entry P2 that also always fails → probe P2 fails →
   nothing dropped (residual 4.1-1 pinned as behaviour).
7. Fresh event as the probe: head alone with failures 3 (stored), run with a fresh stop hit → head send
   fails, the stop hit is sent unlabelled (no "Delayed"), delivered → head dropped, state = the stop hit's
   new_state, no queue. Fresh probe failing → queued behind the head, head counters as written. *Kills
   the 4-hour delay (2.3) and a Delayed label on the fresh probe.*
8. Head alone, eligible, no fresh event → only the head is sent; nothing dropped.
9. Malformed entry behind an eligible head is dropped and the following one is probed. `[h, P, M]` with P
   failing → M is not reached and stays (dropped when a walk reaches it); `[h, M]` with M malformed → M dropped and WRITTEN even though counters did not
   change, the watch is probe-ready, the stored queue is `[h]`, and the next run evaluates the watch.
9b. Eligible head, probe P that always fails, and a fresh stop hit in the same run → exactly two notify
   calls (h, P), the fresh event never sent, queue `[h, P, fresh]`, nothing dropped, committed unchanged.
   *Kills probe-ready on any eligible head / the length check dropped.*
10. Old-shape entries (no counters) and malformed counters (`"x"`, `-1`, `true`, unparseable
    `last_failure_at`, naive datetime) behave as 2.1 says.
11. Each entry sent at most once per run: count `notify_enabled_channels` calls per subject in test 1's
    run 3 and test 5.
12. `any_channel` False: an eligible head is committed unsent, no probe.
13. `_Store.raise_on(id, pred)` with `pred` matching only the drop write (`update_state` raises; `_write`
    swallows it) → the rest of the run continues; the next run re-sends at most the one entry.
15. A `_deliver_or_queue` raising for one watch → later watches' transitions are still delivered.
14. Counters survive `_queue` appends, the cap eviction of OTHER entries, and `_write_effective` on a
    single-entry queue (the head is also the tail).

Gates: backend pytest full; `python3 scripts/state.py` exit 0.
