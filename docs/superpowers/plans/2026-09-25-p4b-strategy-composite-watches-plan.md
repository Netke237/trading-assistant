# P4b — Strategy & composite watches (plan r1)

Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § P4b. Branch `claude/cool-heisenberg-6lsa3a`,
off `origin/main` 2f67e6f. Claim `P4B-STRATEGY-COMPOSITE-WATCHES`.

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

## Files

Owned: `services/strategy_watch_evaluator.py`, `services/composite_trigger_evaluator.py`,
`routers/strategy_watch.py`, `backend/tests/conftest.py`, new/edited tests.
Granted by D1/D2: `routers/chart_alerts.py` (composite block ~:953-1005 + the A4e docstring sentence about VWAP),
`services/strategy_engine.py` (the allow-list tuple only).
Unowned by any package, touched for one call-site: `routers/composite_watch.py` (`/regime-snapshot` HMM_intraday
fetch days — T4). `strategy_watch_store.py`, `strategy_watch_scheduler.py`, the frontend page: **no change needed**.

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

Test: `test_conftest_pins_strategy_watches_path` — `os.environ["BAMENDJOU_STRATEGY_WATCHES_PATH"]` is not the
tracked `config/strategy_watches.yaml` and `strategy_watch_store._path` resolves outside `backend/config`.
Mutation: delete the pin → fails.

## T2 — per-watch isolation (Q17, open_questions [64])

Refactor the two loop bodies of `evaluate_all` into `async def _eval_strategy_watch(w, start, end, sustain_minutes)`
and `async def _eval_composite_watch(w, start, end)`, each returning `_Transition | None`
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

Tests: a watch whose `get_bars` stub raises a non-caught error *after* fetch (e.g. malformed `last_state` →
`dict(None)` TypeError) sits between two healthy watches; both healthy watches still fire and have their state
written; the bad one's state is untouched. One test per loop (strategy, composite).
Mutation: remove the try → test fails with the exception.

## T3 — commit state only after delivery; one run at a time (open_questions [3])

1. `@dataclass class _Transition: event: WatchEvent; watch_id: str; new_state: dict`.
   The two per-watch functions return a `_Transition` instead of calling `update_state` for the **event** write.
   Non-event writes (`pending_entry_since` start/reset, composite armed→idle re-arm, corrupt-sustain restart) stay
   immediate: they send nothing, so there is nothing to gate.
2. `async def _collect(sustain_minutes) -> list[_Transition]` = the two isolated loops.
3. `evaluate_all(sustain_minutes=0)` keeps its public contract: `_collect`, then `update_state` for every
   transition, return events. (All existing tests call it and expect state written.)
4. `evaluate_and_notify(sustain_minutes=0)`:
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
               strategy_watch_store.update_state(t.watch_id, t.new_state)
           else:
               logger.warning("strategy-watch: %s %s not delivered; state kept, retries next run", ...)
       return [t.event for t in transitions]
   ```
   `_any_channel_enabled()` reads `load_notification_config()` (the same function `notify_enabled_channels` reads)
   and returns `gmail.enabled or telegram.enabled`. Read once, before sending.
   - Returned events are **all** fired events (delivered or not) — `/evaluate` reports what fired.
   - Retry semantics: an undelivered strategy-watch entry stays `idle` (with `pending_entry_since` if sustain is on,
     so the retry is not re-delayed); an undelivered exit stays `armed` and re-evaluates the stop/target next run
     (if price came back, no exit fires — accepted: the alert reflects the current price); a composite stays
     un-armed and re-fires while its condition holds.
5. `_run_lock()`: a module-level `asyncio.Lock`, created lazily **per running loop**
   (`_lock_loop`, `_lock` globals; recreate when `asyncio.get_running_loop()` differs) so pytest's per-test event
   loops never meet a lock bound to a dead loop. Both `run_now()` and the scheduler go through
   `evaluate_and_notify`, so both are serialised; the second run waits, then sees the committed state.

Tests:
- channels enabled, `notify_enabled_channels` → False: event returned, state **unchanged**; next call → True:
  state armed. (strategy entry, strategy exit_stop, composite entry.)
- `notify_enabled_channels` raises: same as False.
- no channel enabled (config both disabled), notify → False: state **armed** (D3).
- delivered → True: state armed (regression of today's behaviour).
- `evaluate_all` still writes state with no notify call (contract kept).
- lock: two concurrent `evaluate_and_notify()` via `asyncio.gather` on one idle watch whose signal fires, notify
  stub counts calls → exactly **1** send; the second run's result is `[]`.
Mutations: drop the `delivered or not any_channel` guard (always commit) → undelivered test fails; drop
`not any_channel` → D3 test fails; remove the lock → concurrency test sends 2.

## T4 — 4h history (HMM-INTRADAY-4H-HISTORY, open_questions [7])

In `composite_trigger_evaluator.py` (importable without touching the store):

```python
_INTRADAY_HISTORY_DAYS = {"4h": 180}
def intraday_history_days(interval: str) -> int:
    from app.data.market import normalize_interval
    return _INTRADAY_HISTORY_DAYS.get(normalize_interval(interval), 55)
```

Used by the composite-watch fetch in `strategy_watch_evaluator` and by `routers/composite_watch.py`
`/regime-snapshot` (so the dialog's snapshot and the watch read the same history). 180 days →
`_days_to_yf_period` "6mo" of yfinance 1h resampled to 4h: ≈ 2 completed 4h bars per session × ~125 sessions
≈ 250 > `regime_hmm.MIN_BARS` 200. 1h stays 55 (~380 bars, per the record).

Tests: `fetch_intraday_candles` stub records `days`; a 4h HMM_intraday watch requests 180, a 15m one 55;
`/regime-snapshot?model=HMM_intraday&interval=4h` requests 180. The defect marker
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
   The mapping keeps both '5m' and '5min' spellings working, so W2-INTERVAL's later migration needs no change here.
2. `_matched_strategy_signals(keys, bars_daily, bars_intraday, direction, interval=None, bars_vwap_daily=None)`:
   - rsi/bb: unchanged.
   - vwap intraday: `mean_reversion_vwap_signal(slice, direction=direction, interval=_VWAP_SIGNAL_INTERVAL[iv])`
     over `bars_intraday`. **The defect marker line `fn(slice_bars, direction=direction)` is gone.**
   - vwap daily: `mean_reversion_vwap_daily_signal(slice, direction=direction)` over
     `bars_vwap_daily if bars_vwap_daily is not None else bars_daily`.
   - vwap with bar type None: skipped.
   - The ≥60-bar floor, the 3-bar lookback and the 120-bar slice stay as they are for both variants.
3. `interval` (and `bars_vwap_daily`) keyword params are added to `_check_strategy_signals`,
   `evaluate_from_context`, `evaluate_from_context_detailed`, `evaluate_scheduled`, `describe_match` and threaded
   straight through. Default `None` = VWAP never matches (fail closed, like today's 1D rule path) — every in-repo
   caller passes it after this change.
4. `evaluate_scheduled`'s starved count uses `_strategy_bar_type(key, interval)` and the same bar list the matcher
   would read (so a 1D watch with < 60 daily bars is "no reading", not "False").
5. The **caller supplies completed bars**; the evaluator does not trim. Docstrings of `evaluate_from_context` /
   `evaluate_scheduled` drop "strategy confirmations keep bars_intraday (regime models only)" and say: bars_intraday
   must be completed bars of `interval`.

### Watch path (`strategy_watch_evaluator._eval_composite_watch`)

```python
interval = w.get("interval", "15m")
vwap_intraday = "mean_reversion_vwap" in confirmations and _strategy_bar_type("mean_reversion_vwap", interval) == "intraday"
needs_intraday = model == "HMM_intraday" or vwap_intraday
if needs_intraday:
    raw = fetch_intraday_candles(symbol, interval=interval, days=intraday_history_days(interval))
    bars_intraday = completed_bars_for_interval(raw, interval)
evaluate_scheduled(symbol, trigger_def, bars, bars_intraday,
                   regime_bars_intraday=bars_intraday if model == "HMM_intraday" else None,
                   interval=interval, unknown_as_none=True)
describe_match(..., bars_intraday=bars_intraday, interval=interval)
```
- A **1D/1W** watch no longer fetches "intraday" bars at its daily interval; VWAP reads `bars` (get_bars =
  completed daily bars, per the A4g record) through the daily variant.
- The HMM fit is unchanged (it already read completed bars); only the VWAP read moves from raw to completed.

### Rule path (`routers/chart_alerts.py` composite block, D1)

- Intraday rules: `bars_intraday=_regime_candles` (completed bars of the rule's interval, as the HMM already uses)
  instead of `_model_candles` (forming bar included). `_model_candles` is then unused → removed.
- 1D rules: `_bars_daily` is already `_regime_candles` (completed daily) → the daily variant reads it. No change.
- 1W rules: `_regime_candles` are **weekly** bars, so for a rule listing `mean_reversion_vwap` fetch
  `get_bars(symbol, today-730d, today)` once per tick (only if some composite row lists VWAP) and pass it as
  `bars_vwap_daily`. rsi/bb/HMM_daily on 1W keep reading weekly bars (pre-existing, out of scope — logged, not
  changed).
- Pass `interval=interval` to `evaluate_from_context_detailed`.
- The A4e docstring sentence "The VWAP confirmation keeps the forming bar by decision (A4C-FOLLOWUPS-LOCKED-2026-09-24)"
  becomes "The VWAP confirmation reads completed bars too (VWAP-CONFIRMATION-LIKE-REGIME-MODELS, 2026-09-25)".

### Strategy engine (D2)

`if interval not in ("1m", "5m", "15m", "30m", "1h"):` → add `"4h"`; docstring "(intraday only)" unchanged.
Existing `test_strategy_engine` 1D/weekly → None tests still hold.

### Tests (new file `tests/test_p4b_vwap_like_regime_models.py`)

Fixture bars built so the intraday VWAP signal fires on bar[-1] only when the forming bar is **included** (and a
mirror set that fires only on completed bars), plus a daily set that fires the daily variant.
1. Watch, 15m, forming bar present: stub `fetch_intraday_candles` + fixed `now` → VWAP matched only on completed
   bars (forming-only setup → not fired; completed setup → fired).
2. Rule path, 15m: same candles through `evaluate_and_notify_for_symbol` with `as_of` → same answer as (1).
   **Parity test:** for each fixture, watch-path result == rule-path result.
3. `interval` threaded: spy on `mean_reversion_vwap_signal` records `interval="15m"` for a '15min' rule and
   `"4h"` for a 4h watch (the default-'15m' pass-through is gone).
4. 1D watch: no `fetch_intraday_candles` call; the daily variant is called on `bars` (spy); fires on the daily set.
5. 1D rule: daily variant on `_regime_candles`; same answer as (4) on the same daily bars.
6. 1W rule: `get_bars` stub called; daily variant reads it (not the weekly candles); 1W watch same answer.
7. 4h: the intraday signal no longer returns None on `interval="4h"` for a firing fixture.
8. Starved: 1D watch with 30 daily bars and VWAP required → `evaluate_scheduled(..., unknown_as_none=True)` is
   None; unknown interval ('2h') → VWAP never matches, result False (not None).
9. Existing `test_chart_alerts_composite_ws.py:188` (daily rule → bars_intraday []) is updated to assert the new
   behaviour (daily variant on completed daily bars), with a comment pointing at this phase.
Mutations: pass raw instead of completed bars (watch) → test 1 fails; revert rule path to `_model_candles` → test 2
fails; drop `interval=` in the matcher → test 3 fails; route 1D VWAP to intraday → test 4 fails; remove "4h" from
the allow-list → test 7 fails; remove the 1W `bars_vwap_daily` → test 6 fails.

## T6 — momentum confirmations read a number (open_questions [61])

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

## T7 — GET /api/strategy-watch/ lists strategy watches only (open_questions [65])

`list_watches` endpoint returns `[w for w in store.list_watches() if w.get("watch_type") != "composite"]`.
Composites stay listed by `/api/composite-watches/`. The only consumer (`strategyWatchStore` → strategy-watch
page) never handled composites. PATCH/DELETE by id are unchanged.
Test: store holding one strategy + one composite → GET returns only the strategy row. Mutation: drop the filter.

---

## Out of scope — logged, not fixed

- 1W composite rules feed **weekly** bars to rsi/bb/HMM_daily while 1W watches feed daily (pre-existing A4g choice).
- A composite whose condition flips false while undelivered re-arms to idle and loses the undelivered alert
  (inherent: the alert is about a condition that no longer holds).
- `open_questions[9]` counts are recorded, not re-measured (T1).

## PROJECT_STATE.json

- Decision `P4B-DECISIONS-2026-09-25` (D1-D3).
- Phase `P4B-STRATEGY-COMPOSITE-WATCHES` with verify `absent` of the VWAP defect marker
  `if fn\(slice_bars, direction=direction\) is not None:` in composite_trigger_evaluator.py.
- On merge: phases VWAP-CONFIRMATION-LIKE-REGIME-MODELS, HMM-INTRADAY-4H-HISTORY, TESTS-PIN-STRATEGY-WATCHES-PATH →
  shipped; open_questions [3], [4], [6], [7], [9], [61], [64], [65] and the [56] VWAP half → closed_questions with
  evidence. (Indices shift; match by opening words.)

## Verify

`cd backend && .venv/bin/python -m pytest -q`; `cd frontend && npx tsc --noEmit && npx jest` (no frontend change
expected); `python3 scripts/state.py` exit 0. No test writes `backend/config/*.yaml` or runs the real lifespan.
