# WATCH-RULE-BAR-PARITY — plan r6 (after adversarial rounds 1-3; Q-B..Q-I answered; final plan)

**r5 -> r6 (decision `WATCH-RULE-BAR-PARITY-BUILD-AFTER-PLAN-CAP-2026-09-28`).** r6 = r5 + Q-H (keep
`get_bars`' fetch rule, 2.10) + Q-I (no legacy watch-direction fallback, 2.5). The exchange that
raised Q-H and Q-I after round 3 left **no saved findings** beyond those two questions; nothing else
in r5 changed because of it. No further plan round: build as two audit units -- **unit A** = 2.10
(`historical_store`), built and audited first; **unit B** = 2.1-2.9 on top of A. Each unit gets up to
3 code rounds under audit_rule v2's gate; rounds after the first review only the previous round's fixes.

Task: PROJECT_STATE phase `WATCH-RULE-BAR-PARITY`, decision `P4B-FOLLOWUPS-2026-09-26` items
(4), (5), (8), plus decisions `WATCH-RULE-BAR-PARITY-SCOPE-2026-09-28` (1D rules, OMM; its item 3 is moot) and
`WATCH-RULE-BAR-PARITY-OMM-DIRECTION-2026-09-28` (OMM uses the trigger's direction on both paths),
`WATCH-RULE-BAR-PARITY-PARTIAL-ROW-2026-09-28` (the partial-daily-row fix in `historical_store.py`, 2.10)
`WATCH-RULE-BAR-PARITY-QB-QD-2026-09-28` (2.2's candle-close rule; comment-only `chart_cache.py` fix)
`WATCH-RULE-BAR-PARITY-QE-QF-QG-2026-09-28` (1D/1W lag accepted and documented; never store an
unsettled daily row; three out-of-scope descriptions of `get_bars` corrected),
`WATCH-RULE-BAR-PARITY-Q-H-FETCH-RULE-2026-09-28` (`get_bars`' staleness/fetch condition unchanged) and
`WATCH-RULE-BAR-PARITY-Q-I-LEGACY-WATCH-DIRECTION-2026-09-28` (no watch-direction fallback).
Scope and owned files: `docs/superpowers/plans/2026-09-25-work-packages.md` section "P4b follow-ups".
Loop: plan -> adversarial rounds until clean -> build + mutations -> code round -> merge when clean.

**Owned (as used by r2):** `backend/app/routers/chart_alerts.py` — the composite block of
`evaluate_and_notify_for_symbol` and its docstring sentences about composite inputs;
`backend/app/services/composite_trigger_evaluator.py` — `intraday_history_days` /
`_INTRADAY_HISTORY_DAYS`, the new pure helpers of 2.6, and the OMM line of `evaluate_scheduled`
(decision OMM-DIRECTION);
`backend/app/routers/composite_watch.py` — the `/regime-snapshot` fetches;
`backend/app/services/historical_store.py` — `get_bars`, `_store_bars`, `most_recent_trading_day` /
`_prev_trading_day`'s clock, and the new settle helpers of 2.10 (decisions PARTIAL-ROW, Q-F); their
tests.
**Comment/test-only edits outside the owned code (Q-D, Q-G):** `chart_cache.py:115-118` docstring;
`auto_trader.py:673-676` comment; `completed_daily_rows`' docstring in
`composite_trigger_evaluator.py` (its "get_bars never re-fetches" limit sentence);
`tests/test_auto_trader.py` `_scan_series_times` helper (models get_bars' fetch rule).
**Not touched:** `chart_cache.py` code (called with an explicit `days`);
`strategy_watch_evaluator.py`; `evaluate_scheduled` beyond its OMM line; `evaluate_from_context*` /
`describe_match` / `_matched_strategy_signals` (COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD holds a live
claim on those functions' momentum paths **and on the chart_alerts composite block** — see 2.9);
`market_session.py`, `ingestion_job.py`, `auto_trader.py`, `scan.py` (callers of `get_bars` whose
behaviour 2.10 changes are listed there, not edited); the rest of `chart_alerts.py` (P4a).

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

**Rule (Q-B ANSWERED 2026-09-28: adopted, replaces item (5)'s literal "trim at now"):** a composite rule judging a closed candle reads exactly the daily
rows whose **session close is at or before that candle's close instant** ("the rows completed when
the candle closed"). Candle close instant `T`:
- intraday: `time + nominal span` from a new `_NOMINAL_SPAN_SECONDS` (1min 60 ... 1h 3600, 4h
  14400) in `composite_trigger_evaluator.py` -- **not** `_INTERVAL_COMPLETION_SECONDS`, whose 4h
  entry is 5 h (a completion lag, `market.py:623`) and would let an 11:00-stamped 4h candle read
  row D (round 3 finding 15);
- 1D / 1W: the first session close (1D) / week close (1W) **at or after** the stamp — the
  convention `completed_session_bars` already relies on (every stamp in use — 00:00 ET, 00:00 UTC,
  session open, session close; Monday or Friday for a week — lies after the previous close and at or
  before its own);
- undatable `closed_candle["time"]` (non-int, bool): daily rows `[]` (fail closed) + one WARNING;
  no raise outside the per-row try.

Consequences: the 1D candle for day D keeps row D; the 1W candle keeps that Friday; the 15:45
15min candle (close 16:00) keeps row D; a 15:15 candle never sees day D's close (no look-ahead,
catch-up included). `_as_of_dt` is no longer used for daily rows. Item (5)'s literal wording
("trim at now") would let a pre-close candle read the session's close; Kenneth adopted the rule
above instead (Q-B). For the newest candle the two differ only when a stale snapshot straddles 16:00,
and then the candle-close rule is the correct one. `get_bars` fetches through `end` (today) when `last < min(end, _prev_trading_day())`;
`_prev_trading_day` is only the staleness threshold. With 2.10 no row is stored before its
session's close + 30 min, so a row D exists only after that.

Helper: `daily_rows_at_candle(rows, closed_candle, interval)` (pure, in
`composite_trigger_evaluator.py`). **Exact formula (round 3 finding 12):** keep row `d` iff
`close(d) <= T`, with `close(d) = datetime.combine(d, 16:00, MARKET_TZ)` computed directly. For
1D/1W, `T` = `close(d')` for the first weekday `d'` (1D) / first Friday `d'` (1W) with
`close(d') >= stamp`. It does **not** call `completed_daily_rows`, `last_session_close` or
`last_week_close`: those answer "latest close at or before", and `todays_bar_is_unclosed` is
inclusive at 16:00:00, so `completed_daily_rows(rows, close(D))` drops row D (the r2 bug).
Unit-tested at 15:59:59 / 16:00:00 / 16:00:01, all stamp conventions, 4h and 1h stamps, Friday for
1W, and undatable stamps.

**Accepted structural lag (Q-E, round 3 finding 1).** The rule judges `candles[-2]`
(`chart_alert_scheduler.py:193`); the watch cuts daily rows at *now*
(`strategy_watch_evaluator.py:374`). So on 1D, from close(D) until D+1's candle exists (~17 h) the
rule reads rows to D-1 and the watch to D; on 1W the rule reads to last Friday while the watch reads
this week's completed days (up to a week). Kenneth accepted this 2026-09-28 as documented, not
fixed (fixing it means the watch evaluator or the scheduler's candle pick, both out of scope). Test
5 asserts each path's rows explicitly, never "equal".

### 2.3 1W and 1D read completed daily get_bars rows (item 8, SCOPE (1))

Delete `_bars_daily = _regime_candles`. One `get_bars(symbol, date.today()-730d, date.today())`
(the watch's `_HISTORY_DAYS` window), cut by 2.2, shared by `bars_daily`, `bars_vwap_daily` and OMM.
Fetched whenever composite rules exist (not only when some rule "needs" it — round 2 finding 13:
`trigger_values.omm_state` stays filled for every composite fire as today). Failure -> `[]` for all
(fail closed). **Memoised** per `(symbol, settle boundary)` for 300 s, where the settle boundary is the latest
`close(d) + _SETTLE <= now` (round 3 finding 13: a row can only appear in the store at a boundary,
2.10, so the key changes exactly when a new row can exist and the rule never keeps a pre-boundary
copy the watch no longer reads) in a module-level dict inside the
composite block's helpers (round 2 finding 7: OMM is the default model and the chart WS evaluates on
every tick; `get_bars` can hit the providers all day after a holiday, `_prev_trading_day` has no
holiday calendar). The cut (2.2) is applied after the memo, per candle.

Every `.get("primary", {})` in the block becomes `(_rj.get("primary") or {})` (round 2 finding 5 —
`chart_alerts.py:1059` runs per row outside the try; `composite_def` is stored unvalidated).

**Freshness (r5, after Q-F).** No daily row is stored before `close(d) + _SETTLE` (2.10), so
every row either path reads is settled, apart from legacy rows written before this fix (healed by
2.10). A 1D rule judges D once D+1's candle exists; by then row D is in the store if any `get_bars`
call after `close(D) + 30 min` ran with `last < _prev_trading_day()`, else it arrives with the
nightly ingestion or the first call on D+1 (existing staleness rule, unchanged). Both paths read the
same `get_bars`, and the memo key moves at the settle boundary, so the only remaining difference is
the fetch instant (section 4) and the Q-E lag.

### 2.4 `/regime-snapshot` reads what the watch reads (round 1 finding 1, round 2 finding 15)

OMM and HMM_daily: `completed_daily_rows(get_bars(today-730d, today), datetime.now(MARKET_TZ))`;
OMM with the trigger's `direction` (as today; now equal to what both paths compare, decision
OMM-DIRECTION). The "no price history" 404 applies to OMM/HMM_daily only; HMM_intraday no longer
depends on the daily rows. Existing router tests whose rows lack `time` are updated.

### 2.5 Composite OMM (SCOPE (2), OMM-DIRECTION)

- One pure helper `omm_direction(trigger_def)` in `composite_trigger_evaluator.py`:
  `trigger_def["direction"]` if it is exactly "Bullish"/"Bearish", else "Bullish" (Q-I: no fallback
  parameter). `compute_omm` raises `ValueError` on anything else (`regime_omm.py:182`) and
  `composite_def` is stored unvalidated, so the value is never passed through raw (round 3 finding 9).
- Watch: `evaluate_scheduled`'s OMM line passes `direction=omm_direction(trigger_def)`. The only
  line of that function touched. **Q-I (2026-09-28):** `evaluate_scheduled` cannot see the watch's own
  saved `direction` without a new parameter and an edit of its caller in
  `strategy_watch_evaluator.py` (not owned; the momentum task owns that call), so there is **no
  fallback**: a legacy Bearish watch whose `trigger_def` has no direction (dialogs before
  `CompositeAlertDialog` index.tsx:126-130, or "any" = null) keeps judging Bullish OMM exactly as
  today. Follow-up logged: pass the watch's direction through to `evaluate_scheduled`.
- Rule: `_omm` becomes a per-direction memo within the call (`{"Bullish": ..., "Bearish": ...}`),
  keyed by `omm_direction(_td)` and computed lazily **inside the per-row try** from the
  2.2-cut rows (round 2 finding 12; round 3 finding 9 -- today's `_omm` at `chart_alerts.py:1004`
  sits outside any try, and a raise there would abort the block after standard-rule emails and
  before the commit); `trigger_values.omm_state` reads the
  firing rule's direction entry. `compute_omm` returns None below its own minimum (verified), so
  the rule's `len >= 100` pre-check goes.

### 2.6 Intraday model series cut at the closed candle (catch-up)

Bars with int `time <= closed_candle["time"]`; an undatable closed-candle time -> series `[]`
(HMM_intraday / VWAP fail closed) + WARNING, never a TypeError (round 2 finding 9).

### 2.7 The model series must reach the closed candle (round 2 finding 11)

After the cut, if the series' last `time != closed_candle["time"]`, refetch with `max_age=0`
(forces a refetch through `refresh_on_close`) **at most once per `(symbol, interval, as_of)`**
(module dict, pruned to the last 64 keys): `evaluate_closed_candles` calls the block once per
catch-up candle (`chart_alert_scheduler.py:139-160`), and without the bound a stalled entry would
cost one 180-day refetch per candle (round 3 finding 14). Still short -> series `[]` (fail closed)
+ WARNING naming the gap. Pinned by a test with a stalled cache entry and a 3-candle catch-up (one
refetch).

### 2.8 Unchanged, stated

`_regime_candles` (1500 cap, `as_of`) keeps serving standard rules. The chart display windows,
chart_cache code and TTLs are unchanged. `chart_cache.py:115-118`'s docstring ("the chart WebSocket
... pass neither") becomes false because the WS path now reaches `refresh_on_close` through the
composite block -> Q-D answered: comment-only edit allowed.

### 2.9 Coordination with COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD (round 2 finding 10)

Both packages own "the chart_alerts composite block". Before build: `claim.py list`, fetch the
momentum branch and read its diff of the block; whichever merges second merges main in and
resolves (no rebase of the other's branch). The OMM line of `evaluate_scheduled` is not a momentum
path; recorded as such in decision OMM-DIRECTION.

### 2.10 Never store an unsettled daily row (decisions PARTIAL-ROW, Q-F)

**Defect.** `get_bars` fetches `last+1 .. end` whenever `last < min(end, _prev_trading_day())`
(`historical_store.py:230`). During session D that range includes D; Alpaca and Tiingo may return
D's **forming** bar (yfinance does not: its `end` is exclusive, `historical_store.py:184-187`, and
stale mode passes `end=today`), and `_store_bars` upserts it. From D+1, `last == D ==
_prev_trading_day()` so nothing refetches D, and once a later stale fetch appends from `last+1`
the row is buried for good. `ingestion_job.run_ingestion` writes the same way when run in session
(`fetch_end = date.today()`, manual run or the startup catch-up); the nightly Alpaca batch rewrites
the range, so universe symbols heal overnight, but custom-universe and gap-fill symbols do not.

**Rule (Q-F).** `_SETTLE = timedelta(minutes=30)`; `close(d) = datetime.combine(d, dtime(16, 0),
MARKET_TZ)` with `MARKET_TZ` from `scheduling_tz` (no import chain; **not** `market_session`,
whose import of `strategy_watch_scheduler` would make a cycle with this module and add 0.3 s to the
first `get_bars` — round 3 minor). `is_settled(d, now) := now >= close(d) + _SETTLE`.
1. `_store_bars` drops every bar with `not is_settled(date, _utcnow())` before the upsert (one
   DEBUG line with the count). This covers `get_bars` and `ingestion_job` alike: no forming row can
   enter the store from any writer.
2. **Legacy rows** (written before this fix) are healed: a row is *provisional* iff `fetched_at <
   close(d) + _SETTLE`. `get_bars` reads the `(date, fetched_at)` pairs in `[start, end]` (one
   extra indexed SELECT; ~500 rows at 730 days); `heal = min(d provisional and is_settled(d, now))` (a legacy row
   for today written in session before deploy waits for its own settle). Stale mode: `fetch_start = min(last+1, heal)`. Heal-only
   mode (not stale): fetch `heal .. end + 1 day` (the `+1` makes the request independent of each
   provider's `end` inclusivity -- Alpaca is passed a date-only `end`, `alpaca.py:44`, and its
   inclusivity is not verified here; the settled filter of step 1 and a `date <= end` filter make
   the extra day harmless).
3. **Heal success** = a row for date `heal` was stored with a new `fetched_at`. Otherwise the chain
   falls through to the next provider (today "first success wins" on any non-empty list,
   `historical_store.py:243/260/277`, which could stop at a provider that returns other dates but
   not `heal`). **Retry bound** (round 3 finding 7): a module dict `(symbol, heal date) -> next
   attempt` allows one heal attempt per pair per 6 h; a halted, delisted or IEX-missing day is then
   retried four times a day, not per call.
4. `fetched_at` is normalised by one helper `_as_utc(dt)`: naive (SQLite stores the UTC wall
   clock) -> `replace(tzinfo=UTC)`; aware (PostgreSQL) -> `astimezone(UTC)`.
5. **Clock (round 3 finding 2).** One `_utcnow()` feeds `_store_bars` (`fetched_at` and the settled
   filter), the heal test, and a `_host_today()` = `_utcnow().astimezone().date()` that replaces
   `date.today()` inside `most_recent_trading_day` (so `_prev_trading_day` follows). This is the
   host's date exactly as today (host zone, not New York -- the anchor residual recorded in
   `market_session.todays_bar_is_unclosed` is unchanged); tests patch `_utcnow` alone.

**Fetch rule unchanged (Q-H, 2026-09-28).** The staleness condition `last < min(end,
_prev_trading_day())` is **not** changed; heal (step 2) adds fetches only for legacy provisional
rows. Consequence Kenneth accepted: a stale-DB symbol first read on day D before D's settle (16:30)
gets rows through D-1 and stores `last = D-1 == _prev_trading_day()`, so nothing fetches D until the
nightly ingestion or the first call on D+1 -- in practice nearly every symbol read in session, not
only one first read in 16:00-16:30 (r5 understated this). After the close such a symbol's scan ends
at D-1 while guard (i)'s gate keeps D: the fresh-DB mismatch accepted 2026-09-22, now common.
Follow-up logged: "fetch day D once it has settled" (~500 fetches on the first post-settle scan,
Alpaca-rate-limited to ~2-3 min; changes post-close scan results for every symbol).

**Behaviour changes for every `get_bars` caller** (round 3 findings 4, 5; none edited):
- `routers/scan.py:1574` (options scan), `routers/stock_scan.py` (7 sites: :345 regime proxy, :638,
  :913 benchmark, :1044, :1500 SPY, :1684 fib-pullback, :1794 prebreakout),
  `strategy_param_optimizer`, `historical_store._run_prefetch` (:315, which also warms the
  confidence cache from the result):
  * **In session, stale-DB symbol:** today's forming bar is no longer stored or returned; the
    series ends at D-1. The auto-trade gate trims today's forming bar in session (guard (i)), so
    scan and gate now **agree** where they disagreed. Confidence-cache entries computed in session
    for such symbols change accordingly.
  * **Legacy partial row D-1 (or buried D-k):** healed on the first call; the series keeps its
    length and only those rows' values change, in session or not.
  * **Stale-DB symbol first read after 16:30 on D:** row D is stored and returned (complete), as
    before.
  * **Stale-DB symbol first read before 16:30 on D (Q-H):** row D is skipped; `last` becomes D-1 ==
    `_prev_trading_day()`, so D arrives only with the nightly ingestion or the first call on D+1.
    For that evening the scan ends at D-1 while guard (i)'s gate keeps D -- **the same mismatch
    Kenneth accepted for the fresh-DB path**
    (AUTOTRADE-2B-CORE-GUARD-I-KEPT-COMMON-PATH-COST-ACCEPTED-2026-09-22), accepted again for this
    case by Q-H.
  * **Fresh DB:** unchanged (nightly rows have `fetched_at` after the settle; no heal, no fetch).
- `auto_trader`: the fire path does not call `get_bars`; only the agreement above changes. The
  `auto_trader.py:673-676` comment ("would hand back ... partial bar included") becomes false and
  is corrected (Q-G); `test_auto_trader.py`'s `_scan_series_times` helper gets the new ceiling
  (`min(end, last settled day)` on a backfill) by calling the production `is_settled`, so the
  AUTOTRADE-2B acceptance tests keep modelling the real scan (Q-G).
- `ingestion_job`: step 1 stores only settled rows (an in-session manual run or startup catch-up no
  longer writes ~600 forming rows -- round 3 finding 6's burst source is removed, not throttled);
  step 3's gap-fill heals as above.
- `regime.py`, `composite_watch.py`, `chart_alerts.py`, `strategy_watch_evaluator.py`: read settled
  rows only.

**One-time legacy heal burst.** Rows written in session before this fix are healed on first read;
universe symbols with Alpaca are rewritten nightly anyway. At build, a read-only count of
provisional rows in the dev DB is recorded in the build commit; the per-pair retry bound caps
repeats.

**Residuals (section 4):** the before-settle case above (Q-H); provisional legacy rows outside every
caller's range stay (all production callers ask >= 400 days ending today); half-days settle at
16:30 not 13:30 (one row later than necessary on three days a year).

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
   candle keeps row D, the 1W candle keeps Friday; weekly/chart candles unread. **Each path's rows
   are asserted separately**, including mid-week (1W) and D evening (1D), where they differ (Q-E).
6. OMM on 15min, 1D, 1W, Bullish and Bearish: identical closes and direction to `compute_omm` on
   both paths; `primary` missing, `primary: null` and `model: null` never raise.
7. Daily cut (2.2): candle closes at 15:30 -> no row D; 16:00:00 -> row D; undatable time -> `[]`;
   4h candle stamped 11:00 ET -> no row D, 12:00 ET -> row D; 1h 15:30 -> row D.
8. Catch-up: an older `view` -> no daily row or intraday bar after that candle reaches any model.
9. `/regime-snapshot` OMM/HMM_daily inputs == the watch's `bars_daily`; Bearish direction pinned;
   HMM_intraday does not 404 on empty daily rows.
10. One get_bars call across repeated evaluations within the memo window; a new call after it and
    at a settle boundary crossing.
11. Stalled model entry (2.7): one forced refetch, then fail closed; a 3-candle catch-up forces
    one refetch in total.
12. `trigger_values.omm_state` present on an HMM_intraday-only composite fire.

New file `tests/test_historical_store_settle.py` (2.10) -- in-memory aiosqlite engine patched over
`historical_store.AsyncSessionLocal`, `_utcnow` patched (so `_host_today`, `most_recent_trading_day`
and `_prev_trading_day` follow; every scenario pins a weekday), the three providers stubbed with
recorded `(start, end)` calls (the yfinance stub honours an exclusive `end`):
13. Q-C scenario, new writes: DB ends D-2; a call at session D 11:00 with providers returning D-1
    and a forming D stores D-1 only and returns a series ending D-1; the same scenario run fresh
    (DB again ending D-2) at 16:29:59 stores D-1 only, and at 16:30:00 stores D-1 and D.
14. `_store_bars` directly (ingestion's writer): a batch holding today's forming row stores all
    rows but that one.
15. Legacy heal-only: a pre-existing row D-1 with `fetched_at` session D-1 11:00 is refetched at
    D 11:00 (fetch `D-1 .. end+1`), its close replaced, **series length unchanged**, no row D stored.
16. Buried legacy row: provisional D-3 plus settled D-2..D-1 and a stale DB -> the stale fetch
    starts at D-3, not `last+1`.
17. Heal success falls through: Alpaca returns other dates but not the heal date -> Tiingo is
    called; nothing returns it -> one attempt, then no provider call within 6 h, one after.
18. Fresh DB (nightly rows, `fetched_at` 02:00 next day) at session D and after the close:
    **zero provider calls**.
19. `_as_utc`: naive and aware inputs, under `TZ=America/Los_Angeles` (`monkeypatch.setenv` +
    `time.tzset()`), so a "read naive as local" mutant is visible on a UTC host (round 3 finding 3).
20. yfinance-only chain heals today's own legacy row after 16:30 (`end + 1` passed).
21. Composite direction: `omm_direction` table (valid, lower-case, "Neutral", None, missing key,
    non-dict); a rule with direction "bullish" and a watch with `trigger_def.direction` null both
    reach `compute_omm` with "Bullish" (Q-I); a Bearish trigger reaches it with "Bearish"; no raise
    escapes the block.
22. Q-H pin: a stale DB ending D-2, first call at D 11:00 stores D-1 only; a second call at D 17:00
    makes **zero** provider calls and still ends at D-1 (fetch rule unchanged).
Existing `test_historical_store.py` / `test_historical_store_guard.py` stay green unchanged (fixed
2024 dates, all settled).

Suite hygiene (round 3 finding 11): `tests/conftest.py` gets an autouse fixture clearing the new
module-level memos (daily rows, refetch bound, heal retry bound).
`test_composite_sustain.py:52-168` and `test_a4e_closed_candle_alignment.py:155-199` call the
composite block without patching `get_bars`; they get the same `get_bars` patch as the parity
tests (they would otherwise go to real providers and stay green). The build also greps every test
calling `evaluate_and_notify_for_symbol` with a composite rule and lists them in the build commit.

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
m15 no refetch-then-fail-closed -> 11;
m16 `_store_bars` without the settled filter -> 13, 14; m17 `_SETTLE` dropped (compare to `close(d)`)
-> 13; m18 `>` instead of `>=` in `is_settled` -> 13 (16:30:00); m19 stale mode starts at `last+1`
-> 16; m20 no heal (legacy provisional ignored) -> 15; m21 heal-only provider `end` without `+1` ->
20; m22 heal success = any non-empty list -> 17; m23 no retry bound -> 17; m24 `_as_utc` reads naive
as local -> 19; m25 heal triggered on nightly rows -> 18; m26 `_host_today` bypassed (`date.today()`
kept) -> 13 (pinned weekday vs real date); m27 raw direction to `compute_omm` -> 21; m28 watch
OMM without `omm_direction` (Bullish default kept, trigger direction ignored) -> 21; m32 fetch D
after it settles (staleness uses last settled day) -> 22; m29 daily cut via `_INTERVAL_COMPLETION_SECONDS` -> 7
(4h 11:00); m30 memo keyed by date only -> 10; m31 refetch bound per call instead of per
`(symbol, interval, as_of)` -> 11.

The Q-D docstring fix (`chart_cache.py:115-118`) is comment-only and needs no test; the build
commit quotes old and new text.

Before each push: full `cd backend && pytest`, `python3 scripts/state.py`, PROJECT_STATE phase +
probe updated (defect marker gone -> presence probes on `daily_rows_at_candle` and on `def is_settled` in
`historical_store.py`, round 3 finding 16).

## 4. Behaviour changes and residual non-parity

Changes: 1h watches fit HMM_intraday on 180d; 4h rules fit on 180d; 1D/1W rules read the
historical store's daily rows; every composite OMM (watch and rule) judges daily OMM in the
trigger's direction — Bearish-trigger OMM composites change on both paths; `/regime-snapshot` OMM/HMM_daily
show 730d completed rows; catch-up candles stop reading later data; a composite rule whose model
series cannot reach the closed candle fails closed instead of fitting a stale series; no daily row is
stored before its session's close + 30 min and legacy partial rows are refetched (2.10) -- scans,
regime, watches and rules read completed bars only; an in-session scan of a stale-DB symbol ends at
D-1 (now agreeing with guard (i)'s gate).

Residual non-parity, out of scope (logged as open questions at build):
- different fetch instants (cache TTL, IBKR up on one fetch only, Tradier sandbox partial bar);
- **1D/1W structural lag (Q-E, accepted):** the rule reads rows to the judged candle's close, the
  watch to now -- up to ~17 h on 1D and a week on 1W (2.2);
- a stale-DB symbol first read before D's settle (16:30) lacks row D that evening -- nearly every
  symbol read in session; scan vs guard (i) gate then show the accepted fresh-DB mismatch (2.10,
  Q-F, Q-H; follow-up "fetch day D once it has settled");
- a legacy Bearish watch whose `trigger_def` has no direction judges Bullish OMM, as today (Q-I;
  follow-up "pass the watch's direction to `evaluate_scheduled`");
- legacy provisional rows outside every caller's range; half-days settle at 16:30 (2.10);
- structure confirmations: watch = daily-bar structure, rule = chart-interval signals (no owner);
- momentum confirmations: COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD;
- `primary.model: null`: the rule passes the primary, the watch fails it (round 2 finding 14).

## 5. Questions for Kenneth

All answered (2026-09-28): Q-B adopted (2.2), Q-C (b) widen (2.10), Q-D comment-only fix allowed,
Q-E accept + document the 1D/1W lag, Q-F never store an unsettled row, Q-G correct the three
out-of-scope descriptions of get_bars, Q-H keep `get_bars`' fetch rule (accept D-1 after the close
until nightly ingestion), Q-I no legacy watch-direction fallback. `_SETTLE = 30 min` is a plan
choice, not a decision.

**Follow-ups to log at build (open questions in PROJECT_STATE):** (a) fetch day D once it has
settled (Q-H); (b) pass the watch's direction to `evaluate_scheduled` (Q-I).

## 6. Round 3 disposition (16 findings)

1 -> Q-E, documented + test 5; 2 -> `_utcnow`/`_host_today`; 3 -> test 19 under a non-UTC TZ;
4, 5 -> 2.10 caller list; 6 -> removed at the source by Q-F; 7 -> heal success + retry bound;
8 -> yfinance claim corrected, `+1` independent of Alpaca's inclusivity; 9, 10 -> `omm_direction`
+ lazy OMM inside the try; 11 -> conftest memo reset + two files patched; 12 -> exact formula;
13 -> memo keyed by settle boundary; 14 -> per-`(symbol, interval, as_of)` bound; 15 -> nominal
span; 16 -> Q-G edits, 2.2 sentence, 2.10 probe. None rejected.
