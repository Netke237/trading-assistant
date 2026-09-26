# P4b — Strategy & composite watches (plan r4)

Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § P4b. Branch `claude/cool-heisenberg-6lsa3a`,
off `origin/main` 2f67e6f. Claim `P4B-STRATEGY-COMPOSITE-WATCHES`.

r2 = r1 + plan round 1's 16 findings (2 HIGH, 5 MEDIUM, 9 LOW) + Kenneth's D4/D5. Each r1 finding is tagged
`[r1#n]` where it is fixed.
r3 = r2 + plan round 2's 13 findings (1 CRITICAL, 3 HIGH, 5 MEDIUM, 4 LOW) + D4 extended. Tagged `[r2#n]`.
r4 = r3 + plan round 3's 11 findings (1 HIGH, 3 MEDIUM, 7 LOW) + D6/D7/D8. Tagged `[r3#n]`. Round 3 hit the
3-round cap; Kenneth chose (D8) to build from r4 without a plan round 4 — the code rounds are the check.

## Decisions this plan implements

Settled before this session (do not re-ask):
- **Q17** (BACKLOG-DECISIONS-2026-09-25): `evaluate_all` isolates each watch; one failure skips only that watch.
- **VWAP-CONFIRMATION-LIKE-REGIME-MODELS** (FOLLOWUPS-QUEUE-2026-09-25 (4), open_questions "DECIDED IN PRINCIPLE"):
  the composite `mean_reversion_vwap` confirmation reads **completed bars of the rule/watch's own interval**, the
  **same bars and same answer** on the watch and rule paths, and on **1D/1W** uses the existing
  `mean_reversion_vwap_daily_signal` on **completed daily bars** in both paths.
- **HMM-INTRADAY-4H-HISTORY** (FOLLOWUPS-QUEUE-2026-09-25 (1)): 4h HMM_intraday watches fetch ~180 days.
- **TESTS-PIN-STRATEGY-WATCHES-PATH**: conftest pins `BAMENDJOU_STRATEGY_WATCHES_PATH`.

New, asked this session (recorded as decision `P4B-DECISIONS-2026-09-25`):
- **D1** P4b may edit `routers/chart_alerts.py`, **composite-rule block and its docstring line only** (P4a owns the
  file; P4a has not started). P4a's plan must not rework those lines.
- **D2** VWAP on **4h** = the intraday signal on completed 4h bars; add `"4h"` to
  `mean_reversion_vwap_signal`'s interval allow-list in `strategy_engine.py` (one line; P3a merged).
- **D3** Delivery-gated state: when **no** notification channel is enabled, the watch arms as today (nothing to
  retry). When at least one is enabled and none delivered, the transition is **not** committed and retries next run.
- **D4** (asked after plan round 1, [r1#11]; extended after round 2, [r2#8]) P4b may edit `routers/composite_watch.py`,
  **the `/regime-snapshot` HMM_intraday fetch only**: its history-days argument **and** the D5 spelling translation,
  so the dialog's preview fits on the same series the watch will read.
- **D5** (asked after plan round 1, [r1#2]) The composite **watch** evaluator translates its stored interval to the
  chart/fetch spelling (`1m→1min`, `5m→5min`, `15m→15min`, `30m→30min`; `1h`/`4h`/`1D`/`1W` unchanged) before
  `fetch_intraday_candles` and `completed_bars_for_interval`, so a watch reads the **same bars** a rule of that
  interval reads. Accepted side effect: HMM_intraday watches on 1m/5m/15m move from yfinance regular-hours bars to
  the Tradier-merged series (extended hours included, sandbox feed lag applied) — the rule path's series.
  The stored value is **not** migrated (that is W2-INTERVAL's job); the translation is read-side only.
- **D6** (after plan round 3, [r3#1]) P4b fixes the pre-existing test leak in conftest: an autouse fixture points
  `app.services.notifications.dispatch._SETTINGS_PATH` at a missing tmp file for **every** test, so no test reads
  the real `settings.yaml` or sends real Gmail/Telegram — whichever alias of `load_notification_config` it reaches.
- **D7** (after plan round 3, [r3#3]) **Same bars on 1D too:** a 1D (and 1W) composite **rule** listing
  `mean_reversion_vwap` fetches `completed_daily_rows(get_bars(...))` for VWAP, like the 1D/1W watch — never the
  chart-cache daily candles. rsi/bb/HMM_daily on 1D rules keep `_regime_candles` (unchanged).
- **D8** (after plan round 3) Build from r4 without a plan round 4.

## Files

Owned: `services/strategy_watch_evaluator.py`, `services/composite_trigger_evaluator.py`,
`routers/strategy_watch.py`, `backend/tests/conftest.py`, new/edited tests.
Granted: `routers/chart_alerts.py` (D1: composite block ~:953-1005 + the A4e docstring sentence about VWAP),
`services/strategy_engine.py` (D2: the allow-list tuple only), `routers/composite_watch.py` (D4: the
`/regime-snapshot` HMM_intraday fetch call, :80-82).
Imports of `app.data.market` functions **and of `app.services.composite_trigger_evaluator` functions** in
`strategy_watch_evaluator` **stay lazy (inside the function)** [r3#8] — existing tests patch
`app.data.market.fetch_intraday_candles` / `completed_bars_for_interval` and
`app.services.composite_trigger_evaluator.evaluate_scheduled` / `describe_match` at the source module
(test_composite_sustain.py:117,145; test_strategy_watch_evaluator.py:314-317; test_composite_watch_keyerror.py:48-49).
**Called, not edited:** `data/market.py` (`fetch_intraday_candles`, `completed_bars_for_interval`,
`normalize_interval`), `services/market_session.py` (`completed_session_bars`), `notifications/dispatch.py`
(`load_notification_config`). `strategy_watch_store.py`, `strategy_watch_scheduler.py`, the frontend: **no change**.

## Existing tests this plan changes [r1#1, r1#16]

Baseline [r2 intro]: the build re-measures and records it before T1, over these named files —
`test_strategy_watch_evaluator`, `test_composite_watch_keyerror`, `test_chart_alerts_composite_ws`,
`test_composite_trigger`, `test_a4c_user_alert_completed_bars`, `test_a4g_forming_daily_weekly_bar`,
`test_a4f_hmm_intraday_interval`, `test_composite_sustain`, `test_composite_detailed_parity`,
`test_strategy_watch_router` (round 1 counted 214 passed, round 2 counted 248 passed + 1 skipped on the same tree —
the rounds used different file lists; the build's own number is authoritative). Every change below is listed so the build
does not "discover" them; each is either a **signature update** (no meaning change) or a **deliberate flip** (the
decision changed; comment points at this phase).

| Test | Why it breaks | Change |
|---|---|---|
| `test_a4c_user_alert_completed_bars.py:97` (U1 lambda), `:186`, `:218` (`_run`, U3) | lambdas `(names, d, i, direction="Bullish")` reject the new `interval`/`bars_vwap_daily` kwargs; on the rule path the TypeError is swallowed (chart_alerts.py:1003) so `seen` stays empty | signature: add `**kw` |
| `test_a4c...:103` `assert seen_strat == [intraday]` | pinned "VWAP gets the whole series" | **flip**: assert completed bars (`intraday[:-1]` for the fixture's forming bar) |
| `test_a4c...::test_u3_vwap_confirmation_keeps_the_forming_candle` (:211-226) | pinned the old decision | **flip + rename** `..._reads_completed_bars`; assert `seen == [candles[:-1]]` |
| `test_a4g_forming_daily_weekly_bar.py:257-262` (`_strat`) | same lambda shape; `:274 strat_daily == [expected]` fails for 1D/1W | signature: add `**kw` (the assertion keeps its meaning: rsi/bb still read the daily list) |
| `test_composite_watch_keyerror.py:268` (`_call`) | default `interval=None` → VWAP never judged → not starved → `:293-296` and `:331-332` get False instead of None | pass `interval="15m"` in `_call` (keeps the pins' meaning; not weakened) |
| `test_composite_watch_keyerror.py:357-373` (intraday outage end-to-end) | store default `'1D'` → after T5 no intraday fetch; `side_effect=[_bars(300), [], []]` never consumed; test passes vacuously | create the watch with `interval="15m"`; the healthy intraday stub returns bars with **int unix timestamps in the past** [r2#13] (string times are all dropped by `completed_bars_for_interval`, market.py:589-593, so r2's fix modelled an outage on every run); assert the intraday stub **was called** |
| `test_strategy_watch_evaluator.py:352-365` | patches `evaluate_all`; T3's `evaluate_and_notify` calls `_collect`, so result `[]` | patch `_collect` returning `[_Transition(ev, id, state)]`; assert `result == [ev]` |
| `test_strategy_watch_evaluator.py:326-351` (`..._fetches_intraday_for_vwap_confirmation_even_when_model_not_hmm_intraday`) [r2#4] | `_composite_watch()` (:294-301) has no `interval` → '1D' after T5 → no intraday fetch → `assert_called_once` fails | give the watch `interval="15m"`; add a 1D mirror asserting **no** intraday fetch |
| `test_a4f_hmm_intraday_interval.py:219` (`test_b2d_evaluator_fetches_migrated_watch_at_5m`) [r2#3] | asserts fetch `interval == "5m"`; D5 sends `"5min"` | **flip**: assert `"5min"`, comment cites D5 |
| `test_chart_alerts_composite_ws.py:188` | daily rule → `bars_intraday []` | **flip**: daily variant on completed daily bars |
| any test feeding a composite **watch** ISO-string daily bars and relying on the last bar | T5's `completed_daily_rows` drops today's bar only when `now` is before today's close; tests whose last bar is dated **today** with no `now` injected become clock-dependent | build greps the touched files for `date.today()`-built fixtures and injects `now`; each hit is added to this table |

The build runs the full backend suite after T3 and after T5 and adds any breakage not in this table to it
(with its reason) before fixing — no silent edits.

---

## T1 — conftest pin + dedup docstring (TESTS-PIN-STRATEGY-WATCHES-PATH, open_questions [6], [9])

1. Next to `BAMENDJOU_SCAN_SCHEDULE_PATH` (before any app import):
   `os.environ.setdefault("BAMENDJOU_STRATEGY_WATCHES_PATH", Path(_TEST_DB_DIR, "test_strategy_watches.yaml").as_posix())`
   with a comment in the same style (module-level store built at import; `load()` can rewrite the file via the A4f
   migration; setdefault so the two tests' monkeypatch still wins).
   `_TEST_DB_DIR` is `tempfile.mkdtemp()` per run (conftest.py:46), so no watches leak between runs.
2. `_isolate_alert_dedup_state` docstring: replace the single measured count with the honest record — round 3
   measured **two** refusal keys, round 4 measured **four** on a later tree (headwind:AAPL, headwind:NVDA,
   sizing-config, regime-gate-config); the count depends on which alert-reaching tests exist, so no number is pinned.
   No code change.
3. **D6 [r3#1]** autouse fixture `_no_real_notification_settings(tmp_path, monkeypatch)`:
   `monkeypatch.setattr(dispatch, "_SETTINGS_PATH", tmp_path / "no-settings.yaml")` (the file never exists →
   `load_notification_config()` returns `{}`, dispatch.py:52-58). `load_notification_config` reads the module global
   at call time, so this covers the evaluator's import, `notify_enabled_channels` and chart_alerts.py:33's alias.
   Tests that need channels enabled patch the **evaluator's** `load_notification_config` name (T3).
   Test: `load_notification_config() == {}` inside a test, and `chart_alerts._load_notification_config() == {}`.
   The test also asserts `dispatch._SETTINGS_PATH` is under the test's `tmp_path`. Mutation: remove the fixture →
   that assertion fails.

Test: `test_conftest_pins_strategy_watches_path` — `os.environ["BAMENDJOU_STRATEGY_WATCHES_PATH"]` is not the
tracked `config/strategy_watches.yaml` and `strategy_watch_store._path` resolves outside `backend/config`.
Mutation: delete the pin → fails.

## T2 — per-watch isolation (Q17, open_questions [64])

Refactor the two loop bodies of `evaluate_all` into `async def _eval_strategy_watch(w, start, end, sustain_minutes)`
and `async def _eval_composite_watch(w, start, end, now_ts, now_dt)` (the clock of T5 [r3#7]), each returning `_Transition | None`
(see T3). Each loop becomes:

```python
for w in watches:
    try:
        t = await _eval_strategy_watch(w, start, end, sustain_minutes)
    except Exception:
        logger.error("strategy-watch: %s failed, skipped this run", w.get("id"), exc_info=True)
        continue
```

`list_watches()` is read once per loop (as today). Behaviour of every existing branch is unchanged — this is a
move, not a rewrite; the existing inner try/excepts stay.

Tests [r1#14] — a bad watch sits between two healthy ones; both healthy watches fire and have their state written;
the bad one's state is untouched. One test per loop:
- strategy loop: `last_state="x"` → `dict(w["last_state"])` (evaluator :128) raises ValueError, uncaught today.
- composite loop: `evaluate_scheduled` patched True and **every** daily bar's `close="bad"` [r2#10] →
  `float(bars[-1]["close"])` (:333) raises ValueError, uncaught today. (Every bar, not just the last: after T5
  the completed-daily trim may drop the last bar, and the test must keep raising.) This test is re-run after T5. (`dict(w.get("last_state") or {})` tolerates
  None, and `describe_match`/`format_composite_reason` sit inside a try, so neither works as the trigger.)
Mutation: remove the try → test fails with the exception.

## T3 — commit state only after delivery; one run at a time (open_questions [3])

1. `@dataclass class _Transition: event: WatchEvent; watch_id: str; new_state: dict`.
   The two per-watch functions return a `_Transition` instead of calling `update_state` for the **event** write.
   Non-event writes (`pending_entry_since` start/reset, composite armed→idle re-arm, corrupt-sustain restart) stay
   immediate: they send nothing, so there is nothing to gate.
2. `async def _collect(sustain_minutes) -> list[_Transition]` = the two isolated loops.
3. `_commit(t)`: `update_state` wrapped in try/except + `logger.error` [r1#9], so one failed write does not abort the
   remaining commits (which would re-send already-delivered alerts next run).
4. `evaluate_all(sustain_minutes=0)` keeps its public contract: `_collect`, then `_commit` every transition, return
   events. (All existing tests call it and expect state written.)
5. `evaluate_and_notify(sustain_minutes=0)`:
   ```python
   async with _run_lock():
       transitions = await _collect(sustain_minutes)
       any_channel = _any_channel_enabled()
       for t in transitions:
           subject, plain, html = _format_event(t.event)
           try:
               delivered = await notify_enabled_channels(subject, plain, html)
           except Exception:
               logger.error(...); delivered = False
           if delivered or not any_channel:          # D3
               _commit(t)
           else:
               logger.warning("strategy-watch: %s %s not delivered; state kept, retries next run", ...)
       return [t.event for t in transitions]
   ```
   `_any_channel_enabled()` [r1#5]: imports `load_notification_config` **into the evaluator module** (so T1's fixture
   patches it) and returns `_enabled(cfg.get("gmail")) or _enabled(cfg.get("telegram"))`, where `_enabled(b)` is
   `isinstance(b, dict) and bool(b.get("enabled"))` — a `gmail: null` or non-dict block is "disabled", never a raise.
   A non-dict `cfg` (e.g. `notifications: null` → None, dispatch.py:55) is treated as `{}` → False [r3#5].
   Only a genuine exception from the reader → `True` (fail toward "gate on delivery": an unreadable config must not
   silently commit undelivered alerts). Read once, before sending.
   - Returned events are **all** fired events (delivered or not) — `/evaluate` reports what fired.
   - Retry semantics: an undelivered strategy-watch entry stays `idle` (with `pending_entry_since` if sustain is on,
     so the retry is not re-delayed); an undelivered exit stays `armed`; a composite stays un-armed and re-fires
     while its condition holds.
6. **Notification config pin** — superseded by T1.3 (D6, [r3#1]): the r3 fixture patched two function names and
   missed chart_alerts.py:33's alias; pinning `dispatch._SETTINGS_PATH` covers all of them.
7. `_run_lock()`: a module-level `asyncio.Lock`, created lazily **per running loop**
   (`_lock_loop`, `_lock` globals; recreate when `asyncio.get_running_loop()` differs) so pytest's per-test event
   loops never meet a lock bound to a dead loop. Both `run_now()` and the scheduler go through
   `evaluate_and_notify` on one loop, so both are serialised; the second run waits, then sees the committed state.

Tests:
- channels enabled (fixture override), `notify_enabled_channels` → False: event returned, state **unchanged**;
  next call → True: state armed. (strategy entry, strategy exit_stop, composite entry.)
- `notify_enabled_channels` raises: same as False.
- no channel enabled (T1 fixture default `{}`), notify → False: state **armed** (D3).
- `_any_channel_enabled` with `{"gmail": None, "telegram": "x"}` → False, no raise; reader returns None → False
  [r3#5]; reader raises → True.
- delivered → True: state armed (regression of today's behaviour).
- `_commit`: `update_state` raises for the first of two transitions → the second is still committed.
- `evaluate_all` still writes state with no notify call (contract kept).
- lock [r1#4]: two concurrent `evaluate_and_notify()` via `asyncio.gather` on one idle **composite** watch whose
  condition holds (composite, not strategy: an armed strategy watch whose stub always fires would fire a reversal
  on run 2). The notify stub **`await asyncio.sleep(0)`** before returning True and counts calls, so without the
  lock the two runs interleave between collect and commit. → exactly **1** send; run 2's result is `[]`.
  Mutation check performed during the build: remove the lock → test sends **2** (recorded in the commit message).
Mutations: drop the `delivered or not any_channel` guard (always commit) → undelivered test fails; drop
`not any_channel` → D3 test fails; remove the lock → concurrency test sends 2; drop `_commit`'s try → commit test
fails.

## T4 — 4h history (HMM-INTRADAY-4H-HISTORY, open_questions [7])

In `composite_trigger_evaluator.py` (importable without touching the store):

```python
_INTRADAY_HISTORY_DAYS = {"4h": 180}
def intraday_history_days(interval: str) -> int:
    from app.data.market import normalize_interval
    return _INTRADAY_HISTORY_DAYS.get(normalize_interval(interval), 55)
```

Also here (one home for both, used by the watch and the snapshot) [r2#8]:

```python
_WATCH_TO_FETCH_INTERVAL = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min"}   # D5
def watch_fetch_interval(interval: str) -> str:
    return _WATCH_TO_FETCH_INTERVAL.get(interval, interval)
```

Used by the composite-watch fetch in `strategy_watch_evaluator` and by `routers/composite_watch.py`
`/regime-snapshot` (D4): `iv = watch_fetch_interval(interval)`, then
`completed_bars_for_interval(fetch_intraday_candles(symbol, interval=iv, days=intraday_history_days(iv)), iv)`.
The dialog's snapshot and the watch then read the same series **and** the same history.

Bar counts [r1#12], corrected: 180 days → yfinance "6mo" of 1h resampled to 4h on epoch-aligned buckets
(market.py:266): 2 bars per session in EDT, 3 in EST → ~125 sessions ≈ **250–375** bars > `regime_hmm.MIN_BARS`
200. 1h stays 55 days → yfinance "60d" (market.py:283-292) ≈ 41 sessions × 7 ≈ **~287** bars > 200.

Tests: `fetch_intraday_candles` stub records `days`; a 4h HMM_intraday watch requests 180, a 15m one 55;
`/regime-snapshot?model=HMM_intraday&interval=4h` requests 180; `/regime-snapshot?...&interval=15m` fetches
`interval="15min"` (D4 extension; mutation: drop the map in the router → fails). The defect marker
`fetch_intraday_candles(symbol, interval=interval, days=55)` disappears from the evaluator.
Mutation: map 4h → 55 → test fails.

## T5 — VWAP confirmation like the regime models (VWAP-CONFIRMATION-LIKE-REGIME-MODELS, open_questions [4], [56] VWAP half)

### Evaluator (`composite_trigger_evaluator.py`)

1. Interval → which VWAP variant, one function used by the matcher **and** the starved count:
   ```python
   _VWAP_SIGNAL_INTERVAL = {"1m": "1m", "1min": "1m", "5m": "5m", "5min": "5m", "15m": "15m", "15min": "15m",
                            "30m": "30m", "30min": "30m", "1h": "1h", "60m": "1h", "4h": "4h"}
   def _strategy_bar_type(key: str, interval: str | None) -> str | None:
       # rsi/bb -> "daily" (unchanged)
       # vwap -> "intraday" if interval in _VWAP_SIGNAL_INTERVAL
       #         "daily"    if normalize_interval(interval) in ("daily", "weekly")
       #         None       otherwise (None/unknown interval: cannot be judged -> never matches, logged once)
   ```
   `_KNOWN_STRATEGY_BAR_TYPE` is replaced by `_strategy_bar_type` (its only use is the starved count).
2. `_matched_strategy_signals(keys, bars_daily, bars_intraday, direction, interval=None, bars_vwap_daily=None)`:
   - rsi/bb: unchanged.
   - vwap intraday: `mean_reversion_vwap_signal(slice, direction=direction, interval=_VWAP_SIGNAL_INTERVAL[iv])`
     over `bars_intraday`. **The defect marker line `fn(slice_bars, direction=direction)` is gone.**
   - vwap daily: `mean_reversion_vwap_daily_signal(slice, direction=direction)` over **`bars_vwap_daily` only**
     (D7, [r3#3]) — no fallback to `bars_daily`. `bars_vwap_daily is None` → VWAP not matched and not starved
     (fail closed). Every 1D/1W caller (watch and rule) passes completed `get_bars` rows there, so the daily variant
     never reads chart-cache candles or weekly bars [r1#6].
   - vwap with bar type None: skipped.
   - The ≥60-bar floor, the 3-bar lookback and the 120-bar slice stay as they are for both variants.
   - [r2#11] The loop calls one local `call = partial(fn, direction=direction, **extra)` built per key
     (`extra = {"interval": ...}` for intraday VWAP, `{}` otherwise) and tests `if call(slice_bars) is not None:` —
     so the defect-marker line `if fn(slice_bars, direction=direction) is not None:` is gone for **every** key,
     rsi/bb included. The build greps for the marker after T5.
6. **`completed_daily_rows(bars, now: datetime) -> list[dict]`** [r2#1] — new helper, the completed-daily trim for
   `get_bars` output. `get_bars` rows carry `time` as an **ISO date string** (historical_store.py:157), which
   `completed_session_bars` treats as undatable and pops (market_session.py:264-271) — it would drop the last
   **completed** bar every run. The helper: `close = market_session.last_session_close(now)`; walk trailing bars and
   drop a bar while it is after `close` — a `str` time compared as `date.fromisoformat(t[:10]) > close.date()`, an
   `int` (non-bool) time as `t > close.timestamp()`; any other `time` on the last bar, **or a `str` that
   `fromisoformat` rejects (ValueError) [r3#6]**, → drop that bar only and stop (fail closed, same as A4g). Order preserved, input not mutated. `completed_session_bars` itself is not touched.
3. `interval` (and `bars_vwap_daily`) keyword params are added to `_check_strategy_signals`,
   `evaluate_from_context`, `evaluate_from_context_detailed`, `evaluate_scheduled`, `describe_match` and threaded
   straight through. Default `None` = VWAP never matches (fail closed, like today's 1D rule path) — every in-repo
   caller passes it after this change.
4. `evaluate_scheduled`'s starved count uses `_strategy_bar_type(key, interval)` and **the same bar list the matcher
   would read** — one private `_vwap_bars(interval, bars_intraday, bars_vwap_daily)` used by both
   (so a 1D watch with < 60 daily bars is "no reading", not "False"; `bars_vwap_daily` short → starved,
   i.e. "no reading" under `unknown_as_none`; `bars_vwap_daily` None → not starved) [r2#2, r3#3].
   `describe_match`'s gate becomes `if strategy_keys and (bars_daily or bars_intraday or bars_vwap_daily)` [r3#10].
5. The **caller supplies completed bars**; the evaluator does not trim. Docstrings of `evaluate_from_context` /
   `evaluate_scheduled` drop "strategy confirmations keep bars_intraday (regime models only)" and say: bars_intraday
   must be completed bars of `interval`.

### Watch path (`strategy_watch_evaluator._eval_composite_watch`)

```python
interval = w.get("interval", "1D")                                    # [r1#15] the store's default
fetch_iv = watch_fetch_interval(interval)                             # D5 (T4 helper)
bars = completed_daily_rows(await get_bars(symbol, start, end), now_dt)   # [r1#3, r2#1]
vwap_intraday = "mean_reversion_vwap" in confirmations and _strategy_bar_type("mean_reversion_vwap", fetch_iv) == "intraday"
needs_intraday = model == "HMM_intraday" or vwap_intraday
if needs_intraday:
    raw = fetch_intraday_candles(symbol, interval=fetch_iv, days=intraday_history_days(fetch_iv))
    bars_intraday = completed_bars_for_interval(raw, fetch_iv, now=now_ts)          # [r2#6]
vwap_daily = bars if normalize_interval(fetch_iv) in ("daily", "weekly") else None   # [r2#2, r3#3] D7
evaluate_scheduled(symbol, trigger_def, bars, bars_intraday,
                   regime_bars_intraday=bars_intraday if model == "HMM_intraday" else None,
                   interval=fetch_iv, bars_vwap_daily=vwap_daily, unknown_as_none=True)
describe_match(..., bars_intraday=bars_intraday, interval=fetch_iv, bars_vwap_daily=vwap_daily)
```
- **Clock [r2#6]:** `_collect(sustain_minutes, now_ts: float | None = None)` takes one instant —
  `now_ts = time.time()` if None — and derives `now_dt = datetime.fromtimestamp(now_ts, MARKET_TZ)` (aware, what
  `last_session_close` needs). `now_ts` goes to `completed_bars_for_interval` (float, market.py:621-624), `now_dt`
  to `completed_daily_rows`. `evaluate_all`/`evaluate_and_notify` pass through an optional `now_ts` (tests inject it;
  the scheduler and `run_now` pass nothing). The sustain clock keeps `datetime.now(timezone.utc)` (unchanged).
- [r1#3, r2#1] `get_bars(..., end=today)` can persist today's forming daily bar (Alpaca date-only end, per the A4g
  record); `completed_daily_rows` drops it while the session is open. **Limit [r3#9]:** `get_bars` never re-fetches a
  stored bar (historical_store.py:229), so a forming bar stored mid-session is kept after the close as "completed"
  though it is a snapshot — the A4g open question (a) on the Alpaca date-only `end`; not fixed here, cited. This applies to **all** consumers of
  the composite watch's daily bars (OMM/HMM_daily, rsi/bb, VWAP daily). Strategy (non-composite) watches are
  unchanged.
- 1D/1W watch [r2#2, r3#3]: VWAP runs the daily variant on the completed daily `bars` (passed as `bars_vwap_daily`).
- A **1D/1W** watch no longer fetches "intraday" bars at its daily interval; VWAP reads `bars` through the daily
  variant.
- The HMM fit already read completed bars; only the VWAP read moves from raw to completed, and (D5) the source
  series becomes the rule path's.

### Rule path (`routers/chart_alerts.py` composite block, D1)

- Intraday rules: `bars_intraday=_regime_candles` (completed bars of the rule's interval, as the HMM already uses)
  instead of `_model_candles` (forming bar included). `_model_candles` is then unused → removed.
- 1D rules: rsi/bb/HMM_daily keep `_bars_daily = _regime_candles` (no change). **VWAP (D7, [r3#3])** reads
  `bars_vwap_daily`, fetched as for 1W below.
- Intraday rules' daily bars [r2#9]: the existing `_bars_daily = await get_bars(...)` branch (chart_alerts.py:973-976,
  inside D1) becomes `completed_daily_rows(await get_bars(...), _as_of_dt)`, so an intraday rule's rsi/bb read the same
  completed daily bars as an intraday watch.
- 1D and 1W rules (D7): `_regime_candles` are chart-cache daily (1D) or **weekly** (1W) bars, so for a rule listing
  `mean_reversion_vwap` fetch
  `get_bars(symbol, today-730d, today)` once per tick (only if some composite row lists VWAP), pass it through
  `completed_daily_rows(..., _as_of_dt)` [r1#3, r2#1, r2#7] (the block's existing aware datetime,
  chart_alerts.py:892 — never the float `as_of`), and pass it as `bars_vwap_daily`. On a `get_bars` failure
  `bars_vwap_daily = []` [r1#6] (fail closed: VWAP not matched; logged), never None.
  rsi/bb/HMM_daily on 1W keep reading weekly bars (pre-existing, out of scope — logged, not changed).
- Pass `interval=interval` to `evaluate_from_context_detailed`.
- The A4e docstring sentence "The VWAP confirmation keeps the forming bar by decision (A4C-FOLLOWUPS-LOCKED-2026-09-24)"
  becomes "The VWAP confirmation reads completed bars too (VWAP-CONFIRMATION-LIKE-REGIME-MODELS, 2026-09-25)".

### Strategy engine (D2)

`if interval not in ("1m", "5m", "15m", "30m", "1h"):` → add `"4h"`; docstring "(intraday only)" unchanged.
Existing `test_strategy_engine` 1D/weekly → None tests still hold; stock_scan passes `'15m'` only (stock_scan.py:185).

### Tests (new file `tests/test_p4b_vwap_like_regime_models.py`)

Every test here that reaches `completed_bars_for_interval` pins `monkeypatch.setattr(app.data.market,
"intraday_feed_lag_seconds", lambda: 0)` [r3#4] (the lag reads `TRADIER_BASE_URL` from a developer `.env`), plus one
test with the lag at 900 on '15min' asserting the extra bar is dropped on **both** paths (parity holds).
Fixture bars built so the intraday VWAP signal fires on bar[-1] only when the forming bar is **included** (and a
mirror set that fires only on completed bars), plus a daily set that fires the daily variant.
1. Watch, stored '15m', forming bar present: stub `fetch_intraday_candles` (int unix times) + injected `now_ts`
   (reaches `completed_bars_for_interval`, [r2#6]) → VWAP matched only on
   completed bars (forming-only setup → not fired; completed setup → fired).
2. Rule path, '15min': same candles through `evaluate_and_notify_for_symbol` with `as_of` → same answer as (1).
   **Parity test:** for each fixture, watch-path result == rule-path result.
3. D5 spelling [r1#2]: a watch stored '15m' calls `fetch_intraday_candles(interval="15min", ...)` and
   `completed_bars_for_interval(..., "15min")` (spies); '5m' → '5min'; '4h' → '4h'. Mutation: drop the map →
   fails. (This is the part the stubbed parity test cannot see — the real series differ by spelling.)
4. `interval` threaded: spy on `mean_reversion_vwap_signal` records `interval="15m"` for a '15min' rule and
   `"4h"` for a 4h watch.
5. 1D watch: no `fetch_intraday_candles` call; the daily variant is called on `bars` (spy); fires on the daily set.
   All daily fixtures use **ISO-string** times, as `get_bars` does in production [r2#1]:
   (a) `now_ts` mid-session, last bar dated today → that bar is **not** read;
   (b) `now_ts` after 16:00 ET, last bar dated today → that bar **is** read (the completed bar is kept);
   (c) `now_ts` on a Saturday, last bar dated Friday → kept.
   Mutation: swap `completed_daily_rows` for `completed_session_bars` → (b) and (c) fail.
6. 1D rule [r3#3]: `get_bars` stub called; the daily variant reads its completed rows, **not** `_regime_candles`
   (the chart candles are given a different, non-firing series); same answer as (5) on the same `get_bars` rows.
7. 1W rule, called with a **real float `as_of`** [r2#7]: `get_bars` stub called; daily variant reads it (not the
   weekly candles). 1W **watch** on the same daily bars → same answer (daily variant on `bars_vwap_daily=bars`)
   [r2#2]. `get_bars` raising on the rule path → VWAP not matched, no exception, and the daily variant is **not**
   called on weekly bars [r1#6]. Mutation: pass `as_of` instead of `_as_of_dt` → the real-`as_of` case fails.
7b. Intraday rule (15min) listing rsi: the `get_bars` rows reach the matcher through `completed_daily_rows`
   (forming daily bar dropped at a mid-session `as_of`) [r2#9].
7c. `completed_daily_rows` unit tests: string times, int times, mixed, a non-str/non-int last `time` (dropped,
   earlier bars kept), a non-ISO string last `time` ("t5") dropped without raising [r3#6], empty list, input not mutated.
8. 4h: the intraday signal no longer returns None on `interval="4h"` for a firing fixture.
9. Starved [r3#2]: trigger `primary {"model": "any"}`, `min_confirmations 0`, VWAP required. (a) 1D watch, 30
   completed daily bars → `evaluate_scheduled(..., unknown_as_none=True)` is None. (b) 1D, ≥ 60 completed daily bars,
   `bars_intraday=[]`, daily variant stubbed to None → **False** (the mutation "`_vwap_bars` reads bars_intraday" gives
   None here). (c) unknown interval ('2h') → False (not None).
10. Missing `interval` key on a composite watch → treated as '1D' (store default), no intraday fetch [r1#15].
Plus the existing-test flips in the table above.
Mutations: pass raw instead of completed bars (watch) → test 1 fails; revert rule path to `_model_candles` → test 2
fails; drop the D5 map → test 3 fails; drop `interval=` in the matcher → test 4 fails; route 1D VWAP to intraday →
test 5 fails; drop `completed_daily_rows` on the watch → test 5(a) fails [r3#7]; remove the 1W
`bars_vwap_daily` or set it to None on failure → test 7 fails; remove "4h" from the allow-list → test 8 fails.

## T6 — momentum confirmations read a number, no crash (open_questions [61])

1. Evaluator: `_matched_confirmations` momentum branch accepts only a real number
   (`isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)`); anything else is "not
   matched" (debug log) — never a TypeError.
2. Evaluator: new pure helper `indicator_values_at(indicators: dict, t) -> dict[str, float]` → for each series the
   `value` of the point whose `time == t` (search from the end; missing/None → key omitted).
3. Rule path (D1): composite call passes `indicator_values_at(indicators, closed_candle.get("time"))` instead of
   the series dict — the closed candle's value, consistent with A4e.
Tests: series dict → momentum matched when the closed-candle point ≥ min_confidence, not matched when only the
forming point is; a list value passed directly → no exception, not matched. Mutation: read `series[-1]` → the
forming-point test fails.

**Scope honesty [r1#7]:** this fixes the crash/garbage read only. Composite momentum kinds
(`volume_spike`/`rsi_cross`/`macd_cross`, schemas/composite_trigger.py:21) still **never match on either path**:
`compute_indicators_for_conditions` computes only names referenced by standard-rule indicator conditions
(indicator_compute.py:11-24; called at chart_alerts.py:901-905, outside D1) and the watch path passes `{}`
(composite_trigger_evaluator.py:433). open_questions[61] is closed with that stated, and a **new open question**
"composite momentum confirmations never match on either path" is added — not implied fixed.

## T7 — GET /api/strategy-watch/ lists strategy watches only (open_questions [65])

`list_watches` endpoint returns `[w for w in store.list_watches() if w.get("watch_type") != "composite"]`.
Composites stay listed by `/api/composite-watches/`. The only consumer (`strategyWatchStore` → strategy-watch
page, api.ts:799-800) never handled composites. PATCH/DELETE by id are unchanged.
Test: store holding one strategy + one composite → GET returns only the strategy row. Mutation: drop the filter.

---

## Out of scope — logged, not fixed

- 1W composite rules feed **weekly** bars to rsi/bb/HMM_daily while 1W watches feed daily (pre-existing A4g choice).
- A composite whose condition flips false while undelivered re-arms to idle and loses the undelivered alert
  (inherent: the alert is about a condition that no longer holds).
- **D3 under the default EOD schedule [r1#8]:** "retries next run" means the **next day** (the scheduler runs once
  per date, strategy_watch_scheduler.py:57-68). An undelivered **exit** whose price reverts overnight is never
  alerted, and the watch **stays armed** — it re-checks only stop/target/reversal, so new entries on that watch are
  blocked until one of those fires. Accepted under D3; recorded as an open question so Kenneth can revisit.
- **HMM_intraday history differs by path [r1#13]:** watches fetch 55 days (180 on 4h); rules use chart_cache's
  730 days on 1h/4h (chart_cache.py:38, :83-84), capped at 1500 bars. The same symbol/interval can fit a different
  HMM on the watch and the rule, and `/regime-snapshot` matches the watch, not a rule. Logged as an open question.
- `open_questions[9]` counts are recorded, not re-measured (T1).
- Stale mid-session daily bar kept after the close by `get_bars` [r3#9] — A4g open question (a), cited, not fixed.
- **dispatch null block [r2#12]:** with `gmail: null` and telegram enabled, `notify_enabled_channels` raises at
  `gmail.get` before telegram is tried (dispatch.py, not P4b's file); `_any_channel_enabled` returns True, so the
  transition is never committed and retries every run. T3 logs the raise; a new open question records the dispatch
  bug for its owner.

## PROJECT_STATE.json [r1#10]

`state.py` semantics (scripts/state.py:87-110): `defect_marker` = shipped when the pattern is **gone**;
`absent`/`present` = shipped when the pattern is **found**; drift = declared status ≠ probe. So statuses must move
**in the same commit** that changes the probe's answer:

- Decision `P4B-DECISIONS-2026-09-25` gains D4 and D5 (r2), D6-D8 (r4).
- T1's commit: TESTS-PIN-STRATEGY-WATCHES-PATH (`absent` of `BAMENDJOU_STRATEGY_WATCHES_PATH` in conftest) →
  `shipped_unaudited` (the pattern is now found). Its `kind` stays `absent`.
- T4's commit: HMM-INTRADAY-4H-HISTORY (defect_marker `fetch_intraday_candles\(symbol, interval=interval, days=55\)`)
  → `shipped_unaudited`. Kind stays `defect_marker`.
- T5's commit: VWAP-CONFIRMATION-LIKE-REGIME-MODELS (defect_marker on
  `if fn\(slice_bars, direction=direction\) is not None:`) → `shipped_unaudited`. Kind stays `defect_marker`.
  (r1 and the handoff said "flip to `absent` on merge" — wrong: `absent` of a gone pattern would read NOT BUILT.)
- The umbrella P4B-STRATEGY-COMPOSITE-WATCHES shares that marker, so it would read BUILT at T5 while T6/T7 are
  unbuilt [r2#11]. In **this r3 commit** its verify moves to a marker that disappears only at T7:
  `defect_marker` of `return strategy_watch_store\.list_watches\(\)` in `backend/app/routers/strategy_watch.py`
  (the build confirms the exact line before committing; T7 replaces it with the filtered comprehension), and its
  note drops the stale "On merge this flips to kind 'absent'" sentence. It goes `shipped_unaudited` in T7's commit.
- Plan rounds are recorded on the P4B entry as they run [r2#11]: `audit_rounds` counts plan + code rounds,
  `audit_clean` stays false until a clean **code** round; each round's verdict goes in the entry's note.
- After the clean code round: those four → `shipped` with `audit_rounds`/`audit_clean` filled.
- On merge: open_questions [3], [4], [6], [7], [9], [61] (with the T6 scope note), [64], [65] and the [56] VWAP half →
  closed_questions with evidence (indices shift; match by opening words). New open questions: composite momentum
  never matches (T6), D3 EOD stuck-armed exit, HMM_intraday history differs by path.
- `python3 scripts/state.py` exits 0 after every commit.

## Verify

`cd backend && .venv/bin/python -m pytest -q` (full suite; the 10-file touched set was 214 passed at baseline);
`cd frontend && npx tsc --noEmit && npx jest` (no frontend change expected); `python3 scripts/state.py` exit 0.
No test writes `backend/config/*.yaml`, reads `backend/config/settings.yaml`, or runs the real lifespan.
