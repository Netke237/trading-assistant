# NO-LIVE-QUOTE — plan r3 (PLAN STAGE CLEAN 2026-10-05: round 3 returned 0 gate findings; Kenneth answered Q-A to Q-D on 2026-10-09, all as recommended; build in progress)

- **Phase:** `NO-LIVE-QUOTE` (PROJECT_STATE.json). Status `not_started`: nothing built.
- **Origin:** split out of `CONTRACT-LIQUIDITY-DTE` on 2026-09-30 (decision `CONTRACT-LIQUIDITY-DTE-SPLIT-2026-09-30`).
  It was fix 3 of that plan and produced every high finding there. Its input had never been observed.
- **Kenneth's standing decision** (`CONTRACT-LIQUIDITY-DTE-ANSWERS-2026-09-30`, Q3): a chain row with no live
  two-sided quote is hard-rejected in the scan and in auto-trade; Step 6 and the Watchlist only label it.
  The reason key is `no_live_quote`.
- **Merge hold:** `CONTRACT-LIQUIDITY-DTE` has a closed plan (no code yet) and is held from main until this phase lands
  (`CONTRACT-LIQUIDITY-DTE-MERGE-HOLD-2026-09-30`). §1 changes the premise of that hold; see Q-D in §5.
- **r0 → r1:** r0 was a draft written before Step 0 and was never audited. r1 replaces sections 3a–3g
  against the measurements in §1 and disposes of r0's 19 open round-2 findings in §4.

## 1. Step 0 — what Tradier actually returns (measured 2026-10-03 to 2026-10-05)

`backend/scripts/tradier_chain_raw_sample.py` called Tradier `GET /v1/markets/options/chains?greeks=true`
directly on the **production** base. It recorded every row, including those the app drops. Seven names (AAPL MSFT
XOM LYB SRE CPRT TSCO), one or two expiries each. The raw rows are committed under
`backend/scripts/out/tradier_chain_raw/` (force-added; the folder is gitignored).

| Sample (ET) | Tradier clock | Rows | `ask == 0` | `bid == 0` | Two-sided | Two-sided bid/ask age, median | Both sizes > 0 |
|---|---|---|---|---|---|---|---|
| Sat 10-03 17:01 (weekend) | closed | 980 | **0** | 249 | 731 (75%) | 25.0 h | 731 / 731 |
| Mon 10-05 02:02 (overnight) | closed | 972 | **0** | 224 | 748 (77%) | 2.4 d | 748 / 748 |
| Mon 10-05 08:30 (pre-market) | premarket | 972 | **0** | 224 | 748 (77%) | 30.0 min | **0 / 748** |
| Mon 10-05 12:00 (in session) | open | 972 | **0** | 231 | 741 (76%) | **4 s** | 741 / 741 |
| Mon 10-05 16:45 (after close) | postmarket | 972 | **0** | 235 | 737 (76%) | 45.0 min | 737 / 737 |

What the samples establish:

1. **The off-hours shape in the code comment never occurred.** That comment is "Outside market hours Tradier
   returns bid=0, ask=0" (`market.py:867` and `:1595`). No sample had a single `ask == 0` row (4,868 rows). The
   fabricated-zero-spread branch (`spread = 0.0`, `market.py:873` and `:1601`) was never taken.
2. **Off-hours rows carry the last close's quotes, two-sided and non-zero.** Weekend and overnight rows show
   Friday's 16:00 quotes, with non-zero sizes and Friday's volume. After the close, rows show the 16:00 quotes
   (latest stamp 16:00:06 ET) with non-zero sizes. So `bid > 0 and ask > 0` cannot tell stale from live.
3. **Tradier rolls the day at 08:00 ET without new prices.** Between overnight and pre-market:
   - every `bid_date`/`ask_date` was re-stamped to 08:00:00–08:00:03 ET;
   - volume went to 0, `close` to null, and bid and ask sizes to 0 on all rows;
   - bid/ask/last prices were unchanged on 972 of 972 rows.
   So a pre-market Friday quote reads 30 minutes old.
4. **In session, live quotes are seconds old, but one side can sit still for a long time.** Of 741 two-sided
   rows, 737 had prices different from pre-market.
   - The older side, `max(age(bid_date), age(ask_date))`, was over 15 minutes on **24** rows. These are quiet
     far-OTM strikes whose other side was seconds old.
   - The fresher side, `min(...)`, was over 15 minutes on 2 rows and never over 27.3 minutes.
5. **`bid == 0 and ask > 0` is about a quarter of every sample, in session too.** These rows are far OTM
   (|delta| ≤ 0.008 at p90). It is not an off-hours marker. Today these rows already hard-reject as
   `spread_too_wide`, because augment builds `bid = 0.01` and `spread_pct ≈ 2.0`.
6. **No single row field separates live from stale in all five windows.**
   - Quote age catches weekend and overnight.
   - Zero sizes catch 08:00–09:30.
   - Neither catches 16:00–16:15: the closing quotes are young and have sizes.
   - A wall-clock NYSE session test does separate them in all five, by construction.
7. **The host clock ran about 5 s behind Tradier.** Ages went down to −5.3 s, so an age rule needs skew
   tolerance.

**The r0 §3g verdict.** r0's pass condition was "off-hours rows show `bid == 0 or ask == 0`, in-session rows
two-sided with current dates". It **failed**. r0's pre-decided fallback was "stale when `max(bid_date,
ask_date)` is older than 15 minutes". It is wrong in three windows:
- it false-rejects 24 of 741 live rows (point 4);
- it calls Friday's quotes live from 08:00 to 08:15 (point 3);
- it calls the closing quotes live from 16:00 to 16:15 (point 2).

r1's rule (3a) is a session test plus a fresher-side age.

**What this means for the defect the phase was opened for.** The real off-hours risk is a stale but plausible
closing spread graded as live. That spread passes both spread rules exactly like a live one. A fabricated 0%
spread is unobserved, though the code path remains. Both are fixed below; the first is the one that occurs.

## 2. What is true on main (2026-10-05, after merging main at `bdf159ac`)

- **Chain builders.** `fetch_option_chain_async` (`market.py:1513`, the live one) and its sync twin
  `fetch_option_chain` (`:790`, no production caller) build each row like this:
  - `ask > 0`: `price = (bid+ask)/2`, `spread = ask − bid`;
  - else `last > 0`: `price = last`, `spread = 0.0`;
  - else the row is dropped.
  - A `bid == 0, ask > 0` row gets `price = ask/2`.
  - Rows carry no `bid`/`ask` keys (keys: `id symbol strike expiry right dte dteTotal price delta theta iv ivRank
    ivPercentile spread volume open_interest score`).
- **Quote fetch.** `fetch_contract_quote_async` (`:1721`) re-fetches the chain with `expiry=` and returns the
  first row whose strike matches. If `expiry` is not listed, the chain builder's fallback picks another expiry
  (`:1545`), and the row is returned anyway. `get_option_quote` (`contracts.py:360`) guards this with an expiry
  check (`:380`). The other consumers do not: `portfolio.py:95,430`, `position_writer.py:256`,
  `alerts.py:45`, `portfolio_alert_monitor.py:115`, `daily_risk_hooks.py:20`, `auto_trade_booking.py:412`.
- **Augment.** `augment.py:94-95` builds `bid = max(0.01, mid − spread/2)` and `ask = mid + spread/2`, and
  copies every chain key through (`**c`).
- **Grading.** `validate_contract` (`contract_validator.py:441`) has two callers:
  - the scan (`scan.py:899`), whose chain comes from `scan.py:797`;
  - Step 6 / the Watchlist refresh (`contracts.py:300`).
- **Auto-trade fire.** `AutoTrader.fire()` (`auto_trader.py:2541`) checks `_market_is_open(symbol)`
  (`:648`, a 3 s price probe that `fetch_price` answers around the clock) between two lock acquisitions. A
  refusal there raises `ArmPreservedError`: nothing consumed, nothing recorded (`:39-60`). The first lock
  captures only `strategy.symbol`. `option_symbol` is an unvalidated `str` (`routers/auto_trade.py:79`), and
  `to_occ` (`data/option_symbol.py:51`) raises `ValueError` on anything that is neither OCC nor pipe form.
- **Session test.** `strategy_watch_scheduler._market_open` is a weekday 09:30–16:00 ET wall-clock test, with
  16:00 inclusive and no holiday calendar. `services/market_session.py` re-exports it as
  `_market_session_open` (deliberately one definition). `market.py` cannot import it at module level:
  `strategy_watch_scheduler` imports `strategy_watch_evaluator`, which reaches the data layer.
- **Sandbox lag.** `intraday_feed_lag_seconds()` (`market.py:566`) returns 900 on the sandbox base, else 0.
- **Step 7 recompute.** `page.tsx:914` sends `spread: q?.spread ?? 0`: a failed live quote becomes a 0
  spread. `recompute_plan` (`contracts.py:449`) turns it into `bid = ask = premium`, and `assess_entry`
  (`entry_quality.py:62`) reads that as a perfect spread.
- **Vertical spreads (bearish).** `_build_spreads` (`scan.py:439`) passes raw chain rows to
  `spread_builder.build_bear_put/call`, which read `long["ask"]`/`short["bid"]`. Raw chain rows have no such
  keys, so every build raises `KeyError`, which is caught and logged at debug: the spread path never produces
  a spread today. **This plan must not add `bid`/`ask` keys to chain rows**, or it silently switches that
  unaudited path on (logged in §6).

## 3. Design

### 3a. Data: classify every chain row's quote

**New pure module `backend/app/data/quote_liveness.py`.** It has no app imports beyond the standard library:

```python
QuoteState = Literal["live", "one_sided", "session_closed", "stale"]

def classify_quote(bid: float, ask: float, bid_date_ms, ask_date_ms, *,
                   now_s: float, session_open: bool, feed_lag_s: float,
                   max_age_s: float) -> tuple[QuoteState, float | None]:
```

Rules, applied in this order; the first that matches wins:
1. `bid <= 0` → `one_sided`. A row with `ask <= 0` never reaches the classifier (see "Rows with no ask"
   below).
2. `not session_open` → `session_closed`.
3. Take `freshest = max(bid_date_ms, ask_date_ms)`, counting a stamp that is missing, non-numeric or `<= 0` as
   absent. If both are absent → `stale`, age `None`.
4. Compute `age_s = now_s − freshest/1000 − feed_lag_s`. If `age_s > max_age_s` → `stale`.
5. Otherwise → `live`.

The function returns `(state, age_s)`. A negative `age_s` (host clock behind Tradier, §1 point 7) is live, not
an error.

**Why each clause exists, from §1:**
- The session test covers weekend, overnight, pre-market and after-close. That includes 08:00–08:15 and
  16:00–16:15, which no row field catches.
- The fresher-side age covers what a wall clock cannot see:
  - holidays, where the session test says open but quotes are at least 17 h old;
  - early-close days after the close, where the residual window is `max_age_s` after 13:00;
  - a frozen feed.
- The fresher side, not the older one, because the older side false-rejected 24 of 741 live rows.
- Sizes are recorded in §1 but **not used**. With the session test in place they add no window, and they are
  an unmeasured false-reject risk on rows with a null size.

**Threshold.** A new config key in `contract_rules.yaml`:

```yaml
quote_liveness:
  max_age_minutes: 30
```

- It is registered in `config_health.CONTRACT_KEYS` (`config_health.py:185`). Otherwise the closed-key walk
  (`:634`) flags it on the health banner.
- It is read through `contract_validator._load_config`, the same cached loader the validator uses.
- A missing, non-numeric or ≤ 0 value falls back to 30 and logs a warning.
- **Why 30:** in session the fresher side was never older than 27.3 minutes (0 of 741 rows over 30). The
  margin is thin, so this value is Q-A in §5.

**Rows with no ask (`ask <= 0`) are dropped.** This replaces the `elif last > 0: … spread = 0.0` branch in
both builders, and removes the defect marker.
- Reasons: such a row has no executable price for a buyer (FR-24 "missing ask"), it was never observed in
  4,868 rows, and keeping it would need a `None` spread threaded through every reader (r0 findings 2, 7
  and 8).
- Consequence: a held contract whose ask is 0 gets `fetch_contract_quote_async → None`. Its consumers (§2,
  quote fetch) already treat `None` as "quote unavailable". The build verifies each one (§3g, test T5).
  This is Q-C in §5.

**Every row both builders emit gains three keys, and never `bid`/`ask`:**
- `quoteState`: one of the four states;
- `quoteLive`: `quoteState == "live"`;
- `quoteAgeS`: the fresher-side age, or `None`.

How the builders compute them:
- `now_s` and `session_open` are taken **once per chain fetch**: `time.time()`, and
  `_market_session_open(datetime.now(MARKET_TZ))` via a call-time import of
  `app.services.market_session`. One fetch therefore cannot straddle 16:00 row by row.
- `feed_lag_s = intraday_feed_lag_seconds()`. On the sandbox every quote is at least 15 minutes old, and
  without this every sandbox row would read stale (r0 finding 19).
- `price` and `spread` are unchanged for every kept row, including `bid == 0` rows (`price = ask/2`). r0
  finding 12 is answered in §4.
- The sync twin is changed identically, so the two builders cannot drift. A test pins both.

**`fetch_contract_quote_async`** returns the matched row only when `row["expiry"] == expiry` (r0 finding 5).
The strike is still matched, and the right is fixed by the `option_type` it fetched. Otherwise it returns
`None`. This moves `contracts.py:380`'s guard into the shared function, so every consumer in §2 is protected.
`contracts.py:380` stays as a harmless second check.

**`augment`** needs no change: `**c` carries the three keys.

### 3b. Grading

`validate_contract(contract, stock_score, overrides=None, *, quote_mode: Literal["reject", "label"] = "reject")`

- **When the rule fires.** Only when `contract.get("quoteLive") is False`. A missing key reads as live, so
  fixtures and hand-built dicts keep working. A test pins that both builders always set the key.
- **`"reject"` (the default, so any new caller is safe).** If the row is not live, `reject_reasons ==
  ["no_live_quote"]`, and the other hard rules are **not evaluated** for that row (short-circuit, r0 finding
  20).
  - Status `REJECT`; `explanation.blockers` gets one entry: `code "no_live_quote"`, label
    `"No live quote"`, metric `"quote_state"`, observed `quoteState`.
  - The soft scores are still computed so the breakdown renders, but nothing reads them on a REJECT.
- **`"label"`.** The row is graded exactly as today on every axis, including the spread from its stale but
  real numbers, with three additions:
  - status is capped at `CAUTION`, so a non-live row can never read PASS;
  - `soft_flags` gains `"no_live_quote"`;
  - the card's new fields are set: `no_live_quote: bool = False` and `quote_state: str | None = None`.
  - A `one_sided` row still hard-rejects as `spread_too_wide`, exactly as today.
- **Recorded deviation.** The label path deviates from FR-24's "blocks recommendation" for display only. That
  deviation is Kenneth's Q3 decision. It is logged as a decision when this plan is clean.

### 3c. Callers and wire

- **The scan** (`scan.py:899`) keeps the default `"reject"`.
  - Its per-name reason becomes `contracts rejected: no_live_quote(N)` through the existing counter
    (`:902-928`), with no change there.
  - `ScanLog`'s `REASON_CATEGORY` gains `no_live_quote: 'DATA'`. The map gets exported so a test can read it
    (r0 finding 15).
- **Step 6 / the Watchlist refresh** (`contracts.py:300`) pass `quote_mode="label"`.
  - `OptionContract` (`schemas`) gains `noLiveQuote: bool = False` and `quoteState: str | None = None`, both
    filled from the card.
  - `spread` stays `float`, because 3a never makes it `None`.
- **The live quote** (`get_option_quote`, `contracts.py:360`): `ContractQuoteResponse` gains
  `quoteLive: bool | None = None` and `quoteState: str | None = None`, filled from the row. `None` means
  "row had no state", which only a fixture produces.
- **The scan's trade card** comes only from non-REJECT rows, so it was live **when the scan ran**. That says
  nothing about now: `scanResult` is persisted (`scanStore.ts` `partialize`), so Step 7 can show yesterday's
  card. `TradeCardData` gains `noLiveQuote: bool = False` to carry a Step 6 pick's flag (3e). Step 7 never
  treats `false` as proof of a live quote (3e, round 1 F2).
- **The bearish spread path** (`scan.py:457-460`) is untouched. It is dead today (§2), and 3a adds no `bid`/`ask`
  keys, so it stays dead. A test pins that chain rows carry no `bid`/`ask` keys.

### 3d. Auto-trade fire gate

**New in `auto_trader.py`, next to `_market_is_open`:**

```python
def _option_quote_state(option_symbol: str) -> str:
```

It returns a `QuoteState`, `"invalid_symbol"` or `"unavailable"`, in this order:
1. `occ = to_occ(option_symbol)`. A `ValueError` → `"invalid_symbol"`. This is r0 finding 10: an armed symbol
   that is neither pipe nor OCC form is refused rather than treated as "a stock strategy". No such thing
   exists, because `execute_option_order` hardcodes `sec_type="OPT"` (`:2457`).
2. `_market_session_open(datetime.now(MARKET_TZ))` is False → `"session_closed"`, with **no network call**.
3. **One** direct Tradier `GET /v1/markets/options/chains`, for the OCC symbol's underlying and expiry, with
   `greeks=false`. It goes through `get_tradier_creds()` / `_headers()`, with no IBKR/tastytrade/yfinance
   enrichment (r0 finding 4). It runs in the same worker-thread pattern as `_market_is_open`: an httpx
   timeout of 2.5 s inside a 3.0 s `future.result` deadline, then `shutdown(wait=False)`, and never under the
   lock.
4. Find the row whose `symbol == occ`. That is an exact match on root, expiry, right and strike, so r0 finding
   5 cannot recur. No row, a non-2xx response, a timeout or any exception → `"unavailable"`.
5. Drop a row with `ask <= 0` → `"one_sided"`. Otherwise
   `classify_quote(bid, ask, bid_date, ask_date, now_s=time.time(), session_open=True, feed_lag_s=intraday_feed_lag_seconds(), max_age_s=<config>)[0]`.
   That is the same classifier and the same fields measured in §1.

**Where it sits in `fire()`.**
- The first lock acquisition captures `_option_symbol = self._state.strategy.option_symbol` beside
  `_symbol`.
- Right after the `_market_is_open` check, still before the disarm:

```python
_qs = _option_quote_state(_option_symbol)
if _qs != "live":
    raise ArmPreservedError(f"No live option quote for {_option_symbol} ({_qs}) "
                            f"— armed state preserved for retry")
```

- In the second lock acquisition, next to the existing `expect` identity check: if
  `self._state.strategy.option_symbol != _option_symbol`, raise `ArmPreservedError` too. This closes the
  window in which a manual re-arm with another contract would fire on the first contract's probe. Without
  `expect`, the existing code has that window for `symbol` today.
- **Pre-disarm reading, stated (r0 finding 3).** The refusal is armed and silent, exactly like
  `_market_is_open`.
  - Nothing is consumed and no history row is written. `maybe_fire_on_scan` does not alert on
    `ArmPreservedError` (`:39-60`).
  - The next trigger retries. One `logger.warning` line per refusal names the contract and the state.
  - r0's "consumed with a named history reason" is withdrawn.
- `_market_is_open` stays, unchanged and first. It is the existing halt check on the underlying.

**Tests that patch `_market_is_open` (r0 finding 11).** Sixteen files do, as listed by `grep -l _market_is_open tests`:
- `test_a4_intraday_regime_bars`, `test_a4b_completed_intraday_bars`, `test_account_value`,
  `test_arm_entry_premium_required`, `test_auto_trader`, `test_auto_trader_event_veto`;
- `test_autotrade_a6_a7`, `test_autotrade_a9`, `test_autotrade_scan_reject_log`,
  `test_daily_risk_integration`, `test_docc1_money_blocks`, `test_docc2_regime_block`;
- `test_o4_step4_booking`, `test_p3c_fire_off_loop`, `test_phase_g_arm_pick`,
  `test_premium_stop_per_position`.

They get an **autouse fixture in `tests/conftest.py`** that patches `app.services.auto_trader._option_quote_state` to return
`"live"`, unless the test carries `@pytest.mark.real_quote_gate`. The gate's own tests carry the marker. The
build adds the marker to `pytest.ini`/`pyproject` markers, so an unknown-marker warning cannot hide a typo.

### 3e. Frontend

- **Step 6** (`step-6-contracts/page.tsx`) and **the Watchlist Contracts tab** (`watchlist/page.tsx`):
  - a "no live quote" tag on rows with `noLiveQuote`, with the tooltip naming `quoteState` ("market closed",
    "quote N min old", "no bid").
  - The Watchlist table has no SPREAD column (r0 finding 13), and none is added. The tag sits in the existing
    status cell.
- **Step 6 "A — Recommended"** (`page.tsx:350`) is the highest-score row that is neither rescued nor
  `noLiveQuote`. If **every** row is non-live (any off-hours visit), it falls back to the highest-score row,
  tagged. Off-hours Step 6 thus still shows a labelled recommendation, which is Q3's "label, don't block".
- **`applyPickedContract`** (`lib/tradeCardOverride.ts:52`) copies `noLiveQuote` onto the card. A scan card
  defaults to false.
- **Step 7: a contract counts as live only when this visit proved it** (r0 finding 9; round 1 F1 and F2).
  - **Confirmed live** means that Step 7's live quote for **that exact contract** arrived during this visit,
    with `quoteLive === true`. Nothing else counts:
    - a failed or timed-out quote (`q == null`) does not;
    - the scan card's `noLiveQuote: false` does not, because the card may be a persisted scan from yesterday;
    - basket items other than the active card, which never fetch a live quote (`page.tsx:959-961`), do not.
  - **Not confirmed live → the warning shows.** It is worded by what is known, for example:
    - "No live quote (market closed) — the entry premium is the last close's mid, not a live price";
    - "Live quote unavailable — the entry premium is the scan-time mid".
  - **The decision is made at send time, not render time** (round 2 G2).
    - The quote fetched when the card opened only drives the on-screen warning. It is fetched once per
      `[contractKey, isOverride, recomputeTick]` (`page.tsx:955`) and never re-fetched, so a 15:50 quote
      would otherwise still count at 17:30.
    - The order gate is a **fresh** `getContractQuote` for the exact contract, made at the top of
      `placeDirectOrder` (`:1113`) before anything is saved or sent. It reuses the 8 s budget of the
      existing quote call.
    - The contract counts as confirmed live only if that fresh quote returns `quoteLive === true`.
    - A failure, timeout, 404 or `quoteLive !== true` means not live.
    - The backend decides liveness from its own clock and session test (3a), so no client clock is trusted.
  - **Not live at send time → a confirm tick keyed to the contract** (round 2 G1).
    - The tick is stored as `{ contractKey }`. It counts only when that key equals the current card's
      `contractKey`, and it is cleared whenever `contractKey` changes, including Prev/Next
      (`:1328-1329`) and the `[active]` effect (`:667`).
    - If the fresh quote is not live and no matching tick exists, `placeDirectOrder` sends nothing. It shows
      the warning, worded from the fresh result, and leaves the tick box to the user.
    - Once the user ticks for this contract and clicks again, the fresh quote is fetched again. If it is
      still not live, the order goes out with the tick on record.
  - **Paths covered** (round 1 F1, checked in round 2):
    - The only broker order on Step 7 is `api.postOptionOrder` inside `placeDirectOrder` (`:1215`), reached
      by "Place Limit @ $X" (`:1599`) and "Right Now — Market" (`:1615`). The gate above covers both.
    - The buttons stay enabled. Their gate is the send-time check, because a render-time disable would
      rest on the stale quote.
    - The basket dialog books positions but places no order: `handleSubmit` (`:1338`) only calls
      `addPosition`, and `SendToBrokerDialog.onSubmit` posts nothing. It gets the warning text for
      information only, with no tick.
    - Arming auto-trade needs no tick, because the fire gate (3d) re-checks the quote at fire time.
  - Q-B in §5 chooses between the tick (the default), warning only, and refuse. Whichever is chosen applies at
    the same send-time point in `placeDirectOrder`.
- **Step 7 recompute** (`page.tsx:914`, r0 finding 2):
  - `spread: q?.spread ?? <the pick's spread>`, never `?? 0`;
  - `RecomputePlanRequest` (`contracts.py`) gains `quote_live: bool | None = None`, sent as
    `q?.quoteLive ?? !card.noLiveQuote`;
  - `recompute_plan` passes it to `assess_entry`, which gains `quote_live: bool | None = None`. When it is
    `False`, the result is CAUTION with the reason "no live quote — entry priced off the last close".
  - `None` keeps today's behaviour for any other caller.
- **Types.** `OptionContract`, `TradeCardData` and `getContractQuote`'s return type gain the optional
  fields. `spread` stays `number` everywhere, because 3a never sends `null`. That retires r0 finding 8's
  `scoreDetailText.ts:109` / `statusTooltips.ts:322` crash path.
- **Mocks.** None to update: `frontend/__mocks__/` holds only `lightweight-charts.js` and `styleMock.js` (r0
  finding 14). Jest fixtures that build `OptionContract` literals get the field through its default.

### 3f. Consequences, stated

- **Off-hours options scan.** Every row is `session_closed`, so the scan returns no candidates. Each name's
  reason reads `contracts rejected: no_live_quote(N)`, and the funnel counts it under `failed_contracts`. No
  new funnel row.
- **Off-hours manual scan → auto-trade.** `run_scan` calls `maybe_fire_on_scan` only when a candidate is
  PASS (`scan.py:2199`), so an off-hours options scan cannot trigger a fire. An armed Step 7 card triggered by
  any later scan is refused at fire time by 3d's session clause. The same goes for `/auto-trade/fire` called
  by hand.
- **Holiday.** The session test says open, but quote age is at least 17 h. Every row is `stale`: scan
  rejects, fire refuses.
- **Early close (13:00 ET).** From 13:00 to 13:30 the closing quotes still read live. That is the residual
  window, equal to `max_age_minutes`. A fire in that window prices off a quote at most 30 minutes old, and the
  broker would reject or queue it after its own close.
- **Scheduled options scans** (`scan_schedule_scheduler.py:125-181`):
  - The scheduler never touches auto-trade, and r0 finding 6's premise was wrong.
  - An off-hours run records `success` with 0 candidates. Its success notice gains one clause when every
    rejected name's reason is `no_live_quote`: "ran outside market hours — no live option quotes".
    `ScanResult` gains `noLiveQuoteNames: int`, counted in `_execute_scan_core` from the per-name reasons,
    and the scheduler reads that field rather than parsing strings.
  - **Not done:** keeping the previous run as the delta base. An empty run as `previous_result` makes
    `_compute_deltas` return no deltas (`scan.py:209`), which loses deltas for one run but never shows a wrong
    one. That is below the gate and logged in §6.
- **In session.** `one_sided` rows (about 24%) change reason from `spread_too_wide` to `no_live_quote`. They
  were rejected before and still are. Quiet far-OTM rows over 30 minutes on the fresher side would newly
  reject; there were 0 in the sample.

### 3g. Verification: tests, replay and mutations

Test files (r0 finding 17: one named file each):

| ID | File | What it pins |
|---|---|---|
| T1 | `tests/test_quote_liveness.py` (new) | `classify_quote` truth table: rule order, absent/0/non-numeric stamps, negative age, feed lag, the `max_age_s` boundary, and a `session_open=False` row with 5-minute-old stamps (16:05) → `session_closed` |
| T2 | same file | **Replay of the five committed samples.** Fixtures are trimmed copies of the five `rows.csv` files under `tests/fixtures/tradier_chain_raw/`, with only the columns the classifier reads. Each row is classified at its sample's capture time, with the session flag from the capture's ET wall clock. Expected: weekend, overnight, pre-market and after-close give **0 live rows**; in session gives **741 live, 231 one_sided, 0 stale**, at 30 min |
| T3 | `tests/test_option_chain_expiry_selection.py` | Both builders: every row carries `quoteState`/`quoteLive`/`quoteAgeS`; no row carries `bid`/`ask`; `ask == 0` rows are dropped; `price`/`spread` unchanged for kept rows; session flag and `now` taken once per fetch; sandbox lag applied |
| T4 | `tests/test_contracts_expiry.py` | `fetch_contract_quote_async` returns `None` when the chain came back for another expiry |
| T5 | `tests/test_contracts_expiry.py` | Each §2 quote consumer, given `None`, takes its existing "unavailable" path: portfolio `/positions` and position_writer at least; the others by reading, listed in the build report |
| T6 | `tests/test_contract_validator.py` | `quote_mode` default is `"reject"` (one test relies on the default, r0 finding 18); reject short-circuits to exactly `["no_live_quote"]` with the blocker entry; label caps PASS → CAUTION, adds the flag, sets the card fields; missing key → live |
| T7 | `tests/test_contracts_scoring.py` | Step 6 endpoint passes `"label"`: a non-live row comes back CAUTION with `noLiveQuote: true`; `get_option_quote` returns `quoteLive`/`quoteState` |
| T8 | `tests/test_no_live_quote_fire_gate.py` (new, `real_quote_gate`) | `_option_quote_state` for each outcome (invalid symbol, session closed with no HTTP call, timeout, non-2xx, no row, `ask == 0`, stale, live); `fire()` raises `ArmPreservedError` before the disarm, the strategy stays armed, no history row is written; the re-arm-with-another-contract window refuses |
| T9 | `tests/test_entry_quality.py` | `assess_entry(..., quote_live=False)` → CAUTION with the reason; `None` unchanged; `recompute_plan` forwards `quote_live` |
| T10 | `tests/test_scan_schedule_entry.py` | An all-`no_live_quote` options run's notice carries the clause; `noLiveQuoteNames` counted |
| T11 | Jest: `step-7-trade-card` + `SendToBrokerDialog` + `ScanLog` | Confirmed-live rule: `quoteLive: true` → no warning; `quoteLive: false`, `q == null`, a persisted card with `noLiveQuote: false` and no quote, and a non-active basket item → warning. `placeDirectOrder` fetches a fresh quote and sends only when it is live or a tick for the **current** `contractKey` exists. Cases: a live quote at open followed by a not-live fresh quote at send (the clock passed 16:00) refuses without the tick; a tick for candidate A does not cover B after Next; the tick is cleared on a `contractKey` change; recompute sends the pick's spread when the quote failed; `REASON_CATEGORY.no_live_quote === 'DATA'` |

Mutations. The build runs each one and confirms it fails a test:

| M | Mutation | Must fail |
|---|---|---|
| M1 | Restore `elif last > 0: spread = 0.0` | T3 |
| M2 | Rule 3/4 on the older side (`min` of the stamps) | T2 (in session drops below 741 live) |
| M3 | Delete the session clause | T1 (the 16:05 case; T2 alone would not catch it, since the after-close sample's quotes are already 45 minutes old) |
| M4 | Default `quote_mode="label"` | T6 |
| M5 | Remove the short-circuit | T6 |
| M6 | Drop the label-mode CAUTION cap | T6, T7 |
| M7 | Remove the 3d call from `fire()` | T8 |
| M8 | Probe in the post-disarm region | T8 (strategy no longer armed) |
| M9 | Restore `spread: q?.spread ?? 0` | T11 |
| M12 | Treat `q == null` as live, or drop the tick check from `placeDirectOrder` | T11 |
| M13 | Gate on the open-time quote instead of the send-time fetch | T11 (the 16:00 case) |
| M14 | Tick not keyed to `contractKey` | T11 (A's tick covers B) |
| M10 | Drop `feed_lag_s` | T3 (sandbox case) |
| M11 | `fetch_contract_quote_async` without the expiry check | T4 |

**Live check after the build.** Kenneth runs `/api/contracts` for one name in session and once after the
close, then reads `noLiveQuote` on the rows. In session it should be false on two-sided rows; after the close,
true on all rows. The command is given in the build report. This is evidence only; the replay in T2 is the
gate.

## 4. r0's open round-2 findings: disposition

| # | Finding (short) | Disposition in r1 |
|---|---|---|
| 0 | After-close vol 1–49 + fabricated 0% spread reaches a broker order once `min_volume` → 0 | **Closed.** The fabricated spread is removed (3a). Any after-close row is `session_closed` → scan rejects (3b) and fire refuses (3d). Step 7 send: a send-time fresh quote in `placeDirectOrder`, and a per-contract confirm tick when it is not live (3e, Q-B). §1 shows the real after-close shape is stale non-zero quotes, also covered |
| 1 | Verification can't run through `/api/contracts` | **Done.** Step 0 measured the raw endpoint (§1); T2 replays it |
| 2 | Step 7 recompute sends 0% spread | **Fixed** in 3e. With `spread` never `None`, the `float(None)` 500 at `:388` cannot occur |
| 3 | 3d: armed-and-silent or consumed? | **Stated:** armed-and-silent, pre-disarm `ArmPreservedError` (3d) |
| 4 | 3 s probe over the enriched chain times out | **Fixed:** one raw Tradier chain GET, no enrichment, 2.5 s / 3.0 s budget (3d) |
| 5 | Probe can match another expiry | **Fixed:** exact OCC match in 3d; expiry check in `fetch_contract_quote_async` (3a) |
| 6 | Scheduled-scan rule wrong on four points | **Rewritten** (3f): no auto-trade claim; notice clause from structured `noLiveQuoteNames`; no new run status (the delta loss is below gate, §6); the in-session trigger problem is gone (needs *all* names `no_live_quote`) |
| 7 | `float(None)` crash sites | **Retired:** 3a never produces a `None` spread (rows with no ask are dropped) |
| 8 | Frontend turns null spread into 0 | **Retired** for the same reason; types stay `number` |
| 9 | Step 7 warning from a Step 6 snapshot | **Fixed:** live only when this visit's live quote proved it; everything else warns (3e) |
| 10 | 4-part test fails open for OCC; "stock strategies" don't exist | **Fixed:** `to_occ` validation → `invalid_symbol` refusal; claim dropped (3d) |
| 11 | ~15 test files patch `_market_is_open` | **Fixed:** 16 listed; autouse conftest fixture + `real_quote_gate` marker (3d) |
| 12 | `price` for `bid == 0, ask > 0` unspecified | **Specified: unchanged (`ask/2`).** Such rows are `one_sided`: rejected in the scan as before, tagged in Step 6 ("no bid"). Changing `price` would move held-position marks for no gain |
| 13 | Watchlist has no SPREAD column | **Accepted:** the tag goes in the status cell; no column added (3e) |
| 14 | `__mocks__/` holds no API mocks | **Accepted:** nothing to update there (3e) |
| 15 | ScanLog category mutation | **Fixed:** `REASON_CATEGORY` exported and tested directly (3c, T11) |
| 17 | Name one test file each | **Done** (3g table) |
| 18 | Mutation needs a default-reliant validator test | **Done** (T6, M4) |
| 19 | 15-min age marks every sandbox quote stale | **Fixed:** `feed_lag_s = intraday_feed_lag_seconds()` (3a), M10 |
| 20 | Hard-reject reasons accumulate | **Fixed:** short-circuit to `["no_live_quote"]` (3b), M5 |

**Carried item (parent plan).** CONTRACT-LIQUIDITY-DTE keeps the zero-volume exemption for an explicit
`min_volume` floor above 0. Revisiting it is out of scope here and logged in §6. §1 point 3 now confirms its
premise: volume resets to 0 at 08:00 ET, before any trade.

## 5. Questions for Kenneth

- **Q-A — threshold.** `max_age_minutes: 30`. In session the fresher side never exceeded 27.3 minutes (n=741),
  so 30 has a thin margin. 60 halves the false-reject risk on quiet strikes, and doubles the early-close
  residual window (13:00–14:00). **Recommendation: 30.**
- **Q-B — Step 7 direct send.** Q3 named the scan and auto-trade; it did not name Step 7's send, which the
  merge-hold question listed as a route. Option (a): warning plus a confirm tick before sending. Option (b):
  warning only. Option (c): refuse. Whichever is chosen applies at the one send point, `placeDirectOrder`, which
  serves both Place Limit and Market. The basket dialog places no order. **Recommendation: (a).**
- **Q-C — dropping rows with no ask.** Never observed. Dropping them removes the `None`-spread surface
  entirely, at the cost of a held contract with ask 0 showing "quote unavailable" rather than a last-trade mark.
  **Recommendation: drop.**
- **Q-D — the merge hold.** The hold's stated reason was "after-close rows with a fabricated 0% spread reach
  a broker order". That shape never occurred in five samples. The real after-close shape is a stale but
  plausible spread, and main grades that as live today, with or without CONTRACT-LIQUIDITY-DTE. Lifting the
  hold early would not make main worse than it is; keeping it costs only time. **Your call; no recommendation.**

**Answered by Kenneth, 2026-10-09 (decision `NO-LIVE-QUOTE-QA-QD-ANSWERS-2026-10-09`):** Q-A 30 minutes; Q-B (a) warning + confirm tick, decided on the send-time fresh quote; Q-C drop rows with no ask; Q-D keep the hold (this phase merges first).

## 6. Out of scope, logged

- **The bearish vertical-spread path is dead in production** (§2, `KeyError` on `long["ask"]`). That is a
  separate task: switching it on needs its own plan, with the quote gate applied per leg.
- **Scheduled options entries saved at off-hours times** will always come back empty. A save-time warning in
  the schedule UI is a separate task.
- **An empty off-hours scheduled run becomes the next run's delta base** (3f). A run status that skips it is a
  separate task, below the gate.
- **The zero-volume exemption** (carried item, §4) can become "only when the quote is not live" once
  `quoteLive` exists. That is a separate task after both phases land.
- **The holiday calendar.** The session test has none; quote age covers holidays (3f). A calendar would also
  close the early-close residual. Separate task.

- **Corroborating sample (Codex, 2026-10-08, branch `codex/tradier-quote-evidence-20261008` e312cc53, not merged):** two
  production SPY 2026-10-16 chains at 16:00:24 and 16:15:50 ET, 474 rows each, 0 rows with `ask == 0`. Replayed
  through NLQ-1's `classify_quote`: 0 live with the session clause. It also shows that **SPY (ETF) options keep
  quoting until 16:15 ET** (fresher-side age 52 s at 16:15:50), so 16:00-16:15 ETF/index-option quotes are live
  but read `session_closed` here. That errs toward refusing, never toward a stale quote reaching an order, and the
  screener universes are stocks. A product-hours calendar (with the holiday calendar above) is a separate task.
- **Tradier rate limit (Kenneth, 2026-10-09).** `governor.py`'s `tradier` bucket (120/min) is used by no Tradier
  call today. The fire gate's new call must use it (ticket NLQ-3); routing every Tradier call through it is
  ticket TG-1.

## 7. Bookkeeping when clean

- Log decisions: the 3b label deviation (Q3), and the Q-A to Q-D answers.
- PROJECT_STATE: the phase stays `not_started` until the build; this plan's audit rounds are recorded on the
  phase's `audit_rounds`.
- The defect marker (`spread = 0\.0` in `market.py`) disappears with 3a. Build step 1 is 3a, so `state.py` flags
  the status drift at the first build commit, and the phase status moves with it.
