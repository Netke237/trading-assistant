> **Rescued 2026-09-17.** Was `PLAN_CHART_DEFERRED_FIXES.md` at the repo root on
> `claude/terminated-session-details-ozquzb`, the ONLY copy anywhere on origin, and that
> branch is slated for deletion. Renamed into `plans/` with the branch's own date so it
> sorts with its siblings. Content is byte-identical to the original; nothing was edited.
> The chart work it describes SHIPPED — this is the unsaved document, not open work.

# Plan: fix the two deferred chart-lookback audit findings

## Origin

Round 1 of the adversarial audit on the 1h/4h chart lookback widening
(`claude/previous-session-token-limit-bgs1df`, commit `80743b7`) deferred
four findings. Two were named with reasons in the round-1 summary; two were
unnamed cosmetic nits whose detail lived only in that session's transcript,
which is no longer retrievable. This plan covers the two recoverable items.

Both are reachable from the current branch after fast-forwarding onto
`origin/claude/previous-session-token-limit-bgs1df` (already done — HEAD is
`101d388`, which includes the VWAP session-anchor fix and the round-1
audit-fix commit).

---

## Finding 1 — `days` query param is a floor, not a limit

**File:** `backend/app/data/chart_cache.py`, `get_intraday()` (lines 45-53)
**Also:** `backend/app/routers/chart.py`, `history()` endpoint (lines 18-24)

### Current behavior

```python
async def get_intraday(symbol: str, interval: str = "15min", days: int = 55) -> list[dict]:
    interval = normalize_interval(interval)
    if interval == "daily":
        days = max(days, _CHART_DAILY_DAYS)     # 1825
    elif interval == "weekly":
        days = max(days, _CHART_WEEKLY_DAYS)    # 1825
    elif interval in ("1h", "4h"):
        days = max(days, _CHART_HOURLY_DAYS)    # 730
```

`max(days, cap)` can only ever push `days` *up* to the per-interval cap. A
caller that explicitly asks for a smaller window (e.g. `days=10` for a
daily chart) silently gets the full 5-year window back instead. The router
default is a literal `days: int = Query(55)`, so there is no way to tell
"caller omitted `days`" apart from "caller explicitly asked for 55" — which
is exactly why round 1 left this alone: forcing a `min()` instead of `max()`
would also break the *existing* legitimate use of a larger explicit value
(`test_1D_and_daily_share_one_cache_entry_and_ttl` passes `days=3650` for
`"1D"` and expects exactly `3650` back, not the 1825 cap).

### Root cause

The function conflates two different things under one `days: int` param:
"the default window for this interval" and "an explicit request that
should override the default in either direction." A plain `int` default
can't distinguish "not supplied" from "supplied as 55."

### Fix

Use `days: int | None = None` as the sentinel for "not supplied," and only
apply the per-interval default when it's `None`. An explicit value —
smaller *or* larger — is passed through untouched (matching the existing
`days=3650` test, which relies on exactly this "explicit values aren't
touched" behavior today for the *larger* case).

```python
async def get_intraday(symbol: str, interval: str = "15min", days: int | None = None) -> list[dict]:
    """Return OHLCV bars, served from cache when fresh.

    `days=None` (the default) applies the per-interval default window ---
    the historical behavior of the daily/weekly/1h/4h widening. An explicit
    `days` is honored as the caller's real request, smaller or larger,
    since chart_cache only sets the default and never re-caps an explicit
    value (market.py's _YF_MAX_DAYS is the actual fetch-time ceiling).
    """
    interval = normalize_interval(interval)
    if days is None:
        if interval == "daily":
            days = _CHART_DAILY_DAYS
        elif interval == "weekly":
            days = _CHART_WEEKLY_DAYS
        elif interval in ("1h", "4h"):
            days = _CHART_HOURLY_DAYS
        else:
            days = 55
    key = _key(symbol, interval, days)
    ...
```

In `backend/app/routers/chart.py`:

```python
@router.get("/history")
async def history(
    symbol: str = Query(...),
    interval: str = Query("15min"),
    days: Optional[int] = Query(None),
) -> list[dict]:
    return await get_intraday(symbol.upper(), interval, days)
```

(`Optional` is already imported in that file for the WS handler's
`Optional[asyncio.Queue]`.)

### Why this is safe (production call sites)

- Grepped every call site of `get_intraday` in `backend/app/`: `chart.py`
  has 5 (not 4 — round 3 of this audit caught a miscount here) — line 24
  (`history()`, forwards the query param), lines 39 and 52 (`stream()`'s
  initial history fetch + MTF fetch, both omit `days`), and lines 77 and 80
  (the on-tick candle-close re-fetch branch inside `stream()`'s loop, also
  both omit `days`) — plus `chart_alert_scheduler.py` (2 call sites, both
  omit `days`). No internal *production* caller ever passes an explicit
  `days` for daily/weekly/1h/4h, so every existing production call keeps
  getting exactly the same widened default as before (`None` →
  per-interval default, same numbers).
- Grepped the frontend: no production code calls `/chart/history` at all
  (only one Playwright e2e test, `chart-phase2-4-cohesion.spec.ts`, using
  `days=5&interval=15min` — a sub-hourly interval untouched by this branch
  either way).

### Existing tests this breaks — must be updated as part of this fix

Round-1 self-review of this plan caught that the "no caller passes an
explicit days" grep above was scoped to `backend/app/` only, and silently
excluded `backend/tests/`. That's exactly backwards for a plan whose whole
point is a test-observable behavior change: four existing tests hardcode
`days=55` for daily/weekly/1h/4h/60m and assert it gets *widened* — which
was the only way to express "the router's old default" before this fix
existed. Under the new semantics (explicit value passed through untouched)
these assertions go from correct to wrong the moment the fix lands:

1. **`backend/tests/test_chart_cache.py::test_hourly_intervals_widen_past_the_55_day_default`**
   (parametrized `1h`/`4h`) — calls `get_intraday("AAPL", interval, 55)`,
   asserts `fetch_intraday_candles` called with `("AAPL", interval, 730)`.
   **Change:** drop the explicit `55` — call `get_intraday("AAPL", interval)`
   instead, keep the same `730` assertion. This is still exactly the
   "caller omitted days → default widening" case; only the encoding of
   "omitted" changes from `55` to no-arg/`None`.
2. **`backend/tests/test_chart_cache.py::test_60m_normalizes_to_1h_and_widens`**
   — same pattern: drop the explicit `55` from
   `get_intraday("AAPL", "60m", 55)`, keep the `("AAPL", "1h", 730)`
   assertion.
3. **`backend/tests/test_market_data_fixes.py::test_get_intraday_widens_daily_weekly_at_production_default`**
   — calls `get_intraday("SPY", "1D", days=55)` / `"1W", days=55` /
   `"15min", days=55` and asserts daily/weekly widen while 15min doesn't.
   **Change:** drop `days=55` from all three calls (call with no `days`
   arg), keep the same assertions. Also update the docstring's premise —
   it currently says *"The chart's real entry points … pass days=55"*,
   which was true only because the router's old literal default happened
   to be `55`; post-fix the router passes `None` when the query param is
   omitted, so rephrase to "the router's real entry points omit `days`."
4. **`backend/tests/test_chart_router.py::test_history_uppercases_symbol`**
   — hits `GET /chart/history` with no `days` query param and asserts
   `mock_get.assert_called_once_with("AAPL", "15min", 55)`, depending on
   the router's old `Query(55)` literal default being forwarded.
   **Change:** the router now forwards `None` when `days` is omitted from
   the request — update the assertion to
   `mock_get.assert_called_once_with("AAPL", "15min", None)`.

None of these four needs new behavior verified — they're all "omitted
days" cases that keep the same widening outcome, just expressed via the
new `None` sentinel instead of the old `55` stand-in. The actual new
behavior (explicit `days` for daily/weekly/1h/4h no longer gets floored)
has no existing test either direction — that's what the new tests below
cover.

- `test_1D_and_daily_share_one_cache_entry_and_ttl` and
  `test_1W_and_weekly_share_one_cache_entry_and_ttl` both pass explicit
  `days=3650` and assert the cache key ends in `:3650` — i.e. they already
  depend on "explicit values pass through untouched" for the *larger* case.
  Unaffected by this fix; listed here only to confirm they were checked.

### New test coverage

Add to `backend/tests/test_chart_cache.py`:
- Explicit `days=10, interval="daily"` resolves to `days=10` (cache key
  ends `:10`, `fetch_intraday_candles` called with `days=10`) — the actual
  regression guard for this fix; this is the case that was previously
  impossible.
- `days=None` (or omitted) for `interval="daily"` still resolves to `1825`
  — regression guard that the no-args default behavior is unchanged.

Modify (not just add to) `backend/tests/test_chart_cache.py`,
`backend/tests/test_market_data_fixes.py`, and
`backend/tests/test_chart_router.py` per the four items above.

---

## Finding 2 — frontend WS latches into `'error'` permanently on a data error

**File:** `frontend/lib/chartWS.ts`, `ChartWSClient` (lines 21-99)

### Current behavior

```ts
private dataError = false;   // true after server sends type:"error"

connect(): void {
  if (this.destroyed || this.dataError) return;   // (a) never connects again
  ...
}

this.ws.onmessage = (e) => {
  ...
  if (msg.type === 'error') {
    this.dataError = true;                          // (b) latched forever
    this.stateHandler?.('error');
  }
  ...
};

this.ws.onclose = () => {
  if (!this.destroyed && !this.dataError) {          // (c) reconnect blocked
    ...
  }
};
```

The backend closes the WS right after sending `type: "error"`
(`backend/app/routers/chart.py`'s `stream()` handler `return`s after
`send_json({"type": "error", ...})`), so `onclose` fires immediately after
`dataError` is set. `(c)` then blocks the scheduled reconnect, and `(a)`
blocks any future manual `connect()` call too — there is no code path that
ever clears `dataError`, so the client is stuck in `'error'` state for the
rest of its lifetime. The only recovery today is unmounting it, which
`ChartWorkspace` only does when `symbol` or `interval` changes
(`frontend/components/organisms/ChartWorkspace/index.tsx`'s
`useEffect(..., [symbol, interval])`) — so a momentary condition (backend
mid-restart, a transient upstream data-provider gap) leaves the chart dead
until the user manually switches away and back.

### Root cause

`dataError` was written as a one-way latch to solve a real problem —
"don't hammer the server for a symbol that will never have data" — but it
conflates a *possibly transient* condition (temporarily no data) with a
*permanent* one (bad symbol), and gives no path back to `'connected'` for
the transient case.

### Fix

Stop treating a data error as a permanent stop condition. The existing
exponential backoff (`backoff = Math.min(backoff * 2, 30_000)`, only reset
on a successful `history` message) already exists specifically to avoid
hammering the server — reuse it here instead of a separate permanent
latch. A data error becomes: report `'error'` state to the UI (unchanged),
but keep scheduling reconnects on the same capped backoff as any other
disconnect. If the condition was transient, the next attempt (≤30s later,
backing off further on repeated failures) recovers on its own. If the
symbol is genuinely never going to have data, retries settle at the same
30s cap as a normal dead connection — no worse than today's behavior for
an ordinary flaky connection.

```ts
// `dataError` field removed entirely (see below).

connect(): void {
  if (this.destroyed) return;
  ...
}

this.ws.onmessage = (e) => {
  try {
    const msg = JSON.parse(e.data as string) as WSMessage;
    if (msg.type === 'history') {
      // Real data received — connection is healthy, reset backoff.
      this.backoff = 1000;
    }
    if (msg.type === 'error') {
      // Backend signals no data is available for this symbol/interval
      // right now. Surface 'error' to the UI, but keep retrying on the
      // capped backoff below rather than stopping forever --- the
      // condition may be transient (upstream gap, backend restart).
      this.stateHandler?.('error');
    }
    this.handlers.forEach(h => h(msg));
  } catch { /* ignore malformed messages */ }
};

this.ws.onclose = () => {
  if (this.destroyed) return;
  this.stateHandler?.('reconnecting');
  this.timer = setTimeout(() => {
    this.backoff = Math.min(this.backoff * 2, 30_000);
    this.connect();
  }, this.backoff);
};

this.ws.onerror = () => {
  // Previously guarded by `!this.dataError`. That guard was a no-op under
  // the old permanent-latch design (dataError could be set at most once,
  // and the client never reconnected afterward, so there was never a
  // "later onerror while dataError is true" to skip). With the latch gone
  // entirely, this handler just always reports 'error' and closes —
  // onclose fires moments later and schedules the retry.
  this.stateHandler?.('error');
  this.ws?.close();
};
```

**`dataError` is deleted, not kept.** Round 2 of this audit caught that the
original draft of this fix kept the field "because `ChartWorkspace` still
needs the distinct `'error'` state" — but that's a category error: the
private `dataError` boolean and the public `ConnectionState` string
(`'error'`, passed through `stateHandler`) are two different mechanisms.
`ChartWorkspace` only ever reads the latter. (Round 3 tightened this
argument further: "`ChartWorkspace` can't read a private field" is true of
*any* private field by construction — including a correctly-designed one
— so it isn't on its own evidence that removal is safe. The claim that
actually matters, verified by reading the whole class — constructor,
`connect()`, `onStateChange`, `onMessage`, `destroy()` — is that **no
method inside `ChartWSClient` itself** still needs `dataError` once it's
removed from all four of its touch points: the *reads* that gate
`connect()` and `onclose`/`onerror`, and the *write* inside the `onmessage`
handler's `type: 'error'` branch (`this.dataError = true;`) — the fix's
code block above already rewrites all four. Round 5 caught that this
prose had undercounted them as "three," naming only the three gating
methods and silently folding in — or omitting — the fourth, the
`onmessage` write; the constructor and `destroy()` never referenced the
field even before this fix. Once those four sites are rewritten, nothing
anywhere reads the field —
it becomes write-only dead state. There's no future use being preserved by
keeping it; deleting `private dataError = false;` — **along with its
preceding JSDoc comment**, `/** True after the server sends type:"error"
(data unavailable). Stops auto-reconnect. */` (round 4 caught this: the
comment documents exactly the latching behavior this fix removes, and
since it doesn't contain the identifier `dataError` itself, a plain
text-search for that name during implementation would miss it and leave
it dangling above the next field, `private handlers = new
Set<MessageHandler>();`, describing code that no longer exists) — and its
(now only) two write sites is the honest fix, not "keep it just in case."
If a future need arises to let `ChartWorkspace` distinguish "confirmed no
data" from "transient hiccup" in its UI, that would need an actual
consumer (e.g. a
getter) added deliberately, not a vestigial private field nobody reads.

### Why this is safe

- `ChartWorkspace`'s `onStateChange`/`onMessage` handling is unaffected —
  it already treats `'error'` as a display-only state (`setWsError`) and
  doesn't special-case "will never recover."
- No other file constructs or reads into `ChartWSClient` internals
  (grepped: only `ChartWorkspace/index.tsx` constructs one).
- Worst case for a permanently-bad symbol: reconnect attempts continue
  indefinitely at a 30s-capped interval instead of stopping after one —
  identical in kind to what already happens for a symbol whose connection
  just keeps failing for any other reason (network blip, server restart),
  which this code already retries forever today.

### New test coverage

Add `frontend/lib/__tests__/chartWS.test.ts` with a minimal mock
`WebSocket` class, installed as `global.WebSocket = MockWebSocket` before
constructing any `ChartWSClient` (jsdom, this project's configured Jest
`testEnvironment`, does not provide a real `WebSocket`; `chartWS.ts` reads
the global at each `new WebSocket(...)` call inside `connect()`, not at
module-import time, so a per-test global reassignment is sufficient — no
constructor-injection seam is needed or proposed). The mock assigns
`onopen`/`onmessage`/`onclose`/`onerror` and never opens a real socket.
Covering:
- A `type: "error"` message followed by `onclose` schedules a reconnect
  (fake timers; assert a new `WebSocket` is constructed after the backoff
  delay) instead of staying silent forever.
- A subsequent successful `type: "history"` message after a prior data
  error resets `backoff` (assert a *further* `onclose` after that success
  reconnects with the 1000ms floor rather than a continued-growing delay).
- `destroy()` still prevents any further reconnect after a data error
  (unchanged behavior — explicit regression guard; no longer phrased
  around `dataError` since that field no longer exists — `destroyed` is
  the only relevant flag).
- Backoff compounds correctly across *repeated* errors, not just once:
  fire 3-4 consecutive `error`→`onclose` cycles (fake timers, no
  intervening `history` message) and assert the scheduled delay sequence
  is `1000 → 2000 → 4000 → …`, capped at `30000`, never resetting back to
  `1000` in between. This is the actual mechanism the "Why this is safe"
  section above relies on to claim retrying forever isn't "hammering the
  server" — without this test, a regression that reset backoff on every
  error (instead of only on a successful `history` message) would pass
  the other three tests undetected.

---

## Out of scope

- The two unnamed "cosmetic nits" from round 1 — undocumented, not
  reconstructable from the repo; excluded from this plan.
- Any change to `market.py`'s `_YF_MAX_DAYS` / `_days_to_yf_period` — those
  remain the actual fetch-time ceiling and are untouched by Finding 1.
- Any change to the reconnect backoff *values* themselves (1s start, 30s
  cap) — Finding 2's fix reuses them as-is.

## Files touched

- `backend/app/data/chart_cache.py`
- `backend/app/routers/chart.py`
- `backend/tests/test_chart_cache.py` (modify 2 existing tests + new tests)
- `backend/tests/test_market_data_fixes.py` (modify 1 existing test)
- `backend/tests/test_chart_router.py` (modify 1 existing test)
- `frontend/lib/chartWS.ts`
- `frontend/lib/__tests__/chartWS.test.ts` (new file)
