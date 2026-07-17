# Deferred Audit Follow-Ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four items deferred out of (or discovered while auditing) the 2026-07-15 Critical-findings audit fix pass — each is the same bug class as a Critical fix that already landed on `main`, just in a different file that wasn't part of the original 11 findings.

**Architecture:** Four independent, surgical fixes — no shared files, no ordering dependency between them. Each mirrors a pattern already proven correct and shipped: Task 1 mirrors the confidence-cache fixes' key discipline (and must warm BOTH the options- and stocks-path key shapes, not just repoint to one), Task 2 is a one-line message-text fix parallel to the already-fixed backend direction logic it sits next to, Task 3 is a direct copy of the Step 3 hydration-sync effect onto a second store/page, Task 4 fixes a second, independent client-side re-implementation of the same direction-unaware stop/target logic Task 2 fixes on the backend — found while auditing this very plan, and more severe than Task 2 since it's the firing *condition* that's wrong, not just the message text.

**Tech Stack:** FastAPI + pytest (backend, Tasks 1–2); Next.js 15 + Zustand v5 + Jest (frontend, Tasks 3–4).

---

## Findings-to-tasks coverage map

| # | Finding | File:line | Task | Origin |
|---|---|---|---|---|
| 1 | Confidence prefetch (Load History) writes to a cache key the fixed stock-scan path can never read | `backend/app/services/historical_store.py:319,322,327-328` | Task 1 | Flagged during Task 3's code-quality review (2026-07-15 audit fix pass) |
| 2 | Backend STOP_REACHED alert text always says "below" even for a short position whose stop breaches on a price rise | `backend/app/services/alert_generator.py:119` | Task 2 | Flagged during Task 5's code-quality review |
| 3 | Step 5's strategy-params form seeds from a `skipHydration: true` store with no re-sync effect — same class as the Step 3 fix (Critical finding #8) | `frontend/app/(frame)/screener/step-5-strategy/page.tsx:130` | Task 3 | Flagged during Task 9's code-quality review |
| 4 | Client-side `alertEngine.ts` TP_HIT/STOP_REACHED conditions are hardcoded long-only — short positions' alerts never fire at all on this path (Dashboard/Portfolio, 30s poll) | `frontend/lib/alertEngine.ts:42,53,59` | Task 4 | Found during round-2 adversarial audit of this plan |

---

### Task 1: Confidence prefetch now writes to the correct cache key

**Files:**
- Modify: `backend/app/services/historical_store.py:319,322,327-328`
- Test: `backend/tests/test_historical_store.py` (check this file exists and its exact name first — see Step 1)

**Root cause:** `_run_prefetch()` computes confidence via `compute_confidence(bars, direction=_d, horizon=_h)` — no `atr_mult`/`scoring_mode`, so both default (`atr_mult=None`, `scoring_mode="options"`). It then caches the result under `conf_cache_key(symbol, _d, _h)` — also with no `atr_mult`/`scoring_mode`, so `cache_key`'s own defaults apply (`atr_mult=1.5`, `scoring_mode="options"`). The result: a prefetch-warmed entry is stored under the key `SYM|dir|horizon|1.5|options`. The live **stocks**-path scan (fixed in the 2026-07-15 audit pass) reads `SYM|dir|horizon|default|stock` (since `req.confidence_atr_mult` defaults to `None`, which keys as the literal string `"default"`, and the stocks path always passes `scoring_mode="stock"`) — these never intersect, so the prefetch is a permanent no-op for the stocks path.

**Important — do not simply repoint the prefetch to `scoring_mode="stock"`.** The live **options**-path (`routers/scan.py:446-447`) resolves its own key as `_atr_for_key = atr_mult if atr_mult is not None else 1.5` then `cache_key(symbol, direction, horizon, _atr_for_key)` with no `scoring_mode` (defaults `"options"`) — in the common case (no per-request override) this produces the *same* `SYM|dir|horizon|1.5|options` key the prefetch already writes today. That means the prefetch currently *does* warm the options path's cache, by construction. Naively changing every prefetch combo to `scoring_mode="stock", atr_mult=None` would silently regress that — the options path would lose its warm-cache hit while fixing the stocks path, trading one cold-start problem for another. The fix must prefetch **both** variants: the existing options-path shape (`atr_mult=1.5, scoring_mode="options"`) stays exactly as it is today, and a second, new stocks-path shape (`atr_mult=None, scoring_mode="stock"`) is added alongside it — doubling the combos per symbol from 6 to 12 (2 directions × 3 horizons × 2 scoring modes).

**Important — this is NOT actually a nightly background job; it's user-triggered and doubling its work has a visible cost.** `_run_prefetch` is only ever invoked from `POST /api/historical-data/prefetch` (`backend/app/routers/historical_data.py`), which is only ever called by the "Load History" button on Step 2 of the screener (`frontend/app/(frame)/screener/step-2-universe/page.tsx`'s `handleLoadHistory`) — the frontend then polls its progress on every tick into a visible progress bar. The confidence-prewarm loop inside it (`asyncio.gather` per symbol) is fully serial across symbols, so doubling the combos per symbol from 6 to 12 roughly doubles the wall-clock time of a "Load History" run for however many symbols are in scope (potentially the full SP500), directly in front of a user watching that progress bar — not overnight while nobody's looking. This is still the correct fix (a slower, correct warm-up beats a fast one that only ever warms half the app), but say so plainly in your final report to Kenneth rather than letting a "Load History" run that used to take, say, 90 seconds silently start taking ~3 minutes. If this turns out to matter in practice, the follow-up would be parallelizing across symbols (out of scope here) or a config flag to skip the prewarm — not reverting this fix.

- [ ] **Step 1: Find the right home for a regression test**

Run: `cd backend && grep -rln "historical_store\|_run_prefetch" tests/ | grep -v __pycache__`

Both `backend/tests/test_historical_store.py` and `backend/tests/test_historical_store_guard.py` already exist — read them first to confirm their fixture/mocking conventions (in particular, how any existing test already isolates `_run_prefetch` from real data sources and the real `confidence_cache.db`/`dev.db` files, if any test already does this) and add the new test to whichever one already covers prefetch behavior, matching its style.

- [ ] **Step 2: Write the failing test**

This test MUST be hermetic — `_run_prefetch` calls the real `get_bars(symbol, fetch_start, fetch_end)` (`historical_store.py:315`), which without mocking cascades through live Alpaca → Tiingo → yfinance network calls and reads/writes a real `AsyncSessionLocal()` session backed by `./dev.db` (per `backend/tests/conftest.py`'s `DATABASE_URL`, not an isolated in-memory DB). Mock `get_bars` directly — it's a plain module-level `async def` in `historical_store.py`, so `monkeypatch.setattr(hs, "get_bars", ...)` intercepts it cleanly. Also isolate the confidence cache from the real SQLite file the same way the fixed Task 3 test in the original audit pass did (`test_confidence_gate_stocks.py::test_custom_atr_mult_does_not_collide_with_default_cache_key` — swap `cc._DB_PATH` to a tempfile, restore in `finally`).

```python
def test_prefetch_warms_both_options_and_stock_cache_keys(monkeypatch):
    """The Load History prefetch job must warm BOTH the live options-path's cache key
    (atr_mult=1.5, scoring_mode='options' — the prefetch's pre-existing, correct
    behavior) AND the live stocks-path's cache key (atr_mult=None -> 'default'
    sentinel, scoring_mode='stock' — the bug this task fixes). Repointing the
    prefetch entirely to scoring_mode='stock' would silently regress the
    options path's warm-cache hit while fixing the stocks path — this test
    guards against that regression, not just the original bug."""
    import asyncio
    import tempfile
    import os
    import app.data.confidence_cache as cc
    from app.services import historical_store as hs
    from unittest.mock import AsyncMock

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original_db_path = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc.clear_cache()

        seen_kwargs = []

        def _fake_compute_confidence(bars, **kwargs):
            seen_kwargs.append(kwargs)
            return type("R", (), {"confidence": 55, "sample_size": 40})()

        fake_bars = [{"time": f"2024-01-{i:02d}", "close": 100.0 + i} for i in range(1, 200)]

        monkeypatch.setattr(hs, "compute_confidence", _fake_compute_confidence)
        monkeypatch.setattr(hs, "get_bars", AsyncMock(return_value=fake_bars))

        asyncio.run(hs._run_prefetch(["AAPL"], years=1, delay_secs=0))

        assert seen_kwargs, "compute_confidence was never called — check the monkeypatch target"
        stock_calls = [kw for kw in seen_kwargs if kw.get("scoring_mode") == "stock"]
        options_calls = [kw for kw in seen_kwargs if kw.get("scoring_mode") != "stock"]
        assert stock_calls, "prefetch never computed a scoring_mode='stock' variant"
        assert options_calls, "prefetch stopped computing the options-path variant — regression"

        # Both live paths' actual key shapes must be warmed.
        stock_key = cc.cache_key("AAPL", "Bullish", "Swing", None, scoring_mode="stock")
        options_key = cc.cache_key("AAPL", "Bullish", "Swing", 1.5, scoring_mode="options")
        assert cc.get_cached(stock_key) is not None, "stocks-path key was not warmed"
        assert cc.get_cached(options_key) is not None, "options-path key was not warmed (regression)"
    finally:
        cc._DB_PATH = original_db_path
        os.unlink(db_path)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/<file-from-step-1>::test_prefetch_warms_both_options_and_stock_cache_keys -v`

Expected: FAIL — `stock_calls` is empty (nothing computes with `scoring_mode="stock"` yet) and/or `stock_key`'s cache lookup returns `None`.

- [ ] **Step 4: Fix `_run_prefetch` to compute and cache both variants**

In `backend/app/services/historical_store.py`, read the current content around lines 316-345 first to confirm it matches, then change from:

```python
                if bars:
                    _combos = [
                        (conf_cache_key(symbol, _d, _h), _d, _h)
                        for _d in ("Bullish", "Bearish")
                        for _h in ("Intraday", "Swing", "Position")
                        if get_cached(conf_cache_key(symbol, _d, _h)) is None
                    ]
                    if _combos:
                        _conf_tasks = [
                            asyncio.to_thread(
                                compute_confidence, bars,
                                direction=_d, horizon=_h,
                            )
                            for _, _d, _h in _combos
                        ]
                        _conf_results = await asyncio.gather(
                            *_conf_tasks, return_exceptions=True
                        )
                        for (_ck, _d, _h), _res in zip(_combos, _conf_results):
                            if isinstance(_res, BaseException):
                                logger.debug(
                                    "prefetch: confidence pre-warm failed %s/%s/%s — %s",
                                    symbol, _d, _h, _res,
                                )
                            else:
                                set_cached(_ck, {
                                    "confidence": _res.confidence,
                                    "sample_size": _res.sample_size,
                                })
```

to:

```python
                if bars:
                    # Warm both live paths' actual cache-key shapes: the options
                    # path (routers/scan.py) reads atr_mult=1.5,scoring_mode=
                    # "options"; the stocks path (routers/stock_scan.py) reads
                    # atr_mult=None ("default" sentinel),scoring_mode="stock".
                    # These are genuinely different computations — repointing
                    # this loop entirely to one or the other silently stops
                    # warming the path left behind.
                    _variants = (
                        (None, "stock"),
                        (1.5, "options"),
                    )
                    _combos = [
                        (conf_cache_key(symbol, _d, _h, _mult, scoring_mode=_mode), _d, _h, _mult, _mode)
                        for _d in ("Bullish", "Bearish")
                        for _h in ("Intraday", "Swing", "Position")
                        for _mult, _mode in _variants
                        if get_cached(conf_cache_key(symbol, _d, _h, _mult, scoring_mode=_mode)) is None
                    ]
                    if _combos:
                        _conf_tasks = [
                            asyncio.to_thread(
                                compute_confidence, bars,
                                direction=_d, horizon=_h, atr_mult=_mult, scoring_mode=_mode,
                            )
                            for _, _d, _h, _mult, _mode in _combos
                        ]
                        _conf_results = await asyncio.gather(
                            *_conf_tasks, return_exceptions=True
                        )
                        for (_ck, _d, _h, _mult, _mode), _res in zip(_combos, _conf_results):
                            if isinstance(_res, BaseException):
                                logger.debug(
                                    "prefetch: confidence pre-warm failed %s/%s/%s/%s/%s — %s",
                                    symbol, _d, _h, _mult, _mode, _res,
                                )
                            else:
                                set_cached(_ck, {
                                    "confidence": _res.confidence,
                                    "sample_size": _res.sample_size,
                                })
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/<file-from-step-1>::test_prefetch_warms_both_options_and_stock_cache_keys -v`

Expected: PASS. Then run the broader confidence/historical-store test surface: `cd backend && pytest tests/test_confidence_cache.py tests/test_confidence_gate_stocks.py tests/test_confidence_gate.py tests/test_historical_store.py tests/test_historical_store_guard.py -v` — expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/historical_store.py backend/tests/<file-from-step-1>
git commit -m "fix: Load History confidence prefetch now writes to the key the stocks-scan path reads"
```

---

### Task 2: STOP_REACHED alert text is direction-aware

**Files:**
- Modify: `backend/app/services/alert_generator.py:119`
- Test: `backend/tests/test_alerts.py`

**Root cause:** The `STOP_REACHED` alert's message is hardcoded: `reason=f"Stop breached — {symbol} below ${pos.stop:.2f}"`. For a long position (`is_bearish=False`), the stop breaches when price falls below it — "below" is correct. For a short/Bearish position (fixed to actually fire in the 2026-07-15 audit pass, Critical finding #5), the stop breaches when price *rises above* it — the message still says "below", which is now reachable and misleading now that short-stock stops actually fire.

- [ ] **Step 1: Write the failing test**

`test_alerts.py` already has `_insert_position`/`db_session` and an existing `test_short_stock_stop_triggers_on_price_rise` test (added in the prior audit pass) that only checks the alert *fires*, not its message text. Add a new test right after it:

```python
@pytest.mark.asyncio
async def test_short_stock_stop_message_says_above_not_below(db_session):
    """A short (Bearish) position's STOP_REACHED message must say the price is
    above the stop, not below — the hardcoded 'below' text predates the fix
    that made short-stock stops actually fire (2026-07-15 audit pass)."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="XYZ", contract="XYZ|STOCK", direction="Bearish",
        stop=105.0, targets=[],
    )
    alerts = await generate_alerts(db_session, current_prices={"XYZ": 106.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert "above" in stop_alerts[0].reason
    assert "below" not in stop_alerts[0].reason


@pytest.mark.asyncio
async def test_long_stock_stop_message_still_says_below(db_session):
    """A long (Bullish) position's STOP_REACHED message must keep saying
    'below' — this is the pre-existing, correct behavior for longs."""
    from app.services.alert_generator import generate_alerts
    await _insert_position(
        db_session, symbol="ABC", contract="ABC|STOCK", direction="Bullish",
        stop=105.0, targets=[],
    )
    alerts = await generate_alerts(db_session, current_prices={"ABC": 104.0})
    stop_alerts = [a for a in alerts if a.alertType == "STOP_REACHED"]
    assert len(stop_alerts) == 1
    assert "below" in stop_alerts[0].reason
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `cd backend && pytest tests/test_alerts.py::test_short_stock_stop_message_says_above_not_below tests/test_alerts.py::test_long_stock_stop_message_still_says_below -v`

Expected: the short-stock test FAILs (`assert "above" in "Stop breached — XYZ below $105.00"` — false), the long-stock test PASSes already.

- [ ] **Step 3: Make the message direction-aware**

In `backend/app/services/alert_generator.py`, read the current content around line 119 first (it now sits inside a block using a `_sustained(...)` wrapper introduced by an unrelated feature — don't touch that wrapper, only the message string), then change:

```python
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} below ${pos.stop:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
            ))
```

to:

```python
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} {'above' if is_bearish else 'below'} ${pos.stop:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
            ))
```

(`is_bearish` is already computed a few lines earlier in the same function and used for the STOP_REACHED direction check itself — reuse it, don't recompute.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_alerts.py -v` — expected: all PASS (should be 11 total: the pre-existing 9 plus these 2 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/alert_generator.py backend/tests/test_alerts.py
git commit -m "fix: STOP_REACHED alert text now says above/below correctly for short positions"
```

---

### Task 3: Step 5's strategy-params form no longer risks stale-default hydration race

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx:130`
- Test: manual verification via a running dev server — same rationale as the Step 3 fix (this store's rehydration timing can't be reliably unit-tested against Jest's DOM/localStorage shim without reproducing the exact async timing bug itself).

**Root cause:** `const [params, setParams] = useState(() => ({ ...savedParams }));` (line 130) seeds local form state once, at mount, from `savedParams` — a `useShallow` selector over `useScanParamsStore` (lines 100-117). That store has `skipHydration: true` (`frontend/lib/scanParamsStore.ts:72`) and is rehydrated asynchronously by the shared `StoreHydration` component, exactly like `useScanStore` was before the Step 3 fix (Critical finding #8, 2026-07-15 audit). If this page mounts before `useScanParamsStore` finishes rehydrating, `params` captures the store's hardcoded module defaults instead of the user's saved strategy params (pullback tolerance, EMA periods, RSI thresholds, backtest gate thresholds, etc.). Those stale defaults then flow straight into `api.postStockScan(...)` on `runScan()` (line 174+), silently running — and, via `StrategyParamsPanel`'s `setParams` calls, potentially persisting — a scan with the wrong parameters instead of the user's saved ones.

- [ ] **Step 1: Add a one-time hydration-sync effect**

In `frontend/app/(frame)/screener/step-5-strategy/page.tsx`, read the current file first to confirm the `useState` block still looks as described (line 130, right after the `savedParams`/`scanOverrides`/`requireReversal`/mean-reversion-variant hooks), then add this right after the `resetParams` function definition (line 132) and before the `strategyLabel` block.

`params` is a shallow-selected subset of ~16 fields (see the `useShallow` selector at lines 100-117), not the full store — reconstruct the exact same shape that selector builds, reusing its field list verbatim, rather than spreading `useScanParamsStore.getState()`'s full state (which also carries setters/actions `params` was never typed to have):

```typescript
  // If this page mounts before useScanParamsStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializer above captures the store's hardcoded module defaults instead
  // of the persisted savedParams. Sync local state once hydration actually
  // finishes, so a scan run shortly after a fresh load doesn't silently use
  // stale defaults instead of the user's saved strategy params (same class of
  // bug as the Step 3 fix, Critical finding #8, 2026-07-15 audit).
  useEffect(() => {
    const syncFromHydratedStore = () => {
      const s = useScanParamsStore.getState();
      setParams({
        pullbackTolerancePct: s.pullbackTolerancePct,
        pullbackEmaPeriod:    s.pullbackEmaPeriod,
        pullbackTrendEma:     s.pullbackTrendEma,
        pullbackMaType:       s.pullbackMaType,
        maCrossoverFast:      s.maCrossoverFast,
        maCrossoverSlow:      s.maCrossoverSlow,
        maCrossoverLookback:  s.maCrossoverLookback,
        breakoutVolumeMult:   s.breakoutVolumeMult,
        rsiPeriod:            s.rsiPeriod,
        rsiOversold:          s.rsiOversold,
        rsiTrendSma:          s.rsiTrendSma,
        requireChoppyRegime:  s.requireChoppyRegime ?? false,
        btMinTrades:          s.btMinTrades,
        btMinWinRate:         s.btMinWinRate,
        eventFilter:          s.eventFilter,
        stockShortlistMax:    s.stockShortlistMax,
      });
    };
    if (useScanParamsStore.persist.hasHydrated()) syncFromHydratedStore();
    const unsub = useScanParamsStore.persist.onFinishHydration(syncFromHydratedStore);
    return unsub;
  }, []);
```

- [ ] **Step 2: Confirm `useEffect` is already imported**

Run: `grep -n "^import.*useEffect\|useEffect," "frontend/app/(frame)/screener/step-5-strategy/page.tsx" | head -3`

If not present, add it to the existing React import line.

- [ ] **Step 3: Manual verification via a running dev server**

Start the frontend dev server and use a browser automation tool (or a static trace if none is available — state that limitation clearly rather than skipping verification silently):

1. Navigate through the screener to Step 5 (Stocks mode).
2. Change a strategy param (e.g. pullback tolerance) to a non-default value; let it persist to the store (however this page's existing save/apply flow works — check `StrategyParamsPanel`'s `onChange`/`onApply` wiring first).
3. Navigate away, then do a full page reload directly on the Step 5 URL (not client-side navigation) to force the pre-hydration mount race.
4. Confirm the params form immediately shows the saved non-default value, not the module defaults.
5. **Regression check**: without touching any control, trigger `runScan` (or inspect the request payload some other way) immediately after the fresh load and confirm it uses the saved value, not a default — this is the actual bug (a stale-default *scan*, not just a stale-default *display*).

- [ ] **Step 4: Run the frontend test suite and typecheck**

Run: `cd frontend && npm run typecheck` — expected: clean. Run: `cd frontend && npm run test` — expected: no new failures (no dedicated test file exists for this page, matching the Step 3 fix's precedent).

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-5-strategy/page.tsx"
git commit -m "fix: Step 5 strategy params no longer risk a stale-default hydration race"
```

---

### Task 4: alertEngine.ts's client-side TP_HIT/STOP_REACHED are direction-unaware — a functional bug, not just text

**Files:**
- Modify: `frontend/lib/alertEngine.ts`
- Test: `frontend/lib/__tests__/alertEngine.test.ts`

**Root cause:** `scanPortfolio()` is a second, independent, client-side re-implementation of the stop/target alert logic that `alert_generator.py` implements on the backend. Its `TP_HIT` check (`p.currentPrice >= firstTarget.stockPrice`) and `STOP_REACHED` check (`p.currentPrice <= p.stop`) are hardcoded long-only, with no direction awareness at all — `AlertPosition` doesn't even carry a `direction` field. This is more severe than Task 2: Task 2 only fixes backend *message text* (the backend's firing *condition* was already corrected in the original Critical finding #5 fix). Here, the firing condition itself is wrong — a Bearish/short position's stop (which should breach on a price **rise**) and target (which should hit on a price **fall**) never fire at all through this path. `scanPortfolio` is wired into both `frontend/app/(frame)/dashboard/page.tsx` (a 30-second poll, line ~91 and again at line ~133) and `frontend/app/(frame)/portfolio/page.tsx` (line ~87), pushing live toast alerts — this is an actively-used, user-facing path, not dead code.

The `positions`/`portfolio` arrays passed into `scanPortfolio` at all three call sites are already-typed domain objects that already carry `direction: Direction` (`'Bullish' | 'Bearish'` — confirmed in `frontend/types/domain.ts`), so adding a required `direction` field to `AlertPosition` requires **zero call-site changes** — TypeScript's structural typing means the existing objects already satisfy the wider interface.

- [ ] **Step 1: Write the failing tests**

Read `frontend/lib/__tests__/alertEngine.test.ts` first to confirm its `makePosition(overrides)` helper and existing test style. Add `direction: 'Bullish'` to `makePosition`'s default object (so existing tests, which all assume long positions, keep passing unchanged), then add:

```typescript
  it('fires STOP_REACHED for a Bearish position when price rises above stop, not below', () => {
    const short = makePosition({ direction: 'Bearish', stop: 95, currentPrice: 100 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(true);
  });

  it('does NOT fire STOP_REACHED for a Bearish position when price falls below stop', () => {
    const short = makePosition({ direction: 'Bearish', stop: 95, currentPrice: 90 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });

  it('fires TP_HIT for a Bearish position when price falls to target, not rises', () => {
    const short = makePosition({
      direction: 'Bearish', currentPrice: 80,
      targets: [{ id: 't1', stockPrice: 85, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(true);
  });

  it('does NOT fire TP_HIT for a Bearish position when price rises toward target', () => {
    const short = makePosition({
      direction: 'Bearish', currentPrice: 120,
      targets: [{ id: 't1', stockPrice: 85, contractsToSell: 1, status: 'PENDING' }],
    });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'TP_HIT')).toBe(false);
  });

  it('does NOT fire STOP_REACHED for a Bearish position with no stop set (stop=0)', () => {
    // portfolioStore.ts coerces a null backend stop to 0 before it reaches
    // AlertPosition — without a guard, a Bearish position with no stop would
    // satisfy currentPrice >= 0 on virtually every poll, firing a spurious
    // Critical alert continuously (found during round-3 audit of this plan).
    const short = makePosition({ direction: 'Bearish', stop: 0, currentPrice: 150 });
    const out = scanPortfolio([short]);
    expect(out.some((a) => a.alertType === 'STOP_REACHED')).toBe(false);
  });
```

Check `TargetLevel`'s exact shape in `frontend/types/domain.ts` before finalizing the `targets` object literals above — match its real required fields exactly (the plan's guess above may not have every field right).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- --testPathPattern=alertEngine`

**Expected: this step does not produce individual runtime pass/fail results at all — it fails to compile.** `frontend/jest.config.ts` uses `ts-jest`, which type-checks before running. Step 1's fixtures pass `direction: 'Bearish'` into `makePosition(overrides: Partial<AlertPosition>)`, but `AlertPosition` doesn't gain a `direction` field until Step 3 — so every new test object literal is an excess-property error against `Partial<AlertPosition>` (TS2353), and the whole suite reports `Test suite failed to run`, not a per-test pass/fail breakdown. **This is still the correct "red" state for this step** — TDD's failing-test checkpoint expressed as a compile error instead of a runtime assertion failure, which is normal in a typed codebase when a test references a field that doesn't exist yet. Don't troubleshoot or work around the compile error here — proceed straight to Step 3, which adds the field and the direction-aware logic together, making the whole file compile and all 8 tests pass in one move. (Step 3 as written bundles the interface change and the logic fix into a single edit, so there is no separate intermediate point where the file compiles but the tests are still runtime-red — if you want to see that intermediate state for your own confidence, you can add just the `direction` field to the interface first, confirm 4 fail / 1 passes, then apply the logic change and confirm all 8 pass; this is optional extra rigor, not a required step.)

- [ ] **Step 3: Add `direction` to `AlertPosition` and make both checks direction-aware**

In `frontend/lib/alertEngine.ts`, read the current file first to confirm it matches, then:

Add the import and field:

```typescript
import type { AlertKind, AlertType, TargetLevel, Direction } from '@/types/domain';

export interface AlertPosition {
  recId: string;
  symbol: string;
  contract: string;
  currentPrice: number;
  entryPrice: number;
  stop: number;
  targets: TargetLevel[];
  dteRemaining: number;
  dteTotal: number;
  pnlPct: number;
  direction: Direction;
  nextEventDays?: number;
  nextEventLabel?: string;
}
```

Then change the TP_HIT and STOP_REACHED blocks from:

```typescript
  for (const p of positions) {
    // TP_HIT
    const firstTarget = p.targets[0];
    if (firstTarget && p.currentPrice >= firstTarget.stockPrice) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
      });
    }

    // STOP_REACHED
    if (p.currentPrice <= p.stop) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} below $${p.stop.toFixed(2)}`,
      });
    }
```

to:

```typescript
  for (const p of positions) {
    const isBearish = p.direction === 'Bearish';

    // TP_HIT — direction-aware: bullish targets are above current price, bearish below
    const firstTarget = p.targets[0];
    const tpHit = firstTarget
      ? (isBearish ? p.currentPrice <= firstTarget.stockPrice : p.currentPrice >= firstTarget.stockPrice)
      : false;
    if (tpHit) {
      out.push({
        recId: p.recId,
        kind: 'Action',
        symbol: p.symbol,
        alertType: 'TP_HIT',
        reason: `Target reached — ${p.symbol} at $${p.currentPrice.toFixed(2)}`,
      });
    }

    // STOP_REACHED — direction-aware: puts/shorts are invalidated when price rises above stop.
    // `p.stop > 0` guards positions with no stop set: portfolioStore.ts:47 coerces a
    // null backend stop to 0 before it reaches this function (AlertPosition.stop is
    // non-optional), so the null/unset case is invisible here — without this guard,
    // a Bearish position with no stop would satisfy `currentPrice >= 0` on virtually
    // every poll (any real stock price is positive), firing a spurious Critical alert
    // every 30 seconds. The backend's equivalent check (alert_generator.py:109-112)
    // guards this explicitly via `pos.stop is not None`; `stop > 0` is this function's
    // only available proxy for the same condition since the null information is
    // already lost by the time data reaches here. (Bullish positions were already
    // safe from this by coincidence — currentPrice <= 0 is never true for a real
    // price — this guard makes that safety explicit for both directions instead of
    // relying on it remaining a coincidence.)
    const stopBreached = p.stop > 0 && (isBearish ? p.currentPrice >= p.stop : p.currentPrice <= p.stop);
    if (stopBreached) {
      out.push({
        recId: p.recId,
        kind: 'Critical',
        symbol: p.symbol,
        alertType: 'STOP_REACHED',
        reason: `Stop breached — ${p.symbol} ${isBearish ? 'above' : 'below'} $${p.stop.toFixed(2)}`,
      });
    }
```

Leave `PREMIUM_STOP`, `TIME_STOP`, and `EVENT_RISK` untouched — none of them are direction-dependent.

- [ ] **Step 4: Run tests and typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=alertEngine` — expected: all PASS (3 pre-existing + 5 new = 8 total). Run: `cd frontend && npm run typecheck` — expected: clean (confirms the structural-typing claim that no call site needs to change).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/alertEngine.ts frontend/lib/__tests__/alertEngine.test.ts
git commit -m "fix: alertEngine TP_HIT/STOP_REACHED now fire correctly for short positions"
```

---

## Final verification (after all 4 tasks)

- [ ] **Backend suite:** `cd backend && pytest -q --ignore=tests/test_tastytrade_iv.py --ignore=tests/test_tastytrade_paper.py --ignore=tests/test_tastytrade_session.py` — expect no new failures beyond the pre-existing, unrelated tastytrade-package-missing ones.
- [ ] **Frontend suite + typecheck:** `cd frontend && npm run typecheck && npm run test` — expect clean.
- [ ] **Manual Step 5 hydration-race check** (Task 3, Step 3) — do not skip; no automated regression coverage exists for this by design, same as the Step 3 precedent it mirrors.
- [ ] **Report the Load History duration cost to Kenneth** (Task 1) — don't let the ~2x-slower "Load History" run be a silent surprise; mention it explicitly when reporting this plan complete.
