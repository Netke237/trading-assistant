# A4c — the user-built intraday alert models measure on completed bars (plan)

Date: 2026-09-24. Planned against main at `22c4942` (A4b merged). Answers the open question A4b logged
("should the user-built alert models that fit a regime on intraday bars also drop the forming bar?").

**Kenneth, 2026-09-24:** "every model that decides or fires". Asked before planning, he also chose:
- **Intraday intervals only** (1m–4h). The forming DAILY/WEEKLY bar that 1D/1W chart rules (and
  `HMM_intraday` watches left on the dialog's default `'1D'` interval) still read is logged as its own item.
  It needs 2B guard (i)'s session-hours test, not a timestamp rule.
- **Regime models only** (OMM / HMM fits). The same alerts' non-regime inputs keep the forming bar, the same
  line A4b drew: the composite `mean_reversion_vwap` strategy confirmation, chart-rule indicator values and
  structure signals. These are logged.

---

## 1. The readers, verified against today's tree

A reader is in scope when a regime model fitted on user-interval intraday bars **decides whether an alert
fires** (Kenneth's criterion). One display reader is also included (U2) because it shows the user the exact
value the watch will compare against.

| # | Reader | Where | Fires? |
|---|---|---|---|
| U1 | Composite watch, scheduled path, `primary.model == "HMM_intraday"` | `services/strategy_watch_evaluator.py:~254-264` fetches `fetch_intraday_candles(symbol, interval=w.interval, days=55)` → `composite_trigger_evaluator.evaluate_scheduled` HMM_intraday branch (`:~320-334`) | Gmail/Telegram |
| U2 | Composite regime snapshot for the alert dialog, `HMM_intraday` | `routers/composite_watch.py:~75-80` | display (the threshold the user picks is compared against this value) |
| U3 | Chart-drawn COMPOSITE rules: the OMM primary (`_omm = compute_omm(_closes)` on the chart candles) and the HMM_intraday primary (`bars_intraday=_bars_intraday` → `evaluate_from_context` HMM branch) | `routers/chart_alerts.py:~816-862` | history row + Gmail/Telegram + WS |
| U4 | Chart-drawn STANDARD rules with a `regime` condition: `build_regime_snapshot(all_candles[-MAX_LIVE_MODEL_CANDLES:])` (OMM, HMM, HMM_directional) | `routers/chart_alerts.py:~763`, `services/alert_evaluator.py:154-195` | same |

U3 and U4 run inside `evaluate_and_notify_for_symbol`. Its two callers: the chart WS on a new candle
(`routers/chart.py:~76-97`), and the background `chart_alert_scheduler._tick`. Both pass
`candles = await chart_cache.get_intraday(symbol, interval)`, whose last element is the forming candle.
Both code comments say this: `candles[-2]` is "the just-closed candle; candles[-1] is the new open".

**Out of scope, each for a stated reason:**
- `require_choppy_regime` (`strategy_engine.py:808/:906`, rsi/bb mean reversion). No caller passes intraday
  bars. The strategy-watch path uses daily `get_bars`, the composite `_check_strategy_signals` maps both to
  `"daily"`, and `stock_scan`'s `_INTRADAY_STRATEGIES` is `{"mean_reversion_vwap"}` only. Its forming-daily
  exposure belongs to the logged daily item.
- `/api/regime/intraday-series` chart overlay. Display only ("Viterbi-decoded over full window, not
  point-in-time"). It neither decides nor fires.
- `POST /rules/{id}/test` dry-run (`chart_alerts.py:~667-700`). It replays user-supplied candles causally,
  evaluating candle *i* on `candles[:i+1]` (so that candle counts as closed). It fires nothing.
- HMM_daily (daily bars), and every 1D/1W chart rule (Kenneth: intraday only).

## 2. Completeness for a user interval

A4b's `completed_intraday_bars(bars, now, bar_seconds, feed_lag)` is the rule: keep a bar iff its int
`time` (bar START) `+ bar_seconds + feed_lag <= now`. Non-int time is dropped. It is reused unchanged.
New thin wrapper in `app/data/market.py`:

```python
def completed_bars_for_interval(bars, interval, now=None) -> list[dict]:
```

- `interval` normalised (`normalize_interval`). The known intraday intervals map to a completeness span:
  `1min/1m 60`, `5min/5m 300`, `15min/15m 900`, `30min/30m 1800`, `1h 3600`,
  **`4h 18000`**. The 4h value is 4h + 1h, not 4h. `_fetch_intraday_yf` builds 4h by resampling
  **yfinance 1h bars** (which start at :30) into `origin="epoch"` 4-hour buckets keyed by bucket start. The
  last 1h constituent can start up to 30 min before the bucket boundary and end 30 min after it. So a 4h bar
  is only provably complete one constituent length past its nominal end. Conservative by up to 1h.
- **Any other interval** (daily/weekly/`1D`/`1W`, or an unrecognised string) → the list is returned
  **unchanged**. Daily and weekly are Kenneth's scoping. For an unrecognised string, fail-open is chosen over
  fail-closed on purpose. Dropping every bar would silently kill the user's alert. The frontend offers only
  `5m/15m/30m/1h/4h` (composite dialog) and `1min/5min/15min/1h/4h/1D/1W` (chart), all mapped.
- `feed_lag = intraday_feed_lag_seconds()` only when the normalised interval is one Tradier timesales serves
  (`_TRADIER_INTRADAY_INTERVALS` = `1min/5min/15min`). Otherwise it is 0. The aliases `5m`/`15m` are not in
  that set, so `fetch_intraday_candles` never asks Tradier for them and yfinance, real time, is the only
  source.

## 3. Fetch time — the chart cache (U3, U4)

`chart_cache.get_intraday` serves cached rows for up to 15–30 min (intraday TTLs). A cached bar that was
forming **at fetch time** keeps its partial content after its interval elapses on the wall clock. So
completeness must be judged at the **fetch instant**, not at `time.time()`.
- `chart_cache` records the wall-clock fetch time with each entry and gains
  `get_intraday_with_fetched_at(symbol, interval, days=None) -> (rows, fetched_at)`. `get_intraday` is
  rewritten over it, so its return value and behaviour are unchanged for its other callers.
- `evaluate_and_notify_for_symbol(..., as_of: float | None = None)`. Both callers pass the `fetched_at` of
  the very `candles` they pass. `None` falls back to `time.time()`, for direct callers such as tests.

U1 and U2 call `fetch_intraday_candles` directly, which has no cache, so `now` defaults to `time.time()`.

## 4. The change

- **composite_trigger_evaluator.** `evaluate_scheduled`, `evaluate_from_context` and
  `evaluate_from_context_detailed` gain a keyword `regime_bars_intraday: list[dict] | None = None`. The
  HMM_intraday branch fits on `regime_bars_intraday if regime_bars_intraday is not None else bars_intraday`.
  `bars_intraday` still feeds `_check_strategy_signals` (VWAP) and `describe_match` unchanged. The emptiness
  check applies to the regime series. An all-dropped series means the existing "no intraday bars" →
  `False`, fail closed, as today.
- **U1** `strategy_watch_evaluator`: when `model == "HMM_intraday"`, pass
  `regime_bars_intraday=completed_bars_for_interval(bars_intraday, interval)`.
- **U2** `composite_watch`: `hmm_bars = completed_bars_for_interval(fetch_intraday_candles(...), interval)`
  for HMM_intraday.
- **U3/U4** `evaluate_and_notify_for_symbol`:
  `_regime_candles = completed_bars_for_interval(all_candles, interval, now=as_of)[-MAX_LIVE_MODEL_CANDLES:]`.
  It is computed once. For 1D/1W it equals today's `all_candles[-MAX:]`.
  - U4: `build_regime_snapshot(_regime_candles)`.
  - U3: `_omm` from `_regime_candles` closes (the `>= 100` test on that series). The call passes
    `regime_bars_intraday=_regime_candles if interval not in ("1D","1W") else None`. `_bars_intraday` is
    unchanged and still feeds VWAP.
  - `closed_candle`, `indicators`, `signals` are untouched (Kenneth: regime only).
- Callers: `chart.py` WS and `chart_alert_scheduler._tick` switch to `get_intraday_with_fetched_at` and pass
  `as_of=fetched_at`.

## 5. Decisions and residuals

1. **Lag accepted** as in A4b: up to one bar interval, plus 15 min on the Tradier sandbox for
   1min/5min/15min, and up to 1h extra on 4h. On a 15min rule under the sandbox, the regime can lag the
   `closed` candle the price condition reads by one bar. This is the conservative direction.
2. **Alerts that fire today may stop firing, or fire later.** This is the intended behaviour change.
3. The scheduler's `_last_seen_candle` dedupe and the chart WS's own candle-close detection are unchanged.

## 6. Tests — new `backend/tests/test_a4c_user_alert_completed_bars.py`

1. `completed_bars_for_interval`: each mapped interval keeps a bar exactly at `now - span` and drops one at
   `now - span + 1`. `4h` uses 18000. `1D`/`1W`/`daily`/unknown are returned unchanged (identity of content).
   The sandbox lag applies to `15min` and not to `15m`/`30m`/`1h`.
2. U1: a composite HMM_intraday watch. `compute_intraday_hmm` receives every bar but the forming last one,
   while `_check_strategy_signals` receives the whole `bars_intraday`.
3. U2: the snapshot endpoint's HMM receives the completed series.
4. U3: a chart composite rule on `15min`. The OMM closes and the HMM series exclude the forming candle, while
   `bars_intraday` (VWAP) keeps it. On `1D`, unchanged.
5. U4: `build_regime_snapshot` receives the completed candles on `15min`, and the full slice on `1D`.
6. `as_of`: a cached series fetched while its last bar was forming. `evaluate_and_notify_for_symbol` called
   with that `as_of` and a much later wall clock still drops the last bar.
7. Both callers (`chart.py` WS, `chart_alert_scheduler._tick`) pass the `fetched_at` returned with their
   candles.
8. `chart_cache.get_intraday` returns exactly what it did (the rows), cached and uncached.

Existing tests whose fixtures carry non-int candle `time` (e.g. `"t{i}"`) on intraday-interval regime rules
will change behaviour. They are adjusted to unix-int times, as `fetch_intraday_candles` returns them, and the
reason is recorded.

Mutations before the round: span `<=`→`<`, the 4h span back to 14400, the lag applied to `15m`, the helper
skipped at each of U1–U4, `as_of` ignored (use `time.time()`), VWAP bars filtered too, and 1D filtered.

## 7. Done means

Full backend suite green and reconciling (frontend untouched). `state.py` exit 0 with a phase entry
`A4C-USER-ALERT-COMPLETED-BARS`. The adversarial round on the code is clean at `audit_rule`'s gate. Then merge.

---

## 8. Adversarial round 1 (the plan) — 2026-09-24: CLEAN (zero gate-level findings)

Fresh subagent (bmad-review-adversarial-general, audit_rule's gate). It checked every caller of `compute_omm`,
`compute_intraday_hmm`, `build_regime_snapshot`, `evaluate_scheduled`/`evaluate_from_context*`,
`fetch_intraday_candles` and `get_intraday`, and confirmed that U1–U4 are the complete set of readers that
decide or fire. It found `describe_match`/`format_composite_reason` carry no regime value. The one regime
number persisted in history (`trigger_values.omm_state`) comes from `_omm`, which the plan fixes. All bar
sources give int start times. The 4h span of 18000 was worked through for yfinance :30 bars and IBKR
clock-aligned bars in both EDT and EST, and is sufficient. The Tradier set and the aliases are as stated.
The reviewer confirmed the `as_of` reasoning, with the note that `fetched_at` must be wall-clock (it is:
`time.time()`, with cached entries derived from the monotonic expiry).

Below the gate, not raised: IBKR 1h/4h carry no feed lag (no evidence the gateway is delayed, and 4h's
extra hour covers it). The scheduler tests that patch `get_intraday` need updating (test hygiene). The
rule-level `closed` candle can still be partial under the sandbox (not regime; scoped out).

## 9. Build notes

- `chart_cache.get_intraday_with_fetched_at` keeps the cache entry's `(rows, expiry)` shape. A cached
  entry's fetch time is derived from its expiry and `_ttl_for(interval, rows)`, so there is no second store
  to keep in lockstep. A fresh fetch stamps `time.time()` taken before the fetch, which can only
  understate the fetch time (the conservative direction).
- The U1 watch fetch keeps its own interval default (`"15m"`) for the completeness span.

## 10. Adversarial round 2 (the code, f2ad5bc) — 2026-09-24: CLEAN (zero gate-level findings)

Fresh subagent against `git diff 22c4942 -- backend/`. Every user-alert regime fit is covered (U1–U4). U3's
persisted `omm_state` now comes from completed bars too. No real source yields non-int times, so no path
drops a whole series. Unknown, daily and weekly intervals are unchanged. OMM (100) and HMM (200) floors are
cleared by the cache windows. 1D/1W and every non-regime input (indicators, closed candle, structure, VWAP,
daily bars, `describe_match`) are untouched. `fetched_at` is at or before the true fetch start in all three
cases (fresh, cached, empty rows), so any error is the conservative one. Both callers pass the `as_of` of
the candles they evaluate. The adjusted tests still pin the fire. The 4h span was re-verified.

Below the gate, not raised: the cached fetch time is taken before the semaphore wait, which can add about
one extra bar of regime lag (the conservative direction).
