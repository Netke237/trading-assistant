# Day-Scoped Tradier Caching + Options Pipeline Label Explanations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent, low-risk changes bundled in one plan because the user requested them together:

1. **Reduce Tradier call volume** (not concurrency) for two currently-uncached, per-symbol, per-scan calls: `fetch_fundamentals_calendar` and the expirations lookup inside `fetch_option_chain_async`. Both mirror `_candles_cache`'s already-established, already-trusted pattern in the same file — a date-keyed `dict[str, tuple[..., str]]`, checked against `date.today().isoformat()` before reuse. (Note: `_company_cache`, mentioned in earlier drafts of this plan alongside `_candles_cache`, is a *different* pattern — it's a permanent, never-expiring cache with no date check at all, since company names don't change; it is not what Tasks 1-2 mirror. Flagged during round-1 review as a factual inaccuracy in this framing — corrected here, no code was affected.)
2. **Add short bracketed explanations** to the four Options Pipeline funnel stage labels shown in the screener UI (`ScanFunnel` component), so a user reading the funnel understands what each stage is filtering for without needing to open the per-reason breakdown rows already shown beneath it.

**Context:** Investigated in this session — a live SP500/Position scan took ~416s wall-clock. Heston pricing (17.6s total across 7 calibrations) is not the bottleneck; the dominant cost is total Tradier HTTP request volume (an estimated 1,500-1,800 requests across ~518 symbols) funneled through a deliberately-capped 5-concurrent gate (`_SCAN_CONCURRENCY = 5` in `backend/app/routers/scan.py:230`, capped because a prior test found higher concurrency makes Tradier throttle harder, not help — see the comment at `scan.py:223-229`). Raising concurrency was already tried and rejected; reducing call *count* instead is the safe, untried lever. `fetch_fundamentals_calendar` and the chain-expirations lookup are the two calls that get zero caching today, unlike their neighbors in the same file.

**Non-goals:** Not touching `_SCAN_CONCURRENCY`. Not touching the IBKR/Tastytrade IV-enrichment calls inside `fetch_option_chain_async` (separate, already-fault-tolerant code path). Not adding the same bracket treatment to the *Stock* pipeline funnel (`ScanFunnel`'s `mode === 'stock'` branch) — only the Options pipeline was shown/requested; can be a fast follow-up if wanted.

**Tech stack:** Python 3 (backend), pytest, unittest.mock; TypeScript/React (frontend, label-only change, no new tests required — cosmetic string change, no new logic branches).

---

### Task 1: Day-scoped cache for `fetch_fundamentals_calendar`

**Files:**
- Modify: `backend/app/data/market.py` (add cache dict near line 57, cache check inside the function at line ~1393)
- Test: `backend/tests/test_market_data_fixes.py` (two new tests, mirroring `test_fetch_candles_async_cache_stores_date_string` / `test_fetch_candles_async_yesterday_entry_triggers_new_fetch` at lines 472-524)

Earnings/dividend calendar dates don't change intraday, so caching "for the current calendar day" (the same safety margin already used for candles) is safe. This is a per-symbol cache — no dependency on scan direction/horizon/overrides, since the raw calendar payload is symbol-only.

- [ ] **Step 1: Add the cache dict**

In `backend/app/data/market.py`, directly after the existing `_company_cache` declaration (line 57):

```python
# Company names: immutable; permanent cache for the process lifetime.
_company_cache: dict[str, str] = {}

# Fundamentals calendar (earnings/dividend dates): doesn't change intraday —
# date-keyed cache, same safety margin as _candles_cache.
_fundamentals_calendar_cache: dict[str, tuple[dict | None, str]] = {}
```

- [ ] **Step 2: Write the failing tests**

In `backend/tests/test_market_data_fixes.py`, add directly after `test_fetch_candles_async_yesterday_entry_triggers_new_fetch` (ends at line 522):

```python
@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_cache_stores_date_string():
    """After a successful fetch, the cache entry key must be an ISO date string,
    mirroring _candles_cache's pattern (test_fetch_candles_async_cache_stores_date_string)."""
    import app.data.market as mkt

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        _, cache_key = mkt._fundamentals_calendar_cache["AAPL"]
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    assert isinstance(cache_key, str), f"Expected str cache key, got {type(cache_key)}"
    assert cache_key == date.today().isoformat()


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_second_call_skips_network():
    """A second call for the same symbol on the same day must be served from
    cache -- exactly one HTTP call total, not two."""
    import app.data.market as mkt

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    try:
        first = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
        second = await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    mock_client.get.assert_called_once()
    assert first == second


@pytest.mark.asyncio
async def test_fetch_fundamentals_calendar_yesterday_entry_triggers_new_fetch():
    """A cache entry stamped with yesterday's date must NOT be served -- fresh
    HTTP call required, mirroring test_fetch_candles_async_yesterday_entry_triggers_new_fetch."""
    import app.data.market as mkt

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    stale_entry = {"tables": {"earnings": {"report_date": "2025-01-01"}}}

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [{"results": [{"tables": {"earnings": {"report_date": "2026-09-01"}}}]}]

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)

    saved = dict(mkt._fundamentals_calendar_cache)
    mkt._fundamentals_calendar_cache.clear()
    mkt._fundamentals_calendar_cache["AAPL"] = (stale_entry, yesterday)
    try:
        await mkt.fetch_fundamentals_calendar(mock_client, "AAPL")
    finally:
        mkt._fundamentals_calendar_cache.clear()
        mkt._fundamentals_calendar_cache.update(saved)

    mock_client.get.assert_called_once()
```

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py -v -k fundamentals_calendar` (from `backend/`) — expected: all 3 FAIL (function doesn't check/populate the cache yet). Use `-k fundamentals_calendar`, NOT `-k fundamentals_calendar_cache` — the latter only matches `test_fetch_fundamentals_calendar_cache_stores_date_string` (verified live: `1 passed, 2 deselected`) and silently skips the other two of these three tests at this checkpoint. An earlier draft of this plan had this bug in all four `-k` commands across Tasks 1 and 2.

- [ ] **Step 3: Implement the cache check in `fetch_fundamentals_calendar`**

In `backend/app/data/market.py`, replace the function body (currently lines ~1393-1416):

```python
async def fetch_fundamentals_calendar(
    client: httpx.AsyncClient, symbol: str
) -> dict | None:
    """Fetch the full fundamentals calendar response once per symbol.

    Returns the raw JSON dict (the list element for this symbol) so the caller
    can extract both earnings and dividend dates without a second HTTP round-trip.
    """
    cached = _fundamentals_calendar_cache.get(symbol)
    if cached is not None:
        data, cached_date = cached
        if cached_date == date.today().isoformat():
            return data

    result: dict | None = None
    try:
        resp = await client.get(
            f"{_tradier_base()}/beta/markets/fundamentals/calendars",
            headers=_headers(),
            params={"symbols": symbol},
        )
        resp.raise_for_status()
        data = resp.json()
        if data and isinstance(data, list):
            for entry in data:
                for r in entry.get("results", []):
                    result = r
                    break
                if result is not None:
                    break
    except Exception:
        result = None

    _fundamentals_calendar_cache[symbol] = (result, date.today().isoformat())
    return result
```

Note: a `None`/failed result is cached too (same-day). This is safe, not just convenient — confirmed directly against `scan.py:554-560`: `_extract_earnings_date`/`_extract_dividend_date` returning `None` from `fund_data` already unconditionally falls through to a yfinance calendar lookup (`fetch_calendar_dates_async`) regardless of *why* `fund_data` was `None` — a fresh failure and a cached same-day failure hit that identical fallback path. So caching a failed result only skips a same-day *retry against Tradier specifically*; it does not remove earnings/dividend data from the event-proximity gate, which already has its own independent fallback.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py -v -k fundamentals_calendar` (from `backend/`) — expected: all 3 PASS.

- [ ] **Step 5: Run the full existing test_market_data_fixes.py + test_scan_endpoint.py to confirm no regression**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py tests/test_scan_endpoint.py -v` (from `backend/`) — expected: all PASS, same counts as before this task.

- [ ] **Step 6: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_data_fixes.py
git commit -m "perf(market): day-scoped cache for fetch_fundamentals_calendar"
```

---

### Task 2: Day-scoped cache for the expirations lookup inside `fetch_option_chain_async`

**Files:**
- Modify: `backend/app/data/market.py` (add cache dict near the Task 1 addition, cache check inside `fetch_option_chain_async` at line ~1148-1163)
- Test: `backend/tests/test_market_data_fixes.py` (three new tests, same pattern as Task 1)

The expirations list (`/v1/markets/options/expirations`) is symbol-only — independent of `option_type`, `dte_bounds`, or `expiry`, all of which are applied *after* the raw dates list is fetched (lines 1164-1177). So one cache entry per symbol per day is correct regardless of which parameters a given call uses.

- [ ] **Step 1: Add the cache dict**

Directly after Task 1's `_fundamentals_calendar_cache` declaration:

```python
# Option expirations list: changes rarely (new expiries added ~weekly), not
# intraday -- date-keyed cache, same pattern as the calendar cache above.
_expirations_cache: dict[str, tuple[list[str], str]] = {}
```

- [ ] **Step 2: Write the failing tests**

Add directly after Task 1's three new tests:

Every test below patches `app.data.ibkr.fetch_iv_metrics_ibkr` and `app.data.tastytrade_iv.fetch_iv_metrics_tastytrade` to `return_value=None` — `fetch_option_chain_async` calls both unconditionally for IV enrichment (lines ~1248-1274), and the existing sibling test `test_fetch_option_chain_async_yf_iv_fallback_acquires_semaphore` (line 529) already isolates them the same way. Skipping this, as an earlier draft of this plan did, would make these tests issue a real synchronous `httpx.get` to `https://localhost:5000` (IBKR's local gateway check) on every run — slow at best, flaky depending on machine state at worst.

Every test below also uses `_FUTURE_EXPIRY` for its expirations-list JSON, not a hard-coded date string — `_FUTURE_EXPIRY = (date.today() + timedelta(days=30)).isoformat()` already exists at `test_market_data_fixes.py:26`, with a comment explaining exactly why: a hard-coded date eventually falls outside any `dte_bounds` window as time passes, silently breaking the test months later. An earlier draft of this plan hard-coded `"2026-09-19"`/`"2026-10-17"` here, which would have made `_nearest_expiration_in_window` return `None` and short-circuit `fetch_option_chain_async` to `return []` (`market.py:1169-1170`) once those dates aged out of the tests' `dte_bounds=(20, 40)` window — silently invalidating the `mock_client.get.call_count` assertion in the second test below. Do not reintroduce hard-coded absolute dates; reuse the existing constant.

```python
@pytest.mark.asyncio
async def test_fetch_option_chain_async_expirations_cache_stores_date_string():
    """Mirrors test_fetch_candles_async_cache_stores_date_string for the
    expirations-list cache inside fetch_option_chain_async."""
    import app.data.market as mkt

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
        _, cache_key = mkt._expirations_cache["AAPL"]
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    assert isinstance(cache_key, str), f"Expected str cache key, got {type(cache_key)}"
    assert cache_key == date.today().isoformat()


@pytest.mark.asyncio
async def test_fetch_option_chain_async_second_sequential_call_skips_expirations_call():
    """Two SEQUENTIAL chain fetches (one awaited fully before the next starts)
    for the same symbol on the same day must reuse the cached expirations
    list -- one expirations HTTP call total, even though each call still
    makes its own chain HTTP call (the chain itself is NOT cached, only the
    expirations list).

    Deliberately does NOT claim this holds for concurrent calls: scan.py's
    _build_spreads fetches the put and call legs for the same symbol via
    asyncio.gather (concurrently), so on a cache-cold symbol both coroutines
    can race past the cache-empty check before either writes to it, each
    issuing its own expirations call. This is a known, accepted gap in the
    cache's coverage for that one specific concurrent call site, not a bug in
    the cache itself -- subsequent calls (same day) still hit the now-warm
    cache. Not fixed here to avoid adding a lock/coalescing mechanism for a
    single-pair edge case."""
    import app.data.market as mkt

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    urls_called = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_client.get.call_args_list]
    expirations_calls = [u for u in urls_called if u and "expirations" in u]
    assert len(expirations_calls) == 1, f"expected exactly 1 expirations call, got {len(expirations_calls)}"
    assert mock_client.get.call_count == 3  # 1 expirations + 2 chain


@pytest.mark.asyncio
async def test_fetch_option_chain_async_yesterday_expirations_triggers_new_fetch():
    """A cache entry stamped with yesterday's date must NOT be served for the
    expirations list -- fresh HTTP call required."""
    import app.data.market as mkt

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    exp_resp = MagicMock()
    exp_resp.raise_for_status.return_value = None
    exp_resp.json.return_value = {"expirations": {"date": [_FUTURE_EXPIRY]}}

    chain_resp = MagicMock()
    chain_resp.raise_for_status.return_value = None
    chain_resp.json.return_value = {"options": {"option": []}}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[exp_resp, chain_resp])

    saved = dict(mkt._expirations_cache)
    mkt._expirations_cache.clear()
    mkt._expirations_cache["AAPL"] = (["2025-01-17"], yesterday)
    try:
        with (
            patch("app.data.ibkr.fetch_iv_metrics_ibkr", return_value=None),
            patch("app.data.tastytrade_iv.fetch_iv_metrics_tastytrade", return_value=None),
        ):
            await mkt.fetch_option_chain_async(mock_client, "AAPL", dte_bounds=(20, 40))
    finally:
        mkt._expirations_cache.clear()
        mkt._expirations_cache.update(saved)

    urls_called = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_client.get.call_args_list]
    expirations_calls = [u for u in urls_called if u and "expirations" in u]
    assert len(expirations_calls) == 1
```

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py -v -k expirations` (from `backend/`) — expected: all 3 FAIL. Use `-k expirations`, NOT `-k expirations_cache` — the latter only matches the first of these three tests (same class of bug as Task 1's `-k` filter, caught and fixed on the same review pass); `expirations` alone matches all three real test names.

- [ ] **Step 3: Implement the cache check**

In `backend/app/data/market.py`, inside `fetch_option_chain_async`, replace the expirations-fetch block (currently lines ~1148-1163):

```python
    try:
        exp_resp = await client.get(
            f"{_tradier_base()}/v1/markets/options/expirations",
            headers=_headers(),
            params={"symbol": symbol, "includeAllRoots": "true"},
        )
        exp_resp.raise_for_status()
        expirations = exp_resp.json().get("expirations")
        if not expirations:
            return []
        dates = expirations.get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        if not dates:
            return []
```

with:

```python
    try:
        cached_exp = _expirations_cache.get(symbol)
        if cached_exp is not None and cached_exp[1] == date.today().isoformat():
            dates = cached_exp[0]
        else:
            exp_resp = await client.get(
                f"{_tradier_base()}/v1/markets/options/expirations",
                headers=_headers(),
                params={"symbol": symbol, "includeAllRoots": "true"},
            )
            exp_resp.raise_for_status()
            expirations = exp_resp.json().get("expirations")
            if not expirations:
                return []
            dates = expirations.get("date", [])
            if isinstance(dates, str):
                dates = [dates]
            if not dates:
                return []
            _expirations_cache[symbol] = (dates, date.today().isoformat())
```

An empty/missing expirations response is deliberately NOT cached (unlike Task 1's fundamentals calendar) — a symbol with genuinely no listed options is rare, and caching an empty result here would silently suppress a real newly-listed contract appearing later the same day. This asymmetry versus Task 1 is intentional; flag it in Task 4's audit if that reasoning doesn't hold up.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py -v -k expirations` (from `backend/`) — expected: all 3 PASS.

- [ ] **Step 5: Run the full existing test suite to confirm no regression**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest tests/test_market_data_fixes.py tests/test_scan_endpoint.py tests/test_alternatives.py tests/test_shortlist.py -v` (from `backend/`) — expected: all PASS, same counts as before this task.

- [ ] **Step 6: Commit**

```bash
git add backend/app/data/market.py backend/tests/test_market_data_fixes.py
git commit -m "perf(market): day-scoped cache for option-chain expirations lookup"
```

---

### Task 3: Short bracketed explanations on the Options Pipeline funnel labels

**Files:**
- Modify: `frontend/components/organisms/ScanFunnel/index.tsx` (the `Stage` component's props/render, and the options-mode block only — lines 15-33 and 65-85)
- Modify: `frontend/components/organisms/ScanFunnel/ScanFunnel.module.css` (add two new classes; do not edit the existing `.stage`/`.finalStage`)

**Scoping correction (round 3):** an earlier draft of this task edited `.stage`/`.finalStage` directly, at 190px. Those two classes are shared by BOTH the options-mode block (lines 74-78, 80-83) and the stock-mode block (lines 51-55, 57-60) in the same file — editing them in place would have also widened the Stock Pipeline funnel's label column by 80px, for no reason, contradicting this task's own Non-goal ("only the Options pipeline was shown/requested"). Fixed by adding two *new* classes (`.stageWide`, `.finalStageWide`) instead of changing the shared ones, and giving `Stage` an opt-in `wide` prop so only the options-mode call sites use them. Stock mode's rendering is untouched — same classes, same 110px, same behavior as today.

Per the user's explicit direction: keep each bracket short — the detailed per-reason breakdown (e.g. "Score gate: score 64 rejected — 11 symbols") is already shown directly below the funnel, so the bracket is a category hint, not a restatement. Grounded in the actual reject-reason logic in `backend/app/routers/scan.py`, and covering all three reasons that feed each bucket, not just the most obvious one or two (round-2 review caught an earlier draft's "Data / Filters" bracket silently dropping the "no market data" case):
- `failed_data` (line ~1298-1300 `_data_kw = ("no market data", "price filter", "cap filter")` — three distinct reasons: symbol fetch failed outright, price outside the min/max filter, or market cap outside the min/max filter)
- `failed_pre_screen` — `score_stock(..., iv_rank=None, ...)`, gates on trend/pullback/trigger/event (docstring at `_process_symbol`, line ~490-495)
- `no_chain` — empty option chain within the resolved DTE window
- `failed_score` + `failed_contracts` combined — full `score_stock(..., iv_rank=<real>)` plus `contract_rules.yaml`'s hard-reject band (delta 0.20-0.85, DTE, liquidity, spread — `backend/config/contract_rules.yaml` lines 17-27, the `hard_reject:` block)

**Width check done up front, not deferred, but not treated as guaranteed either:** `ScanFunnel.module.css:14` fixes the label column at `110px` (`.stage { grid-template-columns: 110px 40px 1fr; }`), and the `Text` primitive rendering the label has no truncation — it's a plain wrapping span. The existing labels (max 17 characters, "Score + contracts") already roughly fill that column; any added text needs a wider column, not just shorter wording, or it will wrap to 2-3 lines and inflate every stage row's height. This step widens the column (110px → 190px) alongside genuinely short bracket text (kept to ~33 characters at most — the longest new label is exactly 33). Round-2 review checked the arithmetic and found it inconclusive, not confirmed: the longest new label is a ~94% character increase against only a 73% width increase, so it may still wrap to two lines rather than fitting on one — the honest expectation is "probably close, not guaranteed," which is exactly why Step 3 below is a real verification step with a concrete fallback (shorten further), not a formality.

- [ ] **Step 1: Add two new (not shared) CSS classes**

In `frontend/components/organisms/ScanFunnel/ScanFunnel.module.css`, directly after the existing `.stage` block (after line 18) and directly after the existing `.finalStage` block (after line 51), add new classes rather than editing the existing ones — `.stage`/`.finalStage` stay exactly as they are today, at 110px, so Stock mode is untouched:

```css
.stageWide {
  display: grid;
  grid-template-columns: 190px 40px 1fr;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
}
```

```css
.finalStageWide {
  display: grid;
  grid-template-columns: 190px 40px;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
}
```

- [ ] **Step 2: Give the `Stage` component an opt-in `wide` prop**

In `frontend/components/organisms/ScanFunnel/index.tsx`, replace the `StageProps` interface and `Stage` function (lines 7-33):

```tsx
interface StageProps {
  label: string;
  count: number;
  rejected?: number;
  rejectedLabel?: string;
  total: number;
}

function Stage({ label, count, rejected, rejectedLabel, total }: StageProps) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <>
      <div className={styles.stage}>
        <Text size={11} tone="secondary">{label}</Text>
        <Data size={12} weight={500}>{count}</Data>
        {rejected != null && rejected > 0 ? (
          <span className={styles.rejected}>
            −{rejected}{rejectedLabel ? ` ${rejectedLabel}` : ''}
          </span>
        ) : <span />}
      </div>
      <div className={styles.bar}>
        <div className={styles.barFill} style={{ width: `${pct}%` }} />
      </div>
    </>
  );
}
```

with:

```tsx
interface StageProps {
  label: string;
  count: number;
  rejected?: number;
  rejectedLabel?: string;
  total: number;
  wide?: boolean;
}

function Stage({ label, count, rejected, rejectedLabel, total, wide }: StageProps) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <>
      <div className={wide ? styles.stageWide : styles.stage}>
        <Text size={11} tone="secondary">{label}</Text>
        <Data size={12} weight={500}>{count}</Data>
        {rejected != null && rejected > 0 ? (
          <span className={styles.rejected}>
            −{rejected}{rejectedLabel ? ` ${rejectedLabel}` : ''}
          </span>
        ) : <span />}
      </div>
      <div className={styles.bar}>
        <div className={styles.barFill} style={{ width: `${pct}%` }} />
      </div>
    </>
  );
}
```

`wide` defaults to `undefined` (falsy), so every existing call site — all 5 stock-mode `<Stage>` calls (lines 51-55) — keeps using `styles.stage` exactly as before, with zero visual change. Only the options-mode call sites touched in Step 3 below opt in.

- [ ] **Step 3: Update the four Options-mode labels and the options "Candidates" row**

In `frontend/components/organisms/ScanFunnel/index.tsx`, replace the options-mode block (lines 74-83):

```tsx
      <Stage label="Universe"        count={p.scanned}      total={p.scanned} />
      <Stage label="Data / Filters"  count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"  total={p.scanned} />
      <Stage label="Pre-screen"      count={afterPreScreen} rejected={p.failed_pre_screen} rejectedLabel="score low" total={p.scanned} />
      <Stage label="Option chain"    count={afterChain}     rejected={p.no_chain}          rejectedLabel="no chain"  total={p.scanned} />
      <Stage label="Score + contracts" count={afterChain - p.failed_score - p.failed_contracts} rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      <div className={styles.divider} />
      <div className={styles.finalStage}>
        <Text size={12} tone="pass" weight={500}>Candidates</Text>
        <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
      </div>
```

with:

```tsx
      <Stage wide label="Universe"        count={p.scanned}      total={p.scanned} />
      <Stage wide label="Data / Filters (data/price/cap)" count={afterData}      rejected={p.failed_data}       rejectedLabel="filtered"  total={p.scanned} />
      <Stage wide label="Pre-screen (setup score)"        count={afterPreScreen} rejected={p.failed_pre_screen} rejectedLabel="score low" total={p.scanned} />
      <Stage wide label="Option chain (DTE window)"       count={afterChain}     rejected={p.no_chain}          rejectedLabel="no chain"  total={p.scanned} />
      <Stage wide label="Score + contracts (final + rules)" count={afterChain - p.failed_score - p.failed_contracts} rejected={p.failed_score + p.failed_contracts} rejectedLabel="rejected" total={p.scanned} />
      <div className={styles.divider} />
      <div className={styles.finalStageWide}>
        <Text size={12} tone="pass" weight={500}>Candidates</Text>
        <Data size={13} weight={500} tone="pass">{p.candidates}</Data>
      </div>
```

Note "Universe" also gets `wide` (with its label text unchanged) purely so its row's grid column matches the other four rows below it in the same funnel — without it, "Universe" would stay at 110px while its neighbors sit at 190px, misaligning the count/bar columns across rows.

- [ ] **Step 4: Visual check — both funnels**

Start the frontend dev server if not already running. Check TWO things, not just one:
1. Open the screener at the Options Pipeline view and confirm the five labels render on one line each (or, worst case, wrap cleanly to two lines without clipping) at the new 190px column. If any label still wraps awkwardly, shorten that specific label further rather than widening the column again (a much wider column starts crowding the count/rejected columns next to it).
2. Switch to Stocks mode and confirm the Stock Pipeline funnel (Universe/History/Score gate/Signal/Backtest/Candidates) looks IDENTICAL to before this change — this is the regression check for the round-3-caught shared-CSS bug; if `.stage`/`.finalStage` were touched instead of adding new classes, this is where it would show up as unexplained extra whitespace.

Use the Browser tool: `preview_start` (or `navigate` if already running) → `screenshot` on both panels.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ScanFunnel/index.tsx frontend/components/organisms/ScanFunnel/ScanFunnel.module.css
git commit -m "docs(scan-funnel): add short stage explanations to Options Pipeline labels"
```

---

### Task 4: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend full suite**

Run: `"F:\Git\GitHub\Trading assistant\backend\venv\Scripts\python.exe" -m pytest -q` (from `backend/`) — expected: prior baseline count + 6 net-new tests (3 from Task 1, 3 from Task 2), 0 failed.

- [ ] **Step 2: Frontend typecheck + tests**

Run: `cd frontend && npm run typecheck` — expected clean. `npm run test -- --watchAll=false` — expected same pass count as baseline (label-only change, no new test files).

- [ ] **Step 3: No commit** (verification-only task)

---

## Self-review notes

- **Placeholder scan:** no TBD/TODO; every step has literal code or an exact command.
- **Scope check:** three independent, self-contained changes (two backend caches, one frontend label+CSS set), each committed separately — reviewable and revertable independently if one needs rework.
- **Round-1 adversarial audit (2026-08-15):** an independent subagent found: (1) Task 2's three new tests were not hermetic — `fetch_option_chain_async` unconditionally calls `fetch_iv_metrics_ibkr`/`fetch_iv_metrics_tastytrade`, and the plan's tests omitted the mocking the codebase's own sibling test already established for exactly this reason — fixed by adding the same two `patch()` calls to all three tests. (2) Task 1's stated "could mask a transient error" risk was overstated and left as an open question the plan itself could have resolved — fixed by confirming directly against `scan.py:554-560` that a `None` fundamentals-calendar result (fresh or cached) already falls through to an independent yfinance calendar fallback, so the cached-failure case changes nothing about data availability, only about whether Tradier gets retried same-day. (3) Task 3's bracket wording was checked against real code for accuracy but never checked against the real CSS, which fixes the label column at 110px with no truncation — the added text would have wrapped 2-3 lines on the two longest labels — fixed by widening the column to 190px (both `.stage` and `.finalStage`, so the "Candidates" row stays aligned) and shortening the wording to fit. (4) `scan.py`'s `_build_spreads` calls `fetch_option_chain_async` twice concurrently (put+call legs) for the same symbol, which can race past the Task 2 cache on a cache-cold symbol and issue two expirations calls instead of one — not fixed (would require a lock/coalescing mechanism for a single-pair edge case, out of proportion to this plan's scope), but now explicitly documented as a known gap in the relevant test's docstring rather than an implied guarantee the code doesn't keep. All four addressed (three fixed, one deliberately deferred with reason given).
- **Resolved, no longer open:** Task 1's failed-result caching is confirmed safe (see round-1 fix above). Task 2's asymmetric no-cache-on-empty-expirations choice was reviewed by the same audit round and not flagged — stands as reasoned in the task text.
- **Round-2 adversarial audit (2026-08-15):** a second, independent subagent re-verified all four round-1 fixes directly against the real files (not trusted on claim alone) and confirmed each one accurate. It then found four new issues: (1) Task 2's three new tests hard-coded absolute expiration dates (`"2026-09-19"`/`"2026-10-17"`) despite `test_market_data_fixes.py:24-26` explicitly documenting, with an existing `_FUTURE_EXPIRY` constant, that hard-coded dates eventually drift outside any `dte_bounds` window and silently break — fixed by switching all three tests to reuse `_FUTURE_EXPIRY`. (2) The CSS fix's "fits on one line at 190px" framing was asserted rather than demonstrated, and the auditor's own character-count math (94% more text, 73% more width) suggests it may not — fixed by softening the plan's framing to "probably close, not guaranteed" and confirming Step 3's manual check is load-bearing, not a formality. (3) The plan's Goal section cited `_company_cache` alongside `_candles_cache` as the "day-scoped" pattern being mirrored, but `_company_cache` is actually a *permanent*, non-expiring cache with no date logic — a factual inaccuracy in the justification text only, not the code — fixed by correcting the citation to `_candles_cache` alone. (4) The "Data / Filters" bracket label named only 2 of the 3 reasons in `_data_kw` ("no market data" was dropped) despite the plan claiming full grounding in that logic — fixed by adding it. All four fixed, none deferred.
- **Round-3 adversarial audit (2026-08-15):** a third, independent subagent re-verified all eight round-1/round-2 fixes directly against the live files (not trusted on claim alone) and confirmed all eight hold. It then found two substantive new issues and two minor ones. Substantive: (1) all four of the plan's `-k` pytest filter commands (`-k fundamentals_calendar_cache`, `-k expirations_cache`) were empirically run and confirmed to silently deselect 2 of every 3 new tests at each red/green checkpoint — fixed by widening the filters to `-k fundamentals_calendar` and `-k expirations` (verified these substrings are common to all 3 real test names in each group). (2) The CSS fix (as it stood after round 2) edited `.stage`/`.finalStage` directly — but those classes are shared by BOTH the options-mode AND stock-mode funnel branches in the same file, so widening them would have also restyled the Stock Pipeline funnel by 80px, contradicting this plan's own Non-goal of leaving Stock mode untouched, and the round-2 visual-check step only looked at the Options panel so this side effect would have shipped unnoticed — fixed by adding two new, non-shared classes (`.stageWide`, `.finalStageWide`), giving the `Stage` component an opt-in `wide` prop, applying it only to the 5 options-mode call sites, and expanding the visual-check step to explicitly verify the Stock funnel is unchanged. Minor: (3) a citation to `contract_rules.yaml` lines 5-11 for the hard-reject band was wrong (real location: lines 17-27) — fixed. (4) "kept under ~33 characters" was imprecise since the longest label is exactly 33 — reworded to "~33 characters at most." All four fixed, none deferred.
