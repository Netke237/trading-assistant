# Chart-Jump Buttons, Strategy Watch Symbol Names, Scan Persistence, Contract Scorecard Detail

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five separate UI/UX gaps Kenneth flagged from three screenshots (Strategy Watch, Portfolio, Trade Card):

1. Strategy Watch table: add a Name (company name) column after Symbol, and a "jump to chart in a new tab" icon button to the left of Symbol.
2. Portfolio "Open positions" table: add the same chart-jump button to the left of Symbol.
3. Screener scan results (Options and Stocks mode) should survive a backend restart, not just a frontend refresh.
4. Step 5 (Volatility + Events) table: add the same chart-jump button to the left of Symbol.
5. Trade Card: (a) give the Contract Scorecard bars (DTE fit, Delta, IV, Liquidity, Spread) the same kind of explanatory caption text the Stock Scorecard bars already have; (b) add the same chart-jump button beside the symbol in the Trade Card header.

**Architecture — what already exists vs. what's missing (confirmed by direct code reading, not guesswork):**

- **Chart-jump button:** No shared component exists. Seven places already duplicate the same `window.open('/chart?symbol=...', '_blank')` snippet inline (Watchlist, step-6-contracts, step-4-prebreakout ×2, step-4-ranking, analysis page, `ContextRail/QuickLook.tsx`), each with its own copy-pasted CSS or inline handler. Since this plan adds it to four more places, Task 1 extracts a shared atom (`components/atoms/OpenChartButton`) instead of adding a fifth through eighth copy — the existing seven are left untouched (out of scope, no regression risk).
- **Company name lookup:** `GET /api/symbol/{symbol}/info` already exists and is already used client-side exactly this way in `ChartTopBar` (`frontend/components/organisms/ChartTopBar/index.tsx:33-40`). `StrategyWatch` objects carry no `company` field, so Strategy Watch is the one page that needs to call it itself.
- **Scan persistence:** Options-mode scans are *already* durably written to Postgres/SQLite (`scan_sessions` table, `ScanSession` model, `_upsert_session`/`restore_from_db` in `backend/app/routers/scan.py`) — restored into memory on every backend startup. But **no HTTP route exposes `_last_result`** to a client, so the frontend has no way to recover it if `localStorage` is empty. Stocks-mode (`backend/app/routers/stock_scan.py`) has **no server-side persistence at all** — nothing to restore even if there were a route.
- **Contract Scorecard captions:** The Stock Scorecard's captions (e.g. "ADX 37D · additive") come from typed "detail" objects (`TrendDetail`, `PullbackDetail`, etc.) that travel backend → frontend and get formatted by small functions in `TradeCard/index.tsx`. `ContractScoreBreakdown` (both the Pydantic schema and the frontend interface) has **no such fields at all** — flat numbers only. The raw ingredients (dte, delta, iv_rank, volume, open_interest, spread_pct, and each metric's preferred band) already exist inside `contract_validator.py`'s scoring functions, they're just never surfaced.

**Tech stack:** Next.js 15 / TypeScript (frontend), FastAPI / Pydantic v2 / SQLAlchemy (backend). CSS Modules throughout, no Tailwind.

**Scope note on testing:** Following this repo's established convention (see `docs/superpowers/plans/2026-07-22-strategy-watch-direction-picker.md`), backend logic changes (contract_validator detail fields, scan persistence) get real pytest coverage. Pure UI insertions in `app/**/page.tsx` files (adding a button/column to an existing table) have no test precedent in this codebase — those are verified via `npm run typecheck` plus a manual browser check, matching how the rest of these pages were built.

**Deliberately out of scope:**
- Refactoring the six *existing* inline chart-button call sites to use the new shared atom — no behavior change needed there, touching them adds regression risk for no benefit.
- Adding the chart-jump button to the Portfolio "History" tab table (separate `HISTORY_COLUMNS`/table, not shown in the screenshot Kenneth flagged) or to Watchlist (already has one).
- Restoring the exact scan **request/context** (universe, direction, horizon picker state) from the backend on recovery — only the **results** (candidates/rejected) are recovered. `scanStore`'s `context` field already persists independently via `localStorage`; the backend recovery path is a fallback for when that's gone, and re-deriving a full request from a stored `ScanResult` isn't possible (the result doesn't carry the original filters).

---

### Task 1: Shared `OpenChartButton` atom

**Files:**
- Create: `frontend/components/atoms/OpenChartButton/index.tsx`
- Create: `frontend/components/atoms/OpenChartButton/OpenChartButton.module.css`

- [ ] **Step 1: Create the component**

```tsx
'use client';

import styles from './OpenChartButton.module.css';

interface OpenChartButtonProps {
  symbol: string;
  className?: string;
}

/** Icon button that opens /chart?symbol=... in a new tab. Mirrors the pattern
 *  already used inline on Watchlist / step-4-ranking / step-6-contracts. */
export function OpenChartButton({ symbol, className }: OpenChartButtonProps) {
  return (
    <button
      type="button"
      className={[styles.chartBtn, className].filter(Boolean).join(' ')}
      title="Open in Chart"
      onClick={(e) => {
        e.stopPropagation();
        window.open(`/chart?symbol=${encodeURIComponent(symbol)}`, '_blank');
      }}
    >
      📈
    </button>
  );
}
```

- [ ] **Step 2: Create the CSS module** (copied verbatim from Watchlist's existing `.chartBtn`, `frontend/app/(frame)/watchlist/page.module.css:179-189`)

```css
.chartBtn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  opacity: 0.4;
  padding: 2px 3px;
  line-height: 1;
  flex-shrink: 0;
}
.chartBtn:hover {
  opacity: 1;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (new file isn't imported anywhere yet, so this just confirms it compiles standalone).

- [ ] **Step 4: Commit**

```bash
git add frontend/components/atoms/OpenChartButton
git commit -m "feat(atoms): add shared OpenChartButton for jump-to-chart affordance"
```

---

### Task 2: Strategy Watch — chart button + Name column

**Files:**
- Modify: `frontend/app/(frame)/strategy-watch/page.tsx`

- [ ] **Step 1: Import the new atom and `api`**

Add to the import block:

```tsx
import { api } from '@/lib/api';
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
```

- [ ] **Step 2: Fetch and cache company names for the watched symbols**

Add state and an effect after the existing `useState` declarations, before `useEffect(() => { refresh(); }, [refresh]);`:

```tsx
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    const missing = Array.from(new Set(watches.map((w) => w.symbol))).filter((s) => !(s in names));
    if (missing.length === 0) return;
    let cancelled = false;
    Promise.all(
      missing.map((s) =>
        api.getSymbolInfo(s).then(
          ({ name }) => [s, name] as const,
          () => [s, s] as const,
        ),
      ),
    ).then((pairs) => {
      if (cancelled) return;
      setNames((cur) => ({ ...cur, ...Object.fromEntries(pairs) }));
    });
    return () => { cancelled = true; };
  }, [watches, names]);
```

This mirrors the fetch-and-fall-back-to-symbol pattern already used in `ChartTopBar/index.tsx:33-40`, batched per unique symbol (avoids one request per row when the same symbol somehow appears twice) and only for symbols not already resolved.

- [ ] **Step 3: Add the chart button column and Name column to the table**

Replace the table header:

```tsx
          <thead><tr><th>Symbol</th><th>Strategy</th><th>Direction</th><th>State</th><th>Enabled</th><th></th></tr></thead>
```

with:

```tsx
          <thead><tr><th></th><th>Symbol</th><th>Name</th><th>Strategy</th><th>Direction</th><th>State</th><th>Enabled</th><th></th></tr></thead>
```

Replace the table row:

```tsx
              <tr key={w.id}>
                <td>{w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
```

with:

```tsx
              <tr key={w.id}>
                <td><OpenChartButton symbol={w.symbol} /></td>
                <td>{w.symbol}</td>
                <td>{names[w.symbol] ?? w.symbol}</td>
                <td>{STRATEGIES.find((s) => s.key === w.strategy_key)?.label ?? w.strategy_key}</td>
```

(The rest of the row — Direction, State, Enabled, Remove — is unchanged; only the two new leading/inserted `<td>`s and the removed old Symbol `<td>` are touched.)

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Manual verification with the dev server**

Run: `cd frontend && npm run dev`, open `/strategy-watch`.
- Confirm each watched row shows a 📈 button to the left of the symbol; clicking it opens `/chart?symbol=<SYMBOL>` in a new tab.
- Confirm the Name column shows a real company name (e.g. "AAPL" → "Apple Inc") for symbols in the curated `KNOWN_NAMES` list, and at minimum the bare symbol (not blank, not "undefined") for anything else.

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/(frame)/strategy-watch/page.tsx"
git commit -m "feat(strategy-watch): add chart-jump button and company name column"
```

---

### Task 3: Portfolio — chart button on the Open Positions table

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`

- [ ] **Step 1: Import the new atom**

```tsx
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
```

- [ ] **Step 2: Add a leading grid track**

Replace:

```tsx
const COLUMNS = '72px 1.6fr 72px 1fr 110px 104px 60px 56px 60px 90px 40px';
```

with:

```tsx
const COLUMNS = '28px 72px 1.6fr 72px 1fr 110px 104px 60px 56px 60px 90px 40px';
```

- [ ] **Step 3: Add the header cell and row cell**

Replace the header row's opening:

```tsx
          <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
            <Text size={11} tone="dim">SYMBOL</Text>
```

with:

```tsx
          <div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
            <span aria-hidden />
            <Text size={11} tone="dim">SYMBOL</Text>
```

Replace the row's opening cell:

```tsx
                <TableRow status={p.status} columns={COLUMNS}>
                  <Data size={13} weight={500}>{p.symbol}</Data>
```

with:

```tsx
                <TableRow status={p.status} columns={COLUMNS}>
                  <OpenChartButton symbol={p.symbol} />
                  <Data size={13} weight={500}>{p.symbol}</Data>
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Manual verification**

Open `/portfolio`, Open tab. Confirm each position row has a 📈 button left of the symbol, all other columns still line up under their headers (the added 28px track shifts everything right by one column — this is the point of the check), and clicking it opens the chart in a new tab.

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/(frame)/portfolio/page.tsx"
git commit -m "feat(portfolio): add chart-jump button to open positions table"
```

---

### Task 4: Step 5 (Volatility + Events) — chart button

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`

- [ ] **Step 1: Import the new atom**

```tsx
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
```

- [ ] **Step 2: Add a leading grid track**

Replace:

```tsx
const COLUMNS = '32px 72px 1fr 120px 70px 110px 80px';
```

with:

```tsx
const COLUMNS = '24px 32px 72px 1fr 120px 70px 110px 80px';
```

- [ ] **Step 3: Add the header cell and row cell**

Replace:

```tsx
        <div className={pageStyles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
          <Text size={11} tone="dim">SYMBOL</Text>
```

with:

```tsx
        <div className={pageStyles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>
          <span aria-hidden />
          <span aria-hidden />
          <Text size={11} tone="dim">SYMBOL</Text>
```

Replace:

```tsx
    <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
      <WatchStar symbol={r.symbol} size="sm" />
      <Data size={13} weight={500}>{r.symbol}</Data>
```

with:

```tsx
    <TableRow key={r.symbol} status={gate} columns={COLUMNS}>
      <OpenChartButton symbol={r.symbol} />
      <WatchStar symbol={r.symbol} size="sm" />
      <Data size={13} weight={500}>{r.symbol}</Data>
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Manual verification**

Run an options scan, open Step 5 (Volatility + Events). Confirm each row shows the 📈 button left of the star icon, columns still align under their headers, and the button opens the chart in a new tab without also toggling the watch star (the star's own `stopPropagation` and the new button's `stopPropagation` should keep the two independent).

- [ ] **Step 6: Commit**

```bash
git add "frontend/app/(frame)/screener/step-5-vol-events/page.tsx"
git commit -m "feat(screener): add chart-jump button to Volatility + Events table"
```

---

### Task 5: Backend — expose the already-persisted last **options** scan over HTTP

**Files:**
- Modify: `backend/app/routers/scan.py`
- Test: `backend/tests/test_scan_persistence.py` (create if it doesn't exist, else extend)

The DB write/restore machinery (`_upsert_session`, `restore_from_db`, called from `main.py`'s `lifespan`) already works and is unaffected by this task. This task only adds a route that reads the already-restored `_last_result` global.

`backend/tests/test_scan_session.py` and `backend/tests/test_persistence.py` already establish a `get_db`-override pattern (in-memory engine, direct row assertions) for this exact kind of scan-session persistence test — skim those first; if their fixture is a better fit than a hand-rolled `ASGITransport` client, use it instead of Step 1's version below.

- [ ] **Step 1: Write the failing test**

Check whether `backend/tests/test_scan_persistence.py` already exists (it's referenced by the existing Alembic migration names but may or may not have a test file — verify with `Glob`/`Read` before assuming). Add:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
import app.routers.scan as scan_router


@pytest.mark.asyncio
async def test_get_last_scan_returns_none_when_no_scan_yet(monkeypatch):
    monkeypatch.setattr(scan_router, "_last_result", None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/scan/last")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_get_last_scan_returns_the_last_result(monkeypatch):
    from app.schemas import ScanResult
    fake = ScanResult(scan_id="SCAN-1", timestamp="2026-07-24T10:00:00", candidates=[], rejected=[])
    monkeypatch.setattr(scan_router, "_last_result", fake)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/scan/last")
    assert resp.status_code == 200
    assert resp.json()["scan_id"] == "SCAN-1"
```

(If the project's existing async test convention differs — e.g. a shared `client` fixture already wraps `ASGITransport` — match that fixture instead of hand-rolling a new `AsyncClient`; check `backend/tests/conftest.py` and an existing `test_scan*.py` file for the actual pattern before writing this step for real.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_scan_persistence.py -v`
Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Add the route**

In `backend/app/routers/scan.py`, add near the other `@router.get` routes (after `restore_from_db`, before `run_scan`):

```python
@router.get('/scan/last', response_model=ScanResult | None)
async def get_last_scan() -> ScanResult | None:
    """Return the most recently completed scan, if any — survives a backend
    restart because _last_result is repopulated from the DB in main.py's
    lifespan startup hook (restore_from_db()). Used by the frontend as a
    fallback when localStorage has no cached scan result."""
    return _last_result
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_scan_persistence.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/scan.py backend/tests/test_scan_persistence.py
git commit -m "feat(scan): expose last completed options scan over GET /api/scan/last"
```

---

### Task 6: Backend — persist and expose the last **stocks-mode** scan

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_stock_scan_persistence.py` (create)

No new DB table/migration is needed — this reuses the existing `scan_sessions` table (`ScanSession` model, `id` is a free-form string primary key) with a different `id` value (`"stock-current"`) so it can't collide with the options-mode row (`id="current"`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_stock_scan_persistence.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
import app.routers.stock_scan as stock_scan_router


@pytest.mark.asyncio
async def test_get_last_stock_scan_returns_none_when_no_scan_yet(monkeypatch):
    monkeypatch.setattr(stock_scan_router, "_last_stock_result", None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stock-scan/last")
    assert resp.status_code == 200
    assert resp.json() is None


@pytest.mark.asyncio
async def test_get_last_stock_scan_returns_the_last_result(monkeypatch):
    from app.schemas.stock_scan import StockScanResult
    fake = StockScanResult(scan_id="SSCAN-1", timestamp="2026-07-24T10:00:00", candidates=[], rejected=[])
    monkeypatch.setattr(stock_scan_router, "_last_stock_result", fake)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stock-scan/last")
    assert resp.status_code == 200
    assert resp.json()["scan_id"] == "SSCAN-1"
```

(Match the actual async-test client fixture convention from `backend/tests/conftest.py` as in Task 5 Step 1.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_stock_scan_persistence.py -v`
Expected: FAIL (module has no `_last_stock_result` attribute / route 404).

- [ ] **Step 3: Add module-level state, upsert/restore helpers, and the route**

In `backend/app/routers/stock_scan.py`, add to the imports. The file's current FastAPI import (line 18) is `from fastapi import APIRouter, HTTPException` — it does **not** already import `Depends` (verified directly; the plan-review round for this document caught an earlier draft wrongly assuming it did), so this needs to change too:

```python
from fastapi import APIRouter, HTTPException, Depends
from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
```

(None of `AsyncSession`/`get_db`/`AsyncSessionLocal`/`ScanSession`/`Depends`/`select` are already imported anywhere in this file — confirmed by full-file grep during planning. Add all of them.)

Add near the top of the module, alongside other module-level state:

```python
_last_stock_request: StockScanRequest | None = None
_last_stock_result: StockScanResult | None = None


async def _upsert_stock_session(db: AsyncSession, req: StockScanRequest | None, result: StockScanResult | None) -> None:
    """Persist the last stocks-mode scan to the same scan_sessions table the
    options-mode scan uses, under a distinct id so the two never collide."""
    await db.merge(
        ScanSession(
            id="stock-current",
            status="complete",
            last_result_json=result.model_dump_json() if result else None,
            last_request_json=req.model_dump_json() if req else None,
        )
    )
    await db.commit()


async def restore_stock_from_db() -> None:
    """Restore _last_stock_result from DB on startup — mirrors scan.py's restore_from_db()."""
    global _last_stock_request, _last_stock_result
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ScanSession).where(ScanSession.id == "stock-current"))
        except Exception:
            return
        row = result.scalar_one_or_none()
        if row is None:
            return
        if row.last_result_json:
            _last_stock_result = StockScanResult.model_validate_json(row.last_result_json)
        if row.last_request_json:
            _last_stock_request = StockScanRequest.model_validate_json(row.last_request_json)
```

Note: `scan.py`'s equivalent options-mode globals are guarded by `_state_lock = asyncio.Lock()` (`scan.py:93`), which serializes *any* concurrent writers to `_last_request`/`_last_result` — not just scheduler-vs-manual, but also two manually-triggered scans overlapping (e.g. two browser tabs, a double-submit). `_last_stock_request`/`_last_stock_result` deliberately skip the equivalent lock here. The residual risk is real but low-severity: two concurrent stock scans could interleave their writes to the module globals and the `stock-current` DB row, so the "last" result shown might not be whichever scan actually finished last — cosmetic last-write-wins, not corruption, since each request still gets its own DB session and a fully-formed `StockScanResult`. Accepted for this task; add the equivalent lock if this ever becomes a real problem in practice (e.g. once a stocks-mode scheduler is added, which would make the race far more routine).

Add the route near `run_stock_scan`:

```python
@router.get('/stock-scan/last', response_model=StockScanResult | None)
async def get_last_stock_scan() -> StockScanResult | None:
    """Return the most recently completed stocks-mode scan, if any."""
    return _last_stock_result
```

Update `run_stock_scan` to persist on completion. Change its signature:

```python
async def run_stock_scan(req: StockScanRequest) -> StockScanResult:
```

to:

```python
async def run_stock_scan(req: StockScanRequest, db: AsyncSession = Depends(get_db)) -> StockScanResult:
```

The function's actual final statement (`stock_scan.py:939-944`, confirmed during planning) is a bare inline constructor, not an assignment to a `result` local:

```python
    return StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
        original_count=original_count, shortlist_truncated=shortlist_truncated,
        direction_banner=_direction_banner,
    )
```

Replace it with:

```python
    result = StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
        original_count=original_count, shortlist_truncated=shortlist_truncated,
        direction_banner=_direction_banner,
    )
    global _last_stock_request, _last_stock_result
    _last_stock_request, _last_stock_result = req, result
    await _upsert_stock_session(db, req, result)
    return result
```

(Re-verify these exact lines against the file before editing — earlier tasks in this plan don't touch `stock_scan.py`, so the line numbers should be stable, but confirm rather than assume.)

- [ ] **Step 4: Wire `restore_stock_from_db()` into startup**

In `backend/app/main.py`, alongside the existing:

```python
    from app.routers.scan import restore_from_db, _scheduler, _scheduled_scan
    status = await restore_from_db()
```

add:

```python
    from app.routers.stock_scan import restore_stock_from_db
    await restore_stock_from_db()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_stock_scan_persistence.py -v`
Expected: PASS.

- [ ] **Step 6: Fix the `stock_client` fixture in `test_stock_scan_router.py` — it has no `get_db` override**

This step is required, not optional — skipping it either 500s existing tests or silently writes into the real local `dev.db` file, depending on what's present in the checkout. `backend/tests/test_stock_scan_router.py` (confirmed during planning) defines two fixtures: `client` (from `conftest.py`, which *does* override `get_db` with an in-memory SQLite session — used elsewhere in this codebase specifically so tests "can NEVER connect to or mutate the real Postgres dev database") and a second, separate `stock_client` fixture local to this file:

```python
app = FastAPI()
app.include_router(stock_scan_router)
return TestClient(app)
```

This bare app has no `get_db` override at all. **Four** tests use it (not three — confirmed by re-grepping the file during this plan's third audit round, which caught the earlier undercount): `test_stock_scan_expands_universe_when_no_symbols_given`, `test_stock_scan_uses_symbols_directly_when_provided`, `test_stock_scan_response_shape`, and `test_stock_scan_bearish_direction_threads_to_signal` (line 231 — a heavier test that drives a real candidate through the pipeline and backtest cache, and will genuinely hit `_upsert_stock_session` on its success path, so it's worth watching specifically in Step 7's verification, not just the first three). Once `run_stock_scan` takes a real `db` dependency and unconditionally persists on every call (Step 3 above), all four will hit `get_db()`'s real default resolution instead of a test override.

The actual override function is `_override_get_db`, defined module-level in `backend/tests/conftest.py:138-140` (confirmed during the plan's audit round). Because `backend/tests/` is a real package (`tests/__init__.py` exists), it must be imported as `from tests.conftest import _override_get_db` — exactly the pattern `backend/tests/test_scan_session.py:13` already uses for other conftest internals (`from tests.conftest import _TestSession, _test_engine`).

`test_stock_scan_router.py`'s current import block (confirmed directly — verified during this plan's third audit round, which caught this gap) is:

```python
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.schemas.stock_scan import StockScanRequest
from app.routers.stock_scan import router as stock_scan_router
```

It imports neither `get_db` nor `_override_get_db` today — **both** need adding, not just `_override_get_db` (using `get_db` as a dependency-override dict key without importing it raises `NameError` the moment any `stock_client`-based test runs, which would silently defeat this entire fix step). Add:

```python
from app.database import get_db
from tests.conftest import _override_get_db
```

and apply the override to `stock_client`:

```python
@pytest.fixture
def stock_client():
    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)
```

(Confirm `_override_get_db`'s exact signature in `conftest.py` before wiring it in — it should be a zero-arg callable/generator matching FastAPI's dependency-override contract, the same shape already used by the `client` fixture's own override, since it's the identical function.)

- [ ] **Step 7: Run the full backend test suite** to catch any regression from adding a `db` dependency to `run_stock_scan`

Run: `cd backend && pytest -k stock_scan -v`
Expected: all pass, including all four `stock_client`-based tests from Step 6 — confirm none of them are hitting a real file-backed DB (watch for a `dev.db` file appearing/changing mtime in the repo root during the run), and pay particular attention to `test_stock_scan_bearish_direction_threads_to_signal`, which actually drives a candidate through to completion and will genuinely call `_upsert_stock_session`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/app/main.py backend/tests/test_stock_scan_persistence.py backend/tests/test_stock_scan_router.py
git commit -m "feat(stock-scan): persist last stocks-mode scan across backend restarts"
```

---

### Task 7: Frontend — recover the last scan from the backend when local state is empty

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/StoreHydration/index.tsx`
- Modify: `frontend/lib/scanStore.ts` (Step 2a — fixes a pre-existing, independent timestamp bug found while researching this task)

- [ ] **Step 1: Add API client methods**

In `frontend/lib/api.ts`, add near `postScan`/`postStockScan`:

```ts
  getLastScan: () => get<ScanResult | null>('/api/scan/last'),
  getLastStockScan: () => get<StockScanResult | null>('/api/stock-scan/last'),
```

Add the `ScanResult` type import at the top of the file (it's already defined in `scanStore.ts`, not duplicated here):

```ts
import type { ScanResult } from '@/lib/scanStore';
```

- [ ] **Step 2: Fetch as a fallback after rehydration**

In `frontend/components/StoreHydration/index.tsx`, replace the `useEffect` body:

```tsx
  useEffect(() => {
    useChartStore.persist.rehydrate();
    useChartAlertStore.persist.rehydrate();
    useScanStore.persist.rehydrate();
    useSettingsStore.persist.rehydrate();
    useStructureStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    useWatchedContractsStore.persist.rehydrate();
    useThemeStore.persist.rehydrate();
    useAutoTradeStore.persist.rehydrate();
    useDrawingStore.persist.rehydrate();
    useRiskStore.persist.rehydrate();
    usePortfolioStore.persist.rehydrate();
    useAlertStore.persist.rehydrate();
    useScanParamsStore.persist.rehydrate();
  }, []);
```

with:

```tsx
  useEffect(() => {
    useChartStore.persist.rehydrate();
    useChartAlertStore.persist.rehydrate();
    useSettingsStore.persist.rehydrate();
    useStructureStore.persist.rehydrate();
    useWatchlistStore.persist.rehydrate();
    useWatchedContractsStore.persist.rehydrate();
    useThemeStore.persist.rehydrate();
    useAutoTradeStore.persist.rehydrate();
    useDrawingStore.persist.rehydrate();
    useRiskStore.persist.rehydrate();
    usePortfolioStore.persist.rehydrate();
    useAlertStore.persist.rehydrate();
    useScanParamsStore.persist.rehydrate();

    (async () => {
      await useScanStore.persist.rehydrate();
      const { scanResult, stockScanResult, setScanResult, setStockScanResult, setScanState } = useScanStore.getState();

      if (!scanResult) {
        try {
          const last = await api.getLastScan();
          if (last) {
            setScanResult(last);
            setScanState('COMPLETED', toLocalWallClock(last.timestamp));
          }
        } catch {
          // No backend reachable yet, or nothing to recover — leave state as-is.
        }
      }

      if (!stockScanResult) {
        try {
          const lastStock = await api.getLastStockScan();
          if (lastStock) {
            setStockScanResult(lastStock);
            // setStockScanResult()'s own auto-stamp (frontend/lib/scanStore.ts:186-190)
            // is fixed to use local wall-clock time in Step 2b below, so by the time
            // this runs it's "now" in the same convention toLocalWallClock() produces —
            // still wrong here specifically, since a recovered scan could be hours old,
            // not just-completed. Overwrite with the real recovered timestamp.
            useScanStore.setState({ stockScanAt: toLocalWallClock(lastStock.timestamp) });
          }
        } catch {
          // Same fallback behavior as above.
        }
      }
    })();
  }, []);
```

Add the `api` import at the top of the file:

```tsx
import { api } from '@/lib/api';
```

Add a small helper above the component, in the same file:

```tsx
/** Backend timestamps are real UTC-offset ISO strings (e.g. "...T18:32:10+00:00",
 *  from Python's `datetime.now(timezone.utc).isoformat()`). Every scanAt/stockScanAt
 *  consumer in this app (ScanIndicator, TopBar, the dashboard rail) parses the stored
 *  string via `new Date(iso)` and expects an *offset-free local wall-clock* string —
 *  the same convention RunScanButton's own `nowLocalISO()` produces for a live scan
 *  (frontend/components/organisms/RunScanButton/index.tsx:27-34). Naively slicing the
 *  backend's UTC string to 19 chars would keep UTC clock digits mislabeled as local,
 *  shifting the displayed time by the viewer's UTC offset — this converts properly. */
function toLocalWallClock(isoWithOffset: string): string {
  const d = new Date(isoWithOffset);
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}
```

`setScanState`'s exact signature is `(s: ScanState, at?: string, durationMs?: number) => void` (`frontend/lib/scanStore.ts`) — confirm this before writing the call for real; pass only `scanState` and the converted `scanAt`, leaving `scanDurationMs` unset since it isn't meaningful for a recovered (not just-completed) scan.

- [ ] **Step 2a: Fix the pre-existing UTC/local bug in `setStockScanResult`'s own auto-stamp**

This is a real, independent bug discovered while researching Task 7 (confirmed during the plan's third audit round, not introduced by this plan) — it affects every *live* stocks-mode scan, not just backend-recovery. `frontend/lib/scanStore.ts:186-190` currently reads:

```ts
      setStockScanResult:  (r) => set((state) => ({
        stockScanResult: r,
        previousStockScanResult: r !== null ? state.stockScanResult : state.previousStockScanResult,
        stockScanAt: r !== null ? new Date().toISOString().slice(0, 19) : state.stockScanAt,
      })),
```

`toISOString()` always returns UTC; slicing off the trailing `Z` leaves bare UTC clock digits with no offset marker. `stockScanAt`'s own doc comment (`scanStore.ts:58`, "ISO-ish local timestamp") and every real consumer (`ScanIndicator`'s `labelWithDate`/`hhmmFrom`, `step-4-stocks/page.tsx`'s `_labelWithDate`) parse it via `new Date(iso)`, which treats an offset-free string as **local** time — so today, a stocks-mode scan that completes at, say, 14:00 local in a UTC+2 zone gets stamped `"...T12:00:00"` (UTC digits) and then re-interpreted as `12:00 local`, a 2-hour display error on every single stock scan. This is separate from — and pre-dates — this plan's recovery-path work, but it uses the same wrong pattern the recovery path had to be fixed away from, so fix it here rather than leaving a shipped comment (see Step 2 above) claiming the live-scan stamp is "correct" when it isn't.

Replace:

```ts
        stockScanAt: r !== null ? new Date().toISOString().slice(0, 19) : state.stockScanAt,
```

with:

```ts
        stockScanAt: r !== null ? toLocalWallClockNow() : state.stockScanAt,
```

adding a small local-getter helper near the top of `scanStore.ts` (mirroring `RunScanButton`'s own `nowLocalISO()` — `frontend/components/organisms/RunScanButton/index.tsx:27-34` — rather than importing across files, since `scanStore.ts` shouldn't depend on an organism):

```ts
function toLocalWallClockNow(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}
```

- [ ] **Step 2b: Manually verify the timezone conversion**, since this is easy to get backwards: pick a UTC offset other than 0 on the dev machine (or reason through it with the system's actual offset), then check two things — (1) run a **live** stocks-mode scan and confirm "Last stock scan" displays the actual local completion time (this is the Step 2a fix); (2) trigger a **recovery** (see Step 4 below) and confirm the displayed "last scan" time matches the wall-clock time the recovered scan actually completed at, not a UTC-shifted value (this is the Step 2 fix).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Manual verification**

1. Run a scan (either mode) so `scanResult`/`stockScanResult` and the backend's `scan_sessions` row are both populated.
2. Open browser devtools → Application → clear `localStorage` key `bamendjou-scan-store` only (leave other keys alone).
3. Reload the page.
4. Confirm the last scan's candidates reappear on Step 4 (ranking or stocks) without re-running a scan — proving the backend fallback path works.
5. Restart the backend process (`Ctrl+C` and re-run uvicorn), *then* clear `localStorage` and reload again — confirms recovery still works after a real process restart, not just from the in-memory globals surviving a hot-reload.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/components/StoreHydration/index.tsx frontend/lib/scanStore.ts
git commit -m "feat(scan): recover last scan results from the backend when local storage is empty"
```

---

### Task 8: Backend — surface per-metric detail on the Contract Scorecard

**Files:**
- Modify: `backend/app/scoring/contract_validator.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/routers/scan.py`
- Test: `backend/tests/test_contract_validator.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_contract_validator.py` already has a helper for exactly this (line 66, confirmed during planning):

```python
def _contract_with_expiry(days_out: int, **overrides):
    c = _base_contract(expiry=(date.today() + timedelta(days=days_out)).isoformat())
    c.update(overrides)
    return c
```

`_contract_with_expiry` returns a full contract dict (via `_base_contract()`, which already fills in bid/ask/volume/open_interest/delta/iv_rank defaults), not a bare date string — use it directly rather than building a contract dict by hand:

Add to `backend/tests/test_contract_validator.py`:

```python
def test_score_card_detail_has_all_five_metrics():
    contract = _contract_with_expiry(
        35, bid=2.40, ask=2.50, delta=0.45, volume=500, open_interest=2000, iv_rank=40,
    )
    card = validate_contract(contract, stock_score=70)
    assert set(card.detail.keys()) == {"dte", "delta", "iv_rank", "liquidity", "spread"}
    assert card.detail["dte"]["dte"] == 35
    assert card.detail["delta"]["delta"] == pytest.approx(0.45)
    assert card.detail["iv_rank"]["iv_rank"] == 40
    assert card.detail["liquidity"]["volume"] == 500
    assert card.detail["liquidity"]["open_interest"] == 2000
    assert card.detail["spread"]["spread_pct"] == pytest.approx((2.50 - 2.40) / 2.45, rel=1e-3)


def test_score_card_detail_present_even_on_hard_reject():
    contract = _contract_with_expiry(
        1, bid=2.40, ask=2.50, delta=0.45, volume=500, open_interest=2000, iv_rank=40,
    )
    card = validate_contract(contract, stock_score=70)
    assert card.status == "REJECT"
    assert "dte" in card.detail  # detail is computed before the reject branch, not skipped
```

(Re-verify `_base_contract`'s actual default field set before writing this for real — pass `**overrides` for whichever of bid/ask/volume/open_interest/delta/iv_rank aren't already sensible defaults, so the test isn't fighting the helper's own baseline.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_contract_validator.py -k detail -v`
Expected: FAIL — `ContractScoreCard` has no `detail` attribute.

- [ ] **Step 3: Implement**

In `backend/app/scoring/contract_validator.py`:

**These are edits to existing functions, not full replacements** — the code blocks below show every line that must be present in the final version, including the pre-existing explanatory comments already in the file (round-4 audit caught an earlier draft of this plan reproducing these functions without them, which would have silently deleted real reasoning about edge cases from the codebase). Add or change only what's called out; do not drop any comment that isn't explicitly mentioned as removed.

Add `detail: dict = field(default_factory=dict)` to `ContractScoreCard`, preserving the existing per-field comments on `reject_reasons`/`soft_flags`:

```python
@dataclass
class ContractScoreCard:
    contract_id: str            # canonical ID: SYMBOL|STRIKE|EXPIRY|C/P
    symbol: str
    strike: float
    expiry: str
    is_call: bool
    score: int                  # 0–100 aggregate
    status: Status
    reject_reasons: list[str] = field(default_factory=list)  # hard-reject labels
    soft_flags: list[str] = field(default_factory=list)       # soft-rank labels
    breakdown: ContractScoreBreakdown = field(
        default_factory=lambda: ContractScoreBreakdown(0, 0, 0, 0, 0, 0)
    )
    detail: dict = field(default_factory=dict)
```

Make `_score_spread` and `_score_dte` also return the raw metric value they already compute internally (avoids re-deriving `spread_pct`/`dte` a second time and risking drift from the score logic). Only the signature and final `return` line change in each — every other line, including comments, is unchanged from what's currently in the file:

```python
def _score_spread(contract: dict, cfg: dict) -> tuple[int, float, list[str]]:
    sr = cfg["soft_rank"]
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    flags = []

    max_pct = sr["preferred_spread_pct_max"]
    score = max(0, int((1 - spread_pct / max_pct) * 100)) if spread_pct < max_pct else 0
    score = min(score, 100)

    if spread_pct > max_pct:
        flags.append("spread_elevated")
    return score, spread_pct, flags
```

```python
def _score_dte(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
    sr = cfg["soft_rank"]
    expiry_str = contract.get("expiry", "")
    flags = []
    try:
        dte = (date.fromisoformat(expiry_str) - date.today()).days
    except (ValueError, TypeError):
        return 0, 0, ["dte_parse_error"]

    d_min = sr["preferred_dte_min"]
    d_max = sr["preferred_dte_max"]
    half_range = (d_max - d_min) / 2

    if d_min <= dte <= d_max:
        centre = (d_min + d_max) / 2
        # half_range is 0 when a hold-derived override collapses min==max (e.g. a
        # Custom range typed as the same day twice) — dte sits exactly on centre
        # in that case, so it's a perfect score, not a divide by zero.
        score = 100 if half_range == 0 else int(100 * (1 - abs(dte - centre) / half_range))
    else:
        # A flat score here previously scored a 1-day miss identically to a
        # 100-day miss (and higher than sitting exactly on the boundary, which
        # scores 0 above) — decay linearly from 25 at the boundary to 0 over a
        # span equal to half_range, so misses are graded by how far off they are.
        distance = d_min - dte if dte < d_min else dte - d_max
        decay_span = half_range if half_range > 0 else 1
        score = max(0, int(25 * (1 - distance / decay_span)))
        flags.append("dte_outside_preferred")
    return score, dte, flags
```

In `validate_contract`, update the call sites and build the `detail` dict before either return:

```python
    liq_score, oi_score_val, liq_flags = _score_liquidity(contract, cfg)
    spread_score, spread_pct, spread_flags = _score_spread(contract, cfg)
    delta_score, delta_flags = _score_delta(contract, cfg)
    dte_score, dte, dte_flags = _score_dte(contract, cfg)
    iv_score, iv_flags = _score_iv_rank(contract, cfg)

    sr = cfg["soft_rank"]
    detail = {
        "dte": {
            "dte": dte,
            "preferred_min": sr["preferred_dte_min"],
            "preferred_max": sr["preferred_dte_max"],
        },
        "delta": {
            "delta": abs(contract.get("delta") or 0),
            "preferred_min": sr["preferred_delta_min"],
            "preferred_max": sr["preferred_delta_max"],
        },
        "iv_rank": {
            "iv_rank": contract.get("iv_rank"),
            "preferred_max": sr["preferred_iv_rank_max"],
        },
        "liquidity": {
            "volume": contract.get("volume") or 0,
            "open_interest": contract.get("open_interest") or 0,
            "preferred_volume_min": sr["preferred_volume_min"],
            "preferred_oi_min": sr["preferred_oi_min"],
        },
        "spread": {
            "spread_pct": spread_pct,
            "preferred_max_pct": sr["preferred_spread_pct_max"],
        },
    }
```

(`validate_contract` already has an `sr = cfg["soft_rank"]` binding, but it's inside the `if ov:` override-handling block near the top of the function, so it only executes when override params are actually passed — not the common case. The `sr = cfg["soft_rank"]` line shown above is added *outside* that conditional, alongside the `_score_*` calls, so for most calls it's the first (and only) binding of `sr`, not a redundant re-assignment. Either way it's the same dict object `cfg["soft_rank"]` always refers to, so there's no real collision or shadowing bug — just add the line as shown.)

Then add `detail=detail` to **both** `ContractScoreCard(...)` construction sites (the hard-reject early return and the final PASS/CAUTION/REJECT return) — both already exist as separate `return ContractScoreCard(...)` blocks; just add the one new kwarg to each.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_contract_validator.py -v`
Expected: all pass, including the two new tests.

- [ ] **Step 5: Add Pydantic detail models and extend `ContractScoreBreakdown`**

In `backend/app/schemas/__init__.py`, add near the existing `TrendDetail`/`PullbackDetail`/etc. models:

```python
class DteDetail(BaseModel):
    dte: int
    preferred_min: int
    preferred_max: int


class DeltaDetail(BaseModel):
    delta: float
    preferred_min: float
    preferred_max: float


class IvRankDetail(BaseModel):
    iv_rank: float | None = None
    preferred_max: float


class LiquidityDetail(BaseModel):
    volume: int
    open_interest: int
    preferred_volume_min: int
    preferred_oi_min: int


class SpreadDetail(BaseModel):
    spread_pct: float
    preferred_max_pct: float
```

Replace:

```python
class ContractScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    dteFit: int
    delta: int
    ivAttractiveness: int
    liquidity: int
    spread: int
```

with:

```python
class ContractScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    dteFit: int
    delta: int
    ivAttractiveness: int
    liquidity: int
    spread: int
    dteDetail: DteDetail | None = None
    deltaDetail: DeltaDetail | None = None
    ivDetail: IvRankDetail | None = None
    liquidityDetail: LiquidityDetail | None = None
    spreadDetail: SpreadDetail | None = None
```

- [ ] **Step 6: Wire the detail through at all three construction sites in `scan.py`**

Add the new schema names to `scan.py`'s existing import of detail models (find the line already importing `TrendDetail, PullbackDetail, TriggerDetail, EventDetail, VolDetail` from `app.schemas` and extend it):

```python
from app.schemas import (
    ...,
    TrendDetail, PullbackDetail, TriggerDetail, EventDetail, VolDetail,
    DteDetail, DeltaDetail, IvRankDetail, LiquidityDetail, SpreadDetail,
)
```

(Match whatever the actual existing multi-line import statement looks like — read it first rather than assuming a single form; there may be several import statements from `app.schemas` in this file.)

These three sites differ in **both** variable name and indentation — they are not one block copy-pasted three times, so each needs its own literal diff (all three re-verified directly against the file during this plan's third audit round):

**Site 1 — `scan.py:581-587`** (`contract_card`, 8-space indent — top-level field of the main `TradeCardData(...)` construction). Change:

```python
        contractBreakdown=ContractScoreBreakdown(
            dteFit=contract_card.breakdown.dte_score,
            delta=contract_card.breakdown.delta_score,
            ivAttractiveness=contract_card.breakdown.iv_rank_score,
            liquidity=contract_card.breakdown.liquidity_score,
            spread=contract_card.breakdown.spread_score,
        ),
```

to:

```python
        contractBreakdown=ContractScoreBreakdown(
            dteFit=contract_card.breakdown.dte_score,
            delta=contract_card.breakdown.delta_score,
            ivAttractiveness=contract_card.breakdown.iv_rank_score,
            liquidity=contract_card.breakdown.liquidity_score,
            spread=contract_card.breakdown.spread_score,
            dteDetail=      _safe(DteDetail,       contract_card.detail.get("dte")),
            deltaDetail=    _safe(DeltaDetail,     contract_card.detail.get("delta")),
            ivDetail=       _safe(IvRankDetail,    contract_card.detail.get("iv_rank")),
            liquidityDetail=_safe(LiquidityDetail, contract_card.detail.get("liquidity")),
            spreadDetail=   _safe(SpreadDetail,    contract_card.detail.get("spread")),
        ),
```

**Site 2 — `scan.py:689-695`** (`alt_card`, 12-space indent — inside `alts.append(AlternativeContract(...))` within `for alt_card, alt_c in runner_ups:`). Change:

```python
            contractBreakdown=ContractScoreBreakdown(
                dteFit=alt_card.breakdown.dte_score,
                delta=alt_card.breakdown.delta_score,
                ivAttractiveness=alt_card.breakdown.iv_rank_score,
                liquidity=alt_card.breakdown.liquidity_score,
                spread=alt_card.breakdown.spread_score,
            ),
```

to:

```python
            contractBreakdown=ContractScoreBreakdown(
                dteFit=alt_card.breakdown.dte_score,
                delta=alt_card.breakdown.delta_score,
                ivAttractiveness=alt_card.breakdown.iv_rank_score,
                liquidity=alt_card.breakdown.liquidity_score,
                spread=alt_card.breakdown.spread_score,
                dteDetail=      _safe(DteDetail,       alt_card.detail.get("dte")),
                deltaDetail=    _safe(DeltaDetail,     alt_card.detail.get("delta")),
                ivDetail=       _safe(IvRankDetail,    alt_card.detail.get("iv_rank")),
                liquidityDetail=_safe(LiquidityDetail, alt_card.detail.get("liquidity")),
                spreadDetail=   _safe(SpreadDetail,    alt_card.detail.get("spread")),
            ),
```

**Site 3 — `scan.py:720-726`** (`contract_card` again, but 12-space indent this time — also inside an `alts.append(AlternativeContract(...))`, in the separate bear-spread alternative branch). This is easy to mis-fix by reusing Site 1's 8-space block on the wrong indentation level, or Site 2's block with the wrong variable name — it needs its own version. Change:

```python
            contractBreakdown=ContractScoreBreakdown(
                dteFit=contract_card.breakdown.dte_score,
                delta=contract_card.breakdown.delta_score,
                ivAttractiveness=contract_card.breakdown.iv_rank_score,
                liquidity=contract_card.breakdown.liquidity_score,
                spread=contract_card.breakdown.spread_score,
            ),
```

to:

```python
            contractBreakdown=ContractScoreBreakdown(
                dteFit=contract_card.breakdown.dte_score,
                delta=contract_card.breakdown.delta_score,
                ivAttractiveness=contract_card.breakdown.iv_rank_score,
                liquidity=contract_card.breakdown.liquidity_score,
                spread=contract_card.breakdown.spread_score,
                dteDetail=      _safe(DteDetail,       contract_card.detail.get("dte")),
                deltaDetail=    _safe(DeltaDetail,     contract_card.detail.get("delta")),
                ivDetail=       _safe(IvRankDetail,    contract_card.detail.get("iv_rank")),
                liquidityDetail=_safe(LiquidityDetail, contract_card.detail.get("liquidity")),
                spreadDetail=   _safe(SpreadDetail,    contract_card.detail.get("spread")),
            ),
```

(Line numbers as read during planning and re-confirmed directly against the file during the third audit round — re-locate all three before editing in case they've drifted since.)

- [ ] **Step 7: Run backend tests**

Run: `cd backend && pytest tests/test_contract_validator.py tests/test_scan.py -v` (adjust the second path to whatever the actual scan-router test file is named — check with `Glob` first)
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/scoring/contract_validator.py backend/app/schemas/__init__.py backend/app/routers/scan.py backend/tests/test_contract_validator.py
git commit -m "feat(contracts): surface per-metric detail on the Contract Scorecard breakdown"
```

---

### Task 9: Frontend — render Contract Scorecard captions

**Files:**
- Modify: `frontend/types/domain.ts`
- Modify: `frontend/components/organisms/TradeCard/index.tsx`

- [ ] **Step 1: Add the detail types**

In `frontend/types/domain.ts`, add near the existing `TrendDetail`/etc.:

```ts
export interface DteDetail {
  dte:           number;
  preferred_min: number;
  preferred_max: number;
}
export interface DeltaDetail {
  delta:         number;
  preferred_min: number;
  preferred_max: number;
}
export interface IvRankDetail {
  iv_rank:       number | null;
  preferred_max: number;
}
export interface LiquidityDetail {
  volume:               number;
  open_interest:        number;
  preferred_volume_min: number;
  preferred_oi_min:     number;
}
export interface SpreadDetail {
  spread_pct:       number;
  preferred_max_pct: number;
}
```

Replace:

```ts
export interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
}
```

with:

```ts
export interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
  dteDetail?:       DteDetail;
  deltaDetail?:     DeltaDetail;
  ivDetail?:        IvRankDetail;
  liquidityDetail?: LiquidityDetail;
  spreadDetail?:    SpreadDetail;
}
```

- [ ] **Step 2: Add formatter functions**

In `frontend/components/organisms/TradeCard/index.tsx`, extend the type import:

```tsx
import type { TradeCardData, TargetLevel, TriggerDetail, PullbackDetail, TrendDetail, EventDetail, VolDetail, DteDetail, DeltaDetail, IvRankDetail, LiquidityDetail, SpreadDetail } from '@/types/domain';
```

Add near the existing `*DetailText` functions (after `volDetailText`):

```tsx
function dteDetailText(d?: DteDetail): string | undefined {
  if (!d) return undefined;
  return `${d.dte}d · target ${d.preferred_min}-${d.preferred_max}d`;
}

function deltaDetailText(d?: DeltaDetail): string | undefined {
  if (!d) return undefined;
  return `Δ${d.delta.toFixed(2)} · target ${d.preferred_min.toFixed(2)}-${d.preferred_max.toFixed(2)}`;
}

function ivDetailText(d?: IvRankDetail): string | undefined {
  if (!d) return undefined;
  if (d.iv_rank == null) return 'No IV rank data';
  return `IV Rank ${d.iv_rank.toFixed(0)} · pref ≤${d.preferred_max.toFixed(0)}`;
}

function liquidityDetailText(d?: LiquidityDetail): string | undefined {
  if (!d) return undefined;
  return `Vol ${d.volume.toLocaleString()} · OI ${d.open_interest.toLocaleString()} · pref ≥${d.preferred_volume_min.toLocaleString()}/${d.preferred_oi_min.toLocaleString()}`;
}

function spreadDetailText(d?: SpreadDetail): string | undefined {
  if (!d) return undefined;
  return `Spread ${(d.spread_pct * 100).toFixed(1)}% · pref ≤${(d.preferred_max_pct * 100).toFixed(0)}%`;
}
```

- [ ] **Step 3: Wire the captions into `contractBars`**

Replace:

```tsx
const contractBars = [
  { label: 'DTE fit', value: data.contractBreakdown.dteFit },
  { label: 'Delta', value: data.contractBreakdown.delta },
  { label: 'IV', value: data.contractBreakdown.ivAttractiveness },
  { label: 'Liquidity', value: data.contractBreakdown.liquidity },
  { label: 'Spread', value: data.contractBreakdown.spread },
];
```

with:

```tsx
const contractBars = [
  { label: 'DTE fit', value: data.contractBreakdown.dteFit, detailText: dteDetailText(data.contractBreakdown.dteDetail) },
  { label: 'Delta', value: data.contractBreakdown.delta, detailText: deltaDetailText(data.contractBreakdown.deltaDetail) },
  { label: 'IV', value: data.contractBreakdown.ivAttractiveness, detailText: ivDetailText(data.contractBreakdown.ivDetail) },
  { label: 'Liquidity', value: data.contractBreakdown.liquidity, detailText: liquidityDetailText(data.contractBreakdown.liquidityDetail) },
  { label: 'Spread', value: data.contractBreakdown.spread, detailText: spreadDetailText(data.contractBreakdown.spreadDetail) },
];
```

No change needed in `ScoreCardPanel` — it already renders `b.detailText` generically (`frontend/components/molecules/ScoreCardPanel/index.tsx:65-67`), which is exactly why the Stock Scorecard captions work today.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Run existing TradeCard tests**

Run: `cd frontend && npm run test -- --testPathPattern=TradeCard`
Expected: pass (check whether any existing snapshot/assertion hard-codes the old `contractBars` shape without `detailText` — if so, update the fixture data used by that test rather than loosening the assertion).

- [ ] **Step 6: Manual verification**

Open a Trade Card (Step 7). Confirm the Contract scorecard's five bars each now show a caption line underneath, in the same visual style as the Stock Scorecard's captions (e.g. "17d · target 25-45d" under DTE fit, "Δ0.52 · target 0.35-0.55" under Delta).

- [ ] **Step 7: Commit**

```bash
git add frontend/types/domain.ts frontend/components/organisms/TradeCard/index.tsx
git commit -m "feat(trade-card): render explanatory captions under Contract Scorecard bars"
```

---

### Task 10: Trade Card — chart button beside the symbol

**Files:**
- Modify: `frontend/components/molecules/SymbolHeader/index.tsx`
- Modify: `frontend/components/organisms/TradeCard/index.tsx`

`SymbolHeader` is shared by three call sites (`TradeCard`, `step-4-ranking`, `analysis` page). Adding the button as an opt-in prop (default off) keeps the other two call sites — which may already have their own chart-jump affordance elsewhere on their page — unchanged, avoiding a duplicate button or unwanted layout shift there.

- [ ] **Step 1: Add an opt-in prop to `SymbolHeader`**

Replace:

```tsx
interface SymbolHeaderProps {
  ticker: string;
  company: string;
  price: number;
  direction: Direction;
  status: Status;
  /** Ticker size. 14 for tables/rails, 24 for TradeCard hero. */
  size?: 14 | 18 | 24;
  className?: string;
}
```

with:

```tsx
interface SymbolHeaderProps {
  ticker: string;
  company: string;
  price: number;
  direction: Direction;
  status: Status;
  /** Ticker size. 14 for tables/rails, 24 for TradeCard hero. */
  size?: 14 | 18 | 24;
  /** Show a jump-to-chart icon button beside the ticker. Off by default so
   *  existing call sites (step-4-ranking, analysis page) are unaffected. */
  showChartButton?: boolean;
  className?: string;
}
```

Add the import:

```tsx
import { OpenChartButton } from '@/components/atoms/OpenChartButton';
```

Replace:

```tsx
export function SymbolHeader({
  ticker,
  company,
  price,
  direction,
  status,
  size = 18,
  className,
}: SymbolHeaderProps) {
  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')}>
      <div className={styles.leftGroup}>
        <Data size={size} weight={500} className={styles.ticker}>
          {ticker}
        </Data>
```

with:

```tsx
export function SymbolHeader({
  ticker,
  company,
  price,
  direction,
  status,
  size = 18,
  showChartButton = false,
  className,
}: SymbolHeaderProps) {
  return (
    <div className={[styles.row, className].filter(Boolean).join(' ')}>
      <div className={styles.leftGroup}>
        {showChartButton && <OpenChartButton symbol={ticker} />}
        <Data size={size} weight={500} className={styles.ticker}>
          {ticker}
        </Data>
```

- [ ] **Step 2: Enable it in the Trade Card call site**

In `frontend/components/organisms/TradeCard/index.tsx`, at the `<SymbolHeader ...>` usage (around line 237), add the prop:

```tsx
        <SymbolHeader
          ticker={data.symbol}
          company={data.company}
          showChartButton
          ...
```

(Insert `showChartButton` alongside the existing props — keep the rest of that call site's props exactly as they already are; only adding the one new prop.)

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Run existing TradeCard tests**

`frontend/components/molecules/SymbolHeader/` has no test file of its own (confirmed during planning) — `--testPathPattern="SymbolHeader|TradeCard"` would silently only run the TradeCard side, giving false confidence about SymbolHeader coverage that doesn't exist. Just run:

Run: `cd frontend && npm run test -- --testPathPattern=TradeCard`
Expected: pass (the new prop defaults to `false`, so `step-4-ranking`'s and `analysis`'s existing renders — which don't have a test file either, per the same check — are unaffected in practice; the manual verification in Step 5 below is what actually confirms that for this task).

- [ ] **Step 5: Manual verification**

Open Step 7 (Trade Card). Confirm a 📈 button now appears immediately to the left of the ticker in the card header, and clicking it opens `/chart?symbol=<SYMBOL>` in a new tab. Then check Step 4 (Ranking) and the Analysis page — confirm neither shows the new button (proving the opt-in default didn't leak).

`.leftGroup` in `SymbolHeader.module.css` uses `align-items: baseline`, tuned for its current text-only children (`Data`/`Text`) — a plain `<button>` has no text baseline of its own and may sit visually high or low next to the 24px hero ticker. Specifically check this alignment; if it looks off, add `align-self: center` (or similar) to `OpenChartButton`'s own CSS via the existing `className` override prop rather than changing `.leftGroup`'s shared `align-items` (which would also affect the Status/Direction pills further along the row).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/molecules/SymbolHeader/index.tsx frontend/components/organisms/TradeCard/index.tsx
git commit -m "feat(trade-card): add chart-jump button beside the symbol header"
```

---

## Post-implementation checklist

- [ ] `cd frontend && npm run typecheck` — clean
- [ ] `cd frontend && npm run test` — all pass
- [ ] `cd backend && pytest` — all pass
- [ ] Manual browser pass: Strategy Watch (button + name column), Portfolio open positions (button), Step 5 Vol+Events (button), Trade Card (contract captions + button), all four chart buttons actually open `/chart?symbol=...` in a new tab
- [ ] Manual persistence check: run a scan (both modes), restart the backend process, clear `localStorage`'s `bamendjou-scan-store` key, reload, confirm results reappear
