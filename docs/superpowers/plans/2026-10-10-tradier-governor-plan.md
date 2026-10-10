# TRADIER-GOVERNOR — every Tradier call through the shared rate limiter (board #169)

**Phase id:** `TRADIER-GOVERNOR` · **Board item / tracking issue:** #169 · **Branch:** `board/tradier-governor-2b6fd1f9` (cut from `board/tradier-governor-889de9f2`; base origin/main e765cf4f + main merge 9e1c55f8)
**Source:** NO-LIVE-QUOTE ticket TG-1 (`.scratch/no-live-quote/issues/08-tradier-governor.md`), reconciliation ticket 13.
**Goal (Kenneth, 2026-10-09):** "use the rate limiter for tradier, we don't want my account blocked or flagged."
**Scan slowdown:** pre-accepted by Kenneth ("ok Go ahead", 2026-10-10); T4 still measures and records it.
**Revision r4 (second plan stage, decision `TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10`):** the overdraft design replaces r3's reserve/priority design (§4a).

## 1. What is true on main (e765cf4f)

- **`backend/app/data/governor.py`** builds a `tradier` provider (`TokenBucket(rate=120/60, capacity=15)`, `CircuitBreaker(fail=5, cooldown=60)`). It offers:
  - async `Governor.call()`, which acquires a token, retries on `RateLimited` with Retry-After or backoff, and records failures and the breaker;
  - non-blocking `Governor.try_acquire()`.

  There is **no blocking admission for sync callers**.
- **The only Tradier user of the governor** is `auto_trader._option_quote_state` (`auto_trader.py:705-735`, the NO-LIVE-QUOTE fire gate). It uses `try_acquire`, so with no token the probe returns "unavailable".
- **No Tradier code handles HTTP 429 or Retry-After.** A 429 today is just one more HTTP error at each call site, which then falls back or drops as it does for any error.
- **Every Tradier HTTP call site** (all use the token and base from `market.get_tradier_creds()` or `_tradier_base()`, i.e. live `api.tradier.com` or sandbox, unless noted):

| # | Site | Sync/async | Endpoint |
|---|---|---|---|
| A1–A11 | `market.py` `fetch_candles` :181, `fetch_intraday_candles` :411, `fetch_price` :667, `fetch_option_chain` :840 (expirations) and :874 (chains), `fetch_quotes` :1006, `fetch_earnings_date` :1038, `fetch_dividend_date` :1066, `fetch_company_name` :1094, `fetch_news` :1168, `_fundamentals_calendar_sync` :1991 | sync `httpx.get` | history, timesales, quotes, expirations, chains, calendars, company, news |
| B1–B6 | `market.py` `fetch_candles_async` :1482, `fetch_price_async` :1554, `fetch_option_chain_async` :1600 and :1634, `fetch_company_name_async` :1871, `fetch_fundamentals_calendar` :1906 | async `client.get`. The options scan passes its own `AsyncClient` in (`scan.py:1925`). | same |
| C | `routers/sectors.py:106` `_fetch_etf_change` | async | history |
| D | `services/daily_risk_hooks.py:27` `opening_price` | async | quotes (exact OSI). It authorises the daily-risk budget. |
| E | `data/tradier_stream.py:69` `_create_session`, and `:96` the streaming POST | async | events/session; one long-lived stream |
| F | `services/auto_trader.py:711` `_option_quote_state` | sync, in a worker thread with a 3 s deadline | chains. Already admitted by `try_acquire`. |
| G1 | `routers/data_sources.py:44` `_probe_tradier` | sync | markets/clock (live or sandbox per creds) |
| G2 | `routers/data_sources.py:64` `_probe_tradier_paper` | sync | **sandbox** clock, paper token |
| H | `data/tradier_paper.py:98` `TradierPaperAdapter` order POST | sync | **sandbox** orders, paper account |

How the sync callers run:
- **Worker threads:** most (`asyncio.to_thread` / `run_in_executor` in `stock_scan.py`, `scan.py:1787`, `alerts.py`, `news.py`, `portfolio_alert_monitor.py`, `regime_monitor.py`, the auto-trader's thread wrappers).
- **On the event loop (plan round 4, AST scan of every `async def` body for a direct call):** `services/strategy_watch_evaluator.py:616` `_eval_composite_watch` → `fetch_intraday_candles`, `services/regime_monitor.py:206` `_update_conviction_cache` → `fetch_candles`, `routers/candles.py:10` `get_candles` → `fetch_candles`, `routers/composite_watch.py:93` `get_regime_snapshot` → `fetch_intraday_candles`. Each `httpx.get` already blocks the loop for up to its HTTP timeout today. (`routers/regime.py:106` is a sync endpoint, which FastAPI runs in its threadpool.)

**Per-symbol cost of an options scan:**
- `fetch_option_chain_async` makes **one** chains call per symbol. Expirations are cached per symbol per day (`_expirations_cache`).
- Candles, quote, company and calendar calls are added where their caches miss.
- `_SCAN_CONCURRENCY = 5`.

## 2. Design (r4 — overdraft)

**The rule in one paragraph.** Bulk Tradier traffic (scans, prewarm, monitors, UI, probes) waits for a token as usual. The three deadline-bound **auto-trade fire-path** calls never wait and never fail on the limiter. They take a token if one is free; otherwise they go anyway and **book an overdraft**: the bucket goes negative, floored at `-capacity` (−15). While the bucket is negative, every bulk caller waits until the overdraft has been repaid by the normal refill. The refill rate is unchanged, so the long-run request rate stays at 120/min. The only extra is a one-off burst of at most `capacity` (15) requests, which Kenneth accepted (decision Q3).

The three fire-path calls are:
1. the regime bar fetch, both branches;
2. the earnings veto's Tradier source;
3. `_market_is_open`'s price probe.

**D1 — governor.py.**
- **`TokenBucket.overdraft(tokens=1.0) -> None`.** Under the lock: refill, then `self._tokens = max(self._tokens - tokens, -self.capacity)`. It never blocks and never fails. Normal `acquire`, `acquire_blocking` and `try_acquire` keep requiring `self._tokens >= tokens`, so they wait while the bucket is negative; that is the repayment. `_refill` already caps at `capacity` and adds `elapsed * rate/per` to whatever the balance is, negative included.
- **`TokenBucket.acquire_blocking(tokens=1.0, *, admit_timeout: float | None) -> bool`.** It sleeps the thread (`time.sleep`, the same refill arithmetic as `acquire`) until a token is free, or until `admit_timeout` (seconds, a plain `float`) elapses, and returns whether it got one. `admit_timeout=None` waits without a limit, as the async `acquire` already does.
- **`Governor.admit_sync(provider, *, admit_timeout: float | None, overdraft: bool = False) -> bool`:**
  - unknown provider or open circuit: False at once;
  - `overdraft=True`: if a 429 cooldown is active (`retry_at > now`), **False at once**, without waiting (see D3, "429"); otherwise `bucket.overdraft()` and True;
  - otherwise: wait out any `retry_at` cooldown, then `acquire_blocking`, all within `admit_timeout` (no limit when `None`). False on timeout, True when admitted.
- `admit_timeout` is **always a float admission budget (or `None`), never the HTTP timeout**. A11's HTTP timeout is `httpx.Timeout(4.0, connect=2.0)`, and `time.monotonic() + httpx.Timeout(...)` raises `TypeError`. The two are separate arguments everywhere.
- **`Governor.note_rate_limited(provider, retry_after: float | None)`:** `retry_at = max(retry_at, now + (retry_after or backoff_delay(0)))` and `status = "degraded"`. `Governor.call`'s existing `RateLimited` branch calls it, so sync and async share one cooldown.
- **No reserve, no priority parameter.** r3's `reserve` / `priority` rule is removed entirely.

**D2 — no new circuit breaking for Tradier.**
- Today no Tradier call opens a circuit. The breaker would make every Tradier call fail fast for 60 s after 5 consecutive failures, so a short outage would drop scan symbols for a whole minute instead of call by call.
- The `tradier` provider is therefore built with a fail threshold that never trips (`fail=10**9`, commented). Pacing, the overdraft and the 429 cooldown are the whole change.
- `try_acquire` (site F) keeps working: it simply sees fewer tokens while an overdraft is being repaid. F is fail-closed: "unavailable" refuses the fire, and changes no number.

**D3 — helpers in market.py, used by every market-data site.**
- **Fire-path marker.** A module-level `ContextVar` `_TRADIER_FIRE_PATH` (default False), set by the context manager `market.tradier_fire_path()`, and a helper `market.run_on_fire_path(fn, *args)` that runs `fn(*args)` inside `with tradier_fire_path():`. The ContextVar is the only way a fire-path call is recognised: the fetch functions keep their signatures.
- **Prepaid marker.** A `ContextVar` `_TRADIER_PREPAID` (default 0), and `market.tradier_prepay(admit_timeout: float) -> bool`:
  - it calls `admit_sync("tradier", admit_timeout=admit_timeout)` (a normal, waiting admission);
  - on success it sets `_TRADIER_PREPAID` to 1 in the **current** context and returns True; otherwise it returns False.
- **`_tradier_get(url, *, params=None, headers=None, timeout, admit_timeout: float | None = None)`**, the sync helper. Admission, in order:
  1. If `_TRADIER_PREPAID.get() > 0`: decrement it, no further admission (the token was taken before the deadline started).
  2. Else if `_TRADIER_FIRE_PATH.get()`: `admit_sync("tradier", admit_timeout=0.0, overdraft=True)`.
  3. Else if this thread is running an event loop (`asyncio.get_running_loop()` succeeds): **safety net**. Admit by overdraft as in 2, so the loop is never blocked waiting and the call never falls back for lack of a slot, and log one WARNING per call site naming it (T3 moves every known such caller off the loop, so this is only a net).
  4. Else: `admit_sync("tradier", admit_timeout=admit_timeout)`. For every bulk A-site call this is `None`: **a bulk call waits for its slot without limit and is never turned into a fallback because it waited** (plan round 4 R4-G1). A refusal-driven fallback would also populate `fetch_candles`' day cache (`market.py:224`) with yfinance bars, which a later fire would read as a cache hit.

  Then:
  - **Not admitted:** raise `ProviderUnavailable("tradier rate limiter: no admission")`, and the A-site takes its existing failure path. After R4-G1 this happens **only** in two cases: (a) a fire-path call during an active 429 cooldown (D1), which is the same outcome as today's 429 response; (b) a caller that passes a finite `admit_timeout` on purpose, which in this plan is only G1's probe (D4) and the earnings prepay (below).
  - **The request:** `httpx.get(url, params=..., headers=..., timeout=timeout)`, with `timeout` the site's **existing HTTP timeout passed through unchanged** (an int, or A11's `httpx.Timeout`).
  - **On 429:** `note_rate_limited("tradier", <Retry-After seconds if numeric>)`, and the response is returned unchanged, so the call site's own `raise_for_status()` or status check behaves exactly as today. On a transport exception: `record_failure` and re-raise (no breaker trip, per D2). Otherwise: `record_success`. There is no sync retry.
- **Where the marker is set (auto_trader.py only).** Each submits a wrapper rather than the bare function, so the `with` runs **inside the worker thread**: `ThreadPoolExecutor.submit` does not copy context.
  - `_market_is_open`: `ex.submit(market.run_on_fire_path, fetch_price, symbol)`.
  - `_measure_trade_regime`: `ex.submit(market.run_on_fire_path, _fetch_bars, strategy.symbol)`. This covers both branches: daily `_fetch_scan_window_bars` → A1 and Intraday `_fetch_intraday_regime_bars` → A2 (plan round 2 R2-G1).
  - `_apply_event_veto`: `with market.tradier_fire_path(): earnings = _fetch_earnings_date(strategy.symbol)`.

    `_call_source_with_deadline` submits `contextvars.copy_context().run` with `fn, symbol`, so both markers set in the calling thread reach the source's worker thread. This is a single change: `ex.submit(contextvars.copy_context().run, fn, symbol)`. A copied context is a snapshot: the worker's decrement of `_TRADIER_PREPAID` stays in the worker.
- **The stock scan's earnings lookup waits before its clock starts (R3-G1).** In `_lookup_earnings_date`, immediately before calling the **Tradier** source, and only when `_TRADIER_FIRE_PATH` is not set:
  - call `market.tradier_prepay(admit_timeout=30.0)` **outside** `_call_source_with_deadline`, so the wait does not count against `_TRADIER_LOOKUP_DEADLINE_S = 5.0`;
  - if it returns False (only during a 429 cooldown longer than 30 s), record that source as `"error"` with the reason "rate limiter: no admission" and continue to yfinance. That is the same path as any Tradier failure today, and there is no immediate retry (D5);
  - when it returns True, the copied context carries `_TRADIER_PREPAID = 1` into the worker, where `_tradier_get` consumes it;
  - if the Tradier source answers from its same-day cache without an HTTP call, the prepaid token goes unused. The cost is one bulk slot, and no number changes.

  The prepay applies to every non-fire caller of `_lookup_earnings_date`, which today is the stock scan's `_earnings_days_for` via `asyncio.to_thread`. The fire path skips it and uses the overdraft. Stock-scan lookups are therefore **normal** admissions and no longer compete with the fire path. r3 made them priority, which was R3-G1.
- **429 on the fire path.** During an active 429 cooldown, a fire-path call is refused at once (D1). It does not wait and it does not send. The call site then takes its existing failure path:
  - regime: yfinance or `RegimeDataUnavailableError`, exactly as when Tradier returns 429 today;
  - earnings: yfinance, then "unknown" → the existing D4 veto rule;
  - price probe: `fetch_price`'s own fallback (cached close, then yfinance) answers, exactly as on today's 429. Note that this usually reads "open", not "closed".

  Today the same moment sends a request that Tradier answers with 429, followed by the same path. So the outcome equals today's 429 behaviour, without sending a request Tradier told us not to send.
- **Every other A-site call** (not on the fire path, not prepaid, not on the loop) uses a normal admission with `admit_timeout=None`: it waits as long as the queue needs. The async B-sites already wait without limit through `Governor.call`.
- **Site F joins the fire path (plan round 4).** `_option_quote_state` is the NO-LIVE-QUOTE fire gate. Its `governor.try_acquire("tradier")` becomes `governor.admit_sync("tradier", admit_timeout=0.0, overdraft=True)`. Today nothing else uses the bucket, so `try_acquire` always succeeds. Once bulk traffic drains the bucket it would refuse, and armed orders would stop firing after large scans. With the overdraft, F behaves exactly as today. During a 429 cooldown it returns `"unavailable"`, the same as today's 429.
- **`_tradier_get_async(client, url, *, params=None, headers=None, timeout=httpx.USE_CLIENT_DEFAULT, retries=2)`**, the async helper:
  - **The timeout default is `httpx.USE_CLIENT_DEFAULT`, never `None` (plan round 1 G2).** An explicit `timeout=None` means no timeout at all in httpx. B1–B6, C and D pass no per-call timeout today, so they keep exactly their client's default.
  - It runs `await get_governor().call("tradier", factory, retries=retries)`. The `factory` does `await client.get(...)` and raises `RateLimited(retry_after=...)` on 429, so `call` waits out Retry-After and retries.
  - Any other response is returned for the call site to check, as today. If the 429 retries run out, `RateLimited` propagates, and each B-site's existing `except` handles it as a failed fetch.
  - **One async caller is on the fire path:** D, the daily-risk `opening_price` (`hooks.reserve` before `execute_option_order` for MKT arms, `auto_trader.py:2990`). It has no deadline and no fallback, so waiting for its token only delays the reservation and the order; it changes no number. It keeps a normal admission. The booking's quote fetch happens after the order is sent.
- **A1–A11 and B1–B6 call the helpers** instead of `httpx.get` / `client.get`, with the same URL, params, headers and HTTP timeout (an A-site's passed through verbatim; a B-site that passes none passes none). No other logic changes in those functions.

**D4 — the other sites.**
- **C (sectors) and D (daily_risk_hooks):** `_tradier_get_async(client, ...)`. D uses `retries=0`, meaning only that a 429 is not retried: `Governor.call` still waits for a token, and through any `retry_at`, without limit before the single attempt. D's existing `raise_for_status` / `DailyRiskError` path is unchanged.
- **E:** `_create_session` is admitted through the async helper (a `method="POST"` argument). The long-lived stream POST is one connection, not a request rate, and stays as is.
- **F:** overdraft admission, as described in D3.
- **G1:** goes through `_tradier_get` with `timeout=_PROBE_TIMEOUT` and `admit_timeout=float(_PROBE_TIMEOUT)` (or 2.0 if `_PROBE_TIMEOUT` is not a number). If not admitted, it returns `("degraded", "Tradier rate-limit budget busy; probe skipped")` without calling Tradier.
- **G2 and H** use the paper sandbox account and token, which Tradier rate-limits separately from the live account. They get a provider `tradier_paper` (`rate=60/60, capacity=5`, the same no-trip breaker, no overdraft use).
  - G2 and H call `admit_sync("tradier_paper", admit_timeout=<a float equal to their numeric HTTP timeout>)` before their request.
  - If H is not admitted, it raises the adapter's existing order-failure error **before** anything is sent. An order is never sent without admission and never sent twice.

**D5 — what does not change.**
- **Unchanged:** the `tradier` rate (120/min) and capacity (15), caches, fallbacks (yfinance, IBKR), scan concurrency, every HTTP timeout and deadline (`_TRADIER_LOOKUP_DEADLINE_S`, `_REGIME_FETCH_DEADLINE_S`, the 3 s market-open probe), every call site's error handling, the earnings lookup's retry rule, all response parsing and all numbers.
- **Changed:** only *when* requests are sent. Bulk requests wait for their slot without limit; they are never refused for waiting, so they never take a fallback they would not take today. Fire-path requests are never delayed by bulk traffic. The four on-loop callers (§1) now run their fetch in a worker thread (T3), which moves the same call off the loop and changes no value.
- **Exceptions, each with today's outcome:** fire-path calls during a 429 cooldown, G1's probe skip, and an earnings prepay refused after 30 s (only during a cooldown that long). Each takes the path today's 429 or failure takes.

## 3. Tickets

### T1 — governor: overdraft, sync admission, shared 429 cooldown (blocks T2, T3)
**Files:** `backend/app/data/governor.py`, new `backend/tests/test_governor_sync_admission.py`.
- Add `TokenBucket.overdraft` and `TokenBucket.acquire_blocking`, `Governor.admit_sync` (with `overdraft`) and `Governor.note_rate_limited`, and wire `Governor.call`'s `RateLimited` branch to `note_rate_limited`.
- `fail=10**9` for `tradier`; add the `tradier_paper` provider.
- **Tests** (fake clock or tiny real waits, under 1 s total):
  - `acquire_blocking` admits up to capacity, then waits about 1/rate, and returns False when a finite `admit_timeout` elapses first; with `admit_timeout=None`, eight contending threads on a saturated bucket are **all** eventually admitted, and none is refused;
  - `overdraft` takes the bucket negative and never below `-capacity`, and never blocks;
  - a normal `acquire_blocking` / `try_acquire` / async `acquire` issued while the bucket is negative waits (or is refused, for `try_acquire`) until the refill brings it back to ≥ 1;
  - over a long mixed run (bulk callers saturating the bucket plus periodic overdraft calls), the total admitted count is at most `capacity + capacity + rate × elapsed`: the normal burst, plus at most `capacity` overdraft, plus the refill;
  - `admit_sync(..., overdraft=True)` returns False at once during an active `retry_at`, without sleeping;
  - `admit_sync` honours a `retry_at` cooldown set by `note_rate_limited`, and refuses on an open circuit;
  - an async `call` that hits `RateLimited(retry_after=x)` sets the same cooldown that `admit_sync` then waits out;
  - the existing governor tests still pass.

### T2 — market.py helpers, markers and the 17 market-data sites (blocked by T1)
**Files:** `backend/app/data/market.py`, new `backend/tests/test_tradier_governor_market.py`.
- Add `_tradier_get`, `_tradier_get_async`, `_TRADIER_FIRE_PATH`, `tradier_fire_path()`, `run_on_fire_path()`, `_TRADIER_PREPAID` and `tradier_prepay()` (D3), and switch A1–A11 and B1–B6 to the helpers.
- **Tests:** a fake or real governor (via monkeypatch of `get_governor`), `httpx.MockTransport` for async, and a monkeypatched `httpx.get` for sync. Check `pip show respx` first and use it if installed.
  - Every A and B function makes its Tradier request only after exactly one admission on `tradier`.
  - A 429 with `Retry-After: 2` sets the cooldown, and the call site's result is the same as for any other HTTP error today.
  - Not admitted gives the same fallback or empty result as a transport error today. Assert each function's documented fallback value.
  - Async 429 then 200 gives one retry and the 200's parsed result.
  - **Timeouts pass through (G2):** each B-site request carries its client's timeout in `request.extensions["timeout"]`. Each A-site's `httpx.get` receives exactly its existing HTTP timeout; A11's is the `httpx.Timeout(4.0, connect=2.0)` object.
  - **Markers:**
    - inside `tradier_fire_path()`, an A-call on an **empty** real bucket (drained by normal acquisitions) is admitted at once by overdraft and the request is sent;
    - outside it, the same call waits up to its `admit_timeout`;
    - with `_TRADIER_PREPAID = 1`, the call makes no admission and decrements the marker;
    - both markers reset on context exit, including on exception;
    - `run_on_fire_path` sets the marker inside a worker thread submitted via `ThreadPoolExecutor.submit`;
    - called from inside a running event loop (a test coroutine calling `_tradier_get` directly), the call is admitted by overdraft at once on a saturated bucket, and the WARNING is logged.
  - **No fallback for waiting (R4-G1):** with the real governor's bucket held at 0 by eight contending bulk threads, `fetch_candles(X, 400)` and `fetch_intraday_candles(X, "15min", 55)`, called as bulk, both return the mocked **Tradier** bars. The yfinance mock is never called, and `_candles_cache[X]` holds Tradier's bars, never yfinance's.
  - Finite parsing is unchanged: the same fixture response gives the same output for each function before and after. Pin with existing fixtures where present.

### T3 — auto_trader markers, the remaining sites and the ratchet (blocked by T1, T2)
**Files:**
- `backend/app/services/auto_trader.py`, limited to:
  - the two `ex.submit(...)` lines in `_market_is_open` and `_measure_trade_regime`;
  - the `with market.tradier_fire_path():` around `_fetch_earnings_date` in `_apply_event_veto`;
  - `contextvars.copy_context().run` in `_call_source_with_deadline`;
  - the prepay step in `_lookup_earnings_date`.
- `backend/app/services/auto_trader.py` also gets site F's one-line admission change (D3).
- The four on-loop callers move to `await asyncio.to_thread(...)` with the same arguments: `backend/app/services/strategy_watch_evaluator.py:616`, `backend/app/services/regime_monitor.py:206`, `backend/app/routers/candles.py:10`, `backend/app/routers/composite_watch.py:93`.
- `backend/app/routers/sectors.py`, `backend/app/services/daily_risk_hooks.py`, `backend/app/data/tradier_stream.py`, `backend/app/routers/data_sources.py`, `backend/app/data/tradier_paper.py`.
- New `backend/tests/test_tradier_governor_sites.py`.

Apply D3's marker placement and D4.

**Tests.** "Saturated bucket" below means the real governor's `tradier` bucket held at 0 by a background thread of normal acquisitions, which simulates an options or stock scan running.
- **Fire path under a saturated bucket (R3-G1):**
  - `_measure_trade_regime`, on both the daily-horizon branch (A1 history) and the Intraday branch (`timeframe: 15min`, A2 timesales), gets Tradier's bars (mock), not the yfinance fallback, within `_REGIME_FETCH_DEADLINE_S`;
  - `_apply_event_veto`'s lookup gets Tradier's date within 5 s;
  - `_market_is_open` returns True on a mocked Tradier price within 3 s;
  - each of these made its request by overdraft (spy on `admit_sync`).
- **Fire path during a 429 cooldown:** each of the three takes exactly its existing failure path (yfinance or refusal, unknown → veto, closed), without sending a Tradier request.
- **Stock scan earnings lookup with a saturated bucket:** the prepay waits for a token *before* the 5 s deadline starts, and the Tradier source then completes inside its deadline. With prepay returning False, the source is recorded as an error and yfinance is used, which is the existing path.
- **Repayment:** after an overdraft, a bulk call waits until the bucket is back to ≥ 1.
- **Site F under a saturated bucket:** `_option_quote_state` is admitted by overdraft and classifies the mocked quote as today. During a 429 cooldown it returns `"unavailable"`.
- **Off the loop:** an AST scan of `backend/app/**/*.py` finds no direct call inside an `async def` body to `fetch_candles`, `fetch_intraday_candles`, `fetch_price`, `fetch_option_chain`, `fetch_quotes`, `fetch_earnings_date`, `fetch_dividend_date`, `fetch_company_name`, `fetch_news`, `tradier_next_earnings_date` or `_fundamentals_calendar_sync`. Calls passed to `asyncio.to_thread` or `run_in_executor` are allowed. The existing tests of the four moved callers still pass.
- C, D and the E session are admitted on `tradier`. D keeps its `retries=0` behaviour. C and D requests carry their client's timeout.
- G1 not admitted returns `("degraded", ...)` without an HTTP call.
- G2 and H are admitted on `tradier_paper`. H not admitted raises the adapter's error and **makes no POST**: the mock transport sees zero requests.
- The existing auto-trader, earnings-lookup and regime tests still pass (`tests/test_earnings_lookup_fire.py` among them).
- **Ratchet:** an AST scan of `backend/app/**/*.py` finds every `httpx.get/post`, `client.get/post` and `client.stream` call whose URL argument references `_tradier_base`, `get_tradier_creds`, `TRADIER_BASE_URL`, `_SANDBOX_BASE` or the literal `tradier.com`.
  - It asserts each one lies inside the helpers, site F, the stream connection (E), or the G2/H sites, each in an explicit allowlist with its reason.
  - Any new direct Tradier call fails the test.

### T4 — scan-cost measurement (blocked by T2)
**Files:** new `backend/tests/test_tradier_scan_call_budget.py` only.
- Run `_execute_scan_core` (options) on N = 20 fixture symbols, with a counting fake transport (no network) and a governor whose bucket is effectively unlimited.
- Record and print the Tradier requests per symbol by endpoint, both cold and with the expirations cache warm.
- Assert that every request was admitted through `tradier`.
- The coordinator turns the counts into a projected full-universe duration at 120/min (capacity 15) for SP500, NDX100 and DOW30, and records it on #169.

## 4. Size and order
T1 → T2 → T3, with T4 after T2. T3 and T4 touch disjoint files. Expected size: about 200 lines of code and about 650 lines of tests.

## 4a. Plan audit log
- **First plan stage: rounds 1–3, capped, not clean.**
  - **Round 1 (41cde651), 2 gate findings:** G1, deadline-bound callers lose Tradier to the fallback under load (plus the `httpx.Timeout` `TypeError`); G2, the async helper's `timeout=None`. Both were fixed in r2. G2's fix and G1's float `admit_timeout` remain in r4.
  - **Round 2 (1071fbd5), 1 gate finding:** R2-G1, the Intraday fire-path branch was not covered. Fixed in r3 by wrapping the submitted callable. That wrap remains in r4 as `run_on_fire_path`.
  - **Round 3, 1 gate finding, not fixed (cap):**
    - **What it found (R3-G1):** r3 made every earnings lookup priority, so a stock scan's up-to-5 concurrent lookups competed with the fire path's 2 s priority budget. A fire could then miss its slot, fall back to yfinance bars and size the order differently.
    - **Root cause:** a deadline-bound caller cannot both wait for a slot and stay inside its deadline once other urgent traffic competes.
- **Second plan stage (decision `TRADIER-GOVERNOR-NEW-PLAN-STAGE-2026-10-10`), r4.**
  - **The fix:** fire-path calls never wait (overdraft, D1/D3), and the stock scan's lookups wait *before* their deadline (prepay), so the two no longer compete.
  - **Dropped:** r3's reserve and priority rule.
  - **Round 4 (a6a959c5), round 1 of the new stage, 1 gate finding, fixed in r5:**
    - **What it found (R4-G1):** the 10 s bulk admission budget turned waiting into the yfinance fallback under scan load, about 1–12 % of sync admissions with 5–10 contenders in the auditor's model.
    - **Why that changes numbers:** `fetch_candles` caches the fallback for the day, so a later fire's regime fetch reads yfinance bars with no Tradier call. That is R3-G1 through the cache. Scan-card Intraday regimes also changed.
    - **The fix:** bulk sync admission waits without limit; the four on-loop callers move to worker threads, with an overdraft safety net and an AST ratchet; and D5's claim is corrected.
    - **Below-gate notes taken in the same revision:** site F joins the overdraft (otherwise armed orders could stop firing after large scans); D's text is corrected (it is on the fire path, and waits); the price probe's cooldown outcome is corrected.

## 5. Out of scope / residuals
- **Bucket sizes.** Kenneth's tiers (spec §3) are not re-derived here, and the `tradier_paper` sizing (60/min) is a conservative assumption. Tradier's published limits should be confirmed by Kenneth; changing them is one number.
- **The long-lived streaming connection (E)** is not metered.
- **Live-account effect.** The real effect on a live scan is measured by T4 counts and projection only; a live timing run needs Kenneth's machine and token.

## 6. Acceptance (item #169)
- Every Tradier HTTP call site is admitted by the governor (T3 ratchet).
- A 429 is honoured with Retry-After across sync and async.
- The scan-cost projection is recorded on #169.
- T1–T4 green; full backend `pytest` (Python 3.11) shows no new failures against main.
- Plan audit clean, then code audit clean (`audit_rule`, cap 3 per stage).
- The scan slowdown was pre-accepted by Kenneth ("ok Go ahead", 2026-10-10); the T4 projection is recorded for him anyway. Never merged without his explicit go.
