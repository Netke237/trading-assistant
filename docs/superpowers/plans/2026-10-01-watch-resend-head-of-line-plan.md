# WATCH-RESEND-HEAD-OF-LINE — plan (v2)

Task id: `WATCH-RESEND-HEAD-OF-LINE` (PROJECT_STATE `task_backlog`). Decision:
`WATCH-RESEND-HEAD-OF-LINE-2026-10-01` (Kenneth: skip on proof; also expiry on
re-enable and per-channel partial delivery).

v2 answers plan round 1 (NOT CLEAN, 8 gate + 9 below-gate). Each changed rule
carries its finding number as `[R1-n]`.

## 1. The defect (verified on main 863f95a)

`backend/app/services/strategy_watch_evaluator.py`:

- `_resend_watch` (:727-748) walks `last_state.pending_events` oldest first and
  `return`s at the first failed `_send` (:738-741). A message a channel always
  rejects sits at the head forever; every later event of that watch — stop hits
  included — waits behind it.
- `_deliver_or_queue` (:763-779) never sends a new event while `t.pending` is
  non-empty.
- `_queue` (:195-206) evicts only above `_QUEUE_CAP = 20`.
- `notify_enabled_channels` (dispatch.py:90-130) returns one OR'd bool: a
  rejection cannot be told from an outage, and Gmail up + Telegram down counts
  as delivered (Telegram silently misses it, the state is committed).
- No expiry: a watch disabled for weeks sends weeks-old "Delayed" alerts when
  re-enabled — through EITHER enable route: `routers/strategy_watch.py:75-79`
  and `routers/composite_watch.py:148-152` [R1-1].

WATCH-RESEND-QUEUE-2026-09-27 (queue, oldest first, sent in order, Delayed
label; disabled watches keep theirs) stays the rule. This plan adds a way out
for an entry PROVEN undeliverable, makes delivery per channel, and expires
stale entries on re-enable.

## 2. Behaviour after the change

### 2.1 Dispatch: per-channel results (dispatch.py)

- Private `_send_channels(cfg, subject, plain, html, channels) -> dict[str, bool]`:
  the existing per-channel body of `notify_enabled_channels` (null/non-dict
  block = disabled; Gmail then Telegram; `dispatch(...)` unchanged), restricted
  to `channels` when given; returns `{channel: delivered}` for each channel it
  ATTEMPTED.
- `notify_enabled_channels(subject, plain, html) -> bool` keeps its contract
  and its config read (`load_notification_config()`; corrupt → `{}` → False):
  `return any(_send_channels(cfg, ...).values())` [R1-6]. Its callers are
  exactly alert_notifier.py:288 and scan_schedule_scheduler.py:96/:107 —
  unchanged behaviour (chart_alerts calls `dispatch` directly and is untouched)
  [R1-17].
- New `async def notify_channels(cfg, subject, plain, html, channels) -> dict`:
  public wrapper over `_send_channels` taking an ALREADY-READ cfg (the evaluator
  reads the config once per run) [R1-15].

### 2.2 Evaluator patch points stay in the evaluator [R1-7]

The evaluator keeps importing `read_notification_config` into its own namespace
(the existing tests patch `{_EV}.read_notification_config`) and gains:

- `_run_channels() -> tuple[dict, set[str]] | None` — reads the config through
  the evaluator's `read_notification_config`; `None` when unreadable or the
  reader raises; else `(cfg, enabled set)`. `_any_channel_enabled` keeps its
  exact contract and is re-expressed on it (test_p6_notification_config.py:107-116
  keeps passing unchanged).
- `_send(ev, cfg, channel, delayed_since) -> bool` — calls the evaluator-level
  name `notify_channels` (imported from dispatch) for one channel; an exception
  counts as not delivered (today's rule).

Tests that patch `{_EV}.notify_enabled_channels` are rewritten to patch
`{_EV}.notify_channels`: test_watch_undelivered_resend.py,
test_p4b_watch_isolation_and_delivery.py, test_composite_watch_keyerror.py
(:117, :238, :375), test_strategy_watch_evaluator.py (:394),
test_strategy_watch_router.py (:176). Each of those modules gets an autouse
guard fixture that patches `app.services.notifications.dispatch.send_gmail` and
`.send_telegram` with a mock that FAILS the test if called — so a missed patch
can never send a real message. (Not a global conftest guard: test_notifications
and test_alert_notifier exercise the real dispatch path with their own mocks.)

### 2.3 Stored entry shape (backward compatible)

A pending entry stays `{"event", "new_state", "fired_at"}` and gains optional
keys, absent on entries written by today's code:

- `"targets": [channel, ...]` — the channels enabled when the entry was queued
  [R1-16]. Absent → the current enabled set.
- `"delivered_to": [channel, ...]`, `"abandoned": [channel, ...]`.
- `"failures": {channel: int}`, `"last_failure_at": {channel: iso}`,
  `"proven": {channel: int}` — see 2.5.

Malformed values of these keys read as empty/absent; only a malformed
event/new_state drops an entry, when it reaches the head, as today (:733-734)
[R1-12].

REMAINING channels of an entry = (targets ∩ currently enabled) − delivered_to −
abandoned. COMPLETE = remaining empty. A channel enabled after an entry was
queued never receives it (no out-of-time-order old alerts on a newly enabled
channel) [R1-16]; disabling a broken channel completes everything waiting only
on it.

Nothing run-local (the "fresh" flag, run counters) is ever stored [R1-11].

### 2.4 Run order (evaluate_and_notify), under `_run_lock()`

1. `rc = _run_channels()`.
2. `transitions = await _collect(...)` — unchanged; evaluates enabled watches
   from their EFFECTIVE state. (Each watch makes either a non-event write via
   `_write_effective` or returns a transition, never both — :247-289,
   :469-498 — so evaluating before draining gives the same results as today's
   drain-first order.)
3. Each transition is appended to its watch's queue — `t.pending +
   [new entry with targets = enabled set]` written with `_write` — WITHOUT the
   cap [R1-3]; the new entry's position is remembered run-locally as fresh.
4. RE-READ `strategy_watch_store.list_watches()` [R1-2] (so the sustain clock /
   composite re-arm written by `_write_effective` in step 2, and step 3's
   appends, are what the drain starts from — never the `_collect` snapshot).
5. `_drain_watch(w, rc, run)` for every ENABLED watch with a non-empty queue,
   strategy and composite alike, including watches `_collect` skipped [R1-12].
   Disabled watches are not drained and keep their entries.
6. Apply the cap to what is LEFT in each queue (2.7) [R1-3].

`rc is None` (unreadable config): no sends, no counters touched; step 3 still
queues the new events; nothing commits — today's gating [R1-9].
Enabled set empty (nothing enabled): every entry of every enabled watch, queued
and fresh, is committed unsent oldest first, logged at WARNING — today's D3.

`evaluate_all` (no-notify path) runs steps 2-5 with "nothing enabled" semantics
(commit unsent), replacing `_resend_pending(any_channel=False)`; `_resend_watch`,
`_resend_pending` and `_deliver_or_queue` are deleted [R1-14].

### 2.5 Failures that count, the probe, and giving up [R1-4]

Per entry and channel the entry stores `failures[c]` (counted failures) and
`proven[c]` (runs in which `c` was shown to work while this entry failed).

- COUNTED FAILURE: a failed send of `e` to `c` counts only if it is at least
  `_FAILURE_SPACING = 1 h` after `e`'s previous counted failure on `c`
  (`last_failure_at[c]`) — three manual `/evaluate`s in a minute count once.
- PROBE ELIGIBLE: the head-on-`c` entry `h` fails on `c` and its `failures[c]`
  (including this run's failure, if it counted) is `>= _GIVE_UP_AFTER = 3` —
  the decision's "only after it has failed on 3 runs".
- PROBE: the next entry behind `h` still remaining on `c` is sent. Failed → `c`
  is blocked for this watch, nothing else changes (an outage stops here, every
  run, and drops nothing). Delivered → `h` is RETRIED once:
  - retry delivered → `h` delivered (the one ordering exception: the probe went
    first; both labelled Delayed with their own times);
  - retry failed → `h.proven[c] += 1` (at most once per run) and `c` STAYS OPEN
    for this watch: every later entry is delivered on `c` in order; only `h` is
    left outstanding on `c`. This is what stops a stuck alert from blocking a
    stop hit: from the 3rd counted failure on, the entries behind `h` go out in
    the same run.
- GIVE UP: when `h.proven[c] >= 2` (two separate runs, at least 1 h apart by the
  spacing rule, in which `c` delivered a later alert while `h` failed both
  before and after it), `c` is added to `h.abandoned`, logged at ERROR
  ("undeliverable on <c>: <subject>; later alerts on <c> were delivered").

A post-outage burst (Telegram 429 on the head right after recovery) therefore
cannot drop the head: it needs three spaced failures plus two separate runs in
which it failed on both sides of a successful send. Until it is given up, the
head keeps the committed state where it is (the effective state still moves
on, as today), and nothing behind it is held back on `c`.

### 2.6 `_drain_watch` — per channel, in order

Walk the entries oldest first. A malformed entry at the head is dropped (ERROR)
as today and the walk continues. Per channel `c`, run-local mode for this
watch: `open`, `blocked`. For each entry `e`, for each `c` in remaining(e):

- `blocked`, or `c` tripped by the run breaker (below) → skip.
- send `e` to `c` only, labelled Delayed with `e.fired_at` unless `e` is this
  run's fresh entry.
- delivered → add `c` to `e.delivered_to`; mark `c` delivered-this-run.
- failed → update `failures`/`last_failure_at` per 2.5; if `e` is probe
  eligible, run 2.5's probe/retry; otherwise `c` becomes `blocked`.

`c` never receives an entry while an earlier one is outstanding on `c`, except
after 2.5's probe has shown `c` works while that earlier entry failed.

RUN BREAKER [R1-8]: per channel per run, after `_BREAKER = 3` failures on `c`
with zero deliveries on `c` this run, no further sends go to `c` this run, for
any watch. In a Telegram-only outage a run therefore makes at most 3 Telegram
sends (≤ 30 s at telegram.py's 10 s timeout) however many watches are queued;
Gmail sends continue.

After each entry, the COMPLETE prefix is popped: `committed = popped.new_state`
(an entry abandoned on every target with no delivery is logged at ERROR as
dropped undeliverable). The watch is written after every entry whose
`delivered_to`/`abandoned` changed or that was popped (at most one entry
sent-but-unwritten, the existing guarantee); counter-only changes are written
once at the end of the watch's drain [R1-15]; `_write` stays guarded.

### 2.7 Queue cap

After the drain, a queue longer than `_QUEUE_CAP` drops its oldest entries
(committing their new_state, as `_queue` does today); the ERROR line names the
entry's `delivered_to`, so a partially delivered drop reads differently.

### 2.8 Expiry on re-enable [R1-1, R1-5, R1-13]

`_REENABLE_MAX_AGE = timedelta(days=5)` (named constant; Kenneth's value to
change). New `async def set_enabled_and_expire(watch_id, enabled) -> int | None`
in the evaluator: under `_run_lock()` it reads the watch's current `enabled`
(None → not found), calls `strategy_watch_store.set_enabled`, and only on a
disabled → enabled change drops the leading entries whose `fired_at` is older
than now − max age (oldest first, a prefix; unparseable → expired; a naive
datetime is read as UTC), commits the last dropped entry's new_state, logs each
at WARNING, writes once, returns the count. Holding the run lock means no run
can see the watch enabled before its stale entries are gone.

Both PATCH handlers — `routers/strategy_watch.py:75-79` and
`routers/composite_watch.py:148-152` — call it (404 on None) and return
`{"id", "enabled", "expired_alerts": n}`. frontend/lib/api.ts:828 and :846 type
the response without the extra key, which is ignored. The PATCH can wait for a
running evaluation; the run breaker bounds that wait.

## 3. Files

- `backend/app/services/notifications/dispatch.py`
- `backend/app/services/strategy_watch_evaluator.py`
- `backend/app/routers/strategy_watch.py`, `backend/app/routers/composite_watch.py`
- Tests: new `backend/tests/test_watch_resend_head_of_line.py`; the patch
  rewrites and guards of 2.2.

## 4. Tests (each must fail on main or on a named mutation)

1. Poison head, channel up, a stop hit queued behind it (clock injected):
   counted failures 1, 2 (runs ≥ 1 h apart) → stop hit still queued; run 3:
   probe = stop hit delivered, retry fails, proven = 1, stop hit delivered and
   not blocked; run 4 (≥ 1 h later) with a new entry: probe delivers, retry
   fails, proven = 2 → head abandoned, popped, committed = newest delivered
   entry's new_state, ERROR logged.
2. Counted failures 2 → no probe (kills `>=`→`>` the other way: 3 → probe).
3. Outage 10 runs: probes fail, nothing abandoned, proven stays 0, nothing
   committed, order intact.
4. Outage then recovery: head fails once, probe delivers, retry fails → proven
   1, head NOT abandoned [R1-4].
5. Retry after probe succeeds → head delivered, not abandoned.
6. Three `/evaluate`s within a minute → failures counted once.
7. Fresh stop hit as probe in the run it fires → delivered this run, not
   labelled Delayed; fresh flag absent from stored YAML.
8. Partial: Gmail delivers, Telegram fails → delivered_to=[gmail]; next run
   Telegram only (Gmail send count unchanged).
9. Telegram permanently broken: Gmail gets every new event in order each run;
   disabling Telegram completes them next run.
10. Channel enabled after queueing never receives the old entry.
11. Run breaker: 10 watches queued, Telegram down → exactly 3 Telegram sends,
    all Gmail sends made.
12. Composite with a queued entry re-arms (armed → idle via `_write_effective`)
    in the same run its head delivers → final state phase idle [R1-2].
13. Cap after drain: 20 queued + 1 fresh, channel recovers → all 21 delivered,
    nothing evicted [R1-3]; 25 left undelivered → 5 evicted, ERROR names
    delivered_to.
14. Unreadable config (also mid-run) → no sends, counters untouched.
15. Nothing enabled → all committed unsent; `evaluate_all` likewise.
16. Old-shape entries and malformed new keys behave as empty.
17. `notify_enabled_channels`: attempted channel fails → False [R1-6]; corrupt
    file → False; null block → other channel tried.
18. Expiry: 6 d / 4 d entries → 6 d dropped and committed, 4 d kept; already
    enabled → nothing; unparseable and naive fired_at; BOTH routers return
    expired_alerts; a run started while the PATCH holds the lock sees no stale
    entry [R1-5].
19. A write raising mid-drain → rest of the drain continues, at most one entry
    sent-but-unwritten.

Mutations to kill: spacing removed; give-up at proven 1; give-up without the
retry; probe without eligibility; `c` blocked after a proven run (stop hit held
back again); breaker removed;
drain from the `_collect` snapshot; cap before drain; `any(d)` for
`any(d.values())`; remaining ignoring targets; expiry outside the lock;
fresh label always Delayed.

## 5. Out of scope

Frontend display of queued alerts (logged follow-up). alert_notifier,
scan_schedule_scheduler and chart_alerts delivery (unchanged: the first two keep
`notify_enabled_channels`' contract, chart_alerts calls `dispatch` directly).
Telegram 429 `retry_after` handling in telegram.py.
