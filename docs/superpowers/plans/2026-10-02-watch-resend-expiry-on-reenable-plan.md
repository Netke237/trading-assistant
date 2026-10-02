# WATCH-RESEND-EXPIRY-ON-REENABLE (piece 2 of 3) — plan v1 (not yet reviewed)

- **Phase:** `WATCH-RESEND-EXPIRY-ON-REENABLE` (decision `WATCH-RESEND-SPLIT-2026-10-02`).
- **Starting material:** combined plan `2026-10-01-watch-resend-head-of-line-plan.md` v2 §2.8 and its
  round-1 findings R1-1 (both enable routes), R1-5 (PATCH vs a running evaluation), R1-13 (naive and
  unparseable `fired_at`).
- **Max age:** 5 calendar days, confirmed by Kenneth 2026-10-02 (named constant, his value to change).
- **Rules kept:** `WATCH-RESEND-QUEUE-2026-09-27` (queue oldest first, Delayed label, a DISABLED watch
  keeps its events — expiry happens only at the moment it is re-enabled). Piece 1's skip-on-proof
  counters on surviving entries are untouched.
- **Branch:** `claude/infallible-hertz-c2c2d9`. Backend only, ~80 lines of code + one test file.

## 1. The defect (main e1b9ff1)

A watch's undelivered alerts are stored in `last_state.pending_events` as
`{"event", "new_state", "fired_at", ...}`, oldest first. `_resend_pending` skips disabled watches
(`_resend_watch`, "a disabled watch keeps its events"). Both enable routes —
`routers/strategy_watch.py` PATCH `/{watch_id}` (:75-79) and `routers/composite_watch.py` PATCH
`/{watch_id}` (:148-152) — only call `strategy_watch_store.set_enabled`. So a watch disabled for weeks
sends weeks-old "Delayed" alerts on the first run after it is turned back on.

## 2. Behaviour after the change

### 2.1 The constant

`strategy_watch_evaluator.py`: `_REENABLE_MAX_AGE = timedelta(days=5)` beside the other queue
constants, with a comment naming Kenneth's 2026-10-02 confirmation.

### 2.2 `set_enabled_and_expire(store, watch_id, enabled) -> int | None`

New `async` function in `strategy_watch_evaluator.py`. `store` is passed by the caller (the router's
`strategy_watch_store`): in production it is the same object the evaluator imports; the router tests
reload the store module, so the evaluator's import would point at a stale store there.

```
async with _run_lock():
    w = the watch with id watch_id in store.list_watches()   -> None if absent
    n = 0
    if enabled and not w.get("enabled"):           # only a disabled -> enabled change expires
        committed, pending = _split_state(dict(w.get("last_state") or {}))
        cutoff = _utcnow() - _REENABLE_MAX_AGE
        while pending and _expired(pending[0], cutoff):
            dropped = pending.pop(0); n += 1
            ns = dropped.get("new_state") if isinstance(dropped, dict) else None
            if isinstance(ns, dict): committed = ns          # same rule as _queue's cap eviction
            logger.warning(<watch id, event_type, fired_at, reason>)
        if n:
            store.update_state(watch_id, {**committed, "pending_events": pending} if pending else committed)
    if not store.set_enabled(watch_id, enabled):
        return None
    return n
```

- **Lock [R1-5].** Holding `_run_lock()` means no `evaluate_and_notify` can be between its resend
  pass and its writes while the queue is rewritten, and the first run after the PATCH starts with the
  stale entries already gone. The lock is taken for both directions (one code path); a disable
  therefore also waits for a running evaluation — accepted, see §5.
- **No await between the read and the writes**, so no other coroutine can change the watch in between.
- **Order: expire, then enable.** The expiry write uses `store.update_state` directly, NOT `_write`:
  if it raises, the exception propagates (HTTP 500) and `set_enabled` is never called — the watch is
  never left enabled with its stale alerts saved. (On the real store, `update_state` changes memory
  before saving, so a retry finds nothing left to drop and just enables.)
- **Prefix only.** Expiry stops at the first entry that is not expired. The queue is in firing order,
  so in practice this is every old entry; an out-of-order clock leaves later old entries in place
  rather than delivering a newer one ahead of an older one.
- **Effective state is unchanged.** Dropping a prefix never touches the tail; with every entry
  dropped, committed becomes the tail's `new_state`, which was already the effective state. So the
  next evaluation runs from exactly the same state as without expiry — only the sends disappear.
- `_split_state` gives `[]` for a missing or non-list `pending_events`: nothing to do, no write.

### 2.3 `_expired(entry, cutoff) -> bool` [R1-13]

- Not a dict → expired.
- `fired_at` missing, not a string, or not ISO-parseable → expired.
- Naive datetime → read as UTC.
- Expired iff `fired_at < cutoff` (strictly older than 5 days; exactly 5 days is kept). A future
  `fired_at` (clock jump) is not expired.
- A dict entry whose `event`/`new_state` is malformed is judged only on `fired_at`: if young it is kept
  and the resend walk drops it as today; if old it is dropped here (its non-dict `new_state` is not
  committed).

### 2.4 Routers [R1-1]

Both PATCH handlers become:

```
n = await set_enabled_and_expire(strategy_watch_store, watch_id, body.enabled)
if n is None: raise HTTPException(404, <existing message>)
return {"id": watch_id, "enabled": body.enabled, "expired_alerts": n}
```

`frontend/lib/api.ts:828` types the strategy response as `{ id; enabled }`; the extra key is ignored.
No frontend change in this piece (§5).

## 3. Files

- `backend/app/services/strategy_watch_evaluator.py` — constant, `_expired`, `set_enabled_and_expire`.
- `backend/app/routers/strategy_watch.py`, `backend/app/routers/composite_watch.py` — PATCH handlers.
- New `backend/tests/test_watch_resend_expiry_on_reenable.py` (reuses `_Store`, `_sw`, `_entry` from
  `test_watch_undelivered_resend.py` and `_CfgEnv`, `_Notify`, `_e` from `test_watch_resend_skip_on_proof.py`;
  `_Store` gains a `set_enabled` in the new file's subclass).

## 4. Tests (each fails on main or on a named mutation)

Clock: `_utcnow` patched to `T0`; entries built with `fired_at = T0 - age`.

1. Disabled watch, pending `[6 d, 4 d]`, enable → returns 1; pending = `[4 d entry]` byte-identical
   (its `failures`/`last_failure_at` kept); committed = the 6 d entry's `new_state`; watch enabled;
   one WARNING naming the watch and the dropped reason.
2. All old `[7 d, 6 d]` → returns 2; no `pending_events`; stored state = the 6 d entry's `new_state`
   (= the effective state before). Fails on main (no function) and on "commit the first dropped".
3. Boundary: exactly 5 d → kept; 5 d + 1 s → dropped. Kills `<` → `<=`.
4. Already enabled, old entries, PATCH enabled=true → returns 0, queue untouched, no state write.
   Kills "expire on every enable".
5. Disable (enabled=false) on a disabled or enabled watch with old entries → returns 0, queue
   untouched, watch disabled.
6. Unknown id → None, nothing written.
7. Malformed `fired_at` cases, each at the head with a 4 d entry behind: missing, `"garbage"`, `123`;
   and a non-dict head entry → each dropped (returns 1), 4 d kept; for the non-dict entry committed
   stays the previous committed state.
8. Naive `fired_at`: 6 d naive → dropped; 4 d naive → kept (without the naive guard the aware/naive
   comparison raises TypeError).
9. Prefix only: `[4 d, 6 d]` → returns 0, nothing written. Kills "filter all old entries".
10. Future `fired_at` (T0 + 1 h) at the head → kept.
11. Write failure: `_Store.raise_on("a")` → `set_enabled_and_expire` raises; watch still disabled.
    Kills "enable first" and "use `_write`".
12. Lock: a task holds `_run_lock()`; `set_enabled_and_expire` started alongside does not finish and
    writes nothing until the lock is released, then completes. Kills "expiry outside the lock".
13. End to end: disabled watch with `[6 d, 4 d]`, enable, then one `evaluate_and_notify` run via
    `_CfgEnv` with the channel up → exactly one send, the 4 d entry, labelled Delayed; the 6 d reason
    never sent.
14. Strategy route on a real `StrategyWatchStore(tmp_path)` patched into `app.routers.strategy_watch`:
    PATCH enable → 200 `{"id", "enabled": true, "expired_alerts": 1}`; a fresh store loaded from the
    same file shows the watch enabled with only the 4 d entry. Unknown id → 404.
15. Composite route, same as 14 on a composite watch (`add_composite_watch`), patched into
    `app.routers.composite_watch`. Kills "only one router wired".
16. Existing `test_strategy_watch_router.py::test_patch_enabled` still passes (the reload fixture).

Full backend suite must stay green.

## 5. Out of scope / residuals (logged, not built)

- **No UI notice.** The user is not told in the app that N alerts were dropped; the count is in the
  PATCH response and in the WARNING log. A toast would be a frontend change (separate batch).
- **A disable or enable can wait for a running evaluation** (the lock). There is no run breaker yet
  (that is piece 3's territory); a slow run delays the PATCH response, not its effect.
- **Expiry only at re-enable.** An enabled watch whose channel was down for 6 days still sends its
  6-day-old alerts when the channel recovers — decision WATCH-RESEND-QUEUE-2026-09-27 as it stands.
- **A kept young alert can follow a dropped old one** (e.g. the entry alert expired, its stop-hit
  4 days later is still sent). That is the prefix rule; the stop-hit is still news.
- Open question WATCH-RESEND-TWO-STUCK-IN-A-ROW is untouched (Kenneth's).
