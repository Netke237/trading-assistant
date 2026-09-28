# WATCH-RULE-BAR-PARITY — plan r2 (after adversarial round 1)

Task: PROJECT_STATE phase `WATCH-RULE-BAR-PARITY`, decision `P4B-FOLLOWUPS-2026-09-26` items
(4), (5), (8), plus decision `WATCH-RULE-BAR-PARITY-SCOPE-2026-09-28` (1D rules, OMM, 1h VWAP).
Scope and owned files: `docs/superpowers/plans/2026-09-25-work-packages.md` section "P4b follow-ups".
Loop: plan -> adversarial rounds until clean -> build + mutations -> code round -> merge when clean.

**Owned (as used by r2):** `backend/app/routers/chart_alerts.py` — the composite block of
`evaluate_and_notify_for_symbol` and its docstring sentences about composite inputs;
`backend/app/services/composite_trigger_evaluator.py` — `intraday_history_days` /
`_INTRADAY_HISTORY_DAYS` only (plus the OMM direction line **iff** question Q-A below is answered yes);
`backend/app/routers/composite_watch.py` — the `/regime-snapshot` fetches; their tests.
**Not touched:** `chart_cache.py` (called with an explicit `days`, never edited);
`strategy_watch_evaluator.py`; `evaluate_scheduled` / `evaluate_from_context*` / `describe_match` /
`_matched_strategy_signals` (COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD holds a live claim on those
functions' momentum paths); `historical_store.py`; the rest of `chart_alerts.py` (P4a).

**r1 -> r2 design change.** r1 trimmed series inside the evaluator entry points. Round 1 showed that
(a) it reaches into functions another claimed package owns and changes the watch path, (b) it misses
`describe_match`, and (c) a calendar trim cannot reproduce a yfinance *period* fetch (`"6mo"` is
181–184 days). r2 instead makes the rule **make the same fetch the watch makes**: the same function
(`fetch_intraday_candles`, via `chart_cache` with an explicit `days`) with the same `days`, and the
same `get_bars` window. No trim helper, no evaluator edit.

## 1. What each path reads today, and what actually changes an answer

Effective windows (round 1 finding 4): `compute_intraday_hmm` fits only the last **800** bars
(`regime_hmm.py:67`); strategy confirmations (rsi/bb/VWAP) read **≤120-bar** slices
(`composite_trigger_evaluator.py:289-291`, `bars[max(0, i-119): i+1]`); OMM's transition matrix
uses the last **500** rows (`regime_omm.py:16`, `WINDOW`).

| Input | WATCH | RULE today | Effective difference |
|---|---|---|---|
| HMM_intraday, below 1h | `fetch_intraday_candles(days=55)`, completed at now | chart cache, 55d, completed at `as_of`, cap 1500 | **none** beyond fetch instant (both >800 bars; last 800 equal) |
| HMM_intraday, 1h | 55d (~270 bars) | chart cache 730d, last 800 | **real**: 270 vs 800 bars |
| HMM_intraday, 4h | 180d (~250 bars) | chart cache 730d (~1000), last 800 | **real**: 250 vs 800 bars |
| VWAP intraday | same series as HMM | same `_regime_candles` | **none** once ≥ ~122 bars (120-bar slices) |
| `bars_daily` 1D | completed get_bars 730d at now | chart daily candles (1825d, other source) | **real**: HMM_daily 500 vs 800 bars; source differs |
| `bars_daily` 1W | same | **weekly** candles | **real**: weekly bars fed to daily models |
| `bars_daily` intraday | same | completed get_bars at `as_of` | item (5) only |
| OMM primary | `compute_omm(daily closes)` | `compute_omm(_regime_candles closes)` — intraday/weekly/chart-daily | **real** on every interval |
| `/regime-snapshot` OMM, HMM_daily | — | — | **real**: get_bars **400d**, forming row **kept**, OMM with `direction=` (watch/rule: default Bullish) |
| `/regime-snapshot` HMM_intraday | same fetch as the watch | — | none |

r1's claim that VWAP reads the whole series was **wrong**: `_vwap` only sees ≤120-bar slices, so
the 1h window change does **not** move the watch's VWAP (except a series too short for 122 bars).
Decision SCOPE (3) was accepted on that false premise; it is moot and Kenneth is told so.

## 2. Design

### 2.1 One HMM_intraday window (item 4)

`_INTRADAY_HISTORY_DAYS = {"1h": 180, "4h": 180}` (below 1h: 55). Consequences:
- **Watch:** unchanged code; on 1h it now fetches 180d (`"6mo"`) -> ~880 bars -> fits the last 800.
- **Rule:** in the composite block, when some composite rule on an intraday interval needs
  HMM_intraday or intraday VWAP, fetch the model series with
  `get_intraday_with_fetched_at(symbol, interval, days=intraday_history_days(interval), refresh_on_close=True)`.
  Below 1h this is the **same cache key** as the chart candles (`symbol:iv:55`) -> no extra fetch.
  On 1h/4h it is one extra cached entry (`symbol:1h:180`), which calls `fetch_intraday_candles` with
  the watch's exact arguments (same yfinance period, same IBKR/Tradier merge). Completion is judged
  at **that entry's** `fetched_at` (A4c), then cut at the closed candle (2.6). No 1500 cap.
  A failed fetch -> `[]` -> HMM_intraday/VWAP fail closed (as today when bars are missing).
- **`/regime-snapshot`:** unchanged (already the watch's fetch).
- `_regime_candles` (1500 cap, `as_of`) stays for standard rules and nothing else in the composite
  block (OMM moves in 2.5).

### 2.2 Item (5): daily rows judged at now (or the closed candle, 2.6)

The composite block's `completed_daily_rows(get_bars(...), X)` uses
`X = min(datetime.now(MARKET_TZ), close instant of closed_candle)` instead of `_as_of_dt`.
For the newest closed candle this is "now" except across the session close, where the candle's
close instant keeps exactly the rows completed by then; `_as_of_dt` stays only for the chart candles.

### 2.3 1W and 1D read completed daily get_bars rows (item 8, SCOPE (1))

Delete `_bars_daily = _regime_candles`. One `get_bars(symbol, date.today()-730d, date.today())`
per call (the watch's `_HISTORY_DAYS` window), passed through `completed_daily_rows(..., X)` (2.2),
shared by `bars_daily`, `bars_vwap_daily` and OMM. Fetched when any composite rule needs it:
strategy confirmations, HMM_daily, VWAP daily, **or OMM** (including a missing model — both
evaluators default to `"OMM"`; read as `(_rj.get("primary") or {}).get("model") or "OMM"`, so a
stored `"primary": null` cannot raise outside the per-row try — round 1 finding 13). Failure -> `[]`
for all three (fail closed). Today 1D/1W make **at most one** get_bars call (VWAP only); r2 keeps one.

**Freshness (round 1 finding 3, checked and mostly rebutted).** A 1D rule judges day D as
`candles[-2]` (`chart_alert_scheduler._candles_to_evaluate`), i.e. once day D+1's candle exists. By
then `historical_store._prev_trading_day()` is D, so `get_bars` fetches D if the DB lacks it. 1W
likewise judges week W on the following Monday. Residual, pre-existing and shared with the watch:
a D row stored **partial** mid-session is never refetched (A4g open question (a), documented at
`completed_daily_rows`); this only happens when the DB was ≥2 sessions behind during a session.
Stated in §4; no guard (a guard would silence 1D rules instead).

### 2.4 `/regime-snapshot` OMM and HMM_daily read what the watch reads (round 1 finding 1)

Replace `get_bars(today-400d)` with `completed_daily_rows(get_bars(today-730d, today),
datetime.now(MARKET_TZ))` for OMM and HMM_daily. The OMM `direction` argument: see Q-A.

### 2.5 Composite OMM reads the daily rows (SCOPE (2))

`_omm` = `compute_omm([b["close"] for b in bars])` over the shared rows of 2.3, with the watch's
exact call and empty handling (`None` when no rows; the rule's `len >= 100` pre-check goes, since
`compute_omm` returns None below its own minimum — verified in build, pinned by test).

### 2.6 Catch-up candles never read later data (round 1 finding 2)

`chart_alert_scheduler` evaluates older closed candles with `view = candles[:idx+1]`. The daily
rows and the rule's own model fetch are not cut by `view`, so r2 cuts them explicitly:
- daily rows: `completed_daily_rows(rows, X)` with X from 2.2 (the closed candle's close instant
  drops every later session);
- intraday model series: bars with `time <= closed_candle["time"]`.
The watch has no catch-up, so for the newest candle both paths still match.

## 3. Tests (new `tests/test_watch_rule_bar_parity.py`) and mutations

Stubs: one synthetic intraday universe placed **far from the wall clock** (e.g. 2031) with an
injected clock; `fetch_intraday_candles` stubbed as a pure function of `(interval, days)` that
returns `days` + 4 extra leading days (like `"6mo"`), shared by both paths — so the only way the
rule can match the watch is by calling it with the same `days`. `get_bars` stubbed likewise.
Assertions are on what the **models** receive (`compute_intraday_hmm`, `compute_omm`, the
rsi/bb/VWAP signal functions) and, for HMM, on the fitted result.

1. 1h HMM_intraday: rule model input == watch input (800 bars from the 180d series); under the
   old code the rule's 800 differ (behavioural).
2. 4h HMM_intraday: equal, ~250 bars; old code: 800 (behavioural).
3. 15min HMM_intraday: equal; the rule reuses the chart cache entry (one fetch call).
4. 1h VWAP: same slices on both paths.
5. 1D and 1W: HMM_daily + rsi + bb read the get_bars rows on both paths; weekly/chart candles unread.
6. OMM on 15min, 1D, 1W: identical closes to `compute_omm`; `primary` missing and `primary: null`
   both fetch and neither raises.
7. Item (5): `as_of` 15:30, now 16:30 -> today's completed row reaches the rule, as the watch.
8. Catch-up: an older `view` -> no daily row after the closed candle's session and no intraday bar
   after its time reaches any model.
9. `/regime-snapshot` OMM and HMM_daily inputs == the watch's `bars_daily` (730d, completed).
10. One `get_bars` call per evaluation when OMM, rsi and VWAP rules coexist on 1D.

Existing tests updated because they pin reversed behaviour (round 1 finding 8):
`test_p4b_4h_history.py` (1h 55 -> 180); `test_a4c_user_alert_completed_bars.py:197-201` (composite
OMM on 15min received intraday closes); `test_a4g_forming_daily_weekly_bar.py` 1D/1W chart cases
incl. the D2 composite-OMM case (`:272`). Docstring of `evaluate_and_notify_for_symbol`
(`chart_alerts.py:888-896`) corrected for composite OMM and bars_daily.

**Mutations** (each must turn a test red): m1 1h back to 55 (tests 1, 4 via watch days);
m2 rule HMM series from `_regime_candles` again (tests 1, 2); m3 rule fetch with default `days`
(tests 1, 2); m4 restore the 1W branch (5); m5 restore a 1D branch (5); m6 `_as_of_dt` back (7);
m7 `_omm` on `_regime_candles` (6); m8 daily-fetch condition ignores missing/null model (6);
m9 drop the catch-up cut on daily rows (8); m10 drop it on the intraday series (8);
m11 snapshot back to 400d or without `completed_daily_rows` (9).

Before each push: full `cd backend && pytest`, `python3 scripts/state.py`, PROJECT_STATE phase +
probe updated (defect marker gone -> presence probe).

## 4. Behaviour changes and residual non-parity

Changes: 1h watches fit HMM_intraday on 180d; 1h/4h rules fit on 180d; 1D/1W rules read the
historical store's daily rows; every composite OMM rule judges daily OMM; `/regime-snapshot` OMM
and HMM_daily show 730d completed rows (the preview moves); catch-up candles stop reading later data.

Residual non-parity, out of scope (round 1 findings 7, 14):
- the two paths fetch at different instants (cache TTL, IBKR up on one fetch and down on the other,
  Tradier sandbox partial-bar rule) — same call, not same response;
- a partial daily row stored mid-session is never refetched (historical_store, pre-existing);
- structure confirmations: the watch reads daily-bar structure, the rule the chart interval's
  signals — no owner yet (logged as an open question at build);
- momentum confirmations: COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD.

## 5. Questions for Kenneth (r2)

- **Q-A (new, pre-existing bug on BOTH paths):** the watch and the rule call `compute_omm(closes)`
  with the default `direction="Bullish"`, so a **Bearish** OMM composite compares `conviction_min`
  against the *bullish* conviction; `/regime-snapshot` shows the direction-aligned value. Options:
  (a) fix here — pass the trigger's direction on both paths (one argument in `evaluate_scheduled`'s
  OMM line and in the rule block; needs that one line of `evaluate_scheduled`, not a momentum path);
  (b) log as its own task. Recommend (a).
- **SCOPE (3) correction:** the 1h watch VWAP does not change (section 1). No answer needed.
