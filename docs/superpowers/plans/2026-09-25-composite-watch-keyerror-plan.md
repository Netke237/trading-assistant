# Composite-watch KeyError — one enabled composite watch kills every watch notification

Branch `claude/wizardly-ritchie-ndb5sg`, off main `489202d`. Backend only.
Closes PROJECT_STATE.json `open_questions[0]` (logged by the A4f build, above the gate,
pre-existing). Kenneth chose this ahead of A5c on 2026-09-25.

## The defect (reproduced on 489202d)

`backend/app/services/strategy_watch_evaluator.py::evaluate_all`, strategy loop (~:95-99):

```python
for w in strategy_watch_store.list_watches():
    if not w.get("enabled"):
        continue
    symbol = w["symbol"]
    key = w["strategy_key"]          # KeyError for every composite watch
```

`StrategyWatchStore.add_composite_watch` (strategy_watch_store.py ~:174) never writes
`strategy_key`, so the first enabled composite watch in list order raises `KeyError`.
Measured: one composite + one strategy watch, `evaluate_all()` raises
`KeyError 'strategy_key'`. Consequences:

1. `evaluate_and_notify` never gets an event list, so **no watch of either kind is
   notified** on that tick: strategy watches are silenced, and the composite loop
   (~:236) is never reached, so composite watches have never fired in production.
2. **Persisted state still moves.** Strategy watches listed BEFORE the composite reach
   `strategy_watch_store.update_state(...)` before the raise, so their phase goes
   idle→armed (or armed→idle on an exit) with no notification sent. In EOD mode the
   scheduler does not set `_last_eod_run_date` on a raise, so it retries every tick.
3. The existing composite tests hid it: their fixtures carry `"strategy_key": "composite"`,
   which the real store never writes (`tests/test_composite_sustain.py:108,136,188`).

## Fix

Strategy loop only:

```python
if w.get("watch_type") == "composite":
    continue
...
key = w.get("strategy_key")
fn = _SIGNAL_FNS.get(key)
if fn is None:
    continue
```

- Skipping composites explicitly states that this loop handles strategy watches only. The
  composite loop below already selects `watch_type == "composite"`.
- `.get` means any other watch missing the key (a hand-edited file, a future watch type)
  skips that one watch, the same way an unknown `strategy_key` already does, instead of
  aborting the tick.
- `watch_type` is set to `"strategy"` by `load()`'s `setdefault` for legacy entries, so
  real strategy watches are unaffected. A strategy watch that genuinely lacks
  `watch_type` still goes through the strategy loop because it is not `"composite"`.

No change to the composite loop, the store, the scheduler, or the notification path.

## Behaviour change Kenneth should know (not a new decision; it follows from the fix)

After this merges, on the first scheduler run:
- **Composite watches notify for the first time** whenever their trigger matches
  (including the A4f-migrated HMM_intraday watches).
- **Strategy watches notify again.** A watch that was silently moved to `armed` during the
  broken period (point 2) will next notify its EXIT, for an entry Kenneth never heard
  about. We cannot tell which watches were affected (no notification record exists), so
  the plan does NOT reset or rewrite any stored state. That would be guesswork on
  persisted data. It is logged as an open question instead.
- Nothing here places orders: `evaluate_and_notify` only sends Gmail/Telegram.

## Tests (new file `backend/tests/test_composite_watch_keyerror.py`)

Built with the REAL store (`StrategyWatchStore` on a tmp path, via
`add_composite_watch` / `add_watch`), not hand-written dicts, so the fixture shape is the
one production writes:
1. One enabled composite + one strategy watch whose signal fires → `evaluate_all` returns
   the strategy entry event (does not raise).
2. Same, with the composite listed FIRST and LAST (order independence).
3. The composite's own path is reached: with `evaluate_scheduled` patched to match, the
   composite event is returned alongside the strategy one.
4. A strategy-shaped watch with no `strategy_key` is skipped, and the others still evaluate.
5. `evaluate_and_notify` dispatches one notification per event when a composite is present.

Mutation checks: remove the composite skip AND revert `.get` → 1-3,5 fail; revert only the
skip (keep `.get`) → equivalent (the composite has no key, so `fn is None` skips it). Record
that honestly rather than inventing a test for it.

## Verification
Full backend suite (baseline on main 489202d measured before the change). Frontend untouched.

## Amendment after round 1 (the plan) — two gate-level findings, both taken

**F1. The fix makes the composite loop reachable, and that loop re-fires every run.**
`evaluate_scheduled` is level-triggered (`state == to_state` plus thresholds), and a
composite fire never writes state, so while a regime holds, every scheduler run (EOD daily;
poll mode up to ~7/day; every manual `/evaluate`) sends another identical "Long setup".
With `sustain_minutes` it is the same, because `pending_entry_since` is never cleared after a
fire. The plan's "no change to the composite loop" was wrong.

**Kenneth's decision (2026-09-25): ONCE PER ENTRY.** A composite alerts when its condition
becomes true, then stays quiet until the condition goes false and comes back. This is the
same shape as the strategy watches' idle/armed state machine.

Composite loop, after `fired` is computed by `evaluate_scheduled` (the existing
`get_bars` / `evaluate_scheduled` failure paths `continue` with state UNCHANGED, so a data
outage neither re-arms nor fires):
- `phase = last_state.get("phase", "idle")` (a legacy `{}` state reads as idle).
- **armed and fired** → `continue`: no event, no write.
- **armed and not fired** → `update_state(..., {**state minus pending_entry_since,
  "phase": "idle"})`, keeping `last_event` / `last_event_at` for display, then `continue`.
  This re-arms the watch for the next entry.
- **idle** → the existing sustain logic, unchanged. On a sustained fire: emit the event AND
  `update_state(..., {**state minus pending_entry_since, "phase": "armed", "direction": wdir,
  "last_event": "entry", "last_event_at": now})`.

Consequences, stated rather than hidden:
- On the first run after merge, each composite whose condition already matches alerts ONCE.
  That is the intended "first time" notification.
- A disabled watch is not evaluated, so it keeps its phase. Re-enabling it while the same
  regime still holds sends nothing; it alerts on the next entry. There is no trigger edit
  path (the store has create/delete/enable only), so a stale `armed` cannot outlive a
  changed definition.
- `update_state` REPLACES `last_state` with `_fresh_state()` overlaid by the new dict,
  so omitting `pending_entry_since` removes it.

**F2. The same KeyError in `StrategyWatchStore.add_watch`'s duplicate check.**
`w["strategy_key"]` over every same-symbol watch means adding a strategy watch for a symbol
that has a composite 500s, and `add_watches_bulk` saves the symbols before it, then raises
and silently drops the rest. Fix: skip `watch_type == "composite"` in that loop and read
`w.get("strategy_key")`.

**Tests added:** two `evaluate_all` runs against the real store with the condition held true
give exactly ONE composite event; true → false → true gives two; sustain + hold gives one
and clears `pending_entry_since`; an `evaluate_scheduled` exception leaves state unchanged;
`add_watch` / `add_watches_bulk` for a symbol that has a composite succeed and add all
symbols.
