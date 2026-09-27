# WATCH-UNDELIVERED-EVENT-RESEND — an undelivered watch alert is stored and re-sent — plan

Phase: WATCH-UNDELIVERED-EVENT-RESEND. Package: `2026-09-25-work-packages.md` §"P4b follow-ups", item 3.
Decision: P4B-FOLLOWUPS-2026-09-26 (3) — "store the undelivered event and resend it next run even if price recovered, labelled delayed".
Decisions taken 2026-09-27 (Kenneth), recorded as `WATCH-RESEND-QUEUE-2026-09-27`:
- (a) a new event on a watch that already has an undelivered one is **queued behind it; both are sent oldest first**; evaluation continues from the state the queued event leads to.
- (b) a **disabled** watch keeps its undelivered events; they are sent (labelled delayed, original time) if it is re-enabled. Deleting the watch deletes them.

Branch `claude/clever-planck-rpz8yh`, from main `e101c42`. One layer (backend), one build part, ~300 lines incl. tests.
Owned: `backend/app/services/strategy_watch_evaluator.py`, its tests. `strategy_watch_store.py` is NOT changed (see §1.1).
Do not touch: `notifications/dispatch.py` (P6 item 7), the frontend, `chart_alerts.py`.

## 0. Today (main `e101c42`)

`evaluate_and_notify` (`strategy_watch_evaluator.py:524-550`) runs `_collect` (evaluates every enabled watch from its
`last_state`, returns one `_Transition(event, watch_id, new_state)` per fired event), sends each event, and commits
`new_state` only if delivered or no channel is enabled (D3). Undelivered with a channel on: nothing is written, the log
says "state kept, retries next run", and the next run **re-derives** the event from live data.

Loss cases (all money-relevant):
1. Armed watch, close <= stop today, send fails. Tomorrow close > stop (reverted): no stop alert ever, watch stays armed,
   and its armed state blocks new entries until stop/target/reversal.
2. Idle watch, entry fires, send fails; tomorrow the setup is gone: the entry is never alerted.
3. Composite entry fires, send fails; next run the regime flipped: never alerted (composite is level-triggered).

## 1. Design

### 1.1 Stored shape — inside `last_state`, no store change

`last_state["pending_events"]`: a list (oldest first) of
```python
{"event": {<every WatchEvent field>}, "new_state": {<the state this event commits>}, "fired_at": "<UTC ISO>"}
```
- The **committed** state = `last_state` without `pending_events` (what the watch was before the oldest undelivered event).
- The **effective** state = `pending_events[-1]["new_state"]` if any, else the committed state — what the watch would be
  had every event been delivered. Evaluation always runs from the effective state (decision (a)).
- `strategy_watch_store.update_state` writes `{**_fresh_state(), **new_state}`, so an extra key survives the write and the
  YAML round-trip; `load()` only `setdefault`s. No store change, no migration: a watch without the key has no pending events.
- `new_state` never contains `pending_events` (it is a transition's own state, built by the evaluators).
- Serialisation: `_event_to_dict(ev)` = `dataclasses.asdict` with numeric fields passed through `float()` (None kept) and
  `str()` on text fields. `entry/stop/target/rr_ratio/close` come from strategy-engine signal objects; a numpy scalar in
  `yaml.dump` would write a `!!python/object` tag that `yaml.safe_load` rejects, and `load()` would then start with an
  empty watch list — the next `save()` would erase every watch. The coercion rules that out. `new_state` values
  (`entry_price` etc.) are already written to `last_state` today by `_commit`, so they are not a new exposure; they get the
  same coercion anyway via `_plain_state(new_state)` (floats for the three price fields).

### 1.2 Run order in `evaluate_and_notify` (under the existing `_run_lock`)

```
any_channel = _any_channel_enabled()
resent = await _resend_pending(any_channel)          # NEW, before any evaluation
transitions = await _collect(sustain_minutes, now_ts) # evaluates from the EFFECTIVE state
for t in transitions: _deliver_or_queue(t, any_channel)
```

**`_resend_pending(any_channel)`** — for each watch in `list_watches()` with a non-empty `pending_events`:
- disabled watch: skipped, events kept (decision (b)).
- walk the list oldest first. For each entry:
  - malformed (not a dict, `event` not constructible into `WatchEvent`, `new_state` not a dict): logged at ERROR with the
    watch id, dropped, the committed state unchanged by it, continue with the next.
  - `any_channel` false: not sent; `committed = entry.new_state`; logged at WARNING "dropped undelivered … (no channel
    enabled)". Same rule as D3 today: with no channel nothing can ever deliver, so the state moves on.
  - else send `_format_event(ev, delayed_since=fired_at)` via `notify_enabled_channels`; an exception counts as not
    delivered (as today). Delivered → `committed = entry.new_state`, next entry. Not delivered → stop the walk (order is
    kept: nothing newer is sent before an older one).
- ONE write per watch at the end: `committed` alone if the list is used up, else `{**committed, "pending_events": rest}`.
  Skipped when nothing changed (a failed first resend writes nothing).

**`_collect`** — unchanged except each watch is evaluated as `w_eff = {**w, "last_state": effective}`, and the evaluators'
non-event writes (strategy sustain clock at `:131/:147/:171`, composite re-arm `:309` and sustain clock `:324/:333`) go
through `_write_effective(w, state)` instead of `strategy_watch_store.update_state`:
- no pending → `update_state(w.id, state)` (exactly today's call);
- pending → `update_state(w.id, {**committed, "pending_events": pending[:-1] + [{**pending[-1], "new_state": state}]})`
  — the non-event change lands in the effective state, the committed state and the queue are untouched.
  Example: composite entry queued (effective armed); regime ends → re-arm to idle goes into the queued entry's
  `new_state`; when the entry is finally delivered the watch commits straight to idle, and a later re-entry queues a
  second entry — both alerts are true events.
`_Transition` gains `committed: dict` and `pending: list` (the snapshot the watch was evaluated with).

**`_deliver_or_queue(t, any_channel)`**:
- `t.pending` non-empty (its resend just failed or the watch is disabled — disabled watches are not evaluated, so this is
  the failed-resend case): **not sent**, appended: `{**t.committed, "pending_events": t.pending + [entry(t)]}` (order kept).
- else send `_format_event(ev)` (no delay label). Delivered, or no channel → `_commit(t)` (today's line). Not delivered →
  `update_state(id, {**t.committed, "pending_events": [entry(t)]})` and log WARNING "… not delivered; stored, re-sent next
  run" (the old "state kept, retries next run" text is gone — that string is the phase's defect-marker probe).
- `entry(t)` = `{"event": _event_to_dict(t.event), "new_state": _plain_state(t.new_state), "fired_at": _now_iso()}`.

**Queue cap:** 20 per watch. Appending a 21st first applies the oldest entry's `new_state` to `committed` and drops it,
logged at ERROR with its subject ("undelivered alert dropped, queue full"). Growth is at most one entry per run per watch,
so 20 is ~5 weeks of EOD runs of continuous failures with an event every run; the cap only bounds the YAML file.

**Writes are all through `update_state` under `_run_lock`.** A crash after a delivered resend and before its write re-sends
that event next run (a duplicate, never a loss) — the same window today's commit-after-send has.

### 1.3 Message text

`_format_event(ev, delayed_since: str | None = None)`. When `delayed_since` is set:
- subject: `"Delayed: " + <today's subject>`;
- first line of both bodies: `Delayed: <label> at <ev.close> on <fired_at in MARKET_TZ, "%Y-%m-%d %H:%M ET">`, then a
  blank line, then today's body unchanged. `<label>` is the subject label (`Long setup` / `Short setup` / `Stop hit` /
  `Target hit` / `Reversal`). Unparseable `fired_at` → the raw string is printed (never raises). HTML body escapes the
  line like the rest.
- Without `delayed_since` the output is byte-identical to today (pinned by test).

### 1.4 Other entry points

- `evaluate_all` (no production caller — only tests; the scheduler and `/evaluate` use `evaluate_and_notify`): runs
  `_resend_pending(any_channel=False)` first (commits the chain without sending), then collects and commits as today.
- `run_now` / `/evaluate` return value: still the events fired **this run** (new transitions, delivered or queued). Resent
  delayed events are not in it (they were returned when they first fired). Unchanged response shape.
- Frontend: `last_state.phase` shown on /strategy-watch is the committed phase, so a watch with a queued exit shows
  "armed" until the resend is delivered. Not changed here (frontend is out of scope); logged as a follow-up.

## 2. Tests — `backend/tests/test_watch_undelivered_resend.py` (new), using the `_Store` fake pattern of `test_p4b_watch_isolation_and_delivery.py`

1. **Case 1 (the defect):** armed strategy watch, close ≤ stop, send fails → `pending_events` has one `exit_stop`, committed
   phase still armed. Next run close > stop (reverted), send works → one "Delayed: Stop hit …" message sent, watch idle,
   no pending, and no second exit (the reverted price does not re-fire).
2. Case 2: undelivered entry, next run the signal is gone → delayed entry sent, watch armed with the entry's prices.
3. Case 3: undelivered composite entry, next run `evaluate_scheduled` → False → delayed entry sent; then re-arm to idle is
   applied in the same run (committed idle).
4. **Queue (decision (a)):** entry undelivered; run 2: resend fails AND close ≤ stop → exit_stop queued without a send
   attempt for it (notify awaited once in run 2); run 3 delivery works → two sends, entry then stop, both "Delayed:",
   final state idle.
5. Partial drain: two queued, first delivers, second fails → committed = first's new_state, one left.
6. Effective-state evaluation: pending entry (effective armed) + next run's close ≤ its stop → exit_stop is evaluated from
   the pending entry's prices (not from the committed idle state, which would fire a second entry).
7. Non-event write while pending: composite, queued entry, `fired=False` → the queued entry's `new_state.phase == "idle"`,
   committed state and queue length unchanged; strategy sustain clock the same (pending_entry_since lands in the tail).
8. No channel enabled with pending → nothing sent, chain committed, pending gone (D3).
9. Disabled watch with pending → nothing sent, pending unchanged; after `enabled=True` the next run sends it.
10. Malformed entry (`event` missing a field) → dropped with ERROR log; a valid entry after it is still sent.
11. Cap: 20 pending + one more → length 20, the oldest's new_state applied, ERROR logged.
12. `_format_event`: no-delay output equal to a golden string captured from today's code; delayed subject/first line;
    HTML escapes; bad `fired_at` printed raw.
13. YAML round-trip with the real `StrategyWatchStore` on a tmp path: numpy-float signal prices → stored pending entry
    reloads (`safe_load`) with every watch present.
14. A delivered first-time send commits as today and stores nothing (no `pending_events` key).

**Existing tests that pin the replaced behaviour** (changed, not deleted, each noted in the commit):
`test_p4b_watch_isolation_and_delivery.py` — `test_undelivered_strategy_entry_keeps_state_and_retries` (2nd run now
re-SENDS the stored entry labelled delayed instead of re-deriving it; the "re-fired" assertion becomes "resent"),
`test_undelivered_strategy_exit_stays_armed` and `test_undelivered_composite_entry_stays_unarmed` (committed phase
assertions kept, plus `pending_events` present), `test_notify_raising_counts_as_undelivered` if it asserts exact state
equality. Every other watch test must pass unchanged.

**Mutations the suite must kill** (run and recorded in the phase note): (M1) evaluate from committed instead of effective
state; (M2) send a new event while pending exists; (M3) break on delivered instead of not-delivered in the walk;
(M4) resend disabled watches; (M5) drop the `float()` coercion; (M6) commit an undelivered first send (old D3 bug);
(M7) newest-first order.

## 3. Out of scope / logged

- /strategy-watch page showing a "delayed alert pending" badge (frontend).
- Retrying sooner than the next scheduled run (EOD mode = next day), as today.
- `dispatch.py` semantics (P6 item 7).

## 4. State record

On merge: phase `verify` becomes a presence probe on `pending_events` in `strategy_watch_evaluator.py`; the defect marker
"state kept, retries next run" must be gone (it is, per §1.2).
