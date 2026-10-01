# WATCH-RESEND-HEAD-OF-LINE — plan

Task id: `WATCH-RESEND-HEAD-OF-LINE` (PROJECT_STATE `task_backlog`). Decision:
`WATCH-RESEND-HEAD-OF-LINE-2026-10-01` (Kenneth: skip on proof; also expiry on
re-enable and per-channel partial delivery).

## 1. The defect (verified on main 863f95a)

`backend/app/services/strategy_watch_evaluator.py`:

- `_resend_watch` walks a watch's `last_state.pending_events` oldest first and
  `return`s at the first failed `_send`. A message a channel always rejects
  therefore sits at the head forever, and every later event of that watch —
  stop hits included — waits behind it.
- `_deliver_or_queue` never sends a new event while `t.pending` is non-empty; it
  queues it behind the head.
- `_queue` evicts only above `_QUEUE_CAP = 20`, so the head clears only after 20
  more events of that one watch — in practice never.
- `notify_enabled_channels` (dispatch.py) returns one bool, so (a) a rejection
  cannot be told from an outage and (b) Gmail up + Telegram down counts as
  delivered: Telegram silently misses the alert and it is committed.
- A queued event has no expiry: a watch disabled for weeks sends weeks-old
  "Delayed" alerts the moment it is re-enabled.

Kenneth's earlier rule (WATCH-RESEND-QUEUE-2026-09-27) — queue, oldest first,
sent in order — stays the rule. This plan only adds a way out for an entry that
is PROVEN undeliverable, makes delivery per channel, and expires stale entries
on re-enable.

## 2. Behaviour after the change

### 2.1 Per-channel delivery (dispatch.py)

New `notify_channels(subject, plain, html, channels=None) -> dict[str, bool] | None`:

- reads the config with `read_notification_config()`; unreadable → returns
  `None` (caller: "do not know which channels exist; attempt nothing, keep
  everything" — the existing P6 rule that an unreadable file gates on delivery).
- for each ENABLED channel (`gmail`, `telegram`; null/non-dict block = disabled,
  same as today) that is in `channels` (or all when `channels is None`), calls
  `dispatch(...)` exactly as `notify_enabled_channels` does today, and records
  `{channel: delivered}`. Channels not attempted are absent from the dict.
- `notify_enabled_channels` becomes `any((await notify_channels(...)) or {})` —
  but it must keep reading the config the way it does now
  (`load_notification_config()`, corrupt → `{}` → nothing sent → False), so its
  three other callers (alert_notifier, scan_schedule_scheduler) see no change.
  Implementation: a private `_send_channels(cfg, subject, plain, html, channels)`
  shared by both; `notify_channels` passes the readable cfg or returns None.

New `enabled_channels() -> set[str] | None`: the enabled channel names, `None`
when settings.yaml is unreadable or the reader raises. `_any_channel_enabled`
keeps its exact contract (unreadable → True) and is re-expressed on it.

### 2.2 Stored entry shape (backward compatible)

A pending entry stays `{"event", "new_state", "fired_at"}` and gains two optional
keys, both absent on entries written by today's code:

- `"delivered_to": [channel, ...]` — channels that delivered this entry.
- `"abandoned": [channel, ...]` — channels on which this entry was given up as
  undeliverable (2.4).
- `"attempts": {channel: int}` — failed sends per channel.

Malformed values of these keys (not a list / not a dict / non-int counts) read
as empty — the entry is NOT dropped for them (only a malformed event/new_state
drops an entry, as today).

An entry's REMAINING channels = current enabled channels − delivered_to −
abandoned. An entry is COMPLETE when that set is empty. Using the current
enabled set means disabling a broken channel in Settings completes everything
waiting only on it.

### 2.3 One drain per watch per run (evaluate_and_notify)

Today: resend queues → evaluate → deliver new events. New order:

1. `channels = enabled_channels()`.
2. `_collect(...)` evaluates every enabled watch from its EFFECTIVE state
   (unchanged — effective state is the tail's new_state whether or not the queue
   was drained first, so evaluation results are identical to today's order).
3. Each new transition is appended to its watch's queue in memory, marked fresh
   for this run (fresh = first send is not labelled "Delayed").
4. `_drain_watch` runs once per enabled watch that has a non-empty queue
   (including ones only just given an entry). Disabled watches are not drained
   and keep their entries (decision WATCH-RESEND-QUEUE-2026-09-27 (b)).

Every entry is therefore attempted at most once per channel per run, and a
fresh event can be the probe of 2.4 in the same run it fired.

`channels is None` (unreadable config): no sends, no attempt counts, new
transitions are queued (written) and nothing is committed — today's gating.
`channels == set()` (nothing enabled): every entry, queued and fresh, is
committed unsent, oldest first, logged at WARNING per entry — today's D3 rule.

`evaluate_all` (the no-notify path) is unchanged: it commits the queue unsent and
then commits its transitions.

### 2.4 `_drain_watch` — per channel, in order, with skip on proof

Walk the entries oldest first. Per channel `c` keep a run-local mode:
`open` (send), `probing` (one or more earlier entries failed on `c` and each has
`attempts[c] >= _GIVE_UP_AFTER` = 3, counting this run's failure), `blocked`.

For each entry `e`, for each `c` in its remaining channels:

- `blocked` → skip `c` for the rest of this watch's drain.
- send `e` to `c` only (`notify_channels(..., channels={c})`), labelled Delayed
  with `e.fired_at` unless `e` is fresh this run.
- delivered → add `c` to `e.delivered_to`; if `c` was `probing`, every candidate
  `h` that failed on `c` this run gets `c` added to `h.abandoned`, logged at
  ERROR ("undeliverable on <c>: <subject>; a later alert on <c> was delivered"),
  and `c` returns to `open`.
- failed → `e.attempts[c] += 1`; then if `e.attempts[c] >= _GIVE_UP_AFTER` →
  `c` becomes (or stays) `probing` with `e` added to its candidates; else →
  `blocked`.
- result `None` (config became unreadable mid-run) or an exception from the
  send → treated as failed on `c` (the existing `_send` rule: an exception is
  not delivered).

Per-channel order is preserved: `c` never receives an entry while an earlier
entry is still outstanding on `c`, except as a probe — and a probe is only sent
after the earlier entry has failed on `c` on at least 3 separate runs.

Probing continues past consecutive failing entries only while each of them has
reached the threshold, so in a true outage the extra sends grow by at most one
entry per 3 runs per channel and are bounded by the queue length (≤ 20). In an
outage nothing is ever delivered on `c`, so nothing is abandoned on `c`.

After each entry is processed, the COMPLETE prefix of the queue is popped:
`committed = popped.new_state`; an entry abandoned on every remaining channel
with no delivery anywhere is logged at ERROR as dropped undeliverable. The watch
state is written after EVERY entry whose stored fields changed (at most one
entry sent-but-unwritten, the existing guarantee). A write failure is logged and
does not stop the drain (`_write` is already guarded).

A non-complete entry blocks commit of everything behind it, as today — the
committed state stays "before the oldest not-fully-delivered event", and
evaluation keeps running from the effective state.

### 2.5 Queue cap

`_queue`'s eviction above `_QUEUE_CAP` stays. Its ERROR line additionally says
which channels the dropped entry had reached (`delivered_to`), so a
partially-delivered drop is distinguishable from a never-delivered one.

### 2.6 Expiry on re-enable

`_REENABLE_MAX_AGE = timedelta(days=5)` (named constant; the value is Kenneth's
to change). New `async def expire_on_reenable(watch_id) -> int` in the
evaluator, run under `_run_lock()`: drops the leading entries whose `fired_at`
is older than now − max age (oldest first, so a prefix; an unparseable
`fired_at` counts as expired), commits the last dropped entry's `new_state`,
logs each at WARNING, writes once, returns the count.

`routers/strategy_watches.py` PATCH `/{watch_id}`: when the body enables a watch
that is currently disabled, call `expire_on_reenable` after `set_enabled`
succeeds, and return `{"id", "enabled", "expired_alerts": n}` (an extra key; the
frontend ignores unknown keys — verify `frontend/lib/api.ts`'s typing of this
response before relying on that). Enabling an already-enabled watch, or
disabling, expires nothing. No other path changes `enabled` (verify by grep).

## 3. Files

- `backend/app/services/notifications/dispatch.py` — `notify_channels`,
  `enabled_channels`, shared private sender.
- `backend/app/services/strategy_watch_evaluator.py` — entry fields,
  `_drain_watch`, new `evaluate_and_notify` order, `_queue` log, expiry.
- `backend/app/routers/strategy_watches.py` — PATCH calls the expiry.
- Tests: new `backend/tests/test_watch_resend_head_of_line.py`; existing
  `test_watch_undelivered_resend.py` / `test_p4b_watch_isolation_and_delivery.py`
  updated only where they patch `notify_enabled_channels` on the evaluator
  (the evaluator will call `notify_channels`); each such edit listed in the
  commit message.

## 4. Tests (each must fail on main or on a named mutation)

1. Poison head, channel up: head fails 3 runs (later entry queued behind it);
   run 3 sends the later entry as probe, it delivers, head abandoned, both
   popped, committed = later entry's new_state, ERROR logged.
2. Same but only 2 prior failures: no probe, later entry still queued.
3. Outage: everything fails for 10 runs → nothing abandoned, nothing committed,
   order intact; sends per run bounded as in 2.4.
4. Fresh event as probe in the run it fires (head at threshold, stop hit fires
   this run → delivered this run, NOT labelled Delayed).
5. Partial: Gmail delivers, Telegram fails → entry kept with
   delivered_to=[gmail]; next run sends to Telegram only (Gmail send count
   unchanged); on success popped and committed.
6. Telegram permanently broken, Gmail fine: Gmail receives every new event in
   order, run after run (no regression vs today), entries pile up only on
   Telegram; disabling Telegram in config completes them all next run.
7. Per-channel order: Telegram blocked on entry 1 never receives entry 2 before
   entry 1 (unless probe after threshold).
8. Old-shape entries (no new keys) and malformed new keys behave as empty.
9. Unreadable config: no sends, no attempts counted, new events queued.
10. Nothing enabled: everything committed unsent (D3 unchanged).
11. `notify_enabled_channels` unchanged for its other callers (corrupt file →
    False, null block → other channel tried).
12. Expiry: re-enable with entries 6d/4d old → the 6d one expired and
    committed, the 4d one kept; enabling an enabled watch expires nothing;
    unparseable fired_at expires; router returns expired_alerts.
13. Write after every changed entry (a write raising mid-drain leaves at most one
    entry sent-but-unwritten; the rest of the drain continues).
14. Queue-cap ERROR line names delivered_to.

Mutations to run and kill: threshold `>=` → `>`; probe without threshold;
abandon without a later delivery; drop the per-channel `channels={c}` filter
(would re-send to delivered channels); remaining = enabled − delivered only
(ignore abandoned); expiry `<` → `<=` on the age; fresh label always Delayed.

## 5. Out of scope

Frontend display of queued alerts (logged follow-up), composite-specific
delivery rules (composites already share this path), chart alerts and portfolio
alerts (they use `notify_enabled_channels`, unchanged).
