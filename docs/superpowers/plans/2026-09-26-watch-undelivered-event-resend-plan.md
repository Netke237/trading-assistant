# WATCH-UNDELIVERED-EVENT-RESEND — plan r3

Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § "P4b follow-ups" → WATCH-UNDELIVERED-EVENT-RESEND
(item 3 of decision `P4B-FOLLOWUPS-2026-09-26`). Branch `claude/unclaimed-tasks-xb6tiz`. Claim
`WATCH-UNDELIVERED-EVENT-RESEND`.

r2 = r1 + plan round 1's 17 findings (3 HIGH, 7 MEDIUM, 7 LOW) + Kenneth's decision D1 below, which replaces r1's
"freeze until delivered" design (round 1 finding 5). Findings are tagged `[r1#n]` where fixed.
r3 = r2 + plan round 2's 12 findings (0 CRITICAL/HIGH, 3 MEDIUM, 9 LOW), tagged `[r2#n]`.

## The defect

P4b T3 (decision P4B D3) made `evaluate_and_notify` commit a fired transition's state only once
`notify_enabled_channels` reports delivered. An undelivered transition is **not stored anywhere**: the state is
left as it was and the next run re-derives the event from live data. On the `eod` schedule the next run is the next
day, so an `exit_stop`/`exit_target` whose close reverted overnight is never alerted and the watch stays `armed`.
Defect marker in `strategy_watch_evaluator.py`: the log text `state kept, retries next run`.

## Decisions

- `P4B-FOLLOWUPS-2026-09-26` (3), Kenneth (do not re-ask): store the undelivered event and resend it next run even
  if the price recovered, labelled delayed.
- **D1 (asked this session, 2026-09-26, after plan round 1 [r1#5]) — QUEUE, KEEP WATCHING.** Kenneth chose:
  the watch moves to its new state straight away and keeps being evaluated; every alert that could not be sent
  waits in a per-watch queue and is sent oldest first, labelled "Delayed". This deliberately departs from the
  work-package wording "its state transition commits once the resend is delivered": under that wording a watch
  frozen through a multi-day outage never detects a stop that is hit and recovers during the outage. With the queue
  nothing is lost: entry (day 1, undelivered) → exit_stop (day 2, undelivered) → both sent in order on recovery.
  Recorded as decision `WATCH-RESEND-QUEUE-2026-09-26` in PROJECT_STATE.json.
- "Delivered" means what `notify_enabled_channels` returns: **at least one** enabled channel delivered
  (`dispatch.py:75-95`). With Gmail up and Telegram down the event counts as delivered and Telegram never gets it.
  D3-consistent; per-channel resend would need `dispatch.py` (P6) and is out of scope. [r1#17]

## Files

Owned: `backend/app/services/strategy_watch_evaluator.py`, `backend/tests/test_watch_undelivered_resend.py` (new),
`backend/tests/test_p4b_watch_isolation_and_delivery.py` (update the tests that pin the old behaviour),
`docs/superpowers/PROJECT_STATE.json`. `strategy_watch_store.py`: **no change** — `update_state` stores
`{**_fresh_state(), **new_state}`, so an extra `pending_events` key persists and a write without it drops it (a
round-trip test through the real store pins this, §6 test 12).
Do not touch: `notifications/dispatch.py` (P6), frontend (§8).

## 1. Stored shape

```python
last_state["pending_events"] = [          # oldest first; absent or [] = nothing pending
    {"event": {<WatchEvent fields, plain str/float/None/bool>}, "attempts": 0},
    ...
]
```

- `WatchEvent` gains `fired_at: str | None = None` (UTC ISO, set on **every** event when it fires — the single
  source of the time; there is no separate `pending_events[i].fired_at`) [r1#10], `bar_time: str | None = None`
  (`str(bars[-1]["time"])` of the bars the event was derived from) [r1#11], and `delayed: bool = False`.
  Defaults keep every existing constructor and `asdict` consumer working.
- The stored event dict is built by `_plain_event(ev)`: `asdict(ev)` with every numeric field passed through
  `float()` and every string field through `str()` — **only when not None; None stays None** (`direction`,
  `fired_at`, `bar_time` can be None) [r2#8] — and `bool()` on `delayed` — so `yaml.dump` (the store uses `dump`, not
  `safe_dump`; `load` uses `safe_load`) can never emit a `!!python/...` tag that would make the next `safe_load`
  fail and the store load empty. [r1#8]
- `attempts` = resend attempts that failed. The first (normal) send is not counted.

## 2. One reader for the queue [r1#1, r1#6]

`_pending(last_state) -> tuple[list[dict], bool]` returns `(valid_entries, changed)`:
- `last_state` not a dict (tests already use `"x"`, `test_p4b…:95`) → `([], False)` — never raises.
- key absent, `None`, `[]` → `([], False)`; any other non-list (`{}`, `""`, `"x"`, a dict) → `([], True)`, logged
  ERROR ("malformed pending_events dropped").
- each item kept only if it is a dict with a dict `event` from which `WatchEvent(**{k: v for k in fields})`
  constructs (unknown keys ignored, a missing required field → invalid) and `attempts` coerces with `int()` to
  ≥ 0, catching `(TypeError, ValueError, OverflowError)` (`.inf`/`nan` from `safe_load`) → 0 — coerced, not
  dropped [r2#9]; each invalid item is dropped with an ERROR log and sets
  `changed`.
- returns **new** dicts (never the snapshot's objects — `list_watches()` is a shallow copy, so the snapshot's nested
  dicts are the store's live objects) [r1#9].

Every read of the queue in the evaluator goes through `_pending`.

## 3. Writes keep the queue

Every `update_state` the evaluator makes goes through one helper, `_write_state(watch_id, new_state, queue)`:
writes `{**new_state, "pending_events": queue}` when `queue` is non-empty, else `new_state` without the key; logs
ERROR and returns False on any exception (never raises) [r1#2].

The queue a write must carry is **read from the store at write time** (`_current_queue(watch_id)` =
`_pending(<that watch's last_state in list_watches()>)[0]`; a watch id no longer in the store → `[]`, and the
`update_state` is a no-op for it anyway), not captured on `_Transition` — so no `_Transition`
built without it (e.g. `test_p4b…:239-240`) can wipe a queue, and there is no stale-snapshot copy [r1#7].
**A failed queue read never counts as an empty queue** [r2#2]: if `_current_queue` raises, that watch's write is
skipped (ERROR log "state not written; queue preserved") — the transition is then re-derived next run, as before
this package, which is a duplicate at worst, never a wiped queue. `_commit` wraps queue read + write in one
`try/except Exception`, so neither the `evaluate_all` commit loop nor the send loop can be aborted by it; the send
phase additionally wraps each transition's whole body (queue read, format, send, commit) in `try/except` (Q17).

This applies to:
- `_commit(t)` (event commits);
- the non-event writes inside `_eval_strategy_watch` / `_eval_composite_watch` (sustain clock start/restart/reset,
  composite armed→idle). Today they spread the snapshot's `state`, which already contains `pending_events` — so
  they preserve it. They are left as they are, **and** a test pins that each of them keeps a non-empty queue
  (§6 test 9). The event branches build fresh state dicts without the key, which is why `_commit` must merge.

## 4. Run order in `evaluate_and_notify` (under the existing `_run_lock`)

1. `any_channel = _any_channel_enabled()` — once, first.
2. **Flush phase.** For every **enabled** watch (both kinds), inside a per-watch `try/except Exception:
   logger.error(...); continue` (Q17) [r1#2]:
   - `queue, changed = _pending(last_state)`. Empty → if `changed`, `_write_state(id, state, [])` (drop the
     malformed value); next watch.
   - No channel enabled → **the queue is kept untouched** [r2#1]: nothing sent, no attempt counted, nothing
     returned, no write (except dropping malformed items when `changed`). Switching both channels off briefly
     (e.g. to rotate a token) must not delete a queued exit. When a channel is enabled again the queue is sent.
   - Otherwise send the entries **in order**, each with `ev.delayed = True` then `_format_event(ev)` (§5); every attempted
     entry is appended to the run's returned list with `delayed=True`. Delivered → removed. **Stop at the first
     failure** (send returned False or raised): that entry's `attempts` becomes `attempts + 1` (a new dict), it and
     every later entry stay, in order. Then one `_write_state(id, state_without_queue, remaining)`.
   - Undelivered log: WARNING `"<watch> <event_type> for <symbol> still undelivered after N attempt(s); queued,
     resent next run"`; at N ≥ 3 the same line at ERROR [r1#14].
   - **Give-up** [r2#11]: an entry whose `attempts` reaches `_MAX_ATTEMPTS = 10` is removed from the queue with an
     ERROR log that carries its full formatted subject and body (so the alert text is still in the log), and the
     run carries on with the next entry. Without this, one message a channel always rejects (e.g. a Telegram 400
     on that text) would hold back every later alert of that watch. With the `eod` schedule that is ~10 trading
     days of failed resends.
   - If a delivered entry's removal cannot be written (`_write_state` False), it is sent again next run — a
     duplicate, never a loss. The ERROR log says "may be re-sent" [r1#13].
3. **Evaluate phase.** `_collect(...)` unchanged in what it evaluates: it re-reads `list_watches()`, so it sees the
   flushed queues. **No watch is skipped because of a queue** (D1).
4. **Send phase** for each new transition `t`:
   - `queue = _current_queue(t.watch_id)`.
   - Queue non-empty (phase 2 could not empty it this run) → **do not send now**: append
     `{"event": _plain_event(ev), "attempts": 0}` and commit `t.new_state` with the longer queue. Oldest first is
     kept; the new event goes out after the older ones on the next run. Returned (not delayed).
   - No channel enabled → `_commit(t)` without queueing the new event (D3 unchanged: with no channel configured
     nothing is queued; only events that were queued while a channel was on are kept, per step 2).
   - Queue empty → send normally. Delivered → `_commit(t)` (queue stays empty).
     Undelivered with a channel enabled → commit `t.new_state` **with** `queue = [that event]`.
   - The state machine therefore always advances when an event fires (D1); only the message waits.
   - The log text `state kept, retries next run` is gone (defect marker); the `evaluate_and_notify` docstring is
     rewritten to describe the queue [r1#15].
5. Queue cap: `_MAX_PENDING = 50` per watch. Appending beyond it drops the **oldest** entry with an ERROR log naming
   it (a bound on YAML growth under a months-long outage; at one run per day that is ~2 months of transitions).

Returned list: every event **attempted or fired** this run, in send order: delayed resends first (flag True), then
new transitions (flag False). Queued events not attempted this run (no channel, or behind a failed head) are not
returned. `/evaluate`'s `fired` count therefore includes resend attempts, and a new event queued behind older ones is
returned once as not delayed and later again as delayed [r1#12, r2#10] — logged in §8 for the frontend wording.

`evaluate_all()` (no-notify path; no caller in `app/`, tests only) sends nothing and leaves queues untouched; its
commits go through `_commit`, which carries the queue (§3).

Disabled watches: skipped by phase 2 (as by `_collect`); the queue stays and is sent, with its original times, when
re-enabled. A removed watch takes its queue with it.

## 5. Message format

`_format_event(ev)` keeps its signature and reads **`ev.delayed`** — the one source of truth for "delayed"; the
time is `ev.fired_at` [r2#10]. With `ev.delayed` True:
- subject: `"Delayed: " + <normal subject>` → `Delayed: Stop hit: AAPL — Pullback EMA`.
- first plain line, before `ev.reason`:
  `Delayed: <label> — close <ev.close> (bar <ev.bar_time>), detected <ev.fired_at in MARKET_TZ as
  "%Y-%m-%d %H:%M %Z">. Not delivered at the time; the condition may no longer hold.`
  `<label>` is the subject's label (`Long setup`, `Short setup`, `Stop hit`, …). A missing `bar_time` omits
  `(bar …)`; an unparseable/missing `fired_at` prints `detected <raw or "unknown time">`.
- html: the same line, `html.escape`d, as a plain line after the bold subject (Telegram allowlist unchanged).
- With `ev.delayed` False the output is **byte-identical** to today, pinned by hard-coded expected strings copied from
  the current code before editing (not captured from the modified function) [r1#16].

## 6. Tests

New file `tests/test_watch_undelivered_resend.py`, same patch helpers as `test_p4b…` (copied), but its `_Store`'s
`list_watches` returns a **shallow** copy `[dict(w) for w in self.watches]` like the real store
(`strategy_watch_store.py:135-137`), and `update_state` stores a deep copy of what it is given, so an in-place
mutation of a snapshot's queue by the evaluator is visible as a store change without a write and fails the tests
(test 18) [r2#3]. Signal stubs
are **direction-aware** — `side_effect=lambda bars, direction, **k: sig if direction == <wanted> else None` — so an
armed watch's opposite-direction (reversal) evaluation does not fire by accident [r1#3].

1. Undelivered exit_stop → state **idle** (D1: advanced) with `pending_events == [{"event": {... "event_type":
   "exit_stop", "fired_at": <str>, "bar_time": <str> ...}, "attempts": 0}]`.
2. **The defect:** next run, signal None and close back above the old stop, notify True → exactly one send, subject
   starts `Delayed: Stop hit`, body has the stored close, the bar time and the detected time; queue gone; returned
   `[exit_stop]` with `delayed is True`.
3. Resend fails again → `attempts == 1`, entry still queued, and the watch **was** re-evaluated (signal fn called).
4. **Lost-exit scenario (D1)** [r2#6], per-run patches spelled out: run 1 — bars close 100, Bullish signal entry
   100 / stop 99 / target 110, notify `False` → armed, queue [entry], notify awaited 1. Run 2 — bars close 98,
   signal fn returns None for both directions, notify `False` → flush fails (entry attempts 1), `exit_stop` fires
   and is appended without a send (notify awaited 1 in this run), state idle, queue [entry, exit_stop]. Run 3 —
   bars close 105, signal None, notify `True` → notify awaited 2: entry then exit_stop, both subjects `Delayed:`;
   queue gone, state idle.
5. Queue non-empty + new transition + channel back in the same run: flush delivers → new transition sent
   normally after it (order: delayed entry, then exit_stop not delayed).
6. Flush stops at first failure: queue [a, b], notify `[False]` → b not attempted (notify awaited once), a
   attempts+1, order kept.
7. Composite undelivered entry → phase armed + queue [entry]. Next run `evaluate_scheduled` False → delayed entry
   sent, **and** phase already idle in the same run (re-arm), queue gone [r1#4].
8. No channel enabled with a queue → nothing sent (notify not awaited), queue **kept** (attempts unchanged), not
   returned; a new transition in the same run commits and is **not** queued. Then a channel is enabled → next run
   sends the kept entry as `Delayed:` [r2#1].
9. Non-event writes keep the queue: strategy sustain-clock start, strategy corrupted-`pending_entry_since`
   restart, strategy sustain reset, composite sustain start, composite sustain reset (`fired` False), composite
   armed→idle [r2#7] — each with a non-empty queue in the snapshot and flush failing → queue still present
   after the write.
10. Malformed values: `last_state="x"` (no raise, other watches handled), `pending_events` = `None` (fine), `{}`,
    `""`, `[ "x" ]`, `[{"event": "x"}]`, `[{"event": {<missing close>}}]`, `[{"event": {...}, "attempts": "x"}]`,
    `attempts` `.inf` and `nan` (all three coerced to 0, kept) [r2#9] → invalid dropped + ERROR logged, valid kept, watch evaluated normally.
11. Isolation [r2#5]: `_pending` is wrapped to raise for watch A's state only (outside `_write_state` and outside
    the send `try`) → logged; watch B (queued) still flushed and sent; the run returns. Plus: `update_state` raising
    for A's write → `_write_state` returns False, B still handled.
12. **YAML round-trip through the real `StrategyWatchStore(tmp_path/"w.yaml")`**: add a watch, `update_state` with a
    queue built by `_plain_event` from an event whose numbers are `numpy.float64` → new store on the same path loads
    the watch with an equal queue (and the file has no `!!python`). [r1#8]
13. `_format_event`: `delayed=False` equals hard-coded strings for one entry and one exit_stop; `delayed=True` has
    the prefix and the first line; html escapes a `<` in the reason.
14. Disabled watch with a queue → not sent, kept; re-enabled → sent.
15. `evaluate_all` with a queue and a firing transition → queue kept after the commit, nothing sent.
16. Cap: queue of 50 + one more undelivered → 50, oldest dropped, ERROR logged.
17. ERROR escalation at attempts ≥ 3 (caplog); give-up at attempts 10: entry removed, ERROR log contains its
    subject, the next queued entry is sent in the same run [r2#11].
18. Aliasing [r2#3]: flush fails and a new event is appended → between the evaluator's writes, the store's own
    objects are never mutated (the shallow `_Store` records its queue after each `update_state`; the recorded
    queues equal what was written, and the snapshot handed out before the run is unchanged).
19. Order [r2#4]: a shared recorder patched onto `notify_enabled_channels` and `get_bars` → the delayed send is
    recorded before the first `get_bars` call of the run.
20. Failed queue read [r2#2]: `list_watches` raises inside `_commit` for one transition → the stored queue is
    unchanged, ERROR logged, and the next transition still commits.
21. `_plain_event` with `direction=None`, `bar_time=None` → stays None; the delayed line omits `(bar …)` [r2#8].

Updated in `test_p4b_watch_isolation_and_delivery.py` (direction-aware stubs):
- `test_undelivered_strategy_entry_keeps_state_and_retries` → run 1: armed + queue [entry]; run 2 (notify
  `[False, True]`): returned `[entry]` with `delayed is True`, state armed, no queue, `notify.await_count == 2`.
- `test_undelivered_strategy_exit_stays_armed` → renamed `…_exit_goes_idle_and_is_queued`.
- `test_undelivered_composite_entry_stays_unarmed` → renamed `…_arms_and_is_queued`.
- `test_notify_raising_counts_as_undelivered` → queue stored.
- `test_a_failing_strategy_watch_skips_only_itself` unchanged (pins [r1#1]).

Mutations to run after the build (each must fail ≥ 1 test): `_commit` does not carry the queue; flush after
`_collect`; flush does not stop at first failure; commit without queue on undelivered; new event sent while queue
non-empty; `attempts` not incremented; "Delayed: " prefix removed; `delayed` flag not set on returned events [r1#12];
no-channel branch sends or drops the queue; malformed value not dropped; `_pending` without the `isinstance(dict)`
guard; `_pending` returns the snapshot's own list/dicts [r2#3]; `_plain_event` without `float()`; cap drops newest
instead of oldest; per-watch `try/except` in the flush removed [r2#5]; `_current_queue` failure treated as `[]`
[r2#2]; give-up threshold removed [r2#11].

## 7. State file

- Phase `WATCH-UNDELIVERED-EVENT-RESEND`: the defect marker disappears with the build; its `verify` then switches
  to a `present` probe on `def _pending\(` in `strategy_watch_evaluator.py` (a string's absence alone proves
  nothing) [r2#12]; status → shipped only after a clean code round. Name updated to the queue wording.
- Decision `WATCH-RESEND-QUEUE-2026-09-26` (D1) added.

## 8. Out of scope / follow-ups to log (open_questions)

- UI: `/strategy-watch` could show "N alert(s) waiting to send" per watch. Frontend is not owned here.
- A queued event has no expiry: a watch disabled for weeks sends weeks-old delayed alerts on re-enable (dated).
  Accepted per "resend even if price recovered".
- `/evaluate` `fired` now counts resend attempts, and the page says "N alert(s) fired"
  (`strategy-watch/page.tsx:72`) even when they were queued, not sent — needs "sent / queued" wording (frontend).
- A message that a channel always rejects is given up after 10 attempts (ERROR log with its text) [r2#11].
- Partial delivery (one channel up, one down) counts as delivered — per-channel retry needs `dispatch.py` (P6).
- `dispatch.py` corrupt-settings behaviour stays P6.
