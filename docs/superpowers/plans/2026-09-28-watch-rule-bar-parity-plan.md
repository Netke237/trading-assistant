# WATCH-RULE-BAR-PARITY — plan (draft, pre-audit)

Task: PROJECT_STATE phase `WATCH-RULE-BAR-PARITY`, decision `P4B-FOLLOWUPS-2026-09-26`
items (4), (5), (8). Scope and owned files: `docs/superpowers/plans/2026-09-25-work-packages.md`
section "P4b follow-ups". Loop: this plan -> adversarial round -> build + mutations -> code round
-> merge only when clean.

**Owned:** `backend/app/routers/chart_alerts.py` (composite block of
`evaluate_and_notify_for_symbol` only), `backend/app/services/composite_trigger_evaluator.py`,
`backend/app/routers/composite_watch.py` (`/regime-snapshot` fetch), their tests.
**Not touched:** `chart_cache.py` display windows; the rest of `chart_alerts.py` (P4a);
`strategy_watch_evaluator.py` (owned by COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD, claimed now, and
WATCH-UNDELIVERED-EVENT-RESEND) — this plan is built so it needs no edit there.

## 1. What each path reads today (verified in code)

| Input | Composite WATCH (`strategy_watch_evaluator._eval_composite_watch`) | Composite RULE (`chart_alerts.evaluate_and_notify_for_symbol`) |
|---|---|---|
| HMM_intraday bars | `fetch_intraday_candles(days=intraday_history_days(iv))` = 55d (180d on 4h), completed at `now` | chart-cache candles: 55d below 1h, **730d on 1h/4h**, completed at `as_of`, then capped to the last `MAX_LIVE_MODEL_CANDLES`=1500 |
| VWAP intraday bars | same series as the HMM | same `_regime_candles` (730d / 1500 cap) |
| `bars_daily` (HMM_daily, rsi/bb) | `completed_daily_rows(get_bars(today-730d, today), now)` | intraday: `completed_daily_rows(get_bars(...), _as_of_dt)`; **1D/1W: the chart's daily/weekly candles** (`_bars_daily = _regime_candles`, the defect marker) |
| VWAP daily (1D/1W) | the same get_bars rows | `completed_daily_rows(get_bars(...), _as_of_dt)` — a second fetch |
| `/regime-snapshot` HMM_intraday | `fetch_intraday_candles(days=intraday_history_days(iv))`, completed at now | — |

Why each difference changes an answer:
- `compute_intraday_hmm` fits on the last 800 bars (`regime_hmm.py:67`). 1h: the watch has ~270
  bars (55d x 7/day), the rule 800 of ~1500 -> different model. 4h: watch ~250, rule 800 of ~1000.
- `mean_reversion_vwap_signal` uses `_vwap(bars)` over the **whole** series (`strategy_engine.py:77`,
  cumulative, no lookback) — history length moves the VWAP itself. Below 1h the 1500 cap already
  diverges from the watch (5min 55d ~ 2900 RTH bars; Tradier `session_filter=all` more).
- 1D: chart daily candles (1825d, yfinance/IBKR) vs get_bars (730d, historical store) -> the
  HMM_daily fit sees ~800 of ~1250 vs ~500 bars, and the price sources can differ. 1W: weekly bars
  are fed to strategies/HMM that expect daily bars.
- Item (5): a chart snapshot fetched before 16:00 and evaluated after it makes the rule drop today's
  completed daily row that the watch keeps.

## 2. Design

### 2.1 One intraday history window, applied inside the evaluator (item 4)

In `composite_trigger_evaluator.py`:

```python
# WATCH-RULE-BAR-PARITY (decision P4B-FOLLOWUPS-2026-09-26, item 4)
_INTRADAY_HISTORY_DAYS = {"1h": 180, "4h": 180}          # below 1h: 55

def intraday_history_days(interval) -> int: ...            # unchanged signature

def trim_intraday_history(bars, interval) -> list[dict]:
    """Bars whose time >= newest_time - days*86400. Anchored on the NEWEST bar,
    not the wall clock, so two paths holding the same newest completed bar keep
    exactly the same bars. A non-int newest time -> bars unchanged (fail open,
    like completed_bars_for_interval); order preserved, input not mutated."""
```

- **Where it is applied:** at the top of both `evaluate_scheduled` and `evaluate_from_context(_detailed)`,
  to `bars_intraday` and `regime_bars_intraday` when `interval` is intraday. Both paths therefore run
  the identical trim on their own series; the watch file needs no edit (it already fetches
  `intraday_history_days(iv)` days, which will now be 180 on 1h).
- **Why anchored on the newest bar:** the watch's fetch is a yfinance *period* (`"6mo"` for 180,
  `"60d"` for 55 — `_days_to_yf_period`), not a start date, so the two raw series never start at the
  same instant. Trimming both to `newest - N days` makes the kept set a function of the data only.
  Coverage: `6mo` >= 180d, `60d` >= 55d, Tradier start = today-55d <= newest-55d, and the rule's
  730d chart window covers both -> the trim never cuts a series short of the window.
- **4h:** buckets are `_resample_bars(origin="epoch")`, so a bucket's content does not depend on
  where the fetch started; the trimmed sets match.
- `/regime-snapshot` (`composite_watch.py`): apply `trim_intraday_history` after
  `completed_bars_for_interval`, so the dialog shows the value the watch and rule compare against.

### 2.2 The rule's composite series drops the 1500 cap

In the composite block only, build `_composite_intraday` = `_regime_candles` **without**
`[-MAX_LIVE_MODEL_CANDLES:]` (same `completed_session_bars(completed_bars_for_interval(...))` call,
judged at `as_of` — the chart snapshot's own completeness is still an A4c fetch-time question).
Pass it as `bars_intraday` and `regime_bars_intraday` on intraday intervals; the evaluator trims it
to 55/180 days. Standard rules and the composite OMM keep `_regime_candles` (1500 cap) — unchanged.
Memory: <= 730d of 1h bars (~5k dicts), already held in `all_candles`.

Chart display history is unchanged (chart_cache untouched).

### 2.3 Daily rows trimmed at `now` (item 5)

Both `completed_daily_rows(get_bars(...), ...)` calls in the composite block take
`_now_dt = datetime.now(MARKET_TZ)` (computed once per call) instead of `_as_of_dt`. `_as_of_dt`
stays for the chart candles (a cached chart candle's content is frozen at fetch time; a get_bars
row is not the chart snapshot).

### 2.4 1W **and 1D** composite rules read completed daily get_bars rows (item 8)

Delete the `if interval in ("1D", "1W"): _bars_daily = _regime_candles` branch. On every interval:
one `get_bars(symbol, today-730d, today)` (same window as the watch's `_HISTORY_DAYS`), trimmed by
`completed_daily_rows(..., _now_dt)`, fetched once per call when any composite rule needs daily
bars (strategy confirmations or HMM_daily) or VWAP daily, and shared by `_bars_daily` and
`_bars_vwap_daily` (today two fetches on 1D/1W). A failed fetch -> `[]` for both (fail closed,
unchanged).

**1D decision (the work package asks the plan to decide):** 1D goes to get_bars too. Keeping chart
candles cannot give parity: different source (yfinance/IBKR vs historical store) and different depth
(1825d vs 730d) change the HMM_daily fit, which is the model a 1D rule is most likely to use. Cost:
one DB-first read per tick for symbols with such rules; D7 already pays it for VWAP.

## 3. Tests (new file `tests/test_watch_rule_bar_parity.py`)

A shared bar universe per case (one synthetic intraday series long enough for 730d, one daily
get_bars series); the rule path gets it via the chart candles argument and a stubbed `get_bars`,
the watch path via stubbed `fetch_intraday_candles` (returning the watch's shorter window of the SAME
series) and `get_bars`. Spies on `compute_intraday_hmm`, `_check_strategy_signals`' bar args and the
strategy signal functions record what each path read. Each asserts **equal bar lists**:

1. 15min HMM_intraday: rule (55d chart, >1500 bars) == watch (55d) — pins the dropped cap.
2. 1h HMM_intraday: rule (730d chart) == watch (180d fetch) == `/regime-snapshot` input.
3. 4h HMM_intraday: same, 180d.
4. 1h and 15min VWAP intraday confirmation: same bars both paths.
5. 1D HMM_daily + rsi: rule reads get_bars rows == watch's `bars_daily`; chart candles unread.
6. 1W HMM_daily + bb: same; weekly candles never reach bars_daily (flips the A4g 1W pin).
7. Item 5: `as_of` = 15:30, now = 16:30 on a session day -> the rule keeps today's daily row, like
   the watch.
8. `trim_intraday_history` unit: anchor on newest, boundary inclusive, non-int time -> unchanged,
   empty -> empty, input not mutated.
9. One get_bars call per tick on 1D/1W when both a VWAP and an rsi rule exist.

Existing tests to update (the behaviour they pin is the one being reversed): `test_p4b_4h_history.py`
(1h 55 -> 180), `test_a4g_forming_daily_weekly_bar.py` 1D/1W chart-path cases (bars_daily now from
get_bars), `test_p4b_vwap_like_regime_models.py` where it pins the 1500-capped series.

**Mutations** (each must turn a test red): (m1) 1h back to 55; (m2) remove the trim from
`evaluate_from_context`; (m3) remove it from `evaluate_scheduled`; (m4) re-add the 1500 cap to
`_composite_intraday`; (m5) `_as_of_dt` back in `completed_daily_rows`; (m6) restore the 1W branch;
(m7) restore a 1D-only branch; (m8) drop the trim in `/regime-snapshot`; (m9) anchor the trim on
`time.time()` instead of the newest bar.

Checks before each push: `cd backend && pytest` (full), the state probe (`python3 scripts/state.py`),
PROJECT_STATE phase status + verify probe updated (defect marker gone -> switch to a presence probe
on `trim_intraday_history`).

## 4. Behaviour changes to accept

- Composite **watches** on 1h fetch 180d instead of 55d: their HMM_intraday fit AND their
  intraday VWAP confirmation change (VWAP is cumulative over the series). This follows from "one
  window" and is intended; 4h and below-1h watches are unchanged.
- Composite **rules** on 1h/4h fit a shorter history (180d), below 1h a longer one (no 1500 cap);
  1D/1W rules read the historical store's daily rows.

## 5. Questions for Kenneth (before build)

1. **1D rules -> get_bars** (2.4). Recommended yes; confirms the plan's choice.
2. **OMM is a fourth parity gap, outside items 4/5/8.** The rule's OMM primary runs on
   `_regime_candles` closes — intraday bars on an intraday rule, weekly bars on 1W — while the watch
   and `/regime-snapshot` run OMM on daily get_bars closes. The same OMM rule and watch can disagree
   on every interval but 1D. Options: (a) fold it in here (rule OMM reads the same completed daily
   get_bars rows — one line, same fetch); (b) log it as its own task. Recommend (a): it is the same
   defect ("read the same bars") and the dialog's snapshot already shows the daily OMM.
3. **1h watch VWAP** changes with the window (section 4). Accept, or keep the VWAP on 55d and
   widen only the HMM series? Recommend accept: two windows for one fetched series would reintroduce
   the drift this task removes.
