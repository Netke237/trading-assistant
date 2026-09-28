# WATCH-RULE-BAR-PARITY — plan r3 (after adversarial rounds 1 and 2)

Task: PROJECT_STATE phase `WATCH-RULE-BAR-PARITY`, decision `P4B-FOLLOWUPS-2026-09-26` items
(4), (5), (8), plus decisions `WATCH-RULE-BAR-PARITY-SCOPE-2026-09-28` (1D rules, OMM; its item 3 is moot) and
`WATCH-RULE-BAR-PARITY-OMM-DIRECTION-2026-09-28` (OMM uses the trigger's direction on both paths).
Scope and owned files: `docs/superpowers/plans/2026-09-25-work-packages.md` section "P4b follow-ups".
Loop: plan -> adversarial rounds until clean -> build + mutations -> code round -> merge when clean.

**Owned (as used by r2):** `backend/app/routers/chart_alerts.py` — the composite block of
`evaluate_and_notify_for_symbol` and its docstring sentences about composite inputs;
`backend/app/services/composite_trigger_evaluator.py` — `intraday_history_days` /
`_INTRADAY_HISTORY_DAYS`, the new pure helpers of 2.6, and the OMM line of `evaluate_scheduled`
(decision OMM-DIRECTION);
`backend/app/routers/composite_watch.py` — the `/regime-snapshot` fetches; their tests.
**Not touched:** `chart_cache.py` (called with an explicit `days`, never edited);
`strategy_watch_evaluator.py`; `evaluate_scheduled` beyond its OMM line; `evaluate_from_context*` /
`describe_match` / `_matched_strategy_signals` (COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD holds a live
claim on those functions' momentum paths **and on the chart_alerts composite block** — see 2.9); `historical_store.py`; the rest of `chart_alerts.py` (P4a).

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
  `get_intraday_with_fetched_at(symbol, interval, days=intraday_history_days(interval), refresh_on_close=True)`
  (freshness check in 2.7).
  Below 1h this is the **same cache key** as the chart candles (`symbol:iv:55`) -> no extra fetch.
  On 1h/4h it is one extra cached entry (`symbol:1h:180`), which calls `fetch_intraday_candles` with
  the watch's exact arguments (same yfinance period, same IBKR/Tradier merge). Completion is judged
  at **that entry's** `fetched_at` (A4c), then cut at the closed candle (2.6). No 1500 cap.
  HMM fits the last 800 bars, so on 1h the old 730d series and the new 180d series (~880 bars)
  give the SAME rule input; the real 1h change is the watch's 55 -> 180. The rule-side change is
  behavioural on 4h (~250 vs 800 bars).
  A failed fetch -> `[]` -> HMM_intraday/VWAP fail closed (as today when bars are missing).
- **`/regime-snapshot`:** unchanged (already the watch's fetch).
- `_regime_candles` (1500 cap, `as_of`) stays for standard rules and nothing else in the composite
  block (OMM moves in 2.5).

### 2.2 Daily rows: which rows a candle may read (item 5 + catch-up; round 2 findings 1, 2, 9)

Round 2 showed r2's `X = min(now, candle close)` is never later than `_as_of_dt` (the closed candle
is `candles[-2]` of a snapshot taken at `as_of`), so it did not implement item (5), and that
`completed_daily_rows(rows, D 16:00:00)` drops row D (the close instant is inclusive-forming,
`market_session.todays_bar_is_unclosed`), which would break 1D/1W parity.

**Rule (r3, needs Kenneth — Q-B):** a composite rule judging a closed candle reads exactly the daily
rows whose **session close is at or before that candle's close instant** ("the rows completed when
the candle closed"). Candle close instant:
- intraday: `time + span` (`_INTERVAL_COMPLETION_SECONDS`);
- 1D / 1W: the first session close (1D) / week close (1W) **at or after** the stamp — the
  convention `completed_session_bars` already relies on (every stamp in use — 00:00 ET, 00:00 UTC,
  session open, session close; Monday or Friday for a week — lies after the previous close and at or
  before its own);
- undatable `closed_candle["time"]` (non-int, bool): daily rows `[]` (fail closed) + one WARNING;
  no raise outside the per-row try.

Consequences: the 1D candle for day D keeps row D; the 1W candle keeps that Friday; the 15:45
15min candle (close 16:00) keeps row D; a 15:15 candle never sees day D's close (no look-ahead,
catch-up included). `_as_of_dt` is no longer used for daily rows. Item (5)'s literal wording
("trim at now") would let a pre-close candle read the session's close; r3 proposes the rule above
instead (Q-B). For the newest candle the two differ only when a stale snapshot straddles 16:00,
and then the candle-close rule is the correct one. In practice the D row rarely exists on day D
(get_bars fetches through `_prev_trading_day`).

Helper: `daily_rows_at_candle(rows, closed_candle, interval)` (pure, in
`composite_trigger_evaluator.py`), built on `last_session_close` / `last_week_close` and
`completed_daily_rows`; unit-tested at 15:59:59 / 16:00:00 / 16:00:01, all stamp conventions,
Friday for 1W, and undatable stamps.

### 2.3 1W and 1D read completed daily get_bars rows (item 8, SCOPE (1))

Delete `_bars_daily = _regime_candles`. One `get_bars(symbol, date.today()-730d, date.today())`
(the watch's `_HISTORY_DAYS` window), cut by 2.2, shared by `bars_daily`, `bars_vwap_daily` and OMM.
Fetched whenever composite rules exist (not only when some rule "needs" it — round 2 finding 13:
`trigger_values.omm_state` stays filled for every composite fire as today). Failure -> `[]` for all
(fail closed). **Memoised** per `(symbol, date.today())` for 300 s in a module-level dict inside the
composite block's helpers (round 2 finding 7: OMM is the default model and the chart WS evaluates on
every tick; `get_bars` can hit the providers all day after a holiday, `_prev_trading_day` has no
holiday calendar). The cut (2.2) is applied after the memo, per candle.

Every `.get("primary", {})` in the block becomes `(_rj.get("primary") or {})` (round 2 finding 5 —
`chart_alerts.py:1059` runs per row outside the try; `composite_def` is stored unvalidated).

**Freshness.** A 1D rule judges day D as `candles[-2]` once D+1's candle exists (scheduler and WS),
when `_prev_trading_day()` is D, so get_bars has D unless a partial D row was stored. Round 2
corrected r2's frequency claim: a partial row is stored whenever `get_bars` runs **during** session
D while the DB lacks D-1 (`historical_store.py:230-232`: fetch `last+1 .. today`, a provider may
return today's forming bar), and it is never refetched. This already affects every composite watch
and intraday rule's daily inputs; r3 extends it to 1D/1W rules and OMM. -> **Q-C**.

### 2.4 `/regime-snapshot` reads what the watch reads (round 1 finding 1, round 2 finding 15)

OMM and HMM_daily: `completed_daily_rows(get_bars(today-730d, today), datetime.now(MARKET_TZ))`;
OMM with the trigger's `direction` (as today; now equal to what both paths compare, decision
OMM-DIRECTION). The "no price history" 404 applies to OMM/HMM_daily only; HMM_intraday no longer
depends on the daily rows. Existing router tests whose rows lack `time` are updated.

### 2.5 Composite OMM (SCOPE (2), OMM-DIRECTION)

- Watch: `evaluate_scheduled`'s OMM line passes `direction=` the trigger's direction (same
  default "Bullish" when absent) — the only line of that function touched.
- Rule: `_omm` becomes a per-direction memo within the call (`{"Bullish": ..., "Bearish": ...}`,
  computed lazily from the 2.2-cut rows, round 2 finding 12); `trigger_values.omm_state` reads the
  firing rule's direction entry. `compute_omm` returns None below its own minimum (verified), so
  the rule's `len >= 100` pre-check goes.

### 2.6 Intraday model series cut at the closed candle (catch-up)

Bars with int `time <= closed_candle["time"]`; an undatable closed-candle time -> series `[]`
(HMM_intraday / VWAP fail closed) + WARNING, never a TypeError (round 2 finding 9).

### 2.7 The model series must reach the closed candle (round 2 finding 11)

After the cut, if the series' last `time != closed_candle["time"]`, refetch once with
`max_age=0` (forces a refetch through `refresh_on_close`); still short -> series `[]` (fail
closed) + WARNING naming the gap. Pinned by a test with a stalled cache entry.

### 2.8 Unchanged, stated

`_regime_candles` (1500 cap, `as_of`) keeps serving standard rules. The chart display windows,
chart_cache code and TTLs are unchanged. `chart_cache.py:115-118`'s docstring ("the chart WebSocket
... pass neither") becomes false because the WS path now reaches `refresh_on_close` through the
composite block -> **Q-D** (a comment-only edit in a file this task does not own).

### 2.9 Coordination with COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD (round 2 finding 10)

Both packages own "the chart_alerts composite block". Before build: `claim.py list`, fetch the
momentum branch and read its diff of the block; whichever merges second merges main in and
resolves (no rebase of the other's branch). The OMM line of `evaluate_scheduled` is not a momentum
path; recorded as such in decision OMM-DIRECTION.

## 3. Tests and mutations

**Harness (round 2 finding 3).** `chart_cache` binds `fetch_intraday_candles` at import and judges
`fetched_at` with the real clock, and its cache is module-global. Every new or updated rule-path
test: patches `app.data.chart_cache.fetch_intraday_candles` (and the watch's
`app.data.market.fetch_intraday_candles`) with ONE pure stub of `(interval, days)` that returns
`days + 4` days of a synthetic universe; injects the clock by patching `chart_cache.time` and the
`as_of`/`now_ts` arguments; clears `_INTRADAY_CACHE` and the new daily-row memo in an autouse
fixture; patches `get_bars` at both import sites (`app.routers.chart_alerts.get_bars`,
`app.services.strategy_watch_evaluator.get_bars`, the router's lazy import).

New file `tests/test_watch_rule_bar_parity.py`:
1. 1h HMM_intraday: both paths call the fetch with `days=180`; the HMM receives 800 bars equal on
   both paths (absolute assertions, not only equality — round 2 finding 6).
2. 4h HMM_intraday: `days=180` on both; ~250 bars equal; the old rule input (800) differs.
3. 15min HMM_intraday: `days=55`; the rule reuses the chart's cache entry (one fetch).
4. 1h VWAP: identical slices on both paths.
5. 1D and 1W: HMM_daily, rsi, bb and VWAP-daily read the get_bars rows on both paths; the 1D
   candle keeps row D, the 1W candle keeps Friday; weekly/chart candles unread.
6. OMM on 15min, 1D, 1W, Bullish and Bearish: identical closes and direction to `compute_omm` on
   both paths; `primary` missing, `primary: null` and `model: null` never raise.
7. Daily cut (2.2): candle closes at 15:30 -> no row D; 16:00:00 -> row D; undatable time -> `[]`.
8. Catch-up: an older `view` -> no daily row or intraday bar after that candle reaches any model.
9. `/regime-snapshot` OMM/HMM_daily inputs == the watch's `bars_daily`; Bearish direction pinned;
   HMM_intraday does not 404 on empty daily rows.
10. One get_bars call across repeated evaluations within the memo window; a new call after it.
11. Stalled model entry (2.7): one forced refetch, then fail closed.
12. `trigger_values.omm_state` present on an HMM_intraday-only composite fire.

Existing tests updated (intended new assertion in brackets):
- `test_p4b_4h_history.py` [1h -> 180];
- `test_a4c_user_alert_completed_bars.py:170-201` shared `_run` + composite-OMM case [OMM reads
  completed daily get_bars closes; harness patches];
- `test_a4g_forming_daily_weekly_bar.py` 1D/1W chart-path cases incl. D2 composite OMM (`:272`)
  [bars_daily/OMM from get_bars, cut per 2.2];
- `test_chart_alerts_composite_ws.py:233-257` [1D HMM_daily now calls get_bars] and `:261-288`
  [15min HMM_intraday via the patched chart_cache stub];
- `test_a4f_rules_hmm_intraday_interval.py:234-270` [the HMM receives the model fetch, 5min];
- `test_p4b_vwap_like_regime_models.py:125-170` and every `_rule_fired` user [rule fed through the
  chart_cache stub];
- `test_composite_watch_router.py` snapshot tests [rows carry `time`; 404 only for OMM/HMM_daily];
- any other test found at build by `pytest` red on the first run (listed in the build commit).
Docstring of `evaluate_and_notify_for_symbol` (`chart_alerts.py:888-896`) corrected.

**Mutations -> the test that kills each:** m1 1h back to 55 -> 1 (absolute `days=180`);
m2 rule HMM series from `_regime_candles` -> 2; m3 rule fetch with default days -> 1, 2;
m4 restore the 1W branch -> 5; m5 restore a 1D branch -> 5; m6 daily cut at `_as_of_dt` -> 8
(`as_of` is never before the candle's close, so this keeps later sessions on a catch-up candle); m7 cut at the close instant
exclusive (r2 bug) -> 5, 7; m8 `_omm` on `_regime_candles` -> 6; m9 OMM without direction on
either path -> 6, 9; m10 `.get("primary", {})` back -> 6; m11 drop the catch-up cut, daily -> 8;
m12 drop it, intraday -> 8; m13 snapshot back to 400d / no completion -> 9; m14 no memo -> 10;
m15 no refetch-then-fail-closed -> 11.

Before each push: full `cd backend && pytest`, `python3 scripts/state.py`, PROJECT_STATE phase +
probe updated (defect marker gone -> presence probe on `daily_rows_at_candle`).

## 4. Behaviour changes and residual non-parity

Changes: 1h watches fit HMM_intraday on 180d; 4h rules fit on 180d; 1D/1W rules read the
historical store's daily rows; every composite OMM (watch and rule) judges daily OMM in the
trigger's direction — Bearish OMM composites change on both paths; `/regime-snapshot` OMM/HMM_daily
show 730d completed rows; catch-up candles stop reading later data; a composite rule whose model
series cannot reach the closed candle fails closed instead of fitting a stale series.

Residual non-parity, out of scope (logged as open questions at build):
- different fetch instants (cache TTL, IBKR up on one fetch only, Tradier sandbox partial bar);
- partial daily rows stored mid-session (Q-C);
- structure confirmations: watch = daily-bar structure, rule = chart-interval signals (no owner);
- momentum confirmations: COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD;
- `primary.model: null`: the rule passes the primary, the watch fails it (round 2 finding 14).

## 5. Questions for Kenneth (r3)

- **Q-B** daily rows per candle: adopt 2.2's rule ("a candle reads the rows completed when it
  closed"), which replaces item (5)'s literal "trim at now". Recommended.
- **Q-C** partial daily rows: accept for now and open a separate task for `historical_store`
  (recommended), or extend this task into `historical_store.py`.
- **Q-D** allow a comment-only fix of `chart_cache.py:115-118`'s docstring. Recommended.
