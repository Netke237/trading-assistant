# YF-CALENDAR-SEMAPHORE — the yfinance limiters must not bind to the first event loop

Phase id: `YF-CALENDAR-SEMAPHORE` · Board item / tracking issue: **#142**
Branch: `board/yf-calendar-semaphore-47d6c524` (cut from `main` `13c8b52c`)
Found while isolating #129 (STOCKS-T1-FOLLOWUPS, #139).

## Why

`backend/app/data/market.py` keeps two process-wide `asyncio.Semaphore`s created lazily on first use:

| Limiter | Lines (13c8b52c) | Limit | Guards |
|---|---|---|---|
| `_YF_CALENDAR_SEM` / `_get_yf_sem()` | L1340-1347 | 5 | `fetch_calendar_dates_async` (L1364: yfinance earnings + dividend fallback used by every options-scan candidate, `routers/scan.py` L658) and the chain IV backfill in `fetch_option_chain_async` (L1680) |
| `_PREWARM_SEM` / `_get_prewarm_sem()` | L1450-1457 | 15 | `prewarm_candles_async` (candle pre-warm, `routers/scan.py` L2290) |

On Python 3.11 an `asyncio.Semaphore` binds to the event loop that first has to **wait** on it
(`asyncio.mixins._LoopBoundMixin._get_loop`, called from `acquire()` only when the semaphore is
locked). Any later event loop in the same process that contends on it gets
`RuntimeError: <Semaphore [locked]> is bound to a different event loop`. `fetch_calendar_dates_async`
catches only `EarningsLookupError`, so the RuntimeError escapes to the scan and the contending symbol
is lost.

**Reproduced on Python 3.11.17 (2026-10-10):** two consecutive `asyncio.run(...)` calls in one process,
each gathering `fetch_calendar_dates_async` for 10 symbols with a 50 ms stubbed yfinance fetch →
loop 1: 10 ok; **loop 2: 5 ok, 5 `RuntimeError` ("is bound to a different event loop")**.

**Who runs more than one loop per process:** pytest-asyncio (`asyncio_mode = auto`, a new loop per test —
the #129 offline ranking failure, symbols 6-10 dropped, is consistent with this); CLI scripts that call
`asyncio.run` more than once per process; any future background thread with its own loop. The uvicorn
server runs scans on one loop, so production today is exposed only if a second loop ever contends —
cheap to make impossible.

## The gate (audit_rule)

A finding blocks only if it can put a **wrong number in front of a user or on a broker order**, or
**corrupt persisted data**. Here: a symbol silently missing from a scan, or an earnings/dividend date
lost (it decides the event gate and the stock card's status cap), is a wrong result in front of a user.

## Decision (technical, coordinator): per-loop semaphores

The issue offered "per-loop semaphore or a threading limiter". **Per-loop**: one `asyncio.Semaphore`
per running event loop, held in a `weakref.WeakKeyDictionary` keyed by the loop (a weak key never matches a
new loop that reuses a dead loop's id). Note: a semaphore that has ever been contended holds its loop in
`Semaphore._loop`, so such an entry is not collected when its loop closes — a small, bounded memory cost in
multi-loop processes (tests, scripts); do not claim otherwise in the code comment.
- Same behaviour as today on the single uvicorn loop (limit 5 / 15, same `async with` call sites).
- No thread blocked while waiting (a `threading.BoundedSemaphore` acquired inside the event loop would
  block the loop; acquiring it in a worker thread would change every call site).
- Trade-off, accepted: two loops running **at the same time** each get their own limit (5 + 5 calendar
  fetches). Today that case crashes instead; no production code runs two scan loops concurrently.

## Scope

**Files:** `backend/app/data/market.py` (the two getters and their globals only), new
`backend/tests/test_yf_semaphore_loops.py`. Nothing else. No call site changes (`async with
_get_yf_sem():` / `sem = _get_prewarm_sem()` stay). The existing
`tests/test_market_data_fixes.py::test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore`
patches `_get_yf_sem` and must stay green unedited.

**Out:** the limits themselves (5, 15), the calendar cache / failure back-off, the fundamentals
prefetch's own local semaphore (`services/fundamentals_store.py`, created inside its own loop — not
affected), every other module.

## Task 1 — per-loop yfinance limiters

**Change (`backend/app/data/market.py`):**
1. `import weakref` with the other stdlib imports.
2. One private helper:
   ```python
   def _loop_semaphore(
       registry: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]", limit: int,
   ) -> asyncio.Semaphore:
       """The semaphore for the RUNNING event loop, created on first use. ..."""
       loop = asyncio.get_running_loop()
       sem = registry.get(loop)
       if sem is None:
           sem = asyncio.Semaphore(limit)
           registry[loop] = sem
       return sem
   ```
   with a doc comment stating the mechanism above (binds to the first loop that waits; one per loop
   keeps the limit on every loop and never raises "bound to a different event loop").
3. Replace `_YF_CALENDAR_SEM: asyncio.Semaphore | None = None` with
   `_YF_CALENDAR_SEMS: weakref.WeakKeyDictionary[...] = weakref.WeakKeyDictionary()` and
   `_get_yf_sem()` with `return _loop_semaphore(_YF_CALENDAR_SEMS, 5)`; same for `_PREWARM_SEM` →
   `_PREWARM_SEMS`, `_get_prewarm_sem()` → `_loop_semaphore(_PREWARM_SEMS, 15)`. Keep the existing
   comments that explain each limit. Both getters are only ever called inside a coroutine (verify:
   L1364, L1466, L1680), so `get_running_loop()` cannot raise on a real path.

**Tests first** (new `backend/tests/test_yf_semaphore_loops.py`; sync test functions that call
`asyncio.run` themselves, so pytest-asyncio's own loop is not involved; reset `_yf_cal_cache`,
`_yf_cal_cache_date` and `_yf_cal_fail_until` around each test; stub `_calendar_dates_yf_strict` with a
short `time.sleep` so more than 5 calls contend):
- **calendar across loops:** two consecutive `asyncio.run` bursts of 10 distinct symbols each through
  `fetch_calendar_dates_async` → every result is a tuple, no exception, in **both** bursts (today: burst 2
  has 5 RuntimeErrors).
- **limit still enforced:** within one loop, the stub records the peak number of concurrent calls → peak
  ≤ 5 and > 1 (the limiter still limits, and does not serialize).
- **prewarm across loops:** stub `fetch_candles_async` (async, short `asyncio.sleep`, returns one row);
  two consecutive `asyncio.run(prewarm_candles_async([20 symbols]))` → both return 20 (today: the second
  returns fewer, `return_exceptions=True` hides the RuntimeErrors); peak concurrency ≤ 15.
- **one semaphore per loop:** inside one loop, `_get_yf_sem() is _get_yf_sem()`; across two loops the
  objects differ.
Run them on Python 3.11 and see the across-loop tests FAIL first for the predicted reason.

**Done when:** new tests green; `tests/test_market_data_fixes.py` green unedited; full backend suite on
Python 3.11 shows no new failure versus the base (`13c8b52c`) run.

**Commit:** `fix(market): one yfinance limiter per event loop — no symbol lost to a loop-bound semaphore`

## Coordinator checks after the build

1. Re-run the reproduction script (two loops, 10 symbols): loop 2 must be 10 ok, 0 errors.
2. Full backend suite on Python 3.11, compared with the base run.
3. `git merge origin/main` + retest, then the code audit on `origin/main..HEAD`.
