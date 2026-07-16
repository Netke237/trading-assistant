# CET Timezone + Symbol Name + Watchlist Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three UX fixes — (1) scheduler windows and scan-time display use CET, (2) chart toolbar shows the company name after the symbol input, (3) clicking a watchlist row syncs the chart store so the symbol and name are correct everywhere.

**Architecture:** Backend config change sets the scheduler timezone to `Europe/Paris`. A new `/api/symbol/{symbol}/info` endpoint returns a company name (KNOWN_NAMES lookup → Tradier fallback). `chartStore` gains a `symbolName` field; `ChartTopBar` fetches and displays it. The watchlist `onSelect` handler also writes both fields to the store so navigating to `/chart` is always consistent.

**Tech Stack:** FastAPI (backend router), Pydantic v2 (schema default), Zustand v5 (frontend store), Next.js 15 / TypeScript 5.7 (frontend components), CSS Modules.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/config/settings.yaml` | Modify | Change `timezone_name` from `America/New_York` to `Europe/Paris` |
| `backend/app/schemas/schedule.py` | Modify | Change `timezone_name` default to `"Europe/Paris"` |
| `frontend/components/molecules/ScanIndicator/index.tsx` | Modify | Fix `labelWithDate` to format time with locale (was slicing raw ISO = UTC digits) |
| `backend/app/routers/symbols.py` | Create | `GET /api/symbol/{symbol}/info` — returns `{ symbol, name }` |
| `backend/app/main.py` | Modify | Register `symbols_router` |
| `backend/tests/test_symbol_info.py` | Create | Tests for the new endpoint |
| `frontend/lib/api.ts` | Modify | Add `getSymbolInfo(symbol)` |
| `frontend/lib/chartStore.ts` | Modify | Add `symbolName: string` + `setSymbolName` (persisted, version bump to 2) |
| `frontend/components/organisms/ChartTopBar/index.tsx` | Modify | Fetch and display `symbolName`; handle symbol change |
| `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css` | Modify | Add `.symbolName` style |
| `frontend/app/(frame)/watchlist/page.tsx` | Modify | On stock row click, also write `symbol`+`symbolName` to `chartStore` |

---

### Task 1: Change scheduler timezone to CET

**Files:**
- Modify: `backend/config/settings.yaml` line 40
- Modify: `backend/app/schemas/schedule.py` line 12

- [ ] **Step 1: Edit `settings.yaml`**

In `backend/config/settings.yaml`, change line 40:
```yaml
    timezone_name: Europe/Paris
```
(was `America/New_York`)

- [ ] **Step 2: Edit schema default**

In `backend/app/schemas/schedule.py`, change line 12:
```python
    timezone_name:      str       = "Europe/Paris"
```
(was `"America/New_York"`)

- [ ] **Step 3: Run existing scheduler tests to confirm nothing broke**

```bash
cd backend && pytest tests/test_schedule_endpoint.py -v
```
Expected: all 4 tests PASS. The tests that use `timezone_name` pass an explicit value, so the default change does not affect them.

- [ ] **Step 4: Commit**

```bash
git add backend/config/settings.yaml backend/app/schemas/schedule.py
git commit -m "config: change scheduler timezone default to Europe/Paris (CET)"
```

---

### Task 2: Fix ScanIndicator time display to use locale time

**Files:**
- Modify: `frontend/components/molecules/ScanIndicator/index.tsx`

`ScanIndicator.labelWithDate` calls `hhmmFrom(iso)` which does `iso.slice(11,16)` — this extracts UTC digits from the ISO string regardless of the user's timezone. The `TopBar` version of the same function already uses `toLocaleTimeString`; `ScanIndicator` must match.

- [ ] **Step 1: Replace only `labelWithDate` in ScanIndicator**

Open `frontend/components/molecules/ScanIndicator/index.tsx`.

The file has three helper functions: `hhmmFrom` (lines 29–31), `startOfDay` (lines 33–35), `labelWithDate` (lines 37–50).
**Do NOT touch `hhmmFrom` or `startOfDay`.** Replace only `labelWithDate` (lines 37–50) with the version below that uses `toLocaleTimeString` instead of calling `hhmmFrom`:

```ts
function labelWithDate(iso: string): string {
  const scan = new Date(iso);
  const now  = new Date();
  const diffDays = Math.round((startOfDay(now) - startOfDay(scan)) / 86_400_000);
  const timeStr = scan.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  if (diffDays === 0) return timeStr;
  if (diffDays === 1) return `Yesterday ${timeStr}`;
  const sameYear = scan.getFullYear() === now.getFullYear();
  const mon = scan.toLocaleString(undefined, { month: 'short' });
  const day = scan.getDate();
  return sameYear
    ? `${mon} ${day} ${timeStr}`
    : `${mon} ${day} ${scan.getFullYear()} ${timeStr}`;
}
```

`hhmmFrom` (the UTC string-slice) remains unchanged — it is the SSR fallback used when `mounted === false` to avoid hydration mismatches.

- [ ] **Step 2: Run typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/molecules/ScanIndicator/index.tsx
git commit -m "fix(ScanIndicator): format scan time with locale timezone instead of UTC string slice"
```

---

### Task 3: Backend symbol-info endpoint

**Files:**
- Create: `backend/app/routers/symbols.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_symbol_info.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_symbol_info.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_symbol_info_known_ticker():
    """AAPL is in KNOWN_NAMES — endpoint must return Apple's name without an HTTP call."""
    resp = client.get("/api/symbol/AAPL/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert "Apple" in data["name"]


def test_symbol_info_case_insensitive():
    """Symbol should be uppercased before lookup."""
    resp = client.get("/api/symbol/aapl/info")
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "AAPL"


def test_symbol_info_unknown_ticker_falls_back_to_symbol():
    """Unknown symbols must return the symbol itself as the name (never crash)."""
    resp = client.get("/api/symbol/ZZZNOTREAL/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "ZZZNOTREAL"
    assert data["name"] == "ZZZNOTREAL"
```

- [ ] **Step 2: Run tests to confirm they fail (endpoint not yet created)**

```bash
cd backend && pytest tests/test_symbol_info.py -v
```
Expected: 3 FAILED with `404 Not Found` or `Method Not Allowed`.

- [ ] **Step 3: Create `backend/app/routers/symbols.py`**

```python
from fastapi import APIRouter
from app.data.company_names import KNOWN_NAMES

router = APIRouter(prefix='/api', tags=['symbols'])


@router.get('/symbol/{symbol}/info')
async def get_symbol_info(symbol: str) -> dict:
    sym = symbol.upper()
    name = KNOWN_NAMES.get(sym, sym)
    return {"symbol": sym, "name": name}
```

This uses only `KNOWN_NAMES` (synchronous, no HTTP). The async Tradier fallback in `market.py` requires an `httpx.AsyncClient` session and a Tradier API token; since the chart loads on every page visit, an HTTP call per symbol would be slow and brittle. `KNOWN_NAMES` covers ~150 common S&P 500/NDX100 tickers which is sufficient. Unknown symbols fall back to the symbol string itself.

- [ ] **Step 4: Register router in `backend/app/main.py`**

Add the import near the other router imports (line ~30):
```python
from app.routers.symbols import router as symbols_router
```

Add the `include_router` call inside `create_app()` (after the `app.include_router(candles_router)` line, ~line 239):
```python
    app.include_router(symbols_router)
```

Note: all `include_router` calls are inside `create_app()`, not inside `lifespan`. Do not place it inside the async `lifespan` context manager.

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd backend && pytest tests/test_symbol_info.py -v
```
Expected: 3 PASSED.

- [ ] **Step 6: Run full backend test suite to confirm no regressions**

```bash
cd backend && pytest -v 2>&1 | tail -20
```
Expected: all previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/symbols.py backend/app/main.py backend/tests/test_symbol_info.py
git commit -m "feat(backend): add GET /api/symbol/{symbol}/info endpoint for company name lookup"
```

---

### Task 4: Add `symbolName` to chartStore and `getSymbolInfo` to api.ts

**Files:**
- Modify: `frontend/lib/chartStore.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add `symbolName` to `chartStore`**

In `frontend/lib/chartStore.ts`:

1. Add `symbolName` and `setSymbolName` to the `ChartState` interface (after `symbol: string;`, line 23):
```ts
  symbolName: string;
  setSymbolName: (n: string) => void;
```

2. Add the initial state and action in the `create` call (after `symbol: 'AAPL',`, line 55):
```ts
      symbolName: 'AAPL',
      setSymbolName: (symbolName) => set({ symbolName }),
```

   Also update `setSymbol` so it resets `symbolName` to the raw symbol string immediately — this ensures the old company name disappears at once when the user changes the symbol, rather than lingering until the next fetch resolves:
```ts
      setSymbol: (symbol) => set({ symbol, symbolName: symbol }),
```
(Replace the existing `setSymbol: (symbol) => set({ symbol }),` on line 60.)

3. Add `symbolName` to the `partialize` return object (after `symbol: state.symbol,`, line 77):
```ts
        symbolName: state.symbolName,
```

4. Bump `version` from `1` to `2` (line 83):
```ts
      version: 2,
```

5. Update the **existing** `version < 1` migration branch to include `symbolName` — otherwise a user upgrading from the original (version 0) store will have `symbolName === undefined` at runtime:

Find the existing `version < 1` branch (lines 87–93) and change its return to:
```ts
          return {
            symbol: prev.symbol ?? 'AAPL',
            interval: prev.interval ?? '1D',
            chartType: prev.chartType ?? 'candle',
            symbolName: prev.symbol ?? 'AAPL',
            activeIndicators: Array.isArray(prev.activeIndicators) ? prev.activeIndicators : DEFAULT_INDICATORS,
            paneLayout: prev.paneLayout ?? DEFAULT_PANE_LAYOUT,
          } as ChartState;
```

6. Add a new `version < 2` migration branch immediately after the `version < 1` block:
```ts
        if (version < 2) {
          return {
            ...prev,
            symbolName: (prev as { symbolName?: string }).symbolName ?? prev.symbol ?? 'AAPL',
          } as ChartState;
        }
```

- [ ] **Step 2: Add `getSymbolInfo` to api.ts**

In `frontend/lib/api.ts`, inside the `export const api = { … }` object, add after `getCandles`:
```ts
  getSymbolInfo: (symbol: string) =>
    get<{ symbol: string; name: string }>(`/api/symbol/${encodeURIComponent(symbol)}/info`),
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/chartStore.ts frontend/lib/api.ts
git commit -m "feat(chartStore): add symbolName field + getSymbolInfo API call"
```

---

### Task 5: Display company name in ChartTopBar

**Files:**
- Modify: `frontend/components/organisms/ChartTopBar/index.tsx`
- Modify: `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css`

- [ ] **Step 1: Update ChartTopBar to fetch and display symbolName**

Replace the full contents of `frontend/components/organisms/ChartTopBar/index.tsx` with:

```tsx
'use client';
import { useEffect } from 'react';
import { useChartStore, type Interval, type ChartType } from '@/lib/chartStore';
import { api } from '@/lib/api';
import type { ConnectionState } from '@/lib/chartWS';
import styles from './ChartTopBar.module.css';

const INTERVALS: Interval[] = ['1min', '5min', '15min', '1h', '4h', '1D', '1W'];

const CONN_STATE_CLASS: Record<ConnectionState, string> = {
  connecting:   styles.connecting,
  connected:    '',
  reconnecting: styles.reconnecting,
  error:        styles.error,
};

interface Props {
  onToggleIndicators: () => void;
  onToggleStructure: () => void;
  onToggleAlerts?: () => void;
  connState?: ConnectionState;
  wsError?: string | null;
}

export default function ChartTopBar({ onToggleIndicators, onToggleStructure, onToggleAlerts, connState, wsError }: Props) {
  const { symbol, interval, chartType, symbolName, setSymbol, setInterval, setChartType, setSymbolName } = useChartStore();

  // Fetch company name whenever the active symbol changes.
  useEffect(() => {
    let cancelled = false;
    api.getSymbolInfo(symbol)
      .then(({ name }) => { if (!cancelled) setSymbolName(name); })
      .catch(() => { if (!cancelled) setSymbolName(symbol); });
    return () => { cancelled = true; };
  }, [symbol, setSymbolName]);

  const handleSymbolKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      setSymbol(e.currentTarget.value.toUpperCase().trim());
    }
  };

  const handlePopOut = () => {
    window.open(`/chart/standalone?symbol=${symbol}&interval=${interval}`, '_blank', 'width=1400,height=900');
  };

  return (
    <div className={styles.bar}>
      <input
        className={styles.symbolInput}
        defaultValue={symbol}
        key={symbol}
        onKeyDown={handleSymbolKeyDown}
        onBlur={(e) => setSymbol(e.target.value.toUpperCase().trim())}
        aria-label="Symbol"
      />

      {symbolName && symbolName !== symbol && (
        <span className={styles.symbolName}>{symbolName}</span>
      )}

      <div className={styles.intervals}>
        {INTERVALS.map(i => (
          <button
            key={i}
            className={`${styles.tf} ${interval === i ? styles.tfActive : ''}`}
            onClick={() => setInterval(i)}
          >
            {i}
          </button>
        ))}
      </div>

      <select
        className={styles.chartType}
        value={chartType}
        onChange={(e) => setChartType(e.target.value as ChartType)}
        aria-label="Chart type"
      >
        <option value="candle">Candles</option>
        <option value="bar">Bars</option>
        <option value="line">Line</option>
      </select>

      <button className={styles.btn} onClick={onToggleIndicators}>Indicators</button>
      <button className={styles.btn} onClick={onToggleStructure}>Structure</button>
      {onToggleAlerts && <button className={styles.btn} onClick={onToggleAlerts}>Alerts</button>}

      {connState && connState !== 'connected' && (
        <span
          className={`${styles.connBadge} ${CONN_STATE_CLASS[connState]}`}
          title={wsError ?? connState}
        >
          {connState === 'connecting'   ? 'Connecting…'  :
           connState === 'reconnecting' ? 'Reconnecting…' :
           wsError ?? 'Error'}
        </span>
      )}

      <div className={styles.spacer} />

      <button className={styles.popOut} onClick={handlePopOut} title="Open in new window">
        ⧉ Pop out
      </button>
    </div>
  );
}
```

Key changes vs. original:
- Added `import { useEffect }` and `import { api }`.
- Destructured `symbolName` and `setSymbolName` from `useChartStore`.
- Added `useEffect` to fetch company name on symbol change.
- Added `key={symbol}` on the input so it resets its controlled value when symbol changes externally (e.g., from watchlist).
- Added `{symbolName && symbolName !== symbol && <span className={styles.symbolName}>{symbolName}</span>}` between input and intervals.

- [ ] **Step 2: Add `.symbolName` CSS rule**

In `frontend/components/organisms/ChartTopBar/ChartTopBar.module.css`, add after `.symbolInput {}`:

```css
.symbolName {
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 180px;
  flex-shrink: 1;
}
```

- [ ] **Step 3: Run typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 4: Run frontend tests**

```bash
cd frontend && npm test -- --passWithNoTests 2>&1 | tail -10
```
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/ChartTopBar/index.tsx frontend/components/organisms/ChartTopBar/ChartTopBar.module.css
git commit -m "feat(ChartTopBar): show company name after symbol input"
```

---

### Task 6: Watchlist click syncs chartStore symbol + name

**Files:**
- Modify: `frontend/app/(frame)/watchlist/page.tsx`

When a stock row is clicked in the watchlist, the current `onSelect` handler only updates local `selected` state (which controls the `InlineChartPanel`). It does **not** update `chartStore`. This means the chart page search box shows stale data. Fix: write both `symbol` and `symbolName` to the store on every click.

- [ ] **Step 1: Import `useChartStore` at the top of the watchlist page**

In `frontend/app/(frame)/watchlist/page.tsx`, add after the existing imports (around line 27):

```ts
import { useChartStore } from '@/lib/chartStore';
```

- [ ] **Step 2: Destructure the store actions inside `WatchlistPage`**

Inside `WatchlistPage()`, add after the existing store hook calls (around line 52):

```ts
  const setChartSymbol     = useChartStore((s) => s.setSymbol);
  const setChartSymbolName = useChartStore((s) => s.setSymbolName);
```

- [ ] **Step 3: Update `onSelect` to also write to chartStore**

Replace the existing `onSelect` function (line 164):

```ts
  const onSelect = (symbol: string, company: string) => {
    setSelected((cur) => (cur === symbol ? null : symbol));
    // Keep chartStore in sync so the /chart page shows the right symbol + name
    // even if the user navigates there without explicitly changing the input.
    setChartSymbol(symbol);
    setChartSymbolName(company);
  };
```

- [ ] **Step 4: Update all call sites of `onSelect` to pass `company`**

In the JSX, the `TableRow` `onClick` currently calls `() => onSelect(row.symbol)`. Change it to:

```tsx
onClick={() => onSelect(row.symbol, row.company)}
```

This is the only call site of `onSelect` in the file (line 235).

- [ ] **Step 5: Run typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 6: Run frontend tests**

```bash
cd frontend && npm test -- --passWithNoTests 2>&1 | tail -10
```
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add "frontend/app/(frame)/watchlist/page.tsx"
git commit -m "feat(watchlist): sync chartStore symbol+name on row click"
```

---

## Self-Review

**Spec coverage:**
1. CET scheduling → Task 1 (settings.yaml + schema default). ✓
2. CET time display → Task 2 (ScanIndicator.labelWithDate). ✓
3. Company name after search box → Tasks 3–5 (endpoint + store + ChartTopBar). ✓
4. Watchlist click updates search box → Task 6 (onSelect writes to store). ✓

**Placeholder scan:** No TBDs or "add appropriate error handling" patterns present.

**Type consistency:**
- `setSymbolName` defined in Task 4 (chartStore), used in Tasks 5 and 6. ✓
- `getSymbolInfo` defined in Task 4 (api.ts), called in Task 5. ✓
- `onSelect(symbol, company)` — signature changed in Task 6 Step 3, call site updated in Step 4 (same task). ✓
- `symbolName` in store partialize (Task 4) matches `symbolName` in ChartTopBar destructure (Task 5). ✓
- Backend endpoint `GET /api/symbol/{symbol}/info` (Task 3) matches `api.getSymbolInfo` path `/api/symbol/${…}/info` (Task 4). ✓
- `var(--text-secondary)` confirmed in `frontend/styles/tokens.css` (light and dark variants). ✓
- `setSymbol` updated to reset `symbolName` in Task 4 — eliminates stale-name flicker when symbol changes. ✓
- `version < 1` migration branch updated to include `symbolName` (Task 4 step 5) — covers users upgrading from the original version-0 store. ✓
- Task 2 only replaces `labelWithDate`; `hhmmFrom` and `startOfDay` are left intact. ✓
- `include_router(symbols_router)` placed inside `create_app()`, not lifespan. ✓
