# WATCH-UNDELIVERED-EVENT-RESEND — plan r2

Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § "P4b follow-ups" → WATCH-UNDELIVERED-EVENT-RESEND
(item 3 of decision `P4B-FOLLOWUPS-2026-09-26`). Branch `claude/unclaimed-tasks-xb6tiz`. Claim
`WATCH-UNDELIVERED-EVENT-RESEND`.

r2 = r1 + plan round 1's 17 findings (3 HIGH, 7 MEDIUM, 7 LOW) + Kenneth's decision D1 below, which replaces r1's
"freeze until delivered" design (round 1 finding 5). Findings are tagged `[r1#n]` where fixed.

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
  `float()` (None kept), `str()` on strings, `bool()` on `delayed` — so `yaml.dump` (the store uses `dump`, not
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
  ≥ 0 (else treated as 0 — coerced, not dropped); each invalid item is dropped with an ERROR log and sets
  `changed`.
- returns **new** dicts (never the snapshot's objects — `list_watches()` is a shallow copy, so the snapshot's nested
  dicts are the store's live objects) [r1#9].

Every read of the queue in the evaluator goes through `_pending`.

## 3. Writes keep the queue

Every `update_state` the evaluator makes goes through one helper, `_write_state(watch_id, new_state, queue)`:
writes `{**new_state, "pending_events": queue}` when `queue` is non-empty, else `new_state` without the key; logs
ERROR and returns False on any exception (never raises) [r1#2].

The queue a write must carry is **read from the store at write time** (`_current_queue(watch_id)` =
`_pending(<that watch's last_state in list_watches()>)[0]`), not captured on `_Transition` — so no `_Transition`
built without it (e.g. `test_p4b…:239-240`) can wipe a queue, and there is no stale-snapshot copy [r1#7].
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
   - No channel enabled → drop the queue (`_write_state(id, state, [])`), log WARNING listing the dropped event
     types (D3 parity: nothing could ever deliver). Nothing sent, nothing returned.
   - Otherwise send the entries **in order**, each with `_format_event(ev, delayed=True)` (§5); every attempted
     entry is appended to the run's returned list with `delayed=True`. Delivered → removed. **Stop at the first
     failure** (send returned False or raised): that entry's `attempts` becomes `attempts + 1` (a new dict), it and
     every later entry stay, in order. Then one `_write_state(id, state_without_queue, remaining)`.
   - Undelivered log: WARNING `"<watch> <event_type> for <symbol> still undelivered after N attempt(s); queued,
     resent next run"`; at N ≥ 3 the same line at ERROR [r1#14].
   - If a delivered entry's removal cannot be written (`_write_state` False), it is sent again next run — a
     duplicate, never a loss. The ERROR log says "may be re-sent" [r1#13].
3. **Evaluate phase.** `_collect(...)` unchanged in what it evaluates: it re-reads `list_watches()`, so it sees the
   flushed queues. **No watch is skipped because of a queue** (D1).
4. **Send phase** for each new transition `t`:
   - `queue = _current_queue(t.watch_id)`.
   - Queue non-empty (phase 2 could not empty it this run) → **do not send now**: append
     `{"event": _plain_event(ev), "attempts": 0}` and commit `t.new_state` with the longer queue. Oldest first is
     kept; the new event goes out after the older ones on the next run. Returned (not delayed).
   - Queue empty → send normally. Delivered, or no channel enabled → `_commit(t)` (queue stays empty).
     Undelivered with a channel enabled → commit `t.new_state` **with** `queue = [that event]`.
   - The state machine therefore always advances when an event fires (D1); only the message waits.
   - The log text `state kept, retries next run` is gone (defect marker); the `evaluate_and_notify` docstring is
     rewritten to describe the queue [r1#15].
5. Queue cap: `_MAX_PENDING = 50` per watch. Appending beyond it drops the **oldest** entry with an ERROR log naming
   it (a bound on YAML growth under a months-long outage; at one run per day that is ~2 months of transitions).

Returned list: every event **attempted or fired** this run, in send order: delayed resends first (flag True), then
new transitions (flag False). Events dropped because no channel is enabled are not returned. `/evaluate`'s `fired`
count therefore includes resend attempts [r1#12].

`evaluate_all()` (no-notify path; no caller in `app/`, tests only) sends nothing and leaves queues untouched; its
commits go through `_commit`, which carries the queue (§3).

Disabled watches: skipped by phase 2 (as by `_collect`); the queue stays and is sent, with its original times, when
re-enabled. A removed watch takes its queue with it.

## 5. Message format

`_format_event(ev, delayed: bool = False)` (the flag, not a separate time — the time is `ev.fired_at`).
With `delayed=True`:
- subject: `"Delayed: " + <normal subject>` → `Delayed: Stop hit: AAPL — Pullback EMA`.
- first plain line, before `ev.reason`:
  `Delayed: <label> — close <ev.close> (bar <ev.bar_time>), detected <ev.fired_at in MARKET_TZ as
  "%Y-%m-%d %H:%M %Z">. Not delivered at the time; the condition may no longer hold.`
  `<label>` is the subject's label (`Long setup`, `Short setup`, `Stop hit`, …). A missing `bar_time` omits
  `(bar …)`; an unparseable/missing `fired_at` prints `detected <raw or "unknown time">`.
- html: the same line, `html.escape`d, as a plain line after the bold subject (Telegram allowlist unchanged).
- With `delayed=False` the output is **byte-identical** to today, pinned by hard-coded expected strings copied from
  the current code before editing (not captured from the modified function) [r1#16].

## 6. Tests

New file `tests/test_watch_undelivered_resend.py`, same `_Store` / patch helpers as `test_p4b…` (copied). Signal stubs
are **direction-aware** — `side_effect=lambda bars, direction, **k: sig if direction == <wanted> else None` — so an
armed watch's opposite-direction (reversal) evaluation does not fire by accident [r1#3].

1. Undelivered exit_stop → state **idle** (D1: advanced) with `pending_events == [{"event": {... "event_type":
   "exit_stop", "fired_at": <str>, "bar_time": <str> ...}, "attempts": 0}]`.
2. **The defect:** next run, signal None and close back above the old stop, notify True → exactly one send, subject
   starts `Delayed: Stop hit`, body has the stored close, the bar time and the detected time; queue gone; returned
   `[exit_stop]` with `delayed is True`.
3. Resend fails again → `attempts == 1`, entry still queued, and the watch **was** re-evaluated (signal fn called).
4. **Lost-exit scenario (D1):** run 1 entry fires, undelivered → armed + queue [entry]. Run 2 channel still down,
   close ≤ stop → flush fails (attempts 1), `exit_stop` fires and is appended (not sent: notify awaited once in run 2),
   state idle, queue [entry, exit_stop]. Run 3 channel up → two sends, entry then exit_stop, both `Delayed:`; queue
   gone.
5. Queue non-empty + new transition + channel back in the same run: flush delivers → new transition sent
   normally after it (order: delayed entry, then exit_stop not delayed).
6. Flush stops at first failure: queue [a, b], notify `[False]` → b not attempted (notify awaited once), a
   attempts+1, order kept.
7. Composite undelivered entry → phase armed + queue [entry]. Next run `evaluate_scheduled` False → delayed entry
   sent, **and** phase already idle in the same run (re-arm), queue gone [r1#4].
8. No channel enabled with a queue → nothing sent (notify not awaited), queue dropped, not returned.
9. Non-event writes keep the queue: strategy sustain-clock start, strategy sustain reset, composite sustain start,
   composite armed→idle — each with a non-empty queue in the snapshot and flush failing → queue still present
   after the write.
10. Malformed values: `last_state="x"` (no raise, other watches handled), `pending_events` = `None` (fine), `{}`,
    `""`, `[ "x" ]`, `[{"event": "x"}]`, `[{"event": {<missing close>}}]`, `[{"event": {...}, "attempts": "x"}]`
    (coerced to 0, kept) → invalid dropped + ERROR logged, valid kept, watch evaluated normally.
11. Isolation: watch A's flush write raises (`update_state` side effect) → logged; watch B (queued) still flushed and
    sent; the run returns.
12. **YAML round-trip through the real `StrategyWatchStore(tmp_path/"w.yaml")`**: add a watch, `update_state` with a
    queue built by `_plain_event` from an event whose numbers are `numpy.float64` → new store on the same path loads
    the watch with an equal queue (and the file has no `!!python`). [r1#8]
13. `_format_event`: `delayed=False` equals hard-coded strings for one entry and one exit_stop; `delayed=True` has
    the prefix and the first line; html escapes a `<` in the reason.
14. Disabled watch with a queue → not sent, kept; re-enabled → sent.
15. `evaluate_all` with a queue and a firing transition → queue kept after the commit, nothing sent.
16. Cap: queue of 50 + one more undelivered → 50, oldest dropped, ERROR logged.
17. ERROR escalation at attempts ≥ 3 (caplog).

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
no-channel branch sends instead of dropping; malformed value not dropped; `_pending` without the `isinstance(dict)`
guard; `_plain_event` without `float()`; cap drops newest instead of oldest.

## 7. State file

- Phase `WATCH-UNDELIVERED-EVENT-RESEND`: the defect marker disappears with the build (probe → BUILT); status →
  shipped only after a clean code round. Name updated to the queue wording.
- Decision `WATCH-RESEND-QUEUE-2026-09-26` (D1) added.

## 8. Out of scope / follow-ups to log (open_questions)

- UI: `/strategy-watch` could show "N alert(s) waiting to send" per watch. Frontend is not owned here.
- A queued event has no expiry: a watch disabled for weeks sends weeks-old delayed alerts on re-enable (dated).
  Accepted per "resend even if price recovered".
- Partial delivery (one channel up, one down) counts as delivered — per-channel retry needs `dispatch.py` (P6).
- `dispatch.py` corrupt-settings behaviour stays P6.
