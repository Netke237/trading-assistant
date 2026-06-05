# Scan Parameters Panel, Performance Fixes & Vol Rule — Design Spec

**Date:** 2026-06-05
**Status:** Approved — ready for implementation planning

---

## Problem Summary

Three independent problems in the stock scan pipeline:

1. **No user control over scan rejection thresholds.** Strategy signal tolerances and backtest gate thresholds are hardcoded. Users cannot tune them without editing source code, making the scan inflexible when market conditions change.

2. **Scan takes 27 minutes for 519 symbols.** Root causes (ranked):
   - Tiingo re-fetches delta history on every run even when local DB data is current (3–10 min).
   - `compute_confidence` is O(n²) and cold-starts on every server restart (8–15 min).
   - 519 individual Tradier price HTTP calls instead of one batch request (0.5–2 min).

3. **Vol rule silently penalises every stock scan.** `_rule_vol` in `stock_scorer.py` returns CAUTION 50 for Swing and Position horizons when `iv_rank=None` — which is always the case in the stock scan path. This deflates scores and increases rejection rate without any signal from the user.

---

## Goals

- Expose 5 scan parameters as user-editable controls (Settings defaults + Step 5 per-scan override).
- Fix the three most impactful performance bottlenecks without rewriting the backtest engine.
- Stop the vol rule from penalising stock scans.

## Non-Goals

- Rewriting `run_strategy_backtest` to replace `backtesting.py` (deferred — high complexity).
- Increasing `_SCAN_SEM` limit or restructuring semaphore scope (deferred).
- Exposing `min_cap_usd` / `max_cap_usd` in the UI (dead schema fields — remove or leave).

---

## Architecture

### Section A — Scan Parameters Panel

#### A1. Backend schema (`backend/app/schemas/stock_scan.py`)

Add five optional fields to `StockScanRequest` with defaults matching current hardcoded values:

```python
pullback_tolerance_pct: float = 0.04      # was hardcoded 0.04 in strategy_engine.py
ma_crossover_lookback:  int   = 10        # was hardcoded range(-10, 0)
breakout_volume_mult:   float = 1.1       # was hardcoded 1.1 default param
bt_min_trades:          int   = 10        # already existed; now surfaced
bt_min_win_rate:        float = 0.45      # already existed; now surfaced
```

`bt_min_trades` and `bt_min_win_rate` already exist in the schema; their defaults are unchanged. Only the three strategy tolerance fields are new.

#### A2. Backend router (`backend/app/routers/stock_scan.py`)

Add a `_SIGNAL_KWARGS` dispatch table alongside the existing `_SIGNAL_FNS` table. Each entry is a lambda that extracts the relevant kwargs from the request:

```python
_SIGNAL_KWARGS: dict[str, Callable[[StockScanRequest], dict]] = {
    "pullback_ema":       lambda r: {"tolerance":   r.pullback_tolerance_pct},
    "breakout_base":      lambda r: {"volume_mult": r.breakout_volume_mult},
    "ma_crossover":       lambda r: {"lookback":    r.ma_crossover_lookback},
    "mean_reversion_rsi": lambda r: {},
}
```

Inside `_process_stock`, replace the bare `signal_fn(bars[-120:])` call with:

```python
signal_kwargs = _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req)
signal = signal_fn(bars[-120:], **signal_kwargs)
```

Also add `price_map: dict[str, float]` as a new parameter to `_process_stock` and remove the `fetch_price_async` call (see B3 below).

#### A3. Strategy engine (`backend/app/services/strategy_engine.py`)

Two signature changes required (one function already has its parameter):

- `pullback_ema_signal`: add `tolerance: float = 0.04` keyword parameter; replace the hardcoded `0.04` literal at line 115 with `tolerance`.
- `ma_crossover_signal`: add `lookback: int = 10` keyword parameter; replace `range(-10, 0)` with `range(-lookback, 0)`.
- `breakout_base_signal`: already has `volume_mult: float = 1.1` as a parameter — no signature change needed.

#### A4. Zustand store (`frontend/lib/scanParamsStore.ts`) — new file

```ts
interface ScanParams {
  pullbackTolerancePct: number;   // 0.04
  maCrossoverLookback:  number;   // 10
  breakoutVolumeMult:   number;   // 1.1
  btMinTrades:          number;   // 10
  btMinWinRate:         number;   // 0.45
}
```

Persisted to `localStorage` under key `bamendjou:scan-params`, version 1. Exported as `useScanParamsStore`. Provides `setParam(key, value)` and `resetToDefaults()` actions.

#### A5. Settings page — new "Strategy scan" section

Location: `frontend/app/(frame)/screener/settings/` — add under the "Score weights & parameters" tab, below the existing horizon strip.

Layout: a labelled row per parameter with a numeric input. Labels and value ranges:

| Label | Key | Min | Max | Step | Unit |
|---|---|---|---|---|---|
| Pullback tolerance | `pullbackTolerancePct` | 0.5 | 15 | 0.5 | % |
| MA crossover lookback | `maCrossoverLookback` | 1 | 30 | 1 | bars |
| Breakout volume mult | `breakoutVolumeMult` | 1.0 | 3.0 | 0.05 | × |
| Min backtest trades | `btMinTrades` | 1 | 50 | 1 | trades |
| Min win rate | `btMinWinRate` | 10 | 80 | 5 | % |

Each input is an `<input type="number">` styled with existing CSS tokens. No new design system components needed.

#### A6. Step 5 page — collapsible override panel

Add a `<details>` / `<summary>` collapsible section labelled "⚙ Scan parameters" above the strategy grid. Pre-fills from `useScanParamsStore`. Values held in local `useState` — not written back to the store. Includes a "Reset to saved" button that resets local state back to the values currently in the store (i.e., the user's saved Settings defaults, not the hardcoded system defaults).

The 5 values are passed into `api.postStockScan()` at call time.

---

### Section B — Performance Fixes

#### B1. Skip Tiingo delta fetch when data is current (`backend/app/services/historical_store.py`)

Add a `most_recent_trading_day() -> date` helper:

```python
def most_recent_trading_day() -> date:
    """Returns the most recent US market close date (Mon–Fri, no holiday check)."""
    today = date.today()
    # Simple: if today is Saturday return Friday, if Sunday return Friday, else today.
    # A full holiday calendar is overkill for this use case.
    weekday = today.weekday()  # 0=Mon … 6=Sun
    if weekday == 5:   return today - timedelta(days=1)
    if weekday == 6:   return today - timedelta(days=2)
    return today
```

In `get_bars()`, the actual stale-check condition is:

```python
fetch_needed = (last is None) or (last < end)
```

where `end` is the caller-supplied end date (typically `date.today()`). Change the `last < end` branch to compare against `most_recent_trading_day()` instead:

```python
fetch_needed = (last is None) or (last < most_recent_trading_day())
```

This eliminates Tiingo delta fetches on non-first runs after the trading session closes.

**Constraint:** Does not require a full holiday calendar. During live market hours the fetch will still fire (correct behaviour — data may be updating). On weekends and after close it is skipped.

#### B2. Persist confidence cache across server restarts (`backend/app/data/confidence_cache.py` + new `confidence_cache_db.py`)

Current behaviour: in-memory dict with 7-day TTL. Clears on every server restart → cold start for all symbols.

Change:
- Open a **dedicated SQLite file** (`backend/data/confidence_cache.db`) using Python's stdlib `sqlite3` module directly — `historical_store.py` uses SQLAlchemy async sessions and does not expose a raw connection, so sharing it would be complex. A separate lightweight file is simpler and has no dependency on SQLAlchemy.
- Create `confidence_cache` table on first open: columns `cache_key TEXT PRIMARY KEY`, `value TEXT` (JSON), `expires_at REAL` (Unix timestamp).
- `get_cached(key)`: check in-memory dict first (L1), then `sqlite3` DB (L2). On L2 hit, populate L1.
- `set_cached(key, value)`: write to both L1 and L2 via `sqlite3`.
- On module import, load all non-expired rows from the DB into L1 (warm start).

Schema:

```sql
CREATE TABLE IF NOT EXISTS confidence_cache (
    cache_key  TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at REAL NOT NULL
);
```

TTL remains 7 days. No change to the `cache_key` format or the calling code in `stock_scan.py`.

#### B3. Batch Tradier price fetch (`backend/app/routers/stock_scan.py`)

Before spawning per-symbol tasks, pre-fetch all prices in one call:

```python
# Before the task list — fetch_quotes is synchronous; wrap in asyncio.to_thread
price_map: dict[str, float] = await asyncio.to_thread(fetch_quotes, symbols)

# _process_stock receives price_map directly — no per-symbol price fetch
async def _process_stock(symbol, req, scan_id, price_map): ...
    price = price_map.get(symbol)
```

`fetch_quotes(symbols)` already exists in `backend/app/data/market.py` as a **synchronous** function that calls Tradier's batch quotes endpoint and returns `dict[str, float]`. Wrap it in `asyncio.to_thread` for non-blocking use. Remove the `fetch_price_async` call from inside `_process_stock`.

**Edge case:** If a symbol is missing from `price_map` (Tradier returned no quote), return `{"symbol": symbol, "reason": "no price data"}` — same as the current `if not price:` check.

Company name fetches remain per-symbol (cached after first run, negligible cost).

---

### Section C — Vol Rule Fix

**File:** `backend/config/scoring_rules.yaml`

For Swing and Position horizons, find the `vol` rule block and set `iv_rank_pass_max: null` (same as the current Intraday config). When `iv_rank` is `None`, `_rule_vol` returns PASS 90 instead of CAUTION 50.

This is a two-line YAML change (one for Swing, one for Position). No Python changes required.

**Verification:** After the change, a stock scan on Swing horizon with no IV data should show the vol rule contributing PASS 90 to the composite score rather than CAUTION 50.

---

## Data Flow

```
User sets params in Settings → scanParamsStore (localStorage)
          ↓
Step 5 page loads store values → pre-fills override panel
          ↓
User clicks strategy → runScan() reads panel values
          ↓
api.postStockScan({ symbols, strategy, pullback_tolerance_pct, ... })
          ↓
POST /api/stock-scan → StockScanRequest (all 5 params present)
          ↓
run_stock_scan():
  fetch_quotes(symbols) → price_map (1 HTTP call)
  [per symbol, semaphore=5]:
    most_recent_trading_day() guard → skip Tiingo if current
    score_stock() → vol rule now PASS when iv_rank=None
    signal_fn(bars, tolerance=req.pullback_tolerance_pct, ...)
    run_strategy_backtest(bt_min_trades=req.bt_min_trades, ...)
    compute_confidence() → L1 cache → L2 SQLite cache
```

---

## Error Handling

- **B1 (trading day):** If `most_recent_trading_day()` returns wrong date due to holiday, worst case is one extra Tiingo call — safe.
- **B2 (cache DB):** Wrap all SQLite cache operations in try/except; fall through to live compute on any DB error. Never block a scan on a cache failure.
- **B3 (batch price):** If `fetch_quotes` throws, fall back to per-symbol `fetch_price_async` calls (existing behaviour). Log a warning.

---

## Testing

- **A (params):** Unit tests — verify `StockScanRequest` accepts all 5 new fields; verify `pullback_ema_signal(bars, tolerance=0.06)` respects the passed value.
- **B1 (trading day):** Unit test `most_recent_trading_day()` for Mon–Sun inputs. Integration: confirm no Tiingo call when last stored date equals output.
- **B2 (cache):** Unit test `get_cached` L1→L2 fallback; verify rows persist after simulated restart (new in-memory state reading from DB).
- **B3 (batch price):** Mock `fetch_quotes` return; verify `_process_stock` uses `price_map` not live call; verify fallback on missing symbol.
- **C (vol rule):** Run `score_stock(symbol, direction='Bullish', horizon='Swing', bars=...)` without `iv_rank` and assert vol rule returns PASS 90.

---

## File Map

| File | Change |
|---|---|
| `backend/app/schemas/stock_scan.py` | Add 3 new optional fields |
| `backend/app/services/strategy_engine.py` | Add `tolerance` and `lookback` params to signal functions |
| `backend/app/routers/stock_scan.py` | Pass new fields to signal fns; batch price pre-fetch |
| `backend/app/services/historical_store.py` | Add `most_recent_trading_day()`; fix stale-check condition |
| `backend/app/data/confidence_cache.py` | Add SQLite L2 layer to `get_cached` / `set_cached` |
| `backend/config/scoring_rules.yaml` | Set `iv_rank_pass_max: null` for Swing + Position vol rule |
| `frontend/lib/scanParamsStore.ts` | New Zustand store, persisted |
| `frontend/app/(frame)/screener/settings/...` | Add Strategy scan parameter rows |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | Add collapsible override panel; wire params to postStockScan |
| `backend/tests/test_scan_params.py` | New — schema + signal function tests |
| `backend/tests/test_confidence_cache.py` | New — L1/L2 cache tests |
| `backend/tests/test_historical_store.py` | New/extend — trading day guard tests |
