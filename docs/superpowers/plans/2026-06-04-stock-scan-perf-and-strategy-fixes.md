# Stock Scan Performance & Strategy Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four problems in the stocks screener: no-concurrency-limit causing 27-minute scans, strategy signals so strict they return 0 matches, strategy scan running on all 519 symbols instead of the 8 Step-4 candidates, and no way to pre-warm historical data from the UI.

**Architecture:** Four independent fixes applied in dependency order — (1) semaphore in backend keeps Tiingo/Tradier within rate limits; (2) relaxed strategy tolerances give realistic signal rates; (3) schema + router + frontend change narrows the strategy scan to only the candidates Step 4 already ranked; (4) a prefetch button in the Step 5 page lets the user pre-warm the historical DB before the first scan so cold-start fetches don't block.

**Tech Stack:** FastAPI (Python 3.11), Pydantic v2, pytest; Next.js 15 App Router, TypeScript 5.7, Zustand v5.

---

## File Map

| File | Change |
|---|---|
| `backend/app/routers/stock_scan.py` | Add module-level `_SCAN_SEM = asyncio.Semaphore(5)`; wrap `_process_stock` body |
| `backend/app/services/strategy_engine.py` | Relax three tolerance parameters |
| `backend/app/schemas/stock_scan.py` | Add `symbols: Optional[list[str]] = None` to `StockScanRequest` |
| `backend/app/routers/stock_scan.py` | Prefer `req.symbols` over `expand_universe` when provided |
| `backend/tests/test_strategy_engine.py` | Add deterministic tests for relaxed conditions |
| `frontend/lib/api.ts` | Add `symbols?` to `postStockScan`; add `prefetchHistory` + `getPrefetchStatus` |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | Read Step 4 candidates, pass as `symbols`; add prefetch button + status |

---

## Task 1 — Add concurrency semaphore to `/stock-scan`

**Problem:** `stock_scan.py:142` fires `asyncio.gather(*tasks)` with no limit — 519 simultaneous Tiingo HTTP calls, 519 simultaneous `asyncio.to_thread(run_strategy_backtest)` threads. Hits Tiingo rate limit immediately, exhausts Python's thread pool.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`

- [ ] **Step 1.1: Add the semaphore constant**

In `backend/app/routers/stock_scan.py`, after line 34 (`_HISTORY_YEARS = 5`), add:

```python
_SCAN_SEM = asyncio.Semaphore(5)
```

- [ ] **Step 1.2: Wrap `_process_stock` with the semaphore**

Replace the current `_process_stock` signature + first line of the `try` block. The full function becomes:

```python
async def _process_stock(symbol: str, req: StockScanRequest, scan_id: str) -> PositionCardOut | dict:
    async with _SCAN_SEM:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                price, company = await asyncio.gather(
                    fetch_price_async(client, symbol),
                    fetch_company_name_async(client, symbol),
                )
            if not price:
                return {"symbol": symbol, "reason": "no price data"}
            if req.min_price is not None and price < req.min_price:
                return {"symbol": symbol, "reason": f"price ${price:.2f} < min"}
            if req.max_price is not None and price > req.max_price:
                return {"symbol": symbol, "reason": f"price ${price:.2f} > max"}

            end = date.today()
            start = end - timedelta(days=_HISTORY_YEARS * 365)
            bars = await get_historical_bars(symbol, start, end)
            if not bars or len(bars) < 60:
                return {"symbol": symbol, "reason": "insufficient history"}

            card = score_stock(symbol=symbol, direction=req.direction,
                               horizon=req.horizon, bars=bars[-120:])
            if card.status == "REJECT":
                return {"symbol": symbol, "reason": f"REJECT score={card.score}"}

            signal_fn = _SIGNAL_FNS.get(req.strategy)
            if not signal_fn:
                return {"symbol": symbol, "reason": f"unknown strategy {req.strategy}"}
            signal = signal_fn(bars[-120:])
            if signal is None:
                return {"symbol": symbol, "reason": f"no {req.strategy} setup"}

            bt_result = await asyncio.to_thread(
                run_strategy_backtest, bars,
                strategy=req.strategy, direction=req.direction,
                min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
            )
            if not bt_result.passes_gate:
                return {"symbol": symbol, "reason": f"backtest gate: {bt_result.summary_text}"}

            _ck = conf_cache_key(symbol, req.direction, req.horizon)
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
            conf_val = _cached["confidence"]
            conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol) if conf_val is not None else None

            shares, dollar_risk = _position_size(
                req.account_size, req.risk_pct, req.risk_fixed_usd,
                signal.entry_price, signal.stop_price,
            )

            return PositionCardOut(
                symbol=symbol, company=company or symbol, price=price, direction=req.direction,
                strategy=StrategySignalOut(
                    strategy=signal.strategy, entry_price=signal.entry_price,
                    stop_price=signal.stop_price, target_price=signal.target_price,
                    rr_ratio=round(signal.rr_ratio, 2), atr=signal.atr, detail=signal.detail,
                ),
                backtest=BacktestOut(
                    n_trades=bt_result.n_trades, win_rate=round(bt_result.win_rate, 3),
                    total_return_pct=round(bt_result.total_return_pct, 2),
                    max_drawdown_pct=round(bt_result.max_drawdown_pct, 2),
                    expectancy=bt_result.expectancy, sharpe=bt_result.sharpe,
                    confidence=bt_result.confidence, passes_gate=bt_result.passes_gate,
                    summary_text=bt_result.summary_text,
                ),
                stock_score=card.score, stock_status=card.status,
                shares=shares, dollar_risk=dollar_risk,
                dollar_size=round(shares * signal.entry_price, 2),
                confidence=conf_val, confidence_text=conf_txt,
            )
        except Exception as exc:
            logger.exception("Error processing %s", symbol)
            return {"symbol": symbol, "reason": str(exc)}
```

- [ ] **Step 1.3: Verify backend starts cleanly**

```bash
cd backend && python -m uvicorn app.main:app --port 8000 --reload
```

Expected: server starts, no import errors.

- [ ] **Step 1.4: Commit**

```bash
git add backend/app/routers/stock_scan.py
git commit -m "perf(stock-scan): limit concurrency to 5 with asyncio.Semaphore"
```

---

## Task 2 — Relax strategy signal tolerances

**Problem:** Each strategy uses conditions that must all be true on *today's single bar*. With current thresholds, almost no stock qualifies on any given day:
- `pullback_ema`: price must be within **1.5%** of 20-EMA (too tight)
- `ma_crossover`: 20-SMA must have crossed 50-SMA within **3 bars** (too recent)
- `breakout_base`: today's volume must be > **1.3×** 20-day avg (too strict)

**Files:**
- Modify: `backend/app/services/strategy_engine.py`
- Modify: `backend/tests/test_strategy_engine.py`

- [ ] **Step 2.1: Write failing tests for the new tolerances**

Append to `backend/tests/test_strategy_engine.py`:

```python
def _uptrend_with_pullback_pct(pct: float, n: int = 200) -> list[dict]:
    """Rising bars that end with a pullback of exactly `pct` above the 20-EMA."""
    # Build 180 bars of steady rise to establish the 50-SMA uptrend.
    bars = []
    price = 100.0
    for _ in range(n - 20):
        price += 0.5
        bars.append({"open": price - 0.1, "high": price + 0.3,
                     "low": price - 0.3, "close": price, "volume": 1_000})

    # Approximate EMA-20 at this point: last close ≈ price.
    # Pull back so that close is (1 + pct) * ema_approx.
    ema_approx = price  # close approximation
    pullback_price = ema_approx * (1 + pct)

    for _ in range(20):
        bars.append({"open": pullback_price - 0.1, "high": pullback_price + 0.2,
                     "low": pullback_price - 0.2, "close": pullback_price, "volume": 1_000})
    # Make the last bar a bullish candle.
    bars[-1]["close"] = bars[-1]["open"] + 0.3
    return bars


def test_pullback_ema_fires_at_2pct_above_ema():
    """2% above EMA is inside the new 4% tolerance — should fire."""
    bars = _uptrend_with_pullback_pct(0.02, n=200)
    signal = pullback_ema_signal(bars)
    assert signal is not None, "Expected a signal at 2% above EMA with 4% tolerance"
    assert signal.strategy == "pullback_ema"


def test_pullback_ema_still_rejects_at_5pct_above_ema():
    """5% above EMA is outside the new 4% tolerance — should return None."""
    bars = _uptrend_with_pullback_pct(0.05, n=200)
    signal = pullback_ema_signal(bars)
    assert signal is None, "Expected None at 5% above EMA (outside tolerance)"


def _crossover_bars(cross_bars_ago: int, n: int = 200) -> list[dict]:
    """Bars where 20-SMA crossed above 50-SMA exactly `cross_bars_ago` bars ago.

    Before the cross: close = 80 (fast below slow).
    At cross point: close jumps to 120 (fast leaps above slow).
    After: close = 120 + 0.1 * i (slight rise).
    """
    bars = []
    # Phase 1: 60 bars of low price so fast < slow
    for _ in range(60):
        bars.append({"open": 79.9, "high": 80.5, "low": 79.5, "close": 80.0, "volume": 1_000})
    # Phase 2: rise sharply over 10 bars to force fast above slow
    price = 80.0
    rise_bars = n - 60 - cross_bars_ago
    for i in range(rise_bars):
        price += 2.0
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 1_000})
    # Phase 3: flat continuation for `cross_bars_ago` bars
    for _ in range(cross_bars_ago):
        bars.append({"open": price - 0.1, "high": price + 0.2,
                     "low": price - 0.2, "close": price, "volume": 1_000})
    return bars


def test_ma_crossover_fires_within_10_bars():
    """Cross that happened 5 bars ago should fire with 10-bar lookback."""
    bars = _crossover_bars(cross_bars_ago=5, n=200)
    signal = ma_crossover_signal(bars)
    assert signal is not None, "Expected a signal when cross is 5 bars old with 10-bar lookback"
    assert signal.strategy == "ma_crossover"


def test_ma_crossover_still_rejects_at_12_bars():
    """Cross that happened 12 bars ago is outside the 10-bar window — should return None."""
    bars = _crossover_bars(cross_bars_ago=12, n=220)
    signal = ma_crossover_signal(bars)
    assert signal is None, "Expected None when cross is 12 bars old"
```

- [ ] **Step 2.2: Run the new tests and confirm they fail**

```bash
cd backend && pytest tests/test_strategy_engine.py::test_pullback_ema_fires_at_2pct_above_ema tests/test_strategy_engine.py::test_ma_crossover_fires_within_10_bars -v
```

Expected: FAIL (AssertionError — current tolerance 1.5% / 3-bar lookback too strict).

- [ ] **Step 2.3: Relax `pullback_ema` tolerance from 1.5% → 4%**

In `backend/app/services/strategy_engine.py`, change line 115:

```python
# Before:
    if not (0 <= (current - ema_val) / ema_val <= 0.015):

# After:
    if not (0 <= (current - ema_val) / ema_val <= 0.04):
```

- [ ] **Step 2.4: Relax `ma_crossover` lookback from 3 → 10 bars**

In `backend/app/services/strategy_engine.py`, change line 199:

```python
# Before:
    for i in range(-3, 0):

# After:
    for i in range(-10, 0):
```

- [ ] **Step 2.5: Relax `breakout_base` volume multiplier from 1.3 → 1.1**

In `backend/app/services/strategy_engine.py`, change the default parameter at line 143:

```python
# Before:
    volume_mult: float = 1.3,

# After:
    volume_mult: float = 1.1,
```

- [ ] **Step 2.6: Run all strategy engine tests**

```bash
cd backend && pytest tests/test_strategy_engine.py -v
```

Expected: all tests PASS. Pay attention to `test_pullback_ema_still_rejects_at_5pct_above_ema` and `test_ma_crossover_still_rejects_at_12_bars` — they must still be PASS (the tighter bound is still enforced).

- [ ] **Step 2.7: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_engine.py
git commit -m "feat(strategy): relax pullback_ema to 4%, ma_crossover to 10-bar, breakout volume to 1.1x"
```

---

## Task 3 — Backend schema: add optional `symbols` to `StockScanRequest`

**Problem:** `StockScanRequest` only accepts a `universe` preset name. There's no way to scan a specific list of tickers (the 8 from Step 4).

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`

- [ ] **Step 3.1: Add `symbols` field to the schema**

In `backend/app/schemas/stock_scan.py`, change `StockScanRequest` to:

```python
class StockScanRequest(BaseModel):
    universe:    list[str]
    symbols:     Optional[list[str]] = None   # ← new: when set, scan only these tickers
    direction:   Literal["Bullish", "Bearish"]
    horizon:     Literal["Intraday", "Swing", "Position"]
    strategy:    Strategy
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    account_size:       float = 50_000.0
    risk_pct:           Optional[float] = 0.01
    risk_fixed_usd:     Optional[float] = None
    bt_min_trades:      int   = 10
    bt_min_win_rate:    float = 0.45
```

- [ ] **Step 3.2: Verify schema parses correctly**

```bash
cd backend && python -c "
from app.schemas.stock_scan import StockScanRequest
r = StockScanRequest(universe=['SP500'], symbols=['AAPL','MSFT'], direction='Bullish', horizon='Swing', strategy='pullback_ema')
print(r.symbols)
"
```

Expected output: `['AAPL', 'MSFT']`

- [ ] **Step 3.3: Commit**

```bash
git add backend/app/schemas/stock_scan.py
git commit -m "feat(schema): add optional symbols list to StockScanRequest"
```

---

## Task 4 — Backend router: prefer `symbols` over `expand_universe`

**Problem:** `run_stock_scan` always calls `expand_universe(req.universe)` even when the caller provided `req.symbols`.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`

- [ ] **Step 4.1: Replace universe expansion with symbols-first logic**

In `backend/app/routers/stock_scan.py`, replace lines 136–140 (the `scan_id` + `expand_universe` block):

```python
@router.post("/stock-scan")
async def run_stock_scan(req: StockScanRequest) -> StockScanResult:
    from app.data.universe_presets import expand_universe, PresetUnavailableError

    scan_id = new_rec_id()

    if req.symbols:
        symbols = req.symbols
    else:
        try:
            symbols = expand_universe(req.universe)
        except PresetUnavailableError as e:
            raise HTTPException(status_code=400, detail=str(e))
```

The rest of the function (`tasks = [...]`, `asyncio.gather`, etc.) is unchanged.

- [ ] **Step 4.2: Write a test for the symbols-first path**

Create `backend/tests/test_stock_scan_router.py`:

```python
"""Unit tests for /stock-scan endpoint — schema and routing logic only (no live API calls)."""
import pytest
from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_symbols():
    req = StockScanRequest(
        universe=["SP500"],
        symbols=["AAPL", "MSFT"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols == ["AAPL", "MSFT"]


def test_stock_scan_request_symbols_defaults_none():
    req = StockScanRequest(
        universe=["SP500"],
        direction="Bullish",
        horizon="Swing",
        strategy="pullback_ema",
    )
    assert req.symbols is None
```

- [ ] **Step 4.3: Run the router tests**

```bash
cd backend && pytest tests/test_stock_scan_router.py -v
```

Expected: both tests PASS.

- [ ] **Step 4.4: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_stock_scan_router.py
git commit -m "feat(stock-scan): use explicit symbols list when provided, skip universe expansion"
```

---

## Task 5 — Frontend `api.ts`: add `symbols` to `postStockScan` and expose prefetch helpers

**Problem:** The `postStockScan` call site has no way to pass `symbols`. The prefetch endpoints exist on the backend but are unreachable from the frontend.

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 5.1: Add `symbols?` to `postStockScan`**

In `frontend/lib/api.ts`, change the `postStockScan` definition (currently around line 92):

```typescript
  postStockScan: (req: {
    universe: string[]; direction: string; horizon: string;
    strategy: string; symbols?: string[];
    account_size?: number; risk_pct?: number;
    risk_fixed_usd?: number; bt_min_trades?: number; bt_min_win_rate?: number;
    min_price?: number; max_price?: number;
  }) => post<StockScanResult>('/api/stock-scan', req),
```

- [ ] **Step 5.2: Add prefetch helpers**

After the `postStockScan` entry in the `api` object, add:

```typescript
  prefetchHistory: (universe: string[], years = 5) =>
    post<{ message: string; total: number }>(
      '/api/historical-data/prefetch',
      { universe, years, delay_secs: 0.5 },
    ),

  getPrefetchStatus: () =>
    get<{
      status: 'idle' | 'running' | 'completed' | 'error';
      total: number; done: number; failed: number;
      current_symbol: string | null; elapsed_secs: number; started_at: string | null;
    }>('/api/historical-data/prefetch/status'),
```

- [ ] **Step 5.3: Run the TypeScript typechecker**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0, no errors.

- [ ] **Step 5.4: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(api): add symbols to postStockScan; expose prefetchHistory and getPrefetchStatus"
```

---

## Task 6 — Step 5 page: pass Step 4 candidates as `symbols`

**Problem:** The strategy scan reads `context.universe` and sends `universe: ['SP500']` to the backend, which then re-expands to all 519 stocks. Step 4 already ranked 8 of them — the strategy scan should only cover those 8.

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`

Step 4 (`step-4-ranking/page.tsx:118`) reads `useScanStore((s) => s.scanResult?.candidates)` — these are the `TradeCardData[]` candidates. Each has a `.symbol` string.

- [ ] **Step 6.1: Read candidates from the store**

In `frontend/app/(frame)/screener/step-5-strategy/page.tsx`, add `scanResult` to the store reads (around line 47):

```typescript
  const context = useScanStore((s) => s.context);
  const scanResult = useScanStore((s) => s.scanResult);      // ← add this line
  const activeStrategy = useScanStore((s) => s.activeStrategy);
```

- [ ] **Step 6.2: Pass `symbols` in `runScan`**

Replace the `runScan` function body (currently lines 54–75) with:

```typescript
  async function runScan(stratKey: string) {
    setActiveStrategy(stratKey);
    setStockScanResult(null);
    setLoadingStrategy(stratKey);
    setError(null);
    try {
      const candidateSymbols = scanResult?.candidates.map((c) => c.symbol);
      const result = await api.postStockScan({
        universe: context?.universe ? [context.universe] : ['SP500'],
        symbols: candidateSymbols?.length ? candidateSymbols : undefined,
        direction: context?.direction ?? 'Bullish',
        horizon: (context?.horizon ?? 'Swing (5–15d)').split(' ')[0],
        strategy: stratKey,
        account_size: 50_000,
        risk_pct: 0.01,
      });
      setStockScanResult(result);
      router.push('/screener/step-6-backtest');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingStrategy(null);
    }
  }
```

When `candidateSymbols` is non-empty, the backend skips `expand_universe` and scans only those tickers. When Step 4 has not been run (no `scanResult`), it falls back to the full universe as before.

- [ ] **Step 6.3: Show the candidate count to the user**

In the `<div className={styles.header}>` block (after the subtitle `<Text>`), add:

```tsx
        {scanResult?.candidates.length ? (
          <Text size={12} tone="secondary">
            Scanning {scanResult.candidates.length} candidates from Stock Ranking
          </Text>
        ) : (
          <Text size={12} tone="caution">
            No Stock Ranking results — scanning full universe
          </Text>
        )}
```

- [ ] **Step 6.4: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 6.5: Commit**

```bash
git add frontend/app/'(frame)'/screener/step-5-strategy/page.tsx
git commit -m "feat(step-5): pass Step-4 candidates as symbols to narrow strategy scan"
```

---

## Task 7 — Step 5 page: prefetch trigger button + status

**Problem:** On a cold start, the historical DB is empty. Even with 8 symbols, each `get_bars()` call must fetch 5 years from Tiingo. A one-click pre-warm button lets the user fill the DB in the background before they run any scan.

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`

- [ ] **Step 7.1: Add prefetch state and handlers**

After the existing `useState` declarations (around line 51), add:

```typescript
  const [prefetchStatus, setPrefetchStatus] = useState<
    'idle' | 'running' | 'completed' | 'error' | null
  >(null);
  const [prefetchProgress, setPrefetchProgress] = useState<{ done: number; total: number } | null>(null);
```

Add a `startPrefetch` function after the `runScan` function:

```typescript
  async function startPrefetch() {
    try {
      const universe = context?.universe ? [context.universe] : ['SP500'];
      await api.prefetchHistory(universe);
      setPrefetchStatus('running');
      // Poll status every 5 seconds until done.
      const poll = setInterval(async () => {
        try {
          const s = await api.getPrefetchStatus();
          setPrefetchProgress({ done: s.done, total: s.total });
          if (s.status === 'completed' || s.status === 'error') {
            setPrefetchStatus(s.status);
            clearInterval(poll);
          }
        } catch {
          clearInterval(poll);
        }
      }, 5_000);
    } catch (e) {
      setPrefetchStatus('error');
    }
  }
```

- [ ] **Step 7.2: Add the prefetch UI below the strategy grid**

After the closing `</div>` of the strategy `<div className={styles.grid}>`, add:

```tsx
      <div className={styles.prefetchRow}>
        <Text size={12} tone="secondary">
          Historical data:{' '}
          {prefetchStatus === 'running' && prefetchProgress
            ? `warming up ${prefetchProgress.done}/${prefetchProgress.total}`
            : prefetchStatus === 'completed'
            ? 'ready'
            : prefetchStatus === 'error'
            ? 'error — retry below'
            : 'not pre-warmed'}
        </Text>
        {prefetchStatus !== 'running' && (
          <button
            className={styles.prefetchBtn}
            onClick={startPrefetch}
          >
            {prefetchStatus === 'completed' ? 'Re-warm' : 'Pre-warm history'}
          </button>
        )}
      </div>
```

- [ ] **Step 7.3: Add CSS for the new elements**

In `frontend/app/(frame)/screener/step-5-strategy/page.module.css`, append:

```css
.prefetchRow {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.prefetchBtn {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  cursor: pointer;
}

.prefetchBtn:hover {
  border-color: var(--border-default);
  color: var(--text-primary);
}
```

- [ ] **Step 7.4: Run typecheck**

```bash
cd frontend && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 7.5: Run frontend tests**

```bash
cd frontend && npm run test
```

Expected: all pass (no tests import this page directly; this is a smoke check).

- [ ] **Step 7.6: Commit**

```bash
git add frontend/app/'(frame)'/screener/step-5-strategy/page.tsx \
        frontend/app/'(frame)'/screener/step-5-strategy/page.module.css
git commit -m "feat(step-5): add pre-warm historical data button with polling status"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|---|---|
| 27-min scan: concurrency was unbounded | Task 1 (semaphore) |
| 0 matches: pullback_ema 1.5% too tight | Task 2 (4% tolerance) |
| 0 matches: ma_crossover 3-bar too recent | Task 2 (10-bar lookback) |
| 0 matches: breakout_base 1.3× too strict | Task 2 (1.1× multiplier) |
| Strategy scans 519 instead of 8 — backend | Tasks 3 + 4 (schema + router) |
| Strategy scans 519 instead of 8 — frontend | Tasks 5 + 6 (api.ts + page) |
| Pre-warm historical data from UI | Tasks 5 + 7 (api.ts + prefetch button) |

### Placeholder check

No TBDs, no "add appropriate error handling" phrases, no forward references to undefined types.

### Type consistency

- `symbols?: string[]` added to both `StockScanRequest` (Python, Task 3) and `postStockScan` TS type (Task 5) — identical shape.
- `scanResult.candidates[].symbol: string` — `TradeCardData` has `.symbol`; confirmed in `step-4-ranking/page.tsx:118` which maps candidates to rows.
- `prefetchStatus` state is `'idle' | 'running' | 'completed' | 'error' | null` — matches `PrefetchStatus.status` from backend response (Task 5 `getPrefetchStatus` return type).
