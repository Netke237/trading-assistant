# Portfolio Single-Source-of-Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend database the single source of truth for portfolio positions and alert dispatch, so the UI can never show — or email alerts for — a position the backend does not actually hold, and so a save that is rejected or still unsynced is surfaced to the user instead of silently swallowed or silently lost.

**Architecture:** Four coordinated changes.
1. **Alert gate (backend):** `POST /api/alerts/notify` only emails/Telegrams when the `recId` is a currently-open position in the DB, so the browser's local alert engine cannot email alerts for phantom local positions.
2. **One account value (frontend):** every path that POSTs a position to the backend risk check uses the same configured account value (`riskStore.limits.portfolioValue`), not the sum of deployed premiums. This is the specific fix for the ABT `422 single_trade_exposure_too_high`.
3. **Verified writes (frontend):** `addPosition` becomes async and returns an outcome. It inserts an optimistic row tagged `pending`, awaits the POST, then promotes it to `synced`, drops it and surfaces the reason on a 4xx rejection, or leaves it `pending` on a network error. Nothing is ever silently lost.
4. **Authoritative reconcile with retry (frontend):** `syncFromBackend` lets the backend win. A local row absent from the backend is: **retried** if it is `pending` (so a network-dropped save eventually lands or surfaces a real rejection — never silently deleted); **kept** if it was `synced` after this GET's snapshot could have been taken (avoids the poll race); otherwise **dropped** as a genuine phantom. This auto-clears the existing 8 phantom rows.

**Tech Stack:** FastAPI + SQLAlchemy async (backend, pytest/pytest-asyncio), Next.js 15 + TypeScript + Zustand (frontend, Jest). Postgres via Docker container `tradingassistant-db` (port 5433); tests pin to in-memory SQLite.

**Root-cause evidence this plan is built on (verified live, not assumed):**
- `POST /api/alerts/notify` (`backend/app/routers/alerts.py:33-41`) dispatches from the request body with **no DB check** — the browser's local alert engine (`frontend/lib/alertEngine.ts` via `frontend/lib/alertStore.ts:85`) can email alerts for positions the backend never had.
- `addPosition` (`frontend/lib/portfolioStore.ts:200-249`) writes to localStorage then fires `postPosition` fire-and-forget; `postPosition` (`:98-114`) swallows all non-409 failures.
- `syncFromBackend` (`frontend/lib/portfolioStore.ts:375-399`) deliberately **retains** local rows absent from the backend, so phantoms persist forever.
- The ABT save was rejected `HTTP 422 single_trade_exposure_too_high`: `addPosition` computes `computedPortfolioValue` as the sum of deployed premiums (`:210-213`, ≈ $5,496), so one $1,045 contract reads as 19% exposure against the 5% cap (`backend/app/services/portfolio_risk.py:87-99`, `backend/config/risk_rules.yaml` `max_single_trade_exposure_pct: 0.05`). Verified live: same POST at `portfolioValue=100000` → 201; at `portfolioValue=5496` → 422.
- Two OTHER POST paths carry the same or a related wrong value: `persistPosition` (single-order buttons, defaults to `100_000`) and `syncToBackend` (`:403-406`, sums deployed premiums). All three must agree.

**Revisions from adversarial audit round 1 (baked in below, do not re-introduce):**
- Pending rows are **retried on every sync**, never silently dropped by a grace window (fixes silent re-loss on network error).
- Reconcile keeps a `synced` row absent from a GET when it was confirmed **after** that GET started (`syncedAt >= fetchStartedAt`), fixing the 30s-poll race.
- `addPosition` **returns an outcome**; `handleSubmit` clears prior error first, uses per-order outcomes, and only counts a daily recommendation on a real save.
- The account-value fix is applied to **all three** POST paths via one helper.
- Merge (scale-in) branch **rolls back** the count bump on rejection.
- Persist store gets a **version bump + migrate** so legacy rows (no sync fields) are treated as phantoms to reconcile away.
- Existing `addPosition` tests get a **fetch mock** so the async rewrite doesn't fire real network calls.

---

## Branch setup (do this first)

- [ ] **Step 0: Create a working branch**

Run:
```bash
cd "F:/Git/GitHub/Trading assistant"
git checkout -b fix/portfolio-single-source-of-truth
```
Expected: `Switched to a new branch 'fix/portfolio-single-source-of-truth'`

---

## Task 1: Gate `POST /api/alerts/notify` on a real open position

**Why:** This is the change that would have prevented the phantom ABT email. The endpoint must confirm the `recId` is an open position in the DB before dispatching. The headless monitor is unaffected — it calls `notify_alert` directly after reading the DB.

**Deliberate behaviour change (intended):** an alert that fires exactly on/just after a position is closed on the backend now returns `position_not_found` instead of emailing. That close-boundary case is acceptable to drop; the backend monitor still covers genuine open positions from its own DB reads.

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_alert_notify_guard.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alert_notify_guard.py`:

```python
"""POST /api/alerts/notify must only dispatch for a recId that is an open
portfolio position in the DB — otherwise the browser could email alerts for
positions the backend does not hold (phantom-alert guard)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from app.database import Base
from app.models.portfolio import PortfolioPositionModel

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_engine = create_async_engine(TEST_DB_URL, echo=False)
_Session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False,
                              autoflush=False, autocommit=False)


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.models import portfolio, watchlist, audit_event  # noqa: F401
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with _Session() as s:
        yield s


@pytest_asyncio.fixture
async def client(db_session):
    from app.main import app
    from app.database import get_db

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _insert(db: AsyncSession, rec_id: str) -> None:
    db.add(PortfolioPositionModel(
        rec_id=rec_id, symbol="ABT", contract="ABT|97|2027-01-15|C",
        direction="Bullish", entry_price=10.45, qty=1, entry_date="2026-07-17",
        stop=89.89, targets=[], dte_total=547,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_notify_dispatches_when_position_exists(client, db_session):
    await _insert(db_session, "REC-REAL-1")
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-REAL-1",
        })
    assert resp.status_code == 200
    assert resp.json()["sent"] is True
    mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_notify_suppressed_when_position_absent(client):
    with patch("app.routers.alerts.notify_alert", return_value=True) as mock_notify:
        resp = await client.post("/api/alerts/notify", json={
            "symbol": "ABT", "alertType": "STOP_REACHED",
            "reason": "Stop breached", "recId": "REC-GHOST-1",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is False
    assert body.get("reason") == "position_not_found"
    mock_notify.assert_not_called()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_alert_notify_guard.py -v`
Expected: `test_notify_suppressed_when_position_absent` FAILS (endpoint currently dispatches unconditionally).

- [ ] **Step 3: Implement the guard**

Replace `post_alert_notify` in `backend/app/routers/alerts.py` (`select`, `AsyncSession`, `Depends`, `get_db`, `PortfolioPositionModel` are already imported at lines 1-11 — no new imports):

```python
@router.post('/alerts/notify')
async def post_alert_notify(
    req: AlertNotifyRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dispatch a single in-app alert to email/Telegram.

    Called by the browser when a NEW portfolio alert is shown. Guarded: the
    alert is only dispatched when its recId is a currently-open position in the
    DB, so a stale localStorage phantom in the browser cannot email alerts for a
    position the backend does not hold. Deduped server-side (shared with the
    headless monitor).
    """
    exists = (await db.execute(
        select(PortfolioPositionModel.id).where(
            PortfolioPositionModel.rec_id == req.recId
        )
    )).first()
    if exists is None:
        return {'sent': False, 'reason': 'position_not_found'}

    sent = notify_alert(req.symbol, req.alertType, req.reason, req.recId, req.timestamp)
    return {'sent': sent}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_alert_notify_guard.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the existing alert suite**

Run: `cd backend && python -m pytest tests/test_alerts.py tests/test_alert_notifier.py -q`
Expected: all PASS (existing tests call `notify_alert` directly, not over HTTP, so the new `db` dependency does not affect them).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_alert_notify_guard.py
git commit -m "fix(alerts): only dispatch browser alerts for positions the backend actually holds"
```

---

## Task 2: Add sync-status fields + `lastSyncError`, with a persist version bump

**Why:** Tasks 4 and 5 need to distinguish a confirmed row, an in-flight/retrying row, and the time each was confirmed. Add local-only fields (never sent to the backend) and bump the persisted store version so legacy rows (which have none of these fields) are reconciled as phantoms rather than kept forever.

**Files:**
- Modify: `frontend/types/domain.ts` (`PortfolioPosition`, `:132-163`)
- Modify: `frontend/lib/portfolioStore.ts` (persist config `:410-419` and the `merge` callback)
- Test: `frontend/lib/__tests__/portfolioStore.test.ts` (migration case)

- [ ] **Step 1: Add the position type fields**

In `frontend/types/domain.ts`, inside `interface PortfolioPosition`, add before the closing brace (after `scanStockPrice?`):

```typescript
  /** Local-only sync state vs the backend. Never sent to the backend.
   *  'pending'  — optimistically added, POST in flight or retrying.
   *  'synced'   — confirmed present on the backend. */
  syncStatus?: 'pending' | 'synced';
  /** Epoch ms when this row entered 'pending' (for an "unsynced since" hint). */
  syncPendingSince?: number;
  /** Epoch ms when the backend last confirmed this row. Used by the reconcile
   *  to avoid dropping a row confirmed after the current GET's snapshot. */
  syncedAt?: number;
```

- [ ] **Step 2: Write the failing migration test**

Add to `frontend/lib/__tests__/portfolioStore.test.ts` (top of file, alongside existing imports, add `import { useRiskStore } from '@/lib/riskStore';` if not present):

```typescript
describe('persist migration for legacy rows', () => {
  it('tags legacy persisted rows (no syncStatus) as synced with syncedAt=0', () => {
    const legacy = {
      state: { positions: [{ recId: 'LEGACY-1', symbol: 'ABT', contract: 'ABT|97|2027-01-15|C' }] },
      version: 0,
    };
    // migrate() is exported for test; see implementation step.
    const migrated = migratePortfolioPersist(legacy.state, 0) as { positions: Array<Record<string, unknown>> };
    expect(migrated.positions[0]!.syncStatus).toBe('synced');
    expect(migrated.positions[0]!.syncedAt).toBe(0);
  });
});
```

Add `migratePortfolioPersist` to the import from `'@/lib/portfolioStore'` at the top of the test file.

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: FAIL — `migratePortfolioPersist` is not exported yet.

- [ ] **Step 4: Implement the migration + version bump**

In `frontend/lib/portfolioStore.ts`, add this exported helper near `validatePositions` (`:171`):

```typescript
/** Persist migration. Legacy rows (persisted before sync tracking existed) have
 *  no syncStatus. Tag them synced with syncedAt=0 so the authoritative reconcile
 *  drops them if the backend does not have them (clears old phantom rows), while
 *  a row the backend DOES have is simply confirmed on the next sync. */
export function migratePortfolioPersist(state: unknown, _version: number): unknown {
  const s = state as { positions?: unknown } | undefined;
  if (!s || !Array.isArray(s.positions)) return state;
  return {
    ...s,
    positions: s.positions.map((p) => {
      const po = p as Record<string, unknown>;
      return po.syncStatus
        ? po
        : { ...po, syncStatus: 'synced', syncedAt: 0 };
    }),
  };
}
```

Then update the persist options object (`:410-419`). Add `version: 2` and `migrate`, and exclude the transient `lastSyncError` from `partialize` (it is added in Task 4 but declare the intent here — persist only `positions`):

```typescript
    {
      name: 'bamendjou-portfolio-v1',
      version: 2,
      skipHydration: true,
      migrate: migratePortfolioPersist,
      partialize: (state) => ({ positions: state.positions }),
      merge: (persistedState, currentState) => {
```

Leave the rest of the existing `merge` body unchanged.

- [ ] **Step 5: Run the tests + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore && npm run typecheck`
Expected: migration test PASSES; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/types/domain.ts frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts
git commit -m "feat(portfolio): add sync-status fields + persist v2 migration for legacy rows"
```

---

## Task 3: One account value for every backend POST path

**Why:** The ABT rejection came from the wrong account value. Three paths POST positions with three different values (`addPosition` sum-of-premiums, `persistPosition` default 100k, `syncToBackend` sum-of-premiums). Centralise on the user's configured `riskStore.limits.portfolioValue` so all three agree with the Step-7 pre-check.

**Files:**
- Modify: `frontend/lib/portfolioStore.ts` (add import + helper; `persistPosition` `:123-139`; `syncToBackend` `:400-408`)
- Test: `frontend/lib/__tests__/portfolioStore.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `frontend/lib/__tests__/portfolioStore.test.ts`:

```typescript
describe('account value for backend POSTs', () => {
  beforeEach(() => {
    useRiskStore.setState({
      limits: { maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10, maxDailyRecommendations: 5, portfolioValue: 50000 },
    } as never);
  });

  it('persistPosition sends the configured account value', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
    (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
    const { persistPosition } = await import('@/lib/portfolioStore');
    await persistPosition({
      symbol: 'ABT', contract: 'ABT|97|2027-01-15|C', direction: 'Bullish',
      entryDate: '2026-07-17', expiry: '2027-01-15', dteRemaining: 547, dteTotal: 547,
      entryPrice: 10.45, currentPrice: 10.45, pnlDollar: 0, pnlPct: 0, stop: 89.89,
      targets: [], status: 'PENDING', contracts: 1, recId: 'REC-ABT-1',
    } as never);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.portfolioValue).toBe(50000);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: FAIL — `persistPosition` defaults `portfolioValue` to `100_000`.

- [ ] **Step 3: Add the import and helper**

At the top of `frontend/lib/portfolioStore.ts` (after existing imports):

```typescript
import { useRiskStore } from '@/lib/riskStore';
```

Below the `_BASE_URL` definition (`:79`), add:

```typescript
/** The account value the backend risk check must measure exposure against —
 *  the user's configured value, identical to the Step-7 pre-check. Using the
 *  sum of deployed premiums here made a single option read as a huge fraction
 *  of the account and got otherwise-valid trades rejected (the ABT 422). */
function accountValue(): number {
  return useRiskStore.getState().limits.portfolioValue || 100_000;
}
```

- [ ] **Step 4: Use it in `persistPosition` and `syncToBackend`**

Change `persistPosition`'s signature default (`:123-126`) from:

```typescript
export async function persistPosition(
  p: PortfolioPosition,
  portfolioValue = 100_000,
): Promise<{ ok: boolean; detail?: string }> {
```
to:
```typescript
export async function persistPosition(
  p: PortfolioPosition,
  portfolioValue = accountValue(),
): Promise<{ ok: boolean; detail?: string }> {
```

In `syncToBackend` (`:400-408`), replace the `totalValue` computation:

```typescript
      syncToBackend: async () => {
        // Push all local positions to the backend (409 = already there, safe to ignore).
        const { positions } = usePortfolioStore.getState();
        const value = accountValue();
        await Promise.all(positions.map((p) => postPosition(p, value)));
      },
```

(`postPosition` is redefined in Task 4; for this task it still returns void — the call compiles either way since the result is ignored here.)

- [ ] **Step 5: Run the tests + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore && npm run typecheck`
Expected: new test PASSES; typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts
git commit -m "fix(portfolio): all backend POST paths use one configured account value"
```

---

## Task 4: Verified writes — async `addPosition` that returns an outcome

**Why:** `addPosition` must await the POST and report the result: promote to `synced`, drop-and-surface on 4xx, or keep `pending` on network error (retried later by Task 5). It must roll back a scale-in count bump on rejection, and it must never silently lose a position.

**Files:**
- Modify: `frontend/lib/portfolioStore.ts` (`postPosition` `:98-114`, interface `:62-77`, initializer, `addPosition` `:200-249`)
- Test: `frontend/lib/__tests__/portfolioStore.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/lib/__tests__/portfolioStore.test.ts`:

```typescript
describe('addPosition verified write', () => {
  const abt = {
    symbol: 'ABT', contract: 'ABT|97|2027-01-15|C', direction: 'Bullish',
    entryDate: '2026-07-17', expiry: '2027-01-15', dteRemaining: 547, dteTotal: 547,
    entryPrice: 10.45, currentPrice: 10.45, pnlDollar: 0, pnlPct: 0, stop: 89.89,
    targets: [], status: 'PENDING', contracts: 1, recId: 'REC-ABT-1',
  } as never;

  beforeEach(() => {
    useRiskStore.setState({
      limits: { maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10, maxDailyRecommendations: 5, portfolioValue: 50000 },
    } as never);
    usePortfolioStore.setState({ positions: [], lastSyncError: null } as never);
  });

  it('marks the row synced and returns ok when the backend accepts it', async () => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
    const res = await usePortfolioStore.getState().addPosition(abt);
    expect(res.ok).toBe(true);
    const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1');
    expect(pos?.syncStatus).toBe('synced');
    expect(usePortfolioStore.getState().lastSyncError).toBeNull();
  });

  it('drops the row and records the reason when the backend rejects it (422)', async () => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'single_trade_exposure_too_high' }) });
    const res = await usePortfolioStore.getState().addPosition(abt);
    expect(res.ok).toBe(false);
    expect(res.detail).toBe('single_trade_exposure_too_high');
    expect(usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1')).toBeUndefined();
    expect(usePortfolioStore.getState().lastSyncError?.detail).toBe('single_trade_exposure_too_high');
  });

  it('keeps the row pending (status=pending) when the backend is unreachable', async () => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn().mockRejectedValue(new Error('network'));
    const res = await usePortfolioStore.getState().addPosition(abt);
    expect(res.ok).toBe(false);
    expect(res.status).toBe('pending');
    const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1');
    expect(pos?.syncStatus).toBe('pending');
    expect(usePortfolioStore.getState().lastSyncError).toBeNull();
  });

  it('rolls back a scale-in MERGE (different recId, same contract) when the backend rejects', async () => {
    // Existing synced row with recId REC-EXIST; re-add uses a DIFFERENT recId so
    // addPosition takes the idxByKey MERGE branch (not the idxByRecId replace branch).
    usePortfolioStore.setState({
      positions: [{ ...(abt as object), recId: 'REC-EXIST', contracts: 2, syncStatus: 'synced', syncedAt: Date.now() }],
    } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'x' }) });
    await usePortfolioStore.getState().addPosition({ ...(abt as object), recId: 'REC-NEW', contracts: 3 } as never);
    const rows = usePortfolioStore.getState().positions.filter((p) => p.contract === 'ABT|97|2027-01-15|C');
    expect(rows).toHaveLength(1);
    expect(rows[0]!.recId).toBe('REC-EXIST');
    expect(rows[0]!.contracts).toBe(2);        // +3 bump rolled back to original 2
    expect(rows[0]!.syncStatus).toBe('synced'); // original row restored intact
  });

  it('rolls back a REPLACE (same recId) to the prior row when the backend rejects', async () => {
    usePortfolioStore.setState({
      positions: [{ ...(abt as object), recId: 'REC-ABT-1', contracts: 2, entryPrice: 9.0, syncStatus: 'synced', syncedAt: Date.now() }],
    } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'x' }) });
    await usePortfolioStore.getState().addPosition({ ...(abt as object), recId: 'REC-ABT-1', contracts: 3, entryPrice: 11.0 } as never);
    const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'REC-ABT-1');
    expect(pos?.contracts).toBe(2);      // restored
    expect(pos?.entryPrice).toBe(9.0);   // restored, not the rejected 11.0
    expect(pos?.syncStatus).toBe('synced');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: FAIL — `addPosition` returns void, sets no `syncStatus`, `lastSyncError` doesn't exist.

- [ ] **Step 3: Add `lastSyncError` to the interface + initializer**

In `interface PortfolioStoreState`, after `positions: PortfolioPosition[];`:

```typescript
  lastSyncError: { symbol: string; contract: string; detail: string; at: number } | null;
  clearSyncError: () => void;
```

Change the `addPosition` signature in the interface (`:65`) from `(p: PortfolioPosition) => void;` to the three-way outcome (so callers can tell a hard rejection from a will-retry pending — see Task 7):

```typescript
  /** status: 'ok' saved; 'rejected' backend refused (dropped); 'pending' network
   *  error, kept locally and retried by syncFromBackend. `ok` === (status==='ok'). */
  addPosition:    (p: PortfolioPosition) => Promise<{ ok: boolean; status: 'ok' | 'rejected' | 'pending'; detail?: string }>;
```

Also change the `syncFromBackend` signature (`:75`) from `() => Promise<boolean>;` to accept the force flag Task 5 adds:

```typescript
  /** force=true bypasses the concurrent-sync dedup by SERIALIZING a fresh run
   *  after any in-flight one — used by closePositionRemote, which needs a GET
   *  that post-dates its own write. */
  syncFromBackend: (force?: boolean) => Promise<boolean>;
```

In the store initializer object (`(set) => ({ ... })`), after `positions: [],`:

```typescript
      lastSyncError: null,
      clearSyncError: () => set({ lastSyncError: null }),
```

- [ ] **Step 4: Replace `postPosition` with an outcome-returning version**

Replace `postPosition` (`:98-114`) with:

```typescript
type SaveOutcome =
  | { kind: 'ok' }
  | { kind: 'rejected'; detail: string }   // backend 4xx (except 409) — do not keep the row
  | { kind: 'duplicate' }                  // 409 — backend already has this contract
  | { kind: 'network' };                   // unreachable — keep the row pending

async function postPosition(p: PortfolioPosition, portfolioValue = accountValue()): Promise<SaveOutcome> {
  try {
    const res = await fetch(`${_BASE_URL()}/api/portfolio`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(toBackendPayload(p, portfolioValue)),
    });
    if (res.ok) return { kind: 'ok' };
    if (res.status === 409) return { kind: 'duplicate' };
    const body = await res.json().catch(() => ({}));
    return { kind: 'rejected', detail: (body as { detail?: string }).detail ?? `HTTP ${res.status}` };
  } catch {
    return { kind: 'network' };
  }
}
```

- [ ] **Step 5: Rewrite `addPosition`**

Replace the whole `addPosition` action (`:200-249`) with:

```typescript
      addPosition: async (p) => {
        const recId = (p as PortfolioPosition & { recId?: string }).recId || generateRecId();
        const value = accountValue();

        // Snapshot exactly what we change so a hard rejection restores it precisely:
        //  - insert  → remove the new row (identified by recId)
        //  - replace → restore the prior row that shared this recId
        //  - merge   → restore the prior same-contract row (undoes the count bump)
        // For replace/merge, `prevRow` is the untouched original; restoring it by
        // its own recId reverses whatever we did in place.
        let mutation: 'insert' | 'replace' | 'merge' = 'insert';
        let prevRow: PortfolioPosition | undefined;

        set((s) => {
          const incoming: PortfolioPosition = {
            ...p, recId, syncStatus: 'pending', syncPendingSince: Date.now(),
          };

          const idxByRecId = s.positions.findIndex((x) => x.recId === recId);
          if (idxByRecId >= 0) {
            prevRow = s.positions[idxByRecId];
            mutation = 'replace';
            const next = [...s.positions];
            next[idxByRecId] = { ...next[idxByRecId]!, ...incoming };
            return { positions: next };
          }
          const idxByKey = s.positions.findIndex(
            (x) => x.symbol === incoming.symbol && x.contract === incoming.contract,
          );
          if (idxByKey >= 0) {
            // eslint-disable-next-line no-console
            console.warn('[portfolioStore] merging duplicate position for', incoming.symbol, incoming.contract);
            prevRow = s.positions[idxByKey];
            mutation = 'merge';
            const next = [...s.positions];
            const existing = next[idxByKey]!;
            next[idxByKey] = { ...existing, contracts: (existing.contracts ?? 0) + (incoming.contracts ?? 0) };
            return { positions: next };
          }
          mutation = 'insert';
          return { positions: [...s.positions, incoming] };
        });

        const outcome = await postPosition({ ...p, recId } as PortfolioPosition, value);

        if (outcome.kind === 'ok' || outcome.kind === 'duplicate') {
          // Promote whichever row this add touched. For a merge that is prevRow's
          // recId; otherwise it is `recId`.
          const promoteRecId = mutation === 'merge' && prevRow ? prevRow.recId : recId;
          set((s) => ({
            positions: s.positions.map((x) =>
              x.recId === promoteRecId
                ? { ...x, syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined }
                : x,
            ),
          }));
          return { ok: true, status: 'ok' as const };
        }
        if (outcome.kind === 'rejected') {
          set((s) => {
            let positions = s.positions;
            if (mutation === 'insert') {
              positions = positions.filter((x) => x.recId !== recId);
            } else if (prevRow) {
              const restore = prevRow;
              positions = positions.map((x) => (x.recId === restore.recId ? restore : x));
            }
            return {
              positions,
              lastSyncError: { symbol: p.symbol, contract: p.contract, detail: outcome.detail, at: Date.now() },
            };
          });
          return { ok: false, status: 'rejected' as const, detail: outcome.detail };
        }
        // network — leave the row pending; Task 5's reconcile retries it. Never silently dropped.
        return { ok: false, status: 'pending' as const, detail: 'queued — will retry when the backend is reachable' };
      },
```

- [ ] **Step 6: Add a fetch mock to the EXISTING addPosition tests, and place the new suites correctly**

The async rewrite means any un-mocked `addPosition` call fires a real `fetch`. **Placement:** put all the NEW `describe(...)` blocks added in Tasks 3/4/5 (`account value for backend POSTs`, `addPosition verified write`, `syncFromBackend authoritative reconcile`) and the `persist migration` describe **INSIDE the existing `describe('portfolioStore', () => { … })` block** (as nested describes, before its closing `})`). That way the existing `afterEach` (`portfolioStore.test.ts:54-57`, which restores `global.fetch = originalFetch` and `localStorage.clear()`) runs for them too, so no fetch/localStorage state leaks across suites.

Extend the existing `describe('portfolioStore')` `beforeEach` (`:48-52`) so every test has a benign fetch mock in addition to the positions reset:

```typescript
  beforeEach(() => {
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
    act(() => {
      usePortfolioStore.setState({ positions: [], lastSyncError: null });
    });
  });
```

Tests that set their own `global.fetch` inside the test body still override this per-test. Existing tests that call `addPosition` inside a synchronous `act(() => …)` (e.g. `merges a re-add…`, `closes a position…`, `does not merge different contracts…`) keep passing because the optimistic insert/merge is synchronous — but the awaited promote-to-`synced` resolves after `act`, which can emit a React "not wrapped in act(...)" warning. Convert those three to `await act(async () => { await result.current.addPosition(...); })` to silence the warnings (warnings do not fail the suite, but do this for cleanliness).

- [ ] **Step 7: Fix the two un-awaited `addPosition` call sites in Step 7's page**

In `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, `placeLimitPaper` (`:462`) and `placeMarketNow` (`:492`) call `addPosition(pos)` without awaiting. Now that it returns a promise, mark the intentional fire-and-forget with `void` to avoid an unhandled-rejection/floating-promise lint or `act` warning (these paths already `await persistPosition` first, so the extra POST just 409s → `duplicate` → ok):

```typescript
      void addPosition(pos);
```

Apply to both call sites. Also add a benign fetch mock to `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx` if running it in Step 8 shows real network attempts or act warnings:

```typescript
beforeEach(() => {
  (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
    .mockResolvedValue({ ok: true, status: 201, json: async () => ({}) });
});
```

- [ ] **Step 8: Run the frontend suite + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: all PASS. Fix any remaining test that relied on a synchronous `addPosition` return by awaiting the promise.

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts "frontend/app/(frame)/screener/step-7-trade-card/page.tsx" frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx
git commit -m "feat(portfolio): verified async writes — await backend, drop rejected, keep pending, rollback merges"
```

---

## Task 5: Authoritative reconcile with retry (no silent loss, no poll race)

**Why:** `syncFromBackend` must let the backend win while never silently deleting an unsaved position. A local row absent from the backend is: **retried** if `pending`; **kept** if `synced` after this GET's snapshot (`syncedAt >= fetchStartedAt`, fixes the 30s-poll race); otherwise **dropped** as a phantom (this clears the 8 legacy rows, which Task 2 tagged `synced, syncedAt=0`).

**Files:**
- Modify: `frontend/lib/portfolioStore.ts` (`fromBackend` `:35-60`, `syncFromBackend` `:375-399`, and the one `syncFromBackend()` call inside `closePositionRemote` `:348` → `syncFromBackend(true)`)
- Test: `frontend/lib/__tests__/portfolioStore.test.ts`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/lib/__tests__/portfolioStore.test.ts`:

```typescript
describe('syncFromBackend authoritative reconcile', () => {
  beforeEach(() => {
    useRiskStore.setState({
      limits: { maxSingleTradeExposurePct: 0.05, maxTotalExposurePct: 0.25,
        maxConcurrentPositions: 10, maxDailyRecommendations: 5, portfolioValue: 50000 },
    } as never);
    usePortfolioStore.setState({ positions: [], lastSyncError: null } as never);
  });

  const mkLocal = (recId: string, over: Record<string, unknown> = {}) => ({
    symbol: 'ABT', contract: `ABT|${recId}|2027-01-15|C`, direction: 'Bullish',
    entryDate: '2026-07-17', expiry: '2027-01-15', dteRemaining: 1, dteTotal: 1,
    entryPrice: 10, currentPrice: 10, pnlDollar: 0, pnlPct: 0, stop: 5, targets: [],
    status: 'PENDING', contracts: 1, recId, ...over,
  }) as never;

  it('drops a legacy/synced local row (syncedAt in the past) that the backend lacks', async () => {
    usePortfolioStore.setState({ positions: [mkLocal('GHOST', { syncStatus: 'synced', syncedAt: 0 })] } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: true, json: async () => [] });
    await usePortfolioStore.getState().syncFromBackend();
    expect(usePortfolioStore.getState().positions).toHaveLength(0);
  });

  it('keeps a row synced AFTER this GET started (poll-race safe)', async () => {
    // syncedAt is far in the future → definitely after fetchStartedAt.
    usePortfolioStore.setState({
      positions: [mkLocal('FRESH', { syncStatus: 'synced', syncedAt: Date.now() + 60_000 })],
    } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockResolvedValue({ ok: true, json: async () => [] });
    await usePortfolioStore.getState().syncFromBackend();
    expect(usePortfolioStore.getState().positions.map((p) => p.recId)).toContain('FRESH');
  });

  it('retries a pending local row and marks it synced when the retry POST succeeds', async () => {
    usePortfolioStore.setState({
      positions: [mkLocal('PEND', { syncStatus: 'pending', syncPendingSince: Date.now() })],
    } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockImplementation((url: string, init?: { method?: string }) => {
        if ((init?.method ?? 'GET') === 'GET') return Promise.resolve({ ok: true, json: async () => [] });
        return Promise.resolve({ ok: true, status: 201, json: async () => ({}) }); // retry POST
      });
    await usePortfolioStore.getState().syncFromBackend();
    const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'PEND');
    expect(pos?.syncStatus).toBe('synced');
  });

  it('keeps a pending row (never silently drops it) when the retry POST also fails on network', async () => {
    usePortfolioStore.setState({
      positions: [mkLocal('PEND2', { syncStatus: 'pending', syncPendingSince: Date.now() - 999_999 })],
    } as never);
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn()
      .mockImplementation((url: string, init?: { method?: string }) => {
        if ((init?.method ?? 'GET') === 'GET') return Promise.resolve({ ok: true, json: async () => [] });
        return Promise.reject(new Error('still down')); // retry POST fails
      });
    await usePortfolioStore.getState().syncFromBackend();
    const pos = usePortfolioStore.getState().positions.find((p) => p.recId === 'PEND2');
    expect(pos?.syncStatus).toBe('pending'); // survived — not silently deleted
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore`
Expected: FAIL — current reconcile keeps GHOST and does not retry/mark PEND.

- [ ] **Step 3: Tag backend rows in `fromBackend`**

In `fromBackend`'s returned object (`:39-59`), add before the closing brace:

```typescript
    ivRank:       p.ivRank ?? undefined,
    syncStatus:   'synced',
    syncedAt:     Date.now(),
  };
```

- [ ] **Step 4: Add a module-level in-flight guard**

Near the existing `_inFlightCloses` declaration (`:188`), add:

```typescript
// Dedupes overlapping syncFromBackend calls. The reconcile now awaits POST
// retries for pending rows, so two concurrent syncs (portfolio + dashboard 30s
// intervals, or two tabs) could each read the same snapshot and clobber each
// other's final write. A single shared in-flight promise serializes them.
let _syncInFlight: Promise<boolean> | null = null;
```

- [ ] **Step 5: Rewrite `syncFromBackend`**

Replace the body (`:375-399`) with:

```typescript
      syncFromBackend: async (force = false) => {
        const run = async (): Promise<boolean> => {
          const fetchStartedAt = Date.now();
          try {
            const res = await fetch(`${_BASE_URL()}/api/portfolio`);
            if (!res.ok) return false;
            const remote: BackendPosition[] = await res.json();
            const remotePositions = remote.map(fromBackend);
            const remoteContracts = new Set(remotePositions.map((p) => p.contract));

            const snapshot = usePortfolioStore.getState().positions;
            const snapshotRecIds = new Set(snapshot.map((p) => p.recId));
            const localAbsent = snapshot.filter(
              (p) => p.recId && !remoteContracts.has(p.contract),
            );

            const keep: PortfolioPosition[] = [];
            for (const p of localAbsent) {
              if (p.syncStatus === 'pending') {
                // Retry the save. Never silently drop a pending row: on success
                // promote it, on a hard rejection surface it, on network keep it.
                const outcome = await postPosition(p, accountValue());
                if (outcome.kind === 'ok' || outcome.kind === 'duplicate') {
                  keep.push({ ...p, syncStatus: 'synced', syncedAt: Date.now(), syncPendingSince: undefined });
                } else if (outcome.kind === 'rejected') {
                  set({ lastSyncError: { symbol: p.symbol, contract: p.contract, detail: outcome.detail, at: Date.now() } });
                  // dropped — do not push
                } else {
                  keep.push(p); // network — stays pending, retried next cycle
                }
              } else if (typeof p.syncedAt === 'number' && p.syncedAt >= fetchStartedAt) {
                // Confirmed after this GET's snapshot could have been taken — keep
                // (the GET simply predates it); avoids the 30s-poll race dropping it.
                keep.push(p);
              }
              // else: a synced row confirmed before this snapshot but absent from the
              // backend is a genuine phantom (e.g. legacy row, DB reset) — drop it.
            }

            // Preserve any row inserted into the store DURING the awaited retry
            // loop above so a concurrent addPosition is not clobbered by our final
            // write. Key on recId (NOT contract): a legitimate re-add of a contract
            // that was a phantom in this run's snapshot has a NEW recId, so it must
            // survive even though its contract was in the snapshot.
            const accountedRecIds = new Set([...remotePositions, ...keep].map((x) => x.recId));
            set((s) => {
              const addedDuringSync = s.positions.filter(
                (x) => x.recId && !snapshotRecIds.has(x.recId) && !accountedRecIds.has(x.recId),
              );
              return { positions: dedupePositions([...remotePositions, ...keep, ...addedDuringSync]) };
            });
            return true;
          } catch {
            // network unavailable — keep localStorage state untouched
            return false;
          }
        };

        // Concurrent-sync dedup. A non-forced caller (the 30s interval pollers)
        // shares any in-flight run. A forced caller (closePositionRemote, which
        // must observe a GET that post-dates its own write) SERIALIZES a fresh
        // run after the in-flight one rather than reusing its stale result.
        // NOTE: `_syncInFlight` must hold the SAME promise the finally callback
        // compares against, so attach `.finally` as a side-effect and store/return
        // the original promise — do not store the value `.finally()` returns.
        if (_syncInFlight && !force) return _syncInFlight;

        const started: Promise<boolean> = _syncInFlight
          ? _syncInFlight.catch(() => false).then(() => run()) // forced: chain after in-flight
          : run();
        _syncInFlight = started;
        started.finally(() => { if (_syncInFlight === started) _syncInFlight = null; });
        return started;
      },
```

**Note on `closePositionRemote`:** its post-close pull (`portfolioStore.ts:348`, `const synced = await usePortfolioStore.getState().syncFromBackend();`) MUST use the forced form so it is not satisfied by an in-flight sync whose GET predates the close (which would resurrect the just-closed row). Change that one call to:

```typescript
            const synced = await usePortfolioStore.getState().syncFromBackend(true);
```

- [ ] **Step 6: Update the pre-existing "in-flight local position" test to the new semantics**

The existing test `keeps an in-flight local position for a contract the backend has not seen` (`frontend/lib/__tests__/portfolioStore.test.ts:205-223`) seeds a row with **no** `syncStatus` and asserts it is kept — that encodes the OLD "retain anything absent" behaviour this task deliberately removes. Under the new reconcile an untagged absent row is a phantom and is dropped, so the test would fail. Update it so the seed row is `pending` (which is what "in-flight" now means); the existing `ok: true` fetch mock makes the retry POST succeed, so the row is promoted to `synced` and still kept. Replace the `setState` seed in that test:

```typescript
    act(() => {
      usePortfolioStore.setState({
        positions: [makePosition({
          symbol: 'MSFT', contract: 'MSFT 420C 06/20', recId: 'REC-INFLIGHT',
          syncStatus: 'pending', syncPendingSince: Date.now(),
        })],
      });
    });
```

The assertion `expect(recIds).toEqual(['REC-BACKEND', 'REC-INFLIGHT'])` still holds (remote first, then the promoted-and-kept pending row).

- [ ] **Step 7: Run the tests + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=portfolioStore && npm run typecheck`
Expected: all four new reconcile cases PASS; the updated in-flight test PASSES; earlier tasks' cases still PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/portfolioStore.ts frontend/lib/__tests__/portfolioStore.test.ts
git commit -m "fix(portfolio): backend-authoritative reconcile — retry pending, poll-race safe, drop phantoms"
```

---

## Task 6: Surface the rejection in the Portfolio UI (CSS module)

**Why:** `lastSyncError` now exists but nothing shows it. Add a dismissible banner on the Portfolio page using the page's CSS module (per repo convention — no inline style objects).

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`
- Modify: `frontend/app/(frame)/portfolio/page.module.css` (the module imported at `page.tsx:25`; confirm the exact name in Step 1)

- [ ] **Step 1: Confirm the module filename**

Run: `ls "frontend/app/(frame)/portfolio/"`
Expected: confirm `page.module.css` (referenced in the page as `import styles from './page.module.css'`). Use that exact path below.

- [ ] **Step 2: Add banner styles to the module**

Append to the portfolio page's `.module.css`:

```css
.syncErrorBanner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--reject);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--reject) 8%, var(--bg-surface));
  margin-bottom: var(--space-3);
}
.syncErrorDismiss {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-dim);
  font-size: 16px;
  line-height: 1;
}
```

- [ ] **Step 3: Read the store field + render the banner**

In `frontend/app/(frame)/portfolio/page.tsx`, add near the other store selectors (around `:60`):

```typescript
  const lastSyncError  = usePortfolioStore((s) => s.lastSyncError);
  const clearSyncError = usePortfolioStore((s) => s.clearSyncError);
```

Add this constant after the imports (before the `PortfolioPage` component):

```typescript
const REJECTION_LABELS: Record<string, string> = {
  single_trade_exposure_too_high: 'This trade is too large for your account size (over the single-trade limit). Raise your account value in Settings or reduce size.',
  total_exposure_limit_reached: 'Adding this would exceed your total portfolio exposure limit.',
  max_concurrent_positions_reached: 'You are at your maximum number of open positions.',
  duplicate_symbol_already_open: 'You already have an open position on this symbol.',
  portfolio_too_small: 'Your configured account value is below the minimum required.',
};
```

Inside the returned JSX, immediately after the `<div className={styles.heading}>...</div>` block (around `:130`), insert:

```tsx
      {lastSyncError && (
        <div role="alert" className={styles.syncErrorBanner}>
          <Text size={13} tone="reject">
            {lastSyncError.symbol} was not saved: {REJECTION_LABELS[lastSyncError.detail] ?? lastSyncError.detail}
          </Text>
          <button type="button" className={styles.syncErrorDismiss} onClick={clearSyncError} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
```

Confirm `Text` is imported in this file (it is used elsewhere on the page); if not, add it to the primitives import.

- [ ] **Step 4: Typecheck + commit**

Run: `cd frontend && npm run typecheck`
Expected: clean.
```bash
git add "frontend/app/(frame)/portfolio/page.tsx" "frontend/app/(frame)/portfolio/"*.module.css
git commit -m "feat(portfolio): show a banner when the backend rejects a save"
```

---

## Task 7: Correct the Step 7 basket submit reporting

**Why:** `handleSubmit` (`:509-531`) calls `addPosition` and never checks the outcome. It also increments the daily counter for orders that never persisted. Make it clear the prior error, use each order's returned outcome, only count real saves, and report failures.

**Files:**
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` (`handleSubmit` `:509-531`)

- [ ] **Step 1: Rewrite `handleSubmit`**

Replace `handleSubmit` (`:509-531`) with:

```typescript
  const handleSubmit = async (orders: DraftOrder[], _riskOverridden: boolean) => {
    usePortfolioStore.getState().clearSyncError();
    let auto = 0, manual = 0, queued = 0;
    const failures: string[] = [];

    for (const o of orders) {
      const recId = recIdMap[o.card.symbol] ?? generateRecId();
      const res = await addPosition({ ...positionFromOrder(o), recId });

      if (res.status === 'rejected') {
        // Backend refused it and the optimistic row was dropped — a real failure.
        failures.push(`${o.card.symbol}: ${res.detail ?? 'not saved'}`);
        continue;
      }
      // 'ok' (saved) or 'pending' (queued, will retry) — the order is live and
      // will land, so it counts toward the daily cap and is audited either way.
      incrementDaily();
      if (o.autoSend) auto++; else manual++;
      if (res.status === 'pending') queued++;
      logAudit('APPROVE', recId, {
        symbol: o.card.symbol, contract: o.card.contract, contracts: o.contracts,
      });
    }

    setDialogOpen(false);
    setBasket([]);

    // Toast covers orders that were placed (saved or queued-for-retry); the red
    // error banner covers hard rejections. They describe DIFFERENT orders, so both
    // may show for a mixed basket — but a network-only submit shows just the toast
    // (no contradictory red banner), and the toast reports queued distinctly rather
    // than falsely implying everything reached the backend.
    if (auto + manual > 0) {
      setToast({ auto, manual, queued });
      window.setTimeout(() => setToast(null), 6000);
    }
    if (failures.length) {
      setOrderError(`Some orders were not saved — ${failures.join('; ')}`);
    }
  };
```

This requires two supporting edits in the same file:

**(i)** Extend `ToastState` (`:86-89`) with the queued count:

```typescript
interface ToastState {
  auto:    number;
  manual:  number;
  queued:  number;   // subset of auto+manual that is pending a backend retry
}
```

**(ii)** Update the toast render (`:663-677`) so it never claims a queued order was "sent to broker" — show the queued count as a distinct, accurate clause:

```tsx
      {toast && (
        <div className={toastStyles.toast} role="status" aria-live="polite">
          <div>
            <Text size={13} weight={500}>
              {toast.auto + toast.manual} order{toast.auto + toast.manual === 1 ? '' : 's'} placed
            </Text>
            <Text size={11} tone="secondary">
              {toast.auto} sent to broker · {toast.manual} added manually
              {toast.queued > 0 ? ` · ${toast.queued} awaiting backend sync` : ''}
            </Text>
          </div>
          <Link href="/portfolio" className={toastStyles.link}>
            View Portfolio →
          </Link>
        </div>
      )}
```

Confirm `usePortfolioStore` is imported in this file (it is — `addPosition` comes from it at `:152`). `clearSyncError` and the async `addPosition` are provided by Tasks 2/4.

- [ ] **Step 2: Apply the same outcome handling to the Stock send path**

`frontend/components/organisms/StockSendDialog/index.tsx` also calls `addPosition` unawaited at `:87` and `:105`, inside a loop that already collects per-symbol errors in an `errs` map (`:82,:101,:107`). Now that `addPosition` is async and returns an outcome, await it and record a hard rejection into `errs` so the stock path surfaces it the same way the broker error does. Replace both call sites:

```typescript
        const res = await addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares));
        if (res.status === 'rejected') errs[c.symbol] = res.detail ?? 'not saved';
```

(The enclosing function is already `async` — it `await`s `api.postStockOrder` at `:91`.)

- [ ] **Step 3: Typecheck + run the frontend suite**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: all PASS. Adjust any Step-7 / StockSendDialog test that assumed a synchronous `handleSubmit`/`addPosition`.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-7-trade-card/page.tsx" "frontend/components/organisms/StockSendDialog/index.tsx"
git commit -m "fix(step7): await basket + stock saves, count only real saves, report rejections"
```

---

## Task 8: Set a sensible paper-account default and document the knob

**Why:** With Task 3, exposure is measured against `riskStore.limits.portfolioValue`. To keep normal option trades from bouncing on a fresh install, set the default to a realistic paper-account size and document that all exposure caps are fractions of this value. Decision is fixed here (no interactive confirmation — the plan is executed by a subagent): **default = 100000**, user-editable in Settings.

**Files:**
- Modify: `frontend/lib/riskStore.ts` (`DEFAULT_LIMITS` `:14-20`)

- [ ] **Step 1: Update the default + add the doc comment**

In `frontend/lib/riskStore.ts`, above `DEFAULT_LIMITS`:

```typescript
// portfolioValue is the account size the risk checks measure exposure against.
// It is user-editable in Settings; this is only the first-run default. Exposure
// caps (maxSingleTradeExposurePct etc.) are fractions of THIS value, so a value
// far below the real paper balance will reject otherwise-normal option trades.
```

Change `portfolioValue: 50000,` to `portfolioValue: 100000,`.

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run typecheck`
Expected: clean.
```bash
git add frontend/lib/riskStore.ts
git commit -m "chore(risk): default paper account value to 100k; document it as the exposure basis"
```

---

## Task 9: Full verification pass

- [ ] **Step 1: Backend tests**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 2: Frontend tests + typecheck**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: typecheck clean, all Jest PASS.

- [ ] **Step 3: Live end-to-end check (browser)**

Preconditions: backend up (`uvicorn app.main:app`, port 8000) AND reachable — confirm first, because the phantom-drop only happens on a successful GET:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/api/portfolio   # must be 200
```

1. Open `localhost:3001/portfolio`. After the first successful sync the 8 phantom positions are **gone** (backend has 0 rows; Task 2 tagged them `synced, syncedAt=0`; Task 5 drops them).
2. Run a scan → Step 7 → add a normal-size option. Confirm it appears AND is in the backend:
   ```bash
   curl -s http://localhost:8000/api/portfolio | python -m json.tool
   docker exec tradingassistant-db psql -U bamendjou -d TradingAssistantDB -c "SELECT rec_id, symbol, contract FROM portfolio_positions;"
   ```
   Both must show the new position.
3. Force a rejection: set the account value low in Settings (or add a very large position) so the backend returns 422. Confirm the Portfolio page shows the red rejection banner and the position is **not** in the DB.
4. Confirm no alert email fires for a position not in the DB:
   ```bash
   curl -s -X POST http://localhost:8000/api/alerts/notify -H "Content-Type: application/json" \
     -d '{"symbol":"ABT","alertType":"STOP_REACHED","reason":"x","recId":"REC-GHOST"}'
   ```
   Expected: `{"sent": false, "reason": "position_not_found"}`.

- [ ] **Step 4: Report** the verification output to the user (tests + the four live checks).

---

## Notes / deliberate non-goals

- **The 5% single-trade cap is intentionally unchanged.** The ABT rejection was a wrong *input* (account value), not a wrong rule.
- **Existing phantom cleanup needs no separate script** — Task 2's migration + Task 5's reconcile clear the 8 rows on the next successful `/portfolio` load.
- **Close-boundary alert suppression (Task 1) is intended** — an alert firing exactly as a position closes on the backend is dropped; the monitor still covers genuine open positions.
- **Broker↔persistence consistency:** single-order buttons already abort persistence on a broker failure (the ABT 502 case); the basket path never calls the broker. No further change needed unless a future change routes the basket through the broker, in which case apply "persist only on broker success for auto-send".
