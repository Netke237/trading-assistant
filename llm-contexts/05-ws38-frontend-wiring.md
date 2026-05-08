---
workstream: WS-38
branch: feat/ws-38-frontend-wiring
phase: 2
depends_on: WS-34 AND WS-35 (both must be merged to main)
conflict_class: Infrastructure — modifies Zustand stores and multiple screen pages. Must not change store interface signatures.
---

# WS-38: Frontend–Backend Full Wiring

## Mission

Replace mock-driven portfolio, watchlist, and dashboard data with real `fetch()` calls to the FastAPI backend (now live after WS-34 and WS-35). Wire Step 1 universe selection through RunScanButton to `POST /api/scan`, wire Step 7 trade approvals to `POST /api/portfolio` + `logAudit` on both auto-send and manual paths, and add `syncFromBackend()` actions to portfolioStore and watchlistStore so state survives page refresh.

**PRD coverage:** B5, G6, FR-34, FR-43 (dashboard)

---

## Owned Files

| File | Action | Purpose |
|---|---|---|
| `frontend/lib/portfolioStore.ts` | Modify | Add `syncFromBackend()` action — fetch `GET /api/portfolio` on init |
| `frontend/lib/watchlistStore.ts` | Modify | Add `syncFromBackend()` action — fetch `GET /api/watchlist` on init |
| `frontend/lib/api.ts` | Modify | Update `postScan()` to include price/cap filter params in request body |
| `frontend/components/organisms/RunScanButton/index.tsx` | Modify | Send `[pick]` for presets, `parsedSymbols` for custom; pass price/cap filters |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | Modify | Wire approval to `POST /api/portfolio`; fire `logAudit` on ALL paths |
| `frontend/app/(frame)/dashboard/page.tsx` | Modify | Wire to `GET /api/portfolio` for real P&L and risk status |
| `frontend/app/(frame)/portfolio/page.tsx` | Modify | Wire to `GET /api/portfolio` instead of portfolioStore mock |
| `frontend/app/(frame)/watchlist/page.tsx` | Modify | Wire `WatchStar` adds/removes to `POST/DELETE /api/watchlist` |
| `frontend/e2e/tests/screener-steps-1-3.spec.ts` | Modify | Update to reflect wired Step 1 |

**Do NOT touch any other files.**

---

## Read-Only References

Read these for patterns — do not modify:

- `frontend/lib/portfolioStore.ts` — current `PortfolioStoreState` interface and action signatures
- `frontend/lib/watchlistStore.ts` — current `WatchlistState` interface and action signatures
- `frontend/lib/universeStore.ts` — `pick`, `parsedSymbols`, `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, `capUnit`
- `frontend/lib/scanStore.ts` — `ScanContext`, `ScanResult` types; `setScanResult`, `setScanState`
- `frontend/lib/api.ts` — existing `postScan()`, `api.getPortfolio()`, `api.getWatchlist()` function shapes
- `backend/app/routers/portfolio.py` (after WS-34) — endpoint shapes: GET list, POST create, DELETE by rec_id
- `backend/app/routers/watchlist.py` (after WS-34) — endpoint shapes: GET list[str], POST {symbol}, DELETE /{symbol}
- `backend/app/services/audit.py` (after WS-34) — `log_approval(rec_id, trade_card_data, db)`, `log_rejection(rec_id, reason, db)`
- `frontend/types/domain.ts` — `PortfolioPosition`, `WatchlistRow`, `TradeCardData` type definitions

---

## Integration Constraints

### 1. `syncFromBackend()` for portfolioStore

Add this action to `PortfolioStoreState` — it fetches from backend, falls back to localStorage on any failure:

```typescript
type BackendPosition = {
  id: string;
  recId: string;
  symbol: string;
  contract: string;
  direction: string;
  entryPrice: number;
  qty: number;
  entryDate: string;
  stop: number | null;
  targets: TargetLevel[];
  dteTotal: number | null;
  createdAt: string;
};

const fromBackend = (p: BackendPosition): PortfolioPosition => ({
  symbol: p.symbol,
  contract: p.contract,
  direction: p.direction as Direction,
  entryPrice: p.entryPrice,
  qty: p.qty,
  entryDate: p.entryDate,
  stop: p.stop ?? undefined,
  targets: p.targets ?? [],
  dteTotal: p.dteTotal ?? undefined,
  recId: p.recId,
  currentPrice: 0,
  pnlDollar: 0,
  pnlPct: 0,
  dteRemaining: 0,
});

syncFromBackend: async () => {
  try {
    const res = await fetch('/api/portfolio');
    if (!res.ok) return;  // keep localStorage state as fallback
    const positions: BackendPosition[] = await res.json();
    set({ positions: positions.map(fromBackend) });
  } catch {
    // network unavailable — keep localStorage state
  }
}
```

Call `syncFromBackend()` after store hydration. The simplest approach: call it from a `useEffect` in the root frame layout (`frontend/app/(frame)/layout.tsx`). Do NOT modify `onRehydrateStorage` — just add a one-time effect.

### 2. `syncFromBackend()` for watchlistStore

```typescript
syncFromBackend: async () => {
  try {
    const res = await fetch('/api/watchlist');
    if (!res.ok) return;
    const symbols: string[] = await res.json();
    set({ added: symbols.map(s => s.toUpperCase()) });
  } catch {
    // network unavailable — keep localStorage state
  }
}
```

Same pattern: call from root layout `useEffect`, keep localStorage as fallback.

### 3. RunScanButton — universe wiring

The backend `POST /api/scan` accepts `universe: list[str]`. WS-35 handles preset expansion server-side. So:

- **Presets**: send `[universeStore.pick]` (e.g. `["NDX100"]`)
- **Custom**: send `universeStore.parsedSymbols` (already a `string[]`)

**Do NOT expand presets client-side.** The backend does this.

Also pass price/cap filters in the scan body:

```typescript
const body: Record<string, unknown> = {
  universe: pick === 'Custom' ? parsedSymbols : [pick],
  direction,
  horizon,
};

// Add price/cap filters if set
const minPrice = universeStore.minPriceRaw;
const maxPrice = universeStore.maxPriceRaw;
const minCapRaw = universeStore.minCapRaw;
const maxCapRaw = universeStore.maxCapRaw;
if (minPrice !== null) body.min_price = minPrice;
if (maxPrice !== null) body.max_price = maxPrice;
// Convert cap to USD if unit is B (billions)
const capMultiplier = universeStore.capUnit === 'B' ? 1e9 : 1;
if (minCapRaw !== null) body.min_cap_usd = minCapRaw * capMultiplier;
if (maxCapRaw !== null) body.max_cap_usd = maxCapRaw * capMultiplier;
```

### 4. `api.ts` — update `postScan` signature

The function must accept an expanded payload. Change the body from `{ universe, direction, horizon, overrides: {} }` to include the optional filter fields. The function signature stays the same (`(universe, direction, horizon)`), but the body object sent to the backend is richer.

### 5. Step 7 trade card — approval wiring

`logAudit` from `frontend/lib/audit.ts` must fire on **BOTH** paths:

- **Auto-send** (auto-trading enabled): `POST /api/portfolio` → on success, `logAudit(recId, 'approval', tradeCardData)`
- **Manual approval**: same sequence — `POST /api/portfolio` → `logAudit(recId, 'approval', tradeCardData)`

The `POST /api/portfolio` body must match the `PortfolioPositionCreate` schema from WS-34:
```typescript
{
  recId: string;
  symbol: string;
  contract: string;       // SYMBOL|STRIKE|EXPIRY|C/P
  direction: string;
  entryPrice: number;
  qty: number;
  entryDate: string;      // ISO date
  stop?: number;
  targets?: TargetLevel[];
  dteTotal?: number;
}
```

### 6. Watchlist wiring

`WatchStar` click handler must call the backend **after** updating the local store:

- **Add**: `POST /api/watchlist` with `{ symbol: "AAPL" }` after `addSymbol()`
- **Remove**: `DELETE /api/watchlist/{symbol}` after `removeSymbol()`

Backend calls are fire-and-forget (no awaiting in UI handlers). Use `fetch()` directly in the handler, wrapped in try-catch to silently ignore network errors.

### 7. PortfolioPosition field parity

The `PortfolioPosition` interface in `types/domain.ts` has these required fields: `symbol`, `contract`, `direction`, `entryDate`, `expiry`, `dteRemaining`, `dteTotal`, `entryPrice`, `currentPrice`, `pnlDollar`, `pnlPct`, `stop`, `targets`, `status`, `recId`.

The `fromBackend()` function sets `currentPrice`, `pnlDollar`, `pnlPct`, `dteRemaining` to 0 (placeholder). These are computed later from real-time market data. Make sure every required field is satisfied — check `types/domain.ts` for the exact list.

---

## CRITICAL WARNING

**Do NOT change any store interface signatures** (field names, action names, parameter types). Other workstreams (WS-37, WS-41) depend on the exact TypeScript interfaces in portfolioStore, watchlistStore, and scanStore. You are only:
- **ADDING** `syncFromBackend()` actions to portfolioStore and watchlistStore
- **MODIFYING** `postScan()` in api.ts to accept richer payloads (backward-compatible)
- **WIRING** fetch calls into page components and the RunScanButton

If you need to change a field name or add a required field to an interface, stop and ask — do not proceed.

---

## Tasks

- [ ] 1. Add `syncFromBackend()` to `portfolioStore.ts` — declare `BackendPosition` type (module-level), implement the `fromBackend` mapper, add `syncFromBackend` to `PortfolioStoreState` interface and implementation. Update `partialize`/`merge` if needed to not clobber backend data with stale localStorage.
- [ ] 2. Add `syncFromBackend()` to `watchlistStore.ts` — add to `WatchlistState` interface and implementation. No interface change needed for backend response shape (it's `string[]`).
- [ ] 3. Call both `syncFromBackend()` functions from a `useEffect` in `frontend/app/(frame)/layout.tsx` (the root frame layout). Call both after mount, handle errors silently.
- [ ] 4. Update `postScan()` in `frontend/lib/api.ts` — add `min_price`, `max_price`, `min_cap_usd`, `max_cap_usd` optional fields to the request body. Function signature can stay `(universe: string[], direction: string, horizon: string, filters?: {...})`.
- [ ] 5. Update `RunScanButton/index.tsx` — import `useUniverseStore` fully (read `parsedSymbols`, `minPriceRaw`, `maxPriceRaw`, `minCapRaw`, `maxCapRaw`, `capUnit`). For `pick === 'Custom'` send `parsedSymbols`; otherwise send `[pick]`. Build the price/cap filter values and pass to `postScan`.
- [ ] 6. Update `step-7-trade-card/page.tsx` — find the approval handler (auto-send and manual). On approval: construct a `POST /api/portfolio` body from the `TradeCardData`, call `fetch('/api/portfolio', { method: 'POST', body: JSON.stringify(body) })`, then call `logAudit(recId, 'approval', tradeCardData)` on success. Do this for **both** auto-send and manual paths. Import `logAudit` from `@/lib/audit`.
- [ ] 7. Update `dashboard/page.tsx` — call `usePortfolioStore().syncFromBackend()` on mount. Render total unrealised P&L (sum of `pnlDollar` across positions) and open position count from store data (not mock data). Keep fallback rendering for when positions is empty.
- [ ] 8. Update `portfolio/page.tsx` — read positions from `usePortfolioStore()` and call `syncFromBackend()` on mount. Remove any mock imports (e.g. from `mocks/portfolio.ts`).
- [ ] 9. Update `watchlist/page.tsx` — read symbols from `useWatchlistStore()` and call `syncFromBackend()` on mount. Wire `WatchStar` click handlers: on add → `POST /api/watchlist { symbol }`, on remove → `DELETE /api/watchlist/{symbol}`. Both fire-and-forget after local store update.
- [ ] 10. Update `frontend/e2e/tests/screener-steps-1-3.spec.ts` — ensure test accounts for the wired Step 1 flow (API call made, UI reflects loading/result states).
- [ ] 11. Run `npm run typecheck` from `frontend/` — clean.

---

## Acceptance Criteria

- [ ] Adding a stock to watchlist in UI → `GET /api/watchlist` returns it on next call (backend persistence)
- [ ] Approving a trade card → `GET /api/portfolio` returns the position after page refresh
- [ ] Dashboard shows non-zero P&L when portfolio has open positions (backend has seed data or a manually added position)
- [ ] `logAudit` called for both auto-send and manual approval paths
- [ ] `npm run typecheck` clean

---

## Handover Prompt (copy-paste to start worker)

```
You are implementing WS-38 (Frontend–Backend Full Wiring) for the Bamendjou options screener.

Working directory: F:\Git\GitHub\Trading assistant
Branch: feat/ws-38-frontend-wiring (create from main — WS-34 and WS-35 must already be merged)
Phase: 2
Depends: WS-34 (Backend Persistence) AND WS-35 (Universe Expansion) — both merged to main

Read the full context doc before writing any code:
  F:\Git\GitHub\Trading assistant\llm-contexts\05-ws38-frontend-wiring.md

Key files to read first (do not modify):
- frontend/lib/portfolioStore.ts — current action signatures you must NOT change
- frontend/lib/watchlistStore.ts — current action signatures you must NOT change
- frontend/lib/universeStore.ts — pick, parsedSymbols, price/cap filter fields
- frontend/lib/api.ts — current postScan signature
- frontend/lib/audit.ts — logAudit function signature
- frontend/types/domain.ts — PortfolioPosition required fields
- backend/app/routers/portfolio.py (after WS-34 merge) — endpoint shapes
- backend/app/routers/watchlist.py (after WS-34 merge) — endpoint shapes

CRITICAL: Do NOT change any store interface signatures (field names, action names).
Only ADD syncFromBackend() and wire fetch calls. Other workstreams depend on these interfaces.

Tasks in order:
1. Add syncFromBackend() to portfolioStore.ts with the exact fromBackend() mapper in the context doc
2. Add syncFromBackend() to watchlistStore.ts
3. Call both syncFromBackend() from root layout useEffect
4. Update api.ts postScan() to accept price/cap filter params
5. Update RunScanButton to send [pick] for presets, parsedSymbols for custom + filter values
6. Wire step-7-trade-card approval: POST /api/portfolio then logAudit() — BOTH auto-send AND manual paths
7. Wire dashboard, portfolio, and watchlist pages to use synced data
8. Update e2e test for Step 1
9. Run: cd frontend && npm run typecheck (must be clean)

Return: one-paragraph summary of what you implemented and the typecheck output.
```
