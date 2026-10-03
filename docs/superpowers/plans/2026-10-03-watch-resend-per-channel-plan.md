# WATCH-RESEND-PER-CHANNEL, piece 3: per-channel delivery — plan (v1, not yet reviewed)

- **Phase:** `WATCH-RESEND-PER-CHANNEL`, piece 3 of 3 (decision `WATCH-RESEND-SPLIT-2026-10-02`). Own plan,
  own three plan rounds, then its own three code rounds (`AUDIT-CAP-PER-STAGE-2026-09-25`).
- **Decisions:** `WATCH-RESEND-HEAD-OF-LINE-2026-10-01` ("per-channel partial delivery (dispatch.py reports
  each channel)"; skip on proof "if the next delivers ON THAT CHANNEL the oldest is declared undeliverable
  THERE"), as narrowed by `WATCH-RESEND-SPLIT-2026-10-02` (drop at once, no retry, nothing delivered out of
  order). `WATCH-RESEND-QUEUE-2026-09-27` (queue, oldest first, Delayed label, disabled watches keep theirs)
  stays the rule.
- **Starting material:** combined plan v2 (`2026-10-01-watch-resend-head-of-line-plan.md`) sections 2.1-2.3,
  2.6 and its round-2 findings 1-3, 5-6. This plan is simpler than 2.4-2.6 there: it keeps piece 1's run
  order (resend pass, then `_collect`, then fresh events) instead of append-then-drain, and has no run breaker
  and no `targets` key (see 2.9).
- **Branch:** `ccr-81bee0d6-mzrvun`, from main `41917a6` (pieces 1 and 2 merged).

## 1. What is true on main (41917a6)

`backend/app/services/notifications/dispatch.py`:

1. `notify_enabled_channels(subject, plain, html) -> bool` (:90-130) reads the config itself
   (`load_notification_config()`), sends Gmail then Telegram for each enabled block (null/non-dict block =
   disabled) and returns ONE OR'd bool. Callers: `strategy_watch_evaluator._send`, `alert_notifier.py:325`,
   `scan_schedule_scheduler.py:96/:107`. `chart_alerts` calls `dispatch()` directly.
2. `send_gmail` returns False without sending when `smtp_user`/`smtp_password` are empty after its env
   fallback (`BAMENDJOU_GMAIL_USER`/`_PASSWORD`); `send_telegram` likewise for `bot_token`/`chat_id`
   (`BAMENDJOU_TELEGRAM_BOT_TOKEN`/`_CHAT_ID`). Settings lets a channel be enabled with no token
   (`notification_settings.py:188-191`). `_safe_notify` logs a raised send at ERROR with the traceback.

`backend/app/services/strategy_watch_evaluator.py`:

3. `evaluate_and_notify` (:953-972): `any_channel, readable = _channel_status()` (one config read),
   `probe_ready = _resend_pending(any_channel, count_failures=readable)`, `_collect`, then
   `_deliver_or_queue(t, any_channel, probe_ready)` per transition under a per-watch `try`.
4. `_send(ev, delayed_since)` (:816-823) returns `notify_enabled_channels`' single bool; every send re-reads
   settings.yaml (piece 1 residual 4.1-5).
5. `_resend_watch` (:826-893): piece 1's walk — head failure counted (`failures`, `last_failure_at`, spacing
   1 h), eligible at 3 → probe the next entry → delivered: head dropped at once (`_DROP_LOG`), walk continues;
   failed probe: stop. Probe-ready when an eligible head has nothing valid behind it.
6. `_deliver_or_queue` (:916-950): with `t.pending` non-empty the fresh event is queued unsent, except the
   probe-ready fresh probe (piece 1 2.3). With `t.pending` empty: `_send(ev) or not any_channel` → commit,
   else `_queue`.

**The defect:** "delivered" is one bool. With Gmail up and Telegram down an alert counts as delivered, the
state is committed and Telegram silently never gets it. A probe delivered on Gmail drops a head Telegram
never had (piece 1 section 4, stated residual "until piece 3").

## 2. Design

### 2.1 Dispatch (dispatch.py)

- `_CHANNELS = ("gmail", "telegram")` (send order).
- Private `async def _send_channels(cfg, subject, plain, html, channels=None) -> dict[str, bool]`: today's body
  of `notify_enabled_channels`, unchanged per channel (same block rule, same `dispatch(...)` kwargs, same
  env fallbacks), restricted to `channels` when given; returns `{channel: delivered}` for each channel it
  ATTEMPTED (enabled in `cfg` and, if given, listed).
- `notify_enabled_channels` keeps its signature, its own config read and its contract:
  `return any((await _send_channels(load_notification_config(), subject, plain, html)).values())`.
  Its three callers are unchanged.
- New public `async def notify_channels(cfg, subject, plain, html, channels) -> dict[str, bool]` over
  `_send_channels`, taking the ALREADY-READ cfg (the evaluator reads the config once per run).
- New public `def ready_channels(cfg) -> list[str]`: the enabled channels (same block rule) whose
  credentials are present — Gmail: (`smtp_user` or env `BAMENDJOU_GMAIL_USER`) and (`smtp_password` or env
  `BAMENDJOU_GMAIL_PASSWORD`); Telegram: (`bot_token` or env `BAMENDJOU_TELEGRAM_BOT_TOKEN`) and (`chat_id`
  or env `BAMENDJOU_TELEGRAM_CHAT_ID`) — exactly the checks `send_gmail`/`send_telegram` make before they
  return False without sending. In `_CHANNELS` order.

"Why a send failed": a channel that cannot send at all (not configured) is known before sending
(`ready_channels`) and is not a delivery target (2.3); a channel that was tried and failed is logged per
channel by `_safe_notify` (exception + traceback) and, new, by the evaluator's WARNING naming the watch,
the event and the failed channel(s). No reason code is stored.

### 2.2 The run context (evaluator)

New `_run_context() -> _Run`, ONE `read_notification_config()` call per run, through the evaluator's own
imported name (tests patch `{_EV}.read_notification_config`):

```python
@dataclass(frozen=True)
class _Run:
    mode: str                      # "send" | "hold" | "commit"
    cfg: dict = field(default_factory=dict)
    channels: tuple[str, ...] = ()  # "send" only: the ready channels, in _CHANNELS order
```

- reader raises, or reports not readable → `hold` (ERROR, today's wording: "settings.yaml unreadable;
  gating state on delivery").
- readable, no channel enabled (cfg not a dict, or no enabled block) → `commit` (D3, today).
- some channel enabled, none ready → `hold` (WARNING "notification channel(s) enabled but not configured:
  <names>; alerts kept").
- else `send` with `channels = ready_channels(cfg)`; each enabled-but-not-ready channel → one WARNING per
  run ("<c> enabled but not configured; not a delivery target").

`_channel_status()` and `_any_channel_enabled()` keep their exact contracts and tests
(`test_p6_notification_config.py:107-116`, `test_p4b_watch_isolation_and_delivery.py:238-248`):
`_channel_status` is re-expressed on the same reading helper (`(True, False)` when unreadable/raising,
`(any enabled, True)` otherwise — "enabled" is NOT "ready" there). `evaluate_and_notify` no longer calls
`_channel_status`.

Mode meanings, notify path:

- `hold` — no sends, no counters changed, nothing committed; fresh events are queued unsent (`_queue`).
  This is today's OUTCOME for an unreadable config (every send failed, nothing counted, nothing committed)
  without the futile notify calls. New: an enabled-but-unconfigured-only setup also holds (today its sends
  failed, were counted and probed, and still dropped nothing — an all-channels failure is an outage).
- `commit` — D3: every enabled watch's queue is committed unsent oldest first (WARNING per entry, malformed
  dropped at ERROR), as `_resend_watch(any_channel=False)` does today; a fresh event is committed without
  a send (today it was also passed to `_send`, which found nothing enabled and returned False).
- `send` — 2.4 / 2.5 over `run.channels`.

`evaluate_all` (no-notify path) runs the pass with `_Run("commit")` — today's `any_channel=False`.

The config is read once per run: a Settings save landing mid-run takes effect next run. This closes piece 1
residual 4.1-5 (a mid-run partial file read by one send).

### 2.3 Stored entry keys (backward compatible)

A pending entry `{"event", "new_state", "fired_at"}` (plus piece 1's optional scalars `failures`,
`last_failure_at`) gains three optional keys, absent on entries written by pieces 1-2:

- `"channel_done": {channel: "delivered" | "dropped"}` — channels finished with this entry.
- `"channel_failures": {channel: int}` — counted failed runs as the head ON THAT CHANNEL.
- `"channel_last_failure_at": {channel: iso}` — last counted failure on that channel.

Reading (helpers `_done(e)`, `_failures(e, c)`, `_last_failure(e, c)`):

- `channel_done`: a dict; entries whose key is in `_CHANNELS` and value is "delivered"/"dropped" are kept,
  everything else ignored; not a dict → `{}`.
- `channel_failures[c]` valid when a non-negative int (bool excluded). Absent/invalid for `c` → FALLBACK to
  piece 1's scalar `failures` with piece 1's rule (non-negative int, else 0). Under piece 1 a counted failure
  meant EVERY enabled channel failed, so the scalar is a correct count for each channel; an entry eligible
  before the upgrade stays eligible after it.
- `channel_last_failure_at[c]` likewise falls back to the scalar `last_failure_at`; then piece 1's parsing
  rules (non-string/unparseable/future → counts as absent; naive = UTC).
- Writes go to the `channel_*` dicts only, as NEW dicts on a COPY of the entry (the real `list_watches` is a
  shallow copy). The scalars are never written or removed.

REMAINING(e) = `[c for c in run.channels if c not in _done(e)]`. COMPLETE(e) = parseable and REMAINING
empty. A malformed entry is never complete.

`_pop_complete(committed, pending) -> (committed, pending)`: while the head is COMPLETE, `committed =
dict(head.new_state)` and it is popped. Every write of a queue in `send` mode goes through it, so a fully
finished entry never stays stored. An entry popped with every channel "dropped" was already logged at ERROR
per channel (2.4).

Malformed values of the new keys can make an entry be sent again to a channel that already had it (a
duplicate, never a loss); they only arise from hand edits.

### 2.4 The resend pass, per channel (`_resend_watch(w, run)`, `send` mode)

Nothing changes for a disabled watch or an empty queue (return None). `hold` → return None, nothing written.
`commit` → today's unsent commit (2.2).

`send`: copy the queue (`[dict(e) if isinstance(e, dict) else e for e in rest]`), then walk it oldest first
with run-local per-channel state: `blocked: set[str]`, `stuck: dict[str, tuple[entry, int]]` (channel →
the eligible head on that channel and its failures). For entry `e`:

1. Malformed → ERROR "malformed pending event dropped", removed, written; next entry (today's rule).
2. `targets = [c for c in REMAINING(e) if c not in blocked]`. Empty → next entry (it waits only on blocked
   channels).
3. ONE send: `_send(ev, run, targets, delayed_since=fired_at)` → `{c: bool}`.
4. For each `c` in `targets`:
   - delivered → `channel_done[c] = "delivered"`. If `c in stuck`: the stuck head `h` gets
     `channel_done[c] = "dropped"` and the ERROR `_DROP_LOG` is logged (watch id, channel, `h`'s failures on
     `c`, `h`'s reason); `stuck.pop(c)`; `c` stays open.
   - failed and `c in stuck` → this was the PROBE on `c`: nothing dropped, nothing counted on `e`, `c` →
     blocked (an outage on `c`, or a second stuck alert — open question WATCH-RESEND-TWO-STUCK-IN-A-ROW).
   - failed otherwise → `e` is the HEAD on `c` (every earlier entry with `c` remaining was delivered or
     dropped on `c`, or `c` would be blocked/stuck). Count it per piece 1's rule on channel `c` (spacing 1 h
     against `_last_failure(e, c)`). `_failures(e, c) >= _UNDELIVERABLE_AFTER` → `stuck[c] = (e, n)` (the
     next entry with `c` remaining is the probe); else `c` → blocked (WARNING "still not delivered on <c>;
     kept").
5. If anything in steps 1/4 changed the queue, write it now — `_pop_complete` then `_write` — before the
   next send (at most one entry sent-but-unwritten, today's guarantee).
6. Stop the walk when every channel in `run.channels` is blocked (piece 1 test 9: an entry behind a failed
   probe is not reached).

After the walk, every `c` still in `stuck` had no valid entry behind its head: the watch is PROBE-READY on
`c`. `_resend_watch` returns `{c: n}` for those (None/empty otherwise); `_resend_pending(run)` returns
`{watch_id: {c: n}}` and keeps the per-watch `try`.

The drop ERROR becomes `"strategy-watch: undeliverable alert dropped for %s on %s after %d failed runs; a
later alert was delivered there: %s"` (still contains "undeliverable alert dropped for <id>", which piece 1's
tests match).

Order on each channel: `c` never receives an entry while an earlier one is outstanding on `c` (not
delivered, not dropped), except piece 1's probe — and then the earlier one is dropped on `c` at once, never
delivered later. Each entry is sent at most once per run (one call with its target list).

### 2.5 A fresh event (`_deliver_or_queue(t, run, probe_ready)`)

- `hold` → `_queue(t)` (WARNING), no send.
- `commit` → `t.pending` non-empty (the pass failed for that watch): `_queue(t)`, today's rule; else
  `_commit(t)` (WARNING "no channel enabled").
- `send`: copy `t.pending`. Per channel `c` in `run.channels`, from the STORED queue (`t.pending`, which
  `_collect` re-read after the pass — never from the pass's return value):
  - OPEN when no entry of `t.pending` has `c` remaining (a malformed entry counts as outstanding);
  - PROBE when `c in probe_ready.get(t.watch_id, {})` AND exactly one entry of `t.pending` has `c`
    remaining (defensive, piece 1's length check per channel) — that entry is the stuck head `h`;
  - else BLOCKED.

  `targets` = OPEN + PROBE channels. Empty → `_queue(t)` unsent (WARNING "queued behind <n> undelivered").
  Else ONE send of the fresh event to `targets`, NOT labelled Delayed. Delivered on a PROBE channel → `h`
  gets `channel_done[c] = "dropped"` (ERROR `_DROP_LOG`). The fresh entry is `_pending_entry(t)` with
  `channel_done = {c: "delivered"}` for each delivered `c`. The queue `t.pending' + [fresh]` goes through
  `_pop_complete(t.committed, ...)`: everything complete → `_write(t.watch_id, committed)` (= today's
  `_commit(t)` when the fresh event completes an empty queue); else written through `_queue`'s cap.

So with Gmail up and Telegram stuck on an older alert, a stop hit goes to Gmail in the run it fires; Telegram
gets it in order once the older one is delivered or dropped there.

A failed fresh send is not counted (as in piece 1); its first counted failure is on the next run, as the
head.

### 2.6 Queue cap

`_queue`'s cap body becomes `_store_queue(watch_id, committed, pending)` (unchanged behaviour: drop oldest
above `_QUEUE_CAP`, committing their new_state, ERROR "queue full"); the ERROR line appends the dropped
entry's `channel_done` so a partly delivered drop reads differently. `_queue(t)` calls it.

### 2.7 `_send` (evaluator)

`async def _send(ev, run, channels, delayed_since=None) -> dict[str, bool]`: formats once, calls the
evaluator-level name `notify_channels(run.cfg, subject, plain, html, list(channels))`; a raise or a non-dict
result → every channel not delivered (ERROR with traceback, today's rule); a channel missing from the result
→ not delivered. WARNING naming the failed channels.

### 2.8 Unchanged

`_collect`, `_effective_view`, `_write_effective` (keeps an entry's extra keys), piece 2's
`set_enabled_and_expire` (reads only event/new_state/fired_at), routers, frontend, `notify_enabled_channels`'
callers, chart alerts.

### 2.9 Combined-plan round-2 findings carried here

- R2-1 (run breaker counted stuck heads): no breaker. Per-channel sends never exceed today's: today every
  entry delivered on Gmail was also sent to a down Telegram; now a blocked Telegram is not called again for
  that watch this run (per watch per channel per run: delivered entries + at most one failing head + one
  failing probe).
- R2-2 (two stuck in a row): unchanged residual, per channel; open question WATCH-RESEND-TWO-STUCK-IN-A-ROW.
- R2-3 (unspaced proven increments, post-recovery 429): gone with the retry (drop-at-once decision).
- R2-5 (test migration): section 4.1 — every test that patches the evaluator's notify is migrated, with a
  guard that fails the test on a real send (checked at teardown, since `_safe_notify` swallows raises). No
  append-then-re-read is introduced, so MagicMock-store tests keep working.
- R2-6 (targets on an unreadable config): no `targets` key; unreadable → `hold`.
- Below-gate "token-less enabled Telegram": `ready_channels` (2.1) — an enabled channel without credentials
  is not a target, so Gmail-only delivery still completes an alert, exactly as today.

## 3. Files

- `backend/app/services/notifications/dispatch.py` (~40 lines).
- `backend/app/services/strategy_watch_evaluator.py` (`_Run`, `_run_context`, entry-key helpers,
  `_pop_complete`, `_store_queue`, `_send`, `_resend_watch`, `_resend_pending`, `_deliver_or_queue`,
  `evaluate_and_notify`, `evaluate_all`; ~150 lines changed).
- New `backend/tests/watch_notify_helpers.py`, new `backend/tests/test_watch_resend_per_channel.py`; test
  migrations (4.1).

## 4. Tests

### 4.1 Migration (behaviour preserved; listed so a reviewer can check nothing is weakened)

`tests/watch_notify_helpers.py`:

- `per_channel(notify)`: adapts an existing bool fake `notify(subject, plain, html)` to `notify_channels`'
  signature — awaits it ONCE per call and gives every requested channel that result (call counts and
  `await_args` subjects are unchanged).
- autouse-by-import fixture `configured_channels_no_real_sends(monkeypatch)`: sets the four credential env
  vars to dummies (so an enabled channel in a test cfg is ready) and patches
  `app.services.notifications.dispatch.send_gmail` / `.send_telegram` with recording mocks; asserts at
  teardown that neither was called.

Modules migrated (patch `{_EV}.notify_channels` with `per_channel(...)` instead of
`{_EV}.notify_enabled_channels`; import the fixture): `test_watch_undelivered_resend.py` (`_Env`),
`test_watch_resend_skip_on_proof.py`, `test_p4b_watch_isolation_and_delivery.py`,
`test_composite_watch_keyerror.py` (:117, :238, :375), `test_strategy_watch_evaluator.py` (:394),
`test_strategy_watch_router.py` (:176). Tests that ran `evaluate_and_notify` against the REAL (absent)
settings.yaml and relied on today's "send even when nothing is enabled" (`test_strategy_watch_evaluator.py`
:385-399 asserts `notify.assert_called_once()`; `test_composite_watch_keyerror.py` sends) also patch
`{_EV}.read_notification_config` with a Gmail-enabled cfg — under 2.2 `commit` mode no longer calls send.

Piece 1 tests whose assertions name the representation change, not the behaviour:

- counter assertions `_head(store)["failures"] == n` / `["last_failure_at"] == x` read
  `channel_failures["gmail"]` / `channel_last_failure_at["gmail"]` (inputs keep the legacy scalars, so the
  fallback is exercised); `"failures" not in head` becomes "no `channel_failures`".
- test 2c (unreadable config): `n.reasons() == ["RZ-head"]*3` / `["RZ-head"]` become `[]` (hold sends
  nothing); every other assertion (nothing dropped, counters untouched, fresh queued) stays.
- test 11 (defensive length check) calls `_deliver_or_queue(t, _Run("send", cfg, ("gmail",)),
  {"a": {"gmail": 3}})`.

### 4.2 New: `test_watch_resend_per_channel.py`

Harness: `_Store`/`_Env` from `test_watch_undelivered_resend.py`; cfg with BOTH channels enabled; a
`notify_channels` fake that decides per (channel, reason) and records `(channel, reason, delayed?)` per call;
`{_EV}._utcnow` patched. Fresh transitions come from the real `_collect` (head `new_state` armed with
`stop_price` above `env.close`). Tests 1 and 3 also run on the real YAML store rebuilt from disk before each
run.

1. Partial delivery: fresh event, Gmail delivers, Telegram fails → returned event, NOT committed, queue
   `[e]` with `channel_done == {"gmail": "delivered"}`. Next run, Telegram up → exactly one call, channels
   `["telegram"]`, labelled Delayed; queue empty; committed = e's new_state. *Kills the OR'd bool and
   re-sending to a done channel.*
2. Gmail not held back: queue `[e(gmail delivered)]`, Telegram fails, a fresh stop hit → Gmail gets the
   stop hit this run, unlabelled; Telegram is called for e only (not the fresh); queue `[e, fresh(gmail)]`.
   *Kills "any outstanding entry blocks every channel" and "Telegram gets the fresh event while e is
   outstanding there".*
3. Skip on proof per channel: Telegram rejects head H only; Gmail delivers everything; queue `[H, B]`.
   Run 1 (t0): Gmail gets H and B; Telegram H fails (count 1), B not sent to Telegram. Runs t0+1h, t0+2h:
   only Telegram is called, H only; count 2, then 3 → B sent to Telegram as the probe, delivered → H dropped
   on Telegram (ERROR names "telegram"), queue empty, committed = B's new_state. Gmail never gets H or B
   twice. *Kills per-channel counting, the drop, and drop-on-the-wrong-channel.*
4. Counters are per channel: H fails on Gmail once (count 1) and on Telegram at the same run; Gmail then
   delivers H next run; Telegram's count continues from 1. Legacy scalar `failures: 3` → eligible on BOTH
   channels (probe on each).
5. A failed probe on Telegram (outage) blocks Telegram only; Gmail keeps delivering later entries in order;
   nothing dropped.
6. Readiness: Telegram enabled with no token/chat id (env cleared), Gmail ready → the fresh event is sent to
   Gmail only and COMMITTED (no queue), one WARNING names Telegram. Both enabled, neither ready → no send,
   fresh queued, no counters, nothing committed. *Kills dropping `ready_channels`.*
7. Disabling the failing channel: queue `[e(gmail delivered)]`, Telegram disabled in cfg → no send; e
   popped; committed = e's new_state.
8. A channel enabled after queueing: queue `[e]` (Gmail failing, Telegram disabled) → Telegram enabled →
   Telegram gets e (rule pinned, 2.9 / no targets).
9. Fresh event as the probe on one channel: head `[H]` with `channel_done {gmail: delivered}`,
   `channel_failures {telegram: 3}`, Telegram rejects H; fresh stop hit → pass: H to Telegram fails →
   probe-ready on Telegram; fresh sent to Gmail AND Telegram, unlabelled; Telegram delivered → H dropped on
   Telegram, both popped, committed = fresh new_state, no queue. Variant: fresh fails on Telegram → queue
   `[H, fresh(gmail)]`, H kept.
10. Defensive per-channel length check: direct `_deliver_or_queue` with `probe_ready {"a": {"telegram": 3}}`
    but two entries outstanding on Telegram → Telegram not in the send; Gmail is (nothing outstanding there).
11. A watch whose pass raised (patched `_resend_watch` raising for it) → its fresh event is NOT sent to a
    channel with an outstanding stored entry (openness from `t.pending`). *Kills openness taken from the
    pass's return value.*
12. One notify call per entry per run: count calls per reason in tests 1-3.
13. Unreadable config (returning `({}, False)` and raising) → zero notify calls, nothing committed, fresh
    queued, counters unchanged.
14. Malformed `channel_done` / `channel_failures` values (`"x"`, `-1`, `True`, unknown channel key,
    unknown status) read as absent; scalar fallback used.
15. dispatch: `notify_channels` with `channels=["telegram"]` attempts Telegram only and returns
    `{"telegram": bool}`; a listed channel disabled in cfg is not attempted (absent); a raising
    `send_telegram` → `{"telegram": False}`, Gmail still tried. `notify_enabled_channels`: any delivered →
    True; all failed → False; null block → other channel tried (existing tests stay). `ready_channels`:
    yaml credentials, env fallback, missing token, missing chat id, missing password, disabled, null block.
16. Cap with partial delivery: 21 entries with Telegram stuck → the evicted entry's ERROR includes its
    `channel_done`.

Mutations to kill (run on the build): OR'd result restored in `_send`; `_done` ignored in REMAINING;
`ready_channels` → enabled; counting on the scalar only; drop on every channel when one probe delivers;
openness from probe_ready only; `_pop_complete` ignoring one channel; fresh label Delayed; probe failure
counted on the probe entry; walk not stopped when all channels blocked.

## 5. Residuals (stated)

1. While one ready channel keeps failing (e.g. a wrong Telegram token), every alert of a watch with a queue
   stays queued for that channel; the watch's COMMITTED state (the phase pill on /strategy-watch) is the
   state before its oldest entry not yet finished on every ready channel, and the cap (20) evicts with
   ERROR. Evaluation always runs from the effective state, so alerts keep firing correctly and Gmail gets
   them at once. This is today's behaviour during a full outage, now also for a one-channel failure; it ends
   when the channel recovers, the stuck alert is dropped (skip on proof, if only that alert fails), or the
   channel is disabled or loses its credentials. Frontend display of queued alerts stays a logged follow-up.
2. Two undeliverable alerts in a row on one channel still block that channel (open question).
3. A crash or failed write between a send and its write: the next run sends that entry to the same channel
   again (the existing one-sent-but-unwritten window). A failed write after the pass also leaves `t.pending`
   behind the pass's view; openness is taken from `t.pending`, so this can only re-send, never skip.
4. A send that timed out client-side may have delivered; it counts as failed (pre-existing). Gmail SMTP has
   no timeout (pre-existing).
5. `ready_channels` checks that credentials are PRESENT, not valid; wrong credentials are residual 1.
6. Old entries (pieces 1-2) carry the scalar counters forever; harmless (fallback only).

## 6. Gates

Backend pytest full from `backend/` (Python 3.11); `python3 scripts/state.py` exit 0; frontend untouched.
