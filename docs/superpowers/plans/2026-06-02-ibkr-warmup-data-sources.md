# IBKR Warm-Up Fix + Data Source Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix intermittent IBKR IV data (Rank + Percentile) by adding a snapshot warm-up step, then expose Tradier / IBKR / yfinance availability as a panel in the Context Rail that refreshes after every scan.

**Architecture:** A module-level warm-up cache in `ibkr.py` handles the one-time subscription cost per symbol per process session. A new `GET /api/data-sources` endpoint probes each source and returns structured status. The frontend fetches this on mount and after scan completion, rendering it as a `RailSection` below Portfolio in `QuickLook.tsx`.

**Tech Stack:** Python 3.11, FastAPI, httpx, pytest — backend. TypeScript 5.7, Next.js 15 App Router, Zustand, CSS Modules — frontend.

---

### Task 1: IBKR snapshot warm-up cache

**Files:**
- Modify: `backend/app/data/ibkr.py`

The IBKR snapshot endpoint `/iserver/marketdata/snapshot` starts a field subscription on the first call but returns no data until the subscription is active. A second request (made after a short delay) returns the actual values. We need to track which `(conid, fields)` pairs have already been warmed so we pay the delay only once per process session.

- [ ] **Step 1: Add `_snapshot_warmed` cache and lock at the top of the module-level caches block**

In `backend/app/data/ibkr.py`, after the `_conid_lock` line (line 39), add:

```python
# Warm-up cache: set of conids whose snapshot subscription is already active.
# A freshly started subscription returns no data on the first request.
# Subsequent requests (after ~1.5s) return live data.
_snapshot_warmed: set[int] = set()
_snapshot_lock = threading.Lock()
```

- [ ] **Step 2: Update `fetch_iv_metrics_ibkr` to perform warm-up on first access**

Replace the entire `fetch_iv_metrics_ibkr` function (lines 254–295) with:

```python
def fetch_iv_metrics_ibkr(symbol: str) -> dict | None:
    """Fetch IV Rank (field 7308) and IV Percentile (field 7309) from IBKR.

    Returns {"ivRank": float, "ivPercentile": float} or None if unavailable.

    On the first call for a given conid the snapshot endpoint only starts the
    subscription — it returns no data yet.  We fire a silent warm-up request,
    wait 1.5 seconds, then make the real request.  Subsequent calls reuse the
    active subscription and skip the warm-up.
    """
    if not ibkr_available():
        return None

    conid_val = _conid(symbol)
    if conid_val is None:
        return None

    FIELDS = "7308,7309"

    with _snapshot_lock:
        needs_warmup = conid_val not in _snapshot_warmed

    if needs_warmup:
        # Fire the subscribe-only request (data will be empty — that is expected)
        try:
            httpx.get(
                f"{_BASE}/iserver/marketdata/snapshot",
                params={"conids": conid_val, "fields": FIELDS},
                verify=False,
                timeout=_TIMEOUT,
            )
        except Exception:
            pass  # best-effort; the real request will fail gracefully if needed

        time.sleep(1.5)

        with _snapshot_lock:
            _snapshot_warmed.add(conid_val)

    try:
        resp = httpx.get(
            f"{_BASE}/iserver/marketdata/snapshot",
            params={"conids": conid_val, "fields": FIELDS},
            verify=False,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
        if not items or not isinstance(items, list):
            return None

        item = items[0]
        raw_rank = item.get("7308")
        raw_pct = item.get("7309")

        if raw_rank is None or raw_pct is None:
            return None

        # Fields can be "--" or other non-numeric strings
        try:
            iv_rank = float(raw_rank)
            iv_pct = float(raw_pct)
        except (ValueError, TypeError):
            return None

        return {"ivRank": iv_rank, "ivPercentile": iv_pct}
    except Exception as exc:
        logger.debug("IBKR IV metrics fetch failed for %s: %s", symbol, exc)
        return None
```

- [ ] **Step 3: Verify the module still imports cleanly**

```bash
cd backend && python -c "from app.data.ibkr import fetch_iv_metrics_ibkr, ibkr_available; print('OK')"
```
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/data/ibkr.py
git commit -m "fix(ibkr): add snapshot warm-up cache for IV Rank/Percentile fields"
```

---

### Task 2: Backend `GET /api/data-sources` endpoint

**Files:**
- Create: `backend/app/routers/data_sources.py`
- Create: `backend/tests/test_data_sources.py`
- Modify: `backend/app/main.py` (add import + `app.include_router`)

The endpoint probes each data source and returns a list of status objects. It must never raise — any probe failure returns `"unavailable"` for that source. The response is consumed by the frontend panel.

**Response shape:**
```json
[
  {
    "id": "tradier",
    "label": "Tradier",
    "status": "ok",
    "provides": ["candles", "chains", "greeks", "news", "earnings"],
    "detail": null
  },
  {
    "id": "ibkr",
    "label": "IBKR",
    "status": "unavailable",
    "provides": ["iv_rank", "iv_percentile", "intraday_bars"],
    "detail": "Gateway unreachable"
  },
  {
    "id": "yfinance",
    "label": "yfinance",
    "status": "ok",
    "provides": ["iv_fallback", "earnings_fallback"],
    "detail": null
  }
]
```

- [ ] **Step 1: Write the failing test first**

Create `backend/tests/test_data_sources.py`:

```python
"""Tests for GET /api/data-sources."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app

client = TestClient(app)


def test_data_sources_returns_list():
    """Endpoint always returns a list of 3 source objects."""
    with (
        patch("app.routers.data_sources._probe_tradier", return_value=("ok", None)),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("ok", None)),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3
    ids = {d["id"] for d in data}
    assert ids == {"tradier", "ibkr", "yfinance"}


def test_data_sources_fields():
    """Each item has id, label, status, provides, detail."""
    with (
        patch("app.routers.data_sources._probe_tradier", return_value=("ok", None)),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("unavailable", "Gateway unreachable")),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    ibkr = next(d for d in resp.json() if d["id"] == "ibkr")
    assert ibkr["status"] == "unavailable"
    assert ibkr["detail"] == "Gateway unreachable"
    assert isinstance(ibkr["provides"], list)
    assert len(ibkr["provides"]) > 0


def test_data_sources_never_raises_on_probe_exception():
    """If a probe throws, the endpoint still returns 200 with status=error."""
    with (
        patch("app.routers.data_sources._probe_tradier", side_effect=Exception("boom")),
        patch("app.routers.data_sources._probe_ibkr",    return_value=("ok", None)),
        patch("app.routers.data_sources._probe_yfinance", return_value=("ok", None)),
    ):
        resp = client.get("/api/data-sources")
    assert resp.status_code == 200
    tradier = next(d for d in resp.json() if d["id"] == "tradier")
    assert tradier["status"] == "error"
```

- [ ] **Step 2: Run test to confirm it fails (router not yet registered)**

```bash
cd backend && pytest tests/test_data_sources.py -v
```
Expected: 3 errors — `ImportError` or 404s because `app.routers.data_sources` does not exist yet.

- [ ] **Step 3: Create `backend/app/routers/data_sources.py`**

```python
"""GET /api/data-sources — probe each data source and return availability."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class DataSourceStatus(BaseModel):
    id: str
    label: str
    status: str          # "ok" | "unavailable" | "error" | "unconfigured"
    provides: list[str]
    detail: str | None = None


# ── Probes ────────────────────────────────────────────────────────────────────


def _probe_tradier() -> tuple[str, str | None]:
    """Return (status, detail).  Checks that the API token is set."""
    token = os.environ.get("TRADIER_API_TOKEN", "").strip()
    if not token:
        return "unconfigured", "TRADIER_API_TOKEN not set"
    # Tradier is always reachable when the token is present; a lightweight
    # liveness check would require a live HTTP call which is too slow for the
    # panel.  Token presence is sufficient — failures surface as scan errors.
    return "ok", None


def _probe_ibkr() -> tuple[str, str | None]:
    """Return (status, detail).  Calls ibkr_available() — cached 60 s."""
    from app.data.ibkr import ibkr_available
    available = ibkr_available()
    if available:
        return "ok", None
    return "unavailable", "Gateway unreachable or not authenticated"


def _probe_yfinance() -> tuple[str, str | None]:
    """Return (status, detail).  Checks that yfinance can be imported."""
    try:
        import yfinance  # noqa: F401
        return "ok", None
    except ImportError:
        return "unavailable", "yfinance not installed"


# ── Route ─────────────────────────────────────────────────────────────────────

_SOURCES: list[dict] = [
    {
        "id": "tradier",
        "label": "Tradier",
        "provides": ["candles", "option chains", "greeks", "news", "earnings"],
        "probe": _probe_tradier,
    },
    {
        "id": "ibkr",
        "label": "IBKR",
        "provides": ["IV rank", "IV percentile", "intraday bars"],
        "probe": _probe_ibkr,
    },
    {
        "id": "yfinance",
        "label": "yfinance",
        "provides": ["IV fallback", "earnings fallback"],
        "probe": _probe_yfinance,
    },
]


@router.get("/api/data-sources", response_model=list[DataSourceStatus])
def get_data_sources() -> list[DataSourceStatus]:
    """Probe each data source and return its availability status."""
    results: list[DataSourceStatus] = []
    for src in _SOURCES:
        try:
            status, detail = src["probe"]()
        except Exception as exc:
            logger.warning("Data source probe failed for %s: %s", src["id"], exc)
            status, detail = "error", str(exc)
        results.append(DataSourceStatus(
            id=src["id"],
            label=src["label"],
            status=status,
            provides=src["provides"],
            detail=detail,
        ))
    return results
```

- [ ] **Step 4: Register the router in `backend/app/main.py`**

After the existing `from app.routers.risk_settings import router as risk_settings_router` line (line 30), add:

```python
from app.routers.data_sources  import router as data_sources_router
```

After `app.include_router(risk_settings_router)` (line 100), add:

```python
    app.include_router(data_sources_router)
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
cd backend && pytest tests/test_data_sources.py -v
```
Expected:
```
tests/test_data_sources.py::test_data_sources_returns_list PASSED
tests/test_data_sources.py::test_data_sources_fields PASSED
tests/test_data_sources.py::test_data_sources_never_raises_on_probe_exception PASSED
3 passed
```

- [ ] **Step 6: Smoke-test the live endpoint (requires the backend running)**

```bash
curl http://localhost:8000/api/data-sources
```
Expected: JSON array with 3 objects, each with `id`, `label`, `status`, `provides`, `detail`.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/routers/data_sources.py tests/test_data_sources.py app/main.py
git commit -m "feat(api): add GET /api/data-sources to probe Tradier/IBKR/yfinance"
```

---

### Task 3: Frontend data source panel

**Files:**
- Modify: `frontend/lib/api.ts` — add `getDataSources()`
- Modify: `frontend/components/organisms/ContextRail/QuickLook.tsx` — add Data Sources section
- Modify: `frontend/components/organisms/ContextRail/QuickLook.module.css` — styles for the new section

The panel shows three rows (Tradier · IBKR · yfinance) with a colored status dot and a single-line label. It fetches on mount and re-fetches whenever a scan finishes (`scanState` changes to `'COMPLETED'` or `'FAILED'`).

**Status dot colors:**
- `ok` → `var(--pass)` (green)
- `unconfigured` → `var(--caution)` (yellow)
- `unavailable` / `error` → `var(--reject)` (red)

- [ ] **Step 1: Add `getDataSources` to `frontend/lib/api.ts`**

After the `getSectors` line (line 45 in the current file), add a `DataSourceInfo` type and the `getDataSources` call:

```typescript
export interface DataSourceInfo {
  id: string;
  label: string;
  status: 'ok' | 'unavailable' | 'error' | 'unconfigured';
  provides: string[];
  detail: string | null;
}
```

Inside the `api` object, after `getSectors: () => get<SectorTile[]>('/api/sectors'),`, add:

```typescript
getDataSources: () => get<DataSourceInfo[]>('/api/data-sources'),
```

- [ ] **Step 2: Run typecheck to confirm the addition is clean**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 3: Add the Data Sources section to `QuickLook.tsx`**

Replace the entire file content with:

```tsx
/*
 * RailQuickLook — shared right-rail widget.
 * Surfaces watchlist top picks, portfolio mini-totals, and data source status.
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { RailSection } from '@/components/organisms/ContextRail';
import { Text, Data } from '@/components/primitives';
import { QuickLookRow } from '@/components/molecules/QuickLookRow';
import { api } from '@/lib/api';
import type { DataSourceInfo } from '@/lib/api';
import { usePortfolioStore } from '@/lib/portfolioStore';
import { useScanStore } from '@/lib/scanStore';
import type { WatchlistRow } from '@/types/domain';
import styles from './QuickLook.module.css';

export function RailQuickLook() {
  const router = useRouter();
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([]);
  const [watchlistError, setWatchlistError] = useState(false);
  const [dataSources, setDataSources] = useState<DataSourceInfo[]>([]);
  const portfolio       = usePortfolioStore((s) => s.positions);
  const syncFromBackend = usePortfolioStore((s) => s.syncFromBackend);
  const scanState       = useScanStore((s) => s.scanState);

  useEffect(() => {
    api.getWatchlist()
      .then(setWatchlist)
      .catch(() => setWatchlistError(true));
    syncFromBackend();
    api.getDataSources().then(setDataSources).catch(() => {});
  }, [syncFromBackend]);

  // Re-fetch data sources after a scan completes or fails so the panel
  // reflects any IBKR session that came online during the scan.
  useEffect(() => {
    if (scanState === 'COMPLETED' || scanState === 'FAILED') {
      api.getDataSources().then(setDataSources).catch(() => {});
    }
  }, [scanState]);

  const top = useMemo(
    () => [...watchlist].sort((a, b) => b.score - a.score).slice(0, 5),
    [watchlist],
  );

  const deployed = portfolio.reduce(
    (s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1),
    0,
  );
  const openPnL = portfolio.reduce((s, p) => s + p.pnlDollar, 0);
  const winners = portfolio.filter((p) => p.pnlDollar > 0).length;

  return (
    <>
      <RailSection title="Watchlist · Top 5">
        <div className={styles.watchlistStack}>
          {watchlistError && (
            <Text size={12} tone="dim">Could not load watchlist</Text>
          )}
          {top.map((r) => (
            <QuickLookRow
              key={r.symbol}
              symbol={r.symbol}
              score={r.score}
              status={r.status}
              onClick={() => router.push(`/chart?symbol=${r.symbol}`)}
            />
          ))}
        </div>
      </RailSection>

      <RailSection title="Portfolio">
        <div className={styles.portfolioStack}>
          <Row><Text size={12} tone="secondary">Positions</Text><Data size={12}>{portfolio.length}</Data></Row>
          <Row><Text size={12} tone="secondary">Deployed</Text><Data size={12}>${Math.round(deployed).toLocaleString()}</Data></Row>
          <Row>
            <Text size={12} tone="secondary">Open P&amp;L</Text>
            <Data size={12} tone={openPnL > 0 ? 'pass' : openPnL < 0 ? 'reject' : undefined}>
              {openPnL > 0 ? '+' : ''}${Math.round(openPnL).toLocaleString()}
            </Data>
          </Row>
          <Row>
            <Text size={12} tone="secondary">Winners</Text>
            <Data size={12} tone="pass">{winners} / {portfolio.length}</Data>
          </Row>
        </div>
      </RailSection>

      {dataSources.length > 0 && (
        <RailSection title="Data Sources">
          <div className={styles.dataSourceStack}>
            {dataSources.map((src) => (
              <div key={src.id} className={styles.dataSourceRow} title={src.detail ?? src.provides.join(', ')}>
                <span
                  className={styles.statusDot}
                  data-status={src.status}
                  aria-label={src.status}
                />
                <Text size={12} tone="secondary">{src.label}</Text>
                <Text size={11} tone="dim" weight={400} className={styles.dataSourceStatus}>
                  {src.status === 'ok' ? 'connected' : src.status}
                </Text>
              </div>
            ))}
          </div>
        </RailSection>
      )}
    </>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}
```

- [ ] **Step 4: Add CSS for the data source rows to `QuickLook.module.css`**

Append to the existing file:

```css
/* ---------- Data Sources section ---------- */

.dataSourceStack {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dataSourceRow {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.statusDot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--text-dim);
}

.statusDot[data-status="ok"]           { background: var(--pass);    }
.statusDot[data-status="unavailable"]  { background: var(--reject);  }
.statusDot[data-status="error"]        { background: var(--reject);  }
.statusDot[data-status="unconfigured"] { background: var(--caution); }

.dataSourceStatus {
  margin-left: auto;
}
```

- [ ] **Step 5: Check that `Text` doesn't need a `className` prop — if it doesn't accept one, remove the `className` prop**

Open `frontend/components/primitives/index.tsx` (or wherever `Text` is defined) and check its props interface. If `className` is not in the interface, remove `className={styles.dataSourceStatus}` from the `Text` element in `QuickLook.tsx` and instead wrap it in `<span className={styles.dataSourceStatus}>`.

The corrected row (if `Text` has no `className`):

```tsx
<span className={styles.dataSourceStatus}>
  <Text size={11} tone="dim" weight={400}>
    {src.status === 'ok' ? 'connected' : src.status}
  </Text>
</span>
```

- [ ] **Step 6: Run typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add lib/api.ts components/organisms/ContextRail/QuickLook.tsx components/organisms/ContextRail/QuickLook.module.css
git commit -m "feat(rail): add Data Sources availability panel to Context Rail"
```

---

## Self-Review

**Spec coverage:**
- IBKR warm-up on first snapshot call per conid: Task 1 ✓
- Module-level warm-up cache (skipped on subsequent calls): Task 1 ✓
- `GET /api/data-sources` probes Tradier / IBKR / yfinance: Task 2 ✓
- Never raises — probe exceptions return `"error"` status: Task 2, Step 3 `try/except` ✓
- Tests for all three probe scenarios: Task 2, Step 1 ✓
- Frontend fetches on mount: Task 3, `useEffect([syncFromBackend])` ✓
- Frontend re-fetches after scan completes/fails: Task 3, `useEffect([scanState])` ✓
- Color-coded status dots: Task 3, CSS `[data-status]` selectors ✓
- Tooltip shows `provides` list on hover: Task 3, `title={src.provides.join(', ')}` ✓

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `DataSourceInfo` defined in `api.ts`, imported as `import type { DataSourceInfo } from '@/lib/api'` in `QuickLook.tsx` ✓
- `_probe_tradier`, `_probe_ibkr`, `_probe_yfinance` are the exact names patched in tests ✓
- `DataSourceStatus.id` / `DataSourceStatus.status` / `DataSourceStatus.provides` / `DataSourceStatus.detail` match the Pydantic model across tests and router ✓
