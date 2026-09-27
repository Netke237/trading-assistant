# CHART-WS-1D-1W-RULES — 1D/1W alert rules judged once per closed bar, including by the open chart — plan

Phase: CHART-WS-1D-1W-RULES (claimed on `claude/clever-planck-rpz8yh`, off main `7a5fc92`).
Logged by: W2-STRUCT phase note ("1D/1W rules are never evaluated by the chart WS ('daily' vs stored '1D'), so their fires reach email/Telegram only").
Decision: Kenneth chose **approach A** (2026-09-27): the chart WS evaluates 1D/1W rules with the stored spelling, and the chart WS and the background scheduler share one "already judged" marker per (symbol, interval, closed bar), so each daily/weekly bar is judged exactly once by whichever path gets there first. The open chart shows an in-app toast only when the chart path gets there first; the scheduler path still sends Gmail/Telegram as today.
Related records: A4G-CHART-COMPLETED-FOR-ALL-2026-09-25 (the 1D/1W path drops the forming bar for regime/daily readers); the open question on the forming daily/weekly bar in 1D/1W alerts is **not** touched (which bar is "closed" stays exactly what the scheduler uses today, `candles[-2]`).

## 0. The problem

Three facts, each read from main `7a5fc92`:

1. **Spelling.** ChartWorkspace opens the WS with `'daily'`/`'weekly'` for the chart's `'1D'`/`'1W'` (index.tsx:226-229, :348). `chart.py`'s tick loop passes that value to `evaluate_and_notify_for_symbol` (chart.py:100), which selects `AlertRuleModel.interval == interval` (chart_alerts.py:909). Rules are stored `'1D'`/`'1W'`, so none match. The evaluator's own 1D/1W branches (`interval in ("1D", "1W")`, chart_alerts.py:1014 and :1044, composite `_bars_daily` and its follow-up) also test the stored spelling, so matching both spellings in the query alone would still take the intraday branch. (`completed_session_bars` / `completed_bars_for_interval` normalize and accept either spelling.)
2. **Re-evaluation.** The WS treats a tick as a candle close when `tick["timestamp"] != last_candle_time` (chart.py:72), where `last_candle_time` is the int bar `time` and the tick's `timestamp` is the trade's. For any real trade they differ, so each such tick re-evaluates `candles[-2]`. Intraday, a bar lasts ≤ the default 60-minute cooldown, which hides this. On 1D a plain rename would re-judge yesterday's bar all session: a rule whose condition stays true would fire about once per cooldown (≈6-7 times a day) on one bar, plus once more from the scheduler. **Unverified (egress to Tradier's docs is blocked):** Tradier trade events may carry the time as `date`, not `timestamp` (tradier_stream.py:116 reads `timestamp`; tests use a made-up `timestamp`). If so, `tick_time` is always `""` and the WS evaluates nothing on any interval. The design below does not depend on the tick's time at all for 1D/1W, so it is correct either way; the intraday question is logged (§6), not fixed here.
3. **The browser also judges 1D/1W rules.** ChartWorkspace runs `evaluateRules` on the rules for the chart's interval whenever `candles.length` grows (index.tsx:398-436), and W2-STRUCT deliberately left 1D/1W in (chartAlertEngine.ts:237-240). A browser fire persists history, pushes a toast and PATCHes `last_triggered_at`. With the WS judging 1D/1W, the browser would be a third judge of the same bar, on a tick-built "closed" candle rather than the completed daily bar. "Exactly once" requires the browser to stop judging 1D/1W.

## 1. One shared "claim" in the scheduler module

`backend/app/services/chart_alert_scheduler.py`.

**1a. `_claim_candles_to_evaluate(key, candles) -> list[int]`** — new, synchronous (no `await`, so under asyncio's single thread the check and the write are atomic against the other path):
```python
idxs = _candles_to_evaluate(key, candles)
if idxs:
    _last_seen_candle[key] = candles[idxs[-1]]['time']
return idxs
```
The marker moves to the **newest** index being evaluated **before** any of them is evaluated. Today the scheduler advances it per candle, just before each evaluation; with two paths that interleave at every `await`, per-candle advancing lets path 2 see "newest ≠ marker" while path 1 is still on an older candle and evaluate the newest one too. Consequence for the scheduler alone: none observable. Every candle in the list is still attempted in order, and a failure on one was already only logged, never retried (P4a B2 "one attempt per candle").

**1b. `async def evaluate_closed_candles(symbol, interval, candles, fetched_at) -> list[dict]`** — new, public. It is the scheduler's per-pair body from `_tick` moved verbatim, with `_candles_to_evaluate` + per-candle marker writes replaced by one `_claim_candles_to_evaluate` call:
- `if len(candles) < 2: return []`;
- for each claimed `idx`: `closed = candles[idx]`; `view = candles if idx == len(candles) - 2 else candles[:idx + 1]`; `ht_candles` fetched once (`get_intraday(symbol, '1D')`) only when `interval == '1h'`; `signals = await asyncio.to_thread(closed_candle_structure, view, closed, interval, symbol, ht_candles)`; `entries = await evaluate_and_notify_for_symbol(symbol, interval, closed, view, signals, as_of=fetched_at)`; the entries are collected;
- per-candle `try/except` with the existing WARNING (a failure on an older candle does not stop the newer ones);
- returns every triggered entry, oldest candle first;
- `closed_candle_structure` and `evaluate_and_notify_for_symbol` are imported from `app.routers.chart_alerts` **inside the function**, as `_tick` does today, so the existing tests' `monkeypatch.setattr('app.routers.chart_alerts.evaluate_and_notify_for_symbol', …)` still intercepts both paths.
`_tick` keeps its fetch (`refresh_on_close=True`, `max_age=_max_age_for(...)`), the `_last_newest_bar` write, and its outer `try/except`, and calls `await evaluate_closed_candles(symbol, interval, candles, fetched_at)`, ignoring the return.

**1c.** The `run_chart_alert_scheduler` docstring's "Known limitation" paragraph is reworded to its new mechanism: 1D/1W candles are claimed once across the chart WS and this loop; intraday rules are still evaluated by both paths (the WS on its tick-based close check), with the rule cooldown as the only guard.

Key: `(symbol, interval)` with the **stored** spelling. The scheduler reads both from `AlertRuleModel` (symbol stored upper-case by `create_rule`/`replace_rule`); the WS passes `symbol.upper()` and the stored spelling (§2). Same key, same marker.

Marker residuals (unchanged, restated so the audit does not re-derive them): markers are in memory, so a server restart makes the next sighting a first sighting (newest closed candle only), exactly as today; `_prune_markers` drops a key with no enabled rule at each scheduler tick, so a WS claim on a pair with no rule is dropped within one tick. A WS claim made while a pair has no enabled rule means a rule created before the next tick does not fire on that already-claimed bar — the same "not a catch-up over candles from before the rule" posture P4a chose for first sightings.

## 2. The chart WS evaluates 1D/1W through the shared function

`backend/app/routers/chart.py`, `stream`.

**2a. Spelling.** Module level: `_RULE_INTERVAL = {"daily": "1D", "weekly": "1W"}`. In `stream`, after `symbol = symbol.upper()`: `rule_interval = _RULE_INTERVAL.get(interval, interval)` and `daily_alerts = rule_interval in ("1D", "1W")`. `'1D'`/`'1W'` passed directly (not by today's frontend) map to themselves. `interval` (the fetch/display spelling) is unchanged everywhere it is used today: history, structure messages, the fetch cache (`normalize_interval` makes `'1D'` and `'daily'` one cache key, chart_cache.py:121, so the WS and the scheduler read the same cached rows).

**2b. The existing tick-timestamp block** keeps its display work (structure recompute + `structure` message) for every interval. Its Phase 4 alert evaluation runs only `if not daily_alerts` — intraday is byte-for-byte unchanged.

**2c. 1D/1W alert check, not tied to the tick's time.** Module constant `_DAILY_ALERT_CHECK_SECONDS = 60` (the scheduler's default cadence). In the `while True` loop, after the `try: tick … except asyncio.TimeoutError: ping` block (so it runs after a tick **or** after a 30 s ping):
```python
if daily_alerts and time.monotonic() >= next_daily_check:
    next_daily_check = time.monotonic() + _DAILY_ALERT_CHECK_SECONDS
    try:
        from app.services.chart_alert_scheduler import evaluate_closed_candles
        d_candles, d_fetched = await get_intraday_with_fetched_at(symbol, interval)
        for entry in await evaluate_closed_candles(symbol, rule_interval, d_candles, d_fetched):
            await websocket.send_json({"type": "alert_triggered", "entry": entry})
    except WebSocketDisconnect:
        raise
    except Exception:
        logger.warning("Daily/weekly alert evaluation failed for %s [%s]", symbol, rule_interval, exc_info=True)
```
`next_daily_check` starts at `0.0`, so the first check runs on the first loop pass (first tick or first ping). The fetch uses the plain call, as the WS does today: for daily/weekly `refresh_on_close` has no effect (`_needs_refresh` has no due-instant rule for them, and the scheduler's `max_age` is `None` for them), so the scheduler and the WS see the same cached rows. Which bar is judged is the scheduler's (`candles[-2]` and the P4a catch-up list), because it is the scheduler's code. A `send_json` failing after a fire loses only the toast: history, `last_triggered_at` and Gmail/Telegram were already done by `evaluate_and_notify_for_symbol`; the marker is already claimed, so neither path re-sends.

## 3. The browser stops judging 1D/1W rules

**3a.** `frontend/lib/chartAlertEngine.ts`: new export
```ts
/** CHART-WS-1D-1W-RULES: 1D/1W rules are judged by the backend only (chart WS or
 *  scheduler, once per closed bar, shared claim); the chart receives a fire as
 *  `alert_triggered`. The browser judges every other interval. */
export function browserJudgesInterval(interval: Interval): boolean {
  return interval !== '1D' && interval !== '1W';
}
```
**3b.** `ChartWorkspace/index.tsx` candle-close effect: the rule filter becomes `r => r.symbol === symbol && r.interval === interval` **and** the whole evaluation is skipped when `!browserJudgesInterval(interval)` (guard at the top of the `if (candles.length > …)` body, before the rule filter; `prevCandleCount` is still updated). `evaluateRules` itself is unchanged, so its tests (which use `'1D'` as their default interval) keep testing the engine.
**3c.** The W2-STRUCT comment in `evaluateRules` (chartAlertEngine.ts:228-238) currently says "1D/1W are untouched: the chart WS does not evaluate those rules ('daily' vs stored '1D'), only the scheduler does, with no chart push." That now misstates the mechanism; it becomes: "1D/1W never reach this function from the chart (ChartWorkspace skips them via `browserJudgesInterval`; the backend judges them and pushes `alert_triggered`), so this skip is intraday-only."

## 4. Tests

Backend (new file `backend/tests/test_chart_ws_1d_1w_rules.py`; fixtures reuse `test_a4e_closed_candle_alignment.py`'s `_OneTickQueue` pattern and patch `app.routers.chart.get_intraday`, `app.routers.chart.get_intraday_with_fetched_at`, `app.routers.chart_alerts.evaluate_and_notify_for_symbol`, `app.routers.chart.get_stream_client`; markers cleared in a fixture):
- **T1 spelling:** WS `?interval=daily` → `evaluate_and_notify_for_symbol` awaited with interval `'1D'`, closed `candles[-2]`, `view == candles`; `?interval=weekly` → `'1W'`. Fails on main (never called with `'1D'`).
- **T2 tick time irrelevant:** a tick with `timestamp == ""` (and a second case with no tick at all — queue times out once) still leads to exactly one evaluation for `'1D'`. (Timeout case: patch `asyncio.wait_for` in `app.routers.chart` or use a queue whose `get` raises `TimeoutError` once, then `WebSocketDisconnect`.)
- **T3 once per bar, WS repeatedly:** three ticks with distinct timestamps and `_DAILY_ALERT_CHECK_SECONDS` patched to `0` → evaluated once (same `candles[-2]`). Fails on a rename-only fix.
- **T4 once per bar, across paths:** WS evaluates bar B for `('AAPL','1D')`; then `chart_alert_scheduler._tick` with a rule row for `('AAPL','1D')` and the same candles → no second `evaluate_and_notify_for_symbol` call. And the reverse order (scheduler first, then WS) → WS does not evaluate. A new bar (candles extended by one) → exactly one more evaluation, by whichever path runs first.
- **T5 push:** `evaluate_and_notify_for_symbol` returning `[entry]` on the WS path → the client receives `{"type": "alert_triggered", "entry": entry}`.
- **T6 intraday unchanged:** WS `?interval=15min` with one new-timestamp tick → the existing path (the A4e T7 test stays green unchanged) and no `evaluate_closed_candles` call; `_last_seen_candle` has no `('AAPL','15min')` key after.
- **T7 claim before evaluate:** `_claim_candles_to_evaluate` with an unseen list of two → marker equals the newer candle's time on return, before anything is awaited; a second call returns `[]`.
- **T8 scheduler parity:** the existing scheduler tests (`test_chart_alert_scheduler.py`, `test_p4a_chart_alert_rules.py`, `test_a4e_closed_candle_alignment.py` T5/T6) pass unchanged — they pin catch-up count, first sighting, per-candle failure isolation and the `view` truncation that `evaluate_closed_candles` now owns.
- **T9 failure isolation:** `evaluate_and_notify_for_symbol` raising on the WS path → WARNING logged, stream stays open (a following ping is received), marker still claimed (no retry).

Frontend (`frontend/lib/__tests__/chartAlertEngine.test.ts`): `browserJudgesInterval` is false for `'1D'`, `'1W'`; true for `'1min'`, `'5min'`, `'15min'`, `'1h'`, `'4h'`. The existing W2-STRUCT `1D/1W is unchanged` engine test stays (engine behaviour is unchanged).

## 5. What does NOT change

- Which daily bar is "closed" (`candles[-2]`, the scheduler's choice), the A4g forming-bar handling inside `evaluate_and_notify_for_symbol`, and the open question on the forming daily/weekly bar.
- Intraday evaluation on both paths (WS tick-based, scheduler marker-based) and the browser's intraday evaluation.
- Rule storage, spellings, migrations, `chart_interval`, `normalize_interval`, the cooldown logic, notification text.
- The structure display messages on every interval.

## 6. Logged, not fixed here

- **L1 (needs a live check):** if Tradier trade events carry `date` rather than `timestamp`, the WS's intraday close check never passes, so intraday rules are judged only by the scheduler and the browser, and the WS never re-sends structure. Confirm against a live stream (Kenneth's machine) before designing a fix.
- **L2:** intraday rules are still judged by the WS on every new-timestamp tick and by the scheduler; the shared claim could extend to intraday, but that changes the sustain-clock timing of WS-judged rules and is a separate decision.
- **L3:** the browser's tick handling appends a new candle for every tick whose `timestamp` differs from the last bar's `time` (index.tsx:358-368), so on any interval the chart can grow tick-built bars. Display-only after §3 for 1D/1W; intraday browser evaluation reads them. Pre-existing.

## 7. Size and layering

Backend: ~60 lines moved/added across `chart_alert_scheduler.py` and `chart.py`, one new test file. Frontend: ~10 lines across `chartAlertEngine.ts` and `ChartWorkspace/index.tsx`, a few test lines. One change, well under the ~500-line batch guidance; built as Part A (backend) then Part B (frontend), each audited.
