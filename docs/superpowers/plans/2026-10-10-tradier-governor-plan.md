# TRADIER-GOVERNOR — every Tradier call through the shared rate limiter (board #169)

**Phase id:** `TRADIER-GOVERNOR` · **Board item / tracking issue:** #169 · **Branch:** `board/tradier-governor-889de9f2` (from origin/main e765cf4f)
**Source:** NO-LIVE-QUOTE ticket TG-1 (`.scratch/no-live-quote/issues/08-tradier-governor.md`), reconciliation ticket 13.
**Goal (Kenneth, 2026-10-09):** "use the rate limiter for tradier, we don't want my account blocked or flagged."
**Merge decision reserved for Kenneth (TG-1):** an options scan gets slower. T4 measures by how much, and Kenneth decides before merge whether that is acceptable.

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
- **On the event loop:** at least `routers/regime.py:106` `fetch_price('VIX')`. Its `httpx.get` already blocks the loop for up to its HTTP timeout today.

**Per-symbol cost of an options scan:**
- `fetch_option_chain_async` makes **one** chains call per symbol. Expirations are cached per symbol per day (`_expirations_cache`).
- Candles, quote, company and calendar calls are added where their caches miss.
- `_SCAN_CONCURRENCY = 5`.

## 2. Design

**D1 — admission for sync callers (governor.py).**
- Add `TokenBucket.acquire_blocking(tokens=1.0, *, admit_timeout: float, priority=False) -> bool`. It sleeps the thread (`time.sleep`, the same refill arithmetic as `acquire`) until a token is free or `admit_timeout` (seconds, a plain `float`) elapses, and returns whether it got one.
- **Priority reserve (plan round 1 G1).** `TokenBucket` gains `reserve: float = 0.0` (must be `< capacity`). A normal acquisition (`acquire`, `acquire_blocking`, `try_acquire`) succeeds only while `tokens >= n + reserve`. A `priority=True` acquisition needs only `tokens >= n`. The refill rate is unchanged, so the total request rate never exceeds the bucket's rate. Priority callers only jump the queue. `tradier` gets `reserve=3`; `tradier_paper` gets `reserve=0`.
- Add `Governor.admit_sync(provider, *, admit_timeout: float, priority: bool = False) -> bool`:
  - false at once for an unknown provider or an open circuit;
  - otherwise waits out any `retry_at` cooldown and then a token, all within `admit_timeout`;
  - false on timeout, true when admitted.
- `admit_timeout` is **always a float admission budget, never the HTTP timeout**. Several sites pass an `httpx.Timeout` object as their HTTP timeout (A11: `_TRADIER_CALENDAR_HTTP_TIMEOUT = httpx.Timeout(4.0, connect=2.0)`), and `time.monotonic() + httpx.Timeout(...)` raises `TypeError`. The two values are separate arguments everywhere.
- Add `Governor.note_rate_limited(provider, retry_after: float | None)`: sets `retry_at = max(retry_at, now + (retry_after or backoff_delay(0)))` and `status = "degraded"`. `Governor.call`'s existing `RateLimited` branch calls it, so sync and async share one cooldown.

**D2 — no new circuit breaking for Tradier.** Today no Tradier call opens a circuit. The breaker would make every Tradier call fail fast for 60 s after 5 consecutive failures, so a short outage would drop scan symbols for a whole minute instead of call by call. The `tradier` provider is therefore built with a fail threshold that never trips (`fail=10**9`, commented). Pacing and the 429 cooldown are the whole change. `try_acquire` (site F) keeps working.

**D3 — one helper per mode in market.py, used by every market-data site.**
- **`_tradier_get(url, *, params=None, headers=None, timeout, admit_timeout: float, priority: bool = False)`**, the sync helper:
  - It calls `get_governor().admit_sync("tradier", admit_timeout=admit_timeout, priority=priority or _TRADIER_PRIORITY.get())`. If not admitted it raises `ProviderUnavailable("tradier rate limiter: no admission within <admit_timeout>s")`. Every A-site already treats any exception as a Tradier failure and takes its existing fallback or empty result, so callers need no change.
  - Then it calls `httpx.get(url, params=..., headers=..., timeout=timeout)`, where `timeout` is the site's **existing HTTP timeout passed through unchanged** (an int, or A11's `httpx.Timeout`).
  - On **429** it calls `note_rate_limited("tradier", <Retry-After seconds if numeric>)` and returns the response unchanged, so each call site's own `raise_for_status()` or status check behaves exactly as today.
  - On a **transport exception** it calls `record_failure` and re-raises (no breaker trip, per D2). On any other response it calls `record_success`.
  - Sync calls get **no retry**.
- **Admission budgets (plan round 1 G1).** Admission time adds to a call's latency, so every **deadline-bounded** caller must have `admit_timeout + HTTP timeout` inside its deadline, and must not be starved by bulk traffic:
  - **A11 `_fundamentals_calendar_sync`** (the earnings source under `auto_trader._TRADIER_LOOKUP_DEADLINE_S = 5.0`, used by the auto-fire event veto and by the stock scan's `_earnings_days_for`): **always `priority=True`, `admit_timeout=0.5`**. With the reserve, a token is normally immediate even while an options scan or the candle prewarm saturates the bucket, so Tradier's date still wins as today.
  - **The fire-path regime fetch** (`auto_trader._fetch_scan_window_bars` → `fetch_candles`, under `_REGIME_FETCH_DEADLINE_S = 25.0` with a 10 s HTTP timeout): `fetch_candles` keeps its signature. Instead a module-level `ContextVar` `_TRADIER_PRIORITY` (default False) and a context manager `market.tradier_priority()` mark the call priority. `_fetch_scan_window_bars` wraps its existing `fetch_candles(...)` call in `with market.tradier_priority():`. It runs in one thread, so the ContextVar is visible to `_tradier_get` in that same thread; no executor hop sits in between. `fetch_candles` uses `admit_timeout=10.0`, so 10 + 10 < 25.
  - **`fetch_price` under `_market_is_open`'s 3 s deadline:** not priority. That path is fail-closed (no price → treated as closed → the fire is blocked), so a busy limiter refuses the fire and changes no number.
  - **Every other A-site** (bulk/scan/UI traffic, not deadline-bounded): normal priority, `admit_timeout=10.0`.
  - **A 429 cooldown** (`retry_at`) is honoured by priority callers too. If it outlasts their `admit_timeout`, they fall back exactly as they do today when Tradier errors. That is the intended behaviour: Tradier told us to back off.
- **`_tradier_get_async(client, url, *, params=None, headers=None, timeout=httpx.USE_CLIENT_DEFAULT, retries=2, admit_priority=False)`**, the async helper:
  - **The timeout default is `httpx.USE_CLIENT_DEFAULT`, never `None` (plan round 1 G2).** In httpx an explicit `timeout=None` means no timeout at all, not the client default. B1–B6, C and D pass no per-call timeout today and rely on their client's default (scan `httpx.Timeout(10.0)`, the booking `AsyncClient(timeout=8)`, daily risk 10). The helper forwards `timeout` to `client.get` only as given, so those sites keep exactly their client's timeout.
  - `await get_governor().call("tradier", factory, retries=retries)`, where `factory` does `await client.get(...)` and raises `RateLimited(retry_after=...)` on 429, so `call` waits out Retry-After and retries. `Governor.call`'s token acquisition passes `priority` through to `TokenBucket.acquire` (no async caller uses priority in this phase; the parameter exists so async and sync share one bucket rule).
  - Any other response is returned for the call site to check as today.
  - If the retries run out on 429, `RateLimited` propagates. `ProviderUnavailable` cannot occur with D2's threshold. Each B-site's existing `except` handles both as a failed fetch, as it handles HTTP errors today.
- **A1–A11 and B1–B6 call the helpers** instead of `httpx.get` / `client.get`, with the same URL, params, headers and HTTP timeout (an A-site's timeout passed through verbatim; a B-site that passes none today passes none, so the helper's `USE_CLIENT_DEFAULT` applies), plus the A-site `admit_timeout` / `priority` from the budget list above. No other logic changes in those functions.

**D4 — the other sites.**
- **C (sectors) and D (daily_risk_hooks):** `_tradier_get_async(client, ...)`. D uses `retries=0`: the budget authorisation fails rather than waits, and its existing `raise_for_status` / `DailyRiskError` path is unchanged.
- **E:** `_create_session` acquires through `_tradier_get_async`'s admission. Add a `_tradier_post_async` twin, or a `method` argument on the helper. The long-lived stream POST is one connection, not a request rate, and stays as is.
- **F:** unchanged, already admitted.
- **G1:** goes through `_tradier_get` with `timeout=_PROBE_TIMEOUT` and `admit_timeout=float(_PROBE_TIMEOUT)` (or 2.0 if `_PROBE_TIMEOUT` is not a number). If not admitted, the probe returns `("degraded", "Tradier rate-limit budget busy; probe skipped")` instead of calling Tradier.
- **G2 and H** use the **paper sandbox account and token**, which Tradier rate-limits separately from the live account. Add a provider `tradier_paper` to `build_default_governor` (`rate=60/60, capacity=5`, same no-trip breaker). G2 and H call `admit_sync("tradier_paper", admit_timeout=<a float equal to their numeric HTTP timeout>)` before their request. If H is not admitted, it raises the adapter's existing order-failure error **before** anything is sent, so no order goes out and the user sees the error. An order is never sent without admission and never sent twice.

**D5 — what does not change.** Bucket rate and capacity for `tradier` (120/min, capacity 15) stay as configured (the new `reserve=3` holds back part of the existing capacity for priority callers; it adds no rate). Caches, fallbacks (yfinance, IBKR), scan concurrency, every HTTP timeout and every call site's error handling stay as they are, as do all response parsing and numbers.

## 3. Tickets

### T1 — governor sync admission and the shared 429 cooldown (blocks T2, T3)
**Files:** `backend/app/data/governor.py`, new `backend/tests/test_governor_sync_admission.py`.
- Add `TokenBucket.acquire_blocking`, the `reserve` / `priority` rule on `acquire`, `acquire_blocking` and `try_acquire`, `Governor.admit_sync`, `Governor.note_rate_limited`, a `priority` pass-through on `Governor.call`, and wire the `Governor.call` `RateLimited` branch to `note_rate_limited`.
- Use `fail=10**9` and `reserve=3` for `tradier`, and add the `tradier_paper` provider (D2, D4).
- **Tests** (fake clock or tiny real waits, < 1 s total):
  - `acquire_blocking` admits up to capacity, then waits about 1/rate, and returns False when `timeout` elapses first;
  - `admit_sync` honours a `retry_at` cooldown set by `note_rate_limited`, and refuses on an open circuit;
  - reserve: with the bucket drained to `reserve`, a normal `acquire_blocking` / `try_acquire` / async `acquire` is refused or waits, while a `priority=True` one is admitted at once; over a long run the admitted rate never exceeds `rate` whatever the mix;
  - `admit_sync` accepts only a float `admit_timeout` (a test passes A11's `httpx.Timeout` as the HTTP timeout through the T2 helper and asserts no `TypeError` path; see T2);
  - an async `call` that hits `RateLimited(retry_after=x)` sets the same cooldown that `admit_sync` then waits out;
  - the existing governor tests still pass;
  - `try_acquire` behaves as before.

### T2 — market.py helpers and the 17 market-data sites (blocked by T1)
**Files:** `backend/app/data/market.py`, new `backend/tests/test_tradier_governor_market.py`.
- Add `_tradier_get`, `_tradier_get_async`, the `_TRADIER_PRIORITY` ContextVar and `tradier_priority()` (D3), and switch A1–A11 and B1–B6 to them with the D3 admission budgets.
- **Tests:** a fake governor (injected via monkeypatch of `get_governor`) plus `respx`, or a mock `httpx` transport if respx is not installed. Check with `pip show respx`; otherwise use `httpx.MockTransport` for async and monkeypatch `httpx.get` for sync.
  - Every A and B function makes its Tradier request only after one admission on `tradier`.
  - A 429 with `Retry-After: 2` sets the cooldown, and the call site's result is the same as for any other HTTP error today.
  - Not admitted (fake returns False / raises) gives the same fallback or empty result as a transport error today. Assert each function's documented fallback value.
  - Async 429 then 200 gives one retry and the 200's parsed result.
  - **Timeouts pass through (G2):** each B-site request, made through a real `AsyncClient(timeout=X, transport=MockTransport)`, carries the client's timeout `X` in `request.extensions["timeout"]` (not all-None). Each A-site's `httpx.get` receives exactly its existing HTTP timeout, and A11's is the `httpx.Timeout(4.0, connect=2.0)` object.
  - **Deadline-bounded earnings lookup under load (G1):** with the **real** governor, drain the `tradier` bucket down to its reserve (as a saturating scan would) and keep it there. Then the real `auto_trader._lookup_earnings_date` for a symbol, with Tradier mocked to return a date and yfinance mocked to fail, returns **Tradier's date** within the 5 s deadline. With the bucket fully empty and a 429 cooldown active, it takes the existing fallback.
  - **ContextVar priority:** inside `with market.tradier_priority():`, `fetch_candles` is admitted as priority, and outside it as normal. The var is reset on exit, including on exception.
  - Finite parsing is unchanged: for each function, the same fixture response gives the same output before and after. Pin with existing fixtures where present.

### T3 — the remaining sites and the ratchet (blocked by T1, T2)
**Files:** `backend/app/routers/sectors.py`, `backend/app/services/daily_risk_hooks.py`, `backend/app/data/tradier_stream.py`, `backend/app/routers/data_sources.py`, `backend/app/data/tradier_paper.py`, `backend/app/services/auto_trader.py` (only the `with market.tradier_priority():` wrap in `_fetch_scan_window_bars`), new `backend/tests/test_tradier_governor_sites.py`.
- Apply D4, and the D3 fire-path priority wrap.
- **Tests:**
  - C, D and E-session are admitted on `tradier`; D's retries=0 behaviour holds; C and D requests carry their client's timeout (G2).
  - The fire-path regime fetch (`_fetch_scan_window_bars`) makes its Tradier candle request as priority (spy on `admit_sync`), and its cache-restore behaviour is unchanged (existing tests pass).
  - G1 not admitted returns `("degraded", ...)` without an HTTP call.
  - G2 and H are admitted on `tradier_paper`. H not admitted raises the adapter's error and **makes no POST** (assert the mock transport saw zero requests).
- **Ratchet:** an AST scan of `backend/app/**/*.py` finds every `httpx.get/post`, `client.get/post` and `client.stream` call whose URL argument references `_tradier_base`, `get_tradier_creds`, `TRADIER_BASE_URL`, `_SANDBOX_BASE` or the literal `tradier.com`. It asserts each lies inside the helpers, site F, the stream connection (E, long-lived), or the G2/H sites that are admitted on `tradier_paper`, each named in an explicit allowlist with its reason. Any new direct Tradier call fails the test.

### T4 — scan-cost measurement (blocked by T2)
**Files:** new `backend/tests/test_tradier_scan_call_budget.py` only.
- Run `_execute_scan_core` (options) on N = 20 fixture symbols with a counting fake transport (no network) and a governor whose bucket is effectively unlimited.
- Record and print the Tradier requests per symbol by endpoint, both cold and with the expirations cache warm.
- Assert every request was admitted through the `tradier` bucket.
- The coordinator turns the counts into a projected full-universe duration at 120/min (capacity 15) for SP500, NDX100 and DOW30, and records it on #169 for Kenneth's merge decision.

## 4. Size and order
T1 → T2 → T3, with T4 after T2. T3 and T4 touch disjoint files. Expected: about 190 lines of code and about 600 of tests.

## 4a. Plan audit log
- **Round 1 (41cde651), 2 gate findings, both fixed in this revision:**
  - **G1:** admission time is added inside deadline-bounded callers, so the earnings veto, the stock scan's earnings flag and the fire-path regime bars lose Tradier to the fallback under load. A literal implementation also passed A11's `httpx.Timeout` as a float budget (`TypeError`). Fixed with a float `admit_timeout` separate from the HTTP timeout, per-site budgets, the `reserve` / priority rule, and the ContextVar for the fire-path regime fetch. New T1/T2/T3 tests.
  - **G2:** `timeout=None` on the async helper removed every B/C/D timeout. Fixed with the default `httpx.USE_CLIENT_DEFAULT` and a T2/T3 pass-through test.

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
- **Merge only after Kenneth accepts the projected scan slowdown (TG-1).**
