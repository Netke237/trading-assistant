# Fibonacci Pullback — Standalone Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated "Fib Pullback" tab in the Setup Scanner (step-4-prebreakout page) that scans for stocks near Fibonacci retracement levels, with its own 3-param panel and results table, and clean up the now-redundant fib checkbox from the Pre-Breakout params panel.

**Architecture:** New `/api/scan/fib-pullback` backend endpoint calls `_fibonacci_pullback_signal()` directly, returning per-symbol results with level hit, distance, and at_level flag. Frontend adds a third `ScanMode` value (`'fib'`), a new `FibPullbackParamsPanel` component, and a dedicated results table. Fib fields are removed from `PreBreakoutParams`.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 App Router, TypeScript strict, CSS Modules, Zustand v5 (frontend), pytest (tests).

---

## File Map

| Action | File | What changes |
|---|---|---|
| Modify | `backend/app/routers/stock_scan.py` | Add `FibPullbackScanRequest` model + `/scan/fib-pullback` endpoint |
| Modify | `backend/app/services/strategy_engine.py` | Export `_fibonacci_pullback_signal` as public `fibonacci_pullback_signal` |
| Create | `backend/tests/test_fib_pullback_endpoint.py` | Integration tests for new endpoint |
| Modify | `frontend/lib/api.ts` | Add `fibPullbackScan()` |
| Modify | `frontend/lib/scanStore.ts` | Add `fibPullbackResults` + `setFibPullbackResults` |
| Create | `frontend/components/organisms/FibPullbackParamsPanel/index.tsx` | 3-param panel UI |
| Create | `frontend/components/organisms/FibPullbackParamsPanel/FibPullbackParamsPanel.module.css` | Styles |
| Modify | `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` | Add 'fib' mode, wire panel + results table |
| Modify | `frontend/app/(frame)/screener/step-4-prebreakout/page.module.css` | Fib results table columns |
| Modify | `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` | Remove fib fields |
| Modify | `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css` | Remove fib styles |

---

## Task 1: Make `_fibonacci_pullback_signal` importable

**Files:**
- Modify: `backend/app/services/strategy_engine.py`

- [ ] **Step 1: Add public alias after the private function definition**

In `strategy_engine.py`, after the closing line of `_fibonacci_pullback_signal` (currently around line 166), add:

```python
# Public alias so routers can import without depending on the private name
fibonacci_pullback_signal = _fibonacci_pullback_signal
```

- [ ] **Step 2: Verify import works**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
python -c "from app.services.strategy_engine import fibonacci_pullback_signal; print('ok')"
```
Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/strategy_engine.py
git commit -m "refactor(strategy_engine): expose fibonacci_pullback_signal as public alias"
```

---

## Task 2: Backend — `/api/scan/fib-pullback` endpoint

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Create: `backend/tests/test_fib_pullback_endpoint.py`

- [ ] **Step 1: Write failing tests first**

Create `backend/tests/test_fib_pullback_endpoint.py`:

```python
"""Tests for POST /api/scan/fib-pullback endpoint."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app

BARS_50 = [
    {"open": 100.0 + i * 0.1, "high": 101.0 + i * 0.1,
     "low": 99.0 + i * 0.1, "close": 100.5 + i * 0.1, "volume": 1_000_000}
    for i in range(120)
]


@pytest.mark.asyncio
async def test_fib_pullback_returns_list():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        row = data[0]
        assert "symbol" in row
        assert "fib_level_hit" in row
        assert "fib_dist_pct" in row
        assert "at_level" in row
        assert "confidence" in row


@pytest.mark.asyncio
async def test_fib_pullback_accepts_params_override():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["MSFT"],
                "direction": "Bullish",
                "params_override": {
                    "fib_swing_lookback": 80,
                    "fib_levels": [38.2, 61.8],
                    "fib_tolerance_pct": 0.02,
                },
            })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_fib_pullback_rejects_unknown_override():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/scan/fib-pullback", json={
            "symbols": ["AAPL"],
            "direction": "Bullish",
            "params_override": {"bad_key": 99},
        })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_fib_pullback_empty_bars_skipped():
    with patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_bars.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": ["AAPL"],
                "direction": "Bullish",
            })
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_fib_pullback_universe_expansion():
    with patch("app.routers.stock_scan.expand_universe") as mock_expand, \
         patch("app.routers.stock_scan.get_historical_bars", new_callable=AsyncMock) as mock_bars:
        mock_expand.return_value = ["AAPL", "MSFT"]
        mock_bars.return_value = BARS_50
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/scan/fib-pullback", json={
                "symbols": [],
                "direction": "Bullish",
                "universe": ["SP500"],
            })
    assert resp.status_code == 200
    assert len(resp.json()) == 2
```

- [ ] **Step 2: Run tests — expect failures**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
python -m pytest tests/test_fib_pullback_endpoint.py -v
```
Expected: `FAILED` (endpoint does not exist yet)

- [ ] **Step 3: Add Pydantic model and endpoint to `stock_scan.py`**

Add after the `PreBreakoutScanRequest` class (search for it) and before the `@router.post("/scan/prebreakout")` line:

```python
_FIB_ALLOWED_OVERRIDE_KEYS = frozenset({
    "fib_swing_lookback",
    "fib_levels",
    "fib_tolerance_pct",
})
_FIB_INT_OVERRIDE_KEYS = frozenset({"fib_swing_lookback"})

_FIB_DEFAULTS = {
    "fib_swing_lookback": 100,
    "fib_levels": [38.2, 61.8],
    "fib_tolerance_pct": 0.015,
}


class FibPullbackScanRequest(BaseModel):
    symbols: list[str] = []
    direction: Literal["Bullish", "Bearish"] = "Bullish"
    params_override: dict | None = None
    universe: list[str] | None = None


@router.post("/scan/fib-pullback")
async def fib_pullback_scan(body: FibPullbackScanRequest) -> list[dict]:
    """Scan symbols for Fibonacci retracement setups using fibonacci_pullback_signal."""
    from app.services.strategy_engine import fibonacci_pullback_signal

    end = date.today()
    start = end - timedelta(days=365)

    if body.universe:
        try:
            symbols_to_scan = expand_universe(body.universe)
        except PresetUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

    if not symbols_to_scan:
        return []

    scan_params: dict = dict(_FIB_DEFAULTS)
    if body.params_override:
        unknown = set(body.params_override) - _FIB_ALLOWED_OVERRIDE_KEYS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown override keys: {sorted(unknown)}")
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _FIB_INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                coerced[k] = [float(x) for x in v]
            else:
                coerced[k] = float(v) if isinstance(v, (int, float)) else v
        scan_params.update(coerced)

    results: list[dict] = []
    for sym in symbols_to_scan:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            bars = await get_historical_bars(sym, start, end)
        except Exception as exc:
            logger.warning("fib-pullback scan: get_bars failed for %s — %s", sym, exc)
            continue
        if not bars:
            continue
        try:
            at_level, dist_pct, level_hit = fibonacci_pullback_signal(
                bars,
                body.direction,
                fib_swing_lookback=scan_params["fib_swing_lookback"],
                fib_levels=scan_params["fib_levels"],
                fib_tolerance_pct=scan_params["fib_tolerance_pct"],
            )
        except Exception as exc:
            logger.warning("fib-pullback scan: signal failed for %s — %s", sym, exc)
            continue
        if level_hit is None:
            # Insufficient bars or no swing found — skip
            continue
        # Confidence: 100 if at level, scaled by proximity otherwise
        tol = scan_params["fib_tolerance_pct"] * 100  # convert to pct units
        if dist_pct is None:
            confidence = 0
        elif at_level:
            confidence = max(60, round(100 - (dist_pct / tol) * 40))
        else:
            confidence = max(0, round(60 - ((dist_pct - tol) / tol) * 30))
        results.append({
            "symbol": sym,
            "direction": body.direction,
            "fib_level_hit": level_hit,
            "fib_dist_pct": dist_pct,
            "at_level": at_level,
            "confidence": confidence,
        })

    results.sort(key=lambda r: (r["at_level"], -r["fib_dist_pct"] if r["fib_dist_pct"] else 0), reverse=True)
    return results
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
python -m pytest tests/test_fib_pullback_endpoint.py -v
```
Expected: 5 passed

- [ ] **Step 5: Run full backend suite**

```bash
python -m pytest -v --tb=short 2>&1 | tail -20
```
Expected: all prior tests still pass, 5 new tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_fib_pullback_endpoint.py
git commit -m "feat(fib-pullback): add /api/scan/fib-pullback endpoint with 3-param override"
```

---

## Task 3: Frontend — `fibPullbackScan` API call + store slot

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/scanStore.ts`

- [ ] **Step 1: Add API call to `api.ts`**

After the `prebreakoutScan` entry (around line 511), add:

```typescript
  fibPullbackScan: (
    symbols: string[],
    direction: string,
    paramsOverride?: { fib_swing_lookback?: number; fib_levels?: number[]; fib_tolerance_pct?: number },
    universe?: string[],
  ) =>
    post<Array<{
      symbol: string;
      direction: string;
      fib_level_hit: string;
      fib_dist_pct: number | null;
      at_level: boolean;
      confidence: number;
    }>>(
      '/api/scan/fib-pullback',
      { symbols, direction, params_override: paramsOverride ?? null, universe: universe ?? null }
    ),
```

- [ ] **Step 2: Add state slot to `scanStore.ts`**

Read `frontend/lib/scanStore.ts` first to find the store shape, then add:

```typescript
// In the state interface, after preBreakoutResults:
fibPullbackResults: Array<{
  symbol: string;
  direction: string;
  fib_level_hit: string;
  fib_dist_pct: number | null;
  at_level: boolean;
  confidence: number;
}>;

// In the initial state:
fibPullbackResults: [],

// Action in the store:
setFibPullbackResults: (rows) => set({ fibPullbackResults: rows }),
```

- [ ] **Step 3: Typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/scanStore.ts
git commit -m "feat(fib-pullback): add fibPullbackScan API call + store slot"
```

---

## Task 4: `FibPullbackParamsPanel` component

**Files:**
- Create: `frontend/components/organisms/FibPullbackParamsPanel/index.tsx`
- Create: `frontend/components/organisms/FibPullbackParamsPanel/FibPullbackParamsPanel.module.css`

- [ ] **Step 1: Create CSS module**

```css
/* FibPullbackParamsPanel.module.css */
.paramsPanel {
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
}
.paramsSummary {
  padding: 8px 12px;
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  user-select: none;
}
.paramsSummary::-webkit-details-marker { display: none; }
.paramsGrid {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  border-top: 1px solid var(--border-subtle);
}
.paramSection {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.paramLabel {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.paramInput {
  display: flex;
  align-items: center;
  gap: 6px;
}
.paramInput input[type="number"] {
  width: 72px;
  padding: 4px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--bg-input, var(--bg-surface));
  color: var(--text-primary);
  font-size: 12px;
}
.fibLevels {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}
.fibLevelCheck {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.fibLevelCheck input[type="checkbox"]:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.resetBtn {
  align-self: flex-start;
  padding: 4px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}
.resetBtn:hover { background: var(--bg-hover, rgba(255,255,255,0.05)); }
```

- [ ] **Step 2: Create component**

```tsx
// frontend/components/organisms/FibPullbackParamsPanel/index.tsx
'use client';

import { Text } from '@/components/primitives';
import styles from './FibPullbackParamsPanel.module.css';

export interface FibPullbackParams {
  fibSwingLookback: number;   // 20–200, default 100
  fibLevels: number[];        // subset of [23.6, 38.2, 50.0, 61.8, 78.6], default [38.2, 61.8]
  fibTolerancePct: number;    // stored as fraction 0.005–0.05, default 0.015
}

export const FIB_PULLBACK_DEFAULTS: FibPullbackParams = {
  fibSwingLookback: 100,
  fibLevels: [38.2, 61.8],
  fibTolerancePct: 0.015,
};

const ALL_FIB_LEVELS = [23.6, 38.2, 50.0, 61.8, 78.6];

interface Props {
  params: FibPullbackParams;
  setParams: React.Dispatch<React.SetStateAction<FibPullbackParams>>;
  onReset: () => void;
}

export function FibPullbackParamsPanel({ params, setParams, onReset }: Props) {
  return (
    <details className={styles.paramsPanel}>
      <summary className={styles.paramsSummary}>
        <Text size={12} tone="secondary">Scan parameters</Text>
      </summary>

      <div className={styles.paramsGrid}>

        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Fibonacci levels</Text>
          <Text size={10} tone="dim">
            Which retracement levels to treat as support. 38.2% and 61.8% are the most
            reliable. More levels = more results but more false positives.
          </Text>
          <div className={styles.fibLevels}>
            {ALL_FIB_LEVELS.map((lvl) => {
              const isChecked = params.fibLevels.includes(lvl);
              const isLastRemaining = isChecked && params.fibLevels.length === 1;
              return (
                <label key={lvl} className={styles.fibLevelCheck}>
                  <input
                    type="checkbox"
                    checked={isChecked}
                    disabled={isLastRemaining}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...params.fibLevels, lvl].sort((a, b) => a - b)
                        : params.fibLevels.filter((l) => l !== lvl);
                      setParams((p) => ({ ...p, fibLevels: next }));
                    }}
                  />
                  <Text size={11} tone={isChecked ? 'primary' : 'dim'}>{lvl}%</Text>
                </label>
              );
            })}
          </div>
        </div>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Swing lookback</Text>
          <Text size={10} tone="dim">
            Bars back to search for the dominant swing high/low that anchors the fib move.
            Higher = captures bigger structural moves.
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={params.fibSwingLookback}
              min={20} max={200} step={5}
              onChange={(e) => setParams((p) => ({ ...p, fibSwingLookback: Number(e.target.value) }))}
            />
            <Text size={11} tone="dim">bars</Text>
          </div>
        </label>

        <label className={styles.paramLabel}>
          <Text size={11} tone="dim">Tolerance</Text>
          <Text size={10} tone="dim">
            How close (%) price must be to a fib level to count as &quot;at level&quot;.
            Higher = wider net (more results); lower = only precise hits qualify.
          </Text>
          <div className={styles.paramInput}>
            <input
              type="number"
              value={Math.round(params.fibTolerancePct * 100 * 10) / 10}
              min={0.5} max={5.0} step={0.1}
              onChange={(e) =>
                setParams((p) => ({ ...p, fibTolerancePct: Number(e.target.value) / 100 }))
              }
            />
            <Text size={11} tone="dim">%</Text>
          </div>
        </label>

        <button type="button" className={styles.resetBtn} onClick={onReset}>
          Reset to defaults
        </button>

      </div>
    </details>
  );
}
```

- [ ] **Step 3: Typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/FibPullbackParamsPanel/
git commit -m "feat(fib-pullback): FibPullbackParamsPanel component (3 params)"
```

---

## Task 5: Wire "Fib Pullback" tab into step-4-prebreakout page

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.module.css`

- [ ] **Step 1: Read the current page and CSS to understand exact insertion points**

Read both files before editing.

- [ ] **Step 2: Update `page.tsx`**

Changes needed (apply in this order):

**a) Extend ScanMode type and imports:**
```typescript
// Change:
type ScanMode = 'prebreakout' | 'pullback';
// To:
type ScanMode = 'prebreakout' | 'pullback' | 'fib';
```

**b) Add new imports at the top of the file:**
```typescript
import {
  FibPullbackParamsPanel,
  FIB_PULLBACK_DEFAULTS,
  type FibPullbackParams,
} from '@/components/organisms/FibPullbackParamsPanel';
```

**c) Add FibScanRow type (after the existing ScanRow type):**
```typescript
type FibScanRow = {
  symbol: string;
  direction: string;
  fib_level_hit: string;
  fib_dist_pct: number | null;
  at_level: boolean;
  confidence: number;
};
```

**d) Add fib state inside the component (after the existing `params` state):**
```typescript
const [fibParams, setFibParams] = useState<FibPullbackParams>({ ...FIB_PULLBACK_DEFAULTS });
const fibResults = useScanStore((s) => s.fibPullbackResults);
const setFibResults = useScanStore((s) => s.setFibPullbackResults);
```

**e) Extend the `useEffect` that clears results on params change to also clear fib results:**
```typescript
useEffect(() => {
  if (isFirstRender.current) {
    isFirstRender.current = false;
    return;
  }
  setResults([]);
  setFibResults([]);
}, [params, fibParams, universePick, direction, setResults, setFibResults]);
```

**f) Add fib scan branch inside `runScan` (after the existing try/catch block for prebreakout, before `setScanning(false)`):**

Replace the entire `runScan` callback with:
```typescript
const runScan = useCallback(async () => {
  const manualSymbols = parseSymbols(symbolOverride);
  let symbols: string[];
  let universe: string[] | undefined;

  if (manualSymbols.length > 0) {
    symbols = manualSymbols;
    universe = undefined;
  } else if (universePick === 'Custom') {
    symbols = parseSymbols(customRaw);
    universe = undefined;
  } else if (universePick === 'Watchlist') {
    symbols = useWatchlistStore.getState().added;
    universe = undefined;
  } else {
    symbols = [];
    universe = [universePick];
  }

  if (symbols.length === 0 && !universe) {
    if (universePick === 'Custom') {
      setError('Custom universe is empty — add symbols in Step 2 (Universe) or enter them above.');
    } else if (universePick === 'Watchlist') {
      setError('Watchlist is empty — star some symbols or enter them above.');
    } else {
      setError('No symbols to scan.');
    }
    return;
  }

  setError(null);
  setScanning(true);
  try {
    if (scanMode === 'fib') {
      const results = await api.fibPullbackScan(
        symbols,
        direction,
        {
          fib_swing_lookback: fibParams.fibSwingLookback,
          fib_levels: fibParams.fibLevels,
          fib_tolerance_pct: fibParams.fibTolerancePct,
        },
        universe,
      );
      setFibResults(results);
    } else {
      const paramsOverride: Record<string, unknown> = {
        atr_compression_ratio:    params.atrCompressionRatio,
        atr_avg_lookback:         params.atrAvgLookback,
        range_atr_mult:           params.rangeAtrMult,
        range_lookback_bars:      params.rangeLookbackBars,
        vol_compression_ratio:    params.volCompressionRatio,
        resistance_proximity_pct: params.resistanceProximityPct,
        swing_lookback:           params.swingLookback,
      };
      const results = await api.prebreakoutScan(symbols, direction, paramsOverride, universe);
      setResults(results);
    }
  } catch (e) {
    setError((e as Error).message);
  } finally {
    setScanning(false);
  }
}, [scanMode, symbolOverride, universePick, customRaw, direction, params, fibParams, setResults, setFibResults]);
```

**g) Add the third tab button (in the modeToggle div, after the Pullback to EMA button):**
```tsx
<button
  type="button"
  aria-pressed={scanMode === 'fib'}
  className={`${styles.modeBtn} ${scanMode === 'fib' ? styles.modeBtnActive : ''}`}
  onClick={() => setScanMode('fib')}
>
  Fib Pullback
</button>
```

**h) Add Fib Pullback mode UI block (after the pullbackInfo block and before the closing of the ternary):**

The current structure is:
```tsx
{scanMode === 'pullback' ? (
  <div className={styles.pullbackInfo}>...</div>
) : (
  <>...prebreakout UI...</>
)}
```

Change to:
```tsx
{scanMode === 'pullback' ? (
  <div className={styles.pullbackInfo}>
    <Text size={13} tone="secondary">
      Trending stocks that have pulled back to their EMA are handled in the full
      <strong> Stocks screener</strong> (Steps 1–3 → Stocks mode → Step 4 → pick
      <em> Pullback to 20-EMA</em>). That flow includes a historical backtest, confidence
      gate, and broker execution. Use this tab for pre-breakout consolidation setups only.
    </Text>
  </div>
) : scanMode === 'fib' ? (
  <>
    <Text size={12} tone="dim">
      Stocks retracing to a key Fibonacci level (38.2%, 61.8%) after a significant swing move.
      At-level hits are sorted first. Set a regime alert to be notified when conditions align.
    </Text>

    <div className={styles.inputRow}>
      <textarea
        className={styles.symbolInput}
        rows={2}
        placeholder={`Leave blank to use universe (${universeLabel}) · or enter specific symbols to override`}
        value={symbolOverride}
        onChange={(e) => setSymbolOverride(e.target.value)}
      />
      <button
        type="button"
        className={styles.runBtn}
        onClick={runScan}
        disabled={scanning}
      >
        {scanning ? 'Scanning…' : 'Run Scan'}
      </button>
    </div>

    <FibPullbackParamsPanel
      params={fibParams}
      setParams={setFibParams}
      onReset={() => setFibParams({ ...FIB_PULLBACK_DEFAULTS })}
    />

    {error && <Text size={12} tone="reject">{error}</Text>}

    {fibResults.length > 0 && (
      <div className={styles.tableWrap}>
        <div className={styles.fibTableHeader}>
          <span />
          <Text size={11} tone="dim" weight={500}>Symbol</Text>
          <Text size={11} tone="dim" weight={500}>Dir</Text>
          <Text size={11} tone="dim" weight={500}>Fib Level</Text>
          <Text size={11} tone="dim" weight={500}>Distance</Text>
          <Text size={11} tone="dim" weight={500}>At Level</Text>
          <Text size={11} tone="dim" weight={500}>Confidence</Text>
          <span />
        </div>
        {fibResults.map((row) => (
          <div key={row.symbol} className={styles.fibTableRow}>
            <WatchStar symbol={row.symbol} size="sm" />
            <Text size={13} weight={500}>{row.symbol}</Text>
            <Text size={12} tone={row.direction === 'Bullish' ? 'pass' : 'reject'}>
              {row.direction === 'Bullish' ? '↑' : '↓'}
            </Text>
            <Data size={12} tone="secondary">{row.fib_level_hit}%</Data>
            <Data size={12} tone={row.fib_dist_pct != null && row.fib_dist_pct <= 1.5 ? 'pass' : 'caution'}>
              {row.fib_dist_pct != null ? `${row.fib_dist_pct.toFixed(1)}%` : '—'}
            </Data>
            <Data size={12} tone={row.at_level ? 'pass' : 'dim'}>
              {row.at_level ? 'YES' : 'no'}
            </Data>
            <Data size={13} tone={_confidenceTone(row.confidence)}>{row.confidence}%</Data>
            <button
              type="button"
              className={styles.alertBtn}
              onClick={() => setAlertSymbol(row.symbol)}
              title="Set alert"
            >
              +
            </button>
          </div>
        ))}
      </div>
    )}

    {fibResults.length === 0 && !scanning && !error && (
      <Text size={12} tone="dim">No results yet — run the scan.</Text>
    )}
  </>
) : (
  <>
    {/* existing prebreakout UI — unchanged */}
    ...
  </>
)}
```

- [ ] **Step 3: Add CSS for fib table in `page.module.css`**

Append to the existing CSS file:

```css
.fibTableHeader,
.fibTableRow {
  display: grid;
  grid-template-columns: 24px 80px 32px 80px 72px 72px 72px 32px;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
}
.fibTableHeader {
  border-bottom: 1px solid var(--border-subtle);
}
.fibTableRow {
  border-bottom: 1px solid var(--border-subtle);
}
.fibTableRow:last-child {
  border-bottom: none;
}
```

- [ ] **Step 4: Typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```
Expected: 0 errors

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/screener/step-4-prebreakout/"
git commit -m "feat(fib-pullback): add Fib Pullback tab, panel, and results table to Setup Scanner"
```

---

## Task 6: Remove fib fields from `PreBreakoutParamsPanel`

**Files:**
- Modify: `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`
- Modify: `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css`

- [ ] **Step 1: Remove fib fields from `PreBreakoutParams` interface and `PREBREAKOUT_DEFAULTS`**

In `PreBreakoutParamsPanel/index.tsx`, remove:
```typescript
// Remove from interface PreBreakoutParams:
fibEnabled: boolean;
fibSwingLookback: number;
fibLevels: number[];
fibTolerancePct: number;

// Remove from PREBREAKOUT_DEFAULTS:
fibEnabled: false,
fibSwingLookback: 100,
fibLevels: [23.6, 38.2, 50.0, 61.8],
fibTolerancePct: 0.015,
```

- [ ] **Step 2: Remove fib UI block from `PreBreakoutParamsPanel`**

Delete the entire `{/* ── Fibonacci pullback ── */}` section including:
- The `paramSection` div with fib heading/description
- The `fibEnabled` checkbox label
- The `{params.fibEnabled && (...)}` conditional block with fib level checkboxes, swing lookback, and tolerance inputs

- [ ] **Step 3: Remove fib CSS from `PreBreakoutParamsPanel.module.css`**

Remove `.fibLevels` and `.fibLevelCheck` rules if they exist only in this file (they are now in `FibPullbackParamsPanel.module.css`).

- [ ] **Step 4: Remove fib params from the `paramsOverride` in `page.tsx`**

In `step-4-prebreakout/page.tsx`, in the prebreakout branch of `runScan`, ensure the `paramsOverride` object no longer includes `fib_enabled`, `fib_swing_lookback`, `fib_levels`, `fib_tolerance_pct` (should already be clean from Task 5).

- [ ] **Step 5: Typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/PreBreakoutParamsPanel/
git commit -m "refactor(prebreakout): remove fib fields now that Fib Pullback has its own tab"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd "F:\Git\GitHub\Trading assistant\backend"
python -m pytest -v --tb=short 2>&1 | tail -20
```
Expected: all tests pass, 0 failures

- [ ] **Step 2: Run frontend typecheck**

```bash
cd "F:\Git\GitHub\Trading assistant\frontend"
npm run typecheck
```
Expected: 0 errors

- [ ] **Step 3: Commit final state**

```bash
git add -A
git commit -m "chore: final verification pass — fib pullback tab complete"
```
