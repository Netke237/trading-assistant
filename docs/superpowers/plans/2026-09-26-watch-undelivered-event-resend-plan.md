# WATCH-UNDELIVERED-EVENT-RESEND — plan r1

Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § "P4b follow-ups" → WATCH-UNDELIVERED-EVENT-RESEND
(item 3 of decision `P4B-FOLLOWUPS-2026-09-26`). Branch `claude/unclaimed-tasks-xb6tiz`. Claim
`WATCH-UNDELIVERED-EVENT-RESEND`.

## The defect

P4b T3 (decision P4B D3) made `evaluate_and_notify` commit a fired transition's state only once
`notify_enabled_channels` reports delivered. An undelivered transition is **not stored anywhere**: the state is
left as it was and the next run re-derives the event from live data. On the `eod` schedule the next run is the next
day, so an `exit_stop`/`exit_target` whose close reverted overnight is never alerted and the watch stays `armed`
(blocking new entries until stop/target/reversal). Defect marker in `strategy_watch_evaluator.py`: the log text
`state kept, retries next run`.

## Kenneth's decision (do not re-ask)

`P4B-FOLLOWUPS-2026-09-26` (3): store the undelivered event and resend it on the next run **even if the price
recovered**, labelled delayed. Work-package wording: persisted with the watch (e.g. `last_state.pending_event`),
re-sent on the next run **before** re-evaluation, labelled "Delayed: <event> at <price> on <time>"; its state
transition commits once the resend is delivered. No channel enabled = unchanged D3 behaviour (commit).

## Files

Owned: `backend/app/services/strategy_watch_evaluator.py`, `backend/tests/test_watch_undelivered_resend.py` (new),
`backend/tests/test_p4b_watch_isolation_and_delivery.py` (update the tests that pin the old retry-by-re-derive
behaviour). `strategy_watch_store.py` needs **no change**: `update_state` stores
`{**_fresh_state(), **new_state}`, so an extra `pending_event` key persists through YAML as-is and a later
`update_state(new_state)` without it drops it.
Do not touch: `notifications/dispatch.py` (P6), frontend (see §7).

## 1. Stored shape

On an undelivered send (channel enabled, `delivered` False or the send raised), the watch's **current** state is
kept and one key is added:

```python
last_state["pending_event"] = {
    "event":     asdict(WatchEvent),   # all fields, JSON/YAML-plain (str/float/None)
    "new_state": t.new_state,          # the transition's target state, committed on delivery
    "fired_at":  "<UTC ISO>",          # when the transition fired (first attempt)
    "attempts":  1,                    # incremented on every failed resend
}
```

Written with `strategy_watch_store.update_state(watch_id, {**current_state, "pending_event": {...}})`, where
`current_state` is the `last_state` the watch had when `_collect` read it, **plus** any non-event write `_collect`
made in that run (none can coincide with a fired event today: the sustain-clock writes and the composite
armed→idle write all `return None`). So `current_state` = the `last_state` from the `list_watches()` snapshot `_collect`
used. `_Transition` gains `old_state: dict` (set by both `_eval_*` functions from the `state`/`watch_state` they read
before building the event) so the notify loop does not re-read the store.

A failed `update_state` here is logged at ERROR and the run continues; the watch then behaves as today (re-derive
next run). Nothing worse than today.

## 2. Run order in `evaluate_and_notify` (under the existing `_run_lock`)

1. `any_channel = _any_channel_enabled()` — read once, first.
2. **Resend phase.** For every **enabled** watch (both kinds) whose `last_state.pending_event` is present, in
   store order:
   - Malformed (`pending_event` not a dict, or `event` / `new_state` not dicts, or `WatchEvent(**known fields)`
     raises): log ERROR, drop it (`update_state(id, state without pending_event)`), and let phase 3 evaluate the
     watch normally. A corrupt entry must never freeze a watch forever.
   - No channel enabled: commit `new_state` (D3 parity — nothing could ever deliver). No send.
   - Otherwise send `_format_event(ev, delayed_since=fired_at)` (§3). Delivered → `update_state(id, new_state)`
     (this also removes `pending_event`). Not delivered / raised → `update_state(id, {**state, pending_event with
     attempts+1})`, log WARNING `"... still undelivered after N attempt(s); pending, resent next run"`.
   - The resent event is appended to the run's returned list with `delayed=True` (§4).
3. **Evaluate phase.** `_collect(...)` as today (it calls `list_watches()` afresh, so a watch whose resend was
   delivered is evaluated from its **committed** state in the same run — a follow-on transition, e.g. the exit
   after a delayed entry, is sent after the delayed one: oldest first). **`_collect` skips every watch that still
   has a `pending_event`** (both loops, right after the `enabled` check). This is the answer to "a new transition
   while an event is pending": it cannot happen. A watch is frozen at its pre-event state until its event is
   delivered; while no channel delivers, a second event could not be delivered either, and re-deriving it would
   only duplicate/contradict the stored one. The skip also skips that watch's sustain-clock and composite
   armed→idle writes — correct, since they belong to a state the watch has not reached yet.
4. **Send phase** for the new transitions: as today, except the undelivered branch writes `pending_event` (§1)
   instead of only logging. The old log text `state kept, retries next run` is removed (defect marker).

Disabled watches: phase 2 skips them (consistent with `_collect`), the pending event stays stored and is sent,
labelled with its original time, when the watch is re-enabled. A removed watch takes its pending event with it.

`evaluate_all()` (no-notify path; no caller in `app/`, tests only): before `_collect`, commits every enabled
watch's pending `new_state` without sending (same as "no channel"), dropping malformed ones, so its "commits
without notifying" contract holds and it can never be frozen by a pending event.

## 3. Message format

`_format_event(ev, delayed_since: str | None = None)`. With `delayed_since` set:

- subject: `"Delayed: " + <normal subject>` → e.g. `Delayed: Stop hit: AAPL — Pullback EMA`.
- first plain line (before `ev.reason`):
  `Delayed: <label> at <ev.close> on <fired_at in MARKET_TZ, "%Y-%m-%d %H:%M %Z"> — not delivered when it fired;
  the condition may no longer hold.` where `<label>` is the same label the subject uses (`Long setup`,
  `Stop hit`, …). An unparseable `fired_at` prints the raw string.
- html: the same line, escaped, as a plain line after the bold subject (Telegram tag allowlist unchanged).
- The rest of the body is unchanged. Without `delayed_since` the output is byte-identical to today (pinned).

## 4. `WatchEvent` and the `/evaluate` response

`WatchEvent` gains `delayed: bool = False` and `fired_at: str | None = None` (defaults → every existing
constructor and `asdict` consumer keeps working; `/evaluate` serialises with `asdict`, so the UI's `events` gain two
fields and `fired` counts resent events too). Reconstruction from storage filters to `WatchEvent`'s field names, so
an older/newer stored dict with extra keys still loads; the stored `delayed` is ignored and set True.

## 5. Tests (new file `tests/test_watch_undelivered_resend.py`, reusing the `_Store` / patch helpers pattern of
`test_p4b_watch_isolation_and_delivery.py`)

1. Undelivered exit_stop → state still `armed` **and** `pending_event.event.event_type == "exit_stop"`,
   `new_state.phase == "idle"`, `attempts == 1`.
2. **The defect:** next run, price back above stop (signal fn returns None, close > stop), notify True → exactly one
   send, subject starts `Delayed: Stop hit`, body contains the stored close and the fired time; state `idle`, no
   `pending_event`.
3. Resend fails again → `attempts == 2`, still armed, still pending; the watch is **not** re-evaluated (signal fn
   not called for it, no second pending written with a fresh event).
4. Delivered delayed entry followed by a same-run exit: pending entry (new_state armed, stop 101), current close 100
   → two sends, delayed entry first, then `exit_stop`; final state idle.
5. Composite undelivered entry → pending stored, phase idle; next run condition false (`evaluate_scheduled` False)
   → delayed entry still sent, state armed, then (following run) re-arms to idle as usual.
6. No channel enabled with a pending event → committed without sending (notify not awaited); pending gone.
7. Malformed pending (`"x"`, `{"event": "x"}`, `{"event": {...}, "new_state": None}`, event dict with a missing
   required field) → dropped, logged, watch evaluated normally that run.
8. Disabled watch with pending → not sent, pending kept; re-enabled → sent.
9. `evaluate_all` with pending → committed, not sent.
10. `_format_event` without `delayed_since` is identical to today's output for an entry and an exit (snapshot of
    subject/plain/html); with it, the subject prefix and first line are present and the html is escaped.
11. Other watches are unaffected: one watch pending + one normal firing watch → both handled in one run.
12. Pending-write failure (`update_state` raises for the pending write) → logged, run continues, other watches
    still committed.

Updated in `test_p4b_watch_isolation_and_delivery.py`: `test_undelivered_strategy_entry_keeps_state_and_retries`
(now: second run sends the **delayed** entry, subject prefixed), `test_undelivered_strategy_exit_stays_armed` and
`test_undelivered_composite_entry_stays_unarmed` (phase unchanged **plus** `pending_event` present),
`test_notify_raising_counts_as_undelivered` (pending stored). Their `== {"phase": "idle"}` equalities become
phase checks + pending checks.

Mutations to run after the build (each must fail ≥1 test): skip-pending line in `_collect` removed; resend phase
moved after `_collect`; commit on undelivered resend; `attempts` not incremented; "Delayed: " prefix removed;
no-channel branch sends instead of commits; malformed pending not dropped.

## 6. State file

Phase `WATCH-UNDELIVERED-EVENT-RESEND`: after build, the defect-marker pattern is gone → the probe flips to
BUILT; status → shipped only after a clean code round. The verify block stays `defect_marker` on
`state kept, retries next run`.

## 7. Out of scope / follow-ups to log

- UI: `/strategy-watch` could show "alert pending (N attempts)" per watch. Frontend is not in this package's owned
  files; logged as an open question.
- A pending event has no expiry: a watch disabled for weeks sends a weeks-old delayed alert on re-enable (labelled
  with its date). Accepted per Kenneth's "resend even if price recovered"; logged.
- `dispatch.py` corrupt-settings behaviour (a corrupt `settings.yaml` reads as "no channel" and commits) stays P6.
